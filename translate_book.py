#!/usr/bin/env python3
"""
Book Translation CLI - Translate Project Gutenberg books from English to Romanian.

A Python CLI tool that translates Project Gutenberg books from English to Romanian
using a local Ollama TranslateGemma model. The tool accepts an HTML source file,
translates all human-readable text while preserving the complete HTML structure,
and writes a translated HTML output file.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict

from html_processor import HTMLProcessor, DELIMITER
from translator import OllamaTranslator
from checkpoint import Checkpoint
from display import Display
from boilerplate import mark_boilerplate


def notify_telegram(message: str) -> None:
    """Send a Telegram notification using the system alias."""
    try:
        subprocess.run(
            [os.path.expanduser('~/.local/bin/telegram-notify'), message],
            shell=False,
            check=False,
            capture_output=True
        )
    except Exception:
        # Silently ignore notification failures - don't block translation
        pass


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Translate Project Gutenberg books from English to Romanian.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s pg1342.html
  %(prog)s pg1342.html -o pride_prejudice_ro.html --debug
  %(prog)s pg1342.html --resume
  %(prog)s pg1342.html --dry-run
        """
    )

    parser.add_argument(
        "input_file",
        type=Path,
        help="Path to the source HTML file"
    )

    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=None,
        help="Output HTML file path. Default: {input_stem}_ro.html in the same directory"
    )

    parser.add_argument(
        "--model", "-m",
        type=str,
        default="translategemma:27b",
        help="Ollama model name. Default: translategemma:27b"
    )

    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama base URL. Default: http://localhost:11434"
    )

    parser.add_argument(
        "--temperature",
        type=float,
        default=0.3,
        help="Temperature for translation. Default: 0.3"
    )

    parser.add_argument(
        "--num-ctx",
        type=int,
        default=8192,
        help="Context window size. Default: 8192"
    )

    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Path to checkpoint JSON file. Default: {input_stem}_checkpoint.json"
    )

    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from existing checkpoint if present"
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode: log source and translation side-by-side to stderr"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count chunks, print stats, do not call the model"
    )

    parser.add_argument(
        "--skip-boilerplate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-detect and skip Gutenberg header/footer boilerplate (default: --skip-boilerplate)"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite output file without prompting"
    )

    return parser


def estimate_tokens(text: str) -> int:
    """Estimate token count using word count heuristic."""
    return int(len(text.split()) * 1.3)


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    # 1. Validate input file exists and is HTML
    if not args.input_file.exists():
        print(f"Error: Input file not found: {args.input_file}", file=sys.stderr)
        return 1

    if not args.input_file.is_file():
        print(f"Error: Input path is not a file: {args.input_file}", file=sys.stderr)
        return 1

    if args.input_file.suffix.lower() not in ('.html', '.htm'):
        print(f"Warning: Input file does not have .html/.htm extension: {args.input_file}", file=sys.stderr)

    # Compute input stem once for reuse
    input_stem = args.input_file.stem

    # 2. Resolve output path (default: same dir, _ro suffix)
    if args.output is None:
        output_name = f"{input_stem}_ro.html"
        args.output = args.input_file.parent / output_name

    # 3. Resolve checkpoint path
    if args.checkpoint is None:
        checkpoint_name = f"{input_stem}_checkpoint.json"
        args.checkpoint = args.input_file.parent / checkpoint_name

    # 4. Initialize OllamaTranslator and check_connection()
    translator = OllamaTranslator(
        base_url=args.ollama_url,
        model=args.model,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
    )

    if not args.dry_run:
        try:
            translator.check_connection()
        except ConnectionError as e:
            msg = f"Translation failed: Ollama connection error for {args.input_file.name}"
            print(f"Error: {e}", file=sys.stderr)
            notify_telegram(msg)
            return 1
        except ValueError as e:
            msg = f"Translation failed: Model error for {args.input_file.name}"
            print(f"Error: {e}", file=sys.stderr)
            notify_telegram(msg)
            return 1

    # 5. Read input HTML
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
    except IOError as e:
        msg = f"Translation failed: Cannot read {args.input_file.name}"
        print(f"Error reading input file: {e}", file=sys.stderr)
        notify_telegram(msg)
        return 1

    # 6. Process HTML
    processor = HTMLProcessor(html_content)

    # 6b. Run boilerplate.mark_boilerplate(soup)
    if args.skip_boilerplate:
        mark_boilerplate(processor.get_soup())

    # 7. Run processor.extract_chunks() -> chunks list
    chunks = processor.extract_chunks()

    # 8. If --dry-run: print stats and exit
    if args.dry_run:
        total_est_tokens = sum(estimate_tokens(chunk.plain_text) for chunk in chunks)
        est_output_tokens = int(total_est_tokens * 1.1)  # EN->RO expansion
        est_time = total_est_tokens / 40  # Assume 40 tok/s

        print("\nDry run summary")
        print("─" * 40)
        print(f"Source file:      {args.input_file}")
        print(f"Total chunks:     {len(chunks)}")
        print(f"Est. input tok:   {total_est_tokens:,}")
        print(f"Est. output tok:  {est_output_tokens:,}")
        print(f"Est. time @ 40/s: ~{int(est_time // 60)}m {int(est_time % 60)}s")
        print("")
        return 0

    # 9. Load or create Checkpoint
    checkpoint = Checkpoint(args.checkpoint, args.input_file, args.model)
    if args.resume:
        checkpoint.load()

    # 10. Check if output file exists (unless --force or --resume)
    if args.output.exists() and not args.force and not args.resume:
        print(f"Error: Output file already exists: {args.output}", file=sys.stderr)
        print("Use --force to overwrite or --resume to continue from checkpoint.", file=sys.stderr)
        return 1

    # 11. Initialize Display(total=len(chunks), debug=args.debug)
    display = Display(total_chunks=len(chunks), debug=args.debug)

    # 12. Main translation loop
    translations: Dict[int, str] = {}

    try:
        for chunk in chunks:
            # Check if already done in checkpoint
            if checkpoint.is_done(chunk.index):
                translations[chunk.index] = checkpoint.get_translation(chunk.index)
                display.update_cached(chunk.index)
                continue

            # Calculate expected delimiter count
            expected_delimiters = len(chunk.segments) - 1 if chunk.has_inline_tags else 0

            # Translate (with delimiter retry if needed)
            if chunk.has_inline_tags and expected_delimiters > 0:
                result = translator.translate_with_delimiter_retry(
                    text=chunk.plain_text,
                    expected_delimiter_count=expected_delimiters,
                    delimiter=DELIMITER
                )
            else:
                result = translator.translate(
                    text=chunk.plain_text,
                    has_delimiters=False
                )

            # Check for translation failure
            if not result.success:
                print(f"\nWarning: Chunk {chunk.index} translation failed after all retries.", file=sys.stderr)
                print(f"Error: {result.error_message or 'Unknown error'}", file=sys.stderr)
                print(f"Source text kept as-is. Continuing with next chunk.", file=sys.stderr)
                # Still save the result (which is source text) to checkpoint so we don't retry
                translations[chunk.index] = result.translated_text
                checkpoint.save(chunk.index, result.translated_text, len(chunks))
                display.update(
                    chunk_index=chunk.index,
                    element_type=chunk.element_type,
                    source_text=chunk.plain_text,
                    translated_text=result.translated_text,
                    duration=result.duration_seconds,
                    tokens=result.output_tokens
                )
                continue

            translations[chunk.index] = result.translated_text

            # Save checkpoint
            checkpoint.save(chunk.index, result.translated_text, len(chunks))

            # Update display
            display.update(
                chunk_index=chunk.index,
                element_type=chunk.element_type,
                source_text=chunk.plain_text,
                translated_text=result.translated_text,
                duration=result.duration_seconds,
                tokens=result.output_tokens
            )

    except KeyboardInterrupt:
        msg = f"Translation PAUSED: {args.input_file.name} interrupted by user. Resume with --resume."
        print("\n\nInterrupted! Progress has been saved to checkpoint.", file=sys.stderr)
        print(f"Resume with: python {sys.argv[0]} {args.input_file} --resume", file=sys.stderr)
        display.close()
        notify_telegram(msg)
        return 130

    # 13. processor.apply_translations(translations)
    processor.apply_translations(translations)

    # 14. Write output HTML file (UTF-8, update lang="ro")
    try:
        output_html = processor.serialize()
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_html)
    except IOError as e:
        msg = f"Translation FAILED: Cannot write output for {args.input_file.name}"
        print(f"Error writing output file: {e}", file=sys.stderr)
        display.close()
        notify_telegram(msg)
        return 1

    # 15. Delete checkpoint file on successful completion
    checkpoint.delete()

    # Close display and print summary
    display.close()
    print(f"\nTranslation complete: {args.output}", file=sys.stderr)

    # Notify on successful completion
    notify_telegram(f"Translation COMPLETE: {args.input_file.name} -> {args.output.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
