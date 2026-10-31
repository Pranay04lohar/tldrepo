from __future__ import annotations

import io
from pathlib import Path

from rich.console import Console

from tldrepo.config import Config
from tldrepo.renderer import (
    ProgressLine,
    RunStats,
    description_style,
    render_footer,
    render_stats,
    render_legend,
    render_timing,
    render_tree,
    themed_console,
    truncate,
)
from tldrepo.scanner import ScannedFile, ScanResult
from tldrepo.tree_builder import Node, build_tree
from tldrepo.scanner import scan


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
    assert "5 files scanned" in out and "2 files by AI" in out and "1 file cached" in out
    assert "timing: scan 0.10s" in out


def test_footer_pluralises_file_counts():
    console = capture()
    render_footer(console, RunStats(files_scanned=1, analysed_by_ai=1, duration=1.0))
    out = plain(console)
    assert "1 file scanned" in out
    assert "1 file by AI" in out
    assert "1 files" not in out


def test_pending_files_are_reported():
    console = capture()
    render_footer(console, RunStats(files_scanned=9, pending=4, duration=25.0))
    out = plain(console)
    assert "4 files pending" in out
    assert "run tldrepo again" in out


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


def test_colour_follows_description_source_and_directories_are_purple(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = io.StringIO()
    console = themed_console(file=stream, force_terminal=True, width=100)
    render_tree(
        console,
        node_tree(),
        {"src": "Source code", "src/main.py": "Parses arguments", "README.md": "Read me"},
        sources={"src": "rule", "src/main.py": "llm", "README.md": "fallback"},
    )
    out = stream.getvalue()
    assert "\x1b[" in out
    assert "35m" in out  # bold magenta directory
    assert "36m" in out  # cyan LLM description
    assert "2;3m" in out or "3;2m" in out  # dim italic fallback


def test_no_color_strips_ansi(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = io.StringIO()
    console = themed_console(file=stream, force_terminal=True, no_color=True, width=100)
    render_tree(console, node_tree(), {"src": "Source code"}, sources={"src": "rule"})
    assert "\x1b[" not in stream.getvalue()


def test_non_tty_output_has_no_escape_codes(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    stream = io.StringIO()
    console = themed_console(file=stream, force_terminal=False, width=100)
    render_tree(console, node_tree(), {"src": "Source code"}, sources={"src": "llm"})
    assert "\x1b[" not in stream.getvalue()


def test_no_color_environment_variable_is_respected(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    stream = io.StringIO()
    console = themed_console(file=stream, force_terminal=True, width=100)
    render_tree(console, node_tree(), {"src": "Source code"})
    assert "\x1b[" not in stream.getvalue()


def test_one_description_per_source_renders_with_expected_style(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    sources = {
        "llm.py": "llm",
        "docstring.py": "docstring",
        "rule.py": "rule",
        "fallback.py": "fallback",
    }
    descriptions = {
        "llm.py": "Model-written description",
        "docstring.py": "Docstring description",
        "rule.py": "Rule description",
        "fallback.py": "Fallback description",
    }
    root = Node(name="proj", path="", is_dir=True)
    for name in sources:
        root.children.append(
            Node(
                name=name,
                path=name,
                is_dir=False,
                file=ScannedFile(name, Path("/tmp") / name, 10, "Python", name),
            )
        )
    stream = io.StringIO()
    console = themed_console(file=stream, force_terminal=True, width=100)
    render_tree(console, root, descriptions, sources=sources)
    out = stream.getvalue()
    for text in descriptions.values():
        assert text in out
    assert description_style("llm") == "cyan"
    assert description_style("docstring") is None
    assert description_style("rule") is None
    assert description_style("fallback") == "dim italic"
    assert "\x1b[36m" in out  # cyan only for the LLM description
    assert "\x1b[" in out


def test_footer_counts_ai_directories():
    console = capture()
    render_footer(console, RunStats(files_scanned=4, dirs_by_ai=3, duration=1.0))
    out = plain(console)
    assert "3 dirs by AI" in out


def test_legend_mentions_all_sources():
    console = capture()
    render_legend(console)
    out = plain(console)
    assert "legend:" in out
    assert "LLM" in out
    assert "docstring/rule" in out
    assert "fallback/pending" in out
