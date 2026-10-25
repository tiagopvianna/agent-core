from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from knowledge_mcp.config import AppConfig, load_config
from knowledge_mcp.server import run_server


def _add_json_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowledge", description="Index and semantically search local files"
    )
    parser.add_argument("--config", help="Path to the TOML configuration file")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("serve", help="Run the local MCP server and indexing poller")

    index = commands.add_parser("index", help="Synchronize all currently pending files")
    index.add_argument("--max-files", type=int, help="Files processed by each request")
    _add_json_flag(index)

    search = commands.add_parser("search", help="Run semantic search")
    search.add_argument("query")
    search.add_argument("--folder")
    search.add_argument("--limit", type=int, default=8)
    _add_json_flag(search)

    status = commands.add_parser("status", help="Show index and source status")
    _add_json_flag(status)

    inspect = commands.add_parser("inspect", help="Inspect indexed chunks for one file")
    inspect.add_argument("relative_path")
    inspect.add_argument("--max-chars", type=int, default=8_000)
    _add_json_flag(inspect)
    return parser


def _read_token(config: AppConfig) -> str:
    token_path = config.server.token_file
    if token_path is None or not token_path.is_file():
        raise RuntimeError(
            f"Knowledge server token is unavailable at {token_path}; "
            f"start it with: knowledge --config {config.config_path} serve"
        )
    token = token_path.read_text(encoding="utf-8").strip()
    if not token:
        raise RuntimeError(f"Knowledge server token is empty: {token_path}")
    return token


def _decode_result(result: Any) -> Any:
    if result.isError:
        message = " ".join(block.text for block in result.content if getattr(block, "text", None))
        raise RuntimeError(message or "MCP tool call failed")
    if result.structuredContent is not None:
        value = result.structuredContent
        if isinstance(value, dict) and set(value) == {"result"}:
            return value["result"]
        return value
    texts = [block.text for block in result.content if getattr(block, "text", None)]
    if len(texts) == 1:
        try:
            return json.loads(texts[0])
        except json.JSONDecodeError:
            return texts[0]
    return texts


async def call_tool(config: AppConfig, name: str, arguments: dict[str, Any]) -> Any:
    token = _read_token(config)
    headers = {"Authorization": f"Bearer {token}"}
    try:
        async with httpx.AsyncClient(headers=headers, timeout=120) as http_client:
            async with streamable_http_client(config.server.url, http_client=http_client) as (
                read_stream,
                write_stream,
                _get_session_id,
            ):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    return _decode_result(await session.call_tool(name, arguments))
    except httpx.ConnectError as exc:
        raise RuntimeError(
            f"Knowledge server is not running at {config.server.url}; "
            f"start it with: knowledge --config {config.config_path} serve"
        ) from exc


async def run_index(
    config: AppConfig, max_files: int | None, *, quiet: bool = False
) -> dict[str, Any]:
    aggregate: dict[str, Any] = {
        "indexed": 0,
        "unchanged": 0,
        "removed": 0,
        "failed": 0,
        "remaining": 0,
        "errors": {},
        "scan_complete": True,
    }
    previous_remaining: int | None = None
    while True:
        arguments = {"max_files": max_files} if max_files is not None else {}
        report = await call_tool(config, "index", arguments)
        for key in ("indexed", "removed", "failed"):
            aggregate[key] += int(report.get(key, 0))
        aggregate["unchanged"] = int(report.get("unchanged", 0))
        aggregate["remaining"] = int(report.get("remaining", 0))
        aggregate["scan_complete"] = bool(report.get("scan_complete", True))
        aggregate["errors"].update(report.get("errors", {}))
        if not quiet:
            print(
                f"indexed={report.get('indexed', 0)} removed={report.get('removed', 0)} "
                f"failed={report.get('failed', 0)} remaining={aggregate['remaining']}",
                file=sys.stderr,
            )
        if aggregate["remaining"] <= 0:
            return aggregate
        if previous_remaining == aggregate["remaining"] and report.get("indexed", 0) == 0:
            raise RuntimeError("Index synchronization made no progress")
        previous_remaining = aggregate["remaining"]


def _print_human(command: str, value: Any) -> None:
    if command == "search" and isinstance(value, list):
        if not value:
            print("No matches.")
            return
        for index, hit in enumerate(value, start=1):
            location = hit.get("path", "")
            if hit.get("page"):
                location += f":page {hit['page']}"
            elif hit.get("start_line"):
                location += f":line {hit['start_line']}"
            print(f"{index}. {location}  distance={hit.get('distance', 0):.4f}")
            print(f"   {hit.get('snippet', '').strip()}")
        return
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "serve":
            run_server(config)
            return
        if args.command == "index":
            result = asyncio.run(run_index(config, args.max_files, quiet=args.json))
        elif args.command == "search":
            result = asyncio.run(
                call_tool(
                    config,
                    "search",
                    {"query": args.query, "limit": args.limit, "folder": args.folder},
                )
            )
        elif args.command == "status":
            result = asyncio.run(call_tool(config, "status", {}))
        else:
            result = asyncio.run(
                call_tool(
                    config,
                    "inspect",
                    {"relative_path": args.relative_path, "max_chars": args.max_chars},
                )
            )
        if getattr(args, "json", False):
            print(json.dumps(result, separators=(",", ":"), ensure_ascii=False))
        else:
            _print_human(args.command, result)
        if args.command == "index" and result.get("failed", 0):
            raise SystemExit(2)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
