from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from rich.console import Console

from explain import analyzer
from explain.analyzer import (
    AIStopped,
    _describe_with_retry,
    build_batches,
    clean_description,
    clean_path,
    parse_descriptions,
)
from explain.cache import Cache
from explain.config import Config
from explain.main import RunContext, _resolve_known
from explain.metadata import analyze
from explain.scanner import scan
from explain.tiers import assign
from explain.tree_builder import build_tree
from explain.renderer import RunStats, themed_console

from fake_ollama import FakeOllama


def write_repo(root: Path, count: int = 3) -> None:
    (root / "src").mkdir(exist_ok=True)
    for index in range(count):
        (root / "src" / f"mod{index}.py").write_text(
            f"def run_{index}(value):\n    return value + {index}\n"
        )
    (root / "README.md").write_text("# Demo\n")
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_mod.py").write_text("def test_one():\n    assert True\n")


def make_ctx(root: Path, **overrides) -> RunContext:
    cfg = Config(**overrides)
    cfg.budget = overrides.get("budget", 30.0)
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


@pytest.fixture
def repo(tmp_path):
    write_repo(tmp_path)
    return tmp_path


def chat_requests(fake):
    return [r for r in fake.requests if r["path"] == "/api/chat"]


def test_analyse_describes_pending_files(fake, repo):
    ctx = make_ctx(repo)
    assert {e.path for e in ctx.pending} == {"src/mod0.py", "src/mod1.py", "src/mod2.py"}
    summary = analyzer.analyse(ctx)
    assert summary.described == 3
    assert all(ctx.descriptions[p] == "Fake description" for p in ("src/mod0.py",))
    assert ctx.stats.analysed_by_ai == 3
    entry = next(e for e in ctx.result.files if e.path == "src/mod0.py")
    assert ctx.cache.get_file(
        "src/mod0.py", entry.digest, ctx.cfg.model, cfg_version(ctx)
    ) == "Fake description"
    request = chat_requests(fake)[0]["payload"]
    assert request["stream"] is False
    assert request["think"] is False
    assert request["options"]["temperature"] == 0
    assert request["keep_alive"] == 0


def cfg_version(ctx) -> int:
    return ctx.cfg.prompt_version


def test_second_run_uses_cache_and_makes_no_chat_request(fake, repo):
    ctx = make_ctx(repo)
    analyzer.analyse(ctx)
    ctx.cache.save()
    ctx2 = make_ctx(repo)
    assert ctx2.pending == []
    assert ctx2.stats.from_cache == 3
    assert len(chat_requests(fake)) == 1


def test_batching_respects_token_and_file_limits(repo):
    write_repo(repo, count=8)
    ctx = make_ctx(repo, batch_max_files=3)
    batches = build_batches(ctx, ctx.pending)
    assert [len(batch.files) for batch in batches] == [3, 3, 2]
    tokens = [b.tokens for b in batches]
    assert all(token >= 0 for token in tokens)
    for batch in batches:
        assert "FILE 1:" in batch.user_prompt
        assert "Describe these" in batch.user_prompt


def test_token_limit_splits_batches(repo):
    write_repo(repo, count=6)
    ctx = make_ctx(repo, batch_input_tokens=120, skeleton_max_chars=400)
    batches = build_batches(ctx, ctx.pending)
    assert len(batches) >= 2


def test_malformed_json_retries_then_falls_back(fake, repo):
    fake.chat_output = "not json at all"
    ctx = make_ctx(repo)
    ctx.cfg.model = "qwen2.5-coder:3b"
    summary = analyzer.analyse(ctx)
    assert len(chat_requests(fake)) == 4  # first attempt + one source-rich retry
    assert summary.stopped == "incomplete"
    assert ctx.stats.batch_failures == 2
    assert {r["payload"]["model"] for r in chat_requests(fake)} == {"qwen2.5-coder:3b"}
    assert ctx.stats.fallbacks == 3
    assert all("module" in ctx.descriptions[e.path].lower() for e in ctx.pending)


def test_first_response_malformed_second_valid(fake, repo):
    class Flaky:
        calls = 0

        def __call__(self, payload):
            Flaky.calls += 1
            return "garbage" if Flaky.calls == 1 else None

    original = fake.chat_output
    dynamic = FakeOllama.__dict__  # unused, kept for clarity
    del dynamic

    def responder(payload):
        Flaky.calls += 1
        return None

    fake.chat_output = None
    ctx = make_ctx(repo)
    real = analyzer._content

    def content_then_valid(payload):
        if payload.get("_first"):
            return "garbage"
        return real(payload)

    # Simulate: first call returns garbage by swapping manager.chat once.
    manager_cls = analyzer.OllamaManager
    seen = {"n": 0}

    def factory(cfg):
        manager = manager_cls(cfg=cfg)
        original_chat = manager.chat

        def chat(*args, **kwargs):
            seen["n"] += 1
            response = original_chat(*args, **kwargs)
            if seen["n"] == 1:
                response["message"]["content"] = "garbage"
            return response

        manager.chat = chat
        return manager

    analyzer.OllamaManager = factory
    try:
        summary = analyzer.analyse(ctx)
    finally:
        analyzer.OllamaManager = manager_cls
    fake.chat_output = original
    assert summary.described == 3
    assert seen["n"] == 2


def test_connection_failure_stops_after_one_retry(repo, monkeypatch):
    ctx = make_ctx(repo)
    calls = {"n": 0}

    class FailingManager:
        last_model = None

        def ensure_running(self):
            return False

        def load_model(self, model):
            pass

        def chat(self, *args, **kwargs):
            calls["n"] += 1
            raise analyzer.OllamaConnectionError("refused")

        def unload_model(self, model=None):
            pass

        def cleanup(self):
            pass

    monkeypatch.setattr(analyzer, "OllamaManager", lambda cfg: FailingManager())
    summary = analyzer.analyse(ctx)
    assert calls["n"] == 2
    assert summary.stopped == "connection"
    assert ctx.stats.fallbacks == 3


def test_budget_exhausted_skips_requests(fake, repo):
    write_repo(repo, count=40)
    ctx = make_ctx(repo, budget=0.0001)
    ctx.started = time.perf_counter() - 10
    summary = analyzer.analyse(ctx)
    assert chat_requests(fake) == []
    assert summary.stopped == "budget"
    assert ctx.stats.fallbacks == 40


def test_model_not_found_is_reported_without_crash(fake, repo):
    ctx = make_ctx(repo)
    fake.missing.add(ctx.cfg.model)
    summary = analyzer.analyse(ctx)
    assert summary.described == 0
    assert ctx.stats.fallbacks == 3
    assert chat_requests(fake) == []


def _batch(paths):
    from explain.analyzer import Batch

    return Batch(
        files=[object() for _ in paths],
        user_prompt="",
        numbers={str(index + 1): path for index, path in enumerate(paths)},
    )


def test_parse_numbered_lines():
    cfg = Config()
    batch = _batch(["src/a.py", "lib/b.py"])
    text = "1|Parses things\n2|Renders output"
    assert parse_descriptions(text, batch, cfg) == {
        "src/a.py": "Parses things",
        "lib/b.py": "Renders output",
    }
    fenced = "```\n1 | Parses things\n2 | Renders output\n```"
    assert parse_descriptions(fenced, batch, cfg) == {
        "src/a.py": "Parses things",
        "lib/b.py": "Renders output",
    }
    assert parse_descriptions(
        "File 2|Renders output\nFile 1|Parses things", batch, cfg
    ) == {"src/a.py": "Parses things", "lib/b.py": "Renders output"}
    assert parse_descriptions("no answer here", batch, cfg) == {}
    assert parse_descriptions("1|unclear\n2|various utilities", batch, cfg) == {}


def test_parse_json_fallback():
    cfg = Config()
    batch = _batch(["src/a.py", "lib/b.py"])
    assert parse_descriptions(
        '```json\n{"descriptions": [{"path": "src/a.py", "description": "Parses things"}]}\n```',
        batch,
        cfg,
    ) == {"src/a.py": "Parses things"}
    assert parse_descriptions(
        '{"src/a.py": "Loads config", "lib/b.py": "Draws charts"}',
        batch,
        cfg,
    ) == {"src/a.py": "Loads config", "lib/b.py": "Draws charts"}
    assert parse_descriptions(
        '[{"file": "lib/b.py", "description": "Serves requests"}]', batch, cfg
    ) == {"lib/b.py": "Serves requests"}
    assert parse_descriptions(
        '{"path": "src/other.py", "description": "Not in batch"}', batch, cfg
    ) == {}


def test_clean_description_trims_at_word_boundary():
    cfg = Config()
    text = "Parses configuration files and merges defaults with environment overrides for users now every single time"
    cleaned = clean_description(text, cfg)
    assert len(cleaned.split()) == cfg.docstring_max_words
    assert cleaned == "Parses configuration files and merges defaults with environment overrides for users now"


def test_clean_description_rejects_empty_and_generic():
    cfg = Config()
    assert clean_description("", cfg) is None
    assert clean_description("Utilities", cfg) is None
    assert clean_description("Miscellaneous helpers", cfg) is None
    assert clean_description("This file.", cfg) is None
    assert clean_description("Parses command-line arguments and runs commands", cfg) is not None


def test_clean_path_normalises_separators():
    assert clean_path("./src\\main.py") == "src/main.py"
    assert clean_path('"src/x.py"') == "src/x.py"


def test_generic_description_is_not_committed(fake, repo):
    fake.chat_output = json.dumps(
        {
            "descriptions": [
                {"path": "src/mod0.py", "description": "src/mod0.py"},
                {"path": "src/mod1.py", "description": "This file"},
                {"path": "src/mod2.py", "description": "Handles values"},
            ]
        }
    )
    ctx = make_ctx(repo)
    summary = analyzer.analyse(ctx)
    assert summary.described == 1
    assert ctx.descriptions["src/mod2.py"] == "Handles values"
    assert "Handles values" not in ctx.descriptions.get("src/mod0.py", "")


def large_module(root: Path, marker: str) -> None:
    body = "".join(f"    value_{index} = {index}\n" for index in range(50))
    (root / "large.py").write_text(
        '"""Large helper module."""\n\n\n'
        "def alpha(value):\n"
        + body
        + f'    return "{marker}"\n'
    )


def test_retry_uses_same_model_with_more_source(tmp_path, monkeypatch):
    root = tmp_path / "retry"
    root.mkdir()
    large_module(root, "UNIQUE_SNIPPET_42")
    ctx = make_ctx(root)
    ctx.cfg.model = "lfm3:1.7b"
    calls = []

    class Manager:
        last_model = None

        def ensure_running(self):
            return False

        def load_model(self, model):
            pass

        def unload_model(self, model=None):
            pass

        def cleanup(self):
            pass

        def chat(self, model, messages, **kwargs):
            prompt = messages[-1]["content"]
            calls.append((model, prompt))
            if "UNIQUE_SNIPPET_42" in prompt:
                content = "1|Handles unique snippets"
            else:
                content = "1|This file"
            return {
                "message": {"content": content},
                "prompt_eval_count": 10,
                "eval_count": 5,
            }

    monkeypatch.setattr(analyzer, "OllamaManager", lambda cfg: Manager())
    summary = analyzer.analyse(ctx)
    assert summary.retried == 1
    assert [model for model, _ in calls] == ["lfm3:1.7b"] * 3
    assert "UNIQUE_SNIPPET_42" not in calls[0][1]
    assert "UNIQUE_SNIPPET_42" in calls[2][1]
    assert ctx.descriptions["large.py"] == "Handles unique snippets"


def test_failed_retry_falls_back_without_switching_models(tmp_path, monkeypatch):
    root = tmp_path / "retry-fail"
    root.mkdir()
    large_module(root, "STILL_UNKNOWN")
    ctx = make_ctx(root)
    ctx.cfg.model = "lfm3:1.7b"
    models = []

    class Manager:
        last_model = None

        def ensure_running(self):
            return False

        def load_model(self, model):
            pass

        def unload_model(self, model=None):
            pass

        def cleanup(self):
            pass

        def chat(self, model, messages, **kwargs):
            models.append(model)
            return {
                "message": {"content": "1|This file"},
                "prompt_eval_count": 10,
                "eval_count": 5,
            }

    monkeypatch.setattr(analyzer, "OllamaManager", lambda cfg: Manager())
    summary = analyzer.analyse(ctx)
    assert summary.retried == 0
    assert summary.failed == 1
    assert set(models) == {"lfm3:1.7b"}
    assert ctx.descriptions["large.py"].startswith("Python module: alpha")


def test_retry_stub_returns_parsed_after_error(repo):
    ctx = make_ctx(repo)
    batch = build_batches(ctx, ctx.pending)[0]

    class Manager:
        calls = 0

        def chat(self, model, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                raise analyzer.OllamaError("boom")
            return {
                "message": {
                    "content": json.dumps(
                        {
                            "descriptions": [
                                {"path": e.path, "description": "Recovered description"}
                                for e in batch.files
                            ]
                        }
                    )
                }
            }

    parsed, usage = _describe_with_retry(Manager(), ctx.cfg, batch, ctx)
    assert set(parsed.values()) == {"Recovered description"}
    assert usage.requests == 1


def test_rejected_fallback_is_cached_so_warm_run_is_silent(fake, repo, tmp_path):
    root = tmp_path / "one"
    root.mkdir()
    (root / "helpers.py").write_text("def helper(value):\n    return value\n")
    fake.chat_output = "1|unclear"
    ctx = make_ctx(root)
    summary = analyzer.analyse(ctx)
    assert summary.failed == 1
    assert ctx.stats.fallbacks == 1
    ctx.cache.save()

    before = len(chat_requests(fake))
    ctx2 = make_ctx(root)
    assert ctx2.pending == []
    assert ctx2.stats.from_cache == 1
    assert ctx2.descriptions["helpers.py"].startswith("Python module:")
    assert len(chat_requests(fake)) == before
