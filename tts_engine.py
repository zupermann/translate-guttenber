"""Piper-based text-to-speech synthesis."""

from pathlib import Path
import shutil
import subprocess


class PiperTTS:
    """Thin wrapper around the Piper CLI."""

    def __init__(self, piper_bin: str, model: str, config: str):
        self.piper_bin = self._resolve_executable(piper_bin, "Piper")
        self.model = self._resolve_file(model, "Piper model")
        self.config = self._resolve_file(config, "Piper config")

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

    def _is_executable(self, path: Path) -> bool:
        return path.exists() and path.is_file() and path.stat().st_mode & 0o111 != 0
