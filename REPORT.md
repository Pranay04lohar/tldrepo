# Final report

## What was built

`explain` is a local-only codebase map for the terminal: it scans the current
repository, builds an ASCII tree, and puts one short description beside every
file and directory. Deterministic Python does traversal, gitignore matching,
language detection, hashing, AST/regex skeletons, tiering, caching, rendering
and answer validation. Ollama is used only for files that need a description,
and only the skeleton is sent, never full source (except very small files).

| File | Responsibility |
| --- | --- |
| `explain/main.py` | argparse CLI, orchestration, phases, fallbacks, directory labels |
| `explain/scanner.py` | traversal, built-in gitignore matcher, skip rules, digests |
| `explain/tree_builder.py` | sorted directory-first tree, depth pruning |
| `explain/metadata.py` | Python AST + regex metadata, compact skeletons, neighbours |
| `explain/tiers.py` | tier assignment, deterministic/fallback descriptions, duplicates |
| `explain/cache.py` | atomic versioned JSON cache, validation and recovery |
| `explain/ollama_manager.py` | server ownership, readiness, load/unload, cleanup |
| `explain/analyzer.py` | batching, prompt, parsing, quality checks, escalation, budget |
| `explain/renderer.py` | compact Rich tree, footer, progress line, `--timing` |
| `tests/` | 120 tests, including a fake Ollama HTTP server |

## Dependencies

Installed with Homebrew (no sudo): `uv 0.13.6`, `python@3.12` (3.12.16),
`ollama 0.40.13`. Runtime dependency: `rich`. Development: `pytest`. The tool
never installs a service and never starts `ollama` as a login service.

Benchmark models pulled: `qwen2.5-coder:1.5b` (986 MB), `lfm3:1.7b` (1.7 GB),
`qwen3:1.7b` (1.4 GB), `qwen2.5-coder:3b` (1.9 GB).

## Benchmark and default

15 `pallets/flask` source files, one batch, three runs, model unloaded between
runs. Median wall seconds; full table and grading notes in `BENCHMARKS.md`.

| Model | Wall (s) | Score | Role |
| --- | --- | --- | --- |
| `qwen2.5-coder:1.5b` | 4.94 | 73% | `--fast` |
| `lfm3:1.7b` | 8.17 | 87% | **default** |
| `qwen3:1.7b` | 3.38 | 7% (format failure) | rejected |
| `qwen2.5-coder:3b` | 9.36 | 73% | reference / escalation |

Default: `lfm3:1.7b`, 1.7B parameters, 1.7 GB, `nvfp4` quantisation, 262k
context (from `ollama show`). The decision follows section 10: fastest model
at or above 80% correct. Rejected answers escalate once to 3b.

## Zsh integration

A marked, idempotent block is appended to `~/.zshrc`; backup at
`~/.zshrc.bak.20261031-231625`. `uv run` is unavailable because this checkout's
path contains `:` (uv rejects the path segment), so the function calls the
virtualenv directly:

```diff
+# >>> explain >>>
+# Local-AI codebase map. Module execution keeps relative imports working and
+# scans the current working directory, not this install directory.
+explain() {
+    "/Users/pranay/Dev:AI/AI_Engineering/Projects/explain-cli/.venv/bin/python" -m explain "$@"
+}
+# <<< explain <<<
```

Verified with `zsh -i -c 'cd /tmp/explain-gate.GHCeEI && explain --no-ai'`;
the output root was the test repo, so the working directory is preserved.

## Tests

`120 passed` in 3.2 s. Coverage includes scanning/gitignore/symlinks, tree and
width truncation, AST and regex metadata, tiers and duplicates, cache
invalidation/recovery/atomic writes, batching and `num_ctx`, parsing and every
quality check, escalation and fallbacks, budget cut-off, real vs owned Ollama
lifecycle, `keep_alive 0`, interference cleanup, warm runs and CLI combinations.

## Measurement

Target: `pallets/click` (`src/click`, 17 source files), default model, median
of three.

| Scenario | Target | Measured | scan | load | prefill | decode | cleanup | render |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Cold | < 20 s | 15.20 s | 0.00 | 0.92 | 2.31 | 8.05 | 0.02 | 0.00 |
| Warm | < 2 s | 0.23 s | 0.00 | 0 | 0 | 0 | 0 | 0.00 |
| Five modified | < 12 s | 4.27 s | 0.00 | 0.71 | 0.40 | 2.82 | 0.02 | 0.00 |

After every run `ollama ps` was empty. No process from our `Popen` handle
remained. The pre-existing Ollama menu-bar app was left untouched.

## Limitations

- lfm3 is terse but can speculate on mixed-directory batches; the spot check
  flagged 1 of 10 descriptions (“Compatibility layer for I/O streams on
  Windows” for `_compat.py`, which is broader than Windows).
- Cold time varies with answer length (11.9 to 16.2 s on the same 17 files).
- A very large checkout (226 files) can exceed the default 25 s budget; files
  left pending are described by deterministic fallbacks and picked up on the
  next run.
- Functionally rejected descriptions are cached as fallbacks so warm runs stay
  silent; use `--refresh` to retry them.
- `uv run` cannot be used from this colon-containing path; the venv entry point
  is the supported path.
