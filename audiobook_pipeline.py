"""Shared audiobook pipeline used by the audio and orchestration CLIs."""

from dataclasses import dataclass
from pathlib import Path
import shutil
import sys

from audio_builder import AudioBuilder
from audio_checkpoint import AudioCheckpoint
from pipeline_utils import load_html_processor
from speech_processor import SpeechProcessor
from tts_engine import PiperTTS


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
    piper_bin: str = "piper",
    piper_model: str = "~/piper/models/ro_RO-mihai-medium.onnx",
    piper_config: str = "~/piper/models/ro_RO-mihai-medium.onnx.json",
    ffmpeg_bin: str = "ffmpeg",
    resume: bool = False,
    skip_boilerplate: bool = True,
    force: bool = False,
    keep_audio_segments: bool = False,
    heading_pause_seconds: float = 0.75,
) -> AudiobookRunResult:
    """Generate an audiobook from a narration-ready HTML file."""
    _, chunks = load_html_processor(input_file, skip_boilerplate=skip_boilerplate)
    speech_chunks = SpeechProcessor().build_speech_chunks_from_source(chunks)

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

    tts = PiperTTS(piper_bin=piper_bin, model=piper_model, config=piper_config)
    audio_builder = AudioBuilder(ffmpeg_bin=ffmpeg_bin)
    segments_dir = default_segments_dir(output_file)
    segments_dir.mkdir(parents=True, exist_ok=True)
    pause_segment_path = segments_dir / f".heading_pause_{int(heading_pause_seconds * 1000)}ms.wav"
    if heading_pause_seconds > 0:
        audio_builder.create_silence_wav(pause_segment_path, heading_pause_seconds)

    checkpoint.configure(
        piper_bin=tts.piper_bin,
        piper_model=str(tts.model),
        piper_config=str(tts.config),
        ffmpeg_bin=audio_builder.ffmpeg_bin,
        segments_dir=segments_dir,
        output_file=output_file,
        total_segments=len(speech_chunks),
    )

    segment_files = []
    try:
        for speech_chunk in speech_chunks:
            stored_path = checkpoint.get_segment_path(speech_chunk.index)
            segment_path = Path(stored_path) if stored_path else segments_dir / f"{speech_chunk.index:05d}.wav"

            if checkpoint.is_done(speech_chunk.index, speech_chunk.text):
                segment_files.append(segment_path)
            else:
                tts.synthesize(speech_chunk.text, segment_path)
                checkpoint.save(speech_chunk.index, segment_path, speech_chunk.text, len(speech_chunks))
                segment_files.append(segment_path)

            print(
                f"Generating audio: {len(segment_files)}/{len(speech_chunks)} segments ready",
                file=sys.stderr,
                end="\r",
            )

            if speech_chunk.pause_after_seconds > 0 and heading_pause_seconds > 0:
                segment_files.append(pause_segment_path)
    finally:
        print(file=sys.stderr)

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
