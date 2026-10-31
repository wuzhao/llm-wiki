import tempfile
import unittest
import subprocess
import sys

from kb_fixture import ROOT, initialize_kb, page, snapshot
from wiki_evidence import EvidenceDocument, EvidenceIndex, missing_literals
from wiki_lint_report import build_report
from wiki_provenance import ProvenanceGraph, claim_blocks, issue
from wiki_config import load_schema


class EvidenceDiagnosticTests(unittest.TestCase):
    def test_exact_ratio_conversions_preserve_qualifiers_ranges_and_signs(self):
        for left, right in [('5.63‰', '0.563%'), ('-2.41‰', '-0.241%'),
                            ('约3‰', '约0.3%'), ('4‰至5‰', '0.4%至0.5%'),
                            ('百分之零点五六三', '5.63‰')]:
            with self.subTest(left=left):
                self.assertEqual(missing_literals(left, right), [])
                self.assertEqual(missing_literals(right, left), [])
        for left, right in [('5.63‰', '5.63%'), ('5.63‰', '0.563个百分点'),
                            ('5.63‰', '0.00563'), ('-2.41‰', '0.241%'),
                            ('约3‰', '0.3%'), ('4‰至5‰', '0.4%、0.5%')]:
            with self.subTest(left=left):
                self.assertTrue(missing_literals(left, right))
        self.assertEqual(missing_literals('原文：「5.63‰」', '0.563%'), ['5.63‰'])

    def test_candidates_are_diagnostics_not_acceptance(self):
        body = '记录\r\n出生率5.63%，人口减少339万。'
        index = EvidenceIndex([EvidenceDocument('raw/a.md', body, 12)])
        details = {d['claim']: d for d in index.diagnose('出生率5.63‰，减少339万人，另有9个人。')}
        self.assertEqual(details['5.63‰']['kind'], 'unit-difference')
        self.assertEqual(details['339万人']['kind'], 'unit-missing')
        self.assertEqual(details['9个']['kind'], 'not-found')
        candidate = details['5.63‰']['candidates'][0]
        self.assertEqual((candidate['line'], candidate['column']), (13, 4))
        self.assertEqual(body[candidate['start']:candidate['end']], '5.63%')
        self.assertEqual(set(index.missing('5.63‰，339万人')), {'5.63‰', '339万人'})

    def test_candidates_require_complete_shape_and_qualifier(self):
        for claim, source in [('5.63‰', '约5.63%'), ('-5.63‰', '5.63%'),
                              ('4‰至5‰', '4%、5%'), ('1亿人', '1亿9100万'),
                              ('2026年6月7日', '2026年6月8日')]:
            detail = EvidenceIndex([EvidenceDocument('raw/a.md', source)]).diagnose(claim)[0]
            self.assertEqual(detail['candidate_count'], 0, (claim, source))

    def test_quotes_cannot_be_joined_across_documents(self):
        index = EvidenceIndex([EvidenceDocument('a', '原句上半'), EvidenceDocument('b', '原句下半')])
        self.assertEqual(index.diagnose('原文：「原句上半原句下半」')[0]['kind'], 'quote-not-found')

    def graph(self, body, raw_a='5.63%，减少339万。', raw_b='99ms'):
        documents = {
            'raw/a.md': {'metadata': {}, 'body': raw_a, 'body_start_line': 10},
            'raw/b.md': {'metadata': {}, 'body': raw_b, 'body_start_line': 20},
            'wiki/concepts/c.md': {'metadata': {'sources': [
                {'id': 'a', 'resource': 'raw/a.md'}, {'id': 'b', 'resource': 'raw/b.md'}]}, 'body': body}}
        graph = ProvenanceGraph(ROOT, load_schema(), lambda _, target: {'relative': target}, documents)
        return graph.check('wiki/concepts/c.md', body, documents['wiki/concepts/c.md']['metadata'])

    def test_missing_footnote_is_distinct_from_missing_evidence(self):
        findings = self.graph('99ms\n\n5.63‰、339万人。[^a]\n\n[^a]: A')
        citations = [i for i in findings if i.get('category') == 'citation']
        evidence = [i for i in findings if i.get('category') == 'evidence']
        self.assertEqual(len(citations), 1)
        self.assertIn('尚未核对证据', citations[0]['action'])
        self.assertEqual(len(evidence), 1)
        self.assertEqual({d['kind'] for d in evidence[0]['details']}, {'unit-difference', 'unit-missing'})
        self.assertEqual(evidence[0]['line'], 3)

    def test_source_scopes_and_broken_references(self):
        findings = self.graph('99ms[^a]\n\n99ms[^missing]\n\n[^a]: A')
        evidence = [i for i in findings if i.get('category') == 'evidence']
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['details'][0]['candidate_count'], 0)
        self.assertTrue(any(i['level'] == '🔴' for i in findings))

    def test_other_available_source_cannot_hide_unavailable_claim_chain(self):
        body = '42ms[^external]'
        metadata = {'sources': [{'id': 'a', 'resource': 'raw/a.md'},
                                {'id': 'external', 'resource': 'https://example.com'}]}
        documents = {'wiki/concepts/c.md': {'metadata': metadata, 'body': body},
                     'raw/a.md': {'metadata': {}, 'body': '42ms'}}
        graph = ProvenanceGraph(ROOT, load_schema(),
            lambda _, target: {'external': True} if target.startswith('https:') else {'relative': target}, documents)
        findings = graph.check('wiki/concepts/c.md', body, metadata)
        self.assertTrue(any(i['problem'] == '该条引用无法回查 raw 证据' for i in findings))

    def test_common_candidate_locations_use_each_claim_line(self):
        findings = self.graph('5.63‰、\n339万人。[^a]\n\n[^a]: A')
        evidence = next(i for i in findings if i.get('details'))
        self.assertEqual({d['claim']: d['line'] for d in evidence['details']}, {'5.63‰': 1, '339万人': 2})

    def test_shared_table_scope_row_override_and_following_paragraph(self):
        body = ('本表来源：[^a]\n\n| 指标 | 数量 |\n| --- | ---: |\n'
                '| 甲 | 42ms |\n| 乙 | 99ms[^b] |\n| 丙 | 99ms |\n\n'
                '后文42ms。\n\n[^a]: A\n[^b]: B')
        findings = self.graph(body, raw_a='42ms')
        evidence = [i for i in findings if i.get('category') == 'evidence']
        citation = [i for i in findings if i.get('category') == 'citation']
        self.assertEqual(len(evidence), 1)
        self.assertEqual(evidence[0]['line'], 7)
        self.assertIn('99ms', evidence[0]['problem'])
        self.assertEqual(len(citation), 1)
        self.assertEqual(citation[0]['line'], 9)

    def test_table_scope_requires_explicit_adjacent_caption_and_valid_table(self):
        for caption in ['来源：[^a]', '本表来源：[^a]\n\n另一段', '本表来源：[^a]\n\n']:
            body = caption + '\n| 指标 | 数量 |\n| --- | --- |\n| 甲 | 42ms |'
            blocks = list(claim_blocks(body))
            self.assertFalse(any(text.endswith('|[^a]') for _, text in blocks), caption)
        body = '本表来源：[^a]\n| 指标 | 数量 |\n| 错误 | 分隔 |\n| 甲 | 42ms |'
        self.assertEqual(len(list(claim_blocks(body))), 1)

    def test_report_groups_only_unique_shared_candidates_and_retains_context(self):
        index = EvidenceIndex([EvidenceDocument('raw/a.md', '出生率5.63%。')])
        findings = [(path, issue('🟡', '待复核', '', 7, category='evidence', details=index.diagnose(claim)))
                    for path, claim in [('wiki/a.md', '甲地5.63‰'), ('wiki/b.md', '乙地5.63‰')]]
        findings.append(('wiki/c.md', issue('🟡', '缺脚注', '尚未核对证据', 2, category='citation')))
        report = build_report(findings, 3)
        self.assertEqual(report.severity_counts['🟡'], 3)
        self.assertEqual(report.unresolved_levels, {'🟡'})
        self.assertIn('#### 引用完整性 (1)', report.text)
        self.assertIn('共同原文候选', report.text)
        self.assertIn('甲地5.63‰', report.text)
        self.assertIn('乙地5.63‰', report.text)
        index = EvidenceIndex([EvidenceDocument('raw/a.md', '甲5.63%，乙5.63%。')])
        for _, finding in findings[:2]:
            finding['details'] = index.diagnose('5.63‰')
        self.assertNotIn('共同原文候选', build_report(findings, 3).text)

    def test_candidate_limit_and_markdown_escaping(self):
        index = EvidenceIndex([EvidenceDocument('raw/a.md', '<b> [假的](link) ' + '5.63%；' * 5)])
        details = index.diagnose('5.63‰')
        self.assertEqual(details[0]['candidate_count'], 5)
        self.assertEqual(len(details[0]['candidates']), 3)
        report = build_report([('a', issue('🟡', '待复核', '', details=details))], 1).text
        self.assertIn('共 5 处候选', report)
        self.assertNotIn('<b>', report)
        self.assertNotIn('[假的](link)', report)

    def test_cli_positions_warning_exit_and_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            raw = page('source-material', 'A', '开头\n出生率5.63%，减少339万。')
            (kb / 'raw/a.md').write_text(raw)
            (kb / 'wiki/concepts/a.md').write_text(page('concept', 'A',
                '5.63‰，339万人。[^a]\n\n[^a]: A', sources=[{'id': 'a', 'resource': '../../raw/a.md'}]))
            before = snapshot(kb)
            result = subprocess.run([sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb),
                                     '--lint-files', 'wiki/concepts/a.md', '--fail-on', 'warning'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            line = raw[:raw.index('出生率')].count('\n') + 1
            self.assertIn(f'[[raw/a.md]]:{line}，列 4', result.stdout)
            self.assertIn('单位省略或补全', result.stdout)
            self.assertEqual(snapshot(kb), before)
