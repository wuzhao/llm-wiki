import json
import datetime
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb_fixture import ROOT, initialize_kb, page, snapshot
from ingest_attachment import store_attachment
from lint_wiki import scan_links
from markdown_links import mask_non_prose
from wiki_config import SchemaError, load_markdown_template, load_schema, skill_version
from wiki_links import build_target_index, resolve_standard_link
from wiki_metadata import split_frontmatter


class WorkflowToolTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.kb = initialize_kb(self.root / "知识库")
        self.schema = load_schema()

    def tearDown(self):
        self.temp.cleanup()

    def command(self, script, *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / script), str(self.kb), *args],
                              capture_output=True, text=True)

    def test_comment_markers_in_code_do_not_hide_following_links(self):
        for code in ('```html\n<!-- unfinished example\n```', '`<!--`', '    <!-- example',
                     '> ```html\n> <!-- example\n> ```', '``code ` <!--``'):
            with self.subTest(code=code):
                text = code + '\n\n[Broken](missing.md)\n'
                masked = mask_non_prose(text)
                self.assertEqual(len(masked), len(text))
                self.assertEqual(masked.count('\n'), text.count('\n'))
                _, issues, _ = scan_links('wiki/concepts/page.md', text,
                                         build_target_index(self.kb, self.schema), self.schema)
                self.assertEqual(len(issues), 1)
                self.assertIn('missing.md', issues[0]['problem'])
                self.assertEqual(issues[0]['line'], text.count('\n', 0, text.index('[Broken]')) + 1)

    def test_fences_inside_comments_do_not_hide_later_prose(self):
        text = '<!--\n```\n[Hidden](hidden.md)\n-->\n[Visible](visible.md)\n'
        masked = mask_non_prose(text)
        self.assertNotIn('Hidden', masked)
        self.assertIn('[Visible](visible.md)', masked)

    def test_bundle_and_legacy_roots_resolve_to_the_same_page(self):
        (self.kb / 'wiki/concepts/cache.md').write_text(page('concept', 'Cache', '# Cache'))
        (self.kb / 'raw/evidence.md').write_text(page('source-material', 'Evidence', 'Raw evidence'))
        index = build_target_index(self.kb, self.schema)
        for target in ('/concepts/cache.md', '/wiki/concepts/cache.md', '../concepts/cache.md'):
            self.assertEqual(resolve_standard_link('wiki/summaries/page.md', target, index)['relative'],
                             'wiki/concepts/cache.md')
        self.assertEqual(resolve_standard_link('wiki/concepts/cache.md', '/raw/evidence.md', index)['relative'],
                         'raw/evidence.md')
        self.assertIsNone(resolve_standard_link('wiki/concepts/cache.md', '/../../outside.md', index)['relative'])

    def test_skill_version_change_renders_every_template_without_edits(self):
        current = skill_version()
        major, minor, patch_number = current.split('.')
        updated = f'{major}.{minor}.{int(patch_number) + 1}'
        original = Path.read_text
        def bumped(path, *args, **kwargs):
            content = original(path, *args, **kwargs)
            if path == ROOT / 'SKILL.md':
                content = content.replace('  version: ' + current, '  version: ' + updated)
            return content
        with patch.object(Path, 'read_text', bumped):
            for name in ('source', 'concept', 'entity', 'archive', 'hub', 'overview', 'log'):
                _, metadata, _, error = split_frontmatter(load_markdown_template(name + '-template.md'))
                self.assertFalse(error)
                self.assertEqual(metadata['generated']['by'], 'llm-wiki/' + updated)

    def test_missing_external_source_warns_but_damaged_raw_still_blocks(self):
        source = self.root / 'note.md'
        source.write_text('Saved evidence.\n')
        result = self.command('ingest_raw.py', '--file', str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        raw = Path(result.stdout.strip())
        source.unlink()
        result = self.command('lint_wiki.py', '--fail-on', 'error')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('原始文件不可访问', result.stdout)
        result = self.command('lint_wiki.py', '--strict-sources', '--fail-on', 'error')
        self.assertEqual(result.returncode, 1)
        raw.write_text(raw.read_text() + 'Damaged.\n')
        result = self.command('lint_wiki.py', '--fail-on', 'error')
        self.assertEqual(result.returncode, 1)
        self.assertIn('raw 正文与保存时的指纹不一致', result.stdout)

    def test_attachment_bytes_retry_and_extracted_text_provenance(self):
        source = self.root / '论文.pdf'
        data = b'%PDF-1.7\n\xff\x00binary\n'
        source.write_bytes(data)
        result = self.command('ingest_attachment.py', '--file', str(source))
        self.assertEqual(result.returncode, 0, result.stderr)
        attachment = json.loads(result.stdout)
        self.assertEqual((self.kb / attachment['path']).read_bytes(), data)
        before = snapshot(self.kb)
        self.assertTrue(store_attachment(self.kb, source, self.schema)['reused'])
        self.assertEqual(snapshot(self.kb), before)
        result = self.command('ingest_raw.py', '--text', 'Extracted evidence.', '--title', 'Paper',
                              '--attachment', attachment['path'])
        self.assertEqual(result.returncode, 0, result.stderr)
        _, metadata, _, error = split_frontmatter(Path(result.stdout.strip()).read_text())
        self.assertFalse(error)
        self.assertEqual(metadata['source_snapshot'], attachment['path'])
        self.assertEqual(metadata['source_snapshot_sha256'], attachment['sha256'])
        before = snapshot(self.kb)
        retry = self.command('ingest_raw.py', '--text', 'Extracted evidence.', '--title', 'Paper',
                             '--attachment', attachment['path'])
        self.assertEqual(retry.stdout, result.stdout)
        self.assertEqual(snapshot(self.kb), before)

    def test_attachment_invalid_inputs_and_write_failure_leave_no_files(self):
        source = self.root / 'file.bin'
        source.write_bytes(b'1234')
        before = snapshot(self.kb)
        self.schema['limits']['max_source_bytes'] = 3
        with self.assertRaises(ValueError):
            store_attachment(self.kb, source, self.schema)
        self.schema = load_schema()
        with patch('wiki_io.os.fsync', side_effect=OSError('disk error')):
            with self.assertRaises(OSError):
                store_attachment(self.kb, source, self.schema)
        self.assertEqual(snapshot(self.kb), before)
        self.assertEqual(list((self.kb / 'raw/assets').iterdir()), [])
        result = self.command('ingest_raw.py', '--text', 'Evidence', '--title', 'x', '--attachment', '../file.bin')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(self.kb), before)

    def test_attachment_cannot_write_through_an_escaping_month_directory(self):
        source = self.root / 'file.pdf'
        source.write_bytes(b'%PDF-content')
        outside = self.root / 'outside'
        outside.mkdir()
        month = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m')
        (self.kb / 'raw/assets' / month).symlink_to(outside, target_is_directory=True)
        with self.assertRaises(SchemaError):
            store_attachment(self.kb, source, self.schema)
        self.assertEqual(list(outside.iterdir()), [])

    def test_init_cli_is_lint_clean_and_rejects_existing_content(self):
        empty = self.root / 'new'
        empty.mkdir()
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/init_wiki.py'), str(empty)],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(json.loads(result.stdout)['kb_dir']), empty)
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(empty), '--fail-on', 'any'],
                                text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        before = snapshot(empty)
        with self.assertRaises(SchemaError):
            initialize_kb(empty)
        self.assertEqual(snapshot(empty), before)

    def test_init_render_and_install_failure_preserve_the_target(self):
        target = self.root / 'empty'
        target.mkdir()
        with patch('init_wiki.render_markdown_template', side_effect=OSError('template error')):
            with self.assertRaises(OSError):
                initialize_kb(target)
        with patch('init_wiki.os.replace', side_effect=OSError('install error')):
            with self.assertRaises(OSError):
                initialize_kb(target)
        self.assertEqual(list(target.iterdir()), [])
        self.assertFalse(list(self.root.glob('.llm-wiki-init-*')))
        link = self.root / 'link'
        link.symlink_to(target, target_is_directory=True)
        with self.assertRaises(SchemaError):
            initialize_kb(link)


if __name__ == '__main__':
    unittest.main()
