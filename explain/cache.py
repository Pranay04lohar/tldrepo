"""JSON cache under ``<repo>/.explain/cache.json``.

The cache stores descriptions and hashes, never source code. Writes are atomic
and a malformed cache is backed up rather than trusted.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import CACHE_VERSION, PROMPT_VERSION


class Cache:
    def __init__(self, root: Path, version: int = CACHE_VERSION):
        self.root = Path(root)
        self.dir = self.root / ".explain"
        self.path = self.dir / "cache.json"
        self.version = version
        self.data: dict = {"version": version, "files": {}, "dirs": {}}
        self.dirty = False
        self.recovered = False
        self.exists = False

    # -- lifecycle ---------------------------------------------------------

    def _ensure_dir(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        guard = self.dir / ".gitignore"
        if not guard.exists():
            try:
                guard.write_text("*\n", "utf-8")
            except OSError:
                pass

    def _backup(self, suffix: str = "cache.json.bak") -> None:
        if not self.path.exists():
            return
        try:
            os.replace(self.path, self.dir / suffix)
        except OSError:
            try:
                self.path.unlink()
            except OSError:
                pass

    def load(self) -> "Cache":
        self._ensure_dir()
        if not self.path.exists():
            return self
        self.exists = True
        try:
            raw = json.loads(self.path.read_text("utf-8"))
        except (OSError, ValueError):
            self._backup()
            self.recovered = True
            return self
        if not isinstance(raw, dict) or raw.get("version") != self.version:
            self._backup()
            self.recovered = True
            return self
        files = raw.get("files")
        dirs = raw.get("dirs")
        if not isinstance(files, dict) or not isinstance(dirs, dict):
            self._backup()
            self.recovered = True
            return self
        self.data = {
            "version": self.version,
            "files": {k: v for k, v in files.items() if isinstance(v, dict)},
            "dirs": {k: v for k, v in dirs.items() if isinstance(v, str)},
        }
        return self

    def save(self, force: bool = False) -> bool:
        if not self.dirty and not force:
            return False
        self._ensure_dir()
        payload = json.dumps(self.data, indent=2, sort_keys=True) + "\n"
        handle = None
        temp_path = None
        try:
            fd, temp_name = tempfile.mkstemp(
                prefix=".cache-", suffix=".tmp", dir=str(self.dir)
            )
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
            temp_path = None
            self.dirty = False
            self.exists = True
            return True
        finally:
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    # -- files -------------------------------------------------------------

    def get_file(
        self,
        path: str,
        digest: str,
        model: str,
        prompt_version: int = PROMPT_VERSION,
    ) -> str | None:
        entry = self.data["files"].get(path)
        if not isinstance(entry, dict):
            return None
        if entry.get("hash") != digest:
            return None
        description = entry.get("description")
        if not isinstance(description, str) or not description:
            return None
        if entry.get("tier") == 0:
            return description
        if entry.get("model") != model:
            return None
        if entry.get("prompt_version") != prompt_version:
            return None
        return description

    def put_file(
        self,
        path: str,
        digest: str,
        model: str,
        tier: int,
        description: str,
        prompt_version: int = PROMPT_VERSION,
    ) -> None:
        existing = self.data["files"].get(path)
        new_entry = {
            "hash": digest,
            "model": model,
            "prompt_version": prompt_version,
            "tier": tier,
            "description": description,
        }
        if existing != new_entry:
            self.data["files"][path] = new_entry
            self.dirty = True

    def prune(self, keep_paths: set[str]) -> int:
        stale = [path for path in self.data["files"] if path not in keep_paths]
        for path in stale:
            self.data["files"].pop(path, None)
        if stale:
            self.dirty = True
        return len(stale)

    def clear(self) -> None:
        if self.data["files"] or self.data["dirs"]:
            self.data["files"] = {}
            self.data["dirs"] = {}
            self.dirty = True

    # -- directories -------------------------------------------------------

    def get_dir(self, key: str) -> str | None:
        value = self.data["dirs"].get(key)
        return value if isinstance(value, str) and value else None

    def put_dir(self, key: str, description: str) -> None:
        if self.data["dirs"].get(key) != description:
            self.data["dirs"][key] = description
            self.dirty = True

    # -- introspection -----------------------------------------------------

    def counts(self) -> dict[str, int]:
        files = self.data["files"].values()
        return {
            "files": len(self.data["files"]),
            "tier0": sum(1 for entry in files if entry.get("tier") == 0),
            "tier1": sum(1 for entry in files if entry.get("tier") != 0),
            "dirs": len(self.data["dirs"]),
        }
