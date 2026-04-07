"""Checkpoint read/write for resumable translations and audiobook renders."""

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Set


class Checkpoint:
    """Manages translation and audiobook checkpoints for resumable processing."""

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
            "audio": self._default_audio_state(),
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
                raise ValueError(
                    "Source file has changed since checkpoint was created. "
                    f"Checkpoint: {self.path}. Start a fresh run instead."
                )

            # Verify model matches
            if loaded_data.get("model") != self.model:
                print(f"Warning: Model mismatch in checkpoint.")
                print(f"  Checkpoint model: {loaded_data.get('model')}")
                print(f"  Current model: {self.model}")

            self.data = self._normalize_loaded_data(loaded_data)
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

    def configure_audio(
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
        """Store audiobook configuration and prepare audio checkpoint state."""
        with self._lock:
            audio = self._ensure_audio_state()
            current_completed = len(audio.get("completed", []))
            new_state = {
                "enabled": True,
                "piper_bin": str(piper_bin),
                "piper_model": str(piper_model),
                "piper_config": str(piper_config),
                "ffmpeg_bin": str(ffmpeg_bin),
                "segments_dir": str(segments_dir),
                "output_file": str(output_file),
                "total_segments": total_segments,
            }

            if current_completed > 0:
                for key, value in new_state.items():
                    if key in {"enabled", "total_segments"}:
                        continue
                    existing = audio.get(key)
                    if existing is not None and str(existing) != str(value):
                        raise ValueError(
                            "Audio checkpoint was created with different Piper/ffmpeg settings. "
                            "Resume with the same audio configuration or delete the checkpoint and segment files."
                        )
                if audio.get("total_segments") not in (None, 0, total_segments):
                    raise ValueError(
                        "Audio checkpoint was created with different Piper/ffmpeg settings. "
                        "Resume with the same audio configuration or delete the checkpoint and segment files."
                    )

            audio.update(new_state)
            audio["last_updated"] = datetime.now().isoformat()
            self._write_locked()

    def is_done(self, chunk_index: int) -> bool:
        """Return True if chunk_index is in completed list."""
        with self._lock:
            return chunk_index in self._completed_set

    def get_translation(self, chunk_index: int) -> Optional[str]:
        """Return cached translation for chunk_index, or None."""
        with self._lock:
            return self.data["translations"].get(str(chunk_index))

    def audio_is_done(self, chunk_index: int) -> bool:
        """Return True if the audio segment is already generated."""
        with self._lock:
            return chunk_index in self._audio_completed_set()

    def get_audio_segment(self, chunk_index: int) -> Optional[str]:
        """Return cached segment path for chunk_index, or None."""
        with self._lock:
            return self.data.get("audio", {}).get("segments", {}).get(str(chunk_index))

    def save_audio(self, chunk_index: int, segment_path: Path, total_segments: int) -> None:
        """Persist a completed audio segment to disk atomically."""
        with self._lock:
            audio = self._ensure_audio_state()
            completed = audio.setdefault("completed", [])
            if chunk_index not in self._audio_completed_set():
                completed.append(chunk_index)
            audio.setdefault("segments", {})[str(chunk_index)] = str(segment_path)
            audio["total_segments"] = total_segments
            audio["last_updated"] = datetime.now().isoformat()
            self._write_locked()

    def completed_count(self) -> int:
        """Return number of completed chunks."""
        return len(self.data["completed"])

    def audio_completed_count(self) -> int:
        """Return number of completed audio segments."""
        with self._lock:
            return len(self._audio_completed_set())

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
            "audio_completed": self.audio_completed_count(),
            "audio_total": self.data.get("audio", {}).get("total_segments", 0),
            "last_updated": self.data.get("last_updated"),
        }

    def _default_audio_state(self) -> Dict:
        return {
            "enabled": False,
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

    def _ensure_audio_state(self) -> Dict:
        audio = self.data.setdefault("audio", self._default_audio_state())
        for key, value in self._default_audio_state().items():
            audio.setdefault(key, value)
        audio["completed"] = [int(item) for item in audio.get("completed", [])]
        audio["segments"] = {str(key): value for key, value in audio.get("segments", {}).items()}
        return audio

    def _audio_completed_set(self) -> Set[int]:
        audio = self.data.get("audio", {})
        return set(int(item) for item in audio.get("completed", []))

    def _normalize_loaded_data(self, loaded_data: Dict) -> Dict:
        data = dict(loaded_data)
        data.setdefault("source_file", str(self.source_file))
        data.setdefault("source_hash", self.source_hash)
        data.setdefault("model", self.model)
        data.setdefault("total_chunks", 0)
        data.setdefault("completed", [])
        data.setdefault("translations", {})
        data.setdefault("audio", self._default_audio_state())
        data.setdefault("last_updated", None)

        data["completed"] = [int(item) for item in data.get("completed", [])]
        data["translations"] = {str(key): value for key, value in data.get("translations", {}).items()}

        audio = data.get("audio", {})
        if not isinstance(audio, dict):
            audio = self._default_audio_state()
        for key, value in self._default_audio_state().items():
            audio.setdefault(key, value)
        audio["completed"] = [int(item) for item in audio.get("completed", [])]
        audio["segments"] = {str(key): value for key, value in audio.get("segments", {}).items()}
        data["audio"] = audio

        return data

    def _write_locked(self) -> None:
        """Write the current data to disk while holding the lock."""
        tmp_path = self.path.with_suffix('.tmp')
        try:
            with open(tmp_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            tmp_path.rename(self.path)
        except Exception:
            if tmp_path.exists():
                tmp_path.unlink()
            raise
