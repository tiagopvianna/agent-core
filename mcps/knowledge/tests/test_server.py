from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from knowledge_mcp.config import AppConfig, ServerConfig
from knowledge_mcp.server import create_mcp_server


class StubCore:
    def sync(self, max_files=None, retry_errors=False):
        return {"indexed": 0, "remaining": 0, "failed": 0}

    def search(self, query, limit=8, folder=None, before=None, after=None):
        return [{"path": "note.txt", "snippet": query}]

    def status(self):
        return {"indexed_files": 1}

    def inspect(self, relative_path, max_chars=8_000):
        return {"path": relative_path}


class ServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_local_http_client_calls_tools_without_authentication(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = AppConfig(
                source_root=base,
                data_dir=base / "data",
                server=ServerConfig(
                    host="127.0.0.1",
                    port=8765,
                    path="/mcp",
                    poll_interval_seconds=3_600,
                ),
            )
            server = create_mcp_server(config, StubCore())
            app = server.streamable_http_app()
            async with app.router.lifespan_context(app):
                transport = httpx.ASGITransport(app=app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url="http://127.0.0.1:8765",
                ) as client:
                    async with streamable_http_client(config.server.url, http_client=client) as (
                        read_stream,
                        write_stream,
                        _session_id,
                    ):
                        async with ClientSession(read_stream, write_stream) as session:
                            await session.initialize()
                            result = await session.call_tool("search", {"query": "alpha"})
            self.assertEqual(
                result.structuredContent,
                {"result": [{"path": "note.txt", "snippet": "alpha"}]},
            )

    async def test_untrusted_host_and_origin_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = AppConfig(source_root=base, data_dir=base / "data")
            app = create_mcp_server(config, StubCore()).streamable_http_app()
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    base_url="http://127.0.0.1:8765",
                ) as client:
                    for headers in (
                        {"Host": "attacker.example"},
                        {"Origin": "https://attacker.example"},
                    ):
                        response = await client.post("/mcp", headers=headers, json={})
                        self.assertIn(response.status_code, (400, 403, 421))


if __name__ == "__main__":
    unittest.main()
