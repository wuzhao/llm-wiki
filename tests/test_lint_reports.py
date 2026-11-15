import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from kb_fixture import ROOT, initialize_kb, page, snapshot
from wiki_evidence import EvidenceIndex
from wiki_lint_report import build_report, finding_id
from wiki_provenance import issue


class LintReportTests(unittest.TestCase):
    def test_summary_counts_partial_reviews_without_changing_exit_levels(self):
        details = EvidenceIndex([]).diagnose('42ms、99%')
        details[0]['review'] = {'status': 'supported', 'reason': 'checked', 'reviewer': 'test'}
        findings = [('wiki/a.md', issue('🟡', 'candidate', '', category='evidence', details=details)),
                    ('wiki/b.md', issue('🔴', 'broken link', '', category='other'))]
        summary = build_report(findings, 2, details=False, page_limit=1)
        full = build_report(findings, 2)
        self.assertIn('已有有效复核记录 1 个，仍待复核 1 个', summary.text)
        self.assertIn('其中 0 条证据告警', summary.text)
        self.assertIn('显示 1 / 2', summary.text)
        self.assertIn('broken link', summary.text)
        self.assertNotIn('论断上下文', summary.text)
        self.assertEqual(summary.severity_counts, full.severity_counts)
        self.assertEqual(summary.unresolved_levels, full.unresolved_levels)
        self.assertIn(finding_id(*findings[1]), full.text)
        self.assertIn(finding_id(*findings[1]), summary.text)
        self.assertEqual(finding_id(*findings[1]), finding_id(*copy.deepcopy(findings[1])))

    def test_cli_filters_export_and_review_reuse_keep_the_full_scan_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(Path(directory) / 'kb')
            (kb / 'raw/a.md').write_text(page('source-material', 'A', 'one person succeeded'))
            (kb / 'wiki/summaries/a.md').write_text(page('source-summary', 'A',
                '## 摘要\n\n只有一人成功。\n\n## 关键要点\n\n描述。',
                sources=[{'id': 'a', 'resource': '../../raw/a.md'}]))
            (kb / 'wiki/concepts/b.md').write_text(page('concept', 'B',
                '## 来源\n\n[missing](missing-target.md)'))
            before = snapshot(kb)
            cmd = [sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb), '--fail-on', 'warning']
            def run(*args):
                return subprocess.run([*cmd, *args], capture_output=True, text=True)
            summary = run()
            full = run('--details')
            self.assertEqual(summary.returncode, 1)
            self.assertEqual(full.returncode, 1)
            self.assertLess(len(summary.stdout), len(full.stdout))
            self.assertNotIn('论断上下文', summary.stdout)
            self.assertIn('论断上下文', full.stdout)
            report = Path(directory) / 'report.md'
            template = Path(directory) / 'reviews.json'
            filtered = run('--report-page', 'wiki/summaries/a.md', '--report-category', 'evidence',
                           '--report-file', str(report), '--review-template', str(template))
            self.assertEqual(filtered.returncode, 1)
            view = filtered.stdout.split('以下为筛选详情', 1)[1]
            self.assertNotIn('missing-target', view)
            self.assertIn('missing-target', report.read_text())
            self.assertIn('论断上下文', report.read_text())
            data = json.loads(template.read_text())
            self.assertEqual(len(data['records']), 1)
            record = data['records'][0]
            record.update(status='supported', reason='原文表示一人成功，所指对象与摘要一致。',
                          reviewer='test', reviewed_at='2026-11-14T12:00:00Z',
                          evidence=[{'path': 'raw/a.md', 'quote': 'one person succeeded'}])
            template.write_text(json.dumps(data))
            reused = run('--review-file', str(template))
            self.assertEqual(reused.returncode, 1)
            self.assertIn('已有有效复核记录 1 个，仍待复核 0 个', reused.stdout)
            self.assertEqual(snapshot(kb), before)
            raw = kb / 'raw/a.md'
            raw.write_text(raw.read_text().replace('one person succeeded', 'nobody succeeded'))
            changed = snapshot(kb)
            stale = run('--review-file', str(template))
            self.assertIn('已有有效复核记录 0 个，仍待复核 1 个', stale.stdout)
            self.assertIn('未复用', stale.stdout)
            self.assertEqual(snapshot(kb), changed)

    def test_report_filter_does_not_change_repair_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(Path(directory) / 'kb')
            for name in ('a', 'b'):
                (kb / f'wiki/concepts/{name}.md').write_text(f'# {name}\n\n## 来源\n\n内容。\n')
            before = snapshot(kb)
            cmd = [sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb), '--fix', '--dry-run',
                   '--report-page', 'wiki/concepts/a.md', '--report-category', 'evidence']
            preview = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(preview.returncode, 0, preview.stderr)
            self.assertIn('计划修复；', preview.stdout)
            self.assertIn('wiki/concepts/b.md', preview.stdout)
            self.assertEqual(snapshot(kb), before)
            fixed = subprocess.run([arg for arg in cmd if arg != '--dry-run'], capture_output=True, text=True)
            self.assertEqual(fixed.returncode, 0, fixed.stderr)
            self.assertIn('已修复；', fixed.stdout)
            for name in ('a', 'b'):
                self.assertIn('type: concept', (kb / f'wiki/concepts/{name}.md').read_text())


if __name__ == '__main__':
    unittest.main()
