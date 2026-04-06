# Book Translation CLI — Development Plan

Implementation guide for a Python coding agent. Read `01_requirements.md` first for full context. This document defines the module structure, class interfaces, and implementation order.

***

## Project Structure

```
translate_book/
├── translate_book.py          ← CLI entry point (thin wrapper around the pipeline)
├── html_processor.py          ← HTML parsing, chunk extraction, HTML reconstruction
├── translator.py              ← Ollama API client and translation logic
├── checkpoint.py              ← Checkpoint read/write
├── display.py                 ← Progress bar and debug logging
├── boilerplate.py             ← Gutenberg boilerplate detection
└── requirements.txt
```

All modules are importable individually. `translate_book.py` composes them.

***

## Module 1: `html_processor.py`

This is the most critical module. It owns all interaction with BeautifulSoup and must never leak HTML tags to the translation layer.

### Class: `Chunk`

```python
@dataclass
class Chunk:
    index: int                        # Sequential chunk number (0-based)
    element_type: str                 # 'p', 'h1', 'h2', ..., 'li', 'td', etc.
    segments: list[NavigableString]   # Ordered list of text node refs in this chunk
    plain_text: str                   # Full concatenated text for translation
    has_inline_tags: bool             # True if <em>, <strong>, <a>, etc. are present
    delimiter: str                    # Sentinel used for segment splitting (if has_inline_tags)
```

### Class: `HTMLProcessor`

```python
class HTMLProcessor:
    def __init__(self, html_content: str):
        self.soup = BeautifulSoup(html_content, 'html.parser')
        self.chunks: list[Chunk] = []

    def extract_chunks(self) -> list[Chunk]:
        """
        Walk the DOM tree. For each translatable block element found,
        create a Chunk. Skip non-translatable zones entirely.
        Return ordered list of Chunk objects.
        """

    def _is_translatable_element(self, tag) -> bool:
        """
        Return True if this tag's text content should be translated.
        Translatable: p, h1-h6, li, td, th, blockquote, figcaption.
        Leaf div (div with no block-element children).
        """

    def _is_in_skip_zone(self, tag) -> bool:
        """
        Return True if the tag is inside head, script, style, pre, code,
        or has been marked as Gutenberg boilerplate.
        """

    def _build_chunk(self, element, index: int) -> Chunk | None:
        """
        Given a block element, collect all NavigableString descendants.
        Skip whitespace-only strings.
        Build plain_text: if multiple strings, join with sentinel delimiter.
        Return None if no translatable text found.
        """

    def apply_translations(self, translations: dict[int, str]) -> None:
        """
        For each chunk index in translations:
          - If not has_inline_tags: replace single NavigableString with translated text.
          - If has_inline_tags: split on delimiter, map back to segment list.
            On mismatch: fallback strategy (replace first segment, clear others).
        """

    def serialize(self) -> str:
        """Return str(self.soup) — the full translated HTML."""
```

### Sentinel Delimiter

Use `｜｜｜` (Unicode fullwidth vertical lines, U+FF5C repeated). This character is vanishingly unlikely to appear in English 19th-century prose and is also unlikely to be tokenized ambiguously by the model.

When building `plain_text` for a chunk with inline tags:
```python
plain_text = " ｜｜｜ ".join(seg.strip() for seg in segments if seg.strip())
```

Prompt addition for inline-tag chunks (append to standard prompt):
```
Preserve the ｜｜｜ delimiters exactly as-is in your translation, in the same positions.
```

***

## Module 2: `boilerplate.py`

### Function: `mark_boilerplate(soup: BeautifulSoup) -> None`

Scan the soup for Gutenberg-specific boilerplate patterns and tag matching elements with a custom attribute `data-skip-translation="true"`. The `HTMLProcessor._is_in_skip_zone` checks for this attribute.

Patterns to detect (case-insensitive):
- Any element whose stripped text starts with `"The Project Gutenberg"`
- Any element whose stripped text matches `*** START OF THE PROJECT GUTENBERG EBOOK ***`
- Any element whose stripped text matches `*** END OF THE PROJECT GUTENBERG EBOOK ***`
- Any `<pre>` block containing lines like `Title:`, `Author:`, `Release date:`, `Language:` (the EBook header metadata block)

After the END marker is found, all subsequent elements are also marked as skip (Gutenberg license text).

***

## Module 3: `translator.py`

### Class: `OllamaTranslator`

```python
class OllamaTranslator:
    SYSTEM_PROMPT = """You are a professional English (en) to Romanian (ro) translator.
Your goal is to accurately convey the meaning and nuances of the original English text
while adhering to Romanian grammar, vocabulary, and cultural sensitivities.
Produce only the Romanian translation, without any additional explanations or commentary.
Proper nouns, character names, place names, and author-invented names must remain
in their original English form. Do not translate them."""

    USER_PROMPT_TEMPLATE = "Please translate the following English text into Romanian:\n\n{text}"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "translategemma:27b",
        temperature: float = 0.3,
        num_ctx: int = 8192,
    ):
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.options = {
            "temperature": temperature,
            "top_k": 64,
            "top_p": 0.95,
            "repeat_penalty": 1.1,
            "num_predict": -1,
            "num_ctx": num_ctx,
        }

    def check_connection(self) -> None:
        """GET /api/tags. Raise ConnectionError if unreachable. Raise ValueError if model not found."""

    def translate(self, text: str, has_delimiters: bool = False) -> TranslationResult:
        """
        POST to /api/chat with system + user messages.
        If has_delimiters is True, append delimiter preservation instruction to user message.
        Return TranslationResult with translated text, token counts, and timing.
        Retry up to MAX_RETRIES on empty response or echoed source.
        """

    def _call_api(self, messages: list[dict]) -> dict:
        """Raw POST to /api/chat. Return parsed JSON response. Raise on HTTP errors."""

    def _clean_response(self, raw: str) -> str:
        """Strip preamble lines that start with known meta-commentary phrases."""
```

### Dataclass: `TranslationResult`

```python
@dataclass
class TranslationResult:
    translated_text: str
    prompt_tokens: int
    output_tokens: int
    duration_seconds: float
    retries: int
    success: bool          # False if all retries exhausted; translated_text = source text
```

### Retry Logic

```python
MAX_RETRIES = 3
RETRY_DELAY = 2.0  # seconds

for attempt in range(MAX_RETRIES):
    result = self._call_api(messages)
    cleaned = self._clean_response(result['message']['content'])
    if cleaned and cleaned.strip() != source_text.strip():
        return TranslationResult(translated_text=cleaned, success=True, ...)
    time.sleep(RETRY_DELAY)

# All retries failed
return TranslationResult(translated_text=source_text, success=False, ...)
```

***

## Module 4: `checkpoint.py`

### Class: `Checkpoint`

```python
class Checkpoint:
    def __init__(self, path: Path, source_file: Path, model: str):
        self.path = path
        self.source_hash = self._hash_file(source_file)
        self.model = model
        self.data: dict = {}

    def load(self) -> bool:
        """
        Load existing checkpoint from disk.
        Return True if loaded successfully.
        Warn if source_hash or model differs from current run.
        """

    def save(self, chunk_index: int, translated_text: str, total_chunks: int) -> None:
        """Append chunk result and write checkpoint to disk atomically (write to .tmp, rename)."""

    def is_done(self, chunk_index: int) -> bool:
        """Return True if chunk_index is in completed list."""

    def get_translation(self, chunk_index: int) -> str | None:
        """Return cached translation for chunk_index, or None."""

    def completed_count(self) -> int:
        """Return number of completed chunks."""
```

Atomic write pattern (prevents corruption on interrupt):
```python
tmp_path = self.path.with_suffix('.tmp')
tmp_path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
tmp_path.rename(self.path)
```

***

## Module 5: `display.py`

### Class: `Display`

```python
class Display:
    def __init__(self, total_chunks: int, debug: bool = False):
        self.total = total_chunks
        self.debug = debug
        self.completed = 0
        self.total_tokens = 0
        self.total_seconds = 0.0
        self.pbar = tqdm(total=total_chunks, unit='chunk', file=sys.stderr,
                         bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]')

    def update(self, chunk: Chunk, result: TranslationResult) -> None:
        """
        Increment progress bar.
        If debug: print side-by-side block to stderr BEFORE updating the bar
        (tqdm.write preserves bar position).
        """

    def _format_debug_block(self, chunk: Chunk, result: TranslationResult) -> str:
        """
        Return formatted side-by-side string:
        ━━━━━━━━━━ [chunk N/M] [type] [X tokens] [Y.Zs]
        EN │ {wrapped source}
        RO │ {wrapped translation}
        """

    def _wrap_with_prefix(self, prefix: str, text: str, width: int = 80) -> str:
        """Wrap text at width and prepend prefix to each line."""

    def close(self) -> None:
        """Close the tqdm bar and print final stats."""
```

Debug output uses `tqdm.write()` (not `print`) to avoid corrupting the progress bar.

***

## Module 6: `translate_book.py` (Entry Point)

### CLI Setup (use `argparse`)

```python
def build_parser() -> argparse.ArgumentParser:
    ...

def main() -> None:
    args = build_parser().parse_args()

    # 1. Validate input file exists and is HTML
    # 2. Resolve output path (default: same dir, _ro suffix)
    # 3. Resolve checkpoint path
    # 4. Initialize OllamaTranslator and check_connection()
    # 5. Read input HTML
    # 6. Run boilerplate.mark_boilerplate(soup)
    # 7. Run processor.extract_chunks() → chunks list
    # 8. If --dry-run: print stats and exit
    # 9. Load or create Checkpoint
    # 10. Initialize Display(total=len(chunks), debug=args.debug)
    # 11. Main translation loop (see below)
    # 12. processor.apply_translations(translations)
    # 13. Write output HTML file (UTF-8, update lang="ro")
    # 14. Delete checkpoint file on successful completion
    # 15. Print final summary

if __name__ == '__main__':
    main()
```

### Main Translation Loop

```python
translations = {}

for chunk in chunks:
    if checkpoint.is_done(chunk.index):
        translations[chunk.index] = checkpoint.get_translation(chunk.index)
        display.update(chunk, cached=True)
        continue

    result = translator.translate(
        text=chunk.plain_text,
        has_delimiters=chunk.has_inline_tags
    )

    translations[chunk.index] = result.translated_text
    checkpoint.save(chunk.index, result.translated_text, len(chunks))
    display.update(chunk, result)
```

***

## Implementation Order

Build and test each step before moving to the next. Each step is independently testable.

### Step 1 — Scaffold and CLI
- Create project directory and `requirements.txt`
- Implement `translate_book.py` with `argparse` (no logic, just argument parsing and print)
- Verify: `python translate_book.py --help` works

### Step 2 — HTML Processor (no translation)
- Implement `html_processor.py` fully
- Implement `boilerplate.py`
- Test: run `extract_chunks()` on a real Gutenberg HTML, print chunk stats
- Verify: all chunks are plain text, no HTML tags in `plain_text`
- Verify: `serialize()` after no-op `apply_translations({})` produces identical HTML to input

### Step 3 — Ollama Translator
- Implement `translator.py`
- Test: translate a single hard-coded paragraph, print result
- Verify: retry logic works (test with wrong model name)
- Verify: `_clean_response` strips preamble correctly

### Step 4 — Checkpoint
- Implement `checkpoint.py`
- Test: save a few entries, reload, verify `is_done()` returns correctly
- Test: interrupt mid-loop, resume, verify no re-translation of completed chunks

### Step 5 — Display
- Implement `display.py`
- Test: run with dummy chunks and results, verify progress bar and debug output coexist without corruption

### Step 6 — Integration
- Wire all modules in `translate_book.py`
- Run end-to-end on a short Gutenberg HTML (e.g., first chapter only via `--dry-run` first)
- Verify output HTML opens in browser, structure intact, text in Romanian
- Verify `lang="ro"` updated in `<html>` tag

### Step 7 — Edge Cases
- Test a Gutenberg HTML with heavy dialogue (many short `<p>` tags)
- Test a chapter with inline `<em>` / `<strong>` (mixed-content re-mapping)
- Test resume after interruption at chunk 1, 50, and last chunk
- Test `--dry-run` output accuracy (compare estimated chunks with actual)

***

## Token Estimation (for `--dry-run` stats)

Use a simple word-count heuristic — no tokenizer dependency needed:

```python
def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)
```

For the dry-run summary, compute:
- Total chunks
- Total estimated input tokens
- Estimated output tokens (assume 1.1× input for EN→RO expansion)
- Estimated time at 40 tokens/s

```
Dry run summary
───────────────────────────────────
Source file:      pg1342.html
Total chunks:     412
Est. input tok:   52,800
Est. output tok:  58,000
Est. time @ 40/s: ~24 minutes
```

***

## Known Edge Cases to Handle

| Edge Case | Handling |
|---|---|
| `<p>` contains only `<br>` tags with no text | Skip — no NavigableStrings |
| `<p>` contains only whitespace strings | Skip |
| `<p>` spans thousands of tokens (James Joyce, legal prose) | Send as-is — never split a paragraph |
| `<a>` inside `<p>` — link text must be translated | Include in NavigableString collection; href stays untouched |
| `<img alt="...">` — alt text | Do NOT translate; it's an attribute |
| Nested `<blockquote>` | Translate inner `<p>` children individually, not the blockquote wrapper |
| Chapter title in a `<div>` not a `<h*>` tag | Detected by leaf-div heuristic in `_is_translatable_element` |
| UTF-8 special chars in source (em-dash, curly quotes) | Pass through unchanged — BeautifulSoup preserves them |
| Gutenberg `<pre>` metadata block at top | Caught by `boilerplate.py` |

***

## Final Deliverable Checklist

- [ ] `translate_book.py --help` shows all options with descriptions
- [ ] `--dry-run` on any Gutenberg HTML prints stats without calling Ollama
- [ ] Normal run produces output HTML that opens correctly in a browser
- [ ] Output HTML structure is byte-identical to input except for text node content and `lang` attribute
- [ ] `--debug` shows side-by-side chunks in real time without corrupting the progress bar
- [ ] `--resume` correctly skips completed chunks after any interruption
- [ ] Boilerplate (Gutenberg header, license) is preserved untranslated
- [ ] Inline tags (`<em>`, `<strong>`, `<a>`) are preserved inside translated paragraphs
- [ ] Names are not translated (verified manually on a few test paragraphs)
- [ ] Checkpoint file is deleted on successful completion
