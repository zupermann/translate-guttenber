"""Speech-normalization helpers for audiobook generation."""

from dataclasses import dataclass
import html
import re
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from html_processor import Chunk


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
BRACKET_MARKER_RE = re.compile(r"\[(?:\d+|[ivxlcdm]+)\]", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
DECORATIVE_LINE_RE = re.compile(r"^[\s*_=~-]+$")
DECORATIVE_TOKEN_RE = re.compile(r"(?:(?<=\s)|^)[*_=~-]{2,}(?=(?:\s|$))")
WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class SpeechChunk:
    """A narration-ready chunk derived from a translated HTML chunk."""

    index: int
    source_chunk_index: int
    element_type: str
    text: str
    is_chapter_title: bool = False


class SpeechProcessor:
    """Convert translated chunks into narration-safe text."""

    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def build_speech_chunks(self, chunks: List[Any], translations: Dict[int, str]) -> List[SpeechChunk]:
        """Build ordered speech chunks from translated HTML chunks."""
        speech_chunks: List[SpeechChunk] = []

        for chunk in chunks:
            translated = translations.get(chunk.index, "")
            cleaned = self.normalize_for_speech(translated)
            if not cleaned:
                continue

            speech_chunks.append(
                SpeechChunk(
                    index=len(speech_chunks),
                    source_chunk_index=chunk.index,
                    element_type=chunk.element_type,
                    text=cleaned,
                    is_chapter_title=chunk.element_type.lower() in self.HEADING_TAGS,
                )
            )

        return speech_chunks

    def normalize_for_speech(self, text: str) -> str:
        """Strip obvious HTML artifacts and narration noise from text."""
        if not text:
            return ""

        text = html.unescape(text)
        text = text.replace("\xa0", " ")
        text = HTML_TAG_RE.sub(" ", text)
        text = URL_RE.sub(" ", text)
        text = BRACKET_MARKER_RE.sub(" ", text)
        text = DECORATIVE_TOKEN_RE.sub(" ", text)

        lines = []
        for raw_line in text.splitlines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            if DECORATIVE_LINE_RE.match(stripped):
                continue
            lines.append(stripped)

        text = " ".join(lines) if lines else text
        text = WHITESPACE_RE.sub(" ", text)
        text = text.strip()

        return text
