"""Gutenberg boilerplate detection and marking."""

import re
from typing import Optional

from bs4 import BeautifulSoup, Tag


# Gutenberg boilerplate patterns
START_MARKER_PATTERN = re.compile(
    r'^\s*\*\*\*\s*START\s+OF\s+(?:THE\s+)?PROJECT\s+GUTENBERG\s+EBOOK',
    re.IGNORECASE
)
END_MARKER_PATTERN = re.compile(
    r'^\s*\*\*\*\s*END\s+OF\s+(?:THE\s+)?PROJECT\s+GUTENBERG\s+EBOOK',
    re.IGNORECASE
)
HEADER_PATTERN = re.compile(
    r'^\s*The\s+Project\s+Gutenberg',
    re.IGNORECASE
)

# Metadata patterns in <pre> blocks
METADATA_PATTERNS = [
    re.compile(r'^\s*Title:', re.IGNORECASE),
    re.compile(r'^\s*Author:', re.IGNORECASE),
    re.compile(r'^\s*Release\s+date:', re.IGNORECASE),
    re.compile(r'^\s*Language:', re.IGNORECASE),
    re.compile(r'^\s*Character\s+set\s+encoding:', re.IGNORECASE),
    re.compile(r'^\s*\*\*\*\s*START\s+OF', re.IGNORECASE),
]


def mark_boilerplate(soup: BeautifulSoup) -> None:
    """
    Scan the soup for Gutenberg-specific boilerplate patterns and tag matching
    elements with a custom attribute data-skip-translation="true".
    The HTMLProcessor._is_in_skip_zone checks for this attribute.

    Patterns detected:
    - Any element whose stripped text starts with "The Project Gutenberg"
    - Any element matching *** START OF THE PROJECT GUTENBERG EBOOK ***
    - Any element matching *** END OF THE PROJECT GUTENBERG EBOOK ***
    - Any <pre> block containing metadata lines (Title:, Author:, etc.)

    After the END marker is found, all subsequent elements are also marked as skip.
    """
    end_marker_found = False

    # Get all elements in document order
    elements = list(soup.find_all(True))

    for i, element in enumerate(elements):
        if not isinstance(element, Tag):
            continue

        # If end marker already found, mark this element as skip
        if end_marker_found:
            element['data-skip-translation'] = 'true'
            continue

        # Only check block-level elements that likely contain the boilerplate
        if element.name not in {'p', 'div', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span'}:
            continue

        # Get text content - use string for single-text elements, get_text for multi-child
        text = _get_element_text(element)
        if not text:
            continue

        # Check for end marker
        if END_MARKER_PATTERN.match(text):
            element['data-skip-translation'] = 'true'
            end_marker_found = True
            continue

        # Check for start marker
        if START_MARKER_PATTERN.match(text):
            element['data-skip-translation'] = 'true'
            continue

        # Check for header pattern ("The Project Gutenberg")
        if HEADER_PATTERN.match(text):
            element['data-skip-translation'] = 'true'
            continue

        # Check for <pre> blocks with metadata
        if element.name == 'pre':
            if _is_metadata_pre_block(text):
                element['data-skip-translation'] = 'true'
                continue


def _get_element_text(element: Tag) -> str:
    """
    Get the text content of an element, but only from direct children.
    Avoids getting text from descendants that might be separate chunks.
    """
    # For elements with only one string child, use that
    strings = list(element.strings)
    if len(strings) == 1:
        return strings[0].strip()

    # For elements with mixed content, concatenate direct NavigableStrings
    direct_text = []
    for child in element.children:
        if isinstance(child, str):
            direct_text.append(child)

    if direct_text:
        return ''.join(direct_text).strip()

    # Fall back to get_text if no direct strings
    return element.get_text(strip=True)


def _is_metadata_pre_block(text: str) -> bool:
    """Check if a <pre> block contains Gutenberg metadata patterns."""
    lines = text.split('\n')
    metadata_line_count = 0

    for line in lines:
        for pattern in METADATA_PATTERNS:
            if pattern.match(line):
                metadata_line_count += 1
                break

    # If at least 2 metadata patterns are found, consider it a metadata block
    return metadata_line_count >= 2


def is_boilerplate_element(element: Tag) -> bool:
    """Check if an element has been marked as boilerplate."""
    return element.get('data-skip-translation') == 'true'
