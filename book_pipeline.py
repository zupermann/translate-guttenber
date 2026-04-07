#!/usr/bin/env python3
"""Orchestrator CLI that translates an HTML book and then generates its audiobook."""

import argparse
import sys
from pathlib import Path

from audiobook_pipeline import (
    default_audio_checkpoint_path,
    default_audio_output_path,
    generate_audiobook,
)
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
        description="Translate a book HTML file and generate its audiobook.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s pg8492-images.html
  %(prog)s pg8492-images.html --resume
  %(prog)s pg8492-images.html --translation-output book_ro.html --audio-output book_ro.m4b
        """,
    )

    parser.add_argument("input_file", type=Path, help="Path to the source HTML file")
    parser.add_argument(
        "--translation-output",
        type=Path,
        default=None,
        help="Translated HTML file path. Default: {input_stem}_ro.html",
    )
    parser.add_argument(
        "--audio-output",
        type=Path,
        default=None,
        help="Final audiobook file path. Default: {translated_stem}.m4b",
    )
    parser.add_argument(
        "--translation-checkpoint",
        type=Path,
        default=None,
        help="Path to translation checkpoint JSON file. Default: {input_stem}_checkpoint.json",
    )
    parser.add_argument(
        "--audio-checkpoint",
        type=Path,
        default=None,
        help="Path to audio checkpoint JSON file. Default: {translated_stem}_audio_checkpoint.json",
    )
    parser.add_argument("--resume", action="store_true", help="Resume translation and/or audio from checkpoints")
    parser.add_argument("--debug", action="store_true", help="Enable translation debug logging to stderr")
    parser.add_argument("--dry-run", action="store_true", help="Estimate translation work and exit")
    parser.add_argument(
        "--skip-boilerplate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-detect and skip Gutenberg header/footer boilerplate (default: --skip-boilerplate)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite outputs without prompting")
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
        "--parallel",
        type=positive_int,
        default=2,
        help="Number of parallel translation workers. Default: 2",
    )
    parser.add_argument(
        "--piper-bin",
        type=str,
        default="piper",
        help="Path to Piper executable. Default: piper",
    )
    parser.add_argument(
        "--piper-model",
        type=str,
        default="~/piper/models/ro_RO-mihai-medium.onnx",
        help="Path to Piper voice model. Default: ~/piper/models/ro_RO-mihai-medium.onnx",
    )
    parser.add_argument(
        "--piper-config",
        type=str,
        default="~/piper/models/ro_RO-mihai-medium.onnx.json",
        help="Path to Piper model config. Default: ~/piper/models/ro_RO-mihai-medium.onnx.json",
    )
    parser.add_argument(
        "--ffmpeg-bin",
        type=str,
        default="ffmpeg",
        help="Path to ffmpeg executable. Default: ffmpeg",
    )
    parser.add_argument(
        "--keep-audio-segments",
        action="store_true",
        help="Keep per-chunk WAV files after audiobook assembly",
    )
    parser.add_argument(
        "--heading-pause-seconds",
        type=float,
        default=0.75,
        help="Pause to insert after heading chunks. Default: 0.75",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = build_parser()
    args = parser.parse_args()

    if args.translation_output is None:
        args.translation_output = default_translation_output_path(args.input_file)

    if args.audio_output is None:
        args.audio_output = default_audio_output_path(args.translation_output)

    if args.translation_checkpoint is None:
        args.translation_checkpoint = default_translation_checkpoint_path(args.input_file)

    if args.audio_checkpoint is None:
        args.audio_checkpoint = default_audio_checkpoint_path(args.translation_output)

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

    translated_html = args.translation_output

    if args.resume and translated_html.exists() and not args.translation_checkpoint.exists():
        print(f"Translation already complete: {translated_html}", file=sys.stderr)
    else:
        try:
            translation_result = translate_html_book(
                input_file=args.input_file,
                output_file=translated_html,
                checkpoint_path=args.translation_checkpoint,
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
            print("\nInterrupted! Translation progress was saved to checkpoint.", file=sys.stderr)
            notify_telegram(f"Pipeline PAUSED: {args.input_file.name} interrupted during translation. Resume with --resume.")
            return 130
        except (ConnectionError, FileNotFoundError, ValueError, RuntimeError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            notify_telegram(f"Pipeline FAILED: {args.input_file.name} translation error: {exc}")
            return 1

        translated_html = translation_result.output_file
        print(f"\nTranslation complete: {translated_html}", file=sys.stderr)

    if args.resume and args.audio_output.exists() and not args.audio_checkpoint.exists():
        print(f"Audiobook already complete: {args.audio_output}", file=sys.stderr)
        return 0

    try:
        audio_result = generate_audiobook(
            input_file=translated_html,
            output_file=args.audio_output,
            checkpoint_path=args.audio_checkpoint,
            piper_bin=args.piper_bin,
            piper_model=args.piper_model,
            piper_config=args.piper_config,
            ffmpeg_bin=args.ffmpeg_bin,
            resume=args.resume,
            skip_boilerplate=args.skip_boilerplate,
            force=args.force,
            keep_audio_segments=args.keep_audio_segments,
            heading_pause_seconds=args.heading_pause_seconds,
        )
    except KeyboardInterrupt:
        print("\nInterrupted! Audio progress was saved to checkpoint.", file=sys.stderr)
        notify_telegram(f"Pipeline PAUSED: {args.input_file.name} interrupted during audio generation. Resume with --resume.")
        return 130
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        notify_telegram(f"Pipeline FAILED: {args.input_file.name} audio error: {exc}")
        return 1

    print(f"Audiobook complete: {audio_result.output_file}", file=sys.stderr)
    notify_telegram(
        f"Pipeline COMPLETE: {args.input_file.name} -> {translated_html.name} + {audio_result.output_file.name}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
