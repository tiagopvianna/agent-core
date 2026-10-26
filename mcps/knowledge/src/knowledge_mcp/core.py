from __future__ import annotations

import hashlib
import threading
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from knowledge_mcp.config import AppConfig
from knowledge_mcp.embeddings import Embedder
from knowledge_mcp.ingest import (
    chunk_segments,
    discover_files,
    parse_content,
    processing_fingerprint,
    read_stable_content,
)
from knowledge_mcp.models import DiscoveredFile, SyncReport


def _safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not value or any(part == ".." for part in path.parts):
        raise ValueError("Path must be relative to the configured source root")
    normalized = path.as_posix()
    if normalized == ".":
        raise ValueError("Path must identify a file or folder below the source root")
    return normalized[2:] if normalized.startswith("./") else normalized


def _current_hash(item: DiscoveredFile) -> str:
    digest = hashlib.sha256()
    with item.path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


class KnowledgeCore:
    def __init__(self, config: AppConfig, embedder: Embedder, store: Any):
        self.config = config
        self.embedder = embedder
        self.store = store
        self._operation_lock = threading.RLock()
        self._initialized = False

    def _initialize_index(self) -> None:
        if self._initialized:
            return
        self.store.initialize(self.config.source_root, self.embedder.identity())
        self._initialized = True

    def _process_fingerprint(self, item: DiscoveredFile) -> str:
        return processing_fingerprint(
            item.parser,
            self.config.index.chunk_tokens,
            self.config.index.overlap_tokens,
            self.config.index.chunk_strategy,
        )

    def _needs_indexing(
        self,
        item: DiscoveredFile,
        entry: dict[str, Any] | None,
        retry_errors: bool,
    ) -> bool:
        if not entry:
            return True
        fingerprint = self._process_fingerprint(item)
        if entry.get("content_hash") != item.content_hash:
            return True
        if entry.get("processing_fingerprint") != fingerprint:
            return True
        state = entry.get("state")
        if state in {"pending_replace", "pending_delete"}:
            return True
        if state == "error":
            return retry_errors
        return state != "active"

    def _index_file(self, item: DiscoveredFile, entries: dict[str, dict[str, Any]]) -> None:
        process_fingerprint = self._process_fingerprint(item)
        previous = dict(entries.get(item.relative_path, {}))
        replacement_started = False
        try:
            content = read_stable_content(
                item, self.config.source_root, self.config.index.max_file_bytes
            )
            segments = parse_content(item.parser, content, self.config.index.max_pdf_pages)
            max_tokens = min(self.config.index.chunk_tokens, self.embedder.max_tokens)
            overlap = min(self.config.index.overlap_tokens, max(0, max_tokens - 1))
            chunks = chunk_segments(
                segments=segments,
                relative_path=item.relative_path,
                file_type=item.file_type,
                content_hash=item.content_hash,
                process_fingerprint=process_fingerprint,
                count_tokens=self.embedder.count_tokens,
                max_tokens=max_tokens,
                overlap_tokens=overlap,
                strategy=self.config.index.chunk_strategy,
            )
            embeddings = self.embedder.embed_documents([chunk.text for chunk in chunks])
            if _current_hash(item) != item.content_hash:
                raise RuntimeError(f"File changed while indexing: {item.relative_path}")

            pending = {
                "state": "pending_replace",
                "content_hash": item.content_hash,
                "processing_fingerprint": process_fingerprint,
                "file_type": item.file_type,
                "size": item.size,
                "modified_ns": item.modified_ns,
                "previous_indexed_at": previous.get("indexed_at"),
            }
            self.store.update_file(item.relative_path, pending)
            replacement_started = True
            self.store.replace_document(
                item.relative_path,
                chunks,
                embeddings,
                self.config.embedding.batch_size,
            )
            self.store.update_file(
                item.relative_path,
                {
                    "state": "active",
                    "content_hash": item.content_hash,
                    "processing_fingerprint": process_fingerprint,
                    "file_type": item.file_type,
                    "size": item.size,
                    "modified_ns": item.modified_ns,
                    "chunk_count": len(chunks),
                    "indexed_at": _utc_now(),
                },
            )
        except Exception as exc:
            if replacement_started:
                failed_entry = dict(self.store.file_entries().get(item.relative_path, {}))
                failed_entry["state"] = "pending_replace"
            elif previous.get("state") == "active":
                failed_entry = previous
            else:
                failed_entry = {
                    "state": "error",
                    "content_hash": item.content_hash,
                    "processing_fingerprint": process_fingerprint,
                    "file_type": item.file_type,
                    "size": item.size,
                    "modified_ns": item.modified_ns,
                }
            failed_entry["latest_error"] = str(exc)
            failed_entry["last_attempt_at"] = _utc_now()
            self.store.update_file(item.relative_path, failed_entry)
            raise

    def _remove_document(self, path: str, entry: dict[str, Any]) -> None:
        pending = dict(entry)
        pending["state"] = "pending_delete"
        self.store.update_file(path, pending)
        self.store.delete_document(path)
        self.store.remove_file_entry(path)

    def sync(
        self,
        max_files: int | None = None,
        *,
        retry_errors: bool = False,
    ) -> dict[str, Any]:
        if max_files is not None and max_files <= 0:
            raise ValueError("max_files must be positive")
        with self._operation_lock:
            discovery = discover_files(
                self.config.source_root,
                self.config.parsers,
                self.config.exclude,
                self.config.data_dir,
            )
            report = SyncReport(scan_complete=discovery.complete)
            if not discovery.complete:
                report.failed += len(discovery.errors)
                report.errors.update(
                    {f"scan:{index}": error for index, error in enumerate(discovery.errors, 1)}
                )
                return report.to_dict()

            self._initialize_index()
            entries = self.store.file_entries()
            candidates = [
                item
                for item in discovery.files
                if self._needs_indexing(item, entries.get(item.relative_path), retry_errors)
            ]
            candidates.sort(
                key=lambda item: (
                    entries.get(item.relative_path, {}).get("last_attempt_at", ""),
                    item.relative_path,
                )
            )
            limit = max_files or self.config.index.max_files_per_sync
            attempted = candidates[:limit]
            report.unchanged = len(discovery.files) - len(candidates)

            for item in attempted:
                try:
                    self._index_file(item, entries)
                    report.indexed += 1
                except Exception as exc:
                    report.failed += 1
                    report.errors[item.relative_path] = str(exc)

            discovered_paths = {item.relative_path for item in discovery.files}
            for path in sorted(set(entries) - discovered_paths):
                try:
                    self._remove_document(path, dict(entries[path]))
                    report.removed += 1
                except Exception as exc:
                    report.failed += 1
                    report.errors[path] = str(exc)

            report.remaining = max(0, len(candidates) - len(attempted))
            serialized = report.to_dict()
            self.store.record_sync(serialized, True)
            return serialized

    def search(
        self,
        query: str,
        limit: int = 8,
        folder: str | None = None,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        normalized_folder = _safe_relative_path(folder) if folder else None
        with self._operation_lock:
            self._initialize_index()
            embedding = self.embedder.embed_query(query)
            return [hit.to_dict() for hit in self.store.search(embedding, limit, normalized_folder)]

    def inspect(self, relative_path: str, max_chars: int = 8_000) -> dict[str, Any]:
        safe_path = _safe_relative_path(relative_path)
        if not 1 <= max_chars <= 100_000:
            raise ValueError("max_chars must be between 1 and 100000")
        with self._operation_lock:
            return self.store.inspect(safe_path, max_chars)

    def status(self) -> dict[str, Any]:
        with self._operation_lock:
            status = self.store.status()
            status.update(
                {
                    "source_root": str(self.config.source_root),
                    "source_root_exists": self.config.source_root.is_dir(),
                    "server_url": self.config.server.url,
                    "configured_model": self.config.embedding.model,
                }
            )
            return status
