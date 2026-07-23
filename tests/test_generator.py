import pytest

import cppwiki.generator as generator_module
from cppwiki.generator import OpenCodeServerGateway


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    calls = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/global/health"):
            return FakeResponse({"healthy": True, "version": "test"})
        return FakeResponse({"connected": ["ollama"]})

    async def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if url.endswith("/session"):
            return FakeResponse({"id": "session-1"})
        if kwargs.get("json", {}).get("format"):
            return FakeResponse({"info": {"structured_output": {"answer": "ok"}}, "parts": []})
        return FakeResponse({"info": {}, "parts": [{"type": "text", "text": "完成"}]})

    async def delete(self, url, **kwargs):
        self.calls.append(("DELETE", url, kwargs))
        return FakeResponse(True)


@pytest.mark.asyncio
async def test_opencode_gateway_uses_sessions_model_directory_and_disables_tools(monkeypatch):
    FakeClient.calls.clear()
    monkeypatch.setattr(generator_module.httpx, "AsyncClient", FakeClient)
    gateway = OpenCodeServerGateway("http://localhost:4096", "ollama", "qwen3.5:4b")

    assert await gateway.complete_text("hello", "/repo") == "完成"
    message = next(call for call in FakeClient.calls if call[0] == "POST" and call[1].endswith("/message"))
    assert message[2]["headers"]["x-opencode-directory"] == "/repo"
    assert message[2]["json"]["model"] == {
        "providerID": "ollama", "modelID": "qwen3.5:4b"
    }
    assert all(value is False for value in message[2]["json"]["tools"].values())
    assert any(call[0] == "DELETE" for call in FakeClient.calls)


@pytest.mark.asyncio
async def test_opencode_gateway_structured_output_and_health(monkeypatch):
    FakeClient.calls.clear()
    monkeypatch.setattr(generator_module.httpx, "AsyncClient", FakeClient)
    gateway = OpenCodeServerGateway("http://localhost:4096", "ollama", "qwen3.5:4b")
    payload = await gateway.complete_json("hello", {"type": "object"}, "/repo")
    health = await gateway.health()
    assert payload == {"answer": "ok"}
    assert health["healthy"] is True
    assert health["provider_connected"] is True

