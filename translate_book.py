#!/usr/bin/env python3
"""Translation-only CLI for Project Gutenberg HTML books."""

import argparse
import sys
from pathlib import Path

from cli_utils import notify_telegram, positive_int
from translation_pipeline import (
    collect_translation_dry_run,
    default_translation_checkpoint_path,
    default_translation_output_path,
    translate_html_book,
)


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
        """,
    )

    parser.add_argument("input_file", type=Path, help="Path to the source HTML file")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output HTML file path. Default: {input_stem}_ro.html in the same directory",
    )
    parser.add_argument(
        "--model",
        "-m",
        type=str,
        default="translategemma:27b",
        help="Ollama model name. Default: translategemma:27b",
    )
    parser.add_argument(
        "--ollama-url",
        type=str,
        default="http://localhost:11434",
        help="Ollama base URL. Default: http://localhost:11434",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.3,
        help="Temperature for translation. Default: 0.3",
    )
    parser.add_argument(
        "--num-ctx",
        type=int,
        default=8192,
        help="Context window size. Default: 8192",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Path to checkpoint JSON file. Default: {input_stem}_checkpoint.json",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from existing checkpoint if present")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode: log source and translation side-by-side to stderr",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count chunks, print stats, do not call the model",
    )
    parser.add_argument(
        "--skip-boilerplate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-detect and skip Gutenberg header/footer boilerplate (default: --skip-boilerplate)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite output file without prompting")
    parser.add_argument(
        "--parallel",
        type=positive_int,
        default=2,
        help="Number of parallel translation workers. Default: 2",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.output is None:
        args.output = default_translation_output_path(args.input_file)

    if args.checkpoint is None:
        args.checkpoint = default_translation_checkpoint_path(args.input_file)

    if args.resume and not args.checkpoint.exists() and args.output.exists():
        print(f"Translation already complete: {args.output}", file=sys.stderr)
        return 0

    if args.dry_run:
        try:
            summary = collect_translation_dry_run(
                args.input_file,
                skip_boilerplate=args.skip_boilerplate,
            )
        except (FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1

        print("\nDry run summary")
        print("─" * 40)
        print(f"Source file:      {summary.input_file}")
        print(f"Total chunks:     {summary.total_chunks}")
        print(f"Est. input tok:   {summary.estimated_input_tokens:,}")
        print(f"Est. output tok:  {summary.estimated_output_tokens:,}")
        print(
            f"Est. time @ 40/s: ~{int(summary.estimated_seconds // 60)}m {int(summary.estimated_seconds % 60)}s"
        )
        print("")
        return 0

    try:
        result = translate_html_book(
            input_file=args.input_file,
            output_file=args.output,
            checkpoint_path=args.checkpoint,
            model=args.model,
            ollama_url=args.ollama_url,
            temperature=args.temperature,
            num_ctx=args.num_ctx,
            resume=args.resume,
            debug=args.debug,
            skip_boilerplate=args.skip_boilerplate,
            force=args.force,
            parallel=args.parallel,
        )
    except KeyboardInterrupt:
        print("\nInterrupted! Progress was saved to checkpoint.", file=sys.stderr)
        notify_telegram(f"Translation PAUSED: {args.input_file.name} interrupted. Resume with --resume.")
        return 130
    except (ConnectionError, FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        notify_telegram(f"Translation FAILED: {args.input_file.name} could not be translated: {exc}")
        return 1

    print(f"\nTranslation complete: {result.output_file}", file=sys.stderr)
    notify_telegram(f"Translation COMPLETE: {args.input_file.name} -> {result.output_file.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
