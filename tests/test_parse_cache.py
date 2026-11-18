import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb_fixture import initialize_kb, page, snapshot
from lint_wiki import main
from wiki_config import load_schema
from wiki_links import build_target_index
from wiki_metadata import split_frontmatter
from wiki_scan import WikiSnapshot, load_snapshot


class ParseCacheTests(unittest.TestCase):
    def test_read_only_lint_parses_unchanged_page_once(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            target = kb / 'wiki/concepts/a.md'
            text = page('concept', 'A', '## 来源\n\n说明。', custom={'nested': ['original']})
            target.write_text(text)
            calls = []
            def parse(content):
                if content == text: calls.append(content)
                return split_frontmatter(content)
            before = snapshot(kb)
            with patch.object(WikiSnapshot, 'parse', autospec=True, side_effect=WikiSnapshot.parse) as lookups, \
                    patch('wiki_sources.split_frontmatter', side_effect=parse), \
                    patch('wiki_scan.split_frontmatter', side_effect=parse), \
                    patch('lint_wiki.split_frontmatter', side_effect=parse), \
                    patch('sys.argv', ['lint_wiki.py', str(kb), '--lint-files', 'wiki/concepts/a.md']), \
                    contextlib.redirect_stdout(io.StringIO()):
                main()
            self.assertEqual(len(calls), 1)
            self.assertEqual(sum(args[1] == text for args, _ in lookups.call_args_list), 1)
            self.assertEqual(snapshot(kb), before)

    def test_cache_isolates_nested_metadata_and_tracks_changed_and_invalid_text(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            target = kb / 'wiki/concepts/a.md'
            text = page('concept', 'A', '## 来源\n\n说明。', custom={'nested': ['original']})
            target.write_text(text)
            schema = load_schema()
            state = load_snapshot(kb, schema, build_target_index(kb, schema))
            parsed = state.parse(text)
            parsed[1]['custom']['nested'].append('mutated')
            state.documents['wiki/concepts/a.md']['metadata']['custom']['nested'].append('document mutation')
            self.assertEqual(state.parse(text)[1]['custom']['nested'], ['original'])
            changed = text.replace('original', 'new')
            self.assertEqual(state.parse(changed)[1]['custom']['nested'], ['new'])
            invalid = '---\ntype: concept\ntype: entity\n---\n正文'
            self.assertTrue(state.parse(invalid)[3])
            self.assertEqual(state.parse(invalid), split_frontmatter(invalid))
            self.assertEqual(state.originals['wiki/concepts/a.md'], text)
