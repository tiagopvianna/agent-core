from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from knowledge_mcp.models import Chunk
from knowledge_mcp.storage import ChromaStore, DataDirectoryLock


class StorageTests(unittest.TestCase):
    def test_data_directory_has_one_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "data"
            first = DataDirectoryLock(data_dir)
            second = DataDirectoryLock(data_dir)
            first.acquire()
            try:
                with self.assertRaisesRegex(RuntimeError, "already owns"):
                    second.acquire()
            finally:
                first.release()
            second.acquire()
            second.release()

    def test_chroma_filters_pending_and_folder_boundaries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            store = ChromaStore(root / "data")
            fingerprint = {"provider": "fake", "model": "test", "dimension": 2}
            store.initialize(source, fingerprint)

            for path in ("api/one.txt", "api-old/two.txt"):
                chunk = Chunk(
                    id=path,
                    text=path,
                    metadata={
                        "path": path,
                        "file_type": "txt",
                        "folder": str(Path(path).parent),
                        "chunk_index": 0,
                    },
                )
                store.replace_document(path, [chunk], [[1.0, 0.0]], 10)
                store.update_file(path, {"state": "active", "indexed_at": "now"})

            hits = store.search([1.0, 0.0], 10, folder="api")
            self.assertEqual([hit.path for hit in hits], ["api/one.txt"])

            store.update_file("api/one.txt", {"state": "pending_replace"})
            self.assertEqual(store.search([1.0, 0.0], 10, folder="api"), [])

    def test_missing_manifest_next_to_vectors_is_an_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            source.mkdir()
            store = ChromaStore(root / "data")
            fingerprint = {"provider": "fake", "model": "test", "dimension": 2}
            store.initialize(source, fingerprint)
            chunk = Chunk(
                id="one",
                text="alpha",
                metadata={"path": "one.txt", "file_type": "txt", "chunk_index": 0},
            )
            store.replace_document("one.txt", [chunk], [[1.0, 0.0]], 10)
            store.manifest_path.unlink()

            reopened = ChromaStore(root / "data")
            with self.assertRaisesRegex(RuntimeError, "manifest.json is missing"):
                reopened.initialize(source, fingerprint)


if __name__ == "__main__":
    unittest.main()
