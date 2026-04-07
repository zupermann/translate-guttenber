"""Shared HTML-loading helpers for translation and audiobook pipelines."""

from pathlib import Path
from typing import List, Tuple

from boilerplate import mark_boilerplate
from html_processor import Chunk, HTMLProcessor


def validate_input_file(input_file: Path) -> None:
    """Validate that the input path exists and is a file."""
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file}")
    if not input_file.is_file():
        raise ValueError(f"Input path is not a file: {input_file}")


def read_html_content(input_file: Path) -> str:
    """Read HTML content from disk as UTF-8."""
    validate_input_file(input_file)
    try:
        with open(input_file, "r", encoding="utf-8") as handle:
            return handle.read()
    except IOError as exc:
        raise RuntimeError(f"Cannot read input file: {input_file}") from exc


def load_html_processor(input_file: Path, skip_boilerplate: bool = True) -> Tuple[HTMLProcessor, List[Chunk]]:
    """Load an HTML file, optionally mark Gutenberg boilerplate, and extract chunks."""
    html_content = read_html_content(input_file)
    processor = HTMLProcessor(html_content)
    if skip_boilerplate:
        mark_boilerplate(processor.get_soup())
    chunks = processor.extract_chunks()
    return processor, chunks
