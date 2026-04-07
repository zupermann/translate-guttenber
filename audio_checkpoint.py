"""Checkpoint read/write for resumable audiobook generation."""

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set


class AudioCheckpoint:
    """Manage audiobook synthesis checkpoints for resumable processing."""

    def __init__(self, path: Path, source_file: Path):
        self.path = path
        self.source_file = source_file
        self.source_hash = self._hash_file(source_file)
        self.data: Dict = {
            "source_file": str(source_file),
            "source_hash": self.source_hash,
            "piper_bin": None,
            "piper_model": None,
            "piper_config": None,
            "ffmpeg_bin": None,
            "segments_dir": None,
            "output_file": None,
            "total_segments": 0,
            "completed": [],
            "segments": {},
            "last_updated": None,
        }
        self._completed_set: Set[int] = set()
        self._lock = threading.Lock()

    def load(self) -> bool:
        """Load an existing checkpoint from disk."""
        if not self.path.exists():
            return False

        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded_data = json.load(handle)
        except (json.JSONDecodeError, IOError) as exc:
            print(f"Warning: Failed to load audio checkpoint: {exc}")
            return False

        if loaded_data.get("source_hash") != self.source_hash:
            raise ValueError(
                "Source file has changed since the audio checkpoint was created. "
                f"Checkpoint: {self.path}. Start a fresh audio run instead."
            )

        self.data = self._normalize_loaded_data(loaded_data)
        self._completed_set = set(self.data.get("completed", []))
        return True

    def configure(
        self,
        *,
        piper_bin: str,
        piper_model: str,
        piper_config: str,
        ffmpeg_bin: str,
        segments_dir: Path,
        output_file: Path,
        total_segments: int,
    ) -> None:
        """Store audiobook configuration and guard resume compatibility."""
        with self._lock:
            new_state = {
                "piper_bin": str(piper_bin),
                "piper_model": str(piper_model),
                "piper_config": str(piper_config),
                "ffmpeg_bin": str(ffmpeg_bin),
                "segments_dir": str(segments_dir),
                "output_file": str(output_file),
                "total_segments": total_segments,
            }

            if self._completed_set:
                for key, value in new_state.items():
                    existing = self.data.get(key)
                    if existing not in (None, 0) and str(existing) != str(value):
                        raise ValueError(
                            "Audio checkpoint was created with different Piper/ffmpeg settings. "
                            "Resume with the same audio configuration or delete the audio checkpoint."
                        )

            self.data.update(new_state)
            self.data["last_updated"] = datetime.now().isoformat()
            self._write_locked()

    def import_legacy_audio_state(self, legacy_audio: Dict) -> bool:
        """Import embedded pre-refactor audio progress into the standalone checkpoint file."""
        completed = [int(item) for item in legacy_audio.get("completed", [])]
        raw_segments = legacy_audio.get("segments", {})

        if not completed and not raw_segments:
            return False

        normalized_segments = {}
        for key, value in raw_segments.items():
            path = value.get("path") if isinstance(value, dict) else value
            text_hash = value.get("text_hash") if isinstance(value, dict) else None
            if path:
                normalized_segments[str(key)] = {
                    "path": str(path),
                    "text_hash": text_hash,
                }

        with self._lock:
            self.data.update(
                {
                    "piper_bin": legacy_audio.get("piper_bin"),
                    "piper_model": legacy_audio.get("piper_model"),
                    "piper_config": legacy_audio.get("piper_config"),
                    "ffmpeg_bin": legacy_audio.get("ffmpeg_bin"),
                    "segments_dir": legacy_audio.get("segments_dir"),
                    "output_file": legacy_audio.get("output_file"),
                    "total_segments": legacy_audio.get("total_segments", 0),
                    "completed": completed,
                    "segments": normalized_segments,
                    "last_updated": legacy_audio.get("last_updated") or datetime.now().isoformat(),
                }
            )
            self._completed_set = set(completed)
            self._write_locked()

        return True

    def is_done(self, chunk_index: int, text: str) -> bool:
        """Return True if the segment exists on disk and matches the current text."""
        with self._lock:
            if chunk_index not in self._completed_set:
                return False

            entry = self.data.get("segments", {}).get(str(chunk_index))
            if not isinstance(entry, dict):
                return False

            text_hash = entry.get("text_hash")
            if text_hash not in (None, "") and text_hash != self._hash_text(text):
                return False

            segment_path = Path(entry.get("path", ""))
            return segment_path.exists()

    def save(self, chunk_index: int, segment_path: Path, text: str, total_segments: int) -> None:
        """Persist a completed audio segment."""
        with self._lock:
            if chunk_index not in self._completed_set:
                self._completed_set.add(chunk_index)
                self.data["completed"].append(chunk_index)

            self.data.setdefault("segments", {})[str(chunk_index)] = {
                "path": str(segment_path),
                "text_hash": self._hash_text(text),
            }
            self.data["total_segments"] = total_segments
            self.data["last_updated"] = datetime.now().isoformat()
            self._write_locked()

    def get_segment_path(self, chunk_index: int) -> Optional[str]:
        """Return the cached segment path for a chunk if present."""
        with self._lock:
            entry = self.data.get("segments", {}).get(str(chunk_index))
            if isinstance(entry, dict):
                return entry.get("path")
            return None

    def completed_count(self) -> int:
        """Return the number of completed audio segments."""
        with self._lock:
            return len(self._completed_set)

    def delete(self) -> bool:
        """Delete the checkpoint file if it exists."""
        if self.path.exists():
            try:
                self.path.unlink()
                return True
            except OSError:
                return False
        return True

    def get_stats(self) -> Dict:
        """Return checkpoint statistics."""
        total_segments = self.data.get("total_segments", 0)
        completed = self.completed_count()
        return {
            "total_segments": total_segments,
            "completed": completed,
            "percent": (completed / total_segments * 100) if total_segments > 0 else 0,
            "last_updated": self.data.get("last_updated"),
        }

    def _hash_file(self, file_path: Path) -> str:
        if not file_path.exists():
            return ""
        digest = hashlib.sha256()
        with open(file_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
        return f"sha256:{digest.hexdigest()}"

    def _hash_text(self, text: str) -> str:
        digest = hashlib.sha256(text.encode("utf-8"))
        return f"sha256:{digest.hexdigest()}"

    def _normalize_loaded_data(self, loaded_data: Dict) -> Dict:
        data = dict(loaded_data)
        defaults = {
            "source_file": str(self.source_file),
            "source_hash": self.source_hash,
            "piper_bin": None,
            "piper_model": None,
            "piper_config": None,
            "ffmpeg_bin": None,
            "segments_dir": None,
            "output_file": None,
            "total_segments": 0,
            "completed": [],
            "segments": {},
            "last_updated": None,
        }

        for key, value in defaults.items():
            data.setdefault(key, value)

        data["completed"] = [int(item) for item in data.get("completed", [])]
        normalized_segments = {}
        for key, value in data.get("segments", {}).items():
            if isinstance(value, dict):
                normalized_segments[str(key)] = {
                    "path": value.get("path"),
                    "text_hash": value.get("text_hash"),
                }
        data["segments"] = normalized_segments
        return data

    def _write_locked(self) -> None:
        tmp_path = self.path.with_suffix(".tmp")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
            tmp_path.rename(self.path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
