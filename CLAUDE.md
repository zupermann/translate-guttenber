# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Python CLI tool that translates Project Gutenberg books from English to Romanian using a local Ollama TranslateGemma model. The tool accepts an HTML source file, translates all human-readable text while preserving the complete HTML structure, and writes a translated HTML output file.

## Architecture

### Module Structure

```
translate_book/
├── translate_book.py          # CLI entry point (thin wrapper around the pipeline)
├── html_processor.py          # HTML parsing, chunk extraction, HTML reconstruction
├── translator.py              # Ollama API client and translation logic
├── checkpoint.py              # Checkpoint read/write for resumable translations
├── display.py                 # Progress bar and debug logging
├── boilerplate.py             # Gutenberg boilerplate detection
└── requirements.txt
```

### Core Design Principles

1. **Translate Text Nodes, Never Tags**: HTML structure, attributes, IDs, classes, and tag names remain untouched. Only NavigableString content is extracted, translated, and replaced in-place within the BeautifulSoup tree.

2. **Chunk-Based Processing**: Each `<p>` element is one translation chunk. Other block elements (`<h1>`–`<h6>`, `<li>`, `<td>`, etc.) are individual chunks. Paragraphs are never split, regardless of token length.

3. **Sentinel Delimiter for Inline Tags**: Mixed content (e.g., `<p>He said <em>hello</em> to her.</p>`) uses `｜｜｜` (Unicode fullwidth vertical lines) as a delimiter to preserve inline tag positions across translation.

4. **Checkpointing**: After every completed chunk, state is written to disk. Interrupted runs can be resumed with `--resume`.

## Dependencies

```bash
pip install beautifulsoup4>=4.12 requests>=2.31 tqdm>=4.66
```

## Common Commands

### Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run translation
python translate_book.py pg1342.html

# Run with custom output and debug logging
python translate_book.py pg1342.html -o pride_prejudice_ro.html --debug

# Resume interrupted run
python translate_book.py pg1342.html --resume

# Dry run to estimate chunks and time
python translate_book.py pg1342.html --dry-run

# Use different model
python translate_book.py pg1342.html --model translategemma:12b
```

## Key Implementation Details

### Translation Model Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `temperature` | `0.3` | Tight for accuracy, loose enough for natural Romanian phrasing |
| `top_k` | `64` | Model default |
| `top_p` | `0.95` | Model default |
| `repeat_penalty` | `1.1` | Prevents repetition in long paragraphs |
| `num_predict` | `-1` | Unlimited generation |
| `num_ctx` | `8192` | Sufficient for any single paragraph |

### Translatable Elements

- `<p>` — main prose paragraphs (primary translation unit)
- `<h1>`–`<h6>` — chapter/section headings
- `<li>` — list items
- `<td>`, `<th>` — table cells
- `<blockquote>` — quoted passages
- `<figcaption>` — figure captions
- Leaf `<div>` (divs containing only text, no nested block elements)

### Non-Translatable Elements

- Everything inside `<head>`
- `<script>`, `<style>`, `<pre>`, `<code>`
- HTML attributes (`href`, `src`, `class`, `id`, `alt`, etc.)
- HTML comments
- Whitespace-only text nodes
- Gutenberg header/footer boilerplate (auto-detected)

### Ollama API

- Base URL: `http://localhost:11434`
- Endpoint: `POST /api/chat`
- Model: `translategemma:27b` (default)

### Post-Processing to EPUB

```bash
pandoc translated_book.html -o translated_book.epub --metadata title="Book Title"
```
