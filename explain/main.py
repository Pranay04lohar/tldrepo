"""CLI entry point and orchestration (placeholder until step 8)."""

from __future__ import annotations

import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    from .config import Config
    from .scanner import find_root, scan

    cwd = Path.cwd()
    root = find_root(cwd)
    result = scan(root, cfg=Config())
    print(f"{root} ({len(result.files)} files)")
    for entry in result.files:
        print(entry.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
