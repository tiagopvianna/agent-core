from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from mcp.types import CallToolResult

from knowledge_mcp.cli import _decode_result, _read_token, build_parser
from knowledge_mcp.config import AppConfig, ServerConfig


class CliTests(unittest.TestCase):
    def test_parser_accepts_json_search(self) -> None:
        args = build_parser().parse_args(
            ["--config", "local.toml", "search", "payment retry", "--json"]
        )
        self.assertEqual(args.command, "search")
        self.assertEqual(args.query, "payment retry")
        self.assertTrue(args.json)

    def test_structured_list_result_is_unwrapped(self) -> None:
        result = CallToolResult(content=[], structuredContent={"result": [{"path": "note.txt"}]})
        self.assertEqual(_decode_result(result), [{"path": "note.txt"}])

    def test_missing_token_reports_start_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = AppConfig(
                source_root=base,
                data_dir=base / "data",
                server=ServerConfig(token_file=base / "missing-token"),
                config_path=base / "config.toml",
            )
            with self.assertRaisesRegex(RuntimeError, "start it with"):
                _read_token(config)


if __name__ == "__main__":
    unittest.main()
