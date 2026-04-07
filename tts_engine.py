"""Text-to-speech engine wrappers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, Optional

from speech_processor import SpeechChunkingOptions


@dataclass(frozen=True)
class TTSConfig:
    """User-facing configuration for audiobook synthesis."""

    engine: str = "piper"
    parallelism: Optional[int] = None
    piper_bin: str = "piper"
    piper_model: str = "~/piper/models/ro_RO-mihai-medium.onnx"
    piper_config: str = "~/piper/models/ro_RO-mihai-medium.onnx.json"
    xtts_bin: str = "tts-ro"
    speaker_wav: Optional[str] = None
    voice: Optional[str] = "costel"
    cache_dir: Optional[str] = None
    device: Optional[str] = None
    xtts_temperature: float = 0.3
    top_p: float = 0.7
    top_k: int = 30
    length_penalty: float = 0.8
    repetition_penalty: float = 10.0

    def resolved_parallelism(self) -> int:
        """Return the configured worker count or an engine-specific default."""
        if self.parallelism is not None:
            return max(1, int(self.parallelism))
        return 8 if self.engine in {"xtts", "xtts-ro"} else 1


class TextToSpeechEngine(ABC):
    """Shared interface for CLI-backed TTS engines."""

    engine_name: str
    sample_rate_hz: int
    chunking_options: SpeechChunkingOptions

    @abstractmethod
    def synthesize(self, text: str, output_file: Path) -> None:
        """Render a single speech segment to a WAV file."""

    @abstractmethod
    def checkpoint_config(self) -> Dict[str, Any]:
        """Return resume-critical settings for checkpoint validation."""

    def effective_parallelism(self, requested_parallelism: Optional[int]) -> int:
        """Expose engine-specific default parallelism."""
        if requested_parallelism is not None:
            return max(1, int(requested_parallelism))
        return 1


class PiperTTS(TextToSpeechEngine):
    """Thin wrapper around the Piper CLI."""

    def __init__(self, piper_bin: str, model: str, config: str):
        self.engine_name = "piper"
        self.piper_bin = self._resolve_executable(piper_bin, "Piper")
        self.model = self._resolve_file(model, "Piper model")
        self.config = self._resolve_file(config, "Piper config")
        self.sample_rate_hz = self._read_sample_rate(self.config)
        self.chunking_options = SpeechChunkingOptions()

    def synthesize(self, text: str, output_file: Path) -> None:
        """Synthesize a single WAV file for the provided text."""
        output_file.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.piper_bin,
            "--model",
            str(self.model),
            "--config",
            str(self.config),
            "--output_file",
            str(output_file),
        ]

        try:
            subprocess.run(
                cmd,
                input=(text.rstrip() + "\n").encode("utf-8"),
                check=True,
                capture_output=True,
            )
        except subprocess.CalledProcessError as exc:
            stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
            stdout = exc.stdout.decode("utf-8", errors="replace") if exc.stdout else ""
            details = stderr.strip() or stdout.strip() or "unknown Piper error"
            raise RuntimeError(f"Piper synthesis failed for {output_file.name}: {details}") from exc

        if not output_file.exists():
            raise RuntimeError(f"Piper completed without creating output file: {output_file}")

    def checkpoint_config(self) -> Dict[str, Any]:
        """Return Piper settings that affect generated audio."""
        return {
            "piper_bin": self.piper_bin,
            "piper_model": str(self.model),
            "piper_config": str(self.config),
        }

    def _resolve_executable(self, value: str, label: str) -> str:
        path = Path(value).expanduser()
        if path.exists():
            if not path.is_file():
                raise FileNotFoundError(f"{label} path is not a file: {path}")
            if not self._is_executable(path):
                raise FileNotFoundError(f"{label} is not executable: {path}")
            return str(path)

        resolved = shutil.which(value)
        if not resolved:
            raise FileNotFoundError(f"{label} not found: {value}")
        return resolved

    def _resolve_file(self, value: str, label: str) -> Path:
        path = Path(value).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"{label} is not a file: {path}")
        return path

    def _read_sample_rate(self, config_path: Path) -> int:
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError):
            return 22050

        sample_rate = data.get("audio", {}).get("sample_rate")
        if isinstance(sample_rate, int) and sample_rate > 0:
            return sample_rate
        return 22050

    def _is_executable(self, path: Path) -> bool:
        return path.exists() and path.is_file() and path.stat().st_mode & 0o111 != 0


class XTTSRoTTS(TextToSpeechEngine):
    """Wrapper for the Romanian XTTS-v2 CLI."""

    def __init__(
        self,
        *,
        xtts_bin: str = "tts-ro",
        speaker_wav: Optional[str] = None,
        voice: Optional[str] = "costel",
        cache_dir: Optional[str] = None,
        device: Optional[str] = None,
        temperature: float = 0.3,
        top_p: float = 0.7,
        top_k: int = 30,
        length_penalty: float = 0.8,
        repetition_penalty: float = 10.0,
    ):
        self.engine_name = "xtts-ro"
        self.xtts_bin = self._resolve_executable(xtts_bin, "XTTS CLI")
        self.speaker_wav = self._resolve_optional_file(speaker_wav, "XTTS speaker WAV")
        self.voice = voice or "costel"
        self.cache_dir = self._resolve_optional_path(cache_dir)
        self.device = device
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.length_penalty = length_penalty
        self.repetition_penalty = repetition_penalty
        self.sample_rate_hz = 24000
        self.chunking_options = SpeechChunkingOptions(
            split_on_phrase_punctuation=True,
            max_words_per_chunk=60,
            normalize_numbers=True,
            normalize_symbols=True,
        )

    def synthesize(self, text: str, output_file: Path) -> None:
        """Synthesize a single WAV file using the XTTS CLI."""
        output_file.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.xtts_bin,
            "--text",
            text,
            "--output",
            str(output_file),
        ]

        if self.speaker_wav is not None:
            cmd.extend(["--speaker-wav", str(self.speaker_wav)])
        elif self.voice:
            cmd.extend(["--voice", self.voice])

        if self.cache_dir is not None:
            cmd.extend(["--cache-dir", str(self.cache_dir)])
        if self.device:
            cmd.extend(["--device", self.device])

        cmd.extend(
            [
                "--temperature",
                str(self.temperature),
                "--top-p",
                str(self.top_p),
                "--top-k",
                str(self.top_k),
                "--length-penalty",
                str(self.length_penalty),
                "--repetition-penalty",
                str(self.repetition_penalty),
            ]
        )

        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "unknown XTTS CLI error").strip()
            raise RuntimeError(f"XTTS synthesis failed for {output_file.name}: {details}") from exc

        if not output_file.exists():
            raise RuntimeError(f"XTTS completed without creating output file: {output_file}")

    def checkpoint_config(self) -> Dict[str, Any]:
        """Return XTTS settings that affect generated audio."""
        return {
            "xtts_bin": self.xtts_bin,
            "speaker_wav": str(self.speaker_wav) if self.speaker_wav is not None else None,
            "voice": None if self.speaker_wav is not None else self.voice,
            "cache_dir": str(self.cache_dir) if self.cache_dir is not None else None,
            "device": self.device,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "top_k": self.top_k,
            "length_penalty": self.length_penalty,
            "repetition_penalty": self.repetition_penalty,
        }

    def effective_parallelism(self, requested_parallelism: Optional[int]) -> int:
        """XTTS benefits from running several lightweight CLI workers at once."""
        if requested_parallelism is not None:
            return max(1, int(requested_parallelism))
        return 8

    def _resolve_executable(self, value: str, label: str) -> str:
        path = Path(value).expanduser()
        if path.exists():
            if not path.is_file():
                raise FileNotFoundError(f"{label} path is not a file: {path}")
            if not self._is_executable(path):
                raise FileNotFoundError(f"{label} is not executable: {path}")
            return str(path)

        resolved = shutil.which(value)
        if not resolved:
            raise FileNotFoundError(f"{label} not found: {value}")
        return resolved

    def _resolve_optional_file(self, value: Optional[str], label: str) -> Optional[Path]:
        if not value:
            return None
        path = Path(value).expanduser()
        if not path.exists():
            raise FileNotFoundError(f"{label} not found: {path}")
        if not path.is_file():
            raise FileNotFoundError(f"{label} is not a file: {path}")
        return path

    def _resolve_optional_path(self, value: Optional[str]) -> Optional[Path]:
        if not value:
            return None
        return Path(value).expanduser()

    def _is_executable(self, path: Path) -> bool:
        return path.exists() and path.is_file() and path.stat().st_mode & 0o111 != 0


def create_tts_engine(config: TTSConfig) -> TextToSpeechEngine:
    """Instantiate the requested text-to-speech backend."""
    engine = (config.engine or "piper").lower()
    if engine == "piper":
        return PiperTTS(
            piper_bin=config.piper_bin,
            model=config.piper_model,
            config=config.piper_config,
        )
    if engine in {"xtts", "xtts-ro"}:
        return XTTSRoTTS(
            xtts_bin=config.xtts_bin,
            speaker_wav=config.speaker_wav,
            voice=config.voice,
            cache_dir=config.cache_dir,
            device=config.device,
            temperature=config.xtts_temperature,
            top_p=config.top_p,
            top_k=config.top_k,
            length_penalty=config.length_penalty,
            repetition_penalty=config.repetition_penalty,
        )

    raise ValueError(
        f"Unsupported TTS engine: {config.engine}. Expected one of: piper, xtts-ro."
    )
