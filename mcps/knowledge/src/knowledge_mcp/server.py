from __future__ import annotations

import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import anyio
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from knowledge_mcp.config import AppConfig
from knowledge_mcp.core import KnowledgeCore
from knowledge_mcp.embeddings import create_embedder
from knowledge_mcp.storage import ChromaStore, DataDirectoryLock

logger = logging.getLogger(__name__)


class StaticTokenVerifier:
    def __init__(self, expected_token: str, resource: str):
        self.expected_token = expected_token
        self.resource = resource

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token, self.expected_token):
            return None
        return AccessToken(
            token=token,
            client_id="knowledge-local-client",
            scopes=["knowledge"],
            resource=self.resource,
            subject="local-user",
        )


def ensure_access_token(path: Path) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        token = path.read_text(encoding="utf-8").strip()
        if not token:
            raise RuntimeError(f"Access token file is empty: {path}")
        return token
    token = secrets.token_urlsafe(32)
    descriptor = path.open("x", encoding="utf-8")
    try:
        descriptor.write(f"{token}\n")
    finally:
        descriptor.close()
    path.chmod(0o600)
    return token


def build_core(config: AppConfig) -> KnowledgeCore:
    return KnowledgeCore(
        config=config,
        embedder=create_embedder(config.embedding),
        store=ChromaStore(config.data_dir),
    )


def create_mcp_server(config: AppConfig, core: KnowledgeCore, token: str) -> FastMCP:
    @asynccontextmanager
    async def lifespan(_server: FastMCP):
        async def poll() -> None:
            while True:
                try:
                    await anyio.to_thread.run_sync(lambda: core.sync(retry_errors=True))
                except Exception:
                    logger.exception("Automatic knowledge index synchronization failed")
                await anyio.sleep(config.server.poll_interval_seconds)

        async with anyio.create_task_group() as tasks:
            tasks.start_soon(poll)
            yield {"core": core}
            tasks.cancel_scope.cancel()

    host_values = sorted(
        {
            f"{config.server.host}:{config.server.port}",
            f"127.0.0.1:{config.server.port}",
            f"localhost:{config.server.port}",
        }
    )
    origin_values = [f"http://{value}" for value in host_values]
    auth = AuthSettings(
        issuer_url=f"http://{config.server.host}:{config.server.port}",
        resource_server_url=config.server.url,
        required_scopes=["knowledge"],
        validate_token_resource=True,
    )
    mcp = FastMCP(
        "knowledge",
        instructions="Index and semantically search local files with source locations.",
        host=config.server.host,
        port=config.server.port,
        streamable_http_path=config.server.path,
        lifespan=lifespan,
        token_verifier=StaticTokenVerifier(token, config.server.url),
        auth=auth,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=host_values,
            allowed_origins=origin_values,
        ),
    )

    @mcp.tool(name="index")
    async def index_tool(max_files: int | None = None) -> dict[str, Any]:
        """Index a bounded batch of new, changed, or deleted files."""
        return await anyio.to_thread.run_sync(
            lambda: core.sync(max_files=max_files, retry_errors=False)
        )

    @mcp.tool(name="search")
    async def search_tool(
        query: str, limit: int = 8, folder: str | None = None
    ) -> list[dict[str, Any]]:
        """Semantically search indexed files, optionally below a folder."""
        return await anyio.to_thread.run_sync(
            lambda: core.search(query=query, limit=limit, folder=folder)
        )

    @mcp.tool(name="status")
    async def status_tool() -> dict[str, Any]:
        """Return index, source, and last-synchronization status."""
        return await anyio.to_thread.run_sync(core.status)

    @mcp.tool(name="inspect")
    async def inspect_tool(relative_path: str, max_chars: int = 8_000) -> dict[str, Any]:
        """Inspect bounded indexed text and metadata for one source file."""
        return await anyio.to_thread.run_sync(
            lambda: core.inspect(relative_path, max_chars=max_chars)
        )

    return mcp


def run_server(config: AppConfig) -> None:
    if config.server.token_file is None:
        raise RuntimeError("server.token_file was not resolved")
    owner = DataDirectoryLock(config.data_dir)
    with owner:
        token = ensure_access_token(config.server.token_file)
        server = create_mcp_server(config, build_core(config), token)
        logger.info("Serving knowledge MCP at %s", config.server.url)
        server.run(transport="streamable-http")
