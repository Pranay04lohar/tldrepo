"""File metadata and the compact skeleton the model sees.

Python files are parsed with ``ast``. Every other language gets a cheap regex
skeleton of declaration lines. No source is ever stored in the cache.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .scanner import ScannedFile

MAX_LIST_ITEMS = 40


@dataclass
class FileMetadata:
    path: str
    language: str
    lines: int
    size: int
    docstring: str | None = None
    classes: list[str] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    declarations: list[str] = field(default_factory=list)
    test_count: int = 0
    parse_error: str | None = None
    first_lines: str = ""

    @property
    def has_structure(self) -> bool:
        return bool(
            self.docstring or self.classes or self.functions or self.imports or self.declarations
        )


# ---------------------------------------------------------------------------
# Python AST
# ---------------------------------------------------------------------------


def _first_doc_line(doc: str | None) -> str | None:
    if not doc:
        return None
    for line in doc.strip().splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _import_name(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom):
        module = "." * node.level + (node.module or "")
        if module:
            return [module]
    return []


def _python_metadata(text: str, meta: FileMetadata) -> None:
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        meta.parse_error = f"{exc.msg} (line {exc.lineno})"
        return

    meta.docstring = ast.get_docstring(tree)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            meta.functions.append(node.name)
        elif isinstance(node, ast.ClassDef):
            meta.classes.append(node.name)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    meta.functions.append(f"{node.name}.{child.name}")
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            meta.imports.extend(_import_name(node))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            meta.test_count += 1
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            meta.test_count += sum(
                1
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith("test")
            )

    meta.classes = _dedupe(meta.classes)
    meta.functions = _dedupe(meta.functions)
    meta.imports = _dedupe(meta.imports)


# ---------------------------------------------------------------------------
# Regex skeletons for other languages
# ---------------------------------------------------------------------------

DECLARATION_PATTERNS = [
    re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+|final\s+|sealed\s+|public\s+|private\s+|"
        r"protected\s+|internal\s+|static\s+|async\s+|readonly\s+|partial\s+|data\s+|"
        r"pub(?:\([^)]*\))?\s+)*"
        r"(?:class|interface|enum|struct|trait|impl|record|object|typedef)\b[^;{=]*"
    ),
    re.compile(
        r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*[A-Za-z_$][\w$]*"
    ),
    re.compile(r"^\s*(?:export\s+)?(?:const|let|var)\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?\("),
    re.compile(r"^\s*(?:async\s+)?def\s+[A-Za-z_]\w*"),
    re.compile(r"^\s*class\s+[A-Za-z_]\w*"),
    re.compile(r"^\s*type\s+[A-Za-z_]\w*\b"),
    re.compile(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?fn\s+[A-Za-z_]\w*"),
    re.compile(r"^\s*func\s+(?:\([^)]*\)\s*)?[A-Za-z_]\w*"),
    re.compile(r"^\s*(?:public|private|protected|internal)\s+[\w<>\[\],\s]+\s+[A-Za-z_]\w*\s*\("),
    re.compile(r"^\s*(?:export\s+)?(?:const|let)\s+[A-Za-z_$][\w$]*\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"),
]

ROUTE_PATTERN = re.compile(
    r"^\s*(?:app|router|server|api)\.(?:get|post|put|patch|delete|use|route)\s*\("
)


def _regex_metadata(text: str, meta: FileMetadata) -> None:
    declarations: list[str] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if len(line) > 160:
            line = line[:159] + "\u2026"
        if any(p.search(line) for p in DECLARATION_PATTERNS) or ROUTE_PATTERN.match(raw):
            cleaned = line.rstrip("{").rstrip(":").strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                declarations.append(cleaned)
        if len(declarations) >= 25:
            break
    meta.declarations = declarations


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def analyze(entry: ScannedFile, root: Path, cfg: Config | None = None) -> FileMetadata:
    cfg = cfg or Config()
    meta = FileMetadata(
        path=entry.path,
        language=entry.language,
        lines=0,
        size=entry.size,
    )
    try:
        text = entry.abspath.read_text("utf-8", errors="replace")
    except OSError as exc:
        meta.parse_error = str(exc)
        return meta
    meta.lines = len(text.splitlines())
    if entry.language == "Python":
        _python_metadata(text, meta)
    if entry.language != "Python" or meta.parse_error is not None:
        _regex_metadata(text, meta)
    if meta.lines <= 40:
        meta.first_lines = text
    elif not meta.has_structure:
        meta.first_lines = "\n".join(text.splitlines()[:40])
    return meta


# ---------------------------------------------------------------------------
# Skeleton for the model
# ---------------------------------------------------------------------------


def _clip(items: list[str], limit: int = MAX_LIST_ITEMS) -> str:
    shown = items[:limit]
    suffix = f", ... (+{len(items) - limit})" if len(items) > limit else ""
    return ", ".join(shown) + suffix


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def neighbours_for(path: str, files: list[ScannedFile], limit: int = 4) -> list[str]:
    parent = path.rpartition("/")[0]
    siblings = [
        entry.path.rpartition("/")[2]
        for entry in files
        if entry.path != path and entry.path.rpartition("/")[0] == parent
    ]
    return siblings[:limit]


def build_skeleton(
    index: int,
    meta: FileMetadata,
    neighbours: list[str],
    max_chars: int = 1000,
) -> str:
    lines = [f"FILE {index}: {meta.path}"]
    if meta.docstring:
        lines.append(f"Doc: {_first_doc_line(meta.docstring)}")
    else:
        lines.append("Doc: (none)")
    if meta.imports:
        lines.append(f"Imports: {_clip(meta.imports)}")
    if meta.classes:
        lines.append(f"Classes: {_clip(meta.classes)}")
    if meta.functions:
        lines.append(f"Functions: {_clip(meta.functions)}")
    if meta.declarations:
        lines.append("Declarations:")
        lines.extend("  " + item for item in meta.declarations[:15])
    if neighbours:
        lines.append(f"Neighbours: {', '.join(neighbours)}   (same directory)")

    if meta.first_lines:
        prefix = "\n".join(lines) + "\nSource:\n"
        budget = max_chars - len(prefix)
        if budget > 60:
            return prefix + meta.first_lines[:budget]
        return "\n".join(lines)

    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text

    while len(text) > max_chars:
        trimmed = False
        for prefix in ("Functions: ", "Classes: ", "Imports: "):
            marker = "\n" + prefix
            if marker in text:
                start = text.index(marker)
                end = text.find("\n", start + 1)
                if end == -1:
                    end = len(text)
                segment = text[start:end]
                if len(segment) > 40:
                    text = text[:start] + segment[: max(30, len(segment) - 40)] + "\u2026" + text[end:]
                    trimmed = True
                    break
        if not trimmed:
            text = text[: max_chars - 1] + "\u2026"
            break
    return text


def skeleton_summary(meta: FileMetadata) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = [
        ("language", meta.language),
        ("size", f"{meta.lines} lines, {meta.size:,} bytes"),
    ]
    if meta.docstring:
        rows.append(("docstring", _first_doc_line(meta.docstring) or ""))
    if meta.classes:
        rows.append(("classes", _clip(meta.classes, 8)))
    if meta.functions:
        rows.append(("functions", _clip(meta.functions, 12)))
    if meta.imports:
        rows.append(("imports", _clip(meta.imports, 10)))
    if meta.declarations:
        rows.append(("declarations", _clip(meta.declarations, 6)))
    if meta.test_count:
        rows.append(("tests", str(meta.test_count)))
    if meta.parse_error:
        rows.append(("parse error", meta.parse_error))
    return rows
