# DECISIONS

Running log of assumptions and choices. Newest entries at the top of each phase.

## Release preparation

### R1. Name availability: `tldrepo` is free (2026-11-01)

Checked before renaming:

```text
$ curl -s -o /dev/null -w "%{http_code}" https://pypi.org/pypi/tldrepo/json
404
$ which tldrepo
tldrepo not found
```

`404` means the PyPI project name is available, and no `tldrepo` command is
installed on this machine. The distribution name, import package, command and
cache directory all use `tldrepo`; the cache is `.tldrepo/`.

### R2. No migration from `.tldrepo/` (2026-11-01)

The product is new to other users, so there is no installed base to migrate.
Old `.tldrepo/` caches are simply ignored; `.tldrepo/` is created on first run
and contains a `.gitignore` with `*`.

## Phase A

### A1. Environment (step 1)

Measured on the build machine:

| Fact | Value |
| --- | --- |
| macOS | 27.0.1 (build 26A434) |
| Chip | Apple M5 |
| RAM | 17,179,869,184 bytes (16 GiB) |
| Disk free | 369 GiB (requirement: >= 10 GB) |
| git | 2.54.0 (Apple Git-157) |
| Python (system) | 3.9.6 (too old for the spec) |
| Python (installed) | 3.12.16 via Homebrew |
| uv | 0.13.6 via Homebrew |
| Ollama | 0.40.13 via Homebrew (no service started) |
| Shell | /bin/zsh (Ghostty) |

Assumptions:

- The spec lives in the project root (`SPEC.md`). The literal path
  `~/projects/tldrepo` in the spec did not exist on the build machine; the
  Zsh integration in Phase C points at the actual checkout.
- Prerequisites were installed with Homebrew after an explicit go-ahead, because
  "installing system software" is a Stop condition. No sudo was used; Homebrew
  is user-owned at `/opt/homebrew`.
- `brew services start ollama` was **not** run. The tool starts and stops its own
  server, and must never touch a pre-existing one.

### A2. Project layout

Follows section 6 exactly. Modules stay independent; only `main.py` orchestrates.
`requires-python >= 3.11`, hatchling build backend, Rich as the only runtime
dependency, pytest for tests.

### A3. Toolchain: `uv sync` works, `uv run` does not (colon in path)

The original checkout path contained a colon. `uv sync` succeeded, but `uv run`
exited with `error: path segment contains separator ':'` while launching the
command; the editable install itself was fine. Verified with `uv run -v`.

Decision: use the project virtualenv directly, `.venv/bin/python -m tldrepo`,
and `.venv/bin/python -m pytest`. The release checkout has no colon in its path,
so `uv run` works too, but the venv form remains the supported one. This is the spec's own allowed alternative in
section 14, is one process cheaper than `uv run`, and does not depend on
`uv run`'s path handling. The venv is pinned to CPython 3.12.16 (the `ollama`
Homebrew install pulled in 3.15, which uv would otherwise select).

### A4. Cache pruning only on a full-repo scan

Stale entries are removed only when the scan target is the repository root. A
subtree scan (`tldrepo src/`) leaves entries for other directories intact, so a
later full run still has them.

### A5. `--no-ai` never writes fallbacks into the cache

Deterministic Tier 0 descriptions are cached (they are model-independent).
Metadata fallbacks for Tier 1 files are rendered but not cached, so a later
AI run is not blocked by a placeholder description.

### A6. `.gitignore` files are scanned

`.gitignore` itself is kept as a file entry (a useful one-liner in the map) and
is described deterministically. Ignore rules are still honoured; only the rule
files themselves show up in the tree.

## Phase B

### B1. Numbered prompt is primary, JSON is a fallback (step 10)

The spec's prompt asks for `N|description` lines, so the parser is line-first
(`^\s*(\d+)\s*\|\s*(.+)$`). A JSON object with the same paths is accepted only
when no numbered line parsed, because small models sometimes ignore the format.
Text outside a JSON object is ignored.

### B2. Batches follow directory boundaries (step 10)

Files are grouped by parent directory, groups are ordered by their highest
priority, and the 3,500-token budget splits within that order. This keeps
neighbours meaningful and stopped the 1.5b model from mixing `src/flask` files
with unrelated example templates.

### B3. Default model is `lfm3:1.7b` (step 13)

With prompt v2 and conservative grading, `lfm3:1.7b` scored 87 percent correct
on the 15-file flask corpus at an 8.2 s median, so the section 10 rule selects
it as the fastest model at or above 80 percent. `qwen2.5-coder:3b` (9.4 s,
73 percent) is kept for benchmark comparison only; `--fast` uses
`qwen2.5-coder:1.5b` (4.9 s, 73 percent).

Real-project check: `src/click` cold runs measured 10.6 to 11.6 s (median
10.7 s), inside the 20 s target. lfm3's decode dominates, so its advantage
depends on how concisely it answers; the benchmark and the real run are both
reported in BENCHMARKS.md.

### B4. Failures are retried on the same model, then fall back (step 10)

Rejected lines (missing, `unclear`, vague filler, filename repetition, or
starting with "This file"/"contains") are retried once as a group on the same
model, at most 6 files, with a larger skeleton and up to 80 lines of real
source appended. The model never changes mid-run. If the retry still fails, a
deterministic fallback is used and cached. A failed batch never stops the run.

### B5. Unload before stopping (step 10/11)

The last request uses `keep_alive: 0`, and a `finally` path calls
`unload_model()` and waits for `/api/ps` to drop the model. Cleanup stops only
the `Popen` handle we created; a reused server is left running. Verified on
real runs: `ollama ps` is empty after exit.

### B6. Benchmark note: one transient 3b 500

The first 3b benchmark attempt got HTTP 500 from the Ollama runner while the
server process restarted. A rerun of all three 3b runs succeeded; the table
uses those values. The benchmark material (prompt v2, tolerant parser) is the
same for every model. This is recorded in BENCHMARKS.md rather than hidden.

### B7. Prompt v2 adds worked examples; the parser tolerates `File N|`

Small models copied the literal placeholder `N` and echoed file names until the
system prompt included two worked `-> N|...` examples. That raised lfm3 and 3b
from "filename repetition" to usable descriptions. lfm3 in turn prefixes lines
with `File `, so the parser accepts `File 3|...` and `-> 3|...` as well as
`3|...`. Prompt version is now 2, which invalidates v1 cache entries.

### B8. Rejected descriptions are cached as fallbacks

A file that passes through AI analysis but fails every quality check is cached
with its deterministic fallback (tier 0, keyed by the model and prompt version).
Without this, one permanently rejected file (`helpers.py`) made every warm run
send a request and cost about 4 s. Budget/connection stops are not cached, so a
rerun still makes progress. `--no-ai` still never writes fallbacks (A5).

### B9. Benchmark material is local and untracked

`.bench/` holds the cloned `pallets/flask` corpus, the 15-file subset, the
benchmark script and raw results. It is in `.gitignore`; only the summarized
numbers and the grading table are kept in BENCHMARKS.md.

## Post-Gate C improvements

### I1. Directory descriptions: built-in, one batched LLM call, fallback

Resolution order is the built-in name map, one LLM request for every remaining
unknown directory, then `Contains N files`. The request is capped at 8 words
per directory and uses each directory's children descriptions; quality checks
reuse the file cleaner (vague phrases, filename repetition) with an 8-word
limit. Results are cached under `hash(path + sorted child descriptions)` plus
the model and prompt version, so a warm run makes no directory request.

### I2. Dot-directories are opt-in

Directories whose name starts with `.` are skipped by default and counted as
`hidden-dir`. `--all` shows them, but `.git` and `.tldrepo` remain in the
built-in ignore set at every setting.

### I3. Colour is driven by cache `source`

Cache version 3 stores `source` per file and per directory. The renderer uses
it: bold purple directories, dim connectors/footer labels, green footer
numbers, cyan LLM descriptions, default docstring/rule, dim italic
fallback/pending. Version 2 caches migrate in place (`tier 0` → `rule`,
otherwise `llm`; old directory strings → `rule`). `NO_COLOR`, non-TTY output
and `--no-color` all disable ANSI; `--legend` is opt-in.

### I4. Pluralisation

`plural()` is used for directory fallbacks, footer pending counts, progress and
statistics: `1 file`, `2 files`, `1 subdirectory`, `2 subdirectories`.

### I5. Directory-call cost

On a 157-file click checkout with 17 unknown directories, the single directory
request added 5.1 s to an otherwise warm run (0.17 s → 5.26 s), which is over
the 2 s note threshold. It is one request, cached afterwards; the warm run
returns to 0.17 s and the benchmark target `src/click` has no unknown
subdirectories, so its cold/warm numbers are unaffected.
