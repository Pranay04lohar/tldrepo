from __future__ import annotations

import re
import urllib.request
from pathlib import Path

from tldrepo.main import run

from fake_ollama import FakeOllama

PACKAGE = Path(__file__).resolve().parents[1] / "tldrepo"


def test_network_access_is_confined_to_the_ollama_module():
    offenders = []
    for path in PACKAGE.glob("*.py"):
        text = path.read_text("utf-8")
        if re.search(r"\b(?:import|from)\s+(?:requests|httpx|aiohttp|socket|http\.client)\b", text):
            offenders.append(f"{path.name}: third-party or raw socket network import")
        if "urllib.request" in text and path.name != "ollama_manager.py":
            offenders.append(f"{path.name}: urllib.request outside ollama_manager.py")
    assert offenders == []


def test_only_ollama_host_is_contacted(monkeypatch, tmp_path):
    server = FakeOllama().start()
    monkeypatch.setenv("OLLAMA_HOST", server.host)
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    (repo / "app.py").write_text("def run():\n    return 1\n", "utf-8")
    monkeypatch.chdir(repo)

    seen: list[str] = []
    original = urllib.request.urlopen

    def spy(request, *args, **kwargs):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        seen.append(url)
        return original(request, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", spy)
    try:
        assert run([]) == 0
    finally:
        from tldrepo.ollama_manager import cleanup_registered

        cleanup_registered()
        server.stop()

    assert seen, "the AI path should have contacted Ollama"
    assert all(url.startswith(server.host) for url in seen), seen
