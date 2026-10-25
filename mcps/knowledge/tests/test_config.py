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


if __name__ == "__main__":
    unittest.main()
