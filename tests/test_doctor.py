from __future__ import annotations

import subprocess

import pytest

from tldrepo.config import Config
from tldrepo.doctor import run_doctor

from fake_ollama import FakeOllama


@pytest.fixture
def fake(monkeypatch):
    server = FakeOllama().start()
    monkeypatch.setenv("OLLAMA_HOST", server.host)
    yield server
    server.stop()


def test_doctor_passes_with_python_ollama_and_model(fake, monkeypatch, capsys):
    fake.installed = [Config().model]
    monkeypatch.setattr("tldrepo.doctor.shutil.which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(
        "tldrepo.doctor.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout="ollama version is 0.40.13\n", stderr=""
        ),
    )
    assert run_doctor(Config()) == 0
    out = capsys.readouterr().out
    assert "PASS  Python" in out
    assert "PASS  Ollama installed" in out
    assert "PASS  Default model" in out


def test_doctor_reports_a_missing_model_with_the_pull_command(fake, monkeypatch, capsys):
    fake.installed = []
    monkeypatch.setattr("tldrepo.doctor.shutil.which", lambda name: "/usr/bin/ollama")
    monkeypatch.setattr(
        "tldrepo.doctor.subprocess.run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 0, stdout="ollama version is 0.40.13\n", stderr=""
        ),
    )
    assert run_doctor(Config()) == 1
    out = capsys.readouterr().out
    assert f"FAIL  Default model {Config().model} is missing" in out
    assert f"ollama pull {Config().model}" in out


def test_doctor_reports_missing_ollama_without_a_traceback(monkeypatch, capsys):
    monkeypatch.setattr("tldrepo.doctor.shutil.which", lambda name: None)
    assert run_doctor(Config()) == 1
    out = capsys.readouterr().out
    assert "FAIL  Ollama is not installed" in out
    assert "https://ollama.com/download" in out
    assert "tldrepo --no-ai" in out
    assert "Traceback" not in out


def test_first_run_messages_are_friendly_and_actionable():
    from tldrepo.analyzer import _ai_unavailable_message
    from tldrepo.config import Config as Cfg
    from tldrepo.ollama_manager import ModelNotFoundError, OllamaError

    missing_server = _ai_unavailable_message(
        Cfg(), OllamaError("The 'ollama' binary was not found on PATH.")
    )
    assert "https://ollama.com/download" in missing_server
    assert "tldrepo --no-ai" in missing_server
    assert "Traceback" not in missing_server

    missing_model = _ai_unavailable_message(Cfg(), ModelNotFoundError("lfm3:1.7b"))
    assert "ollama pull lfm3:1.7b" in missing_model
    assert "tldrepo --no-ai" in missing_model
