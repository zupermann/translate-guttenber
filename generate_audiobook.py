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
from cli_utils import notify_telegram, positive_int
from tts_engine import TTSConfig


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
  %(prog)s pride_prejudice_ro.html --tts-engine xtts-ro --speaker-wav narrator.wav --tts-parallel 8
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
        "--tts-engine",
        choices=("piper", "xtts-ro"),
        default="xtts-ro",
        help="TTS backend to use. Default: xtts-ro",
    )
    parser.add_argument(
        "--tts-parallel",
        type=positive_int,
        default=None,
        help="Number of parallel TTS workers. Default: 8 for xtts-ro, 1 for Piper",
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
        "--xtts-bin",
        type=str,
        default="tts-ro",
        help="Path to the XTTS CLI executable. Default: tts-ro",
    )
    parser.add_argument(
        "--speaker-wav",
        type=str,
        default=None,
        help="Reference speaker WAV for xtts-ro. Overrides --voice when provided",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default="costel",
        help="Bundled xtts-ro voice name. Default: costel",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default=None,
        help="xtts-ro model cache directory",
    )
    parser.add_argument(
        "--device",
        type=str,
        default=None,
        help="xtts-ro inference device (for example: cuda or cpu)",
    )
    parser.add_argument(
        "--tts-temperature",
        type=float,
        default=0.3,
        help="xtts-ro temperature. Default: 0.3",
    )
    parser.add_argument(
        "--tts-top-p",
        type=float,
        default=0.7,
        help="xtts-ro top-p sampling threshold. Default: 0.7",
    )
    parser.add_argument(
        "--tts-top-k",
        type=int,
        default=30,
        help="xtts-ro top-k sampling. Default: 30",
    )
    parser.add_argument(
        "--tts-length-penalty",
        type=float,
        default=0.8,
        help="xtts-ro length penalty. Default: 0.8",
    )
    parser.add_argument(
        "--tts-repetition-penalty",
        type=float,
        default=10.0,
        help="xtts-ro repetition penalty. Default: 10.0",
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

    tts_config = TTSConfig(
        engine=args.tts_engine,
        parallelism=args.tts_parallel,
        piper_bin=args.piper_bin,
        piper_model=args.piper_model,
        piper_config=args.piper_config,
        xtts_bin=args.xtts_bin,
        speaker_wav=args.speaker_wav,
        voice=args.voice,
        cache_dir=args.cache_dir,
        device=args.device,
        xtts_temperature=args.tts_temperature,
        top_p=args.tts_top_p,
        top_k=args.tts_top_k,
        length_penalty=args.tts_length_penalty,
        repetition_penalty=args.tts_repetition_penalty,
    )

    try:
        result = generate_audiobook(
            input_file=args.input_file,
            output_file=args.output,
            checkpoint_path=args.checkpoint,
            tts_config=tts_config,
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
