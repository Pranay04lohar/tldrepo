from __future__ import annotations

import time
from pathlib import Path

import pytest
from rich.console import Console

from explain import analyzer
from explain.cache import Cache
from explain.config import Config
from explain.main import RunContext, _resolve_known, run
from explain.metadata import analyze
from explain.renderer import RunStats, themed_console
from explain.scanner import scan
from explain.tiers import assign, directory_key
from explain.tree_builder import build_tree

from fake_ollama import FakeOllama


def make_repo(root: Path) -> None:
    for name in ("alpha", "beta"):
        (root / name).mkdir()
        (root / name / "one.py").write_text("def run(value):\n    return value\n")
    (root / "gamma" / "nested").mkdir(parents=True)


def make_ctx(root: Path) -> RunContext:
    cfg = Config(budget=30.0)
    result = scan(root, root, cfg)
    metas = {entry.path: analyze(entry, root, cfg) for entry in result.files}
    decisions = assign(result.files, metas, cfg)
    cache = Cache(root).load()
    ctx = RunContext(
        cfg=cfg,
        root=root,
        target=root,
        console=themed_console(),
        cache=cache,
        result=result,
        tree=build_tree(result),
        metas=metas,
        decisions=decisions,
        stats=RunStats(),
        started=time.perf_counter(),
    )
    _resolve_known(ctx)
    return ctx


@pytest.fixture
def fake(monkeypatch):
    server = FakeOllama().start()
    monkeypatch.setenv("OLLAMA_HOST", server.host)
    yield server
    from explain.ollama_manager import cleanup_registered

    cleanup_registered()
    server.stop()


def dir_requests(fake):
    return [
        request
        for request in fake.requests
        if request["path"] == "/api/chat"
        and "DIR 1:" in request["payload"]["messages"][-1]["content"]
    ]


def test_all_unknown_directories_use_one_request(fake, tmp_path):
    make_repo(tmp_path)
    ctx = make_ctx(tmp_path)
    summary = analyzer.analyse(ctx)
    requests = dir_requests(fake)
    assert len(requests) == 1
    prompt = requests[0]["payload"]["messages"][-1]["content"]
    assert "DIR 1:" in prompt and "DIR 2:" in prompt
    assert "alpha" in prompt and "beta" in prompt
    assert "Fake description" in prompt
    assert ctx.descriptions["alpha"] == "Fake directory purpose"
    assert ctx.description_sources["alpha"] == "llm"
    assert summary.requests >= 2
    ctx.cache.save()
    payload = __import__("json").loads((tmp_path / ".explain" / "cache.json").read_text())
    assert payload["dirs"]
    assert {entry["source"] for entry in payload["dirs"].values()} == {"llm"}
    assert {entry["model"] for entry in payload["dirs"].values()} == {ctx.cfg.model}


def test_directory_cache_makes_the_next_run_silent(fake, tmp_path):
    make_repo(tmp_path)
    ctx = make_ctx(tmp_path)
    analyzer.analyse(ctx)
    ctx.cache.save()
    before = len(fake.requests)

    ctx2 = make_ctx(tmp_path)
    summary = analyzer.analyse(ctx2)
    assert summary.requests == 0
    assert ctx2.descriptions["alpha"] == "Fake directory purpose"
    assert ctx2.description_sources["alpha"] == "llm"
    assert len(fake.requests) == before


def test_directory_cache_is_model_and_prompt_version_specific(tmp_path):
    cache = Cache(tmp_path).load()
    key = directory_key("alpha", ["Loads things"])
    cache.put_dir(key, "Loads and stores things", "model-a", 2, source="llm")
    assert cache.get_dir(key, "model-a", 2) == "Loads and stores things"
    assert cache.get_dir(key, "model-b", 2) is None
    assert cache.get_dir(key, "model-a", 3) is None
    assert cache.get_dir_source(key) == "llm"


def test_directory_fallbacks_are_pluralised(tmp_path, monkeypatch, capsys):
    root = tmp_path / "plural"
    (root / "one").mkdir(parents=True)
    (root / "one" / "a.py").write_text("def a():\n    return 1\n")
    (root / "many").mkdir()
    (root / "many" / "a.py").write_text("def a():\n    return 1\n")
    (root / "many" / "b.py").write_text("def b():\n    return 2\n")
    (root / "nested" / "child").mkdir(parents=True)
    (root / "nested" / "child" / "c.py").write_text("def c():\n    return 3\n")
    monkeypatch.chdir(root)
    run(["--no-ai"])
    out = capsys.readouterr().out
    assert "Contains 1 file" in out
    assert "Contains 2 files" in out
    assert "Contains 1 file and 1 subdirectory" in out
    assert "1 files" not in out
    assert "1 subdirectories" not in out


def test_directory_descriptions_use_eight_word_limit_and_quality_checks():
    from explain.analyzer import _parse_directory_lines

    cfg = Config()
    numbers = {"1": {}, "2": {}}
    parsed = _parse_directory_lines(
        "1|Various helper functions\n"
        "2|Loads configuration values for every single service in the whole system",
        numbers,
        cfg,
    )
    assert "1" not in parsed
    assert parsed["2"] == "Loads configuration values for every single service in"
    assert len(parsed["2"].split()) == 8
