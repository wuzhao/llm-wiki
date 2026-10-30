import concurrent.futures
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb_fixture import ROOT
from wiki_io import WritePlan, atomic_write_text, create_unique_text


class WikiIOTests(unittest.TestCase):
    def test_replace_failure_keeps_original_and_removes_temporary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "page.md"
            target.write_text("original")
            with patch("wiki_io.os.replace", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    atomic_write_text(target, "replacement")
            self.assertEqual(target.read_text(), "original")
            self.assertEqual(list(Path(temp_dir).iterdir()), [target])

    def test_parallel_raw_creates_preserve_every_version(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                paths = list(pool.map(lambda i: create_unique_text(temp_dir, "same", str(i)), range(24)))
            self.assertEqual(len(set(paths)), 24)
            self.assertEqual({p.read_text() for p in paths}, {str(i) for i in range(24)})

    def test_raw_write_failure_removes_only_new_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old = Path(temp_dir) / "same.md"
            old.write_text("old")
            with patch("wiki_io.os.fsync", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    create_unique_text(temp_dir, "same", "new")
            self.assertEqual(list(Path(temp_dir).iterdir()), [old])
            self.assertEqual(old.read_text(), "old")

    def test_atomic_update_preserves_file_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "page.md"
            target.write_text("original")
            target.chmod(0o640)
            atomic_write_text(target, "updated")
            self.assertEqual(target.stat().st_mode & 0o777, 0o640)

    def test_stale_plan_does_not_overwrite_newer_content_or_other_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "a.md").write_text("original a")
            (root / "b.md").write_text("new user edit")
            plan = WritePlan({"a.md": "fixed a", "b.md": "fixed b"},
                             {"a.md": "original a", "b.md": "original b"})
            written = []
            with self.assertRaisesRegex(OSError, "页面在扫描后已变化"):
                plan.apply(root, written)
            self.assertEqual(written, [])
            self.assertEqual((root / "a.md").read_text(), "original a")
            self.assertEqual((root / "b.md").read_text(), "new user edit")
