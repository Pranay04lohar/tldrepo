"""`tldrepo --doctor`: a short, non-destructive environment check."""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys

from .config import Config, ollama_host
from .ollama_manager import OllamaManager


def _same_model(left: str, right: str) -> bool:
    def norm(name: str) -> str:
        return name if ":" in name else name + ":latest"

    return norm(left) == norm(right)


def run_doctor(cfg: Config) -> int:
    ok = True

    version = platform.python_version()
    if sys.version_info >= (3, 11):
        print(f"PASS  Python {version} (requires 3.11+)")
    else:
        ok = False
        print(f"FAIL  Python {version} is too old; tldrepo requires 3.11+")

    binary = shutil.which("ollama")
    if not binary:
        ok = False
        print(
            "FAIL  Ollama is not installed; get it from https://ollama.com/download "
            "or use tldrepo --no-ai"
        )
    else:
        try:
            result = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            output = (result.stdout or result.stderr).strip().splitlines()
            label = output[0] if output else "version unknown"
            if result.returncode == 0:
                print(f"PASS  Ollama installed ({label})")
            else:
                ok = False
                print(f"FAIL  Ollama found but did not report a version ({label})")
        except (OSError, subprocess.TimeoutExpired) as exc:
            ok = False
            print(f"FAIL  Ollama found but could not run: {exc}")

    manager = OllamaManager(cfg=cfg, track=False)
    host = ollama_host(cfg)
    server_version = manager.version()
    if server_version is None:
        ok = False
        print(
            f"FAIL  Ollama server not reachable at {host}; start it with: ollama serve"
        )
    else:
        installed = manager.models()
        if any(_same_model(name, cfg.model) for name in installed):
            print(f"PASS  Default model {cfg.model} is available")
        else:
            ok = False
            print(
                f"FAIL  Default model {cfg.model} is missing; run: "
                f"ollama pull {cfg.model}"
            )

    return 0 if ok else 1
