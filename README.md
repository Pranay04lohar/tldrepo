# tldrepo

**TL;DR for any codebase. Local AI, seconds, nothing left running.**

`tldrepo` scans the repository you are standing in, draws a compact ASCII map,
and puts one short, truthful description beside every file and directory. It
answers with deterministic Python wherever it can, and asks a tiny local model
only when a description is genuinely worth generating. No account, no cloud,
no daemon left behind.

```text
tldrepo/
│
├── tests/                      Automated tests
│   ├── fake_ollama.py          Tests for fake_ollama
│   ├── test_analyzer.py        Tests for analyzer (20 tests)
│   └── test_cli.py             Tests for cli (16 tests)
├── tldrepo/                    Contains 13 files
│   ├── analyzer.py             Model communication: batching, prompts, parsing…
│   ├── cache.py                JSON cache under ``<repo>/.tldrepo/cache.json``
│   ├── config.py               Configuration values
│   ├── doctor.py               `tldrepo --doctor`: a short, non-destructive en…
│   ├── main.py                 CLI entry point and orchestration
│   ├── scanner.py              Filesystem traversal with built-in .gitignore m…
│   └── tiers.py                File tiers, deterministic descriptions and dire…
├── .gitignore                  Git ignore rules
├── pyproject.toml              Project dependencies
└── README.md                   Project overview, setup and usage
```

That sample is real output from this repository with `tldrepo --no-ai` and
`--depth 2`; long lines are elided by the terminal. Descriptions written by the
model are shown in cyan when colour is enabled.

## Install

```bash
uv tool install tldrepo
# or
pipx install tldrepo
```

Python 3.11 or newer is required. For AI descriptions you also need
[Ollama](https://ollama.com/download); `tldrepo --no-ai` works without it.

## Quick start

```bash
cd ~/my-project
tldrepo --doctor
tldrepo
```

The first run downloads no data and installs nothing. If Ollama is missing, the
tool tells you how to install it and how to keep working with `--no-ai`. If the
model is missing, it prints the exact `ollama pull <model>` command.

## Usage

| Command | Behaviour |
| --- | --- |
| `tldrepo` | Analyse uncached or modified files and show the full map |
| `tldrepo --no-ai` | Tree plus deterministic descriptions; never starts Ollama |
| `tldrepo --doctor` | Check Python, Ollama and the default model, then exit |
| `tldrepo --all` | Show dot-directories (`.git` and `.tldrepo` stay hidden) |
| `tldrepo --refresh` | Regenerate all eligible descriptions |
| `tldrepo --depth 3` | Limit the displayed tree depth |
| `tldrepo --stats` | Show language and file statistics |
| `tldrepo src/` | Analyse and display one directory |
| `tldrepo src/main.py` | Show one file: description and skeleton summary |
| `tldrepo --model NAME` | Override the model |
| `tldrepo --fast` | Use the fast model |
| `tldrepo --budget N` | Time budget in seconds (default 25) |
| `tldrepo --timing` | Show per-phase timings |
| `tldrepo --no-color` | Disable ANSI colour (also honours `NO_COLOR` and non-TTY) |
| `tldrepo --legend` | Show a one-line colour legend under the footer |

## How it works

1. **Deterministic first.** Traversal, `.gitignore`, language detection,
   hashing, Python AST, regex skeletons, tiers, cache, layout and answer
   validation are ordinary Python.
2. **Tiny local model second.** Only files that need prose are sent, as compact
   skeletons, in directory-grouped batches with `temperature: 0`.
3. **One short description per item.** Files get at most ten words; directories
   at most eight. Vague or invented answers are rejected.
4. **Cache.** Descriptions live in `.tldrepo/cache.json`, keyed by content hash,
   model and prompt version. A warm run never contacts Ollama.
5. **Nothing left running.** A model is unloaded after the run; a server started
   by `tldrepo` is stopped, and a pre-existing server is never touched.

AI-written descriptions are cyan. Docstring and rule descriptions use the
default colour, while fallbacks and pending items are dim italic. The footer
reports files and directories described by AI, cache hits, deterministic
descriptions, pending work and total time.

## Models

| Flag | Model | Size | Role |
| --- | --- | --- | --- |
| default | `lfm3:1.7b` | 1.7 GB, `nvfp4` | Fastest benchmarked model at or above 80% correct |
| `--fast` | `qwen2.5-coder:1.5b` | 986 MB | Lower-memory option |

Model names are configuration, not hard-coded into the analysis modules. Use
`--model NAME` for any Ollama model you already have. Sizes above are the
measured Ollama download sizes from the benchmark environment.

## Performance

These are measured numbers, not estimates. Hardware: Apple M5, 16 GiB RAM,
macOS 27.0.1, Ollama 0.40.13, one request at a time. Target:
`pallets/click`, `src/click` (17 Python source files), default model, median of
three runs.

| Scenario | Measured |
| --- | --- |
| Cold (no cache) | **10.37 s** |
| Warm (nothing changed) | **0.10 s** |
| Five files modified | **2.46 s** |
| Model resident after exit | **zero** (`ollama ps` empty) |

Cold time varies with answer length (10.1 to 10.7 s on the same 17 files). On a
full 157-file checkout with 17 unknown directories, one batched directory
request added 5.09 s on an otherwise warm run; it is cached immediately, and
the next run returns to about 0.17 s. Full tables and the model comparison are
in [`BENCHMARKS.md`](BENCHMARKS.md) and [`REPORT.md`](REPORT.md).

## Privacy

- The only network destination is `OLLAMA_HOST`, default
  `http://127.0.0.1:11434`. There is no telemetry, update check or cloud fallback.
- The cache stores descriptions, hashes and source tags, never source code.
- `.tldrepo/.gitignore` contains `*`, so the cache does not appear in
  `git status`.
- The tool never writes to the scanned repository except `.tldrepo/`.
- A test suite guard fails if package code introduces another network module or
  contacts a host other than `OLLAMA_HOST`.

## Limitations

- Local models sometimes hallucinate. Descriptions are kept short and checked
  for vague filler and invented directory concepts, but a confident wrong
  sentence is still possible. Cyan means “written by AI”; verify before relying
  on it.
- `tldrepo` needs files with readable names and skeletons. Minified, generated
  or binary files are skipped.
- A very large repository can exceed the default 25 s budget. Remaining files
  get deterministic descriptions and are picked up on the next run.
- Functionally rejected descriptions are cached as fallbacks so warm runs stay
  fast; use `--refresh` to retry them.
- Subtree scans keep cache entries outside the subtree for later full runs.

## Contributing

Issues and pull requests are welcome. See [`CONTRIBUTING.md`](CONTRIBUTING.md)
for setup with uv, running the tests, and how to propose a change. Tests mock
Ollama, so no model download is needed.

## License

MIT. See [`LICENSE`](LICENSE).
