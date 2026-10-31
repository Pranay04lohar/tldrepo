# Contributing

Thanks for helping improve `tldrepo`.

## Setup

```bash
git clone https://github.com/your-username/tldrepo.git
cd tldrepo
uv sync
```

The project is pinned to Python 3.12 through `.python-version`, and supports
Python 3.11 and newer.

## Run the tests

```bash
uv run pytest
```

Tests mock Ollama, so they do not need a server, a downloaded model or a GPU.

To try the command from the checkout:

```bash
uv run tldrepo --no-ai
uv run tldrepo --doctor
```

## Propose a change

1. Open an issue describing the problem or idea when the change is not tiny.
2. Create a branch, keep the change focused, and add or update tests.
3. Run `uv run pytest` and make sure it passes.
4. Open a pull request with a short description of the change and the commands
   or tests you ran.

Please keep descriptions truthful and deterministic where Python can answer,
and avoid adding dependencies that are not needed at runtime.
