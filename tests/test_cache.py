from __future__ import annotations

import json
import os
from pathlib import Path

from tldrepo.cache import Cache
from tldrepo.config import CACHE_VERSION, PROMPT_VERSION

DIGEST = "a" * 64
MODEL = "qwen2.5-coder:1.5b"


def test_cache_directory_and_gitignore_guard(tmp_path):
    cache = Cache(tmp_path).load()
    assert (tmp_path / ".tldrepo").is_dir()
    assert (tmp_path / ".tldrepo" / ".gitignore").read_text().strip() == "*"
    assert cache.path == tmp_path / ".tldrepo" / "cache.json"


def test_put_get_roundtrip(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_file("src/a.py", DIGEST, MODEL, 1, "Loads records from disk")
    assert cache.get_file("src/a.py", DIGEST, MODEL) == "Loads records from disk"
    assert cache.dirty
    cache.save()
    reloaded = Cache(tmp_path).load()
    assert reloaded.get_file("src/a.py", DIGEST, MODEL) == "Loads records from disk"


def test_hash_change_invalidates(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_file("a.py", DIGEST, MODEL, 1, "Something true")
    assert cache.get_file("a.py", "b" * 64, MODEL) is None


def test_model_change_invalidates_tier1_but_not_tier0(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_file("a.py", DIGEST, MODEL, 1, "AI description")
    cache.put_file("tests/test_a.py", DIGEST, MODEL, 0, "Tests for a (1 tests)")
    assert cache.get_file("a.py", DIGEST, "other:3b") is None
    assert cache.get_file("tests/test_a.py", DIGEST, "other:3b") == "Tests for a (1 tests)"


def test_prompt_version_change_invalidates(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_file("a.py", DIGEST, MODEL, 1, "AI description", prompt_version=PROMPT_VERSION)
    assert cache.get_file("a.py", DIGEST, MODEL, prompt_version=PROMPT_VERSION + 1) is None


def test_prune_removes_deleted_files(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_file("keep.py", DIGEST, MODEL, 1, "Keep me")
    cache.put_file("gone.py", DIGEST, MODEL, 1, "Delete me")
    removed = cache.prune({"keep.py"})
    assert removed == 1
    assert cache.get_file("gone.py", DIGEST, MODEL) is None


def test_malformed_cache_is_backed_up_and_reset(tmp_path):
    directory = tmp_path / ".tldrepo"
    directory.mkdir()
    (directory / "cache.json").write_text("{not json", "utf-8")
    cache = Cache(tmp_path).load()
    assert cache.recovered is True
    assert cache.data["files"] == {}
    assert (directory / "cache.json.bak").exists()
    assert not (directory / "cache.json").exists()


def test_unknown_version_is_backed_up_and_reset(tmp_path):
    directory = tmp_path / ".tldrepo"
    directory.mkdir()
    (directory / "cache.json").write_text(
        json.dumps({"version": 999, "files": {"a.py": {}}, "dirs": {}}), "utf-8"
    )
    cache = Cache(tmp_path).load()
    assert cache.recovered
    assert cache.data["version"] == CACHE_VERSION
    assert (directory / "cache.json.bak").exists()


def test_atomic_write_leaves_no_temp_files(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_file("a.py", DIGEST, MODEL, 1, "Atomic")
    cache.save()
    leftovers = [p.name for p in (tmp_path / ".tldrepo").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    payload = json.loads((tmp_path / ".tldrepo" / "cache.json").read_text())
    assert payload["version"] == CACHE_VERSION
    assert payload["files"]["a.py"]["hash"] == DIGEST


def test_failed_write_keeps_previous_cache(tmp_path, monkeypatch):
    cache = Cache(tmp_path).load()
    cache.put_file("a.py", DIGEST, MODEL, 1, "Original")
    cache.save()
    before = (tmp_path / ".tldrepo" / "cache.json").read_text()

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    cache.put_file("b.py", DIGEST, MODEL, 1, "Second")
    try:
        cache.save()
    except OSError:
        pass
    assert (tmp_path / ".tldrepo" / "cache.json").read_text() == before
    leftovers = [p for p in (tmp_path / ".tldrepo").iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_source_code_is_never_cached(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_file("a.py", DIGEST, MODEL, 1, "Description only")
    cache.save()
    payload = (tmp_path / ".tldrepo" / "cache.json").read_text()
    assert "Description only" in payload
    assert set(json.loads(payload)["files"]["a.py"]) == {
        "hash",
        "model",
        "prompt_version",
        "tier",
        "description",
        "source",
    }


def test_directory_descriptions_are_cached_by_key(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_dir("abc123", "Core business logic")
    cache.save()
    assert Cache(tmp_path).load().get_dir("abc123") == "Core business logic"
    assert Cache(tmp_path).load().get_dir("missing") is None


def test_clear_keeps_cache_file_usable(tmp_path):
    cache = Cache(tmp_path).load()
    cache.put_file("a.py", DIGEST, MODEL, 1, "Thing")
    cache.clear()
    cache.save()
    assert Cache(tmp_path).load().data["files"] == {}


def test_v2_cache_is_migrated_with_sources(tmp_path):
    (tmp_path / ".tldrepo").mkdir()
    (tmp_path / ".tldrepo" / "cache.json").write_text(
        json.dumps(
            {
                "version": 2,
                "files": {
                    "src/a.py": {
                        "hash": DIGEST,
                        "model": MODEL,
                        "prompt_version": PROMPT_VERSION,
                        "tier": 1,
                        "description": "AI description",
                    },
                    "tests/test_a.py": {
                        "hash": DIGEST,
                        "model": MODEL,
                        "prompt_version": PROMPT_VERSION,
                        "tier": 0,
                        "description": "Tests for a",
                    },
                },
                "dirs": {"oldkey": "Old directory description"},
            }
        )
    )
    cache = Cache(tmp_path).load()
    assert cache.data["version"] == CACHE_VERSION
    assert cache.get_file("src/a.py", DIGEST, MODEL) == "AI description"
    assert cache.get_file_source("src/a.py", DIGEST, MODEL) == "llm"
    assert cache.get_file_source("tests/test_a.py", DIGEST, MODEL) == "rule"
    assert cache.get_dir("oldkey") == "Old directory description"
    assert cache.get_dir_source("oldkey") == "rule"
    assert cache.dirty is True
    assert not cache.recovered
