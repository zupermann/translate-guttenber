"""HTML parsing, chunk extraction, and HTML reconstruction."""

from dataclasses import dataclass, field
from typing import List, Optional

from bs4 import BeautifulSoup, NavigableString, Tag


# Sentinel delimiter for inline tag preservation (Unicode fullwidth vertical line)
DELIMITER = "｜｜｜"

# Block elements that are translatable
TRANSLATABLE_ELEMENTS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td', 'th', 'blockquote', 'figcaption'}

# Elements that are never translated (and their children are skipped)
SKIP_ELEMENTS = {'head', 'script', 'style', 'pre', 'code'}

# Inline elements that should have their text collected but tags preserved
INLINE_ELEMENTS = {'a', 'em', 'strong', 'i', 'b', 'u', 'span', 'mark', 'small', 'del', 'ins', 'sub', 'sup'}


@dataclass
class Chunk:
    """Represents a translatable chunk of text."""
    index: int                        # Sequential chunk number (0-based)
    element_type: str                 # 'p', 'h1', 'h2', ..., 'li', 'td', etc.
    segments: list = field(default_factory=list)   # Ordered list of NavigableString refs in this chunk
    plain_text: str = ""              # Full concatenated text for translation
    has_inline_tags: bool = False     # True if <em>, <strong>, <a>, etc. are present
    delimiter: str = DELIMITER        # Sentinel used for segment splitting (if has_inline_tags)


class HTMLProcessor:
    """Process HTML files for translation."""

    def __init__(self, html_content: str):
        """Initialize with HTML content string."""
        self.soup = BeautifulSoup(html_content, 'html.parser')
        self.chunks: List[Chunk] = []

    def extract_chunks(self) -> List[Chunk]:
        """
        Walk the DOM tree. For each translatable block element found,
        create a Chunk. Skip non-translatable zones entirely.
        Return ordered list of Chunk objects.
        """
        self.chunks = []
        chunk_index = 0

        # Walk all elements in document order
        for element in self.soup.find_all(True):
            if not isinstance(element, Tag):
                continue

            # Skip if not translatable
            if not self._is_translatable_element(element):
                continue

            # Skip if in a skip zone
            if self._is_in_skip_zone(element):
                continue

            # Skip if already processed (avoid double-processing nested blocks)
            if element.get('data-chunk-processed'):
                continue

            # Build chunk for this element
            chunk = self._build_chunk(element, chunk_index)
            if chunk:
                self.chunks.append(chunk)
                chunk_index += 1
                # Mark element as processed
                element['data-chunk-processed'] = 'true'

        # Clean up processing markers
        for element in self.soup.find_all(attrs={'data-chunk-processed': True}):
            del element['data-chunk-processed']

        return self.chunks

    def _is_translatable_element(self, tag: Tag) -> bool:
        """
        Return True if this tag's text content should be translated.
        Translatable: p, h1-h6, li, td, th, blockquote (leaf only), figcaption.
        Leaf div (div with no block-element children).
        """
        if not tag.name:
            return False

        name = tag.name.lower()

        # Basic translatable elements that are never containers
        if name in {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td', 'th', 'figcaption'}:
            return True

        # Blockquote: only translatable if it has NO translatable block children
        if name == 'blockquote':
            for child in tag.children:
                if isinstance(child, Tag):
                    child_name = child.name.lower()
                    if child_name in TRANSLATABLE_ELEMENTS or child_name == 'div':
                        return False
            return bool(tag.get_text(strip=True))

        # Leaf div: div with no translatable block-element children
        if name == 'div':
            for child in tag.children:
                if isinstance(child, Tag):
                    child_name = child.name.lower()
                    if child_name in TRANSLATABLE_ELEMENTS or child_name == 'div':
                        return False
            # Has no block element children - check if it has text content
            text = tag.get_text(strip=True)
            return bool(text)

        return False

    def _is_in_skip_zone(self, tag: Tag) -> bool:
        """
        Return True if the tag is inside head, script, style, pre, code,
        or has been marked as Gutenberg boilerplate.
        """
        # Check for skip attribute (set by boilerplate.py)
        if tag.get('data-skip-translation') == 'true':
            return True

        # Check ancestors
        for parent in tag.parents:
            if isinstance(parent, Tag):
                parent_name = parent.name.lower() if parent.name else ''
                if parent_name in SKIP_ELEMENTS:
                    return True
                # Check for skip attribute on ancestors
                if parent.get('data-skip-translation') == 'true':
                    return True

        return False

    def _build_chunk(self, element: Tag, index: int) -> Optional[Chunk]:
        """
        Given a block element, collect all NavigableString descendants.
        Skip whitespace-only strings.
        Build plain_text: if multiple strings, join with sentinel delimiter.
        Return None if no translatable text found.
        """
        segments = []
        has_inline_tags = False

        # Collect all NavigableString descendants
        for string in element.strings:
            # Skip whitespace-only strings
            text = str(string).strip()
            if not text:
                continue

            # Check if this string is inside an inline tag
            for parent in string.parents:
                if parent == element:
                    break
                if isinstance(parent, Tag) and parent.name.lower() in INLINE_ELEMENTS:
                    has_inline_tags = True
                    break

            segments.append(string)

        if not segments:
            return None

        # Build plain text
        if len(segments) == 1:
            plain_text = str(segments[0]).strip()
        else:
            has_inline_tags = True
            plain_text = f" {DELIMITER} ".join(str(seg).strip() for seg in segments if str(seg).strip())

        return Chunk(
            index=index,
            element_type=element.name.lower(),
            segments=segments,
            plain_text=plain_text,
            has_inline_tags=has_inline_tags,
        )

    def apply_translations(self, translations: dict) -> None:
        """
        For each chunk index in translations:
          - If not has_inline_tags: replace single NavigableString with translated text.
          - If has_inline_tags: split on delimiter, map back to segment list.
            On mismatch: fallback strategy (replace first segment, clear others).
        """
        for chunk_index, translated_text in translations.items():
            # Find the chunk
            chunk = None
            for c in self.chunks:
                if c.index == chunk_index:
                    chunk = c
                    break

            if not chunk:
                continue

            if not chunk.has_inline_tags:
                # Simple case: single segment
                if chunk.segments:
                    chunk.segments[0].replace_with(translated_text)
            else:
                # Complex case: multiple segments with delimiter
                if translated_text.count(DELIMITER) == len(chunk.segments) - 1:
                    # Exact match - map each segment
                    parts = translated_text.split(f" {DELIMITER} ")
                    for i, segment in enumerate(chunk.segments):
                        if i < len(parts):
                            segment.replace_with(parts[i].strip())
                else:
                    # Fallback: delimiter count mismatch
                    # Replace first segment with full translation, clear others
                    if chunk.segments:
                        chunk.segments[0].replace_with(translated_text.strip())
                        # Clear remaining segments
                        for segment in chunk.segments[1:]:
                            segment.replace_with('')

    def serialize(self) -> str:
        """Return str(self.soup) - the full translated HTML."""
        # Update html lang attribute if present
        html_tag = self.soup.find('html')
        if html_tag and html_tag.get('lang'):
            html_tag['lang'] = 'ro'

        return str(self.soup)

    def get_soup(self) -> BeautifulSoup:
        """Return the BeautifulSoup object for inspection/testing."""
        return self.soup
