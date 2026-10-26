from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_mcp.config import load_config


class ConfigTests(unittest.TestCase):
    def test_loads_paths_and_extension_mapping_relative_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config_path = base / "config.toml"
            config_path.write_text(
                """
source_root = "content"
data_dir = "state"
exclude = ["**/vendor/**"]

[parsers]
".md" = "markdown"
"py" = "text"
""",
                encoding="utf-8",
            )
            config = load_config(config_path)
            self.assertEqual(config.source_root, (base / "content").resolve())
            self.assertEqual(config.data_dir, (base / "state").resolve())
            self.assertEqual(config.parsers[".py"], "text")
            self.assertEqual(config.exclude, ("**/vendor/**",))

    def test_chunk_strategies_and_docx_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            for strategy in ("paragraph", "section", "packed"):
                path.write_text(
                    'source_root = "content"\ndata_dir = "state"\n'
                    f'[index]\nchunk_strategy = "{strategy}"\n',
                    encoding="utf-8",
                )
                config = load_config(path)
                self.assertEqual(config.index.chunk_strategy, strategy)
                self.assertEqual(config.parsers[".docx"], "docx")
            path.write_text(
                'source_root = "content"\ndata_dir = "state"\n'
                '[index]\nchunk_strategy = "unknown"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "chunk_strategy"):
                load_config(path)

    def test_omitted_strategy_defaults_to_paragraph(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.toml"
            path.write_text('source_root = "content"\ndata_dir = "state"\n')
            self.assertEqual(load_config(path).index.chunk_strategy, "paragraph")


if __name__ == "__main__":
    unittest.main()
