"""Ollama process lifecycle. This is the safety-critical module.

Rules enforced here:

* A server we did not start is never terminated, including the macOS menu-bar app.
* We stop only the ``Popen`` handle we created.
* Cleanup runs from ``try/finally``, ``atexit`` and SIGINT/SIGTERM handlers.
* ``keep_alive: 0`` unloads the model; it does not stop the server.

Only stdlib ``urllib`` is used for HTTP.
"""

from __future__ import annotations

import atexit
import json
import os
import shutil
import signal
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from .config import Config, ollama_host as resolve_host

OLLAMA_BINARY = "ollama"
SERVER_ENV = {
    "OLLAMA_NUM_PARALLEL": "1",
    "OLLAMA_MAX_LOADED_MODELS": "1",
    "OLLAMA_FLASH_ATTENTION": "1",
}


class OllamaError(RuntimeError):
    """A user-facing failure with a clear message."""


class ModelNotFoundError(OllamaError):
    def __init__(self, model: str):
        self.model = model
        super().__init__(
            f"model '{model}' is not installed. Pull it with:  ollama pull {model}"
        )


@dataclass
class ModelInfo:
    name: str
    size: int = 0
    size_vram: int = 0


@dataclass
class OllamaManager:
    cfg: Config = field(default_factory=Config)
    host: str = ""
    owned: bool = False
    process: subprocess.Popen | None = None
    last_model: str | None = None
    track: bool = True
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _cleaned: bool = False

    def __post_init__(self) -> None:
        if not self.host:
            self.host = resolve_host(self.cfg)
        if self.track:
            _MANAGERS.append(self)
            install_atexit()

    # -- HTTP --------------------------------------------------------------

    def _url(self, path: str) -> str:
        return self.host.rstrip("/") + path

    def _request(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self._url(path), data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout or self.cfg.request_timeout) as response:
                body = response.read()
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            if exc.code == 404 and "not found" in detail.lower():
                message = detail
                try:
                    message = json.loads(detail).get("error", detail)
                except ValueError:
                    pass
                raise ModelNotFoundError(_model_from_error(str(message))) from exc
            raise OllamaError(f"Ollama returned HTTP {exc.code}: {detail.strip() or exc.reason}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise OllamaConnectionError(str(exc)) from exc
        if not body:
            return {}
        try:
            parsed = json.loads(body.decode("utf-8", "replace"))
        except ValueError as exc:
            raise OllamaError("Ollama returned a non-JSON response") from exc
        if isinstance(parsed, dict) and parsed.get("error"):
            message = str(parsed["error"])
            if "not found" in message.lower() and "model" in message.lower():
                raise ModelNotFoundError(_model_from_error(message))
            raise OllamaError(message)
        return parsed if isinstance(parsed, dict) else {}

    # -- lifecycle ---------------------------------------------------------

    def version(self) -> str | None:
        try:
            payload = self._request("GET", "/api/version", timeout=min(3.0, self.cfg.request_timeout))
        except OllamaConnectionError:
            return None
        except OllamaError:
            return None
        return str(payload.get("version", ""))

    def is_running(self) -> bool:
        return self.version() is not None

    def ensure_running(self) -> bool:
        """Reuse a running server, or start and own one. Returns ownership."""
        with self._lock:
            if self.owned and self.process is not None and self.process.poll() is None:
                return True
            if self.is_running():
                self.owned = False
                self.process = None
                return False
            install_atexit()
            self._start_server()
            self.owned = True
            return True

    def _start_server(self) -> None:
        binary = shutil.which(OLLAMA_BINARY)
        if not binary:
            raise OllamaError(
                "The 'ollama' binary was not found on PATH. Install Ollama from "
                "https://ollama.com/download or add it to PATH."
            )
        environment = os.environ.copy()
        environment.update(SERVER_ENV)
        if self.host and self.host not in {"http://127.0.0.1:11434", "https://127.0.0.1:11434"}:
            environment["OLLAMA_HOST"] = self.host
        try:
            self.process = subprocess.Popen(
                [binary, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=environment,
                start_new_session=True,
            )
        except OSError as exc:
            raise OllamaError(f"Could not start Ollama: {exc}") from exc

        deadline = time.monotonic() + self.cfg.ollama_start_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                code = self.process.returncode
                self.process = None
                raise OllamaError(
                    f"Ollama exited immediately (status {code}). "
                    f"Check that port {_port(self.host)} is free and try again."
                )
            if self.is_running():
                return
            time.sleep(0.1)
        self._stop_process()
        raise OllamaError(
            f"Ollama did not become ready within {self.cfg.ollama_start_timeout:.0f}s "
            f"at {self.host}. Start it manually with: ollama serve"
        )

    def _stop_process(self) -> None:
        process = self.process
        self.process = None
        if process is None:
            return
        if process.poll() is not None:
            return
        try:
            process.terminate()
        except OSError:
            return
        try:
            process.wait(timeout=5)
            return
        except subprocess.TimeoutExpired:
            pass
        try:
            process.kill()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            pass

    # -- models ------------------------------------------------------------

    def load_model(self, model: str) -> None:
        """Empty generate request: loads the model, keeps it for the run."""
        self._request(
            "POST",
            "/api/generate",
            {
                "model": model,
                "prompt": "",
                "stream": False,
                "keep_alive": self.cfg.keep_alive,
            },
        )
        self.last_model = model

    def unload_model(self, model: str | None = None) -> None:
        model = model or self.last_model
        if not model:
            return
        try:
            self._request(
                "POST",
                "/api/generate",
                {"model": model, "prompt": "", "stream": False, "keep_alive": 0},
                timeout=min(10.0, self.cfg.request_timeout),
            )
        except (OllamaError, OSError):
            pass

    def chat(
        self,
        model: str,
        messages: list[dict],
        fmt: str | None = None,
        options: dict | None = None,
        keep_alive: str | int | None = None,
        timeout: float | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": self.cfg.keep_alive if keep_alive is None else keep_alive,
        }
        if fmt:
            payload["format"] = fmt
        if options:
            payload["options"] = options
        response = self._request("POST", "/api/chat", payload, timeout=timeout)
        self.last_model = model
        return response

    def ps(self) -> list[ModelInfo]:
        try:
            payload = self._request("GET", "/api/ps", timeout=min(5.0, self.cfg.request_timeout))
        except OllamaError:
            return []
        models = payload.get("models") or []
        result: list[ModelInfo] = []
        for item in models:
            if not isinstance(item, dict):
                continue
            result.append(
                ModelInfo(
                    name=str(item.get("name") or item.get("model") or ""),
                    size=int(item.get("size") or 0),
                    size_vram=int(item.get("size_vram") or 0),
                )
            )
        return result

    def wait_until_unloaded(self, model: str | None = None, timeout: float = 5.0) -> bool:
        model = model or self.last_model
        if not model:
            return True
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not any(_same_model(info.name, model) for info in self.ps()):
                return True
            time.sleep(0.1)
        return not any(_same_model(info.name, model) for info in self.ps())

    # -- cleanup -----------------------------------------------------------

    def cleanup(self) -> None:
        with self._lock:
            if self._cleaned:
                return
            self._cleaned = True
            model = self.last_model
            if model and self.is_running():
                self.unload_model(model)
                self.wait_until_unloaded(model)
            if self.owned:
                self._stop_process()
            self.owned = False

class OllamaConnectionError(OllamaError):
    pass


_MANAGERS: list[OllamaManager] = []
_HANDLER_INSTALLED = False
_CLEANING = False


def _make_handler(previous):
    def handler(signum, frame):
        cleanup_registered()
        if callable(previous) and previous not in (signal.SIG_DFL, signal.SIG_IGN):
            return previous(signum, frame)
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    return handler


def cleanup_registered() -> None:
    global _CLEANING
    if _CLEANING:
        return
    _CLEANING = True
    try:
        for manager in list(_MANAGERS):
            try:
                manager.cleanup()
            except Exception:
                continue
    finally:
        _CLEANING = False


def _model_from_error(message: str) -> str:
    for quote in ("'", '"'):
        if quote in message:
            parts = message.split(quote)
            if len(parts) >= 3:
                return parts[1]
    return "the requested model"


def _same_model(left: str, right: str) -> bool:
    def norm(name: str) -> str:
        return name if ":" in name else name + ":latest"

    return norm(left) == norm(right)


def _port(host: str) -> int:
    tail = host.rsplit(":", 1)
    if len(tail) == 2 and tail[1].isdigit():
        return int(tail[1])
    return 11434


def install_atexit() -> None:
    global _HANDLER_INSTALLED
    if _HANDLER_INSTALLED:
        return
    _HANDLER_INSTALLED = True
    atexit.register(cleanup_registered)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous = signal.getsignal(sig)
            signal.signal(sig, _make_handler(previous))
        except (ValueError, OSError):
            continue


def probe(host: str = "", timeout: float = 3.0) -> dict | None:
    """One-off availability probe used before deciding whether to start a server."""
    cfg = Config()
    cfg.request_timeout = timeout
    manager = OllamaManager(cfg=cfg, host=host, track=False)
    version = manager.version()
    if version is None:
        return None
    return {"version": version, "host": manager.host}


def ps_snapshot(host: str = "") -> list[ModelInfo]:
    return OllamaManager(cfg=Config(), host=host, track=False).ps()
