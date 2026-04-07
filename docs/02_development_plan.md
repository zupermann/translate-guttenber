# Development Plan

Implementation guide for the separated CLI architecture. Read `01_requirments.md` first.

***

## Target Structure

```text
translate_book.py          # translation-only CLI
generate_audiobook.py      # audiobook-only CLI
book_pipeline.py           # orchestrator CLI
translation_pipeline.py    # shared translation workflow
audiobook_pipeline.py      # shared audiobook workflow
checkpoint.py              # translation checkpoint
audio_checkpoint.py        # audiobook checkpoint
html_processor.py          # HTML parsing and reconstruction
speech_processor.py        # narration cleanup
tts_engine.py              # Piper wrapper
audio_builder.py           # ffmpeg assembly
```

***

## Phase 1: Separate Responsibilities

### Translation CLI

- Remove audiobook flags and logic from `translate_book.py`.
- Keep only translation concerns:
  - parser setup
  - dry run
  - translation pipeline invocation
  - translation-specific notifications

### Audiobook CLI

- Add `generate_audiobook.py`.
- Make it accept narration-ready HTML and audio configuration only.
- Keep Ollama completely out of this entrypoint.

### Orchestrator CLI

- Add `book_pipeline.py`.
- It should call:
  - `translate_html_book(...)`
  - `generate_audiobook(...)`

***

## Phase 2: Move Workflow Logic into Pipelines

### `translation_pipeline.py`

Owns:

- loading/parsing HTML
- translation checkpoint loading
- pending chunk detection
- Ollama connection checks only when pending work exists
- chunk translation loop
- output HTML write-back

Outputs:

- translated HTML file path
- chunk count metadata

### `audiobook_pipeline.py`

Owns:

- loading/parsing translated HTML
- narration chunk preparation
- Piper initialization
- per-chunk WAV rendering
- final `ffmpeg` assembly
- optional segment cleanup

Outputs:

- audiobook file path
- segment count metadata

***

## Phase 3: Separate Checkpoints

### `checkpoint.py`

Keep translation-only state:

```json
{
  "source_file": "book.html",
  "source_hash": "sha256:...",
  "model": "translategemma:27b",
  "total_chunks": 123,
  "completed": [0, 1, 2],
  "translations": {
    "0": "..."
  }
}
```

### `audio_checkpoint.py`

Keep audio-only state:

```json
{
  "source_file": "book_ro.html",
  "source_hash": "sha256:...",
  "piper_model": "/path/to/model.onnx",
  "total_segments": 123,
  "completed": [0, 1],
  "segments": {
    "0": {
      "path": "book_ro_segments/00000.wav",
      "text_hash": "sha256:..."
    }
  }
}
```

Reason:

- translation resume and audio resume evolve independently
- audio correctness needs text-hash validation, not just chunk index reuse

***

## Phase 4: Installation Surface

- keep `translate-book`
- add `generate-audiobook`
- add `book-pipeline`
- make wrapper scripts path-relative so they work on any checkout path
- update `install.sh` to install all three commands

***

## Phase 5: Documentation Rewrite

### README

- explain the three commands clearly
- state that audiobook generation now belongs to its own CLI
- document the orchestrator workflow

### Requirements

- update architecture and responsibility boundaries

### Plan

- document modules and implementation order for the separated design

***

## Verification Plan

### Static Checks

- `python3 -m py_compile` on all Python modules

### Smoke Tests

- translation CLI dry run
- audiobook CLI with fake Piper/ffmpeg wrappers
- orchestrator CLI imports and argument parsing

### Manual Run

- translate a short Gutenberg HTML file
- generate audiobook from translated HTML
- run the orchestrator end to end

***

## Expected Outcome

- users can translate without seeing any audio flags
- users can generate audio without pulling in Ollama
- users can run one end-to-end command when they want automation
- the codebase is simpler to reason about because each CLI maps to one pipeline
