# Book Tooling Requirements

## Overview

The project must support three cleanly separated command-line interfaces:

- a translation CLI that converts English Gutenberg HTML into Romanian HTML
- an audiobook CLI that converts narration-ready HTML into audio
- an orchestrator CLI that runs translation and audiobook generation automatically

The CLIs may share lower-level modules, but each CLI must keep a single responsibility.

***

## CLI Separation Requirements

### Translation CLI

Command:

```bash
python translate_book.py INPUT.html
```

Responsibilities:

- parse source HTML
- extract readable chunks
- translate chunk text with Ollama
- rebuild translated HTML
- checkpoint translation progress

Must not:

- call Piper
- generate WAV files
- call `ffmpeg`
- expose audiobook-only flags

### Audiobook CLI

Command:

```bash
python generate_audiobook.py INPUT_ro.html
```

Responsibilities:

- parse narration-ready HTML
- extract readable chunks
- normalize text for speech
- synthesize WAV segments with a selectable TTS engine
- stitch the final audiobook with `ffmpeg`
- checkpoint audio generation progress

Must not:

- call Ollama
- translate text
- expose translation-only flags

### Orchestrator CLI

Command:

```bash
python book_pipeline.py INPUT.html
```

Responsibilities:

- run the translation pipeline
- feed the translated HTML into the audiobook pipeline
- surface one end-to-end workflow to the user

Must not:

- duplicate the internal logic of the other pipelines
- mix translation and audio responsibilities in one monolithic function

***

## Translation Requirements

### Input

- Accept `.html` and `.htm` files.
- Prefer Project Gutenberg HTML as the main supported source format.

### HTML Processing

- Never send raw HTML tags or attributes to the translation model.
- Use block-level chunk extraction.
- Skip non-readable regions:
  - `<head>`
  - `<script>`
  - `<style>`
  - `<pre>`
  - `<code>`
  - Gutenberg header/footer boilerplate

### Chunk Rules

- Each `<p>` is one chunk.
- Other readable block elements are also chunk candidates:
  - `<h1>` to `<h6>`
  - `<li>`
  - `<td>`, `<th>`
  - `<blockquote>`
  - `<figcaption>`
  - leaf `<div>`
- Paragraphs are never split.

### Translation Output

- Output a translated HTML file.
- Replace element content with translated plain text.
- Preserve document-level structure even if inline tags inside translated chunks are flattened.

### Translation Checkpointing

- Save progress after each translated chunk.
- Resume with `--resume`.
- Verify the source file hash.

***

## Audiobook Requirements

### Input

- Accept narration-ready HTML, typically the translated HTML output of the translation CLI.
- Reuse the same readable chunk extraction model as translation.

### Speech Normalization

- Convert readable HTML content into narration-safe text.
- Remove obvious noise where practical:
  - repeated whitespace
  - decorative separators
  - isolated bracket footnote markers
  - raw URLs
- Preserve headings and paragraph order.
- When the selected TTS engine requires shorter prompts, support phrase-level splitting:
  - split on `,`, `;`, `:`, `.`, `!`, `?`
  - further split long phrases around connector words such as `și`, `sau`, `dar`, `iar`, `ori`
- For XTTS-style synthesis, strip or verbalize unsupported symbols and digits so the final text sent to the TTS CLI contains short, speech-safe Romanian phrases.

### TTS Generation

- Keep Piper as a supported external CLI dependency.
- Make XTTS-v2 the default audiobook engine through the `tts-ro` external CLI.
- Generate one WAV file per speech chunk.
- Allow the user to select the TTS engine at the CLI level, with XTTS-v2 as the default.
- Require configurable paths/settings for the selected engine:
  - Piper executable
  - Piper model
  - Piper config
  - XTTS CLI executable
  - XTTS voice or speaker WAV
  - XTTS cache dir
  - XTTS device
  - XTTS sampling/penalty parameters
- Pass XTTS-related CLI parameters through to `tts-ro` when provided.
- Support parallel TTS rendering so lightweight XTTS invocations can better utilize available GPU memory.

### Audio Assembly

- Use `ffmpeg` to concatenate chunk WAV files in order.
- Default final output should be `.m4b`.
- Support keeping intermediate WAV files for debugging.
- Preserve natural pacing by inserting short silent pauses after heading chunks and between phrase-level XTTS splits when needed.

### Audio Checkpointing

- Save progress after each rendered speech chunk.
- Resume with `--resume`.
- Reuse segments only when both the file exists and the normalized speech text still matches.
- Validate resume compatibility against the selected TTS engine and its synthesis-affecting settings, not only Piper-specific paths.

***

## Orchestrator Requirements

- The orchestrator CLI must call shared pipeline functions, not shell out to other CLIs.
- Default workflow:
  - source HTML -> translated HTML -> audiobook
- Default derived outputs:
  - translation: `{input_stem}_ro.html`
  - audiobook: `{translated_stem}.m4b`

***

## Module Requirements

### Shared Parsing

- `html_processor.py` remains the owner of HTML chunk extraction and HTML reconstruction.
- `boilerplate.py` remains responsible for Gutenberg boilerplate detection.

### Translation

- `translator.py` remains the Ollama client.
- `checkpoint.py` becomes translation-only checkpoint management.
- `translation_pipeline.py` owns translation workflow orchestration.

### Audiobook

- `speech_processor.py` owns narration cleanup.
- `tts_engine.py` owns TTS engine selection plus Piper and XTTS CLI invocation.
- `audio_builder.py` owns `ffmpeg` concat/encoding.
- `audio_checkpoint.py` owns audio-only checkpoint state.
- `audiobook_pipeline.py` owns audiobook workflow orchestration.

### CLI Layer

- `translate_book.py` is a thin translation CLI.
- `generate_audiobook.py` is a thin audiobook CLI.
- `book_pipeline.py` is a thin orchestrator CLI.

***

## Non-Functional Requirements

- Runs fully locally.
- Supports long-running books.
- Fails early when Ollama, the selected TTS engine, or `ffmpeg` are unavailable for the stage that needs them.
- Keeps checkpoints stage-specific and understandable.
- Keeps the user-facing command model simple and unsurprising.
