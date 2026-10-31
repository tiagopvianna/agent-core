from __future__ import annotations

import unittest

from mcp.types import CallToolResult

from knowledge_mcp.cli import _decode_result, build_parser


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


if __name__ == "__main__":
    unittest.main()
