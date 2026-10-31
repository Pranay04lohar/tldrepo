"""Model communication: batching, prompts, parsing, retries and fallbacks.

The analyzer never prints raw model output and never lets one malformed
response ruin a run. Every file ends up with either a model description, a
cached description, or a deterministic fallback.

Prompt and parsing follow the spec: numbered skeletons in, ``N|description``
lines out. A JSON answer is accepted as a tolerant fallback because small
models sometimes emit it anyway.
"""

from __future__ import annotations

import json
import math
import re
import threading
import time
from dataclasses import dataclass, field

from .config import Config
from .metadata import build_skeleton, estimate_tokens, neighbours_for
from .ollama_manager import (
    ModelNotFoundError,
    OllamaConnectionError,
    OllamaError,
    OllamaManager,
)
from .tiers import (
    clean_directory_description,
    directory_children,
    directory_description,
    directory_key,
    fallback_description,
)
from .tree_builder import directory_nodes

SYSTEM_PROMPT = """You describe source files for a codebase map.
For each numbered file below, write ONE description.

Rules:
- Output exactly one line per file in the form: <number>|<description>
- Example: 1|Database access layer for user records
- Maximum 10 words. State WHAT the file is responsible for.
- Never write the file name and never start with "This file".
- Use only the evidence given. Do not invent functionality.
- If the purpose is unclear, write: <number>|unclear
- No extra text, no markdown, no backticks.

Examples:
FILE 1: billing/invoice.py
Classes: Invoice
Functions: Invoice.total, Invoice.render
-> 1|Builds and totals customer invoices

FILE 2: cli/entry.py
Functions: main, build_parser
-> 2|Command-line entry point that parses arguments and runs the app"""

VAGUE_TERMS = (
    "various",
    "utility functions",
    "helper functions",
    "helper methods",
    "miscellaneous",
    "misc",
    "contains code",
    "handles things",
)

LINE = re.compile(r"^\s*(?:->\s*)?(?i:file\s+)?(\d+)\s*\|\s*(.+?)\s*$")
FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)

MAX_SOURCE_RETRIES = 6
RETRY_SOURCE_LINES = 80
RETRY_SOURCE_CHARS = 2000
GENERIC_STARTS = (
    "this file",
    "the file",
    "a file",
    "this module",
    "the module",
    "this code",
    "source file",
    "the code",
    "here",
)


class AIStopped(RuntimeError):
    """Raised when AI analysis cannot continue (connection, model, budget)."""

    def __init__(self, reason: str, message: str = ""):
        self.reason = reason
        super().__init__(message or reason)


@dataclass
class Batch:
    files: list
    user_prompt: str
    tokens: int = 0
    numbers: dict[str, int] = field(default_factory=dict)


@dataclass
class Usage:
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    prefill: float = 0.0
    decode: float = 0.0


@dataclass
class AnalysisSummary:
    described: int = 0
    failed: int = 0
    retried: int = 0
    requests: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    stopped: str = ""
    model: str = ""

    def merge(self, usage: Usage) -> None:
        self.requests += usage.requests
        self.tokens_in += usage.tokens_in
        self.tokens_out += usage.tokens_out


def analyse(ctx) -> AnalysisSummary:
    cfg: Config = ctx.cfg
    entries = [entry for entry in ctx.pending if entry.path not in ctx.descriptions]
    summary = AnalysisSummary(model=cfg.model)
    ctx._fallback_paths = set()
    ctx.description_sources = getattr(ctx, "description_sources", {})
    if not entries and not _directory_candidates(ctx):
        return summary

    ctx.stats.model = cfg.model
    manager = OllamaManager(cfg=cfg)
    try:
        manager.ensure_running()
    except OllamaError as exc:
        ctx.console.print(f"AI unavailable: {exc}", style="warn")
        _fill_fallbacks(ctx)
        return summary

    load_error: list[BaseException] = []

    def load() -> None:
        try:
            manager.load_model(cfg.model)
        except BaseException as exc:  # noqa: BLE001 - surfaced below
            load_error.append(exc)

    loader = threading.Thread(target=load, name="tldrepo-model-load", daemon=True)
    load_started = time.perf_counter()
    loader.start()

    batches = build_batches(ctx, entries) if entries else []
    if batches:
        noun = "request" if len(batches) == 1 else "requests"
        ctx.console.print(
            f"  preparing {len(batches)} {noun} for {len(entries)} files\u2026",
            style="footer",
        )

    loader.join()
    _phase(ctx, "load", load_started)
    if load_error:
        ctx.console.print(f"AI unavailable: {load_error[0]}", style="warn")
        _fill_fallbacks(ctx)
        return summary

    from .renderer import ProgressLine

    failed: list = []
    described_total = 0
    with ProgressLine(ctx.console, len(entries)) as progress:
        for position, batch in enumerate(batches):
            if _out_of_time(ctx):
                summary.stopped = "budget"
                ctx.console.print(
                    "AI analysis stopped: time budget reached; showing fallbacks",
                    style="warn",
                )
                break
            final = position == len(batches) - 1
            try:
                parsed, usage = _describe_with_retry(
                    manager, cfg, batch, ctx, keep_alive=0 if final else cfg.keep_alive
                )
            except AIStopped as stop:
                summary.stopped = stop.reason
                ctx.console.print(f"AI analysis stopped: {stop}", style="warn")
                break
            summary.merge(usage)
            _phase_add(ctx, "prefill", usage.prefill)
            _phase_add(ctx, "decode", usage.decode)
            ctx.stats.batches += 1
            added = _commit(ctx, batch, parsed, failed)
            described_total += added
            progress.update(described_total)

    if failed and not summary.stopped and not _out_of_time(ctx):
        summary.retried = _retry_with_more_source(ctx, manager, failed, summary)
        described_total += summary.retried

    missing = [entry for entry in entries if entry.path not in ctx.descriptions]
    rejected = {entry.path for entry in failed}
    pending_stop = summary.stopped in {"budget", "connection", "model"}
    if missing:
        _fill_fallbacks(
            ctx,
            cache_paths=rejected if summary.stopped in {"", "incomplete"} else None,
            source="pending" if pending_stop else "fallback",
        )
    if missing and not summary.stopped:
        summary.stopped = "incomplete"
    summary.described = described_total
    summary.failed = len(missing)
    ctx.stats.analysed_by_ai = described_total
    ctx.stats.pending = len(missing) if pending_stop else 0

    if summary.stopped not in {"budget", "connection", "model"} and not _out_of_time(ctx):
        _describe_unknown_directories(ctx, manager, cfg, summary)

    cleanup_started = time.perf_counter()
    try:
        manager.unload_model()
        manager.wait_until_unloaded()
    except Exception:
        pass
    _phase(ctx, "cleanup", cleanup_started)
    return summary


DIRECTORY_PROMPT = """You name directories in a codebase map.
For each numbered directory, write ONE purpose using the children descriptions.

Rules:
- Output exactly one line per directory: <number>|<purpose>
- Maximum 8 words. State WHAT the directory is for as a group.
- Summarise the children's shared role; do not copy one child description.
- Use only the evidence given. Do not invent functionality.
- Never repeat the directory name and do not start with "This directory".
- If the purpose is unclear, write: <number>|unclear
- No extra text, no markdown, no backticks.

Example:
DIR 1: billing
Children: Builds invoices; Totals line items
-> 1|Invoice construction and total calculation"""


def _directory_candidates(ctx) -> list[dict]:
    """Unknown directories, deepest first, after built-ins and cached results."""
    cfg = ctx.cfg
    descriptions = ctx.descriptions
    sources = getattr(ctx, "description_sources", {})
    candidates: list[dict] = []
    for node in reversed(directory_nodes(ctx.tree)):
        name = node.name
        mapped = directory_description(name)
        if mapped:
            if node.path not in descriptions:
                descriptions[node.path] = mapped
                sources[node.path] = "rule"
            continue
        children = directory_children(node, descriptions)
        key = directory_key(node.path, children)
        cached = ctx.cache.get_dir(key, cfg.model, cfg.prompt_version)
        if cached:
            if node.path not in descriptions:
                descriptions[node.path] = cached
                sources[node.path] = ctx.cache.get_dir_source(key)
            continue
        candidates.append(
            {"node": node, "path": node.path, "name": name, "children": children, "key": key}
        )
    return candidates


def _describe_unknown_directories(ctx, manager, cfg: Config, summary: AnalysisSummary) -> None:
    candidates = _directory_candidates(ctx)
    if not candidates:
        return
    lines = []
    numbers: dict[str, dict] = {}
    for index, candidate in enumerate(candidates, start=1):
        numbers[str(index)] = candidate
        child_text = "; ".join(candidate["children"][:8]) or "(no known children)"
        lines.append(f"DIR {index}: {candidate['name']}\nChildren: {child_text}")
    body = "\n\n".join(lines)
    batch = Batch(files=[], user_prompt=body + f"\n\nDescribe these {len(candidates)} directories.")
    try:
        payload = manager.chat(
            cfg.model,
            [
                {"role": "system", "content": DIRECTORY_PROMPT},
                {"role": "user", "content": batch.user_prompt},
            ],
            options={
                "temperature": 0,
                "num_ctx": min(cfg.max_num_ctx, 2048),
                "num_predict": max(80, 24 * len(candidates)),
            },
            keep_alive=0,
            timeout=_request_timeout(ctx),
        )
    except (OllamaError, OSError):
        return
    summary.requests += 1
    summary.tokens_in += int(payload.get("prompt_eval_count") or 0)
    summary.tokens_out += int(payload.get("eval_count") or 0)
    summary.merge(
        Usage(
            requests=0,
            tokens_in=0,
            tokens_out=0,
            prefill=int(payload.get("prompt_eval_duration") or 0) / 1e9,
            decode=int(payload.get("eval_duration") or 0) / 1e9,
        )
    )
    _phase_add(ctx, "prefill", int(payload.get("prompt_eval_duration") or 0) / 1e9)
    _phase_add(ctx, "decode", int(payload.get("eval_duration") or 0) / 1e9)
    parsed = _parse_directory_lines(_content(payload), numbers, cfg)
    for number, candidate in numbers.items():
        description = parsed.get(number)
        if not description:
            continue
        ctx.descriptions[candidate["path"]] = description
        ctx.description_sources[candidate["path"]] = "llm"
    for candidate in candidates:
        node = candidate["node"]
        if node.path not in ctx.descriptions:
            continue
        children = directory_children(node, ctx.descriptions)
        key = directory_key(node.path, children)
        ctx.cache.put_dir(
            key,
            ctx.descriptions[node.path],
            cfg.model,
            cfg.prompt_version,
            source="llm",
        )


def _parse_directory_lines(text: str, numbers: dict[str, dict], cfg: Config) -> dict[str, str]:
    body = FENCE.sub("", text or "").strip()
    result: dict[str, str] = {}
    for line in body.splitlines():
        match = LINE.match(line)
        if not match:
            continue
        number, raw = match.group(1), match.group(2)
        if number not in numbers or number in result:
            continue
        candidate = numbers[number]
        children = candidate.get("children", []) if isinstance(candidate, dict) else []
        description = clean_directory_description(
            raw, children, max_words=cfg.directory_max_words
        )
        if description:
            result[number] = description
    return result


def _phase(ctx, name: str, started: float) -> None:
    ctx.stats.phases[name] = ctx.stats.phases.get(name, 0.0) + (
        time.perf_counter() - started
    )


def _phase_add(ctx, name: str, seconds: float) -> None:
    if seconds:
        ctx.stats.phases[name] = ctx.stats.phases.get(name, 0.0) + seconds


def _out_of_time(ctx) -> bool:
    return time.monotonic() >= ctx.deadline - 0.25


def build_batches(
    ctx,
    entries,
    skeleton_chars: int | None = None,
    extra_source_lines: int = 0,
) -> list[Batch]:
    cfg: Config = ctx.cfg
    skeleton_chars = cfg.skeleton_max_chars if skeleton_chars is None else skeleton_chars
    groups: dict[str, list] = {}
    for entry in entries:
        groups.setdefault(entry.path.rpartition("/")[0], []).append(entry)
    ordered = []
    for directory in sorted(
        groups,
        key=lambda d: (min(ctx.decisions[e.path].priority for e in groups[d]), d),
    ):
        ordered.extend(
            sorted(
                groups[directory],
                key=lambda e: (ctx.decisions[e.path].priority, e.path),
            )
        )
    batches: list[Batch] = []
    current: list = []
    blocks: list[str] = []
    tokens = estimate_tokens(SYSTEM_PROMPT) + 40

    for entry in ordered:
        meta = ctx.metas[entry.path]
        neighbours = neighbours_for(entry.path, ctx.result.files)
        number = len(current) + 1
        skeleton = _skeleton_for(
            entry, meta, neighbours, number, skeleton_chars, extra_source_lines
        )
        block_tokens = estimate_tokens(skeleton) + 8
        if current and (
            tokens + block_tokens > cfg.batch_input_tokens
            or len(current) >= cfg.batch_max_files
        ):
            batches.append(_make_batch(current, blocks))
            current, blocks = [], []
            number = 1
            skeleton = _skeleton_for(
                entry, meta, neighbours, number, skeleton_chars, extra_source_lines
            )
            block_tokens = estimate_tokens(skeleton) + 8
            tokens = estimate_tokens(SYSTEM_PROMPT) + 40
        current.append(entry)
        blocks.append(skeleton)
        tokens += block_tokens

    if current:
        batches.append(_make_batch(current, blocks))
    return batches


def _skeleton_for(
    entry,
    meta,
    neighbours,
    number: int,
    skeleton_chars: int,
    extra_source_lines: int,
) -> str:
    skeleton = build_skeleton(number, meta, neighbours, skeleton_chars)
    if extra_source_lines <= 0 or "Source:" in skeleton:
        return skeleton
    try:
        text = entry.abspath.read_text("utf-8", errors="replace")
    except OSError:
        return skeleton
    lines = text.splitlines()[:extra_source_lines]
    source = "\n".join(lines)[:RETRY_SOURCE_CHARS].rstrip()
    if not source:
        return skeleton
    return skeleton + "\nMore source:\n" + source


def _make_batch(files, blocks) -> Batch:
    body = "\n\n".join(blocks)
    numbers = {str(index + 1): entry.path for index, entry in enumerate(files)}
    return Batch(
        files=list(files),
        user_prompt=body + "\n\n" + f"Describe these {len(files)} files.",
        tokens=estimate_tokens(SYSTEM_PROMPT + "\n" + body),
        numbers=numbers,
    )


def _messages(batch: Batch) -> list[dict]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": batch.user_prompt},
    ]


def _request_options(cfg: Config, batch: Batch) -> dict:
    expected_out = 20 * len(batch.files) + 20
    want_ctx = math.ceil((batch.tokens + expected_out) * 1.25)
    want_ctx = max(1024, math.ceil(want_ctx / 256) * 256)
    return {
        "temperature": 0,
        "num_ctx": min(cfg.max_num_ctx, want_ctx),
        "num_predict": expected_out,
    }


def _describe_with_retry(manager, cfg: Config, batch: Batch, ctx, keep_alive=None):
    usage = Usage()
    parsed: dict[str, str] = {}
    keep_alive = cfg.keep_alive if keep_alive is None else keep_alive

    for attempt in range(cfg.retries + 1):
        if attempt:
            if _out_of_time(ctx):
                raise AIStopped("budget", "time budget exhausted")
            time.sleep(0.2)
        timeout = _request_timeout(ctx)
        try:
            payload = manager.chat(
                cfg.model,
                _messages(batch),
                options=_request_options(cfg, batch),
                keep_alive=keep_alive,
                timeout=timeout,
            )
        except ModelNotFoundError as exc:
            raise AIStopped("model", str(exc)) from exc
        except OllamaConnectionError as exc:
            if attempt < cfg.retries:
                time.sleep(1.0)
                continue
            raise AIStopped("connection", f"Ollama stopped responding ({exc})") from exc
        except OllamaError:
            continue

        usage.requests += 1
        usage.tokens_in += int(payload.get("prompt_eval_count") or 0)
        usage.tokens_out += int(payload.get("eval_count") or 0)
        usage.prefill += int(payload.get("prompt_eval_duration") or 0) / 1e9
        usage.decode += int(payload.get("eval_duration") or 0) / 1e9
        parsed = parse_descriptions(_content(payload), batch, cfg)
        if parsed:
            return parsed, usage

    ctx.stats.batch_failures += 1
    return parsed, usage


def _content(payload: dict) -> str:
    message = payload.get("message")
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(payload.get("response") or "")


def _request_timeout(ctx) -> float:
    remaining = max(1.0, ctx.deadline - time.monotonic())
    return max(5.0, min(ctx.cfg.request_timeout, remaining + 5.0))


def _commit(ctx, batch: Batch, parsed: dict[str, str], failed: list) -> int:
    added = 0
    for entry in batch.files:
        description = parsed.get(entry.path)
        if not description:
            failed.append(entry)
            continue
        ctx.descriptions[entry.path] = description
        ctx.description_sources = getattr(ctx, "description_sources", {})
        ctx.description_sources[entry.path] = "llm"
        ctx.cache.put_file(
            entry.path,
            entry.digest,
            ctx.cfg.model,
            0,
            description,
            ctx.cfg.prompt_version,
            source="llm",
        )
        added += 1
    return added


def _retry_with_more_source(
    ctx, manager, failed: list, summary: AnalysisSummary
) -> int:
    """One retry on the same model with a larger skeleton and real source lines.

    If the retry also fails, the caller fills deterministic fallbacks. The model
    never changes mid-run.
    """
    cfg: Config = ctx.cfg
    candidates = [entry for entry in failed if entry.path not in ctx.descriptions][
        :MAX_SOURCE_RETRIES
    ]
    if not candidates or _out_of_time(ctx):
        return 0
    batches = build_batches(
        ctx,
        candidates,
        skeleton_chars=max(2000, cfg.skeleton_max_chars * 2),
        extra_source_lines=RETRY_SOURCE_LINES,
    )
    added = 0
    for position, batch in enumerate(batches):
        try:
            parsed, usage = _describe_with_retry(
                manager,
                cfg,
                batch,
                ctx,
                keep_alive=0 if position == len(batches) - 1 else cfg.keep_alive,
            )
        except AIStopped:
            break
        summary.merge(usage)
        _phase_add(ctx, "prefill", usage.prefill)
        _phase_add(ctx, "decode", usage.decode)
        ctx.stats.batches += 1
        added += _commit(ctx, batch, parsed, [])
    return added


def _fill_fallbacks(
    ctx, cache_paths: set[str] | None = None, source: str = "fallback"
) -> None:
    for entry in ctx.pending:
        if entry.path in ctx.descriptions:
            continue
        description = fallback_description(ctx.metas[entry.path])
        ctx.descriptions[entry.path] = description
        ctx.description_sources = getattr(ctx, "description_sources", {})
        ctx.description_sources[entry.path] = source
        ctx._fallback_paths.add(entry.path)
        ctx.stats.fallbacks += 1
        if cache_paths and entry.path in cache_paths:
            ctx.cache.put_file(
                entry.path,
                entry.digest,
                ctx.cfg.model,
                0,
                description,
                ctx.cfg.prompt_version,
                source="fallback",
            )


def parse_descriptions(text: str, batch: Batch, cfg: Config) -> dict[str, str]:
    """Accept the spec's ``N|description`` lines, else a JSON object."""
    body = FENCE.sub("", text or "").strip()
    if not body:
        return {}

    result: dict[str, str] = {}
    numbered = 0
    for line in body.splitlines():
        match = LINE.match(line)
        if not match:
            continue
        number, raw = match.group(1), match.group(2)
        numbered += 1
        path = batch.numbers.get(number)
        if path is None or path in result:
            continue
        description = clean_description(raw, cfg, path)
        if description:
            result[path] = description

    if numbered:
        return result

    for path, raw in _json_rows(body).items():
        if path not in batch.numbers.values() or path in result:
            continue
        description = clean_description(raw, cfg, path)
        if description:
            result[path] = description
    return result


def _json_rows(body: str) -> dict[str, str]:
    data = None
    try:
        data = json.loads(body)
    except ValueError:
        start, end = body.find("{"), body.rfind("}")
        if start != -1 and end > start:
            try:
                data = json.loads(body[start : end + 1])
            except ValueError:
                data = None
    if data is None:
        return {}

    rows: dict[str, str] = {}
    items: list = []
    if isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        if isinstance(data.get("descriptions"), list):
            items = data["descriptions"]
        elif isinstance(data.get("files"), list):
            items = data["files"]
        else:
            return {
                clean_path(str(key)): str(value)
                for key, value in data.items()
                if isinstance(value, str)
            }
    for item in items:
        if not isinstance(item, dict):
            continue
        path = item.get("path") or item.get("file") or item.get("name")
        description = (
            item.get("description") or item.get("summary") or item.get("purpose")
        )
        if path and description:
            rows[clean_path(str(path))] = str(description)
    return rows


def clean_path(path: str) -> str:
    value = path.strip().strip("\"'`")
    value = value.replace("\\", "/")
    while value.startswith("./"):
        value = value[2:]
    return value


def clean_description(
    text: str, cfg: Config, path: str = "", max_words: int | None = None
) -> str | None:
    value = text.strip().strip("\"'`").replace("`", "")
    value = re.sub(r"^[\s>*\-•]+", "", value)
    value = re.sub(r"\s+", " ", value)
    value = value.rstrip(".!,;:")
    if not value:
        return None
    lowered = value.lower()
    if path:
        name = path.rpartition("/")[2].lower()
        for prefix in (path.lower(), name):
            if prefix and lowered.startswith(prefix):
                rest = value[len(prefix) :].lstrip(" -:\u2013\u2014.\t")
                if rest:
                    value = rest
                    lowered = value.lower()
                break
    if "unclear" in lowered:
        return None

    if any(term in lowered for term in VAGUE_TERMS):
        return None
    name = path.rpartition("/")[2].lower()
    if name and name in lowered:
        return None
    if lowered.startswith(GENERIC_STARTS) or lowered.startswith("contains "):
        return None

    words = value.split()
    limit = max_words or cfg.max_accepted_words
    trimmed = max_words or cfg.docstring_max_words
    if len(words) > limit:
        value = " ".join(words[:trimmed]).rstrip(",;:")
    if len(value) > 120:
        value = value[:120].rsplit(" ", 1)[0]
    if len(value.split()) < 2:
        return None
    return value[:1].upper() + value[1:]
