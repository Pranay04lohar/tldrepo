"""File tiers, deterministic descriptions and directory labels.

Tier 0 answers without a model. Tier 1 is the only normal model path. Tier 2 is
a rare escalation when a Tier 1 answer fails a deterministic quality check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .metadata import FileMetadata
from .scanner import ScannedFile

TIER_DETERMINISTIC = 0
TIER_LLM = 1
TIER_ESCALATION = 2

TEST_DIR_SEGMENTS = {"tests", "test", "__tests__", "testing", "spec", "specs", "e2e"}
TEST_FILE_RE = re.compile(
    r"^(?:test_.*\.py|.*_test\.(?:py|go|rb|exs|dart|cpp|cc|rs)|.*\.(?:test|spec)\.(?:js|jsx|ts|tsx|vue|svelte)|"
    r"Test[A-Z]\w*\.(?:java|kt|cs)|[A-Z]\w*Test\.(?:java|kt|cs))$"
)
DOC_NAMES = {
    "readme": "Project overview, setup and usage",
    "readme.md": "Project overview, setup and usage",
    "readme.rst": "Project overview, setup and usage",
    "contributing.md": "Contribution guidelines",
    "changelog.md": "Release history and change log",
    "changes.md": "Release history and change log",
    "history.md": "Release history and change log",
    "license": "License terms",
    "license.md": "License terms",
    "license.txt": "License terms",
    "code_of_conduct.md": "Community code of conduct",
    "security.md": "Security policy and reporting",
}

CONFIG_DESCRIPTIONS = {
    "pyproject.toml": "Python project metadata and dependencies",
    "setup.py": "Python package build script",
    "setup.cfg": "Python packaging configuration",
    "requirements.txt": "Python dependency list",
    "requirements-dev.txt": "Development dependency list",
    "pipfile": "Python dependency and environment definition",
    "poetry.lock": "Locked Python dependency versions",
    "uv.lock": "Locked Python dependency versions",
    "package.json": "Node package manifest and scripts",
    "package-lock.json": "Locked Node dependency versions",
    "tsconfig.json": "TypeScript compiler configuration",
    "jsconfig.json": "JavaScript project configuration",
    "vite.config.ts": "Vite build and dev-server configuration",
    "vite.config.js": "Vite build and dev-server configuration",
    "webpack.config.js": "Webpack bundling configuration",
    "next.config.js": "Next.js framework configuration",
    "next.config.mjs": "Next.js framework configuration",
    "tailwind.config.js": "Tailwind CSS configuration",
    "postcss.config.js": "PostCSS plugin configuration",
    ".eslintrc": "ESLint linting rules",
    ".eslintrc.json": "ESLint linting rules",
    ".eslintrc.js": "ESLint linting rules",
    "eslint.config.js": "ESLint linting rules",
    ".prettierrc": "Prettier formatting rules",
    "jest.config.js": "Jest test-runner configuration",
    "vitest.config.ts": "Vitest test-runner configuration",
    "dockerfile": "Container image build definition",
    "docker-compose.yml": "Multi-container service definition",
    "docker-compose.yaml": "Multi-container service definition",
    "compose.yml": "Multi-container service definition",
    "makefile": "Build and task automation targets",
    ".gitignore": "Git ignore rules",
    ".dockerignore": "Docker build-context exclusions",
    ".editorconfig": "Editor formatting conventions",
    ".env.example": "Example environment variables",
    "cargo.toml": "Rust crate manifest and dependencies",
    "go.mod": "Go module definition and dependencies",
    "go.sum": "Locked Go dependency checksums",
    "gemfile": "Ruby dependency definition",
    "composer.json": "PHP package manifest and dependencies",
    "build.gradle": "Gradle build configuration",
    "pom.xml": "Maven project and dependency configuration",
    "cmakelists.txt": "CMake build configuration",
    "tox.ini": "Tox test-environment configuration",
    "pytest.ini": "Pytest configuration",
    "ruff.toml": "Ruff linting and formatting configuration",
    "mypy.ini": "Mypy type-checking configuration",
    ".python-version": "Pinned Python version",
    ".nvmrc": "Pinned Node version",
    ".tool-versions": "Pinned toolchain versions",
    "alembic.ini": "Alembic migration configuration",
}

CONFIG_SUFFIXES = {
    ".toml", ".ini", ".cfg", ".yaml", ".yml", ".json", ".conf", ".properties", ".env",
}

ENTRY_POINT_NAMES = {
    "main.py", "__main__.py", "cli.py", "app.py", "server.py", "manage.py", "run.py",
    "wsgi.py", "asgi.py", "index.js", "index.ts", "main.js", "main.ts", "main.go",
    "main.rs", "lib.rs", "main.c", "main.cpp", "main.java", "program.cs", "index.php",
    "application.rb", "config.ru",
}

PRIORITY_FOLDERS = [
    (("services", "service", "core", "domain", "engine", "pipeline", "workflows"), 10),
    (("api", "routes", "routers", "controllers", "handlers", "endpoints", "views"), 20),
    (("repositories", "repository", "repo", "db", "dao", "storage", "persistence"), 30),
    (("integrations", "integration", "adapters", "clients", "external", "providers"), 40),
    (("config", "settings", "conf"), 50),
]

GENERIC_DOC_PHRASES = {
    "module",
    "package",
    "python module",
    "python package",
    "init file",
    "initialization file",
    "utilities",
    "utils",
    "helpers",
    "misc",
    "miscellaneous",
    "main module",
    "this module",
}


@dataclass
class TierDecision:
    path: str
    tier: int
    description: str | None
    reason: str
    priority: int = 60
    duplicate_of: str | None = None

    @property
    def deterministic(self) -> bool:
        return self.tier == TIER_DETERMINISTIC


def is_test_path(path: str) -> bool:
    parts = path.split("/")
    if any(part.lower() in TEST_DIR_SEGMENTS for part in parts[:-1]):
        return True
    return bool(TEST_FILE_RE.match(parts[-1]))


def is_doc_path(path: str) -> bool:
    parts = path.split("/")
    name = parts[-1].lower()
    if name in DOC_NAMES:
        return True
    if name.endswith((".md", ".rst", ".adoc")):
        return True
    if parts[0].lower() in {"docs", "doc", "documentation"} and name.endswith(".txt"):
        return True
    return False


def is_config_path(path: str) -> bool:
    name = path.split("/")[-1].lower()
    if name in CONFIG_DESCRIPTIONS:
        return True
    if name.startswith(".") and Path(name).suffix in CONFIG_SUFFIXES:
        return True
    if path.split("/")[0].lower() == ".github" and Path(name).suffix in {".yml", ".yaml"}:
        return True
    if name.startswith(("tsconfig.", "eslint", "prettier", "vite.config", "webpack.config")):
        return True
    if any(part.lower() in {"config", "configs", "conf", "settings"} for part in path.split("/")[:-1]):
        return True
    return False


def test_module_name(path: str) -> str:
    name = path.split("/")[-1]
    stem = name
    suffixes = (
        ".test.ts", ".test.tsx", ".test.js", ".test.jsx",
        ".spec.ts", ".spec.tsx", ".spec.js", ".spec.jsx",
        ".py", ".go", ".rb", ".exs", ".dart", ".cpp", ".cc", ".rs",
        ".java", ".kt", ".cs", ".ts", ".tsx", ".js", ".jsx", ".vue", ".svelte",
    )
    for suffix in suffixes:
        if stem.endswith(suffix):
            stem = stem[: -len(suffix)]
            break
    if stem.startswith("test_"):
        stem = stem[5:]
    elif stem.startswith("Test") and stem[4:5].isupper():
        stem = stem[4:]
    elif stem.endswith("_test"):
        stem = stem[:-5]
    elif stem.endswith("Test"):
        stem = stem[:-4]
    return stem or path.split("/")[-2] if "/" in path else (stem or "module")


def _first_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    match = re.match(r"(.+?[.!?])(?:\s|$)", cleaned)
    sentence = match.group(1) if match else cleaned
    return sentence.rstrip(".!?").strip()


def usable_docstring(meta: FileMetadata, cfg: Config) -> str | None:
    if not cfg.use_docstrings or not meta.docstring:
        return None
    first = meta.docstring.strip().splitlines()[0].strip()
    if not first:
        return None
    sentence = _first_sentence(first)
    words = sentence.split()
    if not words or len(words) > cfg.docstring_max_words:
        return None
    lowered = sentence.lower()
    if lowered in GENERIC_DOC_PHRASES:
        return None
    if lowered.endswith("module") or lowered.startswith("this module"):
        return None
    if re.fullmatch(r"[\w\s-]+", sentence) and len(words) == 1:
        return None
    return sentence[:1].upper() + sentence[1:]


def test_description(path: str, meta: FileMetadata) -> str:
    name = path.split("/")[-1].lower()
    if name == "conftest.py":
        return "Shared pytest fixtures and configuration"
    module = test_module_name(path)
    if meta.test_count:
        return f"Tests for {module} ({meta.test_count} tests)"
    return f"Tests for {module}"


def config_description(path: str) -> str | None:
    parts = path.split("/")
    name = parts[-1].lower()
    if name in CONFIG_DESCRIPTIONS:
        return CONFIG_DESCRIPTIONS[name]
    if parts[0].lower() == ".github" and "workflows" in parts[:-1]:
        return "GitHub Actions CI workflow"
    if parts[0].lower() == ".github":
        return "GitHub repository configuration"
    if parts[0].lower() not in {".github", "config", "configs", "conf", ".config"}:
        if name not in CONFIG_DESCRIPTIONS:
            return None
    suffix = Path(name).suffix.lower()
    if suffix in {".yml", ".yaml"}:
        return "Service configuration"
    if suffix == ".toml":
        return "Project configuration"
    if suffix == ".json":
        return "JSON configuration data"
    if suffix in {".ini", ".cfg", ".conf"}:
        return "Application configuration"
    return "Project configuration"


def doc_description(path: str, meta: FileMetadata) -> str:
    name = path.split("/")[-1].lower()
    if name in DOC_NAMES:
        return DOC_NAMES[name]
    if meta.first_lines:
        for line in meta.first_lines.splitlines():
            match = re.match(r"^#{1,3}\s+(.+)$", line.strip())
            if match:
                title = match.group(1).strip().rstrip("#").strip()
                if title and len(title.split()) <= 10:
                    return f"Documentation: {title}"
                break
    return "Project documentation"


def _is_trivial_init(path: str, meta: FileMetadata) -> bool:
    if path.split("/")[-1] != "__init__.py":
        return False
    return meta.lines <= 6 and not meta.classes and not meta.functions


def deterministic_description(
    entry: ScannedFile, meta: FileMetadata, cfg: Config
) -> tuple[str | None, str]:
    path = entry.path
    name = path.split("/")[-1].lower()

    if is_test_path(path):
        return test_description(path, meta), "test-file"

    if _is_trivial_init(path, meta):
        package = path.split("/")[-2] if "/" in path else "project"
        return f"Package marker for {package}", "package-marker"

    if is_doc_path(path):
        return doc_description(path, meta), "docs"

    if is_config_path(path):
        described = config_description(path)
        if described:
            return described, "config"

    if name in CONFIG_DESCRIPTIONS:
        return CONFIG_DESCRIPTIONS[name], "config"

    doc = usable_docstring(meta, cfg)
    if doc:
        return doc, "docstring"

    return None, "needs-ai"


def priority_for(path: str, meta: FileMetadata) -> int:
    name = path.split("/")[-1].lower()
    if name in ENTRY_POINT_NAMES:
        return 0
    parts = [part.lower() for part in path.split("/")[:-1]]
    for folders, score in PRIORITY_FOLDERS:
        if any(part in folders for part in parts):
            return score
    if meta.lines >= 120:
        return 55
    return 60


def assign(
    entries: list[ScannedFile],
    metas: dict[str, FileMetadata],
    cfg: Config,
) -> dict[str, TierDecision]:
    decisions: dict[str, TierDecision] = {}
    for entry in entries:
        meta = metas[entry.path]
        description, reason = deterministic_description(entry, meta, cfg)
        if description is not None:
            decisions[entry.path] = TierDecision(
                path=entry.path,
                tier=TIER_DETERMINISTIC,
                description=description,
                reason=reason,
                priority=0,
            )
        else:
            decisions[entry.path] = TierDecision(
                path=entry.path,
                tier=TIER_LLM,
                description=None,
                reason=reason,
                priority=priority_for(entry.path, meta),
            )

    _reuse_duplicate_hashes(entries, decisions)
    return decisions


def _reuse_duplicate_hashes(
    entries: list[ScannedFile], decisions: dict[str, TierDecision]
) -> None:
    first_by_digest: dict[str, TierDecision] = {}
    ordered = sorted(
        entries,
        key=lambda e: (decisions[e.path].tier != TIER_DETERMINISTIC, decisions[e.path].priority, e.path),
    )
    for entry in ordered:
        decision = decisions[entry.path]
        if not entry.digest:
            continue
        original = first_by_digest.get(entry.digest)
        if original is None:
            if decision.description is not None:
                first_by_digest[entry.digest] = decision
            continue
        if original.path == decision.path:
            continue
        decision.duplicate_of = original.path
        if original.description is not None:
            decision.tier = TIER_DETERMINISTIC
            decision.description = original.description
            decision.reason = "duplicate-content"
            decision.priority = 0
        else:
            decision.reason = "duplicate-content-pending"


def fallback_description(meta: FileMetadata) -> str:
    """Deterministic stand-in when no model description is available."""
    if meta.classes:
        primary = meta.classes[0]
        methods = sum(1 for name in meta.functions if name.startswith(primary + "."))
        if methods:
            return f"{meta.language} module: {primary} ({methods} methods)"
        return f"{meta.language} module: {primary}"
    if meta.functions:
        primary = meta.functions[0]
        extra = len(meta.functions) - 1
        return f"{meta.language} module: {primary}" + (
            f" (+{extra} functions)" if extra else ""
        )
    if meta.declarations:
        first = meta.declarations[0]
        first = re.sub(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?", "", first)
        words = first.split()
        label = " ".join(words[:4])
        return f"{meta.language} file: {label}"
    return f"{meta.language} file"


def directory_key(dir_path: str, child_descriptions: list[str]) -> str:
    import hashlib

    payload = dir_path + "\n" + "\n".join(sorted(child_descriptions))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


DIRECTORY_NAMES = {
    "tests": "Automated tests",
    "test": "Automated tests",
    "__tests__": "Automated tests",
    "spec": "Automated tests",
    "docs": "Documentation",
    "doc": "Documentation",
    "documentation": "Documentation",
    "scripts": "Helper scripts",
    "bin": "Executable scripts",
    "config": "Configuration files",
    "configs": "Configuration files",
    "conf": "Configuration files",
    "settings": "Configuration files",
    "models": "Data models",
    "model": "Data models",
    "schemas": "Data schemas",
    "api": "API routes and handlers",
    "routes": "API routes and handlers",
    "routers": "API routes and handlers",
    "controllers": "Request controllers",
    "handlers": "Request handlers",
    "services": "Core business logic and services",
    "service": "Core business logic and services",
    "core": "Core application logic",
    "domain": "Domain logic",
    "lib": "Shared library code",
    "src": "Application source",
    "app": "Application source",
    "source": "Application source",
    "utils": "Shared helper functions",
    "util": "Shared helper functions",
    "helpers": "Shared helper functions",
    "common": "Shared common code",
    "shared": "Shared code used across modules",
    "migrations": "Database migrations",
    "db": "Database layer",
    "database": "Database layer",
    "repositories": "Data access repositories",
    "static": "Static assets",
    "assets": "Static assets",
    "public": "Public static assets",
    "templates": "View templates",
    "components": "UI components",
    "pages": "Application pages",
    "hooks": "Reusable UI hooks",
    "store": "Application state store",
    "state": "Application state",
    "middleware": "Request middleware",
    "plugins": "Plugins and extensions",
    "workers": "Background workers",
    "jobs": "Background jobs",
    "tasks": "Scheduled tasks",
    "adapters": "External service adapters",
    "integrations": "Third-party integrations",
    "infra": "Infrastructure configuration",
    "infrastructure": "Infrastructure configuration",
    "ci": "Continuous integration",
    ".github": "GitHub configuration and workflows",
    "examples": "Usage examples",
    "benchmarks": "Performance benchmarks",
    "fixtures": "Test fixtures and sample data",
    "types": "Shared type definitions",
    "interfaces": "Shared interfaces",
    "cli": "Command-line interface",
    "commands": "Command implementations",
}


def directory_description(name: str) -> str | None:
    return DIRECTORY_NAMES.get(name.lower())
