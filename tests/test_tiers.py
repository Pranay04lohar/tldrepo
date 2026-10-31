from __future__ import annotations

from pathlib import Path

from explain.config import Config
from explain.metadata import analyze
from explain.scanner import scan
from explain.tiers import (
    TIER_DETERMINISTIC,
    TIER_LLM,
    assign,
    deterministic_description,
    directory_description,
    is_config_path,
    is_doc_path,
    is_test_path,
    priority_for,
    test_module_name as module_name_for,
    usable_docstring,
)

PY = '"""Loads and stores job postings in the database."""\n\nimport sqlite3\n\n\ndef load():\n    return sqlite3.connect("db.sqlite")\n'


def build(tmp_path: Path, files: dict[str, str]):
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, "utf-8")
    result = scan(tmp_path, cfg=Config(show_all=True))
    metas = {entry.path: analyze(entry, tmp_path) for entry in result.files}
    return result.files, metas


def decisions(tmp_path, files, cfg=None):
    entries, metas = build(tmp_path, files)
    return assign(entries, metas, cfg or Config()), entries, metas


def test_test_files_are_tier_zero_with_count(tmp_path, ):
    files = {
        "src/relevance.py": PY,
        "tests/test_relevance.py": "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n",
        "tests/test_empty.py": "x = 1\n",
    }
    result, entries, metas = decisions(tmp_path, files)
    assert result["tests/test_relevance.py"].tier == TIER_DETERMINISTIC
    assert result["tests/test_relevance.py"].description == "Tests for relevance (2 tests)"
    assert result["tests/test_empty.py"].description == "Tests for empty"


def test_conftest_is_described_as_fixtures(tmp_path):
    result, _, _ = decisions(tmp_path, {"tests/conftest.py": "import pytest\n"})
    assert result["tests/conftest.py"].description == "Shared pytest fixtures and configuration"


def test_docstring_supplies_description(tmp_path):
    result, _, _ = decisions(tmp_path, {"src/relevance.py": PY})
    assert result["src/relevance.py"].tier == TIER_DETERMINISTIC
    assert result["src/relevance.py"].description == "Loads and stores job postings in the database"


def test_long_or_generic_docstrings_are_rejected(tmp_path):
    long_doc = '"""' + " ".join(["word"] * 30) + '"""\n'
    generic = '"""Utilities."""\n'
    result, entries, metas = decisions(
        tmp_path, {"a.py": long_doc + "\n\ndef f():\n    pass\n", "b.py": generic + "\n\ndef g():\n    pass\n"}
    )
    assert result["a.py"].tier == TIER_LLM
    assert result["b.py"].tier == TIER_LLM


def test_config_and_docs_are_tier_zero(tmp_path):
    files = {
        "pyproject.toml": "[project]\nname='x'\n",
        "Dockerfile": "FROM python:3.12\n",
        "README.md": "# Demo\n",
        ".github/workflows/ci.yml": "on: push\n",
        "config/app.yaml": "port: 1\n",
    }
    result, _, _ = decisions(tmp_path, files)
    assert result["pyproject.toml"].description == "Python project metadata and dependencies"
    assert result["Dockerfile"].description == "Container image build definition"
    assert result["README.md"].tier == TIER_DETERMINISTIC
    assert result[".github/workflows/ci.yml"].description == "GitHub Actions CI workflow"
    assert result["config/app.yaml"].description == "Service configuration"


def test_trivial_init_is_a_package_marker(tmp_path):
    result, _, _ = decisions(tmp_path, {"pkg/__init__.py": "from .core import run\n"})
    assert result["pkg/__init__.py"].description == "Package marker for pkg"


def test_duplicate_content_reuses_description(tmp_path):
    text = '"""Scores job relevance."""\n\n\ndef score():\n    return 1\n'
    result, _, _ = decisions(tmp_path, {"a/score.py": text, "b/score.py": text})
    assert result["b/score.py"].description == result["a/score.py"].description
    assert result["b/score.py"].tier == TIER_DETERMINISTIC
    assert result["b/score.py"].duplicate_of == "a/score.py"


def test_priority_prefers_entry_points_and_core(tmp_path):
    files = {
        "main.py": "def main():\n    pass\n",
        "src/services/pipeline.py": "def run():\n    pass\n",
        "src/api/routes.py": "def route():\n    pass\n",
        "src/repositories/users.py": "def get():\n    pass\n",
        "src/util/misc.py": "def helper():\n    pass\n",
    }
    result, entries, metas = decisions(tmp_path, files)
    assert result["main.py"].priority == 0
    assert result["src/services/pipeline.py"].priority == 10
    assert result["src/api/routes.py"].priority == 20
    assert result["src/repositories/users.py"].priority == 30
    assert result["src/util/misc.py"].priority == 60


def test_directory_name_map():
    assert directory_description("tests") == "Automated tests"
    assert directory_description("Utils") == "Shared helper functions"
    assert directory_description("not-a-known-dir") is None


def test_test_path_detection():
    assert is_test_path("tests/test_a.py")
    assert is_test_path("pkg/__tests__/x.js")
    assert is_test_path("widget.test.ts")
    assert is_test_path("FooTest.java")
    assert not is_test_path("contest.py")
    assert not is_test_path("src/testing_utils.py")


def test_test_module_name_forms():
    assert module_name_for("tests/test_relevance.py") == "relevance"
    assert module_name_for("pkg/relevance_test.go") == "relevance"
    assert module_name_for("ui/button.spec.ts") == "button"
    assert module_name_for("FooTest.java") == "Foo"


def test_doc_and_config_detection():
    assert is_doc_path("README.md")
    assert is_doc_path("docs/architecture.md")
    assert is_doc_path("CONTRIBUTING.rst")
    assert is_doc_path("PROGRESS.md")
    assert not is_doc_path("src/main.py")
    assert is_config_path("pyproject.toml")
    assert not is_config_path("src/config.py")


def test_usable_docstring_respects_config_flag(tmp_path):
    entries, metas = build(tmp_path, {"a.py": PY})
    meta = metas["a.py"]
    assert usable_docstring(meta, Config()) is not None
    assert usable_docstring(meta, Config(use_docstrings=False)) is None


def test_deterministic_description_returns_needs_ai_for_plain_module(tmp_path):
    entries, metas = build(tmp_path, {"lib/thing.py": "def run():\n    pass\n"})
    entry = next(e for e in entries if e.path == "lib/thing.py")
    description, reason = deterministic_description(entry, metas["lib/thing.py"], Config())
    assert description is None
    assert reason == "needs-ai"
