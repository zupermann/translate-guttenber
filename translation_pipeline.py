"""Shared translation pipeline used by the translation and orchestration CLIs."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Dict

from checkpoint import Checkpoint
from display import Display
from html_processor import Chunk
from pipeline_utils import load_html_processor
from translator import OllamaTranslator, TranslationResult


@dataclass
class TranslationDryRunSummary:
    """Estimated translation workload without calling Ollama."""

    input_file: Path
    total_chunks: int
    estimated_input_tokens: int
    estimated_output_tokens: int
    estimated_seconds: float


@dataclass
class TranslationRunResult:
    """Outcome of a translation pipeline run."""

    input_file: Path
    output_file: Path
    checkpoint_path: Path
    total_chunks: int


def default_translation_output_path(input_file: Path) -> Path:
    """Default translated HTML output path."""
    return input_file.parent / f"{input_file.stem}_ro.html"


def default_translation_checkpoint_path(input_file: Path) -> Path:
    """Default translation checkpoint path."""
    return input_file.parent / f"{input_file.stem}_checkpoint.json"


def estimate_tokens(text: str) -> int:
    """Estimate token count using a word-count heuristic."""
    return int(len(text.split()) * 1.3)


def collect_translation_dry_run(input_file: Path, *, skip_boilerplate: bool = True) -> TranslationDryRunSummary:
    """Compute chunk and token estimates without calling the model."""
    _, chunks = load_html_processor(input_file, skip_boilerplate=skip_boilerplate)
    estimated_input_tokens = sum(estimate_tokens(chunk.plain_text) for chunk in chunks)
    estimated_output_tokens = int(estimated_input_tokens * 1.1)
    estimated_seconds = estimated_input_tokens / 40 if estimated_input_tokens else 0.0

    return TranslationDryRunSummary(
        input_file=input_file,
        total_chunks=len(chunks),
        estimated_input_tokens=estimated_input_tokens,
        estimated_output_tokens=estimated_output_tokens,
        estimated_seconds=estimated_seconds,
    )


def translate_chunk(chunk: Chunk, translator: OllamaTranslator):
    """Translate a single chunk. Used by ThreadPoolExecutor."""
    result = translator.translate(text=chunk.plain_text)
    return chunk, result


def translate_html_book(
    *,
    input_file: Path,
    output_file: Path,
    checkpoint_path: Path,
    model: str = "translategemma:27b",
    ollama_url: str = "http://localhost:11434",
    temperature: float = 0.3,
    num_ctx: int = 8192,
    resume: bool = False,
    debug: bool = False,
    skip_boilerplate: bool = True,
    force: bool = False,
    parallel: int = 2,
) -> TranslationRunResult:
    """Translate a Gutenberg-style HTML file into Romanian."""
    processor, chunks = load_html_processor(input_file, skip_boilerplate=skip_boilerplate)

    checkpoint = Checkpoint(checkpoint_path, input_file, model)
    if resume:
        try:
            loaded = checkpoint.load()
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        if not loaded:
            raise RuntimeError(
                f"Resume requested but no valid checkpoint could be loaded from {checkpoint_path}"
            )

    if output_file.exists() and not force and not resume:
        raise FileExistsError(
            f"Output file already exists: {output_file}. Use --force to overwrite or --resume to continue."
        )

    translations: Dict[int, str] = {}
    pending = [chunk for chunk in chunks if not checkpoint.is_done(chunk.index)]

    translator = OllamaTranslator(
        base_url=ollama_url,
        model=model,
        temperature=temperature,
        num_ctx=num_ctx,
    )

    if pending:
        translator.check_connection()

    display = Display(total_chunks=len(chunks), debug=debug)

    for chunk in chunks:
        if checkpoint.is_done(chunk.index):
            translations[chunk.index] = checkpoint.get_translation(chunk.index)
            display.update_cached(chunk.index)

    shutdown_requested = False
    interrupted = False
    failure_message = None
    executor = ThreadPoolExecutor(max_workers=parallel)

    try:
        pending_iter = iter(pending)
        in_flight = {}

        def submit_next() -> bool:
            chunk = next(pending_iter, None)
            if chunk is None:
                return False
            in_flight[executor.submit(translate_chunk, chunk, translator)] = chunk
            return True

        for _ in range(min(parallel, len(pending))):
            if not submit_next():
                break

        while in_flight:
            done, _ = wait(set(in_flight.keys()), return_when=FIRST_COMPLETED)

            for future in done:
                chunk = in_flight.pop(future)
                try:
                    _, result = future.result()
                except Exception as exc:
                    result = TranslationResult(
                        translated_text=chunk.plain_text,
                        success=False,
                        error_message=str(exc),
                    )

                if not result.success:
                    failure_message = (
                        f"Chunk {chunk.index} failed: {result.error_message}. "
                        "Progress was saved to checkpoint."
                    )
                    shutdown_requested = True
                    break

                translations[chunk.index] = result.translated_text
                checkpoint.save(chunk.index, result.translated_text, len(chunks))
                display.update(
                    chunk_index=chunk.index,
                    element_type=chunk.element_type,
                    source_text=chunk.plain_text,
                    translated_text=result.translated_text,
                    duration=result.duration_seconds,
                    tokens=result.output_tokens,
                )

                submit_next()

            if shutdown_requested:
                break

    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        executor.shutdown(
            wait=not shutdown_requested and not interrupted,
            cancel_futures=shutdown_requested or interrupted,
        )

    if shutdown_requested:
        display.close()
        raise RuntimeError(failure_message or "Translation failed. Progress was saved to checkpoint.")

    try:
        processor.apply_translations(translations)
    except Exception as exc:
        display.close()
        raise RuntimeError(
            f"Cannot apply translations for {input_file.name}: {exc}. Progress was saved to checkpoint."
        ) from exc

    try:
        output_html = processor.serialize()
        with open(output_file, "w", encoding="utf-8") as handle:
            handle.write(output_html)
    except IOError as exc:
        display.close()
        raise RuntimeError(f"Cannot write output file: {output_file}") from exc

    checkpoint.delete()
    display.close()

    return TranslationRunResult(
        input_file=input_file,
        output_file=output_file,
        checkpoint_path=checkpoint_path,
        total_chunks=len(chunks),
    )
