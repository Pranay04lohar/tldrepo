"""Compact ASCII rendering with Rich.

The renderer owns layout only: connectors, alignment, ellipsis truncation,
progress, footer and statistics. It never decides what a description says.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field

from rich.console import Console
from rich.table import Table
from rich.text import Text

from .scanner import ScannedFile, ScanResult
from .tiers import plural
from .tree_builder import Node


@dataclass
class RunStats:
    files_scanned: int = 0
    analysed_by_ai: int = 0
    from_cache: int = 0
    deterministic: int = 0
    pending: int = 0
    duplicate_reuse: int = 0
    batches: int = 0
    batch_failures: int = 0
    fallbacks: int = 0
    duration: float = 0.0
    model: str = ""
    phases: dict[str, float] = field(default_factory=dict)


def truncate(text: str, width: int) -> str:
    if width <= 0:
        return ""
    if len(text) <= width:
        return text
    if width == 1:
        return "\u2026"
    return text[: width - 1].rstrip() + "\u2026"


def _vis_len(value: str) -> int:
    return len(value)


def description_style(source: str | None) -> str | None:
    if source == "llm":
        return "cyan"
    if source in {"fallback", "pending"}:
        return "dim italic"
    return None


def render_tree(
    console: Console,
    root: Node,
    descriptions: dict[str, str],
    depth: int | None = None,
    sources: dict[str, str] | None = None,
) -> None:
    """Print the tree once, directory-first, with aligned descriptions."""
    width = console.width or 80
    sources = sources or {}

    rows: list[tuple[str, str, str, str | None]] = []  # prefix, label, description, style

    def label_for(node: Node) -> str:
        return node.name + "/" if node.is_dir else node.name

    def emit(node: Node, prefix: str, is_last: bool, is_root: bool) -> None:
        desc = descriptions.get(node.path, "")
        style = description_style(sources.get(node.path)) if desc else None
        if is_root:
            rows.append(("", label_for(node), desc, style))
        else:
            connector = "\u2514\u2500\u2500 " if is_last else "\u251c\u2500\u2500 "
            rows.append((prefix + connector, label_for(node), desc, style))
            prefix = prefix + ("    " if is_last else "\u2502   ")
        children = node.children
        for index, child in enumerate(children):
            emit(child, prefix, index == len(children) - 1, False)

    emit(root, "", True, True)

    label_width = max(
        (_vis_len(prefix) + _vis_len(label) for prefix, label, _, _ in rows), default=0
    )
    desc_col = min(label_width + 2, max(30, int(width * 0.5)))
    desc_col = min(desc_col, width - 12) if width > 30 else label_width + 2

    console.print()
    for index, (prefix, label, desc, style) in enumerate(rows):
        if index == 1:
            console.print(Text("\u2502", style="tree.line"))
        line = Text()
        line.append(prefix, style="tree.line")
        label_style = "tree.dir" if label.endswith("/") else "tree.file"
        if desc and desc_col > _vis_len(prefix):
            label_cell = label
            pad = desc_col - _vis_len(prefix) - _vis_len(label_cell)
            if pad < 1:
                label_cell = truncate(label_cell, desc_col - _vis_len(prefix) - 1)
                pad = max(1, desc_col - _vis_len(prefix) - _vis_len(label_cell))
            line.append(label_cell, style=label_style)
            line.append(" " * pad)
            remaining = width - desc_col
            line.append(truncate(desc, remaining), style=style)
        else:
            line.append(label, style=label_style)
            if desc:
                line.append(
                    "  # " + truncate(desc, max(0, width - _vis_len(line))), style=style
                )
        console.print(line, soft_wrap=True, crop=True)
    console.print()


def render_file_detail(
    console: Console,
    entry: ScannedFile,
    description: str,
    skeleton_summary: list[tuple[str, str]],
    source: str | None = None,
) -> None:
    console.print()
    console.print(Text(entry.path, style="tree.file"), soft_wrap=True)
    if description:
        console.print(
            Text("  " + description, style=description_style(source)), soft_wrap=True
        )
    for key, value in skeleton_summary:
        line = Text()
        line.append(f"  {key}: ", style="dim")
        line.append(value)
        console.print(line, soft_wrap=True)
    console.print()


def _stat(parts: list[Text], count: int, label: str) -> None:
    if parts:
        parts.append(Text("  "))
    item = Text()
    item.append(str(count), style="green")
    item.append(" " + label, style="dim")
    parts.append(item)


def render_footer(console: Console, stats: RunStats) -> None:
    parts: list[Text] = []
    _stat(
        parts,
        stats.files_scanned,
        ("file" if stats.files_scanned == 1 else "files") + " scanned",
    )
    _stat(
        parts,
        stats.analysed_by_ai,
        ("file" if stats.analysed_by_ai == 1 else "files") + " by AI",
    )
    _stat(
        parts,
        stats.from_cache,
        ("file" if stats.from_cache == 1 else "files") + " cached",
    )
    _stat(
        parts,
        stats.deterministic,
        ("file" if stats.deterministic == 1 else "files") + " deterministic",
    )
    if stats.duplicate_reuse:
        _stat(
            parts,
            stats.duplicate_reuse,
            "duplicate" if stats.duplicate_reuse == 1 else "duplicates",
        )
    if stats.pending:
        _stat(
            parts,
            stats.pending,
            ("file" if stats.pending == 1 else "files") + " pending \u2014 run explain again",
        )
    if parts:
        parts.append(Text("  "))
    duration = Text()
    duration.append(f"{stats.duration:.2f}", style="green")
    duration.append("s", style="dim")
    parts.append(duration)
    line = Text()
    for part in parts:
        line.append_text(part)
    console.print(line, soft_wrap=True)


def render_legend(console: Console) -> None:
    line = Text("legend: ", style="dim")
    line.append("LLM", style="cyan")
    line.append("  docstring/rule", style="default")
    line.append("  fallback/pending", style="dim italic")
    console.print(line, soft_wrap=True)


def render_timing(console: Console, stats: RunStats) -> None:
    order = ["scan", "cache", "load", "prefill", "decode", "cleanup", "render"]
    parts = []
    for key in order:
        if key in stats.phases:
            parts.append(f"{key} {stats.phases[key]:.2f}s")
    for key, value in stats.phases.items():
        if key not in order:
            parts.append(f"{key} {value:.2f}s")
    if parts:
        console.print(Text("timing: " + "  ".join(parts), style="footer"), soft_wrap=True)


def render_stats(console: Console, result: ScanResult, elapsed: float) -> None:
    table = Table(title="Languages", header_style="bold", box=None, pad_edge=False)
    table.add_column("Language")
    table.add_column("Files", justify="right")
    table.add_column("Bytes", justify="right")
    counts: dict[str, list[int]] = {}
    for entry in result.files:
        bucket = counts.setdefault(entry.language, [0, 0])
        bucket[0] += 1
        bucket[1] += entry.size
    for language, (files, size) in sorted(
        counts.items(), key=lambda item: (-item[1][0], item[0].lower())
    ):
        table.add_row(language, str(files), f"{size:,}")
    console.print(table)

    console.print(
        Text(
            f"{plural(len(result.files), 'file')}, {sum(f.size for f in result.files):,} bytes, "
            f"{plural(len(result.dirs), 'directory', 'directories')}, {elapsed:.2f}s",
            style="footer",
        )
    )
    if result.skipped:
        reasons = ", ".join(f"{name} {count}" for name, count in sorted(result.skipped.items()))
        console.print(Text("skipped: " + reasons, style="footer"), soft_wrap=True)


class ProgressLine:
    """A single transient status line; silent when the output is not a terminal."""

    def __init__(self, console: Console, total: int, verb: str = "Analysing"):
        self.console = console
        self.total = total
        self.verb = verb
        self.done = 0
        self.enabled = bool(total) and console.is_terminal and not console.is_dumb_terminal
        self._started = 0.0
        self._last_width = 0
        self._last_render = 0.0

    def __enter__(self):
        self._started = time.perf_counter()
        return self

    def __exit__(self, *exc_info):
        if self.enabled:
            self._clear()
        return False

    def update(self, done: int | None = None, extra: str = "") -> None:
        if done is not None:
            self.done = done
        if not self.enabled:
            return
        now = time.perf_counter()
        if now - self._last_render < 0.08:
            return
        self._last_render = now
        text = f"{self.verb} {plural(self.total, 'file')}... {self.done}/{self.total}"
        if extra:
            text += f" \u00b7 {extra}"
        text += f"  {now - self._started:.1f}s"
        self._clear()
        self._last_width = len(text)
        self.console.print(Text(text, style="progress"), end="\r", soft_wrap=True)

    def _clear(self) -> None:
        self.console.print(" " * max(self._last_width, 1), end="\r", soft_wrap=True)


THEME = {
    "tree.line": "dim",
    "tree.dir": "bold magenta",
    "tree.file": "default",
    "tree.desc": "default",
    "footer": "dim",
    "progress": "cyan",
    "warn": "yellow",
    "error": "bold red",
}


def themed_console(
    width: int | None = None,
    no_color: bool = False,
    file=None,
    force_terminal: bool | None = None,
) -> Console:
    from rich.theme import Theme

    disabled = no_color or "NO_COLOR" in os.environ
    return Console(
        highlight=False,
        emoji=False,
        theme=Theme(THEME),
        width=width,
        file=file,
        force_terminal=force_terminal,
        no_color=disabled,
        color_system=None if disabled else "auto",
    )
