# Knowledge MCP

Knowledge MCP is a local semantic-search service for personal files. It recursively indexes configured Markdown, text, and text-bearing PDF files, stores vectors in ChromaDB, and returns passages with their source paths and page or line locations. It provides retrieval only; an agent may use retrieved passages as context, but answer generation is outside this service.

The service keeps one embedding model and one database writer in a shared local process. Agents and the included CLI call that process through MCP Streamable HTTP.

## Quick start

Requirements: Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```sh
cd mcps/knowledge
cp config.example.toml config.local.toml
uv sync --locked --group dev
```

Keep `config.local.toml` beside `config.example.toml` and edit these paths before starting the service:

```toml
source_root = "~/Documents/knowledge"
data_dir = "~/.local/share/knowledge-mcp"
```

- `source_root` is the folder containing the files to search. It is scanned recursively, so files may be organized in any number of subfolders.
- `data_dir` contains the persistent ChromaDB index, manifest, and process lock. Keep it outside `source_root` and outside Git.
- `server.token_file` is optional. When omitted, the token is stored at `<data_dir>/access-token`; with the example paths, that is `~/.local/share/knowledge-mcp/access-token`.

Create the source folder if necessary, then start the service:

```sh
mkdir -p ~/Documents/knowledge
uv run knowledge --config config.local.toml serve
```

Keep this terminal running. On startup the server creates the data directory and bearer token, loads the embedding model, performs an initial synchronization, and then checks for changes every `server.poll_interval_seconds` (30 seconds in the example). The first start downloads the configured Sentence Transformers model if it is not cached; later embeddings run locally.

Stop the server with `Ctrl-C`. Vectors and indexing state remain on disk in `data_dir`, so restarting the same configuration reuses the existing index and synchronizes changes made while the server was stopped.

## Standalone CLI operations

The CLI is an MCP client, not a second database process. Keep `serve` running and execute these commands from another terminal in `mcps/knowledge/`:

```sh
uv run knowledge --config config.local.toml status
uv run knowledge --config config.local.toml index
uv run knowledge --config config.local.toml search "how do payment retries work?"
uv run knowledge --config config.local.toml search "how do payment retries work?" --folder apis --limit 5
uv run knowledge --config config.local.toml inspect apis/payments.md
```

Available operations:

| Command | Purpose | Useful options |
| --- | --- | --- |
| `serve` | Run the shared MCP server and automatic indexing poller. | None; stop with `Ctrl-C`. |
| `status` | Show source/index paths, file states, counts, and the latest synchronization. | `--json` |
| `index` | Immediately synchronize new, changed, or deleted files instead of waiting for the poller. It continues requesting bounded batches until current work is complete. | `--max-files N`, `--json` |
| `search "query"` | Return semantically similar passages with source paths and page or line locations. | `--folder RELATIVE_FOLDER`, `--limit N`, `--json` |
| `inspect RELATIVE_PATH` | Return indexed chunks and metadata for one file whose path is relative to `source_root`. | `--max-chars N`, `--json` |

The global `--config` option must appear before the operation name. Add `--json` after a non-server operation for compact, script-friendly output.

To install the command outside the checkout, run `uv tool install .` from `mcps/knowledge/`, then use an absolute configuration path:

```sh
knowledge --config /absolute/path/to/config.local.toml search "your query"
```

## Files and configuration

Subfolders under `source_root` are organizational metadata, so structures such as `apis/`, `work/`, `commands/`, and `projects/` need no schema changes. The default parsers support `.md`, `.txt`, and `.pdf`. To index a code or configuration format as plain UTF-8 text, map it explicitly:

```toml
[parsers]
".md" = "markdown"
".txt" = "text"
".pdf" = "pdf"
".py" = "text"
".sh" = "text"
```

Hidden folders, symlinks, dependencies, virtual environments, and configured exclusions are skipped. PDFs are indexed completely up to `max_pdf_pages`; files above the limit fail visibly instead of being marked partially complete. Image-only PDFs require OCR before ingestion.

`data_dir` contains ChromaDB, `manifest.json`, and a process lock. Keep it outside the source folder and out of Git. The manifest records file hashes and indexing state. Unchanged files are not re-embedded, removed files are removed from search, and interrupted replacements are hidden and retried on a later synchronization.

The server polls at `server.poll_interval_seconds`. A failed file is reported and does not prevent later files from being processed; automatic polling retries it later.

## Connect agents

The default endpoint is `http://127.0.0.1:8765/mcp`. Start the server first, then open another terminal and load its token into the environment before launching Codex. With the example configuration:

```sh
export KNOWLEDGE_MCP_TOKEN="$(tr -d '\n' < ~/.local/share/knowledge-mcp/access-token)"
codex mcp add knowledge \
  --url http://127.0.0.1:8765/mcp \
  --bearer-token-env-var KNOWLEDGE_MCP_TOKEN
codex
```

Registration is normally needed only once, but the environment variable must be present whenever Codex starts. A representative prompt is: `Use the knowledge MCP to search my indexed files and answer this question with source paths: <question>`.

Claude Code accepts the same endpoint with an authorization header:

```sh
claude mcp add --transport http --scope user knowledge \
  http://127.0.0.1:8765/mcp \
  --header "Authorization: Bearer $KNOWLEDGE_MCP_TOKEN"
```

Keep the environment variable available when starting the client. Other MCP clients need Streamable HTTP and `Authorization: Bearer <token>`.

The MCP exposes four tools:

- `index(max_files?)`: synchronize one bounded batch.
- `search(query, limit?, folder?)`: return semantic matches and source locations.
- `status()`: inspect index state without loading the model.
- `inspect(relative_path, max_chars?)`: inspect bounded indexed text and metadata.

This server exposes MCP tools, not MCP resources, so an empty resource list is expected. A native Codex interaction should call tools such as `knowledge.search` or `knowledge.inspect`; invoking the `knowledge` CLI from a shell still reaches the same MCP server, but it is a CLI fallback rather than a native tool call.

## Troubleshooting

- `Knowledge server is not running` or `httpx.ConnectError`: confirm the `serve` terminal is still running and that the configured host, port, and path match the client registration.
- HTTP `401` or `403`: export the token before launching the agent and confirm that the file matches the configured `server.token_file` or the default `<data_dir>/access-token`.
- `Another knowledge server already owns data directory`: an existing server is using that `data_dir`; use it instead of starting a second writer, or stop it cleanly first.
- A new file is not searchable yet: wait for the polling interval or run `uv run knowledge --config config.local.toml index` immediately.
- The token path is uncertain: inspect `config.local.toml`; when `server.token_file` is omitted, it is always `<data_dir>/access-token`.

## Rebuilds and recovery

Changing a parser or chunk setting automatically reindexes affected files. Changing the embedding model, vector dimension, normalization, or metric requires a new index:

1. Stop the server.
2. Change `data_dir` to a new empty directory and update the embedding configuration.
3. Start the server and run representative searches.
4. Keep the previous `data_dir` until the new results are accepted; restoring the old configuration rolls back.

If `manifest.json` is corrupt or missing while vectors exist, the service stops with a rebuild instruction rather than guessing. Source files remain authoritative, so deleting a failed data directory and rebuilding loses only the derived search index. Do not delete an index while its server is running.

Run all local checks with:

```sh
uv run --group dev ./check.sh
```

See [DEVELOPING.md](DEVELOPING.md) for architecture and extension examples.

