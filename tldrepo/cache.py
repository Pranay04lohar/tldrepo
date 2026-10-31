"""JSON cache under ``<repo>/.tldrepo/cache.json``.

The cache stores descriptions, source tags and hashes, never source code.
Writes are atomic and a malformed cache is backed up rather than trusted.
Version 2 caches are migrated in place: every old file becomes ``llm`` or
``rule``, every old directory becomes ``rule``.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .config import CACHE_VERSION, PROMPT_VERSION

SOURCES = {"llm", "docstring", "rule", "fallback"}


class Cache:
    def __init__(self, root: Path, version: int = CACHE_VERSION):
        self.root = Path(root)
        self.dir = self.root / ".tldrepo"
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
        if not isinstance(raw, dict):
            self._backup()
            self.recovered = True
            return self

        version = raw.get("version")
        files = raw.get("files")
        dirs = raw.get("dirs")
        if version == 2:
            migrated = self._migrate_v2(files, dirs)
            if migrated is None:
                self._backup()
                self.recovered = True
                return self
            self.data = migrated
            self.dirty = True
            return self
        if version != self.version:
            self._backup()
            self.recovered = True
            return self
        if not isinstance(files, dict) or not isinstance(dirs, dict):
            self._backup()
            self.recovered = True
            return self
        self.data = {
            "version": self.version,
            "files": {
                k: self._clean_file_entry(v) for k, v in files.items() if isinstance(v, dict)
            },
            "dirs": {
                k: self._clean_dir_entry(v) for k, v in dirs.items() if isinstance(v, dict)
            },
        }
        return self

    def _migrate_v2(self, files, dirs) -> dict | None:
        if not isinstance(files, dict) or not isinstance(dirs, dict):
            return None
        migrated_files = {}
        for path, entry in files.items():
            if not isinstance(entry, dict):
                continue
            source = "rule" if entry.get("tier") == 0 else "llm"
            migrated_files[path] = {
                "hash": entry.get("hash", ""),
                "model": entry.get("model", ""),
                "prompt_version": entry.get("prompt_version", PROMPT_VERSION),
                "tier": entry.get("tier", 1),
                "description": entry.get("description", ""),
                "source": source,
            }
        migrated_dirs = {}
        for key, value in dirs.items():
            if isinstance(value, str):
                migrated_dirs[key] = {
                    "description": value,
                    "source": "rule",
                    "model": "",
                    "prompt_version": 0,
                }
        return {"version": self.version, "files": migrated_files, "dirs": migrated_dirs}

    def _clean_file_entry(self, entry: dict) -> dict:
        source = entry.get("source")
        if source not in SOURCES:
            source = "rule" if entry.get("tier") == 0 else "llm"
        return {**entry, "source": source}

    def _clean_dir_entry(self, entry: dict) -> dict:
        source = entry.get("source")
        if source not in SOURCES:
            source = "llm"
        return {
            "description": str(entry.get("description", "")),
            "source": source,
            "model": str(entry.get("model", "")),
            "prompt_version": int(entry.get("prompt_version") or 0),
        }

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

    def get_file_source(
        self,
        path: str,
        digest: str,
        model: str,
        prompt_version: int = PROMPT_VERSION,
    ) -> str:
        entry = self.data["files"].get(path)
        if not isinstance(entry, dict):
            return "rule"
        source = entry.get("source")
        if source in SOURCES:
            return source
        return "rule" if entry.get("tier") == 0 else "llm"

    def put_file(
        self,
        path: str,
        digest: str,
        model: str,
        tier: int,
        description: str,
        prompt_version: int = PROMPT_VERSION,
        source: str = "rule",
    ) -> None:
        existing = self.data["files"].get(path)
        source = source if source in SOURCES else ("rule" if tier == 0 else "llm")
        new_entry = {
            "hash": digest,
            "model": model,
            "prompt_version": prompt_version,
            "tier": tier,
            "description": description,
            "source": source,
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

    def _dir_entry(self, key: str) -> dict | None:
        entry = self.data["dirs"].get(key)
        if isinstance(entry, str):
            return {"description": entry, "source": "rule", "model": "", "prompt_version": 0}
        return entry if isinstance(entry, dict) else None

    def get_dir(
        self,
        key: str,
        model: str | None = None,
        prompt_version: int | None = None,
    ) -> str | None:
        entry = self._dir_entry(key)
        if not entry:
            return None
        description = entry.get("description")
        if not isinstance(description, str) or not description:
            return None
        if model is not None and entry.get("model") != model:
            return None
        if prompt_version is not None and entry.get("prompt_version") != prompt_version:
            return None
        return description

    def get_dir_source(self, key: str) -> str:
        entry = self._dir_entry(key)
        source = entry.get("source") if entry else None
        return source if source in SOURCES else "rule"

    def put_dir(
        self,
        key: str,
        description: str,
        model: str = "",
        prompt_version: int = 0,
        source: str = "llm",
    ) -> None:
        source = source if source in SOURCES else "llm"
        new_entry = {
            "description": description,
            "source": source,
            "model": model,
            "prompt_version": prompt_version,
        }
        if self._dir_entry(key) != new_entry:
            self.data["dirs"][key] = new_entry
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
