# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## Project Overview

The project is split into translation-only, audiobook-only, and orchestration CLIs for Gutenberg HTML books.

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
speech_processor.py      # narration cleanup
tts_engine.py            # Piper wrapper
audio_builder.py         # ffmpeg assembly
display.py               # translation progress/debug output
boilerplate.py           # Gutenberg boilerplate detection
```

## Core Design Principles

1. Translation and audiobook generation are separate concerns.
2. The orchestrator CLI composes shared pipelines instead of duplicating logic.
3. Translation never invokes Piper or ffmpeg.
4. Audiobook generation never invokes Ollama.

## Common Commands

```bash
python3 translate_book.py book.html
python3 generate_audiobook.py book_ro.html
python3 book_pipeline.py book.html
```
