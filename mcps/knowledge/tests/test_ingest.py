from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_mcp.ingest import chunk_segments, discover_files, parse_markdown


class IngestTests(unittest.TestCase):
    def test_discovery_skips_hidden_dependencies_and_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "docs").mkdir()
            (root / "docs" / "keep.md").write_text("keep", encoding="utf-8")
            (root / ".git").mkdir()
            (root / ".git" / "hidden.md").write_text("hidden", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "vendor.txt").write_text("vendor", encoding="utf-8")
            (root / "linked.md").symlink_to(root / "docs" / "keep.md")

            result = discover_files(
                root,
                {".md": "markdown", ".txt": "text"},
                ("**/node_modules/**",),
            )
            self.assertTrue(result.complete)
            self.assertEqual([item.relative_path for item in result.files], ["docs/keep.md"])

    def test_markdown_chunks_fit_token_budget_and_keep_locations(self) -> None:
        content = b"# Heading\n\n" + (b"word " * 30) + b"\n"
        segments = parse_markdown(content, 10)
        chunks = chunk_segments(
            segments,
            "notes/test.md",
            "md",
            "hash",
            "process",
            lambda text: len(text.split()) + 2,
            max_tokens=10,
            overlap_tokens=2,
        )
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk.text.split()) + 2 <= 10 for chunk in chunks))
        self.assertTrue(all(chunk.metadata["path"] == "notes/test.md" for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
