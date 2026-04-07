# Audiobook Generation — Requirements and Plan

This document extends the current HTML-to-Romanian translation tool with an end-to-end audiobook pipeline.

Goal: accept a source HTML book, strip non-narratable content, translate it to Romanian, synthesize speech with Piper, and assemble a final audiobook file with `ffmpeg`.

***

## Scope

### In Scope

- Input: Project Gutenberg-style HTML files
- Reuse the existing HTML parsing and translation pipeline
- Produce clean narration text from the HTML content
- Generate per-chunk audio with Piper
- Stitch chunk audio into one final audiobook file
- Support resumable runs with checkpoints for long jobs
- Keep intermediate translated HTML as a useful artifact

### Out of Scope for V1

- Multi-voice character assignment
- Background music or sound effects
- SSML support
- EPUB parsing
- Perfect inline-format preservation inside spoken chunks
- Fully automatic pronunciation dictionaries

***

## Target User Workflow

```text
HTML input
  -> parse and skip boilerplate/unreadable zones
  -> extract readable chunks
  -> translate chunks to Romanian
  -> write translated HTML
  -> normalize chunks for speech
  -> synthesize chunk WAV files with Piper
  -> concatenate and encode final audiobook
  -> return translated HTML + audiobook output
```

Recommended default: keep translation as the first stage, then generate Romanian audio from the translated chunks.

***

## Functional Requirements

### 1. Input and Parsing

- Accept `.html` / `.htm` input files.
- Reuse the existing DOM parsing rules from `html_processor.py`.
- Skip non-readable zones:
  - `<head>`
  - `<script>`
  - `<style>`
  - `<pre>`
  - `<code>`
  - Gutenberg header/footer boilerplate
- Continue treating block elements as the main units of work.

### 2. Narration-Safe Text Extraction

- Build spoken text from plain text only, never from raw HTML.
- Normalize text for narration so Piper does not read markup artifacts or layout noise.
- Remove or rewrite unreadable fragments where practical:
  - repeated whitespace
  - stray footnote markers like `[1]` when they are isolated noise
  - decorative separators such as `***`
  - image-only elements with no useful text
  - URLs that should not be spoken verbatim by default
- Preserve meaningful headings and paragraph order.
- Keep chapter titles as separate chunks to improve pacing and later chapterization.

### 3. Translation

- Keep the current translation behavior as the default content-generation step.
- Continue checkpointing translation progress after each chunk.
- Produce translated HTML output even when audiobook generation is requested.
- Allow audiobook generation to reuse completed translation checkpoints on resume.

### 4. Text-to-Speech

- Use Piper as an external CLI dependency.
- Generate one audio file per narration chunk.
- Default voice should be configurable by model path and config path.
- Initial implementation should support the local Romanian voice the user already tested:

```bash
echo "Salut! Acesta este un test audio în limba română." | ./piper \
  --model ~/piper/models/ro_RO-mihai-medium.onnx \
  --config ~/piper/models/ro_RO-mihai-medium.onnx.json \
  --output_file test.wav
```

- Fail early with a clear error if Piper binary, model, or config are missing.

### 5. Audio Assembly

- Use `ffmpeg` to concatenate chunk WAV files in order.
- Produce a single final audiobook artifact.
- V1 output format should default to `.m4b` or `.mp3`; `.m4b` is preferred if chapter metadata is added later.
- Preserve chunk order exactly.
- Optionally keep intermediate WAV files for debugging.

### 6. Resume and Recovery

- Translation and TTS stages must both be resumable.
- If a chunk audio file already exists and matches the checkpoint entry, skip regenerating it.
- If the final assembly step fails, previously rendered chunk audio should remain usable for retry.

***

## Non-Functional Requirements

- Long books must run locally without cloud dependencies.
- The pipeline should tolerate interruption and restart cleanly.
- Logs should make it obvious whether failure happened during translation, TTS, or final assembly.
- Default behavior should optimize for robustness over maximum speed.
- Intermediate artifacts should be stored predictably so users can inspect or reuse them.

***

## Proposed CLI Experience

### Minimal User Flow

```bash
python translate_book.py book.html --audiobook \
  --piper-bin ~/piper/piper \
  --piper-model ~/piper/models/ro_RO-mihai-medium.onnx \
  --piper-config ~/piper/models/ro_RO-mihai-medium.onnx.json
```

### Proposed Options

- `--audiobook`
  - Enable audiobook generation after translation.
- `--audio-output`
  - Final audiobook path. Default: `{input_stem}_ro.m4b`
- `--piper-bin`
  - Path to Piper executable.
- `--piper-model`
  - Path to Piper `.onnx` voice model.
- `--piper-config`
  - Path to Piper `.onnx.json` config.
- `--ffmpeg-bin`
  - Path to `ffmpeg`. Default: `ffmpeg`
- `--keep-audio-segments`
  - Keep per-chunk WAV files after final assembly.
- `--audio-format`
  - Output container/codec choice such as `m4b` or `mp3`.
- `--audio-only`
  - Skip translation only if the input is already Romanian-ready text. This can stay out of V1 if we want to keep scope tight.

Recommended V1 CLI choice: implement `--audiobook`, `--audio-output`, `--piper-bin`, `--piper-model`, `--piper-config`, `--ffmpeg-bin`, and `--keep-audio-segments` first.

***

## Proposed Architecture Changes

### Keep Existing Modules

- `translate_book.py`
- `html_processor.py`
- `translator.py`
- `checkpoint.py`
- `display.py`
- `boilerplate.py`

### Add New Modules

#### `speech_processor.py`

Responsibilities:

- convert translated chunks into narration-safe text
- remove or rewrite content that sounds bad when spoken
- decide which chunk types should be narrated
- optionally label chapter-like headings for later audio metadata

Suggested interface:

```python
@dataclass
class SpeechChunk:
    index: int
    source_chunk_index: int
    element_type: str
    text: str
    is_chapter_title: bool = False


class SpeechProcessor:
    def build_speech_chunks(self, chunks: list[Chunk], translations: dict[int, str]) -> list[SpeechChunk]:
        ...
```

#### `tts_engine.py`

Responsibilities:

- validate Piper executable and model/config paths
- synthesize one WAV file per speech chunk
- expose per-chunk progress and errors

Suggested interface:

```python
class PiperTTS:
    def __init__(self, piper_bin: Path, model: Path, config: Path):
        ...

    def synthesize(self, text: str, output_file: Path) -> None:
        ...
```

#### `audio_builder.py`

Responsibilities:

- create concat input manifest for `ffmpeg`
- stitch WAV segments into final audiobook
- optionally convert WAV -> MP3/M4B
- later: add chapters/metadata

Suggested interface:

```python
class AudioBuilder:
    def concat(self, segment_files: list[Path], output_file: Path, ffmpeg_bin: str = "ffmpeg") -> None:
        ...
```

#### `audio_checkpoint.py` or extend `checkpoint.py`

Responsibilities:

- track completed speech chunk renders
- store segment file paths and timestamps
- allow safe resume without re-synthesizing finished chunks

Recommendation: extend `checkpoint.py` instead of adding a separate checkpoint module unless the JSON structure becomes hard to manage.

***

## Data Flow Design

### Stage 1: HTML -> Translation Chunks

- Parse the HTML
- Mark boilerplate
- Extract ordered `Chunk` objects

### Stage 2: Translation Chunks -> Romanian Text

- Translate with the existing Ollama workflow
- Save translated HTML
- Persist translations in checkpoint state

### Stage 3: Romanian Text -> Speech Chunks

- Normalize translated text for speech
- Drop empty or non-narratable chunks
- Preserve order
- Mark headings that should become chapter boundaries later

### Stage 4: Speech Chunks -> WAV Segments

- Generate deterministic segment filenames such as:

```text
{book_stem}_audio_segments/00001.wav
{book_stem}_audio_segments/00002.wav
...
```

- Save progress after each successful segment

### Stage 5: WAV Segments -> Final Audiobook

- Build an `ffmpeg` concat manifest
- Produce final audiobook file
- Clean up segment files only if the user did not request to keep them

***

## Text Normalization Rules for Speech

V1 should keep this conservative. We want obvious cleanup, not aggressive rewriting.

- Collapse repeated whitespace to single spaces.
- Decode HTML entities through the existing parser output.
- Remove decorative separators that have no spoken meaning.
- Strip empty bracketed references when they are clearly footnote noise.
- Preserve punctuation that helps Piper pace the narration.
- Preserve headings as standalone lines/chunks.
- Do not try to invent pronunciation hints in V1.

Important distinction:
- Translation normalization is about semantic fidelity.
- Speech normalization is about listenability.

These should be separate steps so we do not damage the translated HTML artifact just to make audio sound better.

***

## Checkpoint Design

Extend the checkpoint JSON with audio state:

```json
{
  "source_file": "pg1342.html",
  "model": "translategemma:27b",
  "translations": {
    "0": "..."
  },
  "audio": {
    "voice_model": "/Users/george/piper/models/ro_RO-mihai-medium.onnx",
    "segments_dir": "pg1342_audio_segments",
    "completed": {
      "0": "pg1342_audio_segments/00000.wav"
    },
    "final_output": "pg1342_ro.m4b"
  }
}
```

Rules:

- Translation checkpointing remains chunk-based.
- Audio checkpointing should use the speech chunk index.
- Resume should verify that referenced segment files still exist.
- If a segment file is missing, regenerate only that segment.

***

## Error Handling

- If translation fails for a chunk, keep current behavior and stop cleanly.
- If Piper synthesis fails for a chunk, stop and report the chunk index and output path.
- If `ffmpeg` fails, keep all generated segments and report the concat command context.
- Detect missing binaries before starting long work when possible.

***

## Implementation Plan

### Phase 1: CLI and Dependency Validation

- Add audiobook-related CLI flags.
- Validate Piper and `ffmpeg` availability.
- Decide default output paths for audio artifacts.

### Phase 2: Speech Chunk Preparation

- Add `speech_processor.py`.
- Reuse translated text to build speech-safe chunks.
- Add unit tests for narration cleanup rules.

### Phase 3: Piper Integration

- Add `tts_engine.py`.
- Implement chunk-by-chunk WAV generation through `subprocess.run(...)`.
- Add audio progress logging similar to translation progress.

### Phase 4: Audio Assembly

- Add `audio_builder.py`.
- Generate concat manifest and final audiobook file with `ffmpeg`.
- Support cleanup or retention of segment files.

### Phase 5: Resume Support

- Extend checkpoint format for audio stage progress.
- Allow reruns to skip completed translations and completed audio segments.

### Phase 6: Polish

- Improve README usage examples.
- Add a sample end-to-end command.
- Consider chapter metadata for headings if `m4b` becomes the default.

***

## Testing Plan

### Unit Tests

- speech normalization rules
- chunk-to-segment filename mapping
- concat manifest generation
- checkpoint resume logic for missing/existing segment files

### Integration Tests

- small HTML fixture -> translated HTML + multiple WAV files
- interrupted run -> resume without redoing finished work
- final `ffmpeg` assembly on a short fixture

### Manual Validation

- run on a short Gutenberg chapter
- verify chapter headings sound natural
- verify noisy HTML fragments are not spoken aloud
- verify output plays correctly in standard audiobook/audio players

***

## Recommended V1 Decisions

- Keep translation mandatory for now and generate Romanian audio from translated text.
- Use Piper CLI directly instead of adding a Python wrapper.
- Render WAV per chunk, then stitch with `ffmpeg`.
- Preserve translated HTML and audio segments as first-class artifacts.
- Keep speech cleanup conservative to avoid dropping meaningful text.

***

## Open Questions

- Should the final default output be `.mp3` for simplicity or `.m4b` for audiobook semantics?
- Do we want chapter files in addition to one full-book file?
- Should footnotes be skipped entirely, or narrated in place when they are part of the reading flow?
- Do we want `--audiobook` to imply translation always, or support Romanian-source HTML in a later phase?

My recommendation for V1:

- default to one final file plus optional kept segments
- keep footnotes only when they appear as normal paragraphs
- postpone chapter metadata until the core pipeline is stable

