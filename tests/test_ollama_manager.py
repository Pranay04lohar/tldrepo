from __future__ import annotations

import socket

import pytest

from explain.config import Config
from explain import ollama_manager as om
from explain.ollama_manager import (
    ModelNotFoundError,
    OllamaError,
    OllamaManager,
    cleanup_registered,
    probe,
)

from fake_ollama import FakeOllama


@pytest.fixture(autouse=True)
def reset_registry():
    om._MANAGERS.clear()
    om._CLEANING = False
    yield
    cleanup_registered()
    om._MANAGERS.clear()


@pytest.fixture
def fake():
    server = FakeOllama().start()
    yield server
    server.stop()


def manager_for(fake_server, **cfg):
    config = Config(**cfg)
    return OllamaManager(cfg=config, host=fake_server.host)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class FakePopen:
    def __init__(self, args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.returncode = None
        self.terminated = False
        self.killed = False
        self.waited = 0
        self._server = None
        if kwargs.get("start_new_session") is not True:
            raise AssertionError("Popen must start a new session")
        port = kwargs.pop("_test_port", None) or 0
        server = kwargs.get("env", {}).get("_FAKE_PORT")
        if server:
            self._server = FakeOllama(port=int(server)).start()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = -15
        if self._server:
            self._server.stop()

    def wait(self, timeout=None):
        self.waited += 1
        if self.returncode is None:
            self.returncode = 0
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9


def test_existing_server_is_reused_and_never_stopped(fake, monkeypatch):
    def no_popen(*args, **kwargs):
        raise AssertionError("must not start a second server")

    monkeypatch.setattr(om.subprocess, "Popen", no_popen)
    manager = manager_for(fake)
    assert manager.is_running()
    assert manager.ensure_running() is False
    assert manager.owned is False

    manager.load_model("qwen2.5-coder:1.5b")
    manager.cleanup()
    assert fake.resident == []
    assert manager.is_running()


def test_owned_server_is_started_with_safe_environment_and_stopped(monkeypatch):
    port = free_port()
    manager = OllamaManager(cfg=Config(ollama_start_timeout=3.0), host=f"http://127.0.0.1:{port}")

    started = {}
    server = {}

    class StartingFakePopen(FakePopen):
        def __init__(self, args, **kwargs):
            kwargs["env"] = dict(kwargs["env"])
            started["args"] = args
            started["env"] = kwargs["env"]
            started["session"] = kwargs.get("start_new_session")
            super().__init__(args, **kwargs)
            server["fake"] = FakeOllama(port=port).start()

    fake = None

    monkeypatch.setattr(om.shutil, "which", lambda name: "/fake/ollama")
    monkeypatch.setattr(om.subprocess, "Popen", StartingFakePopen)

    assert manager.ensure_running() is True
    fake = server["fake"]
    assert manager.owned is True
    assert started["args"] == ["/fake/ollama", "serve"]
    assert started["session"] is True
    for key, value in om.SERVER_ENV.items():
        assert started["env"][key] == value

    manager.load_model("qwen2.5-coder:1.5b")
    assert fake.resident == ["qwen2.5-coder:1.5b"]
    manager.cleanup()
    assert fake.resident == []
    assert manager.process is None
    assert manager.owned is False


def test_stop_uses_terminate_then_kill_on_timeout(monkeypatch):
    events = []

    class StubbornPopen:
        def __init__(self, args, **kwargs):
            self.returncode = None

        def poll(self):
            return self.returncode

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout=None):
            events.append(("wait", timeout))
            if len([e for e in events if isinstance(e, tuple)]) == 1:
                raise om.subprocess.TimeoutExpired(cmd="ollama", timeout=timeout)
            self.returncode = -9
            return self.returncode

        def kill(self):
            events.append("kill")

    manager = OllamaManager(cfg=Config(), host=f"http://127.0.0.1:{free_port()}", track=False)
    manager.process = StubbornPopen([], start_new_session=True)
    manager._stop_process()
    assert "terminate" in events
    assert "kill" in events
    assert manager.process is None


def test_startup_failure_is_reported_and_process_reaped(monkeypatch):
    class DeadPopen(FakePopen):
        def __init__(self, args, **kwargs):
            super().__init__(args, **kwargs)
            self.returncode = 1

    monkeypatch.setattr(om.shutil, "which", lambda name: "/fake/ollama")
    monkeypatch.setattr(om.subprocess, "Popen", DeadPopen)
    manager = OllamaManager(cfg=Config(ollama_start_timeout=0.2), host=f"http://127.0.0.1:{free_port()}")
    with pytest.raises(OllamaError, match="exited immediately"):
        manager.ensure_running()
    assert manager.process is None


def test_missing_binary_is_a_clear_error(monkeypatch):
    monkeypatch.setattr(om.shutil, "which", lambda name: None)
    manager = OllamaManager(cfg=Config(), host=f"http://127.0.0.1:{free_port()}", track=False)
    with pytest.raises(OllamaError, match="not found on PATH"):
        manager.ensure_running()


def test_model_not_found_message_includes_pull_command(fake):
    manager = manager_for(fake)
    fake.missing.add("qwen9:99b")
    with pytest.raises(ModelNotFoundError) as info:
        manager.load_model("qwen9:99b")
    assert "ollama pull qwen9:99b" in str(info.value)


def test_load_and_unload_use_correct_keep_alive(fake):
    manager = manager_for(fake)
    manager.ensure_running()
    manager.load_model("qwen3:1.7b")
    assert manager.wait_until_unloaded("qwen3:1.7b", timeout=0) is False
    manager.unload_model("qwen3:1.7b")
    assert manager.wait_until_unloaded("qwen3:1.7b", timeout=2.0) is True
    keep_alives = [
        request["payload"].get("keep_alive")
        for request in fake.requests
        if request["path"] == "/api/generate"
    ]
    assert "5m" in keep_alives or "5m" == manager.cfg.keep_alive
    assert 0 in keep_alives


def test_cleanup_is_idempotent(fake):
    manager = manager_for(fake)
    manager.load_model("qwen3:1.7b")
    manager.cleanup()
    manager.cleanup()
    assert manager._cleaned is True
    assert fake.resident == []


def test_cleanup_registered_only_stops_owned_processes(fake, monkeypatch):
    monkeypatch.setattr(om.subprocess, "Popen", FakePopen)
    reused = manager_for(fake)
    reused.ensure_running()
    cleanup_registered()
    assert reused.is_running()

    owned = manager_for(fake)
    owned.owned = True
    owned.process = FakePopen([], start_new_session=True, env={})
    cleanup_registered()
    assert owned.process is None


def test_ollama_host_env_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:9999")
    manager = OllamaManager(cfg=Config(), track=False)
    assert manager.host == "http://127.0.0.1:9999"


def test_probe_returns_none_when_nothing_listens():
    assert probe(host=f"http://127.0.0.1:{free_port()}", timeout=0.3) is None


def test_probe_returns_version(fake):
    result = probe(host=fake.host, timeout=1.0)
    assert result is not None
    assert result["version"] == fake.version
