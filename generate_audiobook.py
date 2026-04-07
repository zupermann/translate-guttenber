#!/usr/bin/env python3
"""Audiobook generation CLI for already-translated or narration-ready HTML."""

import argparse
import sys
from pathlib import Path

from audiobook_pipeline import (
    default_audio_checkpoint_path,
    default_audio_output_path,
    generate_audiobook,
)
from cli_utils import notify_telegram


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        description="Generate an audiobook from a narration-ready HTML file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s pride_prejudice_ro.html
  %(prog)s pride_prejudice_ro.html -o pride_prejudice_ro.m4b
  %(prog)s pride_prejudice_ro.html --resume
        """,
    )

    parser.add_argument("input_file", type=Path, help="Path to the translated HTML file")
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Final audiobook file path. Default: {input_stem}.m4b",
    )
    parser.add_argument(
        "--checkpoint",
        type=Path,
        default=None,
        help="Path to audio checkpoint JSON file. Default: {input_stem}_audio_checkpoint.json",
    )
    parser.add_argument("--resume", action="store_true", help="Resume from an existing audio checkpoint")
    parser.add_argument(
        "--skip-boilerplate",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Auto-detect and skip Gutenberg header/footer boilerplate (default: --skip-boilerplate)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite output file without prompting")
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

    if args.output is None:
        args.output = default_audio_output_path(args.input_file)

    if args.checkpoint is None:
        args.checkpoint = default_audio_checkpoint_path(args.input_file)

    if args.resume and not args.checkpoint.exists() and args.output.exists():
        print(f"Audiobook already complete: {args.output}", file=sys.stderr)
        return 0

    try:
        result = generate_audiobook(
            input_file=args.input_file,
            output_file=args.output,
            checkpoint_path=args.checkpoint,
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
        notify_telegram(f"Audiobook PAUSED: {args.input_file.name} interrupted. Resume with --resume.")
        return 130
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        notify_telegram(
            f"Audiobook FAILED: {args.input_file.name} could not be rendered: {exc}. Resume with --resume after fixing the issue."
        )
        return 1

    print(f"Audiobook complete: {result.output_file}", file=sys.stderr)
    notify_telegram(f"Audiobook COMPLETE: {args.input_file.name} -> {result.output_file.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
