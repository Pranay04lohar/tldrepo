# tldrepo 0.1.0 — release report

## Name decision

`tldrepo` was checked before any rename work:

```text
$ curl -s -o /dev/null -w "%{http_code}" https://pypi.org/pypi/tldrepo/json
404
$ which tldrepo
tldrepo not found
```

`404` means the PyPI name is available; no command of that name was already
installed. The distribution name, import package, console command and cache
directory are all `tldrepo` / `.tldrepo/`. No fallback name was needed.

## What was built

`tldrepo` is a local-only codebase map for the terminal. It scans the current
repository, prints a compact ASCII tree, and puts one short description beside
every file and directory. Deterministic Python handles traversal, `.gitignore`
matching, language detection, hashing, AST and regex skeletons, tiering,
caching, rendering and answer validation. Ollama is used only for descriptions
that need prose, and only compact skeletons are sent, never full source (except
very small files).

| Path | Responsibility |
| --- | --- |
| `tldrepo/main.py` | argparse CLI, orchestration, phases, fallbacks, directory labels |
| `tldrepo/scanner.py` | traversal, built-in gitignore matcher, skip rules, digests |
| `tldrepo/tree_builder.py` | sorted directory-first tree, depth pruning |
| `tldrepo/metadata.py` | Python AST + regex metadata, compact skeletons, neighbours |
| `tldrepo/tiers.py` | tiers, deterministic/config/directory descriptions, quality guards |
| `tldrepo/cache.py` | atomic versioned JSON cache, validation and recovery |
| `tldrepo/ollama_manager.py` | server ownership, readiness, load/unload, cleanup |
| `tldrepo/analyzer.py` | batching, prompts, parsing, quality checks, retries, budget |
| `tldrepo/renderer.py` | compact Rich tree, footer, progress line, `--timing` |
| `tldrepo/doctor.py` | Python, Ollama and model checks for `--doctor` |
| `tests/` | 149 tests, including a fake Ollama HTTP server and privacy guard |

## Files changed for the release

- Renamed `explain/` to `tldrepo/`, updated imports, tests, README, SPEC and the
  console entry point; `python -m tldrepo` and the `tldrepo` command both work.
- Cache moved from the old directory name to `.tldrepo/`, with
  `.tldrepo/.gitignore` containing `*`. No migration is performed.
- Directory descriptions now strip parentheticals, never end on an unmatched
  parenthesis, truncate on whole words at eight words, and reject concepts that
  are not supported by any child name or description.
- YAML/TOML/JSON labels are filename-derived instead of “Service configuration”
  (for example `pyproject.toml` → “Project dependencies” and
  `profile.example.yaml` → “Example candidate profile settings”).
- Footer reports AI-written directory labels (`N dirs by AI`).
- Added `--doctor`, friendly first-run Ollama/model messages, and a privacy test.
- Added packaging metadata, `LICENSE`, `CHANGELOG.md`, `CONTRIBUTING.md`, a
  product README and the GitHub Actions CI matrix (Ubuntu/macOS, Python
  3.11–3.13, with uv).
- Regenerated `uv.lock` for the `tldrepo` distribution.
- Updated the local `~/.zshrc` marked block; `explain` remains a personal alias.

## Tests

```text
$ .venv/bin/python -m pytest
149 passed in 4.15s

$ uv run pytest
149 passed in 4.13s
```

The baseline before release work was 138 tests; the release adds the
source-style rendering test, directory-label guard tests, doctor tests and the
privacy guard. Tests mock Ollama and need no server or downloaded model.

## Package verification

```text
$ uv build
Successfully built dist/tldrepo-0.1.0.tar.gz
Successfully built dist/tldrepo-0.1.0-py3-none-any.whl

$ uv venv /tmp/tl-venv
$ uv pip install dist/*.whl --python /tmp/tl-venv/bin/python
Installed ... tldrepo==0.1.0 (from file://.../dist/tldrepo-0.1.0-py3-none-any.whl)
```

The wheel contains only the `tldrepo` package, its metadata and `LICENSE`;
tests and development files are excluded. In a fresh `pallets/click` clone:

- `/tmp/tl-venv/bin/tldrepo --no-ai` rendered the full tree.
- `/tmp/tl-venv/bin/tldrepo` used the local model: `157 files scanned  32 files by AI  15 dirs by AI  0 files cached  124 files deterministic  16.76s`.
- `/tmp/tl-venv/bin/tldrepo --help` printed the expected usage.
- `/tmp/tl-venv/bin/tldrepo --doctor` passed Python, Ollama and model checks.
- `ollama ps` was empty afterwards.

## Performance

Hardware for every number: Apple M5, 16 GiB RAM, macOS 27.0.1, Ollama 0.40.13,
one request at a time. Target: `pallets/click`, `src/click` (17 Python source
files), default model `lfm3:1.7b`, median of three runs.

| Scenario | Target | Measured | Previous | Per-phase (scan / load / prefill / decode / cleanup / render) |
| --- | --- | --- | --- | --- |
| Cold | < 20 s | **10.37 s** | 11.66 s | 0.00 / 0.52 / 1.86 / 6.40 / 0.01 / 0.01 |
| Warm | < 2 s | **0.10 s** | 0.12 s | 0.00 / 0 / 0 / 0 / 0 / 0.00 |
| Five modified | < 12 s | **2.46 s** | 3.04 s | 0.00 / 0.52 / 0.34 / 1.40 / 0.01 / 0.00 |

No scenario regressed. `ollama ps` was empty after every run, and no Ollama
process started by the tool remained. The model comparison, grading notes and
directory-call cost are in `BENCHMARKS.md`.

## Models

| Flag | Model | Size | Role |
| --- | --- | --- | --- |
| default | `lfm3:1.7b` | 1.7 GB, `nvfp4` | Fastest benchmarked model at or above 80% correct |
| `--fast` | `qwen2.5-coder:1.5b` | 986 MB | Lower-memory option |

The default follows the measured benchmark: `lfm3:1.7b` scored 87% correct at
an 8.17 s median on the 15-file flask corpus. `qwen2.5-coder:3b` scored 73% at
9.36 s and is kept for comparison only. The model is configuration, never
hard-coded in analysis modules.

## Privacy and safety

- The only network destination is `OLLAMA_HOST`, default
  `http://127.0.0.1:11434`. Tests fail if package code imports another network
  module or contacts another host.
- The cache stores descriptions, hashes and source tags, never source code.
- A server that was already running is never stopped; only the `Popen` handle
  created by `tldrepo` is terminated.
- The model is unloaded after the run, including SIGINT/SIGTERM and `atexit`
  cleanup. `--no-ai` never contacts Ollama.

## Known limitations

- Local models can hallucinate. Descriptions are short and checked, and cyan
  marks AI-written text, but a confident wrong sentence remains possible.
- Cold time varies with answer length (roughly 10 to 12 s on the 17-file target).
- One batched directory call can add about 5.1 s on a checkout with many unknown
  directories; it is cached immediately.
- A large checkout can exceed the default 25 s budget; remaining files receive
  deterministic descriptions and are picked up on the next run.
- Rejected descriptions are cached as fallbacks to keep warm runs fast; use
  `--refresh` to retry them.

## Manual publishing checklist

Nothing was pushed to GitHub and nothing was uploaded to PyPI.

1. Create a public GitHub repository named `tldrepo` under your account.
2. Update the `Homepage`, `Repository`, `Issues` and `Changelog` URLs in
   `pyproject.toml` (and the clone URL in `CONTRIBUTING.md`) from
   `your-username` to your GitHub username.
3. Push the local repository and tag: `git push origin main` and
   `git push origin v0.1.0`.
4. Create a PyPI account and an API token for the `tldrepo` project (or use a
   scoped account token for the first upload).
5. Build fresh artifacts with `uv build`, then publish with
   `uv publish --token <PYPI_TOKEN>` (or set `UV_PUBLISH_TOKEN`).
6. Confirm the install paths: `uv tool install tldrepo` and
   `pipx install tldrepo`, then run `tldrepo --doctor` on a clean machine.
