# explain

A fast, local-AI codebase map for the terminal.

```bash
cd ~/my-project
explain
```

`explain` scans the current repository, shows a compact ASCII tree, and puts one
short description beside each file and directory. Descriptions come from a small
local model (via Ollama) when they are worth generating, and from deterministic
rules when Python can answer better.

## Install

```bash
cd ~/projects/explain-cli
uv sync
uv run python -m explain --help
```

## Usage

| Command | Behaviour |
| --- | --- |
| `explain` | Analyse uncached or modified files, show the full map |
| `explain --no-ai` | Tree from cache plus deterministic descriptions, never starts Ollama |
| `explain --refresh` | Regenerate all eligible descriptions |
| `explain --depth 3` | Limit depth |
| `explain --stats` | Language and file statistics |
| `explain src/` | Analyse and display one directory |
| `explain src/main.py` | Show one file: description and skeleton summary |
| `explain --model NAME` | Override the model |
| `explain --fast` | Use the fast model |
| `explain --budget N` | Time budget in seconds (default 25) |
| `explain --timing` | Show per-phase timings |

## Design

- Deterministic Python does traversal, hierarchy, language detection, hashing,
  AST and regex skeletons, tiering, caching, rendering and answer validation.
- The model only turns a ~200-token skeleton into one short description.
- Input to the model is skeleton, never full source (unless the file is tiny).
- Cache lives in `<repo>/.explain/cache.json` and never contains source code.
- The tool starts an Ollama server only if none is running, and stops only the
  process it started. No model stays resident after exit.

## Tests

```bash
uv run pytest
```
