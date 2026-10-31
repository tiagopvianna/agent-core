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

    def test_neighbors_are_complete_ordered_and_file_local(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            store = ChromaStore(root / "data")
            store.initialize(root, {"model": "fake"})
            chunks = [
                Chunk(
                    str(i),
                    "x" * 2501 + str(i),
                    {
                        "path": "note.txt",
                        "file_type": "txt",
                        "chunk_index": i,
                        "start_line": i + 1,
                        "end_line": i + 1,
                    },
                )
                for i in (0, 2, 4)
            ]
            store.replace_document("note.txt", chunks, [[0.0, 1.0], [1.0, 0.0], [0.0, 1.0]], 10)
            store.update_file("note.txt", {"state": "active"})
            hit = store.search([1.0, 0.0], 1)[0]
            self.assertEqual(hit.chunk_index, 2)
            self.assertEqual(len(hit.snippet), 2502)
            self.assertEqual([c["chunk_index"] for c in hit.previous_chunks], [0])
            self.assertEqual([c["chunk_index"] for c in hit.next_chunks], [4])
            self.assertEqual(hit.previous_chunks[0]["text"], chunks[0].text)
            compact = store.search([1.0, 0.0], 1, before=0, after=0)[0]
            self.assertEqual(compact.previous_chunks, [])
            self.assertEqual(compact.next_chunks, [])
            expanded = store.search([1.0, 0.0], 3, before=99, after=99)
            first = next(h for h in expanded if h.chunk_index == 0)
            self.assertEqual(first.previous_chunks, [])
            self.assertEqual(len(first.next_chunks), 2)

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
