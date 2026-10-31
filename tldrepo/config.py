"""Configuration values. Everything tunable lives here, never hard-coded in modules."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "lfm3:1.7b"
FAST_MODEL = "qwen2.5-coder:1.5b"

PROMPT_VERSION = 2
CACHE_VERSION = 3

OLLAMA_DEFAULT_HOST = "http://127.0.0.1:11434"

IGNORED_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        "out",
        "target",
        ".next",
        ".nuxt",
        ".turbo",
        ".idea",
        ".vscode",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        ".tox",
        ".eggs",
        ".tldrepo",
        "coverage",
        "htmlcov",
        "site-packages",
        "vendor",
        "Pods",
    }
)

EXCLUDED_PATH_CONFIG = ".tldrepo/config.json"


@dataclass
class Config:
    # scanning
    max_depth: int | None = None
    max_file_size: int = 200_000
    ignored_dirs: frozenset[str] = IGNORED_DIRS
    ignored_suffixes: frozenset[str] = frozenset()
    use_docstrings: bool = True
    follow_symlinks: bool = False
    show_all: bool = False

    # description quality
    max_description_words: int = 10
    max_accepted_words: int = 14
    docstring_max_words: int = 12
    directory_max_words: int = 8

    # model and prompts
    model: str = DEFAULT_MODEL
    prompt_version: int = PROMPT_VERSION
    system_prompt: str = ""

    # batching and request limits
    batch_input_tokens: int = 3500
    batch_max_files: int = 20
    skeleton_max_chars: int = 1000
    max_num_ctx: int = 8192
    request_timeout: float = 120.0
    retries: int = 1

    # run behaviour
    budget: float = 25.0
    refresh: bool = False
    no_ai: bool = False
    show_timing: bool = False
    stats: bool = False
    no_color: bool = False
    legend: bool = False

    # ollama lifecycle
    ollama_host: str = ""
    ollama_start_timeout: float = 15.0
    keep_alive: str = "5m"

    # rendering
    depth: int | None = None

    extras: dict = field(default_factory=dict)


def load_project_config(root: Path) -> dict:
    """Optional per-project overrides from ``.tldrepo/config.json``."""
    path = root / EXCLUDED_PATH_CONFIG
    try:
        raw = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return raw


def apply_project_config(cfg: Config, data: dict) -> Config:
    if not data:
        return cfg
    if isinstance(data.get("model"), str) and data["model"].strip():
        cfg.model = data["model"].strip()
    if isinstance(data.get("use_docstrings"), bool):
        cfg.use_docstrings = data["use_docstrings"]
    if isinstance(data.get("max_file_size"), int) and data["max_file_size"] > 0:
        cfg.max_file_size = data["max_file_size"]
    if isinstance(data.get("ignored_dirs"), list):
        cfg.ignored_dirs = cfg.ignored_dirs | frozenset(
            str(item) for item in data["ignored_dirs"]
        )
    if isinstance(data.get("ignored_suffixes"), list):
        cfg.ignored_suffixes = cfg.ignored_suffixes | frozenset(
            str(item) for item in data["ignored_suffixes"]
        )
    if isinstance(data.get("budget"), (int, float)) and data["budget"] > 0:
        cfg.budget = float(data["budget"])
    if isinstance(data.get("batch_input_tokens"), int) and data["batch_input_tokens"] > 0:
        cfg.batch_input_tokens = data["batch_input_tokens"]
    cfg.extras.update({k: v for k, v in data.items() if k not in cfg.extras})
    return cfg


def ollama_host(cfg: Config) -> str:
    import os

    host = cfg.ollama_host or os.environ.get("OLLAMA_HOST") or OLLAMA_DEFAULT_HOST
    host = host.strip().rstrip("/")
    if not host.startswith(("http://", "https://")):
        host = "http://" + host
    return host
