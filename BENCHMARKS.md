# BENCHMARKS

Measured on the build machine: Apple M5, 16 GiB RAM, macOS 27.0.1, Ollama
0.40.13, one request at a time (`OLLAMA_NUM_PARALLEL=1`).

## Model comparison

Corpus: the same 15 files from `pallets/flask` (`src/flask/` core modules),
one batch per run, model unloaded between runs, 3 runs each. Times are medians
in seconds; prefill and decode come from Ollama's `prompt_eval_duration` and
`eval_duration`. The per-file skeletons and descriptions used for grading are
in `.bench/bench-grades.md` (untracked working evidence).

| Model | Size | Load | Prefill | Decode | Cleanup | Median wall | Correct | Vague | Wrong | Missing | Score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen2.5-coder:1.5b` | 986 MB | 0.53 | 1.20 | 1.36 | 0.01 | **3.65** | 11 | 2 | 1 | 1 | 73% |
| `lfm3:1.7b` | 1.7 GB | 0.61 | 1.11 | 5.22 | 0.01 | 7.30 | 9 | 3 | 2 | 1 | 60% |
| `qwen3:1.7b` | 1.4 GB | 0.80 | 1.46 | 2.20 | 0.03 | 5.29 | 5 | 9 | 1 | 0 | 33% |
| `qwen2.5-coder:3b` | 1.9 GB | 0.54 | 3.29 | 3.75 | 0.03 | 8.12 | 11 | 4 | 0 | 0 | 73% |

Grading was conservative: a description must be both specific and true to count
as correct. Repeating the module's obvious role ("Configuration management")
without saying anything more is vague. "Flask application entry point" for
`app.py` is wrong (the module defines the `Flask` class; it is not an entry
point), and "Database access layer for user records" for `app.py` is invented.

`lfm3:1.7b` loaded and answered on Ollama 0.40.13, so no update is required.
One first-pass 3b request returned HTTP 500 while the runner restarted; the
rerun (all three runs) succeeded and is the data above.

**Decision:** no model reached 80 percent correct, so section 10's fallback
applies: default `qwen2.5-coder:3b`. `--fast` uses `qwen2.5-coder:1.5b`.

## Measurement protocol

| Scenario | Target | Measured (median of 3) |
| --- | --- | --- |
| Cold, ~25 files | < 20 s | pending Phase C |
| Warm, no changes | < 2 s | 0.16 s (`--no-ai`, 226-file flask checkout) |
| Five modified files | < 12 s | pending Phase C |
| Model resident after exit | zero | zero (`ollama ps` empty after a real 3b run) |
| Ollama process we started left running | none | none (owned-server test suite covers stop) |
