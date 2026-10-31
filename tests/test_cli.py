from __future__ import annotations

import json
from pathlib import Path

import pytest

from tldrepo.main import build_parser, run

PY = '''"""Scores job relevance against a posting."""


def score(text):
    return len(text)
'''


@pytest.fixture
def repo(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "services").mkdir(parents=True)
    (tmp_path / "src" / "services" / "relevance.py").write_text(PY, "utf-8")
    (tmp_path / "src" / "services" / "pipeline.py").write_text(
        '"""Runs the job fetch, score and save flow."""\n\n\ndef run():\n    pass\n', "utf-8"
    )
    (tmp_path / "src" / "main.py").write_text("def main():\n    pass\n", "utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_relevance.py").write_text(
        "def test_a():\n    pass\n", "utf-8"
    )
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", "utf-8")
    (tmp_path / "README.md").write_text("# Demo\n", "utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_no_ai_renders_tree_and_exits_zero(repo, capsys):
    assert run(["--no-ai"]) == 0
    out = capsys.readouterr().out
    assert "src/" in out
    assert "services/" in out
    assert "relevance.py" in out
    assert "pyproject.toml" in out
    assert "scanned" in out


def test_no_ai_never_touches_ollama(repo, monkeypatch, capsys):
    import tldrepo.main as main_module

    def explode(*args, **kwargs):
        raise AssertionError("AI analysis must not run with --no-ai")

    monkeypatch.setattr(main_module, "_analyse", explode)
    assert run(["--no-ai"]) == 0
    capsys.readouterr()


def test_deterministic_and_fallback_descriptions_appear(repo, capsys):
    run(["--no-ai"])
    out = capsys.readouterr().out
    assert "Tests for relevance (1 tests)" in out or "Tests for relevance" in out
    assert "Project dependencies" in out
    assert "Python module: main" in out or "Python module" in out


def test_depth_limits_display(repo, capsys):
    run(["--no-ai", "--depth", "1"])
    out = capsys.readouterr().out
    assert "src/" in out
    assert "relevance.py" not in out


def test_stats_prints_language_table(repo, capsys):
    run(["--no-ai", "--stats"])
    out = capsys.readouterr().out
    assert "Languages" in out
    assert "Python" in out


def test_single_file_mode(repo, capsys):
    result = run(["--no-ai", "src/main.py"])
    out = capsys.readouterr().out
    assert result == 0
    assert "src/main.py" in out
    assert "language" in out
    assert "skeleton" in out


def test_subdirectory_path(repo, capsys):
    assert run(["--no-ai", "src/services"]) == 0
    out = capsys.readouterr().out
    assert "relevance.py" in out
    assert "main.py" not in out.split("services/")[-1].split("\n")[0]


def test_missing_path_returns_usage_error(repo, capsys):
    assert run(["--no-ai", "does/not/exist"]) == 2
    err = capsys.readouterr().err
    assert "no such file or directory" in err


def test_cache_is_written_and_reused(repo, capsys):
    run(["--no-ai"])
    capsys.readouterr()
    cache_path = repo / ".tldrepo" / "cache.json"
    assert cache_path.exists()
    assert (repo / ".tldrepo" / ".gitignore").read_text().strip() == "*"
    payload = json.loads(cache_path.read_text())
    assert payload["version"] == 3
    assert "tests/test_relevance.py" in payload["files"]
    assert "README.md" in payload["files"]

    run(["--no-ai"])
    out = capsys.readouterr().out
    assert "cached" in out


def test_refresh_regenerates(repo, capsys):
    run(["--no-ai"])
    capsys.readouterr()
    before = json.loads((repo / ".tldrepo" / "cache.json").read_text())
    run(["--no-ai", "--refresh"])
    capsys.readouterr()
    after = json.loads((repo / ".tldrepo" / "cache.json").read_text())
    assert after["files"].keys() == before["files"].keys()


def test_budget_zero_disables_ai(repo, monkeypatch, capsys):
    import tldrepo.main as main_module

    monkeypatch.setattr(main_module, "_analyse", lambda ctx: pytest.fail("AI should be skipped"))
    assert run(["--budget", "0"]) == 0
    capsys.readouterr()


def test_working_directory_is_preserved(repo, capsys):
    import os

    before = os.getcwd()
    run(["--no-ai"])
    assert os.getcwd() == before
    capsys.readouterr()


def test_parser_flags():
    parser = build_parser()
    args = parser.parse_args(["--no-ai", "--depth", "2", "--budget", "5", "src"])
    assert args.no_ai and args.depth == 2 and args.budget == 5 and args.path == "src"
    assert parser.parse_args([]).budget == 25.0


def test_dot_directories_are_hidden_unless_all(repo, capsys):
    (repo / ".agents" / "rules").mkdir(parents=True)
    (repo / ".agents" / "rules" / "style.md").write_text("# Style\n", "utf-8")
    run(["--no-ai"])
    out = capsys.readouterr().out
    assert ".agents" not in out
    run(["--no-ai", "--all"])
    out = capsys.readouterr().out
    assert ".agents/" in out
    assert ".git/" not in out


def test_legend_is_opt_in(repo, capsys):
    run(["--no-ai"])
    assert "legend:" not in capsys.readouterr().out
    run(["--no-ai", "--legend"])
    out = capsys.readouterr().out
    assert "legend:" in out
    assert "LLM" in out


def test_new_cli_flags():
    parser = build_parser()
    args = parser.parse_args(["--all", "--no-color", "--legend"])
    assert args.all and args.no_color and args.legend
