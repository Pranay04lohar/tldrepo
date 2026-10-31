# DECISIONS

Running log of assumptions and choices. Newest entries at the top of each phase.

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

- The spec lives at `/Users/pranay/Dev:AI/AI_Engineering/Projects/explain-cli/SPEC.md`
  (the literal path `~/projects/explain-cli` in the spec does not exist). The
  project is built in that directory, and the Zsh integration in Phase C points
  at this real path.
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

The project path contains `Dev:AI`. `uv sync` succeeds, but `uv run` exits with
`error: path segment contains separator ':'` while launching the command; the
editable install itself is fine. Verified with `uv run -v`.

Decision: use the project virtualenv directly, `.venv/bin/python -m explain`,
and `.venv/bin/python -m pytest`. This is the spec's own allowed alternative in
section 14, is one process cheaper than `uv run`, and does not depend on
`uv run`'s path handling. The venv is pinned to CPython 3.12.16 (the `ollama`
Homebrew install pulled in 3.15, which uv would otherwise select).

### A4. Cache pruning only on a full-repo scan

Stale entries are removed only when the scan target is the repository root. A
subtree scan (`explain src/`) leaves entries for other directories intact, so a
later full run still has them.

### A5. `--no-ai` never writes fallbacks into the cache

Deterministic Tier 0 descriptions are cached (they are model-independent).
Metadata fallbacks for Tier 1 files are rendered but not cached, so a later
AI run is not blocked by a placeholder description.

### A6. `.gitignore` files are scanned

`.gitignore` itself is kept as a file entry (a useful one-liner in the map) and
is described deterministically. Ignore rules are still honoured; only the rule
files themselves show up in the tree.
