import subprocess
import sys
import tempfile
import unittest

from kb_fixture import ROOT, initialize_kb, page, snapshot
from wiki_config import load_schema
from wiki_evidence import EvidenceDocument, EvidenceIndex, claim_literals
from wiki_lint_report import build_report
from wiki_provenance import ProvenanceGraph, issue


class EvidencePriorityTests(unittest.TestCase):
    def detail(self, claim, raw):
        return EvidenceIndex([EvidenceDocument('raw/a.md', raw)]).diagnose(claim)[0]

    def test_ordinary_approximation_is_advice_without_becoming_an_exact_match(self):
        for claim, raw in [('50%', '约50%'), ('约50%', '50%'), ('50%左右', '50%'),
                           ('42ms', '大约0.042秒'), ('1.3至1.5', '1.3到1.5左右')]:
            with self.subTest(claim=claim, raw=raw):
                index = EvidenceIndex([EvidenceDocument('raw/a.md', raw)])
                detail = index.diagnose(claim)[0]
                self.assertEqual(detail['kind'], 'approximation-difference')
                self.assertEqual(detail['level'], '🔵')
                self.assertTrue(index.missing(claim))
                self.assertEqual(detail['candidates'][0]['literal'], raw)

    def test_boundaries_near_and_ordinals_remain_warnings(self):
        for claim, raw in [('50%', '超过50%'), ('低于50%', '50%'), ('50%以上', '超过50%'),
                           ('近20%', '20%'), ('约20%', '近20%'), ('2个', '第2个'),
                           ('50%', '至少50%'), ('50%', '50%以内')]:
            with self.subTest(claim=claim, raw=raw):
                detail = self.detail(claim, raw)
                self.assertEqual(detail['kind'], 'qualifier-difference')
                self.assertEqual(detail['level'], '🟡')

    def test_approximation_candidate_does_not_hide_competing_boundary_or_unit(self):
        for raw, kind in [('约50%，另有超过50%。', 'qualifier-difference'),
                          ('约5.63‰，另有5.63%。', 'unit-difference')]:
            with self.subTest(raw=raw):
                claim = '50%' if '50%' in raw else '5.63‰'
                detail = self.detail(claim, raw)
                self.assertEqual(detail['kind'], kind)
                self.assertEqual(detail['level'], '🟡')

    def test_unlocated_counts_dates_rates_and_derived_values_are_not_silenced(self):
        self.assertFalse(claim_literals('1、2、3'))
        for claim in ('一人', '一项', '重试两次', '其中一项失败', '1.362', '5.63‰',
                      '2026年6月7日至9日', '约5%'):
            with self.subTest(claim=claim):
                detail = self.detail(claim, '没有相应的数量表达。')
                self.assertEqual(detail['kind'], 'not-found')
                self.assertEqual(detail['level'], '🟡')

    def graph(self, body, sources=None):
        path = 'wiki/concepts/a.md'
        metadata = {'sources': sources or [{'id': 'a', 'resource': 'raw/a.md'}]}
        documents = {'raw/a.md': {'metadata': {}, 'body': '50%，5.63%。'},
                     'raw/official.md': {'metadata': {}, 'body': '5.63‰。'},
                     path: {'metadata': metadata, 'body': body, 'body_start_line': 10}}
        graph = ProvenanceGraph(ROOT, load_schema(), lambda _, target: {'relative': target}, documents)
        return graph.check(path, body, metadata)

    def test_mixed_fragment_keeps_warning_and_individual_advice_level(self):
        body = '约50%，5.63‰。[^a]\n\n[^a]: 原始材料'
        findings = self.graph(body)
        evidence = [f for f in findings if f.get('category') == 'evidence']
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['level'], '🟡')
        self.assertEqual({d['level'] for d in evidence[0]['details']}, {'🟡', '🔵'})
        report = build_report([('wiki/concepts/a.md', evidence[0])], 1)
        self.assertEqual(report.severity_counts['🟡'], 1)
        self.assertEqual(report.severity_counts['🔵'], 0)
        self.assertIn('🔵 主张 约50%', report.text)
        self.assertIn('| 数值相同，仅普通近似词不同 | 1 | 0 | 1 |', report.text)
        self.assertIn('| 数值部分相同但单位不同 | 1 | 1 | 0 |', report.text)

    def test_changed_verbatim_quote_is_not_downgraded_with_numeric_approximation(self):
        detail = self.detail('原文：「约50%」', '50%')
        self.assertEqual(detail['kind'], 'quote-not-found')
        self.assertEqual(detail['level'], '🟡')

    def test_calibration_needs_the_supporting_source_in_the_claim_citation(self):
        sources = [{'id': 'a', 'resource': 'raw/a.md'},
                   {'id': 'official', 'resource': 'raw/official.md'}]
        wrong = self.graph('5.63‰。[^a]\n\n[^a]: 原始口播', sources)
        self.assertTrue(any(f.get('details') and f['details'][0]['kind'] == 'unit-difference' for f in wrong))
        corrected = self.graph('5.63‰。[^official]\n\n[^official]: 支持采用值的独立原文', sources)
        self.assertFalse(any(f.get('category') == 'evidence' for f in corrected))

    def test_unlocated_queue_groups_by_page_and_preserves_every_detail(self):
        findings = []
        for path, text, line in [('wiki/a.md', '1.362、9人', 20),
                                 ('wiki/a.md', '2.718', 30), ('wiki/b.md', '99%', 40)]:
            details = EvidenceIndex([]).diagnose(text)
            findings.append((path, issue('🟡', '数值待复核', '', line, category='evidence', details=details)))
        report = build_report(findings, 2)
        self.assertEqual(report.severity_counts['🟡'], 3)
        self.assertIn('共 2 页、4 个未定位主张', report.text)
        self.assertIn('| [[wiki/a.md]]:20 | 3 |', report.text)
        self.assertIn('| [[wiki/b.md]]:40 | 1 |', report.text)
        self.assertIn('复核线索：', report.text)
        for literal in ('1.362', '9人', '2.718', '99%'):
            self.assertIn('主张 ' + literal, report.text)

    def test_cli_advice_does_not_fail_warning_threshold_and_is_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            (kb / 'raw/a.md').write_text(page('source-material', 'A', '50%'))
            summary = kb / 'wiki/summaries/a.md'
            summary.write_text(page('source-summary', 'A', '## 摘要\n\n约50%。\n\n## 关键要点\n\n转述。',
                sources=[{'id': 'a', 'resource': '../../raw/a.md'}]))
            index = kb / 'wiki/index.md'
            index.write_text(index.read_text().replace('## 素材来源', '## 素材来源\n\n- [[summaries/a]]')
                             .replace('素材: 0', '素材: 1'))
            before = snapshot(kb)
            for threshold, expected in [('warning', 0), ('any', 1)]:
                result = subprocess.run([sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb),
                    '--lint-files', 'wiki/summaries/a.md', '--fail-on', threshold], capture_output=True, text=True)
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
                self.assertIn('数值相同，仅普通近似词不同', result.stdout)
                self.assertIn('证据表达建议', result.stdout)
                self.assertNotIn('数值或引文证据待复核:', result.stdout)
                self.assertEqual(snapshot(kb), before)
            summary.write_text(summary.read_text().replace('约50%', '超过50%'))
            before = snapshot(kb)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb),
                '--lint-files', 'wiki/summaries/a.md', '--fail-on', 'warning'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(snapshot(kb), before)


if __name__ == '__main__':
    unittest.main()
