"""HTML parsing, chunk extraction, and HTML reconstruction."""

from dataclasses import dataclass, field
from typing import List, Optional, Union

from bs4 import BeautifulSoup, NavigableString, Tag


# Block elements that are translatable
TRANSLATABLE_ELEMENTS = {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'li', 'td', 'th', 'blockquote', 'figcaption'}

# Elements that are never translated (and their children are skipped)
SKIP_ELEMENTS = {'head', 'script', 'style', 'pre', 'code'}


@dataclass
class Chunk:
    """Represents a translatable chunk of text."""
    index: int                        # Sequential chunk number (0-based)
    element_type: str                 # 'p', 'h1', 'h2', ..., 'li', 'td', etc.
    element: Tag                      # The actual element reference
    plain_text: str = ""              # Text to translate (from get_text())
    has_links: bool = False           # True if <a> tags present
    link_texts: dict = field(default_factory=dict)  # {link_index: (link_element, text)}


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

        try:
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
        finally:
            # Clean up processing markers (exception-safe)
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
        Build a chunk for the element.
        - Get plain text using get_text()
        - Check for <a> tags that need special handling
        - Return None if no translatable text found.
        """
        text = element.get_text(strip=True)
        if not text:
            return None

        # Check for <a> tags within this element
        links = element.find_all('a', href=True)
        has_links = bool(links)
        link_texts = {}

        if has_links:
            # Collect link texts for separate translation
            for i, link in enumerate(links):
                link_text = link.get_text(strip=True)
                if link_text:
                    link_texts[i] = (link, link_text)

        return Chunk(
            index=index,
            element_type=element.name.lower(),
            element=element,
            plain_text=text,
            has_links=has_links,
            link_texts=link_texts,
        )

    def apply_translations(self, translations: dict) -> None:
        """
        Apply translations back to the HTML.
        For chunks without links: replace all text in the element.
        For chunks with links: translate link texts separately.
        """
        # Build lookup dict for O(1) access
        chunk_map = {c.index: c for c in self.chunks}

        for chunk_index, translated_text in translations.items():
            chunk = chunk_map.get(chunk_index)
            if not chunk:
                continue

            if not chunk.has_links:
                # Simple case: no links - clear element and set translated text
                # Clear all current content
                for child in list(chunk.element.contents):
                    child.extract()
                # Add translated text
                chunk.element.append(translated_text)
            else:
                # Complex case: has links - need to translate link texts separately
                # For now, just replace the whole element text
                # (Link preservation would require more complex handling)
                for child in list(chunk.element.contents):
                    child.extract()
                chunk.element.append(translated_text)

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
