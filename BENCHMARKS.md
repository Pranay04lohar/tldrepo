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
| `qwen2.5-coder:1.5b` | 986 MB | 0.81 | 1.48 | 2.03 | 0.04 | **4.94** | 11 | 2 | 1 | 1 | 73% |
| `lfm3:1.7b` | 1.7 GB | 0.81 | 1.57 | 5.90 | 0.02 | 8.17 | 13 | 1 | 0 | 0 | **87%** |
| `qwen3:1.7b` | 1.4 GB | 0.54 | 1.83 | 0.35 | 0.02 | 3.38 | 1 | 0 | 0 | 14 | 7% |
| `qwen2.5-coder:3b` | 1.9 GB | 0.54 | 3.53 | 4.64 | 0.05 | 9.36 | 11 | 4 | 0 | 0 | 73% |

Grading was conservative: a description must be both specific and true to count
as correct. Repeating the module's obvious role ("Configuration management")
without saying anything more is vague. "Flask application entry point" for
`app.py` is wrong (the module defines the `Flask` class; it is not an entry
point). A missing description counts against the score.

`qwen3:1.7b` answered only the first file on all three runs with the example-led
prompt, so it is disqualified on format compliance rather than speed.
`lfm3:1.7b` loaded and answered on Ollama 0.40.13, so no update is required.
One first-pass 3b request returned HTTP 500 while the runner restarted; the
rerun succeeded and the table uses the successful three runs.

**Decision:** `lfm3:1.7b` is the fastest model at or above 80 percent correct,
so it is the default. `qwen2.5-coder:3b` is kept for benchmark comparison only,
and `--fast` uses `qwen2.5-coder:1.5b`.

## Measurement protocol

Target project: `pallets/click` cloned to `/tmp/tldrepo-bench-click`, scan
target `src/click` (17 Python source files after filtering). Default model
`lfm3:1.7b`, prompt version 2, budget 25 s.

| Scenario | Target | Measured (median of 3) | Per-phase (scan / load / prefill / decode / cleanup / render) |
| --- | --- | --- | --- |
| Cold, 17 files | < 20 s | **11.66 s** (12.17, 11.66, 11.01) | 0.00 / 0.72 / 1.99 / 7.07 / 0.01 / 0.00 |
| Warm, nothing changed | < 2 s | **0.12 s** (0.14, 0.12, 0.12) | 0.00 / 0 / 0 / 0 / 0 / 0.00 |
| Five modified files | < 12 s | **3.04 s** (2.95, 3.04, 3.08) | 0.00 / 0.61 / 0.33 / 1.91 / 0.01 / 0.00 |
| Model resident after exit | zero | zero (`ollama ps` empty) | — |
| Ollama process we started left running | none | none from our `Popen` handle | — |

Cold runs vary because lfm3 output length varies (11.0 to 12.2 s), but all stay
under the 20 s target and the 25 s budget. These numbers were re-measured after
directory descriptions, dot-directory filtering, pluralisation and source-based
colour were added. The `src/click` target has no unknown subdirectories, so its
numbers contain no directory LLM call.

### Release re-measurement for 0.1.0 (2026-11-01)

Same hardware, target and protocol as above, re-run after the release work
(rename, output polish, doctor and packaging). Three runs per scenario, median:

| Scenario | Measured | Previous | Per-phase (scan / load / prefill / decode / cleanup / render) |
| --- | --- | --- | --- |
| Cold, 17 files | **10.37 s** | 11.66 s | 0.00 / 0.52 / 1.86 / 6.40 / 0.01 / 0.01 |
| Warm, nothing changed | **0.10 s** | 0.12 s | 0.00 / 0 / 0 / 0 / 0 / 0.00 |
| Five modified files | **2.46 s** | 3.04 s | 0.00 / 0.52 / 0.34 / 1.40 / 0.01 / 0.00 |

All three scenarios improved or stayed effectively flat; none regressed.
`ollama ps` was empty after the runs, and no server started by the tool remained.

### Directory-call cost

Measured separately on the full 157-file click checkout (17 unknown
directories, one request for all of them):

| State | Wall |
| --- | --- |
| Warm, directories cached | 0.17 s |
| Warm files, directory cache cleared | 5.26 s |
| Directory call added | **5.09 s** |

That is above the 2 s note threshold. It is a single request, and it only
happens when directory descriptions are missing; the next run is warm again.
 The warm runs made zero requests
to Ollama; `--timing` shows no load/prefill/decode phases. An earlier 226-file
flask run with 3b took 30.6 s and stopped one file on the 25 s budget, which is
why the target scenario is the 17-file source subtree.

No process from our own `Popen` remains. The machine also has the Ollama
menu-bar app installed; macOS restarted its service after one runner crash
during the benchmark. It is a pre-existing service and was deliberately left
untouched.
