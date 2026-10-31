"""CLI entry point and orchestration.

Only this module wires the deterministic pipeline together. Everything else is
independent and testable on its own.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .cache import Cache
from .config import (
    FAST_MODEL,
    Config,
    apply_project_config,
    load_project_config,
)
from .metadata import analyze, build_skeleton, neighbours_for, skeleton_summary
from .renderer import (
    ProgressLine,
    RunStats,
    render_file_detail,
    render_footer,
    render_legend,
    render_stats,
    render_timing,
    render_tree,
    themed_console,
)
from .scanner import find_root, scan
from .tiers import (
    TIER_DETERMINISTIC,
    assign,
    directory_children,
    directory_description,
    directory_key,
    fallback_description,
    plural,
    source_for_reason,
)
from .tree_builder import build_tree, directory_nodes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tldrepo",
        description="A fast, local-AI codebase map for the terminal.",
    )
    parser.add_argument("path", nargs="?", default=None, help="file or directory to describe")
    parser.add_argument("--no-ai", action="store_true", help="never start or contact Ollama")
    parser.add_argument(
        "--all", action="store_true", help="show dot-directories too (except .git and .tldrepo)"
    )
    parser.add_argument("--refresh", action="store_true", help="regenerate all descriptions")
    parser.add_argument("--depth", type=int, default=None, help="limit the displayed tree depth")
    parser.add_argument("--stats", action="store_true", help="show language statistics")
    parser.add_argument("--model", default=None, help="override the model name")
    parser.add_argument(
        "--fast", action="store_true", help=f"use the fast model ({FAST_MODEL})"
    )
    parser.add_argument(
        "--budget", type=float, default=25.0, help="time budget in seconds (default 25)"
    )
    parser.add_argument("--timing", action="store_true", help="show per-phase timings")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colour")
    parser.add_argument("--legend", action="store_true", help="show a colour legend below the footer")
    return parser


@dataclass
class RunContext:
    cfg: Config
    root: Path
    target: Path
    console: object
    cache: Cache
    result: object
    tree: object
    metas: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)
    descriptions: dict = field(default_factory=dict)
    description_sources: dict = field(default_factory=dict)
    stats: RunStats = field(default_factory=RunStats)
    pending: list = field(default_factory=list)
    started: float = 0.0

    @property
    def deadline(self) -> float:
        return self.started + self.cfg.budget


def _resolve_target(cwd: Path, raw: str | None) -> Path:
    if not raw:
        return cwd
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = (cwd / candidate).resolve()
    return candidate


def _root_for(cwd: Path, target: Path) -> Path:
    try:
        target.relative_to(cwd)
        return find_root(cwd)
    except ValueError:
        return find_root(target)


def _phase(stats: RunStats, name: str, started: float) -> float:
    now = time.perf_counter()
    stats.phases[name] = stats.phases.get(name, 0.0) + (now - started)
    return now


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    cwd = Path.cwd()
    target = _resolve_target(cwd, args.path)
    if not target.exists():
        print(f"tldrepo: no such file or directory: {args.path}", file=sys.stderr)
        return 2

    root = _root_for(cwd, target)
    cfg = Config()
    apply_project_config(cfg, load_project_config(root))
    if args.model:
        cfg.model = args.model
    elif args.fast:
        cfg.model = FAST_MODEL
    cfg.no_ai = args.no_ai
    cfg.show_all = args.all
    cfg.no_color = args.no_color
    cfg.legend = args.legend
    cfg.refresh = args.refresh
    cfg.depth = args.depth
    cfg.stats = args.stats
    cfg.show_timing = args.timing
    cfg.budget = max(0.0, float(args.budget))
    if cfg.budget == 0:
        cfg.no_ai = True

    console = themed_console(no_color=cfg.no_color)
    stats = RunStats()
    started = time.perf_counter()

    phase = time.perf_counter()
    result = scan(root, target, cfg)
    scan_done = _phase(stats, "scan", phase)
    stats.files_scanned = len(result.files)

    if not result.files:
        if cfg.stats:
            render_stats(console, result, time.perf_counter() - started)
        console.print(
            f"No describable files in {target}"
            + (f" (skipped {result.skipped_total()})" if result.skipped else ""),
            style="warn",
        )
        return 0

    phase = scan_done
    metas = {entry.path: analyze(entry, root, cfg) for entry in result.files}
    _phase(stats, "metadata", phase)

    display_depth = cfg.depth
    tree = build_tree(result, display_depth)
    decisions = assign(result.files, metas, cfg)

    cache = Cache(root).load()
    if cfg.refresh:
        cache.clear()
    if root == target.resolve():
        cache.prune({entry.path for entry in result.files})

    ctx = RunContext(
        cfg=cfg,
        root=root,
        target=target,
        console=console,
        cache=cache,
        result=result,
        tree=tree,
        metas=metas,
        decisions=decisions,
        stats=stats,
        started=started,
    )

    _resolve_known(ctx)

    if not cfg.no_ai:
        _analyse(ctx)
    else:
        _fill_with_fallbacks(ctx)
    _resolve_directories(ctx)
    stats.dirs_by_ai = sum(
        1
        for node in directory_nodes(tree)
        if ctx.description_sources.get(node.path) == "llm"
    )

    render_started = time.perf_counter()
    if cfg.stats:
        render_stats(console, result, time.perf_counter() - started)
    if target.is_file():
        entry = result.files[0]
        meta = metas[entry.path]
        skeleton = build_skeleton(1, meta, [], cfg.skeleton_max_chars)
        render_file_detail(
            console,
            entry,
            ctx.descriptions.get(entry.path, ""),
            skeleton_summary(meta),
            ctx.description_sources.get(entry.path),
        )
        console.print(
            f"  skeleton: {len(skeleton)} chars, ~{len(skeleton) // 4} tokens",
            style="footer",
        )
    else:
        render_tree(
            console, tree, ctx.descriptions, cfg.depth, sources=ctx.description_sources
        )

    stats.duration = time.perf_counter() - started
    _phase(stats, "render", render_started)
    render_footer(console, stats)
    if cfg.legend:
        render_legend(console)
    if cfg.show_timing:
        render_timing(console, stats)
    cache.save()
    return 0


def _resolve_known(ctx: RunContext) -> None:
    cfg = ctx.cfg
    pending: list = []
    for entry in ctx.result.files:
        decision = ctx.decisions[entry.path]
        if decision.tier == TIER_DETERMINISTIC and decision.description:
            source = source_for_reason(decision.reason)
            ctx.descriptions[entry.path] = decision.description
            ctx.description_sources[entry.path] = source
            ctx.stats.deterministic += 1
            ctx.cache.put_file(
                entry.path,
                entry.digest,
                cfg.model,
                0,
                decision.description,
                cfg.prompt_version,
                source=source,
            )
            continue
        cached = ctx.cache.get_file(
            entry.path, entry.digest, cfg.model, cfg.prompt_version
        )
        if cached:
            ctx.descriptions[entry.path] = cached
            ctx.description_sources[entry.path] = ctx.cache.get_file_source(
                entry.path, entry.digest, cfg.model, cfg.prompt_version
            )
            ctx.stats.from_cache += 1
            continue
        pending.append(entry)

    for entry in list(pending):
        decision = ctx.decisions[entry.path]
        if not decision.duplicate_of:
            continue
        original = ctx.descriptions.get(decision.duplicate_of)
        if original and entry.path not in ctx.descriptions:
            source = ctx.description_sources.get(decision.duplicate_of, "rule")
            ctx.descriptions[entry.path] = original
            ctx.description_sources[entry.path] = source
            ctx.stats.duplicate_reuse += 1
            ctx.cache.put_file(
                entry.path,
                entry.digest,
                cfg.model,
                0,
                original,
                cfg.prompt_version,
                source=source,
            )
            pending.remove(entry)

    ctx.pending = pending


def _fill_with_fallbacks(ctx: RunContext) -> None:
    for entry in ctx.pending:
        meta = ctx.metas[entry.path]
        description = fallback_description(meta)
        ctx.descriptions[entry.path] = description
        ctx.description_sources[entry.path] = "fallback"
        ctx.stats.deterministic += 1


def _resolve_directories(ctx: RunContext) -> None:
    """Apply built-in names, cached directory entries, then plural fallbacks."""
    known = ctx.descriptions
    for node in directory_nodes(ctx.tree):
        name = node.path.rpartition("/")[2]
        mapped = directory_description(name)
        if mapped:
            known[node.path] = mapped
            ctx.description_sources[node.path] = "rule"
            continue
        if node.path in known:
            continue
        children = directory_children(node, known)
        key = directory_key(node.path, children)
        cached = ctx.cache.get_dir(key, ctx.cfg.model, ctx.cfg.prompt_version)
        if cached:
            known[node.path] = cached
            ctx.description_sources[node.path] = ctx.cache.get_dir_source(key)
            continue
        files = sum(1 for child in node.walk() if not child.is_dir)
        subdirs = sum(1 for child in node.walk() if child.is_dir and child is not node)
        if files == 0 and subdirs == 0:
            description = "Empty directory"
        elif subdirs:
            description = (
                f"Contains {plural(files, 'file')} and "
                f"{plural(subdirs, 'subdirectory', 'subdirectories')}"
            )
        else:
            description = f"Contains {plural(files, 'file')}"
        known[node.path] = description
        ctx.description_sources[node.path] = "fallback"


def _analyse(ctx: RunContext) -> None:
    from .analyzer import analyse

    analyse(ctx)


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
    finally:
        try:
            from .ollama_manager import cleanup_registered
        except ImportError:
            pass
        else:
            cleanup_registered()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
