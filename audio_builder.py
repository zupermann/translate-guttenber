"""Final audiobook assembly helpers."""

from pathlib import Path
import shutil
import subprocess
from typing import Sequence


class AudioBuilder:
    """Concatenate synthesized WAV chunks into a final audiobook file."""

    def __init__(self, ffmpeg_bin: str = "ffmpeg"):
        self.ffmpeg_bin = self._resolve_executable(ffmpeg_bin)

    def concat(self, segment_files: Sequence[Path], output_file: Path) -> None:
        """Concatenate segment files into the requested output container."""
        if not segment_files:
            raise ValueError("No audio segments were provided for concatenation")

        output_file.parent.mkdir(parents=True, exist_ok=True)
        manifest_path = self._write_manifest(segment_files, output_file.parent)

        try:
            cmd = [
                self.ffmpeg_bin,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(manifest_path),
            ]
            cmd.extend(self._codec_args(output_file))
            cmd.append(str(output_file))

            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            details = (exc.stderr or exc.stdout or "unknown ffmpeg error").strip()
            raise RuntimeError(f"ffmpeg failed while assembling audiobook: {details}") from exc
        finally:
            if manifest_path.exists():
                manifest_path.unlink(missing_ok=True)

        if not output_file.exists():
            raise RuntimeError(f"ffmpeg completed without creating output file: {output_file}")

    def _codec_args(self, output_file: Path) -> list[str]:
        suffix = output_file.suffix.lower()
        if suffix in {".m4b", ".m4a", ".mp4"}:
            return ["-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart"]
        if suffix == ".mp3":
            return ["-c:a", "libmp3lame", "-q:a", "2"]
        return ["-c:a", "pcm_s16le"]

    def _write_manifest(self, segment_files: Sequence[Path], directory: Path) -> Path:
        manifest_path = directory / f".{directory.name or 'audio'}_concat.txt"
        with open(manifest_path, "w", encoding="utf-8") as handle:
            for segment in segment_files:
                resolved = Path(segment).resolve()
                handle.write(f"file '{self._escape_concat_path(str(resolved))}'\n")
        return manifest_path

    def _escape_concat_path(self, value: str) -> str:
        return value.replace("'", r"'\''")

    def _resolve_executable(self, value: str) -> str:
        path = Path(value).expanduser()
        if path.exists():
            if not path.is_file():
                raise FileNotFoundError(f"ffmpeg path is not a file: {path}")
            if not self._is_executable(path):
                raise FileNotFoundError(f"ffmpeg is not executable: {path}")
            return str(path)

        resolved = shutil.which(value)
        if not resolved:
            raise FileNotFoundError(f"ffmpeg not found: {value}")
        return resolved

    def _is_executable(self, path: Path) -> bool:
        return path.exists() and path.is_file() and path.stat().st_mode & 0o111 != 0
