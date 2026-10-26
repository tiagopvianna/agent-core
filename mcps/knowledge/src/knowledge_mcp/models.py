from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Segment:
    text: str
    page: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    kind: str = "text"
    heading_level: int | None = None


@dataclass(frozen=True)
class Chunk:
    id: str
    text: str
    metadata: dict[str, str | int | float | bool]


@dataclass(frozen=True)
class DiscoveredFile:
    path: Path
    relative_path: str
    parser: str
    file_type: str
    content_hash: str
    size: int
    modified_ns: int


@dataclass(frozen=True)
class DiscoveryResult:
    files: list[DiscoveredFile]
    complete: bool
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SearchHit:
    path: str
    file_type: str
    snippet: str
    distance: float
    metric: str
    indexed_at: str | None
    page: int | None = None
    start_line: int | None = None
    end_line: int | None = None
    chunk_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SyncReport:
    indexed: int = 0
    unchanged: int = 0
    removed: int = 0
    failed: int = 0
    remaining: int = 0
    errors: dict[str, str] = field(default_factory=dict)
    scan_complete: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
