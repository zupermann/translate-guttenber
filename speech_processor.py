"""Speech-normalization helpers for audiobook generation."""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
from typing import Any, Dict, List, Optional, TYPE_CHECKING

try:
    from num2words import num2words
except ImportError:  # pragma: no cover - optional until dependencies are installed
    num2words = None

if TYPE_CHECKING:
    from html_processor import Chunk


URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
BRACKET_MARKER_RE = re.compile(r"\[(?:\d+|[ivxlcdm]+)\]", re.IGNORECASE)
HTML_TAG_RE = re.compile(r"<[^>]+>")
DECORATIVE_LINE_RE = re.compile(r"^[\s*_=~-]+$")
DECORATIVE_TOKEN_RE = re.compile(r"(?:(?<=\s)|^)[*_=~-]{2,}(?=(?:\s|$))")
WHITESPACE_RE = re.compile(r"\s+")
NUMBER_TOKEN_RE = re.compile(r"(?<!\w)(\d+(?:[.,]\d+)?)(?!\w)")
PHRASE_SPLIT_RE = re.compile(r"([,;:.!?])")
QUOTE_RE = re.compile(r"[\"'“”„”’`´]+")
BRACKET_RE = re.compile(r"[\[\](){}<>]")
SLASH_RE = re.compile(r"[\\/|]+")
DASH_RE = re.compile(r"[-–—]+")
GENERIC_SYMBOL_RE = re.compile(r"[^\w\săâîșțĂÂÎȘȚ]", re.UNICODE)
UNDERSCORE_OR_DIGIT_RE = re.compile(r"[_\d]")

DIGIT_WORDS = {
    "0": "zero",
    "1": "unu",
    "2": "doi",
    "3": "trei",
    "4": "patru",
    "5": "cinci",
    "6": "șase",
    "7": "șapte",
    "8": "opt",
    "9": "nouă",
}

SYMBOL_REPLACEMENTS = {
    "&": " și ",
    "@": " arond ",
    "#": " numărul ",
    "$": " dolari ",
    "%": " la sută ",
    "+": " plus ",
    "=": " egal ",
    "*": " ",
    "^": " ",
    "_": " ",
    "~": " ",
    "€": " euro ",
    "£": " lire ",
    "¥": " yeni ",
    "°": " grade ",
}


@dataclass(frozen=True)
class SpeechChunk:
    """A narration-ready chunk derived from a translated HTML chunk."""

    index: int
    source_chunk_index: int
    element_type: str
    text: str
    is_chapter_title: bool = False
    pause_after_seconds: float = 0.0


@dataclass(frozen=True)
class SpeechChunkingOptions:
    """Controls how narration text is normalized and split."""

    split_on_phrase_punctuation: bool = False
    max_words_per_chunk: Optional[int] = None
    normalize_numbers: bool = False
    normalize_symbols: bool = False
    connector_words: tuple[str, ...] = (
        "și",
        "sau",
        "dar",
        "iar",
        "ori",
        "însă",
        "că",
        "deci",
    )
    clause_pause_seconds: float = 0.14
    sentence_pause_seconds: float = 0.22
    connector_pause_seconds: float = 0.1
    heading_pause_seconds: float = 0.75


class SpeechProcessor:
    """Convert translated chunks into narration-safe text."""

    HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

    def build_speech_chunks(
        self,
        chunks: List[Any],
        translations: Dict[int, str],
        options: Optional[SpeechChunkingOptions] = None,
    ) -> List[SpeechChunk]:
        """Build ordered speech chunks from translated HTML chunks."""
        options = options or SpeechChunkingOptions()
        speech_chunks: List[SpeechChunk] = []

        for chunk in chunks:
            translated = translations.get(chunk.index, "")
            chunk_texts = self._prepare_chunk_texts(translated, options)
            if not chunk_texts:
                continue

            is_heading = chunk.element_type.lower() in self.HEADING_TAGS
            if is_heading:
                last_text, last_pause = chunk_texts[-1]
                chunk_texts[-1] = (last_text, max(last_pause, options.heading_pause_seconds))

            for text, pause_after in chunk_texts:
                speech_chunks.append(
                    SpeechChunk(
                        index=len(speech_chunks),
                        source_chunk_index=chunk.index,
                        element_type=chunk.element_type,
                        text=text,
                        is_chapter_title=is_heading,
                        pause_after_seconds=pause_after,
                    )
                )

        return speech_chunks

    def build_speech_chunks_from_source(
        self,
        chunks: List[Any],
        options: Optional[SpeechChunkingOptions] = None,
    ) -> List[SpeechChunk]:
        """Build speech chunks directly from chunk plain text."""
        source_texts = {chunk.index: chunk.plain_text for chunk in chunks}
        return self.build_speech_chunks(chunks, source_texts, options=options)

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
        return text.strip()

    def _prepare_chunk_texts(
        self,
        text: str,
        options: SpeechChunkingOptions,
    ) -> List[tuple[str, float]]:
        normalized = self.normalize_for_speech(text)
        if not normalized:
            return []

        if not self._requires_advanced_chunking(options):
            return [(normalized, 0.0)]

        prepared = normalized
        if options.normalize_numbers:
            prepared = NUMBER_TOKEN_RE.sub(
                lambda match: self._number_to_words(match.group(1)),
                prepared,
            )
        if options.normalize_symbols:
            prepared = self._replace_symbols(prepared)

        raw_parts = self._split_on_phrase_punctuation(prepared, options)
        chunk_texts: List[tuple[str, float]] = []

        for raw_text, pause_after in raw_parts:
            sanitized = self._sanitize_segment_text(raw_text)
            if not sanitized:
                continue

            split_segments = self._split_long_segment(sanitized, options)
            for index, segment in enumerate(split_segments):
                segment_pause = pause_after if index == len(split_segments) - 1 else options.connector_pause_seconds
                if segment:
                    chunk_texts.append((segment, segment_pause))

        return chunk_texts

    def _requires_advanced_chunking(self, options: SpeechChunkingOptions) -> bool:
        return any(
            [
                options.split_on_phrase_punctuation,
                options.max_words_per_chunk,
                options.normalize_numbers,
                options.normalize_symbols,
            ]
        )

    def _split_on_phrase_punctuation(
        self,
        text: str,
        options: SpeechChunkingOptions,
    ) -> List[tuple[str, float]]:
        if not options.split_on_phrase_punctuation:
            return [(text, 0.0)]

        parts = PHRASE_SPLIT_RE.split(text)
        segments: List[tuple[str, float]] = []
        current: List[str] = []

        for part in parts:
            if part is None or part == "":
                continue

            if part in {",", ";", ":"}:
                phrase = WHITESPACE_RE.sub(" ", " ".join(current)).strip()
                if phrase:
                    segments.append((phrase, options.clause_pause_seconds))
                current = []
                continue

            if part in {".", "!", "?"}:
                phrase = WHITESPACE_RE.sub(" ", " ".join(current)).strip()
                if phrase:
                    segments.append((phrase, options.sentence_pause_seconds))
                current = []
                continue

            current.append(part)

        trailing = WHITESPACE_RE.sub(" ", " ".join(current)).strip()
        if trailing:
            segments.append((trailing, 0.0))
        return segments

    def _split_long_segment(self, text: str, options: SpeechChunkingOptions) -> List[str]:
        max_words = options.max_words_per_chunk
        if not max_words or self._word_count(text) <= max_words:
            return [text]

        words = text.split()
        segments: List[str] = []
        current = list(words)

        while len(current) > max_words:
            connector_index = self._last_connector_index(current[: max_words + 1], options.connector_words)
            min_connector_index = max(3, max_words // 3)
            split_index = max_words

            if connector_index is not None and connector_index >= min_connector_index:
                split_index = connector_index

            head = current[:split_index]
            current = current[split_index:]

            if not head:
                head = current[:max_words]
                current = current[max_words:]

            segment = " ".join(head).strip()
            if segment:
                segments.append(segment)

        if current:
            segments.append(" ".join(current).strip())

        return segments

    def _sanitize_segment_text(self, text: str) -> str:
        text = QUOTE_RE.sub(" ", text)
        text = BRACKET_RE.sub(" ", text)
        text = SLASH_RE.sub(" ", text)
        text = DASH_RE.sub(" ", text)
        text = self._replace_symbols(text)
        text = GENERIC_SYMBOL_RE.sub(" ", text)
        text = UNDERSCORE_OR_DIGIT_RE.sub(" ", text)
        text = WHITESPACE_RE.sub(" ", text)
        return text.strip()

    def _replace_symbols(self, text: str) -> str:
        for symbol, replacement in SYMBOL_REPLACEMENTS.items():
            text = text.replace(symbol, replacement)
        return text

    def _number_to_words(self, token: str) -> str:
        normalized = token.strip()

        if num2words is not None:
            try:
                if normalized.isdigit():
                    return self._cleanup_number_words(num2words(int(normalized), lang="ro"))

                if normalized.count(",") + normalized.count(".") == 1:
                    decimal = float(normalized.replace(",", "."))
                    return self._cleanup_number_words(num2words(decimal, lang="ro"))
            except (OverflowError, TypeError, ValueError):
                pass

        return self._spell_digits_fallback(normalized)

    def _cleanup_number_words(self, text: str) -> str:
        text = text.replace("-", " ")
        text = text.replace(",", " ")
        return WHITESPACE_RE.sub(" ", text).strip()

    def _spell_digits_fallback(self, text: str) -> str:
        words = []
        for char in text:
            if char.isdigit():
                words.append(DIGIT_WORDS.get(char, char))
            elif char in {".", ","}:
                words.append("virgulă")
        return " ".join(words).strip()

    def _last_connector_index(self, words: List[str], connectors: tuple[str, ...]) -> Optional[int]:
        connector_set = {value.lower() for value in connectors}
        for index in range(len(words) - 1, -1, -1):
            if words[index].lower() in connector_set:
                return index
        return None

    def _word_count(self, text: str) -> int:
        return len(text.split())
