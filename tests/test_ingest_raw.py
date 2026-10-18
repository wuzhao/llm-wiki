import subprocess
import sys
import tempfile
import unittest
import urllib.parse
from pathlib import Path

import yaml
from kb_fixture import initialize_kb, snapshot


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ingest_raw.py"


class IngestRawTests(unittest.TestCase):
    def run_ingest(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *map(str, args)],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_text_ingest_always_writes_to_raw_and_quotes_yaml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            initialize_kb(temp_dir)
            result = self.run_ingest(
                temp_dir,
                "--text",
                "正文",
                "--title",
                "标题: 含冒号",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output_path = Path(result.stdout.strip()).resolve()
            self.assertEqual(output_path.parent, (Path(temp_dir) / "raw").resolve())
            content = output_path.read_text(encoding="utf-8")
            frontmatter = content.split("---\n", 2)[1]
            metadata = yaml.safe_load(frontmatter)
            self.assertEqual(metadata["title"], "标题: 含冒号")
            self.assertNotIn("description", metadata)
            self.assertNotIn("tags", metadata)

    def test_url_ingest_uses_okf_resource_field(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            initialize_kb(temp_dir)
            result = self.run_ingest(
                temp_dir,
                "--url",
                "data:text/plain,raw-profile",
                "--title",
                "URL 素材",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output_path = Path(result.stdout.strip())
            frontmatter = output_path.read_text(encoding="utf-8").split("---\n", 2)[1]
            metadata = yaml.safe_load(frontmatter)
            self.assertEqual(metadata["resource"], "data:text/plain,raw-profile")

    def test_raw_dir_option_is_not_supported(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_ingest(
                temp_dir,
                "--text",
                "正文",
                "--title",
                "标题",
                "--raw-dir",
                "../outside",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unrecognized arguments", result.stderr)

    def test_source_arguments_are_mutually_exclusive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_ingest(
                temp_dir,
                "--file",
                __file__,
                "--text",
                "正文",
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not allowed with argument", result.stderr)

    def test_preflight_rejects_empty_or_wrong_structure_without_writes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_ingest(temp_dir, "--text", "正文", "--title", "标题")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
            kb = initialize_kb(temp_dir)
            (kb / "raw/assets").rmdir()
            (kb / "raw/assets").write_text("wrong kind")
            before = snapshot(kb)
            result = self.run_ingest(kb, "--text", "正文", "--title", "标题")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(snapshot(kb), before)

    def test_invalid_title_and_empty_body_leave_no_changes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = self.run_ingest(temp_dir, "--text", "正文")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(list(Path(temp_dir).iterdir()), [])
            kb = initialize_kb(temp_dir)
            before = snapshot(kb)
            for source in (("--text", " \n\t"), ("--url", "data:text/html,<html><script>x</script></html>")):
                with self.subTest(source=source):
                    result = self.run_ingest(kb, *source, "--title", "empty")
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(snapshot(kb), before)

    def test_reingest_preserves_old_raw_and_source_hash(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as inputs:
            import hashlib
            kb = initialize_kb(temp_dir)
            source = Path(inputs) / "source.md"
            source.write_text("first source\n")
            first = self.run_ingest(kb, "--file", source)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_path = Path(first.stdout.strip())
            old = first_path.read_bytes()
            metadata = yaml.safe_load(first_path.read_text().split("---\n", 2)[1])
            self.assertEqual(metadata["source_file_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            source.write_text("changed source\n")
            lint = subprocess.run([sys.executable, str(ROOT / "scripts/lint_wiki.py"), str(kb)], capture_output=True, text=True)
            self.assertIn("与当前原始文件不一致", lint.stdout)
            second = self.run_ingest(kb, "--file", source)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotEqual(second.stdout, first.stdout)
            self.assertEqual(first_path.read_bytes(), old)
            lint = subprocess.run([sys.executable, str(ROOT / "scripts/lint_wiki.py"), str(kb)], capture_output=True, text=True)
            self.assertNotIn("与当前原始文件不一致", lint.stdout)
            new_metadata = yaml.safe_load(Path(second.stdout.strip()).read_text().split("---\n", 2)[1])
            self.assertEqual(new_metadata["source_id"], metadata["source_id"])
            self.assertEqual(new_metadata["source_version"], 2)
            self.assertEqual(new_metadata["supersedes"], first_path.relative_to(kb.resolve()).as_posix())

    def test_identical_retries_report_existing_material_without_writes(self):
        for source in (("--text", "same material"), ("--url", "data:text/plain,same-material")):
            with self.subTest(source=source), tempfile.TemporaryDirectory() as temp_dir:
                kb = initialize_kb(temp_dir)
                first = self.run_ingest(kb, *source, "--title", "same")
                self.assertEqual(first.returncode, 0, first.stderr)
                before = snapshot(kb)
                second = self.run_ingest(kb, *source, "--title", "different-title")
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(second.stdout, first.stdout)
                self.assertIn("已有相同内容 ingested", second.stderr)
                self.assertEqual(snapshot(kb), before)

    def test_url_preserves_original_response_and_extraction_fingerprints(self):
        import hashlib
        from wiki_metadata import split_frontmatter, body_sha256
        html = '<html><h2>例子</h2><pre><code>if ok:\n    run()\n</code></pre></html>'
        url = 'data:text/html;charset=utf-8,' + urllib.parse.quote(html)
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            result = self.run_ingest(kb, '--url', url)
            self.assertEqual(result.returncode, 0, result.stderr)
            _, metadata, body, error = split_frontmatter(Path(result.stdout.strip()).read_text())
            self.assertEqual(error, '')
            self.assertTrue(metadata['source_snapshot'].startswith('raw/assets/'))
            self.assertEqual((kb / metadata['source_snapshot']).read_bytes(), html.encode('utf-8'))
            self.assertEqual(metadata['source_snapshot_sha256'], hashlib.sha256(html.encode('utf-8')).hexdigest())
            self.assertEqual(metadata['body_sha256'], body_sha256(body))
            self.assertIn('if ok:\n    run()\n', body)

    def test_source_reversion_creates_current_version_instead_of_reusing_history(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            paths = []
            for text in ('original', 'changed', 'original'):
                result = self.run_ingest(kb, '--text', text, '--title', 'source', '--source-id', 'text:experiment')
                self.assertEqual(result.returncode, 0, result.stderr)
                paths.append(result.stdout.strip())
            self.assertEqual(len(set(paths)), 3)
            metadata = yaml.safe_load(Path(paths[-1]).read_text().split('---\n', 2)[1])
            self.assertEqual(metadata['source_version'], 3)

    def test_historical_body_tampering_is_still_reported(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as inputs:
            kb = initialize_kb(directory)
            source = Path(inputs) / 'article.md'
            source.write_text('old body\n')
            first = self.run_ingest(kb, '--file', source)
            source.write_text('new body\n')
            second = self.run_ingest(kb, '--file', source)
            self.assertEqual(second.returncode, 0, second.stderr)
            path = Path(first.stdout.strip())
            path.write_text(path.read_text().replace('old body', 'tampered body'))
            lint = subprocess.run([sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb), '--fail-on', 'error'], capture_output=True, text=True)
            self.assertEqual(lint.returncode, 1)
            self.assertIn('raw 正文与保存时的指纹不一致', lint.stdout)

    def test_parallel_identical_ingests_share_one_raw_without_lock_artifacts(self):
        from concurrent.futures import ThreadPoolExecutor
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(lambda _: self.run_ingest(kb, '--text', 'same material', '--title', 'same'), range(2)))
            self.assertTrue(all(result.returncode == 0 for result in results))
            self.assertEqual(results[0].stdout, results[1].stdout)
            self.assertEqual({path.name for path in (kb / 'raw').iterdir()},
                             {'assets', Path(results[0].stdout.strip()).name})

    def test_markdown_attachments_do_not_affect_ingest_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            first = self.run_ingest(kb, '--text', 'same material', '--title', 'same')
            self.assertEqual(first.returncode, 0, first.stderr)
            attachment = kb / 'raw/assets/original.md'
            attachment.write_text('---\ntitle: invalid: yaml\n---\nOriginal attachment\n')
            before = snapshot(kb)
            duplicate = self.run_ingest(kb, '--text', 'same material', '--title', 'same')
            self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
            self.assertEqual(duplicate.stdout, first.stdout)
            self.assertEqual(snapshot(kb), before)
            new = self.run_ingest(kb, '--text', 'new material', '--title', 'new')
            self.assertEqual(new.returncode, 0, new.stderr)
            self.assertEqual(attachment.read_bytes(), before['raw/assets/original.md'])

    def test_corrupted_url_snapshot_is_not_reused_as_an_identical_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            arguments = ('--url', 'data:text/html,<p>original</p>', '--title', 'source')
            first = self.run_ingest(kb, *arguments)
            old_metadata = yaml.safe_load(Path(first.stdout.strip()).read_text().split('---\n', 2)[1])
            old_snapshot = kb / old_metadata['source_snapshot']
            old_snapshot.write_bytes(b'corrupted')
            second = self.run_ingest(kb, *arguments)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertNotEqual(second.stdout, first.stdout)
            metadata = yaml.safe_load(Path(second.stdout.strip()).read_text().split('---\n', 2)[1])
            self.assertEqual((kb / metadata['source_snapshot']).read_bytes(), b'<p>original</p>')
            self.assertEqual(old_snapshot.read_bytes(), b'corrupted')

    def test_url_snapshot_directory_cannot_escape_assets_via_symlink(self):
        import datetime
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            month = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m')
            (kb / 'raw/assets' / month).symlink_to(kb / 'wiki', target_is_directory=True)
            before = snapshot(kb)
            result = self.run_ingest(kb, '--url', 'data:text/plain,source', '--title', 'source')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('越出 assets', result.stderr)
            self.assertEqual(snapshot(kb), before)


if __name__ == "__main__":
    unittest.main()
