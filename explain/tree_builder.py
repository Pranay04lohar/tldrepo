"""Deterministic tree construction from a scan result."""

from __future__ import annotations

from dataclasses import dataclass, field

from .scanner import ScanResult, ScannedFile


@dataclass
class Node:
    name: str
    path: str  # posix path relative to the scan root; "" for the displayed root
    is_dir: bool
    children: list["Node"] = field(default_factory=list)
    file: ScannedFile | None = None

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def files(self) -> list[ScannedFile]:
        return [node.file for node in self.walk() if node.file is not None]


def build_tree(result: ScanResult, display_depth: int | None = None) -> Node:
    """Build a sorted, directory-first tree rooted at the scan target."""
    target_rel = result.target.relative_to(result.root).as_posix()
    if target_rel == ".":
        target_rel = ""
    root_name = result.target.name or str(result.target)

    root = Node(name=root_name, path="", is_dir=True)

    def ensure(rel_path: str) -> Node:
        node = root
        parts = rel_path.split("/") if rel_path else []
        for index, part in enumerate(parts):
            prefix = "/".join(parts[: index + 1])
            child = next((c for c in node.children if c.name == part and c.is_dir), None)
            if child is None:
                child = Node(name=part, path=prefix, is_dir=True)
                node.children.append(child)
            node = child
        return node

    for directory in result.dirs:
        rel = directory
        if target_rel and not (rel == target_rel or rel.startswith(target_rel + "/")):
            continue
        inner = rel[len(target_rel) + 1 :] if target_rel and rel != target_rel else rel
        if target_rel and rel == target_rel:
            continue
        if inner:
            ensure(inner)

    for entry in result.files:
        rel = entry.path
        if target_rel:
            if not rel.startswith(target_rel + "/"):
                continue
            rel = rel[len(target_rel) + 1 :]
        parent_path, _, name = rel.rpartition("/")
        parent = ensure(parent_path) if parent_path else root
        parent.children.append(
            Node(name=name, path=entry.path, is_dir=False, file=entry)
        )

    def sort(node: Node) -> None:
        node.children.sort(key=lambda c: (not c.is_dir, c.name.lower()))
        for child in node.children:
            if child.is_dir:
                sort(child)

    sort(root)

    if display_depth is not None:
        _prune(root, display_depth, 0)

    return root


def _prune(node: Node, max_depth: int, depth: int) -> None:
    if depth >= max_depth:
        node.children = []
        return
    for child in node.children:
        if child.is_dir:
            _prune(child, max_depth, depth + 1)


def iter_with_depth(node: Node, depth: int = 0):
    yield depth, node
    for child in node.children:
        yield from iter_with_depth(child, depth + 1)


def directory_nodes(root: Node) -> list[Node]:
    return [n for n in root.walk() if n.is_dir and n.path]


def file_nodes(root: Node) -> list[Node]:
    return [n for n in root.walk() if not n.is_dir and n.file is not None]
