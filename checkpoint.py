"""Checkpoint read/write for resumable translations."""

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set


class Checkpoint:
    """Manage translation checkpoints for resumable processing."""

    def __init__(self, path: Path, source_file: Path, model: str):
        self.path = path
        self.source_file = source_file
        self.source_hash = self._hash_file(source_file)
        self.model = model
        self.data: Dict = {
            "source_file": str(source_file),
            "source_hash": self.source_hash,
            "model": model,
            "total_chunks": 0,
            "completed": [],
            "translations": {},
            "last_updated": None,
        }
        self._completed_set: Set[int] = set()
        self._lock = threading.Lock()

    def load(self) -> bool:
        """Load existing checkpoint from disk."""
        if not self.path.exists():
            return False

        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded_data = json.load(handle)
        except (json.JSONDecodeError, IOError) as exc:
            print(f"Warning: Failed to load checkpoint: {exc}")
            return False

        if loaded_data.get("source_hash") != self.source_hash:
            raise ValueError(
                "Source file has changed since checkpoint was created. "
                f"Checkpoint: {self.path}. Start a fresh run instead."
            )

        if loaded_data.get("model") != self.model:
            print("Warning: Model mismatch in checkpoint.")
            print(f"  Checkpoint model: {loaded_data.get('model')}")
            print(f"  Current model: {self.model}")

        self.data = self._normalize_loaded_data(loaded_data)
        self._completed_set = set(self.data.get("completed", []))
        return True

    def save(self, chunk_index: int, translated_text: str, total_chunks: int) -> None:
        """Persist a completed translation chunk."""
        with self._lock:
            if chunk_index not in self._completed_set:
                self._completed_set.add(chunk_index)
                self.data["completed"].append(chunk_index)
            self.data["translations"][str(chunk_index)] = translated_text
            self.data["total_chunks"] = total_chunks
            self.data["last_updated"] = datetime.now().isoformat()
            self._write_locked()

    def is_done(self, chunk_index: int) -> bool:
        """Return True if chunk_index is in completed list."""
        with self._lock:
            return chunk_index in self._completed_set

    def get_translation(self, chunk_index: int) -> Optional[str]:
        """Return cached translation for chunk_index, or None."""
        with self._lock:
            return self.data["translations"].get(str(chunk_index))

    def completed_count(self) -> int:
        """Return number of completed chunks."""
        return len(self.data["completed"])

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
        total_chunks = self.data.get("total_chunks", 0)
        completed = self.completed_count()
        return {
            "total_chunks": total_chunks,
            "completed": completed,
            "percent": (completed / total_chunks * 100) if total_chunks > 0 else 0,
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

    def _normalize_loaded_data(self, loaded_data: Dict) -> Dict:
        data = dict(loaded_data)
        data.setdefault("source_file", str(self.source_file))
        data.setdefault("source_hash", self.source_hash)
        data.setdefault("model", self.model)
        data.setdefault("total_chunks", 0)
        data.setdefault("completed", [])
        data.setdefault("translations", {})
        data.setdefault("last_updated", None)

        data["completed"] = [int(item) for item in data.get("completed", [])]
        data["translations"] = {str(key): value for key, value in data.get("translations", {}).items()}
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
