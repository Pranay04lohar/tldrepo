from __future__ import annotations

from pathlib import Path

from rich.console import Console

from explain.config import Config
from explain.renderer import (
    ProgressLine,
    RunStats,
    render_footer,
    render_stats,
    render_timing,
    render_tree,
    truncate,
)
from explain.scanner import ScannedFile, ScanResult
from explain.tree_builder import Node, build_tree
from explain.scanner import scan


def capture(width: int = 100) -> tuple[Console, "list[str]"]:
    console = Console(record=True, width=width, highlight=False, emoji=False)
    return console


def plain(console: Console) -> str:
    return console.export_text()


def node_tree() -> Node:
    root = Node(name="proj", path="", is_dir=True)
    src = Node(name="src", path="src", is_dir=True)
    src.children.append(
        Node(
            name="main.py",
            path="src/main.py",
            is_dir=False,
            file=ScannedFile("src/main.py", Path("/tmp/src/main.py"), 10, "Python", "abc"),
        )
    )
    root.children.append(src)
    root.children.append(
        Node(
            name="README.md",
            path="README.md",
            is_dir=False,
            file=ScannedFile("README.md", Path("/tmp/README.md"), 10, "Markdown", "def"),
        )
    )
    return root


def test_tree_has_ascii_connectors_and_descriptions():
    console = capture()
    render_tree(console, node_tree(), {"src": "Source code", "src/main.py": "Application entry point"})
    out = plain(console)
    assert "proj/" in out
    assert "├── src/" in out
    assert "└── README.md" in out
    assert "Source code" in out
    assert "Application entry point" in out


def test_descriptions_align_in_one_column():
    console = capture(width=100)
    render_tree(
        console,
        node_tree(),
        {
            "src": "Source code",
            "src/main.py": "Entry point",
            "README.md": "Project overview",
        },
    )
    lines = [line for line in plain(console).splitlines() if "Source code" in line or "Entry point" in line]
    columns = {line.index("#") if "#" in line else -1 for line in lines}
    positions = set()
    for line in lines:
        marker = line.find("Source code") if "Source code" in line else line.find("Entry point")
        positions.add(marker)
    assert len(positions) == 1


def test_long_description_is_truncated_to_terminal_width():
    console = capture(width=60)
    long_desc = "A very long description that cannot possibly fit in a narrow terminal window at all"
    render_tree(console, node_tree(), {"src/main.py": long_desc})
    out = plain(console)
    for line in out.splitlines():
        assert len(line) <= 60
    assert "\u2026" in out


def test_missing_description_renders_no_trailing_separator():
    console = capture()
    render_tree(console, node_tree(), {})
    out = plain(console)
    assert "src/" in out
    assert "# " not in out


def test_footer_and_timing_render():
    console = capture()
    stats = RunStats(
        files_scanned=5,
        analysed_by_ai=2,
        from_cache=1,
        deterministic=2,
        duration=1.25,
        phases={"scan": 0.1, "render": 0.2},
    )
    render_footer(console, stats)
    render_timing(console, stats)
    out = plain(console)
    assert "5 scanned" in out and "2 by AI" in out and "1 cached" in out
    assert "timing: scan 0.10s" in out


def test_pending_files_are_reported():
    console = capture()
    render_footer(console, RunStats(files_scanned=9, pending=4, duration=25.0))
    out = plain(console)
    assert "4 pending" in out
    assert "run explain again" in out


def test_stats_table(tmp_path):
    (tmp_path / "a.py").write_text("x=1\n")
    (tmp_path / "b.ts").write_text("let x=1\n")
    result = scan(tmp_path, cfg=Config())
    console = capture()
    render_stats(console, result, elapsed=0.5)
    out = plain(console)
    assert "Python" in out and "TypeScript" in out
    assert "2 files" in out


def test_truncate_appends_ellipsis():
    assert truncate("abcdef", 4) == "abc\u2026"
    assert truncate("abc", 3) == "abc"
    assert truncate("abc", 0) == ""


def test_progress_is_silent_when_not_a_terminal():
    console = capture()
    with ProgressLine(console, total=5) as progress:
        progress.update(2)
    assert plain(console) == ""
    assert progress.enabled is False


def test_progress_emits_a_single_updating_line_on_tty():
    console = Console(record=True, width=80, force_terminal=True, highlight=False)
    with ProgressLine(console, total=4) as progress:
        progress._last_render = 0
        progress.update(1)
    out = plain(console)
    assert "Analysing 4 files... 1/4" in out
