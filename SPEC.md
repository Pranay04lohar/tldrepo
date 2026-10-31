# tldrepo: OpenCode Build Spec (v2)

A fast, local-AI codebase map for the terminal. This is the revised spec. It keeps the original design and adds speed rules, a model benchmark, safety rules and phase gates.

## How to use this file

1. Save this whole document as `~/projects/tldrepo/SPEC.md`.
2. Paste only this launch prompt into OpenCode:

```text
Read ~/projects/tldrepo/SPEC.md completely. Follow its Working Rules, Phase Gates and Speed Rules exactly. Start at Phase A and continue through Phase C without stopping unless a gate fails or a Stop condition in the Working Rules is hit. Do not ask me questions otherwise.
```

---

# 0. Role and Goal

Act as a senior Python engineer specialising in CLI tools, local LLM inference and performance optimisation.

Build, test and install a lightweight standalone Python utility called `tldrepo`. It shows the structure and purpose of an unfamiliar codebase from my Ghostty terminal.

```bash
cd ~/projects/my-project
tldrepo
```

Do not only plan or describe. Build it, test it, benchmark it and integrate it into my Zsh environment.

## Priorities, in order

1. **Speed.** First run under 20 seconds for about 25 files. Warm run under 2 seconds.
2. **Description quality.** Short, true, specific. A boring true description beats a confident wrong one.
3. **Safe process management.** Never leave a model loaded or an Ollama process running that this tool started.
4. **Minimal dependencies.**

---

# 1. Working Rules

- Keep `PROGRESS.md`, `DECISIONS.md` and `BENCHMARKS.md` in the project root. Update them after every step: what was done, assumptions made, what is next. Re-read them whenever you are unsure of earlier context.
- Make one git commit per step with a clear message.
- Never claim a step is done without running its tests or commands and showing the real output.
- Do not ask me questions. Make reasonable assumptions and log them in `DECISIONS.md`.
- **Stop and ask only for:** sudo, installing system software, or deleting anything outside the project directory.
- Never modify source files of any repository being scanned. The only thing written inside a target repo is `.tldrepo/`.
- Do the `.zshrc` change last (see section 14).

---

# 2. Phase Gates

**Phase A: deterministic core, no LLM (steps 1 to 8)** Gate: all tests pass, and `tldrepo --no-ai` renders a correct tree on a real repository.

**Phase B: Ollama, batching, cache, benchmark (steps 9 to 13)** Gate: mocked tests pass, one real run succeeds, `ollama ps` shows nothing loaded afterwards, and `BENCHMARKS.md` contains the model comparison.

**Phase C: integration and measurement (steps 14 to 16)** Gate: the Zsh function works from a different directory, and measured timings are reported.

Do not start a phase until the previous gate passes.

---

# 3. Speed Rules (override anything that conflicts below)

**Why:** a model's time is spent reading input (prefill) and writing output (decode). Both are expensive for small local models. So we send as little as possible, ask for as little as possible, and skip the LLM wherever Python can answer.

1. **Skeleton input, not source.** The LLM sees a compact skeleton per file (section 7), never full source, unless the file is under about 40 lines.
2. **Three file tiers** (section 8). The fastest LLM call is the one never made.
3. **Tiny output.** One line per file, format `N|description`, maximum 10 words. No JSON, no repeated paths.
4. **Deterministic sampling.** `temperature: 0`.
5. **No thinking tokens.** Always send `"think": false`. If Ollama rejects the field for a model, retry once without it and log that in `DECISIONS.md`.
6. **Explicit context size.** Always set `num_ctx` explicitly. Ollama's default is small and silently truncates input, which produces bad descriptions with no error.
7. **Token-budget batching** (section 9), grouped by directory.
8. **Identical system prompt, always first**, so Ollama can reuse its processed prefix between batches.
9. **Overlap the model load.** As soon as the cache check shows there is work to do, load the model in a background thread while prompts are being built.
10. **Time budget.** Default 25 seconds, flag `--budget SECONDS`. Process files in priority order. When the budget would be exceeded, stop cleanly, render partial results, and finish the rest on the next run.
11. **Warm path must be instant.** If nothing needs analysis, never contact Ollama. Use lazy imports so startup is fast. Target under 2 seconds total.
12. **Sequential inference first.** No parallel requests. Only test `OLLAMA_NUM_PARALLEL=2` after benchmarking, and keep it only if wall time drops by more than 15 percent.

---

# 4. Architecture

**Deterministic code handles:** filesystem traversal, hierarchy, filtering, metadata, language detection, hashing, Python AST, skeleton building, tiering, cache, tree rendering, and quality checks on LLM output.

**The local LLM handles only:** turning a skeleton into one short, accurate description, and describing directories whose purpose is not obvious from a name map.

Do not use an LLM for anything deterministic Python can do reliably.

---

# 5. Technology Stack

| Component | Technology |
| --- | --- |
| Language | Python 3.11+ |
| Package manager | uv |
| Terminal formatting | Rich (only runtime dependency) |
| CLI arguments | argparse |
| Filesystem | pathlib |
| Code analysis | Python `ast` |
| Hashing | SHA-256 (hashlib) |
| Cache | JSON |
| HTTP to Ollama | stdlib `urllib` and `json` (no requests/httpx) |
| Model | Configurable, chosen by benchmark (section 10) |

Do not use Typer, Click, tree, cloc, ctags or other external utilities. The app must not depend on OpenCode or any coding assistant at runtime.

`pyproject.toml`: `requires-python >=3.11`, a build system (hatchling), and the package installed editable via `uv sync`.

---

# 6. Project Structure

```text
tldrepo/
├── tldrepo/
│   ├── __init__.py
│   ├── __main__.py        # enables `python -m tldrepo`
│   ├── main.py            # argparse + orchestration
│   ├── scanner.py
│   ├── tree_builder.py
│   ├── metadata.py        # AST + skeleton builder
│   ├── tiers.py           # tier assignment + deterministic descriptions
│   ├── analyzer.py        # batching, prompts, quality checks
│   ├── ollama_manager.py
│   ├── cache.py
│   ├── renderer.py
│   └── config.py
├── tests/
│   ├── fixtures/
│   ├── test_scanner.py
│   ├── test_tree_builder.py
│   ├── test_metadata.py
│   ├── test_tiers.py
│   ├── test_cache.py
│   ├── test_analyzer.py
│   ├── test_ollama_manager.py
│   ├── test_renderer.py
│   └── test_cli.py
├── SPEC.md
├── PROGRESS.md
├── DECISIONS.md
├── BENCHMARKS.md
├── pyproject.toml
└── README.md
```

Keep modules independent. Avoid unnecessary abstractions.

---

# 7. Scanner and Metadata

## scanner.py

- **Root detection:** nearest ancestor containing `.git`, otherwise the current directory. The cache lives at `<root>/.tldrepo/`.
- `tldrepo src/` limits scanning and display to that subtree. `tldrepo src/main.py` shows one file.
- Scan recursively with configurable depth. Do not follow symlinks.
- **Respect `.gitignore`** using a built-in matcher (no git CLI).
- Detect binary files by a null-byte check on the first 8 KB. Skip binaries, oversized files (configurable, default 200 KB), empty files, lockfiles, generated files, images, datasets and build outputs.
- Handle unreadable files gracefully.
- Default ignored directories: `.git`, `.venv`, `venv`, `__pycache__`, `node_modules`, `dist`, `build`, `.next`, `.idea`, `.vscode`, `.pytest_cache`, `.mypy_cache`, `.tldrepo`.
- Exclusions are configurable.
- On first creation of `.tldrepo/`, write `.tldrepo/.gitignore` containing `*` so the cache never appears in `git status`.

## metadata.py

Python (via `ast`): module docstring, classes, functions, methods, imports, line count, size.

Other languages (JS, TS, Java, Go, Rust, and so on): extension, language, size, plus a **cheap regex skeleton** of declaration lines (`export`, `function`, `class`, `func`, `pub fn`, `interface`, `type`, and so on). No deep semantic analysis.

## Skeleton format (what the LLM sees, about 150 to 250 tokens per file)

```text
FILE 3: services/pipeline.py
Doc: (none)
Imports: requests, db.repository, services.relevance
Classes: JobPipeline
Functions: JobPipeline.run, JobPipeline.fetch_jobs, JobPipeline.score_and_save
Neighbours: relevance.py, scheduler.py   (same directory)
```

If a file yields no structure (a script with no defs), include its first 40 lines. Cap every skeleton at about 250 tokens. Estimate tokens as characters divided by 4.

---

# 8. File Tiers (decide before any LLM call)

**Tier 0: deterministic, no LLM**

- Test files. Description: `Tests for <module> (<N> tests)`.
- README, docs, config, package metadata, lockfile-adjacent files, trivial `__init__.py`.
- Files whose module docstring first line is a usable one-liner (a sentence of 12 words or fewer, not generic). Controlled by config `use_docstrings` (default true).
- Files whose hash was already seen in this run: reuse that description.

**Tier 1: LLM, skeleton input** Everything else that matters. Priority order: entry points, services and core logic, API routes and controllers, repositories, external integrations, configuration modules.

**Tier 2: escalation (rare)** If a Tier 1 answer fails the quality checks (section 9), re-ask once for that file with the first 120 lines of source. If it still fails, use a deterministic fallback such as `Python module: JobPipeline (3 methods)`.

Do not skip important source files just because they are small.

**Directory descriptions:** first use a built-in name map (`tests/` is "Automated tests", `utils/` is "Shared helper functions", `docs/`, `scripts/`, `config/`, `models/`, `api/`, and similar). For unknown directories, make one small text-only LLM call per run that sees only each directory's name and its children's descriptions. Cache these keyed by a hash of the sorted children descriptions.

---

# 9. LLM Analysis

## Prompt (system message, identical on every request, always first)

```text
You describe source files for a codebase map.
For each numbered file below, write ONE description.

Rules:
- Output exactly one line per file in the form: N|description
- Maximum 10 words. State WHAT the file is responsible for.
- Use only the evidence given. Do not invent functionality.
- If the purpose is unclear, write: N|unclear
- No extra text, no markdown.

Examples:
FILE 1: db/repository.py
Imports: sqlalchemy, models.user
Classes: UserRepository
Functions: UserRepository.get, UserRepository.save, UserRepository.delete
-> 1|Database access layer for user records

FILE 2: cli/main.py
Imports: argparse, core.runner
Functions: main, build_parser
-> 2|Command-line entry point that parses arguments and runs the app

FILE 3: adapters/slack.py
Imports: requests
Classes: SlackClient
Functions: SlackClient.post_message
-> 3|Slack client for sending messages
```

## Request settings (Ollama `/api/chat`)

```python
{
  "model": cfg.model,
  "messages": [system_msg, user_msg],
  "stream": False,
  "think": False,
  "keep_alive": 0 if last_request else "5m",
  "options": {"temperature": 0, "num_ctx": computed, "num_predict": computed},
}
```

- `num_ctx` = system prompt + batch input + expected output + 25 percent margin (round up, cap in config).
- `num_predict` = about 20 tokens per file in the batch, plus margin.

## Batching

- Batch by token budget, about 3,500 input tokens per batch (configurable), not by file count. Group files from the same directory so neighbours give context.
- Extra input limits: max skeleton size, max file size, max batch size.
- A single file that exceeds the limit is sent alone with a truncated skeleton, never crashes.
- Timeouts and a retry limit (default 1 retry) per request. One failed batch must never stop the run; its files fall back to deterministic descriptions.
- Save to the cache after **every** batch so no work is lost on interruption.

## Quality checks on every answer (deterministic, no LLM)

Parse with the regex `^\s*(\d+)\s*\|\s*(.+)$`. Then reject and escalate (Tier 2) if the description:

- is missing, or says `unclear`,
- is longer than 14 words (truncate at 12 if it is otherwise good),
- contains vague filler: `various`, `utility functions`, `helper functions`, `helper methods`, `miscellaneous`, `misc`, `contains code`, `handles things`,
- merely repeats the file name.

---

# 10. Model Selection and Benchmark

The model is a config value, never hard-coded in modules. Overridable with `--model`.

## Candidates

| Model | Role |
| --- | --- |
| `qwen2.5-coder:1.5b` | fast baseline |
| `lfm3:1.7b` | new challenger (Liquid AI, released Oct 2026, hybrid architecture, pitched for fast edge inference) |
| `qwen3:1.7b` with `think: false` | same-size rival |
| `qwen2.5-coder:3b` | quality reference |

## Procedure (Phase B)

1. Check `ollama --version`. If `lfm3:1.7b` fails to load, report it in `BENCHMARKS.md`, tell me to update Ollama, skip it and continue. Do not work around it.
2. You may `ollama pull` only the candidates above. Report each download size first. Check free disk space (at least 10 GB) before pulling.
3. Use the same 15 files from a real Python repository for every model. Run each model 3 times. Record median wall time, split into load, prefill, decode and cleanup if possible.
4. Grade each description conservatively: **correct** (specific and true), **vague**, or **wrong** (invented or incorrect). Print a table of the file skeleton next to each description so I can verify your grades.
5. **Decision rule:** the default is the fastest model that scores at least 80 percent correct. If none do, use `qwen2.5-coder:3b`. Record the choice and reasoning in `DECISIONS.md`.
6. Keep `--model` and a `--fast` flag (uses `qwen2.5-coder:1.5b`) available.

---

# 11. Ollama Lifecycle (ollama\_manager.py)

This is the most safety-critical part.

```text
tldrepo
  -> cache check says work is needed?
       no  -> render immediately, never touch Ollama
       yes -> is Ollama already running?   (GET /api/version, honour OLLAMA_HOST, default http://127.0.0.1:11434)
                yes -> reuse it, ownership = False
                no  -> start it ourselves, ownership = True
  -> load model (empty /api/generate request) in a background thread
  -> analyse batches, caching after each
  -> final request sends keep_alive 0; also unload in a finally block
  -> verify with /api/ps that no model of ours is resident
  -> ownership True: stop OUR process; ownership False: leave it untouched
  -> render tree
```

Requirements:

- Never terminate a pre-existing Ollama service, including the macOS menu-bar app. Never kill processes by name matching.
- When starting our own server: `subprocess.Popen(..., start_new_session=True)`, keep the handle, and set `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `OLLAMA_FLASH_ATTENTION=1` in its environment. Never set these on a server we do not own.
- Wait for readiness with a configurable timeout (default 15 seconds). Handle startup failure with a clear message.
- Handle model-not-found with a clear message that includes the exact `ollama pull MODEL` command. Do not auto-pull outside the benchmark step.
- Stop our process with terminate, wait up to 5 seconds, then kill. Only the handle we created.
- Cleanup runs through `try/finally`, `atexit`, and SIGINT/SIGTERM handlers, so Ctrl-C leaves nothing behind.
- `keep_alive: 0` unloads the model but does not stop the server. Do not assume otherwise.
- Default behaviour: no model resident in memory after the command exits.

---

# 12. Cache (cache.py)

Location: `<root>/.tldrepo/cache.json`.

```json
{
  "version": 2,
  "files": {
    "src/main.py": {
      "hash": "sha256...",
      "model": "qwen2.5-coder:3b",
      "prompt_version": 1,
      "tier": 1,
      "description": "Application entry point and startup orchestration."
    }
  },
  "dirs": {}
}
```

- An entry is valid only if the hash, the model and the `prompt_version` all match. Changing the model or prompt therefore refreshes old descriptions. Tier 0 entries do not depend on the model.
- Unchanged file: reuse. Modified or new file: analyse. Deleted file: remove the stale entry.
- Malformed or unknown-version cache: recover safely (back it up as `cache.json.bak`, start fresh).
- Never cache raw source code.
- Atomic writes: write a temp file in the same directory, then `os.replace`.
- `--refresh` regenerates every eligible description.

---

# 13. Rendering (renderer.py) and CLI (main.py)

## Rendering

- Use Rich, keep it compact.
- Directory-first ordering, correct ASCII connectors, configurable depth, empty directories handled.
- Descriptions align beside names and are **truncated with an ellipsis to the terminal width**.
- While analysing, show a single transient progress line, for example `Analysing 14 files... 6/14`. Print the final tree once.
- Footer: files scanned, files analysed by AI, descriptions from cache, files described deterministically, files pending (if the time budget ran out, with a hint to run `tldrepo` again), and total duration.
- `--timing` additionally prints per-phase times (scan, load, prefill, decode, cleanup, render).

Example:

```text
my-project/
│
├── src/
│   ├── services/               # Core business logic
│   │   ├── pipeline.py         # Runs the job fetch, score and save flow
│   │   └── relevance.py        # Scores job relevance
│   └── main.py                 # Application entry point
│
├── tests/                      # Automated tests
└── pyproject.toml              # Project dependencies
```

## CLI (argparse)

| Command | Behaviour |
| --- | --- |
| `tldrepo` | Analyse uncached or modified files, show the full map |
| `tldrepo --no-ai` | Tree from cache plus deterministic descriptions, never starts Ollama |
| `tldrepo --refresh` | Regenerate all eligible descriptions |
| `tldrepo --depth 3` | Limit depth |
| `tldrepo --stats` | Language and file statistics |
| `tldrepo src/` | Analyse and display one directory |
| `tldrepo src/main.py` | Show one file: description, skeleton summary |
| `tldrepo --model NAME` | Override the model |
| `tldrepo --fast` | Use the fast model |
| `tldrepo --budget N` | Time budget in seconds (default 25) |
| `tldrepo --timing` | Show per-phase timings |

Support sensible combinations. The tool analyses the current working directory, not its install directory.

---

# 14. Zsh Integration (do this last)

The original function was broken: running `tldrepo/main.py` as a script makes relative imports fail. Use module execution instead:

```zsh
tldrepo() {
    uv run --frozen --no-sync --project "$HOME/projects/tldrepo" \
        python -m tldrepo "$@"
}
```

Before finishing, run `uv sync` once in the project. Also measure the alternative of calling the project's `.venv/bin/python -m tldrepo` directly, and use whichever has lower startup time. Confirm the working directory is preserved (it must scan where I am, not the install directory).

Procedure:

1. Inspect the existing `~/.zshrc`. Check whether a `tldrepo` function or alias already exists.
2. Back up to `~/.zshrc.bak.<timestamp>`.
3. Wrap the function in `# >>> tldrepo >>>` and `# <<< tldrepo <<<` markers. Make the edit idempotent (replace the marked block if present, never duplicate).
4. Do not touch unrelated aliases, functions or configuration.
5. Show the diff.
6. Verify: `zsh -i -c 'cd /tmp/<test-repo> && tldrepo --no-ai'`.

Adapt the path if the project is installed somewhere other than `~/projects/tldrepo`.

---

# 15. Testing

Mock Ollama in unit tests. No downloaded model is needed to run the basic suite.

Cover: recursive scanning, directory exclusions, `.gitignore` handling, hidden files, binary and large files, symlinks, ASCII tree generation and width truncation, Python AST extraction, regex skeletons for other languages, tiering (tests, docstrings, duplicate hashes), deterministic descriptions, batching by token budget, `num_ctx` computation, answer parsing, each quality check, Tier 2 escalation and fallback, time-budget cut-off with partial render, cache creation and invalidation (hash, model, prompt version), deleted-file cleanup, malformed cache recovery, atomic writes, Ollama already running (must not be stopped), Ollama started by us (must be stopped), model loading and unloading, `keep_alive 0` on the last request, failure during inference, cleanup after interruption, warm run never contacting Ollama, and CLI argument combinations.

---

# 16. Implementation Order

**Phase A**

1. Inspect environment: macOS version, chip (`sysctl -n machdep.cpu.brand_string`), RAM (`sysctl hw.memsize`), Python, uv, Ollama version, free disk. Log in `DECISIONS.md`.
2. Set up the project (structure, `pyproject.toml`, git).
3. Scanner with `.gitignore` support.
4. Tree builder and renderer skeleton.
5. Metadata and skeleton extraction.
6. Tiering and deterministic descriptions.
7. Cache.
8. CLI wiring for `--no-ai`, `--depth`, `--stats`, paths. **Gate A.**

**Phase B** 9. Ollama manager with full lifecycle and tests. 10. Analyzer: batching, prompt, parsing, quality checks, escalation, time budget. 11. Rich progress and footer, `--timing`. 12. Real end-to-end run against the test repository. 13. Model benchmark, then set the default per section 10. **Gate B.**

**Phase C** 14. Zsh integration. 15. Full benchmark run (below). 16. Final report. **Gate C.**

---

# 17. Measurement Protocol

- Clone a real public Python project with about 20 to 30 relevant source files (after filtering) into `/tmp` as the target. Log which project you chose.
- Run three scenarios, three times each, and report the **median**: cold (no cache), warm (no changes), and after modifying five files.
- Report per-phase times: scan, model load, prefill, decode, cleanup, render.
- After every run, check `ollama ps` (nothing loaded) and `pgrep -fl ollama` (no process we started).
- Quality spot check: print 10 random descriptions beside their skeletons and flag any that look invented.
- Report real numbers only. If a target is missed, say so and describe why.

| Scenario | Target |
| --- | --- |
| Cold, about 25 files | under 20 s (hard ceiling: the time budget) |
| Warm, nothing changed | under 2 s |
| Five modified files | under 12 s |
| Model resident after exit | zero |
| Ollama process left running that we started | none |

Do not trade away description quality just to hit a number. If quality and speed conflict, show me both and let the benchmark decide.

---

# 18. Scope Restrictions

Do not build: multi-agent systems, RAG, embeddings, vector databases, MCP servers, dependency-graph databases, web interfaces, background monitoring services, or persistent AI daemons. This is a local terminal utility.

---

# 19. Definition of Done and Final Report

Done when I can open Ghostty, `cd` into any repository, type `tldrepo`, and see a complete ASCII tree with meaningful one-line descriptions from a local LLM. Unchanged descriptions come from cache, modified files are re-analysed, the model and any Ollama we started are shut down, a second run is near-instant, and nothing depends on an AI coding assistant.

Finish with a report containing:

- Architecture implemented and files created.
- Dependencies installed.
- Benchmark table (time and quality grade per model) and the chosen default, with its size and quantisation (from `ollama show`).
- Zsh integration status and the diff.
- Test results.
- Measured cold, warm and five-file times, with per-phase breakdown.
- Remaining limitations and ideas for later.
