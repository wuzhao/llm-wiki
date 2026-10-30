import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kb_fixture import ROOT, initialize_kb, snapshot, unreadable_directory
from kb_fixture import page
from wiki_metadata import body_sha256, split_frontmatter
from wiki_sources import source_identity


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

    def test_url_identity_prefers_resource_and_only_falls_back_when_missing(self):
        url = 'https://example.com/article'
        identity = source_identity({'resource': url}, self.kb)
        self.assertIsNotNone(identity)
        for metadata in (
            {'source_url': url},
            {'resource': '', 'source_url': url},
            {'resource': url, 'source_url': 'https://example.com/old-article'},
            {'resource': 'HTTPS://EXAMPLE.COM/article#section'},
        ):
            with self.subTest(metadata=metadata):
                self.assertEqual(source_identity(metadata, self.kb), identity)
        self.assertEqual(source_identity({
            'resource': 'original.md', 'source_url': url, 'source_id': 'text:original',
        }, self.kb), 'text:original')

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

    def test_numeric_normalization_preserves_citation_scope_and_raw(self):
        self.write('raw/a.md', '四十二毫秒，百分之一百五十，负百分之三点五。')
        self.write('raw/b.md', '50%，3.5%。')
        self.write('wiki/concepts/alpha.md',
                   '延迟为 42ms。[^a]占比为 50%，变化为 3.5%。[^a]\n\n'
                   '另一个结果为百分之五十。[^b]\n\n[^a]: A\n[^b]: B',
                   sources=[{'id': 'a', 'resource': '../../raw/a.md'},
                            {'id': 'b', 'resource': '../../raw/b.md'}])
        before = snapshot(self.kb)
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md', '--fail-on', 'error')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('原文未定位到数值或引文候选: 3.5%, 50%', result.stdout)
        self.assertNotIn('原文未定位到数值或引文候选: 42ms', result.stdout)
        self.assertNotIn('原文未定位到数值或引文候选: 百分之五十', result.stdout)
        self.assertEqual(snapshot(self.kb), before)

    def test_values_are_bound_to_their_own_citations_in_one_paragraph(self):
        self.write('raw/a.md', '42ms')
        self.write('raw/b.md', '99ms')
        self.write('wiki/concepts/alpha.md', '延迟为99ms。[^a]另一结果为42ms。[^b]\n\n[^a]: A\n[^b]: B', sources=[{'id': 'a', 'resource': '../../raw/a.md'}, {'id': 'b', 'resource': '../../raw/b.md'}])
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md')
        self.assertIn('原文未定位到数值或引文候选: 99ms', result.stdout)
        self.assertIn('原文未定位到数值或引文候选: 42ms', result.stdout)

    def test_compound_numbers_ranges_and_vague_words_do_not_add_format_noise(self):
        self.write('raw/source.md',
                   '就1亿9100万，一般人群是5.7倍，需求是增长到10.6倍。'
                   '1%至2%，2008年至2018年，2018年至2022年，约40年。1e3个。')
        self.write('wiki/concepts/alpha.md',
                   '1 亿 9100 万，5.7 倍，10.6 倍。[^a]\n\n'
                   '1% 至 2%，2008 年至 2018 年，2018 年至 2022 年，约 40 年。[^a]\n\n'
                   '有1e3个。[^a]\n\n经过多次讨论，做了几十次尝试。\n\n[^a]: 原始记录',
                   sources=[{'id': 'a', 'resource': '../../raw/source.md'}])
        before = snapshot(self.kb)
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md', '--fail-on', 'error')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('原文未定位', result.stdout)
        self.assertNotIn('数值或引文缺少逐条来源', result.stdout)
        self.assertEqual(snapshot(self.kb), before)

    def test_numeric_candidates_stay_grouped_and_cannot_sum_unrelated_sources(self):
        self.write('raw/composite.md', '1亿9100万')
        self.write('raw/a.md', '1亿')
        self.write('raw/b.md', '9100万')
        self.write('wiki/concepts/alpha.md',
                   '数量为1亿，另一结果为9100万。[^composite]\n\n'
                   '总量1.91亿。[^a][^b]\n\n[^composite]: 复合数量\n[^a]: A\n[^b]: B',
                   sources=[{'id': 'composite', 'resource': '../../raw/composite.md'},
                            {'id': 'a', 'resource': '../../raw/a.md'},
                            {'id': 'b', 'resource': '../../raw/b.md'}])
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('原文未定位到数值或引文候选:'), 2)
        self.assertIn('原文未定位到数值或引文候选: 1亿, 9100万', result.stdout)
        self.assertIn('原文未定位到数值或引文候选: 1.91亿', result.stdout)

    def test_claim_markup_does_not_hide_real_quotes_or_numeric_citation_errors(self):
        self.write('raw/source.md', '增长50%，使用缓存。')
        self.write('wiki/concepts/alpha.md',
                   '这是「术语」的概括。[^a]\n\n[50%](alpha.md "2026 年版本")。[^a]\n\n'
                   '原文：「缓冲」。[^a]\n\n实际为99%。\n\n'
                   '## 关联阅读\n\n[2025 年报告](alpha.md)\n\n[^a]: 原始材料',
                   sources=[{'id': 'a', 'resource': '../../raw/source.md'}])
        before = snapshot(self.kb)
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('原文未定位到数值或引文候选:'), 1)
        self.assertIn('原文未定位到数值或引文候选: 缓冲', result.stdout)
        self.assertEqual(result.stdout.count('关键数值或引文缺少逐条来源'), 1)
        self.assertEqual(snapshot(self.kb), before)

    def test_calendar_and_lexical_noise_do_not_hide_numeric_or_citation_errors(self):
        self.write('raw/source.md', 'Published June 7, 2026. 三人受伤，重试三次。')
        self.write('raw/other.md', '2026年6月8日，两人受伤，重试两次。')
        self.write('wiki/concepts/alpha.md',
                   '发布于2026 年 6 月 7 日。[^a]\n\n'
                   '同一项目采用另一种方式；一次性补贴与二次分配，使用三元组。\n\n'
                   '发布于2026年6月8日。[^a]\n\n两人受伤，重试两次。[^a]\n\n'
                   '另有两人受伤。\n\n[^a]: 原始记录\n[^b]: 另一来源',
                   sources=[{'id': 'a', 'resource': '../../raw/source.md'},
                            {'id': 'b', 'resource': '../../raw/other.md'}])
        before = snapshot(self.kb)
        result = self.command('lint_wiki.py', '--lint-files', 'wiki/concepts/alpha.md')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.count('原文未定位到数值或引文候选:'), 2)
        self.assertIn('原文未定位到数值或引文候选: 2026年6月8日', result.stdout)
        self.assertIn('两人, 两次', result.stdout)
        self.assertEqual(result.stdout.count('关键数值或引文缺少逐条来源'), 1)
        self.assertEqual(snapshot(self.kb), before)

    def test_new_source_version_propagates_drift_to_archived_analysis(self):
        self.write('raw/old.md', '42ms', source_url='https://example.com/source', timestamp='2026-01-01T00:00:00Z')
        self.write('wiki/summaries/summary.md', '42ms', sources=[{'id': 'raw', 'resource': '../../raw/old.md'}])
        self.write('wiki/entities/entity.md', 'A', sources=[{'id': 'summary', 'resource': '../summaries/summary.md'}])
        analysis = self.write('wiki/analyses/result.md', 'Historical answer', sources=[{'id': 'entity', 'resource': '../entities/entity.md'}])
        self.write('raw/new.md', '99ms', resource='https://example.com/source', timestamp='2026-02-01T00:00:00Z', supersedes='raw/old.md')
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

    def test_impact_reports_attachment_target_scan_errors(self):
        import contextlib
        import io
        from unittest.mock import patch
        from impact_wiki import main
        self.write('raw/source.md', 'Evidence')
        hidden = self.kb / 'raw/assets/hidden'
        hidden.mkdir()
        before = snapshot(self.kb)
        output = io.StringIO()
        with unreadable_directory(hidden), patch('sys.argv', ['impact_wiki.py', str(self.kb), '--source', 'raw/source.md']), contextlib.redirect_stdout(output):
            status = main()
        self.assertEqual(status, 1)
        self.assertIn('raw/assets/hidden', json.loads(output.getvalue())['read_errors'])
        self.assertEqual(snapshot(self.kb), before)

    def test_impact_excludes_markdown_attachments_from_source_graph(self):
        self.write('raw/source.md', 'Evidence')
        self.write('wiki/concepts/alpha.md', 'Evidence', sources=[{'id': 'source', 'resource': '../../raw/source.md'}])
        (self.kb / 'raw/assets/original.md').write_text('---\ntitle: invalid: yaml\n---\nOriginal attachment\n')
        before = snapshot(self.kb)
        result = self.command('impact_wiki.py', '--source', 'raw/source.md')
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertFalse(payload['read_errors'])
        self.assertEqual({entry['path'] for entry in payload['affected']}, {'wiki/concepts/alpha.md'})
        rejected = self.command('impact_wiki.py', '--source', 'raw/assets/original.md')
        self.assertEqual(rejected.returncode, 2)
        self.assertEqual(snapshot(self.kb), before)
