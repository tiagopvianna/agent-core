from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_CONFIG_PATH = Path("~/.config/knowledge-mcp/config.toml").expanduser()


@dataclass(frozen=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8765
    path: str = "/mcp"
    poll_interval_seconds: float = 30.0
    token_file: Path | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}{self.path}"


@dataclass(frozen=True)
class IndexConfig:
    max_files_per_sync: int = 10
    max_file_bytes: int = 20_000_000
    max_pdf_pages: int = 1_000
    chunk_tokens: int = 220
    overlap_tokens: int = 30


@dataclass(frozen=True)
class EmbeddingConfig:
    provider: str = "sentence_transformers"
    model: str = "sentence-transformers/all-MiniLM-L6-v2"
    batch_size: int = 32
    normalize: bool = True


@dataclass(frozen=True)
class AppConfig:
    source_root: Path
    data_dir: Path
    server: ServerConfig = field(default_factory=ServerConfig)
    index: IndexConfig = field(default_factory=IndexConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
    parsers: dict[str, str] = field(
        default_factory=lambda: {".md": "markdown", ".txt": "text", ".pdf": "pdf"}
    )
    exclude: tuple[str, ...] = (
        "**/.git/**",
        "**/.venv/**",
        "**/node_modules/**",
        "**/__pycache__/**",
    )
    config_path: Path | None = None


def _resolve_path(value: str, base: Path) -> Path:
    expanded = Path(os.path.expandvars(value)).expanduser()
    if not expanded.is_absolute():
        expanded = base / expanded
    return expanded.resolve()


def _mapping(value: Any, name: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a TOML table")
    return value


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = Path(path).expanduser().resolve() if path else DEFAULT_CONFIG_PATH.resolve()
    if not config_path.is_file():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}. "
            "Copy config.example.toml and pass it with --config."
        )

    try:
        raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {config_path}: {exc}") from exc

    base = config_path.parent
    source_value = raw.get("source_root")
    data_value = raw.get("data_dir")
    if not isinstance(source_value, str) or not isinstance(data_value, str):
        raise ValueError("source_root and data_dir must be configured as paths")

    source_root = _resolve_path(source_value, base)
    data_dir = _resolve_path(data_value, base)
    server_raw = _mapping(raw.get("server"), "server")
    index_raw = _mapping(raw.get("index"), "index")
    embedding_raw = _mapping(raw.get("embedding"), "embedding")
    parsers_raw = _mapping(raw.get("parsers"), "parsers")

    token_value = server_raw.get("token_file")
    token_file = (
        _resolve_path(token_value, base)
        if isinstance(token_value, str)
        else data_dir / "access-token"
    )
    server = ServerConfig(
        host=str(server_raw.get("host", "127.0.0.1")),
        port=int(server_raw.get("port", 8765)),
        path=str(server_raw.get("path", "/mcp")),
        poll_interval_seconds=float(server_raw.get("poll_interval_seconds", 30)),
        token_file=token_file,
    )
    index = IndexConfig(
        max_files_per_sync=int(index_raw.get("max_files_per_sync", 10)),
        max_file_bytes=int(index_raw.get("max_file_bytes", 20_000_000)),
        max_pdf_pages=int(index_raw.get("max_pdf_pages", 1_000)),
        chunk_tokens=int(index_raw.get("chunk_tokens", 220)),
        overlap_tokens=int(index_raw.get("overlap_tokens", 30)),
    )
    embedding = EmbeddingConfig(
        provider=str(embedding_raw.get("provider", "sentence_transformers")),
        model=str(embedding_raw.get("model", "sentence-transformers/all-MiniLM-L6-v2")),
        batch_size=int(embedding_raw.get("batch_size", 32)),
        normalize=bool(embedding_raw.get("normalize", True)),
    )
    parsers = {
        (extension if extension.startswith(".") else f".{extension}").lower(): str(parser)
        for extension, parser in (
            parsers_raw or {".md": "markdown", ".txt": "text", ".pdf": "pdf"}
        ).items()
    }
    exclude_raw = raw.get("exclude", list(AppConfig.__dataclass_fields__["exclude"].default))
    if not isinstance(exclude_raw, list) or not all(isinstance(item, str) for item in exclude_raw):
        raise ValueError("exclude must be a list of glob strings")

    config = AppConfig(
        source_root=source_root,
        data_dir=data_dir,
        server=server,
        index=index,
        embedding=embedding,
        parsers=parsers,
        exclude=tuple(exclude_raw),
        config_path=config_path,
    )
    validate_config(config)
    return config


def validate_config(config: AppConfig) -> None:
    if config.server.host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("The first version only permits a loopback server host")
    if not 1 <= config.server.port <= 65_535:
        raise ValueError("server.port must be between 1 and 65535")
    if not config.server.path.startswith("/"):
        raise ValueError("server.path must start with /")
    if config.server.poll_interval_seconds <= 0:
        raise ValueError("server.poll_interval_seconds must be positive")
    if config.index.max_files_per_sync <= 0 or config.index.max_file_bytes <= 0:
        raise ValueError("index file limits must be positive")
    if config.index.max_pdf_pages <= 0 or config.index.chunk_tokens <= 0:
        raise ValueError("PDF and chunk limits must be positive")
    if not 0 <= config.index.overlap_tokens < config.index.chunk_tokens:
        raise ValueError("overlap_tokens must be non-negative and smaller than chunk_tokens")
    if config.embedding.batch_size <= 0:
        raise ValueError("embedding.batch_size must be positive")
    if not config.parsers:
        raise ValueError("At least one parser mapping is required")
    allowed_parsers = {"text", "markdown", "pdf"}
    unknown = sorted(set(config.parsers.values()) - allowed_parsers)
    if unknown:
        raise ValueError(f"Unknown parser names: {', '.join(unknown)}")
    if config.data_dir == config.source_root:
        raise ValueError("data_dir must not be the same directory as source_root")
