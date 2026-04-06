"""Checkpoint read/write for resumable translations."""

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set


class Checkpoint:
    """Manages translation checkpoints for resumable processing."""

    def __init__(self, path: Path, source_file: Path, model: str):
        """
        Initialize checkpoint manager.

        Args:
            path: Path to checkpoint JSON file
            source_file: Path to source HTML file (for hash verification)
            model: Model name (for verification)
        """
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
        # Maintain set for O(1) membership checks
        self._completed_set: Set[int] = set()
        # Threading lock for thread-safe operations
        self._lock = threading.Lock()

    def _hash_file(self, file_path: Path) -> str:
        """Compute SHA256 hash of file contents."""
        if not file_path.exists():
            return ""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return f"sha256:{sha256.hexdigest()}"

    def load(self) -> bool:
        """
        Load existing checkpoint from disk.

        Returns:
            True if loaded successfully, False if file doesn't exist or is invalid
        """
        if not self.path.exists():
            return False

        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)

            # Verify source hash matches
            if loaded_data.get("source_hash") != self.source_hash:
                print(f"Warning: Source file has changed since checkpoint was created.")
                print(f"  Checkpoint: {self.path}")
                print(f"  Consider starting fresh or using --force.")

            # Verify model matches
            if loaded_data.get("model") != self.model:
                print(f"Warning: Model mismatch in checkpoint.")
                print(f"  Checkpoint model: {loaded_data.get('model')}")
                print(f"  Current model: {self.model}")

            self.data = loaded_data
            # Populate set for O(1) lookups
            self._completed_set = set(self.data.get("completed", []))
            return True

        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to load checkpoint: {e}")
            return False

    def save(self, chunk_index: int, translated_text: str, total_chunks: int) -> None:
        """
        Append chunk result and write checkpoint to disk atomically.

        Uses write-to-temp-then-rename pattern to prevent corruption on interrupt.

        Args:
            chunk_index: Index of the completed chunk
            translated_text: The translated text
            total_chunks: Total number of chunks
        """
        with self._lock:
            # Update data and set
            if chunk_index not in self._completed_set:
                self._completed_set.add(chunk_index)
                self.data["completed"].append(chunk_index)
            self.data["translations"][str(chunk_index)] = translated_text
            self.data["total_chunks"] = total_chunks
            self.data["last_updated"] = datetime.now().isoformat()

            # Atomic write
            tmp_path = self.path.with_suffix('.tmp')
            try:
                with open(tmp_path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                tmp_path.rename(self.path)
            except Exception:
                # Clean up temp file on error
                if tmp_path.exists():
                    tmp_path.unlink()
                raise

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
        return {
            "total_chunks": self.data.get("total_chunks", 0),
            "completed": self.completed_count(),
            "percent": (self.completed_count() / self.data["total_chunks"] * 100)
            if self.data.get("total_chunks", 0) > 0 else 0,
            "last_updated": self.data.get("last_updated"),
        }
