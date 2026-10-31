"""Filesystem traversal with built-in .gitignore matching.

Nothing here calls out to git, and nothing writes to the scanned repository.
"""

from __future__ import annotations

import configparser
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .config import Config

GITIGNORE = ".gitignore"


# ---------------------------------------------------------------------------
# Ignore matching
# ---------------------------------------------------------------------------


def _glob_to_regex(pattern: str) -> str:
    """Translate one gitignore glob into a regex fragment (no anchors)."""
    i = 0
    out: list[str] = []
    while i < len(pattern):
        ch = pattern[i]
        if ch == "*":
            if pattern[i : i + 2] == "**":
                if pattern[i : i + 3] == "**/":
                    out.append("(?:.*/)?")
                    i += 3
                    continue
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[":
            end = pattern.find("]", i + 1)
            if end == -1:
                out.append(re.escape(ch))
                i += 1
                continue
            body = pattern[i + 1 : end]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = end + 1
        elif ch == "\\" and i + 1 < len(pattern):
            out.append(re.escape(pattern[i + 1]))
            i += 2
        else:
            out.append(re.escape(ch))
            i += 1
    return "".join(out)


@dataclass(frozen=True)
class IgnoreRule:
    regex: re.Pattern[str]
    negate: bool
    dir_only: bool
    base: str  # posix directory relative to the scan root, "" for the root

    def matches(self, rel_path: str, is_dir: bool) -> bool:
        if self.dir_only and not is_dir:
            return False
        if self.base:
            if rel_path == self.base:
                sub = ""
            elif rel_path.startswith(self.base + "/"):
                sub = rel_path[len(self.base) + 1 :]
            else:
                return False
        else:
            sub = rel_path
        return bool(self.regex.match(sub))


def parse_gitignore(text: str, base: str = "") -> list[IgnoreRule]:
    rules: list[IgnoreRule] = []
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        line = line.strip()
        if line.startswith("!"):
            negate = True
            line = line[1:]
        else:
            negate = False
        if not line:
            continue
        dir_only = line.endswith("/")
        if dir_only:
            line = line[:-1]
        anchored = line.startswith("/") or "/" in line.rstrip("/")
        line = line.lstrip("/")
        if not line:
            continue
        frag = _glob_to_regex(line)
        if anchored:
            regex = re.compile(frag + r"\Z")
        else:
            regex = re.compile(r"(?:.*/)?" + frag + r"\Z")
        rules.append(IgnoreRule(regex=regex, negate=negate, dir_only=dir_only, base=base))
    return rules


def apply_rules(rules: list[IgnoreRule], rel_path: str, is_dir: bool) -> bool:
    ignored = False
    for rule in rules:
        if rule.matches(rel_path, is_dir):
            ignored = not rule.negate
    return ignored


# ---------------------------------------------------------------------------
# File classification
# ---------------------------------------------------------------------------

LANGUAGE_BY_SUFFIX = {
    ".py": "Python",
    ".pyi": "Python",
    ".js": "JavaScript",
    ".jsx": "JavaScript",
    ".mjs": "JavaScript",
    ".cjs": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".kts": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".c": "C",
    ".h": "C",
    ".cc": "C++",
    ".cpp": "C++",
    ".hpp": "C++",
    ".swift": "Swift",
    ".m": "Objective-C",
    ".mm": "Objective-C++",
    ".scala": "Scala",
    ".sh": "Shell",
    ".bash": "Shell",
    ".zsh": "Shell",
    ".fish": "Shell",
    ".sql": "SQL",
    ".lua": "Lua",
    ".ex": "Elixir",
    ".exs": "Elixir",
    ".erl": "Erlang",
    ".hs": "Haskell",
    ".ml": "OCaml",
    ".clj": "Clojure",
    ".dart": "Dart",
    ".vue": "Vue",
    ".svelte": "Svelte",
    ".html": "HTML",
    ".css": "CSS",
    ".scss": "CSS",
    ".md": "Markdown",
    ".rst": "reStructuredText",
    ".txt": "Text",
    ".toml": "TOML",
    ".yaml": "YAML",
    ".yml": "YAML",
    ".json": "JSON",
    ".ini": "INI",
    ".cfg": "INI",
    ".xml": "XML",
}

LOCKFILES = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "npm-shrinkwrap.json",
    "poetry.lock",
    "Pipfile.lock",
    "uv.lock",
    "Cargo.lock",
    "Gemfile.lock",
    "composer.lock",
    "go.sum",
    "mix.lock",
    "packages.lock.json",
}

BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tif", ".tiff",
    ".pdf", ".zip", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar", ".tar",
    ".jar", ".war", ".ear", ".whl", ".pyc", ".pyo", ".so", ".dylib", ".dll",
    ".exe", ".bin", ".o", ".a", ".class", ".wasm", ".pkl", ".pickle", ".npy",
    ".npz", ".pt", ".pth", ".onnx", ".safetensors", ".mp3", ".mp4", ".mov",
    ".avi", ".wav", ".flac", ".ttf", ".otf", ".woff", ".woff2", ".DS_Store",
    ".sqlite", ".db", ".mdb", ".parquet", ".arrow", ".h5", ".hdf5",
}

DATA_SUFFIXES = {".csv", ".tsv", ".jsonl", ".ndjson"}

GENERATED_SUFFIXES = {".min.js", ".min.css", ".map", ".lock"}
GENERATED_NAMES = {"coverage.xml", "codecov.yml"}


def language_for(path: Path) -> str:
    lower = path.name.lower()
    if lower in {"dockerfile", "containerfile"}:
        return "Dockerfile"
    if lower in {"makefile", "gnumakefile"}:
        return "Makefile"
    for suffix, language in LANGUAGE_BY_SUFFIX.items():
        if lower.endswith(suffix):
            return language
    return "Other"


@dataclass
class ScannedFile:
    path: str  # posix path relative to the scan root
    abspath: Path
    size: int
    language: str
    digest: str
    is_empty: bool = False


@dataclass
class ScanResult:
    root: Path
    target: Path
    files: list[ScannedFile] = field(default_factory=list)
    dirs: list[str] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    limits_hit: list[str] = field(default_factory=list)

    def skipped_total(self) -> int:
        return sum(self.skipped.values())


# ---------------------------------------------------------------------------
# Root detection and scanning
# ---------------------------------------------------------------------------


def _scan_single(root: Path, target: Path, cfg: Config, result: ScanResult) -> None:
    try:
        rel_path = target.relative_to(root).as_posix()
    except ValueError:
        rel_path = target.name
    try:
        size = target.stat().st_size
    except OSError:
        result.skipped["unreadable"] = 1
        return
    suffix = target.suffix.lower()
    reason = _skip_reason(target.name, suffix, size, cfg)
    if reason:
        result.skipped[reason] = 1
        return
    try:
        with open(target, "rb") as handle:
            head = handle.read(8192)
            if _is_binary(head):
                result.skipped["binary"] = 1
                return
            digest = hashlib.sha256()
            digest.update(head)
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    except OSError:
        result.skipped["unreadable"] = 1
        return
    result.files.append(
        ScannedFile(
            path=rel_path,
            abspath=target,
            size=size,
            language=language_for(target),
            digest=digest.hexdigest(),
            is_empty=size == 0,
        )
    )


def find_root(start: Path) -> Path:
    current = start.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
    return current


def _is_binary(head: bytes) -> bool:
    return b"\x00" in head


def _skip_reason(name: str, suffix: str, size: int, cfg: Config) -> str | None:
    lower = name.lower()
    if lower in LOCKFILES or lower in GENERATED_NAMES:
        return "lockfile"
    if suffix in GENERATED_SUFFIXES:
        return "generated"
    if suffix in BINARY_SUFFIXES:
        return "binary"
    if suffix in DATA_SUFFIXES:
        return "data"
    if size == 0:
        return "empty"
    if size > cfg.max_file_size:
        return "large"
    return None


def scan(root: Path, target: Path | None = None, cfg: Config | None = None) -> ScanResult:
    """Walk ``target`` (default ``root``) and return the files worth describing."""
    root = root.resolve()
    target = (target or root).resolve()
    cfg = cfg or Config()
    try:
        target_rel = target.relative_to(root).as_posix()
    except ValueError:
        target_rel = "."
    if target_rel == ".":
        target_rel = ""

    result = ScanResult(root=root, target=target)
    if target.is_file():
        _scan_single(root, target, cfg, result)
        result.files.sort(key=lambda f: f.path.lower())
        return result
    rules: list[IgnoreRule] = []
    root_gitignore = root / GITIGNORE
    if root_gitignore.is_file():
        try:
            rules.extend(parse_gitignore(root_gitignore.read_text("utf-8", "replace")))
        except OSError:
            pass

    def bump(reason: str) -> None:
        result.skipped[reason] = result.skipped.get(reason, 0) + 1

    def walk(directory: Path, rel_dir: str) -> None:
        if cfg.max_depth is not None:
            depth = 0 if not rel_dir else rel_dir.count("/") + 1
            if depth > cfg.max_depth:
                result.limits_hit.append(rel_dir)
                return
        try:
            entries = sorted(os.scandir(directory), key=lambda e: e.name.lower())
        except OSError:
            bump("unreadable")
            return

        local_rules = rules
        local_gitignore = directory / GITIGNORE
        if local_gitignore.is_file() and directory != root:
            try:
                local_rules = rules + parse_gitignore(
                    local_gitignore.read_text("utf-8", "replace"), base=rel_dir
                )
            except OSError:
                local_rules = rules

        for entry in entries:
            rel_path = f"{rel_dir}/{entry.name}" if rel_dir else entry.name
            try:
                is_dir = entry.is_dir(follow_symlinks=False)
                is_link = entry.is_symlink()
            except OSError:
                bump("unreadable")
                continue
            if is_link:
                bump("symlink")
                continue
            if is_dir:
                if entry.name in cfg.ignored_dirs:
                    bump("ignored-dir")
                    continue
                if entry.name.startswith(".") and not cfg.show_all:
                    bump("hidden-dir")
                    continue
                if apply_rules(local_rules, rel_path, True):
                    bump("gitignored")
                    continue
                result.dirs.append(rel_path)
                walk(Path(entry.path), rel_path)
                continue

            if apply_rules(local_rules, rel_path, False):
                bump("gitignored")
                continue
            path = Path(entry.path)
            try:
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                bump("unreadable")
                continue
            suffix = path.suffix.lower()
            if path.name.lower().endswith(".min.js") or path.name.lower().endswith(".min.css"):
                suffix = ".min.js"
            reason = _skip_reason(entry.name, suffix, size, cfg)
            if reason:
                bump(reason)
                continue
            try:
                with open(path, "rb") as handle:
                    head = handle.read(8192)
                    if _is_binary(head):
                        bump("binary")
                        continue
                    digest = hashlib.sha256()
                    digest.update(head)
                    for chunk in iter(lambda: handle.read(65536), b""):
                        digest.update(chunk)
            except OSError:
                bump("unreadable")
                continue
            result.files.append(
                ScannedFile(
                    path=rel_path,
                    abspath=path,
                    size=size,
                    language=language_for(path),
                    digest=digest.hexdigest(),
                    is_empty=size == 0,
                )
            )

    start = target if target.is_dir() else target.parent
    walk(start, target_rel)
    result.dirs.sort()
    result.files.sort(key=lambda f: f.path.lower())
    return result
