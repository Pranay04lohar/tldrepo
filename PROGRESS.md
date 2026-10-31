# PROGRESS

## Release preparation (2026-11-01)

- [x] Name availability: PyPI `tldrepo` returned 404; no `tldrepo` command installed
- [x] Output polish: directory labels strip parentheticals and invented concepts,
      config labels are filename-derived, footer counts AI directories, and a
      source-style test covers llm/docstring/rule/fallback
- [x] Rename: package/command/module `tldrepo`, cache `.tldrepo/`, README/SPEC/tests
- [x] Personal paths removed from the repository
- [x] Packaging: hatchling metadata, entry point, LICENSE, CHANGELOG, CONTRIBUTING
- [x] First-run experience: friendly Ollama/model messages, `--doctor`, and a
      privacy test that only allows `OLLAMA_HOST` network traffic
- [x] README product page with measured performance, models, privacy, limits
- [x] CI matrix: Ubuntu and macOS, Python 3.11 to 3.13, via uv

## Phase A: deterministic core (steps 1 to 8)

Gate A: 90 tests pass; `tldrepo --no-ai` renders this repo in 0.02 s.

- [x] Step 1: environment inspected and logged in DECISIONS.md
- [x] Step 2: project scaffolding, pyproject, git
- [x] Step 3: scanner with .gitignore support
- [x] Step 4: tree builder and renderer skeleton
- [x] Step 5: metadata and skeleton extraction (49 tests green)
- [x] Step 6: tiering and deterministic descriptions
- [x] Step 7: cache
- [x] Step 8: CLI wiring; **Gate A passed**

## Phase B: Ollama, batching, cache, benchmark (steps 9 to 13)

Gate B: 121 tests pass (including a fake-Ollama HTTP server for lifecycle and
request-shape tests); real runs on `pallets/flask` (226 files) and
`pallets/click` (17-file target) completed and left `ollama ps` empty; the
benchmark is in BENCHMARKS.md.

- [x] Step 9: Ollama manager lifecycle + tests
  (reuse vs ownership, readiness timeout, safe env, keep_alive 0, unload,
  verify with /api/ps, terminate/wait/kill, atexit + signal cleanup)
- [x] Step 10: analyzer (directory-grouped batching, numbered prompts, quality
  checks, one retry with more source, cache after each batch, time budget)
- [x] Step 11: Rich progress line, footer counters, `--timing` phases
  (scan, metadata, load, prefill, decode, cleanup, render)
- [x] Step 12: real end-to-end run; warm `--no-ai` 0.16 s; model unloaded
- [x] Step 13: model benchmark; default set to `lfm3:1.7b` (87% correct,
  8.2 s median on 15 files); **Gate B passed**

## Phase C: integration and measurement (steps 14 to 16)

- [x] Step 14: Zsh integration (`~/.zshrc` marked block, backup, diff shown,
  `zsh -i` verified from a `/tmp` test repo)
- [x] Step 15: measurement protocol on `pallets/click` (`src/click`, 17 files):
  cold 10.68 s, warm 0.12 s, five modified 2.88 s; `ollama ps` empty
- [x] Step 16: final report (`REPORT.md`); **Gate C passed**

## Post-Gate C improvements

- [x] Directory descriptions: built-in map, one batched LLM call for all unknown
  directories, cached by children hash + model + prompt version, plural fallback
- [x] Dot-directories hidden by default; `--all`; `.git`/`.tldrepo` always hidden
- [x] Cache v3 with `source` per description and v2 migration
- [x] Source-based colour, `NO_COLOR`/non-TTY/`--no-color`, `--legend`
- [x] Pluralisation across directory fallbacks, footer, progress and stats
- [x] 138 tests; benchmark re-run (cold 11.66 s, warm 0.12 s)
