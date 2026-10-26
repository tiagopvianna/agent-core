from __future__ import annotations

import fnmatch
import hashlib
import io
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path, PurePosixPath
from typing import Any

from knowledge_mcp.models import Chunk, DiscoveredFile, DiscoveryResult, Segment

PARSER_VERSIONS = {"text": 1, "markdown": 2, "pdf": 1, "docx": 1}
CHUNKER_VERSION = 2
HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+")
LIST_ITEM = re.compile(r"^ {0,3}(?:[-*+]|\d+[.)])[ \t]+", re.MULTILINE)
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

    return _text_blocks(Segment(text=text, start_line=1))


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


def parse_docx(content: bytes, _max_pdf_pages: int) -> list[Segment]:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    def blocks(container: Any) -> Iterable[Segment]:
        for block in container.iter_inner_content():
            if isinstance(block, Paragraph):
                text = block.text + "\n\n"
                style = block.style.name if block.style is not None else ""
                heading = re.fullmatch(r"Heading ([1-9])", style)
                properties = block._p.pPr
                is_list = (properties is not None and properties.numPr is not None) or (
                    style.startswith("List")
                )
                kind = "heading" if heading else "list" if is_list else "paragraph"
                yield Segment(
                    text=text,
                    kind=kind,
                    heading_level=int(heading[1]) if heading else None,
                )
            elif isinstance(block, Table):
                # Horizontal and vertical merges can expose the same cell repeatedly.
                seen: set[Any] = set()
                for row in block.rows:
                    cells: list[str] = []
                    for cell in row.cells:
                        if cell._tc not in seen:
                            seen.add(cell._tc)
                            cells.append("".join(item.text for item in blocks(cell)).rstrip())
                    yield Segment(text="\t".join(cells) + "\n", kind="table_row")

    try:
        segments = list(blocks(Document(io.BytesIO(content))))
    except Exception as exc:
        raise ValueError("DOCX could not be read") from exc
    # A DOCX list is a run of list paragraphs, not one chunk per item.
    grouped: list[Segment] = []
    for segment in segments:
        if not segment.text.strip():
            continue
        if segment.kind == "list" and grouped and grouped[-1].kind == "list":
            grouped[-1] = replace(grouped[-1], text=grouped[-1].text + segment.text)
        else:
            grouped.append(segment)
    return grouped


PARSERS: dict[str, Parser] = {
    "text": parse_text,
    "markdown": parse_markdown,
    "pdf": parse_pdf,
    "docx": parse_docx,
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
    strategy: str = "paragraph",
) -> str:
    raw = (
        f"parser={parser_name}:{PARSER_VERSIONS.get(parser_name, 0)};"
        f"chunk_tokens={chunk_tokens};overlap_tokens={overlap_tokens};"
        f"strategy={strategy};chunker={CHUNKER_VERSION}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _slice(segment: Segment, start: int, end: int, *, kind: str | None = None) -> Segment:
    text = segment.text[start:end]
    line = (
        segment.start_line + segment.text[:start].count("\n")
        if segment.start_line is not None
        else None
    )
    return replace(
        segment,
        text=text,
        start_line=line,
        end_line=line + text.rstrip("\r\n").count("\n") if line is not None else None,
        kind=kind or segment.kind,
    )


def _join(segments: list[Segment]) -> Segment:
    lines = [item.start_line for item in segments if item.start_line is not None]
    ends = [item.end_line for item in segments if item.end_line is not None]
    return replace(
        segments[0],
        text="".join(item.text for item in segments),
        start_line=min(lines) if lines else None,
        end_line=max(ends) if ends else None,
    )


def _text_blocks(segment: Segment) -> list[Segment]:
    """Recognize plain-text structure while retaining original character spans."""
    result: list[Segment] = []
    start = offset = 0
    kind = "paragraph"
    level = None
    fence: tuple[str, int] | None = None

    def flush(end: int) -> None:
        nonlocal start
        if end > start:
            part = _slice(segment, start, end, kind=kind)
            if part.text.strip():
                result.append(replace(part, heading_level=level))
            elif result:
                result[-1] = replace(result[-1], text=result[-1].text + part.text)
            start = end

    for line in segment.text.splitlines(keepends=True):
        end = offset + len(line)
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence:
            if (
                marker
                and marker[1][0] == fence[0]
                and len(marker[1]) >= fence[1]
                and not line[marker.end() :].strip()
            ):
                flush(end)
                fence = None
                kind, level = "paragraph", None
        elif marker:
            flush(offset)
            kind, level = "code", None
            fence = (marker[1][0], len(marker[1]))
        elif not line.strip():
            flush(end)
            kind, level = "paragraph", None
        else:
            heading = HEADING.match(line)
            if heading:
                flush(offset)
                kind, level = "heading", len(heading[1])
            elif kind == "heading" or (LIST_ITEM.match(line) and kind != "list"):
                flush(offset)
                kind, level = "list" if LIST_ITEM.match(line) else "paragraph", None
        offset = end
    flush(offset)
    return result


def _pack(
    segments: list[Segment],
    count_tokens: Callable[[str], int],
    budget: int,
) -> list[Segment]:
    result: list[Segment] = []
    current: list[Segment] = []
    for segment in segments:
        candidate = "".join(item.text for item in current) + segment.text
        if current and (segment.page != current[0].page or count_tokens(candidate) > budget):
            result.append(_join(current))
            current = []
        current.append(segment)
    if current:
        result.append(_join(current))
    return result


def _partition(segment: Segment, boundaries: list[int]) -> list[Segment]:
    points = sorted({0, *boundaries, len(segment.text)})
    return [_slice(segment, a, b) for a, b in zip(points, points[1:], strict=False) if b > a]


def _split_to_budget(
    segment: Segment,
    count_tokens: Callable[[str], int],
    budget: int,
    overlap_tokens: int,
) -> list[Segment]:
    """Last resort: bounded character spans, preferring whitespace cuts."""
    text = segment.text
    pieces: list[Segment] = []
    start = 0
    while start < len(text):
        if count_tokens(text[start:]) <= budget:
            pieces.append(_slice(segment, start, len(text)))
            break
        low, high, end = start + 1, len(text), start
        while low <= high:
            middle = (low + high) // 2
            if count_tokens(text[start:middle]) <= budget:
                end = middle
                low = middle + 1
            else:
                high = middle - 1
        if end == start:
            raise ValueError("Token budget cannot fit a text fragment including special tokens")
        # Verify candidate boundaries: token counts need not grow monotonically.
        for match in reversed(list(re.finditer(r"\s+", text[start:end]))):
            boundary = start + match.end()
            if boundary > start and count_tokens(text[start:boundary]) <= budget:
                end = boundary
                break
        if count_tokens(text[start:end]) > budget:
            raise ValueError("Unable to split text within the token budget")
        pieces.append(_slice(segment, start, end))
        next_start = end
        if overlap_tokens > 0 and end < len(text):
            # Only reuse a suffix if the next chunk can also consume new text.
            for candidate in range(end - 1, start, -1):
                if count_tokens(text[candidate:end]) > overlap_tokens:
                    break
                if count_tokens(text[candidate : end + 1]) <= budget:
                    next_start = candidate
        start = next_start
    return pieces


def _split_block(
    segment: Segment,
    count_tokens: Callable[[str], int],
    budget: int,
    overlap: int,
) -> list[Segment]:
    if count_tokens(segment.text) <= budget:
        return [segment]
    if segment.kind == "list":
        boundaries = [m.start() for m in LIST_ITEM.finditer(segment.text)]
        # DOCX list paragraphs are separated by blank lines, without rendered markers.
        boundaries += [m.end() for m in re.finditer(r"\n[ \t]*\n", segment.text)]
        items = _partition(segment, boundaries)
        if len(items) > 1:
            return _pack(
                [
                    piece
                    for item in items
                    for piece in _split_block(
                        replace(item, kind="paragraph"), count_tokens, budget, overlap
                    )
                ],
                count_tokens,
                budget,
            )
    pattern = r"\n" if segment.kind in {"code", "table_row"} else r"(?<=[.!?])[ \t]+|\r?\n"
    parts = _partition(segment, [m.end() for m in re.finditer(pattern, segment.text)])
    pieces: list[Segment] = []
    for part in parts:
        if count_tokens(part.text) <= budget:
            pieces.append(part)
        else:
            pieces.extend(_split_to_budget(part, count_tokens, budget, overlap))
    return _pack(pieces, count_tokens, budget)


def _paragraph_units(blocks: list[Segment]) -> list[list[Segment]]:
    units: list[list[Segment]] = []
    pending: list[Segment] = []
    for block in blocks:
        if pending and pending[0].page != block.page:
            units.append(pending)
            pending = []
        if block.kind == "heading":
            pending.append(block)
        else:
            units.append([*pending, block])
            pending = []
    if pending:
        units.append(pending)
    return units


def _section_units(units: list[list[Segment]]) -> list[list[list[Segment]]]:
    sections: list[list[list[Segment]]] = []
    current: list[list[Segment]] = []
    for unit in units:
        if current and (unit[0].kind == "heading" or unit[0].page != current[0][0].page):
            sections.append(current)
            current = []
        if unit[0].kind == "heading" or current:
            current.append(unit)
        else:
            sections.append([unit])
    if current:
        sections.append(current)
    return sections


def chunk_segments(
    segments: list[Segment],
    relative_path: str,
    file_type: str,
    content_hash: str,
    process_fingerprint: str,
    count_tokens: Callable[[str], int],
    max_tokens: int,
    overlap_tokens: int,
    strategy: str = "paragraph",
) -> list[Chunk]:
    if strategy not in {"paragraph", "section", "packed"}:
        raise ValueError("Unknown chunk strategy")
    if max_tokens <= 0 or overlap_tokens < 0:
        raise ValueError("Token budget must be positive and overlap non-negative")
    blocks = [
        block
        for segment in segments
        for block in (_text_blocks(segment) if segment.kind == "text" else [segment])
        if block.text.strip()
    ]
    units = _paragraph_units(blocks)
    sections = _section_units(units) if strategy == "section" else [[unit] for unit in units]
    fitted: list[Segment] = []
    for section in sections:
        combined = _join([block for unit in section for block in unit])
        if count_tokens(combined.text) <= max_tokens:
            fitted.append(combined)
            continue
        for unit in section:
            combined = _join(unit)
            if count_tokens(combined.text) <= max_tokens:
                fitted.append(combined)
            else:
                fitted.extend(
                    _pack(
                        [
                            piece
                            for block in unit
                            for piece in _split_block(
                                block, count_tokens, max_tokens, overlap_tokens
                            )
                        ],
                        count_tokens,
                        max_tokens,
                    )
                )
    if strategy == "packed":
        fitted = _pack(fitted, count_tokens, max_tokens)

    folder = str(PurePosixPath(relative_path).parent)
    if folder == ".":
        folder = ""
    chunks: list[Chunk] = []
    for ordinal, segment in enumerate(fitted):
        text = segment.text
        if not text.strip():
            continue
        if count_tokens(text) > max_tokens:
            raise ValueError("Chunk exceeds the effective model token limit")
        raw_id = f"{relative_path}:{content_hash}:{process_fingerprint}:{ordinal}"
        chunk_id = hashlib.sha256(raw_id.encode("utf-8")).hexdigest()
        metadata: dict[str, str | int | float | bool] = {
            "path": relative_path,
            "file_type": file_type,
            "folder": folder,
            "content_hash": content_hash,
            "processing_fingerprint": process_fingerprint,
            "chunk_index": ordinal,
        }
        if segment.page is not None:
            metadata["page"] = segment.page
        if segment.start_line is not None:
            metadata["start_line"] = segment.start_line
        if segment.end_line is not None:
            metadata["end_line"] = segment.end_line
        chunks.append(Chunk(id=chunk_id, text=text, metadata=metadata))
    return chunks
