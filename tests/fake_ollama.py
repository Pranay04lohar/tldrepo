"""A tiny fake Ollama HTTP server used by unit tests. No model is downloaded."""

from __future__ import annotations

import json
import socketserver
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class _FastHTTPServer(ThreadingHTTPServer):
    """Skip getfqdn(), which can block for tens of seconds on macOS."""

    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name = "127.0.0.1"
        self.server_port = self.server_address[1]


def _dynamic_answer(payload: dict) -> str:
    import re

    user = ""
    for message in payload.get("messages") or []:
        if message.get("role") == "user":
            user = str(message.get("content") or "")
    numbers = re.findall(r"FILE (\d+): (\S+)", user)
    if numbers:
        return "\n".join(f"{number}|Fake description" for number, _path in numbers)
    dirs = re.findall(r"DIR (\d+):", user)
    return "\n".join(f"{number}|Fake directory purpose" for number in dirs)


class FakeOllama:
    def __init__(self, port: int = 0, version: str = "0.40.13"):
        self.version = version
        self.requests: list[dict] = []
        self.resident: list[str] = []
        self.installed: list[str] = []
        self.missing: set[str] = set()
        self.fail_chat = False
        self.chat_delay = 0.0
        self.chat_output: str | None = None
        self._server = _FastHTTPServer(("127.0.0.1", port), self._handler())
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def host(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _handler(self):
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):
                return

            def _send(self, status: int, payload: dict) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path == "/api/version":
                    self._send(200, {"version": fake.version})
                elif self.path == "/api/ps":
                    self._send(
                        200,
                        {
                            "models": [
                                {"name": name, "size": 100, "size_vram": 100}
                                for name in fake.resident
                            ]
                        },
                    )
                elif self.path == "/api/tags":
                    self._send(
                        200,
                        {"models": [{"name": name} for name in fake.installed]},
                    )
                else:
                    self._send(404, {"error": "unknown path"})

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length) if length else b"{}"
                try:
                    payload = json.loads(raw.decode() or "{}")
                except ValueError:
                    payload = {}
                fake.requests.append({"path": self.path, "payload": payload})
                if fake.fail_chat and payload.get("model"):
                    self._send(500, {"error": "inference exploded"})
                    return
                if self.path == "/api/generate":
                    model = payload.get("model", "")
                    if model in fake.missing:
                        self._send(404, {"error": f"model '{model}' not found"})
                        return
                    if payload.get("keep_alive") == 0:
                        fake.resident = [m for m in fake.resident if m != model]
                    elif model and model not in fake.resident:
                        fake.resident.append(model)
                    self._send(200, {"model": model, "response": "", "done": True})
                elif self.path == "/api/chat":
                    if fake.chat_delay:
                        import time

                        time.sleep(fake.chat_delay)
                    model = payload.get("model", "")
                    if model in fake.missing:
                        self._send(404, {"error": f"model '{model}' not found"})
                        return
                    if model and model not in fake.resident:
                        fake.resident.append(model)
                    content = (
                        fake.chat_output
                        if fake.chat_output is not None
                        else _dynamic_answer(payload)
                    )
                    self._send(
                        200,
                        {
                            "model": model,
                            "message": {"role": "assistant", "content": content},
                            "done": True,
                            "prompt_eval_count": 10,
                            "eval_count": 5,
                        },
                    )
                else:
                    self._send(404, {"error": "unknown path"})

        return Handler

    def start(self) -> "FakeOllama":
        self._thread = threading.Thread(target=lambda: self._server.serve_forever(poll_interval=0.02), daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()
