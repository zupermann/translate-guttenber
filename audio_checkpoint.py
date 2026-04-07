"""Checkpoint read/write for resumable audiobook generation."""

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set


class AudioCheckpoint:
    """Manage audiobook synthesis checkpoints for resumable processing."""

    def __init__(self, path: Path, source_file: Path):
        self.path = path
        self.source_file = source_file
        self.source_hash = self._hash_file(source_file)
        self.data: Dict[str, Any] = self._default_data()
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
        tts_engine: str,
        tts_config: Dict[str, Any],
        ffmpeg_bin: str,
        segments_dir: Path,
        output_file: Path,
        total_segments: int,
    ) -> None:
        """Store audiobook configuration and guard resume compatibility."""
        with self._lock:
            new_state = {
                "tts_engine": str(tts_engine),
                "tts_config": dict(tts_config),
                "piper_bin": tts_config.get("piper_bin"),
                "piper_model": tts_config.get("piper_model"),
                "piper_config": tts_config.get("piper_config"),
                "ffmpeg_bin": str(ffmpeg_bin),
                "segments_dir": str(segments_dir),
                "output_file": str(output_file),
                "total_segments": total_segments,
            }

            if self._completed_set:
                existing_engine = self.data.get("tts_engine")
                existing_config = self.data.get("tts_config") or {}
                if existing_engine not in (None, "", new_state["tts_engine"]):
                    raise ValueError(
                        "Audio checkpoint was created with different TTS/ffmpeg settings. "
                        "Resume with the same audio configuration or delete the audio checkpoint."
                    )
                if existing_config not in ({}, new_state["tts_config"]) and existing_config != new_state["tts_config"]:
                    raise ValueError(
                        "Audio checkpoint was created with different TTS/ffmpeg settings. "
                        "Resume with the same audio configuration or delete the audio checkpoint."
                    )

                for key in ("ffmpeg_bin", "segments_dir", "output_file", "total_segments"):
                    existing = self.data.get(key)
                    if existing not in (None, 0, "") and existing != new_state[key]:
                        raise ValueError(
                            "Audio checkpoint was created with different TTS/ffmpeg settings. "
                            "Resume with the same audio configuration or delete the audio checkpoint."
                        )

            self.data.update(new_state)
            self.data["last_updated"] = datetime.now().isoformat()
            self._write_locked()

    def import_legacy_audio_state(self, legacy_audio: Dict[str, Any]) -> bool:
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

        tts_engine = legacy_audio.get("tts_engine") or "piper"
        tts_config = legacy_audio.get("tts_config")
        if not isinstance(tts_config, dict) or not tts_config:
            tts_config = {
                "piper_bin": legacy_audio.get("piper_bin"),
                "piper_model": legacy_audio.get("piper_model"),
                "piper_config": legacy_audio.get("piper_config"),
            }

        with self._lock:
            self.data.update(
                {
                    "tts_engine": tts_engine,
                    "tts_config": tts_config,
                    "piper_bin": tts_config.get("piper_bin"),
                    "piper_model": tts_config.get("piper_model"),
                    "piper_config": tts_config.get("piper_config"),
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

    def get_stats(self) -> Dict[str, Any]:
        """Return checkpoint statistics."""
        total_segments = self.data.get("total_segments", 0)
        completed = self.completed_count()
        return {
            "total_segments": total_segments,
            "completed": completed,
            "percent": (completed / total_segments * 100) if total_segments > 0 else 0,
            "last_updated": self.data.get("last_updated"),
        }

    def _default_data(self) -> Dict[str, Any]:
        return {
            "source_file": str(self.source_file),
            "source_hash": self.source_hash,
            "tts_engine": None,
            "tts_config": {},
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

    def _normalize_loaded_data(self, loaded_data: Dict[str, Any]) -> Dict[str, Any]:
        data = self._default_data()
        data.update(loaded_data)

        legacy_tts_config = {
            "piper_bin": data.get("piper_bin"),
            "piper_model": data.get("piper_model"),
            "piper_config": data.get("piper_config"),
        }

        if not data.get("tts_engine") and any(legacy_tts_config.values()):
            data["tts_engine"] = "piper"

        if (not isinstance(data.get("tts_config"), dict) or not data.get("tts_config")) and any(legacy_tts_config.values()):
            data["tts_config"] = legacy_tts_config

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
