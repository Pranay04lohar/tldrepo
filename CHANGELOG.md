# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-11-01

### Added

- First public release of `tldrepo`.
- Deterministic scanner, tree builder, metadata extraction and cache, with an
  optional local model (Ollama) for short file and directory descriptions.
- Cache in `.tldrepo/cache.json`, with atomic writes and a `.gitignore` guard.
- Source-aware colouring, progress line, footer counters, `--timing`,
  `--stats`, `--legend`, `--doctor` and `--no-ai`.
- Privacy guard: the tool only contacts `OLLAMA_HOST` (default
  `127.0.0.1:11434`).
- Tests, CI for Python 3.11 to 3.13, and packaging with hatchling.
