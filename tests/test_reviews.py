import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from kb_fixture import ROOT, initialize_kb, page, snapshot
from wiki_evidence import EvidenceIndex
from wiki_lint_report import build_report
from wiki_provenance import issue
from wiki_reviews import annotate_reviews, load_reviews


class ReviewTests(unittest.TestCase):
    def fixture(self):
        state = SimpleNamespace(originals={'wiki/a.md': '只有一人成功', 'raw/a.md': 'one person succeeded',
                                           'wiki/summary.md': '转述原文'}, errors={},
                                documents={'raw/a.md': {'body': 'one person succeeded'}})
        findings = [('wiki/a.md', issue('🟡', '待复核', '', 1, category='evidence',
                     sources=['raw/a.md'], review_dependencies=list(state.originals),
                     details=EvidenceIndex([]).diagnose('只有一人成功')))]
        return state, findings

    def approved(self):
        state, findings = self.fixture()
        data, _ = annotate_reviews(findings, state, [], 'rules-v1')
        record = data['records'][0]
        record.update(status='supported', reason='逐项核对原文所指对象。', reviewer='Agent',
                      reviewed_at='2026-11-08T12:00:00Z', evidence=[{'path': 'raw/a.md', 'quote': 'one person succeeded'}])
        return state, record

    def test_export_is_pending_and_reuse_does_not_change_severity(self):
        state, findings = self.fixture()
        data, stale = annotate_reviews(findings, state, [], 'rules-v1')
        self.assertEqual(data['records'][0]['status'], 'pending')
        self.assertNotIn('review', findings[0][1]['details'][0])
        state, approved = self.approved()
        _, findings = self.fixture()
        data, stale = annotate_reviews(findings, state, [approved], 'rules-v1')
        self.assertEqual(stale, 0)
        result = build_report(findings, 1)
        self.assertIn('0 组待复核，1 个主张已有有效复核记录', result.text)
        self.assertEqual(result.severity_counts['🟡'], 1)
        self.assertIn('🟡', result.unresolved_levels)

    def test_page_raw_intermediary_rules_or_quote_change_invalidates_review(self):
        for changed in ('wiki/a.md', 'raw/a.md', 'wiki/summary.md', 'rules', 'quote', 'identity', 'read-error'):
            with self.subTest(changed=changed):
                state, approved = self.approved()
                _, findings = self.fixture()
                rules = 'rules-v1'
                if changed == 'rules': rules = 'rules-v2'
                elif changed == 'quote': approved['evidence'][0]['quote'] = 'absent evidence'
                elif changed == 'identity': approved['context'] = 'different context'
                elif changed == 'read-error': state.errors['raw/b.md'] = 'unreadable'
                else: state.originals[changed] += ' changed'
                _, stale = annotate_reviews(findings, state, [approved], rules)
                self.assertEqual(stale, 1)
                self.assertNotIn('review', findings[0][1]['details'][0])

    def test_records_require_attribution_reason_evidence_and_unique_ids(self):
        _, approved = self.approved()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'reviews.json'
            path.write_text(json.dumps({'version': 1, 'records': [approved]}))
            self.assertEqual(len(load_reviews(path)), 1)
            for field, value in [('reason', ''), ('reviewer', ''), ('reviewed_at', 'yesterday'),
                                 ('status', 'ignore'), ('evidence', []), ('evidence', [{'path': 'raw/a.md', 'quote': ''}])]:
                record = copy.deepcopy(approved)
                record[field] = value
                path.write_text(json.dumps({'version': 1, 'records': [record]}))
                with self.assertRaises(ValueError): load_reviews(path)
            path.write_text(json.dumps({'version': 1, 'records': [approved, approved]}))
            with self.assertRaises(ValueError): load_reviews(path)

    def test_cli_export_and_reuse_are_read_only_and_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(Path(directory) / 'kb')
            (kb / 'raw/a.md').write_text(page('source-material', 'A', '其他描述'))
            (kb / 'wiki/summaries/a.md').write_text(page('source-summary', 'A',
                '## 摘要\n\n只有一人成功。\n\n## 关键要点\n\n描述。',
                sources=[{'id': 'a', 'resource': '../../raw/a.md'}]))
            before = snapshot(kb)
            target = Path(directory) / 'reviews.json'
            cmd = [sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb),
                   '--lint-files', 'wiki/summaries/a.md']
            result = subprocess.run(cmd + ['--review-template', str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(load_reviews(target))
            result = subprocess.run(cmd + ['--review-file', str(target), '--fail-on', 'warning'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(snapshot(kb), before)
            for output in (target, kb / 'reviews.json'):
                result = subprocess.run(cmd + ['--review-template', str(output)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
            self.assertEqual(snapshot(kb), before)


if __name__ == '__main__':
    unittest.main()
