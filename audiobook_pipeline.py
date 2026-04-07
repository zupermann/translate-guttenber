"""Shared audiobook pipeline used by the audio and orchestration CLIs."""

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
import shutil
import sys

from audio_builder import AudioBuilder
from audio_checkpoint import AudioCheckpoint
from pipeline_utils import load_html_processor
from speech_processor import SpeechProcessor
from tts_engine import TTSConfig, create_tts_engine


@dataclass
class AudiobookRunResult:
    """Outcome of an audiobook generation run."""

    input_file: Path
    output_file: Path
    checkpoint_path: Path
    segments_dir: Path
    total_segments: int


def default_audio_output_path(input_file: Path) -> Path:
    """Default audiobook output path for an HTML input."""
    return input_file.with_suffix(".m4b")


def default_audio_checkpoint_path(input_file: Path) -> Path:
    """Default audiobook checkpoint path for an HTML input."""
    return input_file.parent / f"{input_file.stem}_audio_checkpoint.json"


def default_segments_dir(output_file: Path) -> Path:
    """Directory that holds per-chunk WAV files during synthesis."""
    return output_file.parent / f"{output_file.stem}_segments"


def generate_audiobook(
    *,
    input_file: Path,
    output_file: Path,
    checkpoint_path: Path,
    tts_config: TTSConfig,
    ffmpeg_bin: str = "ffmpeg",
    resume: bool = False,
    skip_boilerplate: bool = True,
    force: bool = False,
    keep_audio_segments: bool = False,
    heading_pause_seconds: float = 0.75,
) -> AudiobookRunResult:
    """Generate an audiobook from a narration-ready HTML file."""
    tts = create_tts_engine(tts_config)
    chunking_options = replace(tts.chunking_options, heading_pause_seconds=heading_pause_seconds)

    _, chunks = load_html_processor(input_file, skip_boilerplate=skip_boilerplate)
    speech_chunks = SpeechProcessor().build_speech_chunks_from_source(
        chunks,
        options=chunking_options,
    )

    if not speech_chunks:
        raise ValueError("No narratable chunks were produced from the HTML input")

    if output_file.exists() and not force and not resume:
        raise FileExistsError(
            f"Audio output file already exists: {output_file}. Use --force to overwrite or --resume to continue."
        )

    checkpoint = AudioCheckpoint(checkpoint_path, input_file)
    if resume:
        try:
            loaded = checkpoint.load()
        except ValueError as exc:
            raise RuntimeError(str(exc)) from exc

        if not loaded:
            raise RuntimeError(
                f"Resume requested but no valid audio checkpoint could be loaded from {checkpoint_path}"
            )

    audio_builder = AudioBuilder(ffmpeg_bin=ffmpeg_bin)
    segments_dir = default_segments_dir(output_file)
    segments_dir.mkdir(parents=True, exist_ok=True)

    checkpoint.configure(
        tts_engine=tts.engine_name,
        tts_config=tts.checkpoint_config(),
        ffmpeg_bin=audio_builder.ffmpeg_bin,
        segments_dir=segments_dir,
        output_file=output_file,
        total_segments=len(speech_chunks),
    )

    rendered_segment_paths: list[Path] = []
    pending_chunks = []
    completed_count = 0

    for speech_chunk in speech_chunks:
        stored_path = checkpoint.get_segment_path(speech_chunk.index)
        segment_path = Path(stored_path) if stored_path else segments_dir / f"{speech_chunk.index:05d}.wav"
        rendered_segment_paths.append(segment_path)

        if checkpoint.is_done(speech_chunk.index, speech_chunk.text):
            completed_count += 1
        else:
            pending_chunks.append(speech_chunk)

    if completed_count:
        print(
            f"Generating audio: {completed_count}/{len(speech_chunks)} segments ready",
            file=sys.stderr,
            end="\r",
        )

    shutdown_requested = False
    interrupted = False
    failure_message = None
    executor = None

    try:
        if pending_chunks:
            worker_count = min(
                tts.effective_parallelism(tts_config.parallelism),
                len(pending_chunks),
            )
            executor = ThreadPoolExecutor(max_workers=worker_count)
            pending_iter = iter(pending_chunks)
            in_flight = {}

            def submit_next() -> bool:
                speech_chunk = next(pending_iter, None)
                if speech_chunk is None:
                    return False
                segment_path = rendered_segment_paths[speech_chunk.index]
                in_flight[executor.submit(tts.synthesize, speech_chunk.text, segment_path)] = speech_chunk
                return True

            for _ in range(worker_count):
                if not submit_next():
                    break

            while in_flight:
                done, _ = wait(set(in_flight.keys()), return_when=FIRST_COMPLETED)

                for future in done:
                    speech_chunk = in_flight.pop(future)
                    try:
                        future.result()
                    except Exception as exc:
                        failure_message = (
                            f"Audio segment {speech_chunk.index} failed: {exc}. "
                            "Progress was saved to checkpoint."
                        )
                        shutdown_requested = True
                        break

                    segment_path = rendered_segment_paths[speech_chunk.index]
                    checkpoint.save(
                        speech_chunk.index,
                        segment_path,
                        speech_chunk.text,
                        len(speech_chunks),
                    )
                    completed_count += 1
                    print(
                        f"Generating audio: {completed_count}/{len(speech_chunks)} segments ready",
                        file=sys.stderr,
                        end="\r",
                    )

                    if not shutdown_requested:
                        submit_next()

                if shutdown_requested:
                    break
    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=shutdown_requested or interrupted)
        print(file=sys.stderr)

    if shutdown_requested:
        raise RuntimeError(failure_message or "Audio synthesis failed. Progress was saved to checkpoint.")

    pause_segments = {}
    segment_files = []
    for speech_chunk in speech_chunks:
        segment_files.append(rendered_segment_paths[speech_chunk.index])

        if speech_chunk.pause_after_seconds <= 0:
            continue

        pause_path = _ensure_pause_segment(
            pause_segments,
            audio_builder,
            segments_dir,
            speech_chunk.pause_after_seconds,
            tts.sample_rate_hz,
        )
        segment_files.append(pause_path)

    audio_builder.concat(segment_files, output_file)

    if not keep_audio_segments:
        shutil.rmtree(segments_dir, ignore_errors=True)

    checkpoint.delete()

    return AudiobookRunResult(
        input_file=input_file,
        output_file=output_file,
        checkpoint_path=checkpoint_path,
        segments_dir=segments_dir,
        total_segments=len(speech_chunks),
    )


def _ensure_pause_segment(
    cache: dict[tuple[int, int], Path],
    audio_builder: AudioBuilder,
    segments_dir: Path,
    duration_seconds: float,
    sample_rate_hz: int,
) -> Path:
    duration_ms = max(1, int(round(duration_seconds * 1000)))
    key = (duration_ms, sample_rate_hz)
    if key in cache and cache[key].exists():
        return cache[key]

    pause_path = segments_dir / f".pause_{duration_ms}ms_{sample_rate_hz}hz.wav"
    if not pause_path.exists():
        audio_builder.create_silence_wav(
            pause_path,
            duration_seconds,
            sample_rate=sample_rate_hz,
        )
    cache[key] = pause_path
    return pause_path
