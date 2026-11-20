import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb_fixture import ROOT, initialize_kb, page, snapshot
import test_reviews
from wiki_evidence import EvidenceIndex
from wiki_lint_report import build_report
from wiki_review_policy import claim_category
from wiki_reviews import annotate_reviews, checker_fingerprint, compatible_review_rules, load_reviews
from review_quality import audit_samples


class ReviewPolicyTests(unittest.TestCase):
    def test_explicit_categories(self):
        for text, category in (
            ('只有一人成功', 'direct'), ('原文说：「唯一的赢家」', 'direct'),
            ('**2025年**共有42人', 'direct'),
            ('2026/11/17', 'direct'),
            ('计算得到42人', 'derived'), ('合计42人', 'derived'),
            ('20 + 22 = 42人', 'derived'), ('换算后约42人', 'derived'),
            ('约42人', 'approximate'), ('近42人', 'approximate'),
            ('十余年', 'approximate'), ('约半年', 'approximate'), ('半年左右', 'approximate'),
            ('估算得到十余年', 'derived'), ('十小时', 'direct'), ('半年', 'direct'),
            ('大约16秒', 'approximate'), ('四五十人', 'approximate'),
        ):
            with self.subTest(text=text):
                details = EvidenceIndex([]).diagnose(text)
                self.assertTrue(details)
                for detail in details:
                    self.assertEqual(claim_category(detail), category)
        # Processing marker can be outside the displayed excerpt.
        detail = EvidenceIndex([]).diagnose('42人')[0]
        detail['review_context'] = '计算得到' + '说明' * 80 + '42人'
        self.assertEqual(claim_category(detail), 'derived')

    def test_legacy_alias_preserves_identity_and_invalidates_on_content_or_rules(self):
        fixture = test_reviews.ReviewTests()
        state, record = fixture.approved()
        for key in ('review_policy', 'category', 'source_values', 'derivation',
                    'approximation_span', 'human_confirmation'):
            record.pop(key)
        original = copy.deepcopy(record)
        with patch('wiki_reviews.compatible_review_rules', return_value=['rules-v1']), \
                patch('wiki_reviews.legacy_review_rules', return_value=['rules-v1']):
            _, findings = fixture.fixture()
            data, stale = annotate_reviews(findings, state, [record], 'rules-v2')
            self.assertEqual(stale, 0)
            self.assertEqual(findings[0][1]['level'], '🔵')
            self.assertEqual(data['records'][0]['id'], record['id'])
            self.assertNotIn('review_policy', data['records'][0])
            self.assertEqual(record, original)
            state.originals['raw/a.md'] += 'changed'
            _, findings = fixture.fixture()
            data, stale = annotate_reviews(findings, state, [record], 'rules-v2')
            self.assertEqual(stale, 1)
            self.assertEqual(data['records'][0]['status'], 'pending')
            self.assertEqual(findings[0][1]['level'], '🟡')
        self.assertEqual(compatible_review_rules('changed-rules'), [])

    def test_terminal_reviews_lower_direct_warnings_across_diagnostics(self):
        fixture = test_reviews.ReviewTests()
        _, approved = fixture.approved()
        for kind in ('unit-difference', 'qualifier-difference', 'predicate-count', 'translated-count',
                     'year-abbreviation', 'not-found', 'quote-not-found'):
            for status in ('supported', 'non-quantity', 'author-structure'):
                with self.subTest(kind=kind, status=status):
                    state, findings = fixture.fixture()
                    findings[0][1]['details'][0]['kind'] = kind
                    data, _ = annotate_reviews(findings, state, [], 'rules-v1')
                    record = data['records'][0]
                    record.update({k: approved[k] for k in ('reason', 'reviewer', 'reviewed_at')})
                    record.update(status=status, evidence=approved['evidence'] if status == 'supported' else [])
                    annotate_reviews(findings, state, [record], 'rules-v1')
                    self.assertEqual(findings[0][1]['level'], '🔵')
                    state.originals['wiki/a.md'] += ' changed'
                    _, stale = annotate_reviews(findings, state, [record], 'rules-v1')
                    self.assertEqual(stale, 1)
                    self.assertEqual(findings[0][1]['level'], '🟡')

    def test_mixed_warning_waits_even_for_an_originally_blue_candidate(self):
        fixture = test_reviews.ReviewTests()
        state, findings = fixture.fixture()
        details = findings[0][1]['details']
        details.append(EvidenceIndex.detail('42人', 'unit-missing', '共有42人', 2, 5, []))
        _, approved = fixture.approved()
        data, _ = annotate_reviews(findings, state, [], 'rules-v1')
        for record in data['records']:
            record.update({k: approved[k] for k in ('status', 'reason', 'reviewer', 'reviewed_at', 'evidence')})
        data['records'][0].update(status='non-quantity', evidence=[])
        annotate_reviews(findings, state, data['records'][:1], 'rules-v1')
        self.assertEqual([d['level'] for d in details], ['🔵', '🔵'])
        self.assertEqual(findings[0][1]['level'], '🟡')
        annotate_reviews(findings, state, data['records'], 'rules-v1')
        self.assertEqual(findings[0][1]['level'], '🔵')
        annotate_reviews(findings, state, [], 'rules-v1')
        self.assertEqual(findings[0][1]['level'], '🟡')
        self.assertEqual([d['level'] for d in details], ['🟡', '🔵'])

    def test_gated_non_quantity_and_author_structure_require_confirmation_to_downgrade(self):
        fixture = test_reviews.ReviewTests()
        _, approved = fixture.approved()
        for text in ('合计42人', '约40人'):
            for status in ('non-quantity', 'author-structure'):
                with self.subTest(text=text, status=status):
                    state, findings = fixture.fixture()
                    findings[0][1]['details'] = EvidenceIndex([]).diagnose(text)
                    data, _ = annotate_reviews(findings, state, [], 'rules-v1')
                    record = data['records'][0]
                    record.update({k: approved[k] for k in ('reason', 'reviewer', 'reviewed_at')})
                    record['status'] = status
                    annotate_reviews(findings, state, [record], 'rules-v1')
                    report = build_report(findings, 1)
                    self.assertEqual(report.severity_counts['🟡'], 1)
                    self.assertIn('仍待复核 0 个', report.text)
                    self.assertIn('降级仍需人工确认', report.text)
                    record['human_confirmation'] = {'reviewer': 'Phan', 'confirmed_at': approved['reviewed_at']}
                    annotate_reviews(findings, state, [record], 'rules-v1')
                    self.assertEqual(findings[0][1]['level'], '🔵')

    @patch('wiki_reviews.compatible_review_rules', return_value=['rules-v1'])
    @patch('wiki_reviews.legacy_review_rules', return_value=['rules-v1'])
    def test_compatibility_accepts_legacy_gated_claims_only(self, *_):
        current = 'rules-v2'
        legacy = 'rules-v1'
        for text in ('计算得到42人', '约40人'):
            state, findings = test_reviews.ReviewTests().fixture()
            findings[0][1]['details'] = EvidenceIndex([]).diagnose(text)
            data, _ = annotate_reviews(findings, state, [], legacy)
            record = data['records'][0]
            for field in ('review_policy', 'category', 'source_values', 'derivation',
                          'approximation_span', 'human_confirmation'):
                record.pop(field)
            _, approved = test_reviews.ReviewTests().approved()
            record.update({k: approved[k] for k in ('status', 'reason', 'reviewer', 'reviewed_at', 'evidence')})
            data, stale = annotate_reviews(findings, state, [record], current)
            self.assertEqual(stale, 0)
            self.assertEqual(findings[0][1]['level'], '🟡')
            self.assertIn('仍待复核 0 个', build_report(findings, 1).text)
            self.assertEqual(data['records'][0]['id'], record['id'])
            record['human_confirmation'] = {'reviewer': 'unchecked'}
            annotate_reviews(findings, state, [record], current)
            self.assertEqual(findings[0][1]['level'], '🟡')
            record['status'] = 'pending'
            data, _ = annotate_reviews(findings, state, [record], current)
            self.assertEqual(data['records'][0]['review_policy'], 2)
            self.assertEqual(findings[0][1]['level'], '🟡')
            # Dropping new fields from a current record cannot claim legacy approval.
            forged = {**record, 'id': data['records'][0]['id'], 'rules': current, 'status': 'supported'}
            data, stale = annotate_reviews(findings, state, [forged], current)
            self.assertEqual(stale, 1)
            self.assertEqual(findings[0][1]['level'], '🟡')

    def test_cli_proposal_confirmation_and_hash_invalidation(self):
        for claim, category, explanation, value in (
            ('计算得到42人', 'derived', 'derivation', '20人 + 22人 = 42人'),
            ('约40人', 'approximate', 'approximation_span', '42人取整到十位，误差2人'),
        ):
            with self.subTest(category=category), tempfile.TemporaryDirectory() as directory:
                kb = initialize_kb(Path(directory) / 'kb')
                raw = kb / 'raw/a.md'
                raw.write_text(page('source-material', 'A', '甲组20人，乙组22人。'))
                owner = kb / 'wiki/summaries/a.md'
                owner.write_text(page('source-summary', 'A', f'## 摘要\n\n{claim}。[^a]\n\n## 关键要点\n\n人数说明。\n\n[^a]: 原文',
                                      sources=[{'id': 'a', 'resource': '../../raw/a.md'}]))
                index = kb / 'wiki/index.md'
                index.write_text(index.read_text().replace('素材: 0', '素材: 1').replace(
                    '## 素材来源', '## 素材来源\n\n- [[wiki/summaries/a.md]]'))
                cmd = [sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb),
                       '--lint-files', 'wiki/summaries/a.md', '--fail-on', 'warning', '--details']
                target = Path(directory) / 'reviews.json'
                first = subprocess.run(cmd + ['--review-template', str(target)], capture_output=True, text=True)
                self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
                data = json.loads(target.read_text())
                self.assertEqual(len(data['records']), 1)
                record = data['records'][0]
                self.assertEqual(record['category'], category)
                record.update(status='proposed-supported', reason='原文分量及推导已列出，请人工核验。',
                              reviewer='automatic', reviewed_at='2026-11-17T12:00:00Z',
                              evidence=[{'path': 'raw/a.md', 'quote': '甲组20人，乙组22人。'}])
                target.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'source_values'):
                    load_reviews(target)
                record.update(source_values='甲组20人，乙组22人', **{explanation: value})
                target.write_text(json.dumps(data))
                before = snapshot(kb)
                proposal = subprocess.run(cmd + ['--review-file', str(target)], capture_output=True, text=True)
                self.assertEqual(proposal.returncode, 1, proposal.stdout + proposal.stderr)
                self.assertIn('仍待复核 1 个', proposal.stdout)
                self.assertIn('待人工确认', proposal.stdout)
                self.assertIn(value, proposal.stdout)
                record['status'] = 'supported'
                target.write_text(json.dumps(data))
                with self.assertRaisesRegex(ValueError, 'human_confirmation'):
                    load_reviews(target)
                record['human_confirmation'] = {'reviewer': 'Phan', 'confirmed_at': '2026-11-17T13:00:00Z'}
                target.write_text(json.dumps(data))
                confirmed = subprocess.run(cmd + ['--review-file', str(target)], capture_output=True, text=True)
                self.assertEqual(confirmed.returncode, 0, confirmed.stdout + confirmed.stderr)
                self.assertIn('仍待复核 0 个', confirmed.stdout)
                self.assertIn('1 个未定位主张', confirmed.stdout)
                self.assertEqual(snapshot(kb), before)
                any_level = subprocess.run(cmd + ['--review-file', str(target), '--fail-on', 'any'], capture_output=True, text=True)
                self.assertEqual(any_level.returncode, 1)
                record['category'] = 'direct'  # Relabeling cannot bypass the gate.
                target.write_text(json.dumps(data))
                forged = subprocess.run(cmd + ['--review-file', str(target)], capture_output=True, text=True)
                self.assertEqual(forged.returncode, 1)
                self.assertIn('仍待复核 1 个', forged.stdout)
                record['category'] = category
                target.write_text(json.dumps(data))
                raw.write_text(raw.read_text() + '\n新内容\n')
                changed = subprocess.run(cmd + ['--review-file', str(target)], capture_output=True, text=True)
                self.assertEqual(changed.returncode, 1)
                self.assertIn('仍待复核 1 个', changed.stdout)


class ReviewQualityTests(unittest.TestCase):
    def samples(self):
        return [{'id': f'{category}-{i}', 'category': category, 'source': '甲20人，乙22人。',
                 'quote': '甲20人，乙22人。', 'claim': '共420人', 'flaw': '加法错误',
                 'status': 'supported' if i == 0 else 'unsupported'}
                for category in ('derived', 'approximate') for i in range(20)]

    def test_rates_are_per_category_and_only_high_volume_gates(self):
        samples = self.samples()
        result = audit_samples(samples, weekly_pending=21)
        self.assertTrue(result['automatic_proposals_allowed'])
        self.assertEqual(result['categories']['derived']['false_support_rate'], 0.05)
        samples[1]['status'] = 'proposed-supported'
        result = audit_samples(samples, weekly_pending=21)
        self.assertFalse(result['automatic_proposals_allowed'])
        self.assertTrue(result['categories']['approximate']['passed'])
        self.assertTrue(audit_samples(samples, weekly_pending=20)['automatic_proposals_allowed'])
        self.assertFalse(audit_samples([], weekly_pending=21)['automatic_proposals_allowed'])

    def test_injection_checks_real_quote_and_hides_answer(self):
        def reviewer(sample):
            self.assertNotIn('flaw', sample)
            self.assertNotIn('status', sample)
            return 'pending'
        self.assertTrue(audit_samples(self.samples(), reviewer)['categories']['derived']['passed'])
        bad = self.samples()
        bad[0]['quote'] = '不存在的引文'
        with self.assertRaises(ValueError):
            audit_samples(bad)
