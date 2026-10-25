from __future__ import annotations

import fnmatch
import hashlib
import io
import os
import re
from collections.abc import Callable, Iterable
from pathlib import Path, PurePosixPath

from knowledge_mcp.models import Chunk, DiscoveredFile, DiscoveryResult, Segment

PARSER_VERSIONS = {"text": 1, "markdown": 1, "pdf": 1}
Parser = Callable[[bytes, int], list[Segment]]


def _is_hidden(relative_path: str) -> bool:
    return any(part.startswith(".") for part in PurePosixPath(relative_path).parts)


def _matches_any(relative_path: str, patterns: Iterable[str]) -> bool:
    path = relative_path.strip("/")
    candidates = (path, f"/{path}", f"{path}/")
    return any(
        fnmatch.fnmatch(candidate, pattern) for pattern in patterns for candidate in candidates
    )


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def discover_files(
    root: Path,
    parser_mapping: dict[str, str],
    exclude: Iterable[str],
    data_dir: Path | None = None,
) -> DiscoveryResult:
    canonical_root = root.resolve()
    if not canonical_root.exists():
        return DiscoveryResult([], False, [f"Source root does not exist: {canonical_root}"])
    if not canonical_root.is_dir():
        return DiscoveryResult([], False, [f"Source root is not a directory: {canonical_root}"])

    canonical_data = data_dir.resolve() if data_dir else None
    files: list[DiscoveredFile] = []
    errors: list[str] = []

    def on_error(error: OSError) -> None:
        errors.append(f"Cannot scan {error.filename}: {error.strerror}")

    try:
        for directory, dirnames, filenames in os.walk(
            canonical_root, followlinks=False, onerror=on_error
        ):
            directory_path = Path(directory)
            kept_directories: list[str] = []
            for dirname in dirnames:
                candidate = directory_path / dirname
                relative = candidate.relative_to(canonical_root).as_posix()
                if (
                    candidate.is_symlink()
                    or _is_hidden(relative)
                    or _matches_any(relative, exclude)
                ):
                    continue
                if canonical_data and _inside(candidate.resolve(), canonical_data):
                    continue
                kept_directories.append(dirname)
            dirnames[:] = kept_directories

            for filename in filenames:
                candidate = directory_path / filename
                try:
                    if candidate.is_symlink() or not candidate.is_file():
                        continue
                    relative = candidate.relative_to(canonical_root).as_posix()
                    if _is_hidden(relative) or _matches_any(relative, exclude):
                        continue
                    parser = parser_mapping.get(candidate.suffix.lower())
                    if not parser:
                        continue
                    resolved = candidate.resolve(strict=True)
                    if not _inside(resolved, canonical_root):
                        errors.append(f"Path escaped source root and was skipped: {relative}")
                        continue
                    stat_before = resolved.stat()
                    digest = hashlib.sha256()
                    with resolved.open("rb") as source:
                        for block in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(block)
                    stat_after = resolved.stat()
                    if (
                        stat_before.st_size != stat_after.st_size
                        or stat_before.st_mtime_ns != stat_after.st_mtime_ns
                    ):
                        errors.append(f"File changed while scanning and was skipped: {relative}")
                        continue
                    files.append(
                        DiscoveredFile(
                            path=resolved,
                            relative_path=relative,
                            parser=parser,
                            file_type=candidate.suffix.lower().lstrip("."),
                            content_hash=digest.hexdigest(),
                            size=stat_after.st_size,
                            modified_ns=stat_after.st_mtime_ns,
                        )
                    )
                except OSError as exc:
                    errors.append(f"Cannot read {candidate}: {exc}")
    except OSError as exc:
        errors.append(f"Cannot scan {canonical_root}: {exc}")

    return DiscoveryResult(sorted(files, key=lambda item: item.relative_path), not errors, errors)


def read_stable_content(item: DiscoveredFile, root: Path, max_bytes: int) -> bytes:
    canonical_root = root.resolve()
    resolved = item.path.resolve(strict=True)
    if not _inside(resolved, canonical_root):
        raise ValueError(f"Path outside source root: {item.relative_path}")
    stat_before = resolved.stat()
    if stat_before.st_size > max_bytes:
        raise ValueError(
            f"File exceeds max_file_bytes ({stat_before.st_size} > {max_bytes}): "
            f"{item.relative_path}"
        )
    content = resolved.read_bytes()
    stat_after = resolved.stat()
    digest = hashlib.sha256(content).hexdigest()
    if (
        stat_before.st_size != stat_after.st_size
        or stat_before.st_mtime_ns != stat_after.st_mtime_ns
        or digest != item.content_hash
    ):
        raise RuntimeError(f"File changed while indexing: {item.relative_path}")
    return content


def parse_text(content: bytes, _max_pdf_pages: int) -> list[Segment]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Text file is not valid UTF-8") from exc
    if not text:
        return []
    line_count = text.count("\n") + 1
    return [Segment(text=text, start_line=1, end_line=line_count)]


def parse_markdown(content: bytes, _max_pdf_pages: int) -> list[Segment]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("Markdown file is not valid UTF-8") from exc
    if not text:
        return []

    lines = text.splitlines(keepends=True)
    segments: list[Segment] = []
    start = 0
    buffer: list[str] = []
    for line_number, line in enumerate(lines, start=1):
        is_heading = bool(re.match(r"^#{1,6}\s+", line))
        is_blank = not line.strip()
        if is_heading and buffer:
            segments.append(Segment("".join(buffer), start_line=start, end_line=line_number - 1))
            buffer = []
        if not buffer:
            start = line_number
        buffer.append(line)
        if is_blank and "".join(buffer).strip():
            segments.append(Segment("".join(buffer), start_line=start, end_line=line_number))
            buffer = []
    if buffer and "".join(buffer).strip():
        segments.append(Segment("".join(buffer), start_line=start, end_line=len(lines)))
    return segments


def parse_pdf(content: bytes, max_pdf_pages: int) -> list[Segment]:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as exc:
            raise ValueError("Encrypted PDF cannot be read") from exc
    total_pages = len(reader.pages)
    if total_pages > max_pdf_pages:
        raise ValueError(
            f"PDF has {total_pages} pages, above max_pdf_pages={max_pdf_pages}; "
            "increase the limit to index it completely"
        )
    segments: list[Segment] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            segments.append(Segment(text=text, page=page_number))
    if total_pages and not segments:
        raise ValueError("PDF contains no extractable text; OCR is required")
    return segments


PARSERS: dict[str, Parser] = {
    "text": parse_text,
    "markdown": parse_markdown,
    "pdf": parse_pdf,
}


def parse_content(parser_name: str, content: bytes, max_pdf_pages: int) -> list[Segment]:
    try:
        parser = PARSERS[parser_name]
    except KeyError as exc:
        raise ValueError(f"Unknown parser: {parser_name}") from exc
    return parser(content, max_pdf_pages)


def processing_fingerprint(
    parser_name: str,
    chunk_tokens: int,
    overlap_tokens: int,
) -> str:
    raw = (
        f"parser={parser_name}:{PARSER_VERSIONS.get(parser_name, 0)};"
        f"chunk_tokens={chunk_tokens};overlap_tokens={overlap_tokens}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _split_to_budget(
    segment: Segment,
    count_tokens: Callable[[str], int],
    budget: int,
    overlap_tokens: int,
) -> list[Segment]:
    text = segment.text
    if not text or count_tokens(text) <= budget:
        return [segment] if text else []

    pieces: list[Segment] = []
    start = 0
    while start < len(text):
        low = start + 1
        high = len(text)
        best = low
        while low <= high:
            middle = (low + high) // 2
            if count_tokens(text[start:middle]) <= budget:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        end = best
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind(" ", start, end))
            if boundary > start + max(16, (end - start) // 2):
                end = boundary + 1
        piece = text[start:end]
        start_line = (
            segment.start_line + text[:start].count("\n")
            if segment.start_line is not None
            else None
        )
        end_line = start_line + piece.count("\n") if start_line is not None else segment.end_line
        pieces.append(
            Segment(
                text=piece,
                page=segment.page,
                start_line=start_line,
                end_line=end_line,
            )
        )
        if end >= len(text):
            break
        if overlap_tokens <= 0:
            start = end
            continue
        overlap_start = end
        while overlap_start > start:
            candidate = max(start, overlap_start - 64)
            if count_tokens(text[candidate:end]) > overlap_tokens:
                break
            overlap_start = candidate
        if overlap_start == end:
            overlap_start = max(start, end - 1)
        start = overlap_start
    return pieces


def chunk_segments(
    segments: list[Segment],
    relative_path: str,
    file_type: str,
    content_hash: str,
    process_fingerprint: str,
    count_tokens: Callable[[str], int],
    max_tokens: int,
    overlap_tokens: int,
) -> list[Chunk]:
    expanded: list[Segment] = []
    for segment in segments:
        expanded.extend(_split_to_budget(segment, count_tokens, max_tokens, overlap_tokens))

    groups: list[list[Segment]] = []
    current: list[Segment] = []
    for segment in expanded:
        candidate_text = "".join(item.text for item in [*current, segment])
        if current and count_tokens(candidate_text) > max_tokens:
            groups.append(current)
            current = []
        current.append(segment)
    if current:
        groups.append(current)

    folder = str(PurePosixPath(relative_path).parent)
    if folder == ".":
        folder = ""
    chunks: list[Chunk] = []
    for ordinal, group in enumerate(groups):
        text = "".join(item.text for item in group)
        if not text.strip():
            continue
        raw_id = f"{relative_path}:{content_hash}:{process_fingerprint}:{ordinal}"
        chunk_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        pages = {item.page for item in group if item.page is not None}
        start_lines = [item.start_line for item in group if item.start_line is not None]
        end_lines = [item.end_line for item in group if item.end_line is not None]
        metadata: dict[str, str | int | float | bool] = {
            "path": relative_path,
            "file_type": file_type,
            "folder": folder,
            "content_hash": content_hash,
            "processing_fingerprint": process_fingerprint,
            "chunk_index": ordinal,
        }
        if len(pages) == 1:
            metadata["page"] = next(iter(pages))
        if start_lines:
            metadata["start_line"] = min(start_lines)
        if end_lines:
            metadata["end_line"] = max(end_lines)
        chunks.append(Chunk(id=chunk_id, text=text, metadata=metadata))
    return chunks
