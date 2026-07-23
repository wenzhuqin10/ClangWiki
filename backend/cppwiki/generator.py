import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Optional

import httpx


class GeneratorGateway(ABC):
    @abstractmethod
    async def health(self) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    async def complete_text(self, prompt: str, directory: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def complete_json(self, prompt: str, schema: Dict[str, Any], directory: str) -> Any:
        raise NotImplementedError

    async def stream_text(self, prompt: str, directory: str) -> AsyncIterator[str]:
        yield await self.complete_text(prompt, directory)


class OpenCodeServerGateway(GeneratorGateway):
    def __init__(
        self,
        base_url: str,
        provider_id: str,
        model_id: str,
        username: str = "opencode",
        password: Optional[str] = None,
        timeout: float = 900.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.provider_id = provider_id
        self.model_id = model_id
        self.username = username
        self.password = password
        self.timeout = timeout

    @property
    def auth(self) -> Optional[httpx.BasicAuth]:
        return httpx.BasicAuth(self.username, self.password) if self.password else None

    def _headers(self, directory: str) -> Dict[str, str]:
        return {"x-opencode-directory": directory}

    async def health(self) -> Dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=10.0, auth=self.auth) as client:
                response = await client.get(self.base_url + "/global/health")
                response.raise_for_status()
                provider_response = await client.get(self.base_url + "/provider")
                provider_response.raise_for_status()
            payload = response.json()
            providers = provider_response.json()
            connected = providers.get("connected", []) if isinstance(providers, dict) else []
            return {
                "healthy": bool(payload.get("healthy")),
                "version": payload.get("version"),
                "provider": self.provider_id,
                "model": self.model_id,
                "provider_connected": self.provider_id in connected,
            }
        except Exception as exc:
            return {
                "healthy": False, "provider": self.provider_id,
                "model": self.model_id, "error": str(exc),
            }

    async def _create_session(self, client: httpx.AsyncClient, directory: str) -> str:
        response = await client.post(
            self.base_url + "/session",
            headers=self._headers(directory),
            json={"title": "cpp-deepwiki generation"},
        )
        response.raise_for_status()
        session = response.json()
        session_id = session.get("id")
        if not session_id:
            raise RuntimeError("OpenCode session response has no id")
        return session_id

    async def _prompt(
        self, prompt: str, directory: str, schema: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout, auth=self.auth) as client:
            session_id = await self._create_session(client, directory)
            body: Dict[str, Any] = {
                "model": {"providerID": self.provider_id, "modelID": self.model_id},
                "tools": {"bash": False, "edit": False, "write": False, "patch": False},
                "parts": [{"type": "text", "text": prompt}],
            }
            if schema:
                body["format"] = {"type": "json_schema", "schema": schema, "retryCount": 2}
            try:
                last_error: Optional[Exception] = None
                for attempt in range(3):
                    try:
                        response = await client.post(
                            self.base_url + "/session/%s/message" % session_id,
                            headers=self._headers(directory), json=body,
                        )
                        status = getattr(response, "status_code", 200)
                        if status in {408, 429, 500, 502, 503, 504} and attempt < 2:
                            await asyncio.sleep(2 ** attempt)
                            continue
                        response.raise_for_status()
                        return response.json()
                    except httpx.TransportError as exc:
                        last_error = exc
                        if attempt == 2:
                            raise
                        await asyncio.sleep(2 ** attempt)
                raise RuntimeError("OpenCode request exhausted retries") from last_error
            finally:
                try:
                    await client.delete(
                        self.base_url + "/session/%s" % session_id,
                        headers=self._headers(directory),
                    )
                except httpx.HTTPError:
                    pass

    async def complete_text(self, prompt: str, directory: str) -> str:
        payload = await self._prompt(prompt, directory)
        texts = [
            part.get("text", "") for part in payload.get("parts", [])
            if part.get("type") == "text"
        ]
        result = "".join(texts).strip()
        if not result:
            raise RuntimeError("OpenCode returned no text parts")
        return result

    async def complete_json(self, prompt: str, schema: Dict[str, Any], directory: str) -> Any:
        payload = await self._prompt(prompt, directory, schema)
        structured = payload.get("info", {}).get("structured_output")
        if structured is not None:
            return structured
        text = "".join(
            part.get("text", "") for part in payload.get("parts", [])
            if part.get("type") == "text"
        ).strip()
        return json.loads(text)


class FakeGeneratorGateway(GeneratorGateway):
    def __init__(self, text: str = "# 测试文档\n\n生成成功。"):
        self.text = text

    async def health(self) -> Dict[str, Any]:
        return {"healthy": True, "provider": "fake", "model": "fake"}

    async def complete_text(self, prompt: str, directory: str) -> str:
        return self.text

    async def complete_json(self, prompt: str, schema: Dict[str, Any], directory: str) -> Any:
        return {
            "title": "测试仓库",
            "description": "自动生成的测试规划",
            "pages": [
                {"id": "overview", "title": "项目概览", "description": "整体架构", "query": "主要模块"},
                {"id": "api", "title": "核心接口", "description": "公开接口", "query": "核心 API"},
            ],
        }
