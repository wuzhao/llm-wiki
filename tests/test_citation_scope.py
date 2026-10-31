import subprocess
import sys
import tempfile
import unittest

from kb_fixture import ROOT, initialize_kb, page, snapshot
from wiki_config import load_schema
from wiki_provenance import ProvenanceGraph


class CitationScopeTests(unittest.TestCase):
    def check(self, body, path='wiki/summaries/a.md', sources=None, raw='延迟42ms，占比50%。', extra=None):
        metadata = {'sources': sources if sources is not None else [{'id': 'a', 'resource': 'raw/a.md'}]}
        documents = {'raw/a.md': {'metadata': {}, 'body': raw},
                     path: {'metadata': metadata, 'body': body, 'body_start_line': 10}}
        documents.update(extra or {})
        graph = ProvenanceGraph(ROOT, load_schema(),
                                lambda _, target: {'external': True} if target.startswith('https:')
                                else {'relative': target} if target in documents else {}, documents)
        return graph.check(path, body, metadata)

    def citations(self, findings):
        return [finding for finding in findings if finding.get('category') == 'citation']

    def evidence(self, findings):
        return [finding for finding in findings if finding.get('category') == 'evidence']

    def test_direct_single_raw_summary_uses_page_source_for_transcription(self):
        self.assertEqual(self.check('延迟0.042秒。\n\n占比50%。'), [])
        self.assertEqual(self.check('延迟42ms。', sources=[{'resource': 'raw/a.md'}]), [])

    def test_page_source_exemption_still_reports_unmatched_values_and_positions(self):
        findings = self.check('记录\n\n延迟99ms。')
        self.assertFalse(self.citations(findings))
        evidence = self.evidence(findings)
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['sources'], ['raw/a.md'])
        self.assertEqual(evidence[0]['line'], 3)
        self.assertEqual(evidence[0]['details'][0]['line'], 12)
        self.assertEqual(evidence[0]['details'][0]['claim'], '99ms')

    def test_processed_values_and_verbatim_quotes_still_need_inline_citations(self):
        for body in ('校准值为50%。', '派生值为50%。', '本页计算占比50%。',
                     '计算得到50%。', '1个 + 1个 = 2个。', '原文：「延迟42ms」。',
                     '> 「没有数字的原句」'):
            with self.subTest(body=body):
                self.assertEqual(len(self.citations(self.check(body, raw=body))), 1)

    def test_calibration_without_citation_preserves_unit_diagnostic(self):
        findings = self.check('原文5.63%，本页校准为5.63‰。', raw='出生率5.63%。')
        self.assertEqual(len(self.citations(findings)), 1)
        self.assertEqual(self.evidence(findings)[0]['details'][0]['kind'], 'unit-difference')

    def test_valid_inline_quote_can_be_followed_by_uncited_transcription(self):
        findings = self.check('原文：「延迟42ms」。[^a]占比50%。\n\n[^a]: 原始素材')
        self.assertEqual(findings, [])
        findings = self.check('延迟42ms。[^a]原文：「占比50%」。\n\n[^a]: 原始素材')
        self.assertEqual(len(self.citations(findings)), 1)
        self.assertIn('后续', self.citations(findings)[0]['problem'])

    def test_uncited_tail_is_checked_against_page_source(self):
        findings = self.check('延迟42ms。[^a]占比99%。\n\n[^a]: 原始素材')
        self.assertFalse(self.citations(findings))
        self.assertEqual(self.evidence(findings)[0]['details'][0]['claim'], '99%')

    def test_single_summary_keeps_unknown_missing_and_duplicate_footnote_errors(self):
        for body, expected in (
            ('延迟42ms。[^missing]\n\n[^missing]: 来源', '没有对应来源 id'),
            ('延迟42ms。[^a]', '缺少脚注定义'),
            ('延迟42ms。[^a]\n\n[^a]: 来源\n[^a]: 重复', '脚注定义重复'),
        ):
            with self.subTest(body=body):
                findings = self.check(body)
                self.assertTrue(any(f['level'] == '🔴' and expected in f['problem'] for f in findings))

    def test_multiple_or_unresolved_sources_cannot_claim_single_source_exemption(self):
        for second in ({'id': 'b', 'resource': 'raw/b.md'},
                       {'id': 'b', 'resource': 'missing.md'},
                       {'id': 'b', 'resource': 'https://example.com'},
                       {'id': 'b'}, 'invalid', {'id': 'b', 'resource': 'raw/a.md'}):
            with self.subTest(second=second):
                findings = self.check('延迟42ms。', sources=[{'id': 'a', 'resource': 'raw/a.md'}, second],
                                      extra={'raw/b.md': {'metadata': {}, 'body': '42ms'}})
                self.assertEqual(len(self.citations(findings)), 1)

    def test_single_intermediary_is_not_assumed_to_be_direct_transcription(self):
        for targets in ([{'resource': 'raw/a.md'}],
                        [{'resource': 'raw/a.md'}, {'resource': 'raw/b.md'}]):
            with self.subTest(targets=targets):
                findings = self.check('延迟42ms。', sources=[{'id': 'upstream', 'resource': 'wiki/concepts/a.md'}],
                    extra={'wiki/concepts/a.md': {'metadata': {'sources': targets}, 'body': '42ms'},
                           'raw/b.md': {'metadata': {}, 'body': '50%'}})
                self.assertEqual(len(self.citations(findings)), 1)

    def test_aggregate_pages_keep_inline_citations_even_with_one_raw(self):
        for directory in ('concepts', 'entities', 'analyses', 'hubs'):
            with self.subTest(directory=directory):
                self.assertEqual(len(self.citations(self.check('延迟42ms。', path=f'wiki/{directory}/a.md'))), 1)
                self.assertEqual(self.check('延迟42ms。[^a]\n\n[^a]: 原始素材', path=f'wiki/{directory}/a.md'), [])

    def test_pure_navigation_hub_is_exempt_but_visible_claims_are_checked(self):
        navigation = '## 子主题导航\n\n- [2026 年报告](report.md)\n'
        self.assertEqual(self.check(navigation, path='wiki/hubs/a.md', sources=[]), [])
        findings = self.check(navigation + '\n延迟42ms。', path='wiki/hubs/a.md', sources=[])
        self.assertEqual(len(self.citations(findings)), 1)
        self.assertTrue(any(f['problem'] == '知识页缺少来源证据' for f in findings))

    def test_navigation_hub_does_not_ignore_explicit_broken_citations(self):
        findings = self.check('## 子主题导航\n\n说明。[^missing]', path='wiki/hubs/a.md', sources=[])
        self.assertTrue(any(f['level'] == '🔴' and '没有对应来源 id' in f['problem'] for f in findings))
        self.assertTrue(any(f['level'] == '🔴' and '缺少脚注定义' in f['problem'] for f in findings))

    def test_cli_scope_is_read_only_and_preserves_raw_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            (kb / 'raw/a.md').write_text(page('source-material', 'A', '42ms'))
            (kb / 'wiki/summaries/a.md').write_text(page('source-summary', 'A',
                '## 摘要\n\n延迟42ms。\n\n## 关键要点\n\n延迟99ms。',
                sources=[{'resource': '../../raw/a.md'}]))
            before = snapshot(kb)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb),
                '--lint-files', 'wiki/summaries/a.md', '--fail-on', 'warning'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertNotIn('缺少逐条来源', result.stdout)
            self.assertIn('数值或引文证据待复核: 99ms', result.stdout)
            self.assertEqual(snapshot(kb), before)


if __name__ == '__main__':
    unittest.main()
