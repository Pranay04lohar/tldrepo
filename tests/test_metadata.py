from __future__ import annotations

from pathlib import Path

from tldrepo.config import Config
from tldrepo.metadata import (
    analyze,
    build_skeleton,
    estimate_tokens,
    neighbours_for,
    skeleton_summary,
)
from tldrepo.scanner import ScannedFile, scan

PY_SOURCE = '''"""Utilities for scoring job relevance."""

import json
from dataclasses import dataclass


@dataclass
class Scored:
    score: float


def score(text: str, weights: dict) -> float:
    """Score one posting."""
    return len(text) * weights.get("len", 1.0)


class Ranker:
    """Ranks postings."""

    def rank(self, items):
        return sorted(items, key=score)

    async def refresh(self):
        return None


def test_score():
    assert score("a", {"len": 1}) == 1
'''


def entry_for(tmp_path: Path, name: str, text: str) -> ScannedFile:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    result = scan(tmp_path, cfg=Config())
    return next(f for f in result.files if f.path == name)


def test_python_ast_extracts_structure(tmp_path):
    entry = entry_for(tmp_path, "relevance.py", PY_SOURCE)
    meta = analyze(entry, tmp_path)
    assert meta.docstring.startswith("Utilities for scoring")
    assert meta.classes == ["Scored", "Ranker"]
    assert "score" in meta.functions
    assert "Ranker.rank" in meta.functions
    assert "Ranker.refresh" in meta.functions
    assert "json" in meta.imports
    assert "dataclasses" in meta.imports
    assert meta.lines == len(PY_SOURCE.splitlines())
    assert meta.parse_error is None


def test_python_ast_counts_tests(tmp_path):
    entry = entry_for(tmp_path, "test_relevance.py", PY_SOURCE)
    meta = analyze(entry, tmp_path)
    assert meta.test_count == 1


def test_syntax_error_falls_back_without_crashing(tmp_path):
    entry = entry_for(tmp_path, "broken.py", "def oops(:\n    pass\n")
    meta = analyze(entry, tmp_path)
    assert meta.parse_error is not None
    assert "oops" in " ".join(meta.declarations)


def test_regex_skeleton_for_typescript(tmp_path):
    source = """import { db } from "./db";

export interface Job {
  id: string;
}

export class JobService {
  async run(id: string) {
    return db.get(id);
  }
}

export function createService(): JobService {
  return new JobService();
}
"""
    entry = entry_for(tmp_path, "job.ts", source)
    meta = analyze(entry, tmp_path)
    joined = "\n".join(meta.declarations)
    assert "export interface Job" in joined
    assert "export class JobService" in joined
    assert "export function createService" in joined
    assert meta.first_lines


def test_regex_skeleton_for_go_and_rust(tmp_path):
    go = "package main\n\nfunc main() {\n}\n\ntype Server struct {\n}\n"
    rust = "pub fn run(x: i32) -> i32 {\n    x\n}\n\npub struct Config {\n}\n"
    go_meta = analyze(entry_for(tmp_path, "main.go", go), tmp_path)
    rust_meta = analyze(entry_for(tmp_path, "lib.rs", rust), tmp_path)
    assert any("func main" in line for line in go_meta.declarations)
    assert any("type Server" in line for line in go_meta.declarations)
    assert any("pub fn run" in line for line in rust_meta.declarations)
    assert any("pub struct Config" in line for line in rust_meta.declarations)


def test_skeleton_format_and_budget(tmp_path):
    entry = entry_for(tmp_path, "relevance.py", PY_SOURCE)
    meta = analyze(entry, tmp_path)
    skeleton = build_skeleton(3, meta, ["a.py", "b.py"], max_chars=1000)
    assert skeleton.startswith("FILE 3: relevance.py")
    assert "Doc: Utilities for scoring job relevance." in skeleton
    assert "Classes: Scored, Ranker" in skeleton
    assert "Neighbours: a.py, b.py" in skeleton
    assert len(skeleton) <= 1000
    assert estimate_tokens(skeleton) <= 250


def test_skeleton_uses_source_for_tiny_files(tmp_path):
    entry = entry_for(tmp_path, "tiny.py", "def add(a, b):\n    return a + b\n")
    meta = analyze(entry, tmp_path)
    skeleton = build_skeleton(1, meta, [], max_chars=400)
    assert "Source:" in skeleton
    assert "def add(a, b):" in skeleton


def test_skeleton_falls_back_to_source_when_no_structure(tmp_path):
    text = "\n".join(f"print({i})" for i in range(60))
    entry = entry_for(tmp_path, "script.py", text)
    meta = analyze(entry, tmp_path)
    assert not meta.has_structure
    skeleton = build_skeleton(1, meta, [])
    assert "Source:" in skeleton
    assert "print(0)" in skeleton
    assert "print(59)" not in skeleton


def test_skeleton_is_trimmed_to_max_chars(tmp_path):
    imports = "import " + ", ".join(f"pkg{i}" for i in range(200))
    body = "\n".join(f"def f{i}():\n    pass" for i in range(40))
    entry = entry_for(tmp_path, "wide.py", imports + "\n\n" + body + "\n")
    meta = analyze(entry, tmp_path)
    skeleton = build_skeleton(2, meta, [], max_chars=300)
    assert len(skeleton) <= 300


def test_neighbours_are_same_directory_only(tmp_path):
    (tmp_path / "pkg").mkdir()
    for name in ("a.py", "b.py", "c.py"):
        (tmp_path / "pkg" / name).write_text("x = 1\n")
    (tmp_path / "other.py").write_text("x = 1\n")
    result = scan(tmp_path, cfg=Config())
    neighbours = neighbours_for("pkg/a.py", result.files, limit=2)
    assert neighbours == ["b.py", "c.py"]


def test_skeleton_summary_rows(tmp_path):
    meta = analyze(entry_for(tmp_path, "relevance.py", PY_SOURCE), tmp_path)
    keys = [key for key, _ in skeleton_summary(meta)]
    assert keys[:2] == ["language", "size"]
    assert "classes" in keys and "functions" in keys and "imports" in keys
