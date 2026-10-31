from __future__ import annotations

import os
from pathlib import Path

import pytest

from explain.config import Config
from explain.scanner import (
    ScannedFile,
    apply_rules,
    find_root,
    language_for,
    parse_gitignore,
    scan,
)


def write(path: Path, text: str = "x = 1\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")
    return path


def paths(result) -> set[str]:
    return {f.path for f in result.files}


def test_find_root_uses_nearest_git_ancestor(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "src" / "pkg"
    nested.mkdir(parents=True)
    assert find_root(nested) == tmp_path.resolve()


def test_find_root_falls_back_to_start(tmp_path):
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_root(nested) == nested.resolve()


def test_recursive_scan_and_language_detection(tmp_path):
    write(tmp_path / "app.py")
    write(tmp_path / "web" / "index.ts")
    write(tmp_path / "README.md", "# hi\n")
    result = scan(tmp_path, cfg=Config())
    assert paths(result) == {"app.py", "web/index.ts", "README.md"}
    by_name = {f.path: f for f in result.files}
    assert by_name["app.py"].language == "Python"
    assert by_name["web/index.ts"].language == "TypeScript"
    assert by_name["README.md"].language == "Markdown"
    assert "web" in result.dirs


def test_default_ignored_directories(tmp_path):
    write(tmp_path / "keep.py")
    for ignored in ("node_modules", ".venv", "__pycache__", "dist", ".git"):
        write(tmp_path / ignored / "junk.py")
    result = scan(tmp_path, cfg=Config())
    assert paths(result) == {"keep.py"}
    assert result.skipped.get("ignored-dir", 0) == 5


def test_gitignore_patterns(tmp_path):
    write(tmp_path / ".gitignore", "*.log\nsecret/\n/root_only.py\n!keep.log\n")
    write(tmp_path / "a.log")
    write(tmp_path / "keep.log")
    write(tmp_path / "secret" / "x.py")
    write(tmp_path / "root_only.py")
    write(tmp_path / "pkg" / "root_only.py")
    write(tmp_path / "main.py")
    result = scan(tmp_path, cfg=Config())
    assert paths(result) == {"keep.log", "pkg/root_only.py", "main.py", ".gitignore"}


def test_nested_gitignore_is_scoped_to_its_directory(tmp_path):
    write(tmp_path / ".gitignore", "*.gen.py\n")
    write(tmp_path / "sub" / ".gitignore", "local.py\n!keep.gen.py\n")
    write(tmp_path / "sub" / "local.py")
    write(tmp_path / "sub" / "keep.gen.py")
    write(tmp_path / "other" / "local.py")
    write(tmp_path / "other" / "thing.gen.py")
    result = scan(tmp_path, cfg=Config())
    assert paths(result) == {"sub/keep.gen.py", "other/local.py", ".gitignore", "sub/.gitignore"}


def test_double_star_pattern():
    rules = parse_gitignore("build/**/tmp\n")
    assert apply_rules(rules, "build/a/tmp", False)
    assert apply_rules(rules, "build/tmp", False)
    assert not apply_rules(rules, "src/tmp", False)


def test_directory_only_pattern_does_not_match_file():
    rules = parse_gitignore("cache/\n")
    assert apply_rules(rules, "cache", True)
    assert not apply_rules(rules, "cache", False)


def test_binary_large_empty_and_lockfiles_are_skipped(tmp_path):
    (tmp_path / "image.bin").write_bytes(b"\x00\x01\x02")
    write(tmp_path / "blob.txt", "a" * 300_000)
    write(tmp_path / "empty.py", "")
    write(tmp_path / "uv.lock", "locked\n")
    write(tmp_path / "app.min.js", "var a=1;\n")
    write(tmp_path / "data.csv", "a,b\n1,2\n")
    write(tmp_path / "ok.py")
    result = scan(tmp_path, cfg=Config(max_file_size=1000))
    assert paths(result) == {"ok.py"}
    assert result.skipped["binary"] >= 1
    assert result.skipped["large"] == 1
    assert result.skipped["empty"] == 1
    assert result.skipped["lockfile"] == 1
    assert result.skipped["generated"] >= 1
    assert result.skipped["data"] == 1


def test_symlinks_are_not_followed(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    write(target / "inner.py")
    link = tmp_path / "link"
    os.symlink(target, link)
    os.symlink(target / "inner.py", tmp_path / "linked.py")
    result = scan(tmp_path, cfg=Config())
    assert paths(result) == {"real/inner.py"}
    assert result.skipped["symlink"] == 2


def test_hidden_files_are_included(tmp_path):
    write(tmp_path / ".env", "A=1\n")
    write(tmp_path / ".github" / "workflow.yml", "on: push\n")
    result = scan(tmp_path, cfg=Config())
    assert paths(result) == {".env", ".github/workflow.yml"}


def test_target_subtree_limits_scan(tmp_path):
    write(tmp_path / "src" / "a.py")
    write(tmp_path / "src" / "deep" / "b.py")
    write(tmp_path / "tests" / "test_a.py")
    result = scan(tmp_path, target=tmp_path / "src", cfg=Config())
    assert paths(result) == {"src/a.py", "src/deep/b.py"}


def test_max_depth_limits_scan(tmp_path):
    write(tmp_path / "a.py")
    write(tmp_path / "one" / "b.py")
    write(tmp_path / "one" / "two" / "c.py")
    result = scan(tmp_path, cfg=Config(max_depth=1))
    assert paths(result) == {"a.py", "one/b.py"}
    assert "one/two" in result.limits_hit


def test_digest_is_stable_and_content_addressed(tmp_path):
    write(tmp_path / "a.py", "print(1)\n")
    first = scan(tmp_path, cfg=Config())
    write(tmp_path / "a.py", "print(2)\n")
    second = scan(tmp_path, cfg=Config())
    assert first.files[0].digest != second.files[0].digest
    write(tmp_path / "b.py", "print(1)\n")
    third = scan(tmp_path, cfg=Config())
    by_name = {f.path: f for f in third.files}
    assert by_name["a.py"].digest != by_name["b.py"].digest


def test_single_file_target(tmp_path):
    (tmp_path / ".git").mkdir()
    write(tmp_path / "src" / "main.py", "print(1)\n")
    result = scan(tmp_path, target=tmp_path / "src" / "main.py", cfg=Config())
    assert paths(result) == {"src/main.py"}
    assert result.files[0].language == "Python"


def test_unreadable_file_is_skipped_gracefully(tmp_path):
    path = write(tmp_path / "secret.py")
    path.chmod(0o000)
    try:
        result = scan(tmp_path, cfg=Config())
        assert paths(result) == set()
        assert result.skipped["unreadable"] == 1
    finally:
        path.chmod(0o644)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("main.py", "Python"),
        ("Dockerfile", "Dockerfile"),
        ("Makefile", "Makefile"),
        ("app.tsx", "TypeScript"),
        ("lib.rs", "Rust"),
        ("weird.xyz", "Other"),
    ],
)
def test_language_for(name, expected):
    assert language_for(Path(name)) == expected
