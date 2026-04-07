# Book Translation CLI — Requirements Specification

## Overview

A Python CLI tool that translates Project Gutenberg books from English to Romanian using a local Ollama TranslateGemma model. The tool accepts an HTML source file, translates human-readable text in block chunks, and writes a translated HTML output file.

***

## Why HTML, Not EPUB

Project Gutenberg provides both formats. **HTML is the preferred input** for this use case:

- EPUB is a ZIP container of HTML files plus OPF/NCX metadata. Unpacking it adds complexity with no quality benefit.
- HTML exposes the full document as a single parseable tree. BeautifulSoup can walk it in one pass, extracting and replacing text nodes directly.
- After translation, the output HTML can be read in any browser or converted to EPUB/MOBI with Pandoc in one command — the tool does not need to handle EPUB reassembly.
- Gutenberg HTML files are well-formed and use simple semantic markup (`<p>`, `<h1>`–`<h6>`, `<div>`, `<blockquote>`), making them ideal for NavigableString-level processing.

**Post-processing to EPUB (outside scope of this tool):**
```bash
pandoc translated_book.html -o translated_book.epub --metadata title="Book Title"
```

***

## HTML Processing Strategy

### Core Principle: Translate Block Text, Never Tags

The application must **never send HTML markup to the translation model**. It extracts plain text from translatable block elements, translates that text, and writes the translated plain text back into those elements.

### Processing Pipeline

```
HTML file
  └─ BeautifulSoup parse (html.parser)
       └─ Walk the DOM tree
            └─ Collect translatable block elements and extract plain text (`get_text(strip=True)`)
                 └─ Send plain text to Ollama
                      └─ Replace each chunk element's content with translated text
                           └─ Serialize full soup back to HTML
                                └─ Write output file
```

### Translatable Elements

Text nodes that are direct children or descendants of the following block elements are translated:

- `<p>` — main prose paragraphs (primary translation unit)
- `<h1>`, `<h2>`, `<h3>`, `<h4>`, `<h5>`, `<h6>` — chapter/section headings
- `<li>` — list items
- `<td>`, `<th>` — table cells
- `<blockquote>` — quoted passages
- `<figcaption>` — figure captions
- `<div>` (only leaf divs — divs that contain only text, not nested block elements)

### Elements That Must NOT Be Translated

| Element / Context | Reason |
|---|---|
| Everything inside `<head>` | Metadata, charset, title tags |
| `<script>` content | JavaScript code |
| `<style>` content | CSS |
| `<pre>` and `<code>` | Preformatted / code blocks |
| HTML attributes (`href`, `src`, `class`, `id`, `alt`, `title`, etc.) | Structural, not prose |
| HTML comments (`<!-- ... -->`) | Editor notes, not content |
| Whitespace-only text nodes (`\n`, `\t`, `   `) | Layout whitespace |
| Gutenberg header boilerplate | Lines matching patterns like `The Project Gutenberg EBook of...`, `*** START OF THE PROJECT GUTENBERG EBOOK ***`, `*** END OF THE PROJECT GUTENBERG EBOOK ***` |

### Chunk Assembly from HTML

Each `<p>` element is one translation chunk. Its full text (`get_text(strip=True)`) is sent as one request. **A paragraph is never split, regardless of its token length.**

For other block elements (`<h1>`–`<h6>`, `<li>`, etc.), each element is its own chunk.

After translation, the model response is written back as plain text content for that element.

Note: for mixed-content elements (e.g., `<p>He said <em>hello</em> to her.</p>`), inline tags inside the chunk are flattened by this write-back strategy. This is an intentional simplification for robustness.

***

## Translation Model Parameters

### Base Parameters (from model's own Modelfile)

The `translategemma:27b` model ships with these defaults via `ollama show`:

```
top_k    64
top_p    0.95
stop     <end_of_turn>
```

There is no `temperature` set in the official Modelfile, so Ollama applies its default (0.8). Community-optimized builds hard-code `0.1` for maximum accuracy, which is suitable for technical or legal documents but produces overly stiff literary prose.

### Recommended Parameters for Literary Translation

| Parameter | Value | Rationale |
|---|---|---|
| `temperature` | `0.3` | Tight enough to preserve meaning and names; loose enough to allow natural Romanian idiomatic phrasing over word-for-word literalism |
| `top_k` | `64` | Keep the model's default — it was set during fine-tuning |
| `top_p` | `0.95` | Keep the model's default |
| `repeat_penalty` | `1.1` | Prevents phrase repetition in long paragraphs |
| `num_predict` | `-1` | Unlimited generation — always finish the full paragraph |
| `num_ctx` | `8192` | Sufficient for any single paragraph including very long ones; matches community recommendations |

`temperature: 0.3` is the deliberate choice for this use case:
- `0.0–0.1`: near-deterministic, correct but mechanically literal
- `0.3`: allows natural synonym selection and idiomatic phrasing while keeping proper nouns and meaning stable
- `0.5+`: introduces lexical drift, especially in repeated runs

### Prompt Format

```
You are a professional English (en) to Romanian (ro) translator.
Your goal is to accurately convey the meaning and nuances of the original English text
while adhering to Romanian grammar, vocabulary, and cultural sensitivities.
Produce only the Romanian translation, without any additional explanations or commentary.
Proper nouns, character names, place names, and author-invented names must remain
in their original English form. Do not translate them.
Please translate the following English text into Romanian:

{text}
```

**System message** (chat endpoint): The block above minus the last sentence.
**User message**: `Please translate the following English text into Romanian:\n\n{text}`

***

## CLI Interface

### Command Syntax

```
python translate_book.py [OPTIONS] INPUT_FILE
```

### Arguments and Options

| Argument / Option | Type | Required | Description |
|---|---|---|---|
| `INPUT_FILE` | positional | yes | Path to the source HTML file |
| `--output`, `-o` | path | no | Output HTML file path. Default: `{input_stem}_ro.html` in the same directory |
| `--model`, `-m` | string | no | Ollama model name. Default: `translategemma:27b` |
| `--ollama-url` | URL | no | Ollama base URL. Default: `http://localhost:11434` |
| `--temperature` | float | no | Override temperature. Default: `0.3` |
| `--num-ctx` | int | no | Context window size. Default: `8192` |
| `--checkpoint` | path | no | Path to checkpoint JSON file. Default: `{input_stem}_checkpoint.json` |
| `--resume` | flag | no | Resume from existing checkpoint if present |
| `--debug` | flag | no | Enable debug mode: log source and translation side-by-side to stderr |
| `--dry-run` | flag | no | Parse and count chunks, print stats, do not call the model |
| `--skip-boilerplate` | flag | no | Auto-detect and skip Gutenberg header/footer boilerplate (default: on) |
| `--parallel` | int | no | Number of parallel translation workers. Default: `2` |
| `--force` | flag | no | Overwrite output file if it already exists |

### Usage Examples

```bash
# Basic translation
python translate_book.py pg1342.html

# With custom output path and debug logging
python translate_book.py pg1342.html -o pride_prejudice_ro.html --debug

# Resume interrupted run
python translate_book.py pg1342.html --resume

# Dry run to estimate time
python translate_book.py pg1342.html --dry-run

# Custom model
python translate_book.py pg1342.html --model translategemma:12b
```

***

## Debug Mode Output

When `--debug` is active, each translated chunk is logged to `stderr` in a side-by-side format immediately after the API call returns (real-time, not buffered):

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ [chunk 47/412] [p] [83 tokens] [2.1s]
EN │ It is a truth universally acknowledged, that a single man in possession
   │ of a good fortune, must be in want of a wife.
RO │ Este un adevăr universal recunoscut că un bărbat singur, înstărit,
   │ trebuie să caute o soție.
```

Format rules:
- Separator line includes: chunk index / total, element type, estimated token count, generation time
- `EN │` prefix for each source line (wrapped at 80 chars)
- `RO │` prefix for each translated line (wrapped at 80 chars)
- One blank line between chunks
- Sent to `stderr` so it does not contaminate stdout or the output file

***

## Progress Display

A progress bar is shown on `stderr` at all times (not only in debug mode):

```
Translating: 47/412 chunks ████████░░░░░░░░░░░░ 11.4% | 40.1 tok/s | ETA 18m 32s
```

The progress bar updates in-place using `\r` or a library like `tqdm`. It shows:
- Chunks completed / total
- Visual fill bar
- Percentage
- Running average tokens per second
- Estimated time remaining

***

## Checkpointing

The tool writes a checkpoint file after every completed chunk. If the run is interrupted and `--resume` is passed, it reads the checkpoint, skips already-translated chunks, and continues from where it stopped.

### Checkpoint File Format

```json
{
  "source_file": "pg1342.html",
  "source_hash": "sha256:abc123...",
  "model": "translategemma:27b",
  "total_chunks": 412,
  "completed": [0, 1, 2, ..., 46],
  "translations": {
    "0": "translated text for chunk 0",
    "1": "translated text for chunk 1"
  },
  "last_updated": "2026-04-06T08:30:00"
}
```

The `source_hash` is used to detect if the source file changed between runs and warn the user.

***

## Error Handling

| Condition | Behavior |
|---|---|
| Ollama not reachable | Exit immediately with clear error message and URL hint |
| Model not found in Ollama | Exit immediately, list available models |
| Empty response / request failure | Retry up to 3 times with 2s delay; if all fail, mark chunk as failed |
| Chunk translation failed after retries | Abort the run, keep checkpoint, and instruct resume after fixing the issue |
| Output file already exists (no `--resume`) | Exit with error unless `--force` is set |

***

## Output File

The output is a valid HTML file with translated chunk content in Romanian. The file encoding is UTF-8. The `<html lang="...">` attribute is updated to `lang="ro"` if present.

***

## Dependencies

```
beautifulsoup4>=4.12
requests>=2.31
tqdm>=4.66
```

No heavy ML dependencies. All model inference runs through the local Ollama HTTP API.
