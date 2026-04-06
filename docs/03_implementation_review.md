# Implementation Review

This document catalogs all design decisions, deviations, and additions that were NOT specified in the original requirements (`01_requirments.md`) or development plan (`02_development_plan.md`).

## Summary

The implementation follows the specification closely, but several design decisions were made during development to address edge cases, improve robustness, or handle scenarios not explicitly covered in the requirements.

---

## 1. CLI Arguments

### Additions Not in Requirements

| Argument | Status | Notes |
|----------|--------|-------|
| `--force` | **Added** | Not in requirements. Added to allow overwriting output files without prompting. Requirements only mentioned prompting user, not a force flag. |
| `--skip-boilerplate` | **Modified** | Requirements list this as "default: on" but implementation uses `action="store_true"` which defaults to `False`. However, `default=True` was added making it effectively on by default. |

### Exit Codes

Requirements did not specify exit codes. Implementation uses:
- `0` - Success
- `1` - Error (file not found, connection error, etc.)
- `130` - Interrupted (Ctrl+C)

### Output File Collision Handling

**Requirements stated:**
> "Prompt user to confirm overwrite unless `--force` flag is set"

**Implementation:**
- Does NOT prompt interactively
- Instead, prints error message and exits with code 1
- Requires explicit `--force` or `--resume` to proceed

This is a deviation - no interactive prompting occurs.

---

## 2. HTML Processor (`html_processor.py`)

### Blockquote Handling (Significant Decision)

**Plan stated:**
> "Nested `<blockquote>`: Translate inner `<p>` children individually, not the blockquote wrapper"

**Implementation:**
Added logic to detect if a `<blockquote>` contains translatable block children. If it does, the blockquote itself is NOT a chunk - only its children are. This prevents duplicate extraction.

```python
# Blockquote: only translatable if it has NO translatable block children
if name == 'blockquote':
    for child in tag.children:
        if isinstance(child, Tag):
            child_name = child.name.lower()
            if child_name in TRANSLATABLE_ELEMENTS or child_name == 'div':
                return False
    return bool(tag.get_text(strip=True))
```

### Extended Inline Elements List

**Requirements listed:**
> `<em>`, `<strong>`, `<a>`, `<span>`

**Implementation added:**
```python
INLINE_ELEMENTS = {'a', 'em', 'strong', 'i', 'b', 'u', 'span', 'mark', 'small', 'del', 'ins', 'sub', 'sup'}
```

Added: `i`, `b`, `u`, `mark`, `small`, `del`, `ins`, `sub`, `sup`

This is a reasonable extension but not specified in requirements.

### Data Attribute for Tracking

**Not in requirements:**
Uses temporary `data-chunk-processed` attribute during extraction to prevent double-processing, then removes it:

```python
element['data-chunk-processed'] = 'true'
# ... later ...
del element['data-chunk-processed']
```

This is an implementation detail not mentioned in the plan.

### Single-Segment Optimization

**Implementation:**
When a chunk has only one segment (no inline tags), `has_inline_tags` is `False` and the delimiter is NOT used. This simplifies translation and avoids delimiter-related issues.

```python
if len(segments) == 1:
    plain_text = str(segments[0]).strip()
else:
    has_inline_tags = True
    plain_text = f" {DELIMITER} ".join(...)
```

Plan implied delimiters would always be used for mixed content, but didn't explicitly handle the single-segment case.

### Delimiter Mismatch Fallback

**Plan stated:**
> "Fallback: if the delimiter count in the response does not match the source, replace the entire paragraph's text with the translated string and strip inline tags from that element"

**Implementation:**
```python
if chunk.segments:
    chunk.segments[0].replace_with(translated_text.strip())
    for segment in chunk.segments[1:]:
        segment.replace_with('')
```

This clears remaining segments with empty strings. Note: This doesn't actually "strip inline tags" - it empties their text content. The tags remain in the HTML but are now empty. This is a subtle difference from the plan's wording.

---

## 3. Boilerplate Detection (`boilerplate.py`)

### Element-Type Filtering (Critical Fix)

**Original issue:**
Initial implementation used `element.get_text(strip=True)` which returned ALL descendant text. This caused `<body>` to match boilerplate patterns because its text included Gutenberg headers.

**Fix:**
Added element-type filtering to only check specific block elements:
```python
if element.name not in {'p', 'div', 'pre', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span'}:
    continue
```

And custom text extraction:
```python
def _get_element_text(element: Tag) -> str:
    # For elements with only one string child, use that
    strings = list(element.strings)
    if len(strings) == 1:
        return strings[0].strip()
    # ...
```

This is a significant implementation decision not in the requirements.

### Metadata Pattern Threshold

**Implementation:**
```python
return metadata_line_count >= 2
```

Requires at least 2 metadata patterns to identify a `<pre>` block as metadata. This threshold is arbitrary and not specified in requirements.

---

## 4. Translator (`translator.py`)

### Model Existence Check Logic

**Implementation:**
```python
if self.model not in model_names:
    model_base = self.model.split(':')[0]
    available_models = [m for m in model_names if m.startswith(model_base)]

    if not available_models:
        raise ValueError(...)
    elif self.model not in model_names:
        # Model exists with different tag, that's okay
        pass
```

If model `translategemma:27b` isn't found but `translategemma:latest` exists, it proceeds without error. This is lenient behavior not specified in requirements.

### Response Cleaning Patterns

**Implementation includes:**
```python
preamble_patterns = [
    "Here is the translation:",
    "Here is the Romanian translation:",
    "Translation:",
    "Romanian translation:",
    "The translation is:",
    "Here is your translation:",
    "I will translate this for you:",
    "Sure, here is the translation:",
]
```

This list is more extensive than what might be minimally necessary. These were chosen based on common LLM response patterns but not from requirements.

### Quote Stripping

**Implementation:**
```python
if (cleaned.startswith('"') and cleaned.endswith('"')) or \
   (cleaned.startswith("'") and cleaned.endswith("'")):
    cleaned = cleaned[1:-1].strip()
```

Removes wrapping quotes. Not in requirements.

### Timeout Configuration

**Implementation:**
- Connection check: 10 seconds
- Translation API: 300 seconds (5 minutes)

Not specified in requirements.

### Case-Insensitive Source Match

**Implementation:**
```python
if cleaned.strip().lower() == source_text.strip().lower():
    raise ValueError("Response equals source text")
```

Compares case-insensitively. Not specified in requirements.

---

## 5. Checkpoint (`checkpoint.py`)

### get_stats() Method

**Not in requirements:**
```python
def get_stats(self) -> Dict:
    return {
        "total_chunks": self.data.get("total_chunks", 0),
        "completed": self.completed_count(),
        "percent": ...,
        "last_updated": self.data.get("last_updated"),
    }
```

Utility method for statistics. Not used in main flow but available.

### Hash Verification Behavior

**Requirements stated:**
> "The `source_hash` is used to detect if the source file changed between runs and warn the user."

**Implementation:**
- Prints warning but CONTINUES anyway
- Does NOT stop execution
- Does NOT require user confirmation to proceed

This is permissive behavior - requirements implied stricter handling.

---

## 6. Display (`display.py`)

### TQDM Graceful Fallback

**Implementation:**
```python
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
```

If tqdm is not installed, falls back to simple progress printing. This resilience is not in requirements.

### Progress Bar Format

**Implementation:**
```python
bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]'
```

Custom format chosen during implementation, not specified in requirements.

### update_cached() Method

**Not in requirements:**
Separate method for updating progress when loading cached translations. Displays "[cached]" indicator.

---

## 7. Main Integration (`translate_book.py`)

### Error Handling Order

**Implementation checks:**
1. Input file exists
2. Input is a file
3. File extension warning (non-blocking)
4. Ollama connection (skipped in dry-run)
5. Read input HTML
6. Output file exists (checked AFTER dry-run, which differs from initial validation order)

The order of checks differs from the logical sequence implied in requirements.

### Interrupt Handling

**Implementation:**
```python
except KeyboardInterrupt:
    print("\n\nInterrupted! Progress has been saved to checkpoint.", file=sys.stderr)
    print(f"Resume with: python {sys.argv[0]} {args.input_file} --resume", file=sys.stderr)
    display.close()
    return 130
```

Provides helpful resume command. Not specified in requirements but good UX.

### Dry-Run Output Format

**Implementation:**
```
Dry run summary
────────────────────────────────────────
Source file:      ...
Total chunks:     ...
Est. input tok:   ...
Est. output tok:  ...
Est. time @ 40/s: ~Xm Ys
```

Uses box-drawing characters for separator. Not specified in requirements.

### Token Estimation Formula

**Plan:**
```python
def estimate_tokens(text: str) -> int:
    return int(len(text.split()) * 1.3)
```

**Implementation:** Same as plan.

---

## 8. Missing Features from Requirements

These items were in requirements but NOT implemented:

| Feature | Status | Notes |
|---------|--------|-------|
| `--no-skip-boilerplate` flag | Missing | Requirements don't mention a way to disable boilerplate skipping, but implementation has `--skip-boilerplate` with default True |
| Interactive overwrite prompt | Missing | Requirements: "Prompt user to confirm overwrite" - implementation errors instead |

---

## 9. Potential Issues

### 9.1 Delimiter Tokenization Risk

The delimiter `｜｜｜` (U+FF5C repeated) was chosen for being "unlikely to appear in English 19th-century prose." However:
- No verification that TranslateGemma correctly handles this character
- If the model splits/drops/merges these characters, inline tag preservation fails silently

**Recommendation:** Test with real translations to verify delimiter preservation.

### 9.2 Blockquote Detection Edge Case

```python
if child_name in TRANSLATABLE_ELEMENTS or child_name == 'div':
    return False
```

A `<blockquote>` containing only text and inline elements (no `<p>`) will still be a chunk. This is correct but the logic is complex.

### 9.3 Checkpoint Hash on Non-Existent Source

```python
def _hash_file(self, file_path: Path) -> str:
    if not file_path.exists():
        return ""
```

Returns empty string if source file doesn't exist. This could cause issues if checkpoint is loaded but source was moved.

### 9.4 Missing Validation: Empty Chunks

If `extract_chunks()` returns 0 chunks (e.g., all content is boilerplate), the tool proceeds normally and produces an output file. This edge case should be handled.

---

## 10. Code Quality Observations

### 10.1 Type Hints

Inconsistent use of type hints:
- `html_processor.py`: Uses `List`, `Optional`, `list` (mixed)
- `translator.py`: Uses `List`, `Dict`, `Optional`
- `checkpoint.py`: Uses `Dict`, `List`, `Optional`
- `display.py`: Uses `Optional` only

### 10.2 Import Organization

`translate_book.py` imports from local modules without package prefix:
```python
from html_processor import HTMLProcessor
```

This requires running from the `translate_book/` directory or having it in `PYTHONPATH`.

### 10.3 Missing `__init__.py`

The `translate_book/` directory lacks `__init__.py`, so it's not a proper Python package. This affects importability.

---

## Conclusion

The implementation is largely faithful to the specification with these notable deviations:

1. **No interactive prompting** - uses exit codes instead
2. **Extended boilerplate element filtering** - critical for correct behavior
3. **Lenient checkpoint loading** - warns but proceeds on mismatch
4. **Graceful tqdm fallback** - not required but improves robustness

The most significant risk is the delimiter preservation strategy, which depends on model behavior not explicitly verified.