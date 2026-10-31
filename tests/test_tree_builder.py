from __future__ import annotations

from pathlib import Path

from explain.config import Config
from explain.scanner import scan
from explain.tree_builder import build_tree, directory_nodes, file_nodes, iter_with_depth


def write(path: Path, text: str = "x = 1\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, "utf-8")


def make_scan(tmp_path: Path):
    write(tmp_path / "main.py")
    write(tmp_path / "pkg" / "__init__.py", "from .core import run\n")
    write(tmp_path / "pkg" / "core.py")
    write(tmp_path / "pkg" / "sub" / "deep.py")
    write(tmp_path / "tests" / "test_core.py")
    return scan(tmp_path, cfg=Config())


def test_directories_precede_files_and_sort_case_insensitively(tmp_path):
    tree = build_tree(make_scan(tmp_path))
    names = [child.name for child in tree.children]
    assert names == [".gitignore", "pkg", "tests", "main.py"] or names == ["pkg", "tests", "main.py"]
    pkg = next(c for c in tree.children if c.name == "pkg")
    assert [c.name for c in pkg.children] == ["sub", "__init__.py", "core.py"]


def test_tree_paths_are_root_relative(tmp_path):
    tree = build_tree(make_scan(tmp_path))
    files = {n.path for n in file_nodes(tree)}
    assert "pkg/core.py" in files
    assert "pkg/sub/deep.py" in files
    assert all(not p.startswith("/") for p in files)


def test_display_depth_prunes_children(tmp_path):
    tree = build_tree(make_scan(tmp_path), display_depth=1)
    pkg = next(c for c in tree.children if c.name == "pkg")
    assert pkg.children == []
    assert {n.name for n in tree.children} >= {"pkg", "tests"}


def test_subtree_scan_root_is_displayed_as_subtree(tmp_path):
    write(tmp_path / "app" / "a.py")
    write(tmp_path / "app" / "inner" / "b.py")
    write(tmp_path / "other" / "c.py")
    result = scan(tmp_path, target=tmp_path / "app", cfg=Config())
    tree = build_tree(result)
    assert tree.name == "app"
    assert tree.path == ""
    names = {n.path for n in file_nodes(tree)}
    assert names == {"app/a.py", "app/inner/b.py"}


def test_empty_directories_are_kept(tmp_path):
    (tmp_path / "empty").mkdir()
    write(tmp_path / "a.py")
    tree = build_tree(scan(tmp_path, cfg=Config()))
    assert "empty" in [n.name for n in directory_nodes(tree)]


def test_iter_with_depth_visits_everything(tmp_path):
    tree = build_tree(make_scan(tmp_path))
    seen = list(iter_with_depth(tree))
    assert seen[0][1] is tree
    assert any(depth >= 2 for depth, _ in seen)


def test_all_scanned_files_reach_the_tree(tmp_path):
    result = make_scan(tmp_path)
    tree = build_tree(result)
    assert len(file_nodes(tree)) == len(result.files)
