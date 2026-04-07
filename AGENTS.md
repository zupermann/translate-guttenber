# AGENTS.md

This file provides guidance to Codex when working with code in this repository.

## Project Overview

This repository provides separated CLIs for translating Gutenberg HTML books and generating audiobooks from narration-ready HTML.

## Architecture

### CLI Layer

```text
translate_book.py        # translation-only CLI
generate_audiobook.py    # audiobook-only CLI
book_pipeline.py         # orchestrator CLI
```

### Shared Pipelines

```text
translation_pipeline.py  # translation workflow
audiobook_pipeline.py    # audiobook workflow
checkpoint.py            # translation checkpoint
audio_checkpoint.py      # audiobook checkpoint
```

### Shared Modules

```text
html_processor.py        # HTML parsing and chunk extraction
translator.py            # Ollama client
speech_processor.py      # narration-safe text normalization
tts_engine.py            # Piper wrapper
audio_builder.py         # ffmpeg assembly
display.py               # translation progress/debug output
boilerplate.py           # Gutenberg boilerplate detection
```

## Core Design Principles

1. Translate block text, never raw HTML tags.
2. Generate audiobooks from narration-ready HTML, not from the translation CLI.
3. Keep translation and audio checkpoints separate.
4. Keep CLIs thin and move behavior into reusable pipeline modules.

## Common Commands

```bash
python3 translate_book.py book.html
python3 generate_audiobook.py book_ro.html
python3 book_pipeline.py book.html
```
