# BENCHMARKS

Filled in from Phase B (model comparison) and Phase C (measurement protocol).

## Model comparison

| Model | Size / quant | Load (s) | Prefill (s) | Decode (s) | Cleanup (s) | Median wall (s) | Correct | Vague | Wrong | Score |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| pending | | | | | | | | | | |

## Measurement protocol

| Scenario | Target | Measured (median of 3) |
| --- | --- | --- |
| Cold, ~25 files | < 20 s | pending |
| Warm, no changes | < 2 s | pending |
| Five modified files | < 12 s | pending |
| Model resident after exit | zero | pending |
| Ollama process we started left running | none | pending |
