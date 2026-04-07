# Book Translation and Audiobook Tooling

This repository provides three cleanly separated CLIs for Project Gutenberg HTML books:

- `translate-book` translates English HTML into Romanian HTML with Ollama
- `generate-audiobook` turns narration-ready HTML into an audiobook with XTTS-V2 by default, plus Piper as a fallback + ffmpeg
- `book-pipeline` orchestrates both steps automatically

The CLIs share parsing and pipeline modules, but each command has a single responsibility.

## Features

- HTML-first processing for Gutenberg books
- Chunk-based translation with resumable checkpoints
- Separate audiobook generation from already-translated HTML
- Per-chunk WAV synthesis with XTTS-v2 (`tts-ro`) by default, with Piper still available
- XTTS-oriented speech cleanup for digits, symbols, and short phrase splitting
- Parallel XTTS rendering to better utilize available GPU memory
- Brief pauses after heading chunks for more natural narration
- Final audiobook assembly with `ffmpeg`
- Orchestrated end-to-end workflow when you want one command

## Installation

```bash
./install.sh
# then source your shell rc file, for example:
source ~/.zshrc
```

This installs three commands into `~/.local/bin`:

- `translate-book`
- `generate-audiobook`
- `book-pipeline`

## Requirements

- Python 3.x
- Ollama running locally with a TranslateGemma model for translation
- `tts-ro` installed locally for XTTS-v2, with Piper available as a legacy fallback
- `ffmpeg` installed locally for final audio assembly
- Python dependencies from `requirements.txt`

## Commands

### 1. Translation Only

```bash
translate-book pg8492-images.html
translate-book pg8492-images.html -o pg8492-images_ro.html --debug
translate-book pg8492-images.html --resume
translate-book pg8492-images.html --dry-run
```

Outputs translated HTML such as `pg8492-images_ro.html`.

### 2. Audiobook Only

```bash
generate-audiobook pg8492-images_ro.html
generate-audiobook pg8492-images_ro.html -o pg8492-images_ro.m4b --resume
generate-audiobook pg8492-images_ro.html --tts-engine xtts-ro
generate-audiobook pg8492-images_ro.html \
  --piper-bin ~/piper/piper \
  --piper-model ~/piper/models/ro_RO-mihai-medium.onnx \
  --piper-config ~/piper/models/ro_RO-mihai-medium.onnx.json \
  --heading-pause-seconds 0.75
generate-audiobook pg8492-images_ro.html \
  --tts-engine xtts-ro \
  --speaker-wav ~/voices/narrator.wav \
  --tts-parallel 8 \
  --device cuda
```

This command expects narration-ready HTML, typically the translated HTML from `translate-book`.
XTTS-V2 is the default engine, so the pipeline shortens phrases aggressively, verbalizes digits into Romanian words, strips unsupported symbols, and forwards XTTS options like `--speaker-wav`, `--voice`, `--cache-dir`, `--device`, `--tts-temperature`, `--tts-top-p`, `--tts-top-k`, `--tts-length-penalty`, and `--tts-repetition-penalty`.

### 3. End-to-End Orchestration

```bash
book-pipeline pg8492-images.html
book-pipeline pg8492-images.html --resume
book-pipeline pg8492-images.html --tts-engine xtts-ro
book-pipeline pg8492-images.html \
  --translation-output pg8492-images_ro.html \
  --audio-output pg8492-images_ro.m4b
book-pipeline pg8492-images.html \
  --tts-engine xtts-ro \
  --speaker-wav ~/voices/narrator.wav \
  --tts-parallel 8
```

This command translates first, then feeds the translated HTML into the audiobook CLI logic.

## How It Works

### Translation

1. Parse the HTML with BeautifulSoup.
2. Skip non-readable zones such as boilerplate, `<head>`, `<script>`, `<style>`, `<pre>`, and `<code>`.
3. Extract block chunks such as paragraphs, headings, list items, and table cells.
4. Translate each chunk with Ollama.
5. Write translated plain text back into the HTML structure.

### Audiobook

1. Parse the translated HTML.
2. Extract the same readable block chunks.
3. Normalize text for narration.
4. For XTTS-V2, split long text into short speech-safe Romanian phrases and add pause metadata.
5. Generate one WAV file per speech chunk with the selected TTS engine.
6. Concatenate the WAV files into the final audiobook with `ffmpeg`.

## Output Defaults

- Translation output: `{input_stem}_ro.html`
- Translation checkpoint: `{input_stem}_checkpoint.json`
- Audiobook output from translated HTML: `{input_stem}.m4b`
- Audio checkpoint: `{input_stem}_audio_checkpoint.json`
- Audio segments directory: `{audio_output_stem}_segments/`
- Heading pauses are inserted as short silent WAV files between chapter/section headings and the following narration.

## Development

```bash
python3 translate_book.py book.html
python3 generate_audiobook.py book_ro.html
python3 book_pipeline.py book.html
```

## Docs

- [Requirements](/Users/george/dev/my/translate-guttenber/docs/01_requirments.md)
- [Development Plan](/Users/george/dev/my/translate-guttenber/docs/02_development_plan.md)

## License

MIT
