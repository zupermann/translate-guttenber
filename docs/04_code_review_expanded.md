# Code Review — Book Translation CLI (Expanded)

Reviewed files:
- `translate_book.py`
- `html_processor.py`
- `translator.py`
- `checkpoint.py`
- `display.py`
- `boilerplate.py`
- `README.md`
- `install.sh`

## Overall Assessment

The project has a good shape overall:
- Clear module separation.
- Correct high-level architecture for HTML-preserving translation.
- Checkpoint/resume support is present.
- Debug/progress output is separated from main output.
- Boilerplate handling and inline-tag preservation are built into the design.

The main problems are not architectural. They are concentrated in a few implementation details that can cause:
- wrong CLI behavior,
- broken notifications,
- silent translation failures,
- unnecessary prompt complexity,
- avoidable slowdowns on larger books,
- weaker operational safety.

---

## What Is Good

### 1. Architecture is appropriate

The tool is split into HTML processing, translation, checkpointing, display, and CLI orchestration. That is the right shape for a long-running translation CLI.

### 2. HTML-first approach is implemented the right way

The code parses HTML, extracts text from nodes, translates plain text, then writes the translated text back into the soup tree. That is the correct strategy for preserving markup.

### 3. Resume support is already usable

Checkpoint save/load is straightforward and understandable. For long book jobs, this is one of the most important features, and the code already has the right concept.

### 4. Debug logging is operator-friendly

Putting debug/progress output on `stderr` is the correct choice for a CLI that writes a file. It avoids contaminating stdout and keeps the tool scriptable.

### 5. Prompt handling is centralized

The translator keeps prompt construction in one place instead of scattering it around the app. That will make prompt tuning much easier later.

---

## Critical Findings

### 1. `--skip-boilerplate` cannot be disabled

In `translate_book.py`:

```python
parser.add_argument(
    "--skip-boilerplate",
    action="store_true",
    default=True,
    help="Auto-detect and skip Gutenberg header/footer boilerplate (default: on)"
)
```

This is logically broken. `store_true` means the value becomes `True` when the flag is supplied, but `default=True` means it is already `True` even when the flag is absent. So the option is effectively always enabled.

### Impact

You cannot test the tool with boilerplate processing turned off, and the README implies an option that the user does not actually control.

### Fix

Use one of these patterns:

```python
parser.add_argument("--skip-boilerplate", action=argparse.BooleanOptionalAction, default=True)
```

or:

```python
parser.add_argument("--skip-boilerplate", dest="skip_boilerplate", action="store_true")
parser.add_argument("--no-skip-boilerplate", dest="skip_boilerplate", action="store_false")
parser.set_defaults(skip_boilerplate=True)
```

---

### 2. Telegram notifications are very likely broken

In `translate_book.py`:

```python
subprocess.run(
    ['~/.local/bin/telegram-notify', message],
    shell=True,
    check=False,
    capture_output=True
)
```

This mixes `shell=True` with a list argument. That is the wrong subprocess usage pattern. It also relies on `~` expansion inside a list element, which will not behave the way a normal shell command line does.

### Impact

Notifications may silently fail, and because exceptions are swallowed, you may never notice.

### Fix

```python
import os

subprocess.run(
    [os.path.expanduser('~/.local/bin/telegram-notify'), message],
    shell=False,
    check=False,
    capture_output=True
)
```

If you want shell parsing, pass a single string instead, but here `shell=False` is the cleaner approach.

---

## High Priority Findings

### 3. Failed translations can be silently written back as English

In `translator.py`, when all retries fail, the code returns the original source text and marks `success=False`:

```python
return TranslationResult(
    translated_text=source_text,
    ...,
    success=False,
)
```

But in `translate_book.py`, the caller does not check `result.success` before saving and applying the translation:

```python
translations[chunk.index] = result.translated_text
checkpoint.save(chunk.index, result.translated_text, len(chunks))
```

### Impact

A chunk can fail all retries and still be stored in the checkpoint and final output as untranslated English. That is one of the most important operational risks in the whole project.

### Fix

At minimum, warn loudly:

```python
if not result.success:
    print(f"
Warning: chunk {chunk.index} failed after all retries; source text kept.", file=sys.stderr)
```

Better options:
- add a `--strict` mode that aborts on failed chunk,
- write failed chunk indexes to a separate review file,
- mark failed chunks in the checkpoint explicitly.

---

### 4. Inline-tag mode is triggered too often

In `html_processor.py`:

```python
if len(segments) == 1:
    plain_text = str(segments[0]).strip()
else:
    has_inline_tags = True
    plain_text = f" {DELIMITER} ".join(...)
```

This means any multi-segment element becomes an inline-tag chunk, even if the split was caused by formatting quirks or line breaks rather than real inline markup that must be preserved semantically.

### Impact

The model gets unnecessary delimiter constraints on more chunks than needed. That increases prompt complexity and creates extra opportunities for delimiter mismatch.

### Fix

Do not force `has_inline_tags = True` just because there are multiple text segments. Let the earlier parent inspection determine it.

---

### 5. Delimiter retry path is awkward and can distort prompt intent

When a delimiter mismatch happens, the retry text is built as a long corrective instruction and then passed through `translator.translate(..., has_delimiters=False)`.

That means the retry prompt is no longer using the normal user prompt template cleanly. It also turns the source text into a meta-instruction block rather than a plain translation request.

### Impact

This may reduce translation quality on retries and makes debugging harder because retry prompts differ structurally from normal prompts.

### Better fix

Add a dedicated retry method in `translator.py`, for example:
- same system prompt,
- same translation task,
- one extra instruction line about preserving delimiter count,
- source text still placed in the normal text slot.

That keeps prompt behavior consistent.

---

## Medium Priority Findings

### 6. `apply_translations` does repeated linear scans

In `html_processor.py`, each translation lookup scans `self.chunks` linearly to find the matching chunk.

### Impact

This is O(n²) over the full document. For small books it does not matter much, but for large Gutenberg books it is unnecessary overhead.

### Fix

Create a lookup dict once:

```python
chunk_map = {c.index: c for c in self.chunks}
```

Then use `chunk_map.get(chunk_index)`.

---

### 7. Checkpoint membership checks are list-based

In `checkpoint.py`:

```python
return chunk_index in self.data["completed"]
```

### Impact

This is O(n) per check. Since it runs for every chunk, resume and normal processing both scale worse than necessary.

### Fix

Maintain an in-memory set alongside the serialized list.

---

### 8. Temporary processing markers can leak into output if an exception occurs

`html_processor.extract_chunks()` adds `data-chunk-processed='true'` attributes and removes them later. That cleanup happens only at the end of the function.

### Impact

If extraction crashes midway, those temporary attributes may remain in the soup and later appear in serialized HTML.

### Fix

Wrap marker cleanup in `try/finally`.

---

### 9. `last_error` is collected but effectively lost

In `translator.py`, `last_error` is assigned but never returned or logged usefully.

### Impact

When a translation fails after all retries, the caller loses the reason. That makes operational debugging harder than it needs to be.

### Fix

Either:
- add `error_message: str | None` to `TranslationResult`, or
- log the final exception before returning.

---

### 10. Output file is only written at the very end

The final HTML is serialized and written only after all chunks are translated.

### Impact

Checkpoint data protects translation progress, but there is no partially reconstructed HTML artifact during a long run. If the process fails near the end, you keep progress but not a browsable intermediate output.

### Recommendation

Not mandatory, but useful:
- periodically write a partial HTML snapshot every N chunks, or
- add a `--write-snapshots` option.

---

## Low Priority Findings

### 11. `check_connection()` has dead / confusing logic

In `translator.py`, the nested condition:

```python
elif self.model not in model_names:
    pass
```

appears inside a branch where that condition is already known to be true.

### Impact

It does not break behavior, but it makes the intent unclear.

### Fix

Replace the `pass` branch with a real warning or simplify the logic.

---

### 12. `datetime` is imported inside `save()`

In `checkpoint.py`, `datetime` is imported inside the method body.

### Impact

This is not a bug, but it is inconsistent with the rest of the file and slightly hurts readability.

### Fix

Move it to the module import section.

---

### 13. Debug wrapping may preserve awkward whitespace

In `display.py`, `textwrap.fill(... drop_whitespace=False)` can preserve odd leading whitespace in wrapped debug lines.

### Impact

This can make side-by-side debug output look slightly messy on some chunks.

### Fix

Use `drop_whitespace=True` unless preserving exact source spacing is intentional.

---

### 14. README overstates alias activation

`README.md` says the install script will source `.bashrc`, and `install.sh` prints `Alias activated` after running `source "$BASHRC"` inside the script.

### Impact

That affects only the subshell running the installer, not the user's current shell session. The alias will not become available in the parent terminal automatically.

### Fix

Change the message to:

```bash
echo "Open a new terminal or run: source ~/.bashrc"
```

---

### 15. README references tests, but no test files were provided

`README.md` suggests running:

```bash
python3 -m pytest tests/
```

but no `tests/` tree was included in the reviewed files.

### Impact

That is a documentation mismatch. It creates the impression that tests exist when they do not.

### Fix

Either add tests or remove the command until tests are actually present.

---

## Per-File Review

### `translate_book.py`

Strengths:
- Good orchestration flow.
- Clear CLI intent.
- `stderr` usage is appropriate.
- Checkpoint/resume logic is easy to follow.

Problems:
- Broken `--skip-boilerplate` flag behavior.
- Broken Telegram subprocess call.
- No explicit handling for `result.success == False`.
- Delimiter retry prompt is too ad hoc.
- `input_stem` is recomputed twice.

Recommendation:
- Fix this file first, because it contains the most user-visible issues.

### `html_processor.py`

Strengths:
- Good core approach: translate text nodes, not tags.
- Clear separation of skip zones, translatable elements, and inline elements.
- `serialize()` updating `lang="ro"` is a good touch.

Problems:
- `has_inline_tags` is over-triggered.
- `apply_translations()` uses repeated scans.
- cleanup of temporary attributes should be exception-safe.

Recommendation:
- This is the second file to fix after the CLI orchestrator.

### `translator.py`

Strengths:
- Centralized prompt and options.
- Retry behavior is conceptually correct.
- `/api/chat` usage is the right endpoint for this prompt style.

Problems:
- final error context is lost,
- connection-check logic is slightly muddled,
- fallback-to-source behavior is dangerous without caller-side escalation.

Recommendation:
- Keep the module, but make failures explicit and typed.

### `checkpoint.py`

Strengths:
- Correct idea.
- Atomic temp-write then rename is good.
- Hashing the source file is a strong design choice.

Problems:
- list-based membership checks,
- local import style.

Recommendation:
- Small refactor only; no redesign needed.

### `display.py`

Strengths:
- Separation of progress and debug output is good.
- `tqdm.write()` usage is the right idea.

Problems:
- minor formatting roughness,
- cached updates do not contribute token/time stats, which is fine but worth keeping intentional.

Recommendation:
- Only minor cleanup needed.

### `boilerplate.py`

Strengths:
- Right responsibility boundary.
- Pattern-based skipping is suitable for Gutenberg text.

Risks:
- regex-based boilerplate detection may still miss some Gutenberg variants,
- document-order marking after the END marker is a good idea but should be validated on several real Gutenberg samples.

Recommendation:
- Add fixture-based tests using a few real Gutenberg HTML files.

### `README.md`

Strengths:
- Clear quick-start usage.
- Command examples are useful.

Problems:
- overstates alias activation,
- references tests that were not included,
- documents `--skip-boilerplate` as a real user option even though the current CLI implementation cannot disable it.

### `install.sh`

Strengths:
- Straightforward and understandable.
- Alias update path is helpful.

Problems:
- misleading activation message,
- alias-based installation is convenient but less robust than installing an entry-point script.

Recommendation:
- Long-term, prefer a proper console entry point via `pyproject.toml` or a tiny wrapper script in `~/.local/bin`.

---

## Recommended Fix Order

### Phase 1 — Must fix before real use
1. Fix `--skip-boilerplate` CLI behavior.
2. Fix `notify_telegram()` subprocess invocation.
3. Add explicit handling for `result.success == False`.
4. Stop forcing `has_inline_tags = True` for every multi-segment chunk.

### Phase 2 — Improve reliability
5. Refactor delimiter retry into a dedicated translator method.
6. Preserve and surface `last_error`.
7. Make temporary marker cleanup exception-safe.
8. Add clearer warnings for checkpoint source/model mismatches.

### Phase 3 — Improve scalability and polish
9. Use dict lookup in `apply_translations()`.
10. Use set membership in checkpoint state.
11. Clean up README and installer messaging.
12. Add tests and sample fixtures.

---

## Tests That Should Exist

At minimum, add these tests:

### HTML processing
- paragraph with plain text only,
- paragraph with `<em>` and `<a>` inline tags,
- nested blockquote with child paragraphs,
- leaf `<div>` with text,
- skip zones inside `<script>`, `<style>`, `<pre>`, `<code>`.

### Boilerplate detection
- Gutenberg header block,
- START marker,
- END marker plus trailing license text,
- non-Gutenberg preface that should not be skipped.

### Translator behavior
- empty response retry,
- source-equals-response retry,
- success=False propagation,
- delimiter preservation retry path.

### Checkpointing
- save/load roundtrip,
- resume with completed chunks,
- source hash mismatch warning,
- model mismatch warning.

### CLI behavior
- `--dry-run`,
- output overwrite protection,
- `--resume`,
- `--no-skip-boilerplate` once implemented.

---

## Final Verdict

This is a **good beta-quality implementation**, not a throwaway prototype. The overall design is correct, and most of the work is already in the right places.

The code is **not yet production-safe for unattended long book runs** because of three things:
- failed chunks can silently stay untranslated,
- notifications are likely broken,
- one important CLI flag does not actually behave as documented.

Once the Phase 1 fixes are applied, the tool becomes much safer to use on real Gutenberg books. After the Phase 2 and Phase 3 fixes, it should be a solid long-running CLI for your local translation workflow.
