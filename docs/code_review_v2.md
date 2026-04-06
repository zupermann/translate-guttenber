# Code Review — Book Translation CLI (v2, re-review)

This is a re-review of the updated files uploaded on 2026-04-06. The previous
review raised 15 findings. This document tracks which were fixed, which remain,
and what new issues the changes introduced.

---

## What Was Fixed

All four Phase 1 items from the previous review have been addressed.

| Previous finding | Status |
|---|---|
| `--skip-boilerplate` always `True` (BooleanOptionalAction missing) | ✅ Fixed |
| `notify_telegram` broken subprocess call | ✅ Fixed |
| `result.success == False` silently kept | ✅ Fixed — warning printed, error_message surfaced |
| `has_inline_tags` forced True for all multi-segment chunks | ✅ Fixed |
| `apply_translations()` linear scan (O(n²)) | ✅ Fixed — dict lookup |
| Temporary marker cleanup not exception-safe | ✅ Fixed — `try/finally` |
| `_completed_set` not maintained (O(n) lookups) | ✅ Fixed — Set[int] in checkpoint |
| `datetime` local import in `save()` | ✅ Fixed — module-level |
| `drop_whitespace=False` in display wrapping | ✅ Fixed |
| `error_message` not in `TranslationResult` | ✅ Fixed |
| `check_connection()` confusing nested branch | ✅ Fixed — cleaner structure |
| README overstated alias activation | ✅ Fixed |
| README referenced non-existent `pytest tests/` | ✅ Fixed — removed |
| `install.sh` misleading "Alias activated" message | ✅ Fixed |

---

## Remaining and New Findings

---

### 1. `apply_translations` does not clear leftover segments in the non-inline path

**Severity: High — produces corrupt output**

In `html_processor.py`, the fix for `has_inline_tags` over-triggering introduced
a correctness bug. The non-inline path of `apply_translations` only replaces
`segments[0]` but does not clear `segments[1:]`:

```python
if not chunk.has_inline_tags:
    if chunk.segments:
        chunk.segments[0].replace_with(translated_text)
        # segments[1:] are never touched
```

Now that multi-segment chunks without actual inline markup set
`has_inline_tags = False`, any `<p>` whose text happened to be split across
two `NavigableString` objects (which BeautifulSoup does when HTML has
whitespace nodes or irregular structure) will produce output like:

```html
<!-- source -->
<p>Hello world</p>

<!-- after translation if BS4 produced two strings: "Hello " and "world" -->
<p>Bună ziua world</p>
```

The trailing original-English `NavigableString` remains in the DOM because it
was never replaced.

**Fix:**

```python
if not chunk.has_inline_tags:
    if chunk.segments:
        chunk.segments[0].replace_with(translated_text)
        for seg in chunk.segments[1:]:
            seg.replace_with('')
```

This is the same strategy already used in the delimiter-mismatch fallback path —
it just needs to be applied universally when `has_inline_tags` is False and
there are multiple segments.

---

### 2. `translate_with_delimiter_retry` retry call is not exception-guarded

**Severity: High — crashes entire run on network error during retry**

In `translator.py`, the second API call inside `translate_with_delimiter_retry`
calls `_call_api()` directly:

```python
retry_result = self._call_api(retry_messages)
```

`_call_api()` calls `requests.post()`, which can raise
`requests.exceptions.RequestException` (timeout, connection reset, etc.).
The first attempt goes through `translate()`, which catches
`requests.exceptions.RequestException` and retries gracefully.
The delimiter retry call does not — a network error here raises an unhandled
exception that propagates up to `main()`, which only catches `KeyboardInterrupt`.

The entire translation run would crash instead of gracefully marking this chunk
as failed.

**Fix:** Wrap the retry call:

```python
try:
    retry_result = self._call_api(retry_messages)
    cleaned = self._clean_response(retry_result['message']['content'])
except (requests.exceptions.RequestException, KeyError, ValueError) as e:
    return TranslationResult(
        translated_text=text,
        success=False,
        error_message=f"Delimiter retry API call failed: {e}",
    )
```

---

### 3. `check_connection` silently ignores model tag mismatch

**Severity: Medium — unexpected model may run silently**

In `translator.py`, when the exact model name is not found but a model with the
same base name is:

```python
if not available_models:
    raise ValueError(...)
# else: model exists with different tag, warn but continue
```

The comment says "warn but continue" but there is no actual warning printed.
The user may be running `translategemma:27b` while the checkpoint was created
with `translategemma:12b` and receive no feedback.

**Fix:**

```python
if available_models:
    print(
        f"Warning: Model '{self.model}' not found exactly. "
        f"Found: {available_models[0]}. Continuing with configured model name.",
        file=sys.stderr
    )
```

---

### 4. `start_time` in `translate()` is referenced outside the loop it is set in

**Severity: Low — only a problem if MAX_RETRIES is ever changed to 0**

```python
for attempt in range(MAX_RETRIES):
    start_time = time.time()
    ...

# All retries failed
return TranslationResult(
    ...
    duration_seconds=time.time() - start_time,  # NameError if loop never ran
```

This works correctly with the current `MAX_RETRIES = 3`, but is technically
fragile. Setting `MAX_RETRIES = 0` would cause a `NameError`.

**Fix:** Initialize before the loop:

```python
start_time = time.time()
for attempt in range(MAX_RETRIES):
    ...
```

---

### 5. Unused imports

**Severity: Low — cosmetic / linting**

- `display.py`: `from typing import Optional` is imported but never used.
- `checkpoint.py`: `from typing import Dict, List, Optional, Set` — `List` is not used.

**Fix:** Remove the unused names from each import line.

---

### 6. `input_stem` is computed twice in `translate_book.py`

**Severity: Low — redundancy**

```python
# 2. Resolve output path
if args.output is None:
    input_stem = args.input_file.stem    # first assignment
    ...

# 3. Resolve checkpoint path
if args.checkpoint is None:
    input_stem = args.input_file.stem    # second assignment
```

**Fix:** Compute it once above both blocks:

```python
input_stem = args.input_file.stem
if args.output is None:
    ...
if args.checkpoint is None:
    ...
```

---

### 7. Delimiter retry duration is hardcoded to 0.0

**Severity: Low — affects token rate stats accuracy**

In `translate_with_delimiter_retry`, the successful retry result always returns
`duration_seconds=0.0`. This means chunks that required a delimiter retry do not
contribute accurate timing to the final stats summary in `Display.close()`.

**Fix:** Capture a start time before the retry call and compute the elapsed time
for the full `translate_with_delimiter_retry` scope.

---

### 8. `pip3 install --break-system-packages` in `install.sh`

**Severity: Low — risky on some Linux distributions**

The fallback install chain in `install.sh`:

```bash
pip3 install -r "$SCRIPT_DIR/requirements.txt" --user || pip3 install -r ... --break-system-packages 2>/dev/null || pip3 install -r ...
```

The `--break-system-packages` flag intentionally overrides the externally
managed environment guard added in Python 3.11+ on Debian/Ubuntu systems. Using
it silently (errors suppressed with `2>/dev/null`) can corrupt system packages
without any visible warning to the user.

**Recommendation:** If `--user` fails, print a clear message asking the user
to create a virtualenv, rather than falling back to `--break-system-packages`.

---

### 9. No tests

**Severity: Medium — affects confidence for future changes**

No `tests/` directory was provided. The previous review listed the minimum test
surface. The fixed bugs in this re-review (particularly finding #1 above — the
silent leftover-segment corruption) are exactly the kind of regression that a
unit test over `apply_translations` would have caught immediately.

Minimum recommended test: given a `<p>` whose BS4 tree contains two
`NavigableString` children with no inline tags, assert that after
`apply_translations` the element contains only the translation and no trailing
English text.

---

## Updated Fix Priority

### Must fix before running on real books
1. **Segments not cleared in non-inline path** — produces corrupt translated HTML.
2. **Delimiter retry not exception-guarded** — crashes entire run on transient network error.

### Should fix soon
3. Silent model tag mismatch — misleading operational behavior.
4. `start_time` outside loop — fragile but harmless today.
5. Unused imports — clean up for linting.

### Low priority / polish
6. `input_stem` double computation.
7. Delimiter retry duration tracking.
8. `--break-system-packages` fallback in installer.
9. Add unit tests.

---

## Overall Assessment

The round of fixes was thorough and addressed all the right things. Most of the
operational safety issues from the first review are now resolved. The code is
in a significantly better state.

The two remaining high-severity items (#1 and #2) are both introduced or exposed
by the round of fixes themselves, which is expected — fixing `has_inline_tags`
over-triggering correctly exposed a gap in how non-inline multi-segment chunks
are written back to the DOM. The fix is a one-liner.

After applying findings #1 and #2, this code is safe to run on full Gutenberg
books in unattended mode.
