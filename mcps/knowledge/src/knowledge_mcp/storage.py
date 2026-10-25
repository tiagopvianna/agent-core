from __future__ import annotations

import fcntl
import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from knowledge_mcp.models import Chunk, SearchHit

SCHEMA_VERSION = 1
COLLECTION_NAME = "knowledge"
DISTANCE_METRIC = "cosine"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


class DataDirectoryLock:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.path = data_dir / "owner.lock"
        self._file: Any = None

    def acquire(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._file.close()
            self._file = None
            raise RuntimeError(
                f"Another knowledge server already owns data directory: {self.data_dir}"
            ) from exc
        self._file.seek(0)
        self._file.truncate()
        self._file.write(f"pid={os.getpid()}\n")
        self._file.flush()

    def release(self) -> None:
        if self._file is None:
            return
        fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
        self._file.close()
        self._file = None

    def __enter__(self) -> DataDirectoryLock:
        self.acquire()
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


class ChromaStore:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.chroma_dir = data_dir / "chroma"
        self.manifest_path = data_dir / "manifest.json"
        self._client: Any = None
        self._collection: Any = None
        self._manifest: dict[str, Any] | None = None
        self._lock = threading.RLock()

    def _get_collection(self) -> Any:
        if self._collection is None:
            import chromadb

            self.chroma_dir.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(self.chroma_dir))
            self._collection = self._client.get_or_create_collection(
                COLLECTION_NAME,
                metadata={"hnsw:space": DISTANCE_METRIC},
            )
        return self._collection

    def _read_manifest(self) -> dict[str, Any] | None:
        if not self.manifest_path.exists():
            return None
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(
                f"Manifest is unreadable: {self.manifest_path}; restore it or rebuild the index"
            ) from exc
        if not isinstance(value, dict) or not isinstance(value.get("files", {}), dict):
            raise RuntimeError(
                f"Manifest has an invalid structure: {self.manifest_path}; rebuild the index"
            )
        return value

    def _write_manifest(self) -> None:
        if self._manifest is None:
            raise RuntimeError("Store is not initialized")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_name(f".{self.manifest_path.name}.{os.getpid()}.tmp")
        serialized = json.dumps(self._manifest, indent=2, sort_keys=True)
        try:
            with temporary.open("w", encoding="utf-8") as target:
                target.write(serialized)
                target.write("\n")
                target.flush()
                os.fsync(target.fileno())
            os.replace(temporary, self.manifest_path)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _canonical(value: Any) -> str:
        return json.dumps(value, sort_keys=True, separators=(",", ":"))

    def initialize(self, source_root: Path, embedding_fingerprint: dict[str, Any]) -> None:
        with self._lock:
            collection = self._get_collection()
            manifest = self._read_manifest()
            if manifest is None:
                if collection.count() > 0:
                    raise RuntimeError(
                        "Vector store contains data but manifest.json is missing; "
                        "use a new data_dir or rebuild this one"
                    )
                self._manifest = {
                    "schema_version": SCHEMA_VERSION,
                    "source_root": str(source_root.resolve()),
                    "embedding_fingerprint": embedding_fingerprint,
                    "files": {},
                    "last_complete_scan_at": None,
                    "last_sync": None,
                }
                self._write_manifest()
                return
            if manifest.get("schema_version") != SCHEMA_VERSION:
                raise RuntimeError("Index schema is incompatible; rebuild into a new data_dir")
            if manifest.get("source_root") != str(source_root.resolve()):
                raise RuntimeError(
                    "Configured source_root differs from the root recorded by this index; "
                    "use a new data_dir"
                )
            actual = manifest.get("embedding_fingerprint")
            if self._canonical(actual) != self._canonical(embedding_fingerprint):
                raise RuntimeError(
                    "Embedding configuration differs from this index; rebuild into a new data_dir"
                )
            self._manifest = manifest

    def load_existing(self) -> None:
        with self._lock:
            manifest = self._read_manifest()
            collection = self._get_collection()
            if manifest is None:
                if collection.count() > 0:
                    raise RuntimeError(
                        "Vector store contains data but manifest.json is missing; rebuild the index"
                    )
                return
            self._manifest = manifest

    def manifest(self) -> dict[str, Any]:
        with self._lock:
            if self._manifest is None:
                self.load_existing()
            return self._manifest or {
                "schema_version": SCHEMA_VERSION,
                "files": {},
                "last_complete_scan_at": None,
                "last_sync": None,
            }

    def file_entries(self) -> dict[str, dict[str, Any]]:
        return self.manifest().setdefault("files", {})

    def update_file(self, path: str, entry: dict[str, Any]) -> None:
        with self._lock:
            self.file_entries()[path] = entry
            self._write_manifest()

    def remove_file_entry(self, path: str) -> None:
        with self._lock:
            self.file_entries().pop(path, None)
            self._write_manifest()

    def record_sync(self, report: dict[str, Any], complete_scan: bool) -> None:
        with self._lock:
            manifest = self.manifest()
            manifest["last_sync"] = {"at": utc_now(), **report}
            if complete_scan:
                manifest["last_complete_scan_at"] = utc_now()
            self._write_manifest()

    def replace_document(
        self,
        path: str,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        batch_size: int,
    ) -> None:
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk and embedding counts differ")
        collection = self._get_collection()
        collection.delete(where={"path": path})
        for start in range(0, len(chunks), batch_size):
            batch_chunks = chunks[start : start + batch_size]
            batch_embeddings = embeddings[start : start + batch_size]
            collection.add(
                ids=[chunk.id for chunk in batch_chunks],
                documents=[chunk.text for chunk in batch_chunks],
                metadatas=[chunk.metadata for chunk in batch_chunks],
                embeddings=batch_embeddings,
            )

    def delete_document(self, path: str) -> None:
        self._get_collection().delete(where={"path": path})

    @staticmethod
    def _in_folder(path: str, folder: str | None) -> bool:
        if not folder:
            return True
        normalized = PurePosixPath(folder).as_posix().strip("/")
        if normalized in {"", "."}:
            return True
        return path.startswith(f"{normalized}/")

    def search(
        self,
        query_embedding: list[float],
        limit: int,
        folder: str | None = None,
    ) -> list[SearchHit]:
        collection = self._get_collection()
        count = collection.count()
        if count == 0:
            return []
        result = collection.query(
            query_embeddings=[query_embedding],
            n_results=count,
            include=["documents", "metadatas", "distances"],
        )
        documents = result.get("documents", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        files = self.file_entries()
        hits: list[SearchHit] = []
        for chunk_id, document, metadata, distance in zip(
            result.get("ids", [[]])[0], documents, metadatas, distances, strict=True
        ):
            path = str(metadata.get("path", ""))
            entry = files.get(path, {})
            if entry.get("state") != "active" or not self._in_folder(path, folder):
                continue
            hits.append(
                SearchHit(
                    path=path,
                    file_type=str(metadata.get("file_type", "")),
                    snippet=str(document)[:500],
                    distance=float(distance),
                    metric=DISTANCE_METRIC,
                    indexed_at=entry.get("indexed_at"),
                    page=int(metadata["page"]) if "page" in metadata else None,
                    start_line=(int(metadata["start_line"]) if "start_line" in metadata else None),
                    end_line=int(metadata["end_line"]) if "end_line" in metadata else None,
                    chunk_id=chunk_id,
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def inspect(self, path: str, max_chars: int = 8_000) -> dict[str, Any]:
        entry = self.file_entries().get(path)
        if not entry or entry.get("state") != "active":
            raise FileNotFoundError(f"Indexed document not found: {path}")
        result = self._get_collection().get(
            where={"path": path}, include=["documents", "metadatas"]
        )
        records = sorted(
            zip(
                result.get("documents", []),
                result.get("metadatas", []),
                strict=True,
            ),
            key=lambda pair: int((pair[1] or {}).get("chunk_index", 0)),
        )
        chunks: list[dict[str, Any]] = []
        used = 0
        truncated = False
        for document, metadata in records:
            remaining = max_chars - used
            if remaining <= 0:
                truncated = True
                break
            text = str(document)
            if len(text) > remaining:
                text = text[:remaining]
                truncated = True
            chunks.append({"text": text, "metadata": metadata or {}})
            used += len(text)
            if truncated:
                break
        return {"path": path, "manifest": entry, "chunks": chunks, "truncated": truncated}

    def status(self) -> dict[str, Any]:
        manifest = self.manifest()
        files = manifest.get("files", {})
        states: dict[str, int] = {}
        for entry in files.values():
            state = str(entry.get("state", "unknown"))
            states[state] = states.get(state, 0) + 1
        return {
            "data_dir": str(self.data_dir),
            "manifest_exists": self.manifest_path.exists(),
            "indexed_files": states.get("active", 0),
            "file_states": states,
            "indexed_chunks": self._get_collection().count(),
            "last_complete_scan_at": manifest.get("last_complete_scan_at"),
            "last_sync": manifest.get("last_sync"),
            "embedding_fingerprint": manifest.get("embedding_fingerprint"),
        }
