# Developing Knowledge MCP

## Data flow and module boundaries

```text
configured root
    -> ingest.discover_files()
    -> parser selected by extension
    -> structural units (headings, paragraphs, lists, fenced code, table rows)
    -> strategy-aware, token-bounded chunk_segments()
    -> Embedder.embed_documents()
    -> ChromaStore + atomic JSON manifest

query
    -> Embedder.embed_query()
    -> ChromaStore.search()
    -> active matches with source locations
```

`models.py` holds the few values shared across boundaries. `config.py` parses and validates TOML. `ingest.py` owns filesystem discovery, parsers, processing fingerprints, and chunking. `embeddings.py` owns the small embedding contract and Sentence Transformers adapter. `storage.py` owns all Chroma and manifest details. `core.py` orchestrates use cases without importing vendor libraries. `server.py` owns process lifetime, authentication, polling, and MCP tools. `cli.py` is an MCP client except for its `serve` command.

Keep these boundaries while the project is small. Add a new module or subpackage only when a file develops multiple independent responsibilities or gains several implementations.

## Adding a file format

For a UTF-8 format that needs no structure-aware parsing, only add an extension mapping to configuration:

```toml
[parsers]
".rst" = "text"
```

DOCX is implemented with `python-docx`. For another structured format:

1. Add a parser function in `ingest.py` with the same signature as `parse_pdf`.
2. Return `Segment` values with source locations when the format provides them. Use `kind` (`text`, `heading`, `paragraph`, `list`, `code`, or `table_row`) and optional `heading_level` for explicit structure. Raw `text` segments receive shared plain-text boundary detection. DOCX intentionally has no synthetic page or line locations.
3. Register the function in `PARSERS` and give it a version in `PARSER_VERSIONS`.
4. Permit its name in `config.validate_config`.
5. Add fixtures for empty, malformed, oversized, and representative files.

Increasing a parser version changes that file type's processing fingerprint, so existing matching files are reindexed. `core.py`, MCP tools, and storage should not change.

## Chunking contract

`index.chunk_strategy` selects `paragraph` (default), `section`, or `packed` globally. `core.py` passes the strategy and effective model token ceiling into ingestion; it does not own boundary heuristics. Keep splitting helpers in `ingest.py` while this remains one pipeline.

The chunker preserves independent paragraph/list units, optionally keeps whole sections, or packs neighboring units. It subdivides oversized units at progressively smaller boundaries and applies overlap only to forced budget cuts. It preserves content order and actual source locations, never combines PDF pages, and verifies every emitted chunk with the supplied token counter, including special tokens. It raises a clear error instead of emitting a fragment that cannot fit. Existing core recovery handles that file failure before vector replacement.

`processing_fingerprint()` includes parser version, chunker version, strategy, token budget, and overlap. Increment `CHUNKER_VERSION` whenever boundary semantics change; this triggers batched reindexing in the existing data directory. Strategy changes do not change the embedding identity. Config is read at server startup, not reloaded live.

Use deterministic counters in unit tests for budget and preservation assertions. Use the actual cached tokenizer for an optional smoke test without downloading a model. Retrieval quality requires representative searches, rather than assuming a structural strategy is always better.

## Adding or changing an embedder

Implement the `Embedder` protocol in `embeddings.py`:

- `embed_documents()` and `embed_query()` keep retrieval-specific behavior separate.
- `count_tokens()` and `max_tokens` let ingestion enforce the real model limit.
- `identity()` returns every setting that affects vector compatibility, including provider, model/revision, dimension, normalization, prompts, and token limit.

Register the constructor in `EMBEDDER_FACTORIES`. A changed embedding identity must use a new `data_dir`; this prevents queries from mixing incompatible vectors. Evaluate representative searches before switching configuration.

## Storage and recovery contract

`KnowledgeCore` expects its store to initialize against a source root and embedding identity, expose mutable per-file manifest entries, replace/delete one document's vectors, search active files, inspect one document, and report status. Chroma-specific result shapes stay inside `storage.py`.

Replacement follows a small recovery protocol:

1. Parsing and embedding finish before stored vectors change.
2. The manifest atomically marks the file `pending_replace`.
3. The store replaces the vectors.
4. The manifest atomically marks the file `active`.

Search excludes pending files. A stopped process may temporarily hide one document, but the next synchronization rebuilds it. Deletion similarly uses `pending_delete`. Never infer deletions after an incomplete scan.

The JSON manifest is intentionally simple. Replace it with SQLite inside `storage.py` only after measurements show manifest size or write costs are a problem.

## Testing

Most core tests use deterministic fake embeddings and an in-memory store. Storage tests use a temporary real Chroma database. The real Sentence Transformers model is a manual smoke test because it may require an initial download and is slower than unit tests.

```sh
uv sync --locked --group dev
uv run --group dev ./check.sh

# Real-model smoke test after configuring a disposable data_dir:
uv run knowledge --config config.local.toml serve
uv run knowledge --config config.local.toml index
uv run knowledge --config config.local.toml search "a phrase from a test document"
```

`check.sh` runs Ruff, bytecode compilation, and the standard-library unittest suite.

### Validation snapshot

On 2026-10-25, the initial implementation rebuilt a temporary index from the existing two-PDF corpus (96 pages total) without changing the old MCP or its data. It produced 196 chunks in 10.1 seconds with the cached MiniLM model. Warm searches took about 0.012 seconds: “Open Dental API credentials” returned `open_dental_spec.pdf`, and “Cloud 9 API appointment” returned `cloud-9-documentation-api.pdf`. These are a local smoke-test record, not a performance guarantee.

## Small Python client

The CLI is the supported scripting interface, especially with `--json`. A Python integration can use the same MCP client primitives:

```python
import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    token = "read from the configured token file"
    async with httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"}
    ) as client:
        async with streamable_http_client(
            "http://127.0.0.1:8765/mcp", http_client=client
        ) as (read, write, _session_id):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool("search", {"query": "payment retries"})
                print(result.structuredContent)


anyio.run(main)
```
