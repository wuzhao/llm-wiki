import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kb_fixture import ROOT, initialize_kb, snapshot, unreadable_directory
from test_lint_wiki import page
from wiki_metadata import body_sha256, split_frontmatter


class ProvenanceSearchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.kb = initialize_kb(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def write(self, relative, body, **metadata):
        document_type = {'raw': 'source-material', 'summaries': 'source-summary', 'entities': 'entity', 'concepts': 'concept', 'analyses': 'analysis'}[relative.split('/')[0 if relative.startswith('raw/') else 1]]
        path = self.kb / relative
        path.write_text(page(document_type, path.stem, body, **metadata))
        if relative.startswith('wiki/'):
            with (self.kb / 'wiki/index.md').open('a') as index:
                index.write(f'\n- [[{relative.removeprefix("wiki/")}]]\n')
        return path

    def command(self, script, *args):
        return subprocess.run([sys.executable, str(ROOT / 'scripts' / script), str(self.kb), *args], capture_output=True, text=True)

    def test_missing_sources_are_reported_even_when_links_are_valid(self):
        self.write('wiki/concepts/alpha.md', '[[concepts/beta]]')
        self.write('wiki/concepts/beta.md', '[[concepts/alpha]]')
        result = self.command('lint_wiki.py')
        self.assertIn('知识页缺少来源证据', result.stdout)

    def test_cycles_are_errors_and_never_rewritten(self):
        self.write('wiki/concepts/alpha.md', 'A', sources=[{'id': 'b', 'resource': 'beta.md'}])
        self.write('wiki/concepts/beta.md', 'B', sources=[{'id': 'a', 'resource': 'alpha.md'}])
        before = snapshot(self.kb)
        result = self.command('lint_wiki.py', '--fail-on', 'error')
        self.assertEqual(result.returncode, 1)
        self.assertIn('来源链存在循环引用', result.stdout)
        self.assertEqual(snapshot(self.kb), before)

    def test_per_claim_values_are_checked_against_linked_raw(self):
        self.write('raw/experiment.md', 'The measured latency is 42ms.')
        self.write('wiki/summaries/experiment.md', '## 摘要\n\n## 关键要点', sources=[{'id': 'raw', 'resource': '../../raw/experiment.md'}])
        concept = self.write('wiki/concepts/latency.md', '延迟为 42ms。[^experiment]\n\n[^experiment]: 实验结果', sources=[{'id': 'experiment', 'resource': '../summaries/experiment.md'}])
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/latency.md', '--fail-on', 'error')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('原文未定位', result.stdout)
        self.assertNotIn('发现死链', result.stdout)
        concept.write_text(concept.read_text().replace('42ms', '99ms'))
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/latency.md')
        self.assertIn('原文未定位到数值或引文候选: 99ms', result.stdout)

    def test_unknown_claim_reference_and_duplicate_source_ids_are_errors(self):
        self.write('raw/source.md', '42ms')
        self.write('wiki/concepts/alpha.md', '42ms[^missing]', sources=[{'id': 'same', 'resource': '../../raw/source.md'}, {'id': 'same', 'resource': '../../raw/source.md'}])
        result = self.command('lint_wiki.py', '--fail-on', 'error')
        self.assertEqual(result.returncode, 1)
        self.assertIn('来源 id 重复', result.stdout)
        self.assertIn('逐条引用没有对应来源 id', result.stdout)

    def test_values_are_bound_to_their_own_citations_in_one_paragraph(self):
        self.write('raw/a.md', '42ms')
        self.write('raw/b.md', '99ms')
        self.write('wiki/concepts/alpha.md', '延迟为99ms。[^a]另一结果为42ms。[^b]\n\n[^a]: A\n[^b]: B', sources=[{'id': 'a', 'resource': '../../raw/a.md'}, {'id': 'b', 'resource': '../../raw/b.md'}])
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md')
        self.assertIn('原文未定位到数值或引文候选: 99ms', result.stdout)
        self.assertIn('原文未定位到数值或引文候选: 42ms', result.stdout)

    def test_new_source_version_propagates_drift_to_archived_analysis(self):
        self.write('raw/old.md', '42ms', source_url='https://example.com/source', timestamp='2026-01-01T00:00:00Z')
        self.write('wiki/summaries/summary.md', '42ms', sources=[{'id': 'raw', 'resource': '../../raw/old.md'}])
        self.write('wiki/entities/entity.md', 'A', sources=[{'id': 'summary', 'resource': '../summaries/summary.md'}])
        analysis = self.write('wiki/analyses/result.md', 'Historical answer', sources=[{'id': 'entity', 'resource': '../entities/entity.md'}])
        self.write('raw/new.md', '99ms', source_url='https://example.com/source', timestamp='2026-02-01T00:00:00Z', supersedes='raw/old.md')
        original = analysis.read_bytes()
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/analyses/result.md')
        self.assertIn('来源依赖需要复核', result.stdout)
        self.assertIn('已有新版本 raw/new.md', result.stdout)
        self.assertIn('归档快照仅标记待复核', result.stdout)
        self.assertEqual(analysis.read_bytes(), original)
        impact = self.command('impact_wiki.py', '--source', 'raw/new.md')
        self.assertEqual(impact.returncode, 0, impact.stderr)
        payload = json.loads(impact.stdout)
        self.assertEqual({entry['path'] for entry in payload['affected']}, {'wiki/summaries/summary.md', 'wiki/entities/entity.md', 'wiki/analyses/result.md'})
        self.assertIn({'path': 'wiki/analyses/result.md', 'action': 'review-snapshot'}, payload['affected'])

    def test_dependency_fingerprint_catches_edits_without_date_changes(self):
        raw = self.write('raw/experiment.md', '42ms')
        fingerprint = body_sha256(split_frontmatter(raw.read_text())[2])
        self.write('wiki/concepts/alpha.md', 'A', sources=[{'id': 'raw', 'resource': '../../raw/experiment.md', 'body_sha256': fingerprint}])
        raw.write_text(raw.read_text().replace('42ms', '99ms'))
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md')
        self.assertIn('正文指纹已变化', result.stdout)

    def test_reviewed_historical_source_does_not_keep_current_page_in_drift(self):
        self.write('raw/old.md', '42ms', source_url='https://example.com/source', timestamp='2026-01-01T00:00:00Z')
        self.write('raw/new.md', '99ms', source_url='https://example.com/source', timestamp='2026-02-01T00:00:00Z')
        self.write('wiki/summaries/old.md', 'Historical result', sources=[{'id': 'raw', 'resource': '../../raw/old.md'}])
        self.write('wiki/summaries/current.md', 'Current result', sources=[{'id': 'raw', 'resource': '../../raw/new.md'}])
        self.write('wiki/concepts/alpha.md', 'Current conclusion and explicitly retained history', sources=[{'id': 'current', 'resource': '../summaries/current.md'}, {'id': 'past', 'resource': '../summaries/old.md', 'historical': True}])
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md')
        self.assertNotIn('来源依赖需要复核', result.stdout)
        self.assertNotIn('来源链未到达 raw', result.stdout)

    def test_search_finds_body_details_and_aliases_then_paginates(self):
        self.write('wiki/concepts/rag.md', '方法定义', aliases=['RAG', '检索增强生成'])
        self.write('wiki/entities/a.md', '这里提到了检索增强生成的细节。', domain='retrieval', tags=['search'])
        self.write('wiki/entities/b.md', '这里也提到了检索增强生成。', domain='retrieval', tags=['search'])
        before = snapshot(self.kb)
        result = self.command('search_wiki.py', 'RAG', '--limit', '2')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['total'], 3)
        self.assertEqual(payload['next_offset'], 2)
        second = json.loads(self.command('search_wiki.py', 'RAG', '--limit', '2', '--offset', '2').stdout)
        self.assertEqual(len(second['results']), 1)
        filtered = json.loads(self.command('search_wiki.py', '检索增强生成', '--type', 'entity', '--tag', 'search', '--domain', 'retrieval').stdout)
        self.assertEqual(filtered['total'], 2)
        self.assertEqual(snapshot(self.kb), before)

    def test_search_reports_unreadable_metadata_instead_of_claiming_complete_results(self):
        (self.kb / 'wiki/concepts/broken.md').write_text('---\ntitle: a: b\n---\nneedle\n')
        before = snapshot(self.kb)
        result = self.command('search_wiki.py', 'needle')
        self.assertEqual(result.returncode, 1)
        self.assertIn('wiki/concepts/broken.md', json.loads(result.stdout)['read_errors'])
        self.assertEqual(snapshot(self.kb), before)

    def test_search_covers_description_and_shows_late_matches_on_long_lines(self):
        self.write('wiki/concepts/alpha.md', 'x' * 500 + ' needle ' + 'y' * 500, description='metadata-needle')
        result = json.loads(self.command('search_wiki.py', 'needle').stdout)
        self.assertEqual(result['total'], 1)
        self.assertIn('needle', result['results'][0]['snippet'])
        metadata = json.loads(self.command('search_wiki.py', 'metadata-needle').stdout)
        self.assertEqual(metadata['total'], 1)

    def test_claim_references_require_real_footnote_definitions(self):
        self.write('raw/experiment.md', 'Measured latency: 42ms.')
        concept = self.write('wiki/concepts/latency.md', 'Latency: 42ms.[^experiment]',
                             sources=[{'id': 'experiment', 'resource': '../../raw/experiment.md'}])
        before = snapshot(self.kb)
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/latency.md', '--fail-on', 'error')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('逐条引用缺少脚注定义: experiment', result.stdout)
        self.assertEqual(snapshot(self.kb), before)
        concept.write_text(concept.read_text() + '\n[^experiment]: 实验结果，详见原始资料。\n')
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/latency.md', '--fail-on', 'error')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('缺少脚注定义', result.stdout)

    def test_duplicate_footnotes_are_reported_but_code_examples_are_ignored(self):
        self.write('raw/experiment.md', '42ms')
        concept = self.write('wiki/concepts/latency.md',
                             '42ms[^experiment]\n\n[^experiment]: A\n\n```markdown\n[^experiment]: 示例\n[^fake]\n```',
                             sources=[{'id': 'experiment', 'resource': '../../raw/experiment.md'}])
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/latency.md', '--fail-on', 'error')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        concept.write_text(concept.read_text() + '\n[^experiment]: B\n')
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/latency.md', '--fail-on', 'error')
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn('脚注定义重复: experiment', result.stdout)
        self.assertNotIn('fake', result.stdout)

    def test_search_session_reuses_results_until_explicit_refresh(self):
        from unittest.mock import patch
        from search_wiki import SearchSession
        from wiki_config import load_schema
        self.write('wiki/concepts/alpha.md', 'needle')
        reads = []
        original_read = Path.read_bytes

        def read(path):
            reads.append(path)
            return original_read(path)

        with patch.object(Path, 'read_bytes', read):
            session = SearchSession(self.kb, load_schema(), {'needle'})
            initial_reads = len(reads)
            self.write('wiki/concepts/beta.md', 'needle')
            for offset in (0, 1, 2):
                self.assertEqual(session.page(offset, 1)['total'], 1)
            self.assertEqual(len(reads), initial_reads)
            session.refresh()
            self.assertEqual(session.page(0, 1)['total'], 2)
            self.assertGreater(len(reads), initial_reads)

    def test_interactive_search_paginates_and_recovers_from_bad_requests_without_writes(self):
        for name in ('alpha', 'beta', 'gamma'):
            self.write(f'wiki/concepts/{name}.md', 'needle')
        before = snapshot(self.kb)
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts/search_wiki.py'), str(self.kb), 'needle', '--limit', '1', '--interactive'],
            input='{"offset": 1}\n{"offset": true}\n{"offset": 2}\n{"refresh": true}\n', capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        pages = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([pages[i]['offset'] for i in (0, 1, 3, 4)], [0, 1, 2, 0])
        self.assertIn('error', pages[2])
        self.assertEqual(len({pages[i]['results'][0]['path'] for i in (0, 1, 3)}), 3)
        self.assertIsNone(pages[3]['next_offset'])
        self.assertEqual(snapshot(self.kb), before)

    def test_search_reports_unreadable_topic_directories_even_with_zero_matches(self):
        import contextlib
        import io
        from unittest.mock import patch
        from search_wiki import main
        hidden = self.kb / 'wiki/concepts/hidden'
        hidden.mkdir()
        (hidden / 'alpha.md').write_text(page('concept', 'alpha', 'needle hidden-only'))
        self.write('wiki/concepts/visible.md', 'needle')
        before = snapshot(self.kb)
        for query, count in (('needle', 1), ('hidden-only', 0)):
            with self.subTest(query=query):
                output = io.StringIO()
                with unreadable_directory(hidden), patch('sys.argv', ['search_wiki.py', str(self.kb), query]), contextlib.redirect_stdout(output):
                    status = main()
                result = json.loads(output.getvalue())
                self.assertEqual(status, 1)
                self.assertEqual(result['total'], count)
                self.assertIn('wiki/concepts/hidden', result['read_errors'])
        self.assertEqual(snapshot(self.kb), before)

    def test_ingest_does_not_write_when_raw_directory_inventory_is_incomplete(self):
        import contextlib
        import io
        from unittest.mock import patch
        from ingest_raw import main
        hidden = self.kb / 'raw/hidden'
        hidden.mkdir()
        (hidden / 'source.md').write_text(page('source-material', 'source', 'Existing material'))
        before = snapshot(self.kb)
        error = io.StringIO()
        with unreadable_directory(hidden), patch('sys.argv', ['ingest_raw.py', str(self.kb), '--text', 'New material', '--title', 'new']), contextlib.redirect_stderr(error):
            with self.assertRaises(SystemExit) as stopped:
                main()
        self.assertEqual(stopped.exception.code, 2)
        self.assertIn('raw/hidden', error.getvalue())
        self.assertEqual(snapshot(self.kb), before)

    def test_impact_reports_target_scan_errors_outside_markdown_roots(self):
        import contextlib
        import io
        from unittest.mock import patch
        from impact_wiki import main
        self.write('raw/source.md', 'Evidence')
        hidden = self.kb / 'assets/hidden'
        hidden.mkdir()
        before = snapshot(self.kb)
        output = io.StringIO()
        with unreadable_directory(hidden), patch('sys.argv', ['impact_wiki.py', str(self.kb), '--source', 'raw/source.md']), contextlib.redirect_stdout(output):
            status = main()
        self.assertEqual(status, 1)
        self.assertIn('assets/hidden', json.loads(output.getvalue())['read_errors'])
        self.assertEqual(snapshot(self.kb), before)
