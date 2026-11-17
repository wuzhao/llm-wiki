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
from wiki_reviews import annotate_reviews, load_reviews, metadata_evidence


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

    def test_export_is_pending_and_supported_unlocated_is_advisory(self):
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
        self.assertEqual(result.severity_counts['🔵'], 1)
        self.assertNotIn('🟡', result.unresolved_levels)
        self.assertIn('1 个未定位主张', result.text)

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
                self.assertEqual(findings[0][1]['level'], '🟡')

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

    def test_metadata_requires_explicit_field_and_exact_scalar_value(self):
        state, approved = self.approved()
        state.originals['raw/a.md'] = '---\ntimestamp: 2026-11-08T12:00:00Z\nduration: "16 秒"\npeople: 200\n---\n正文\n'
        state.documents['raw/a.md'] = {'body': '正文'}
        _, findings = self.fixture()
        data, _ = annotate_reviews(findings, state, [], 'rules-v1')
        record = {**data['records'][0], **{k: approved[k] for k in
                  ('status', 'reason', 'reviewer', 'reviewed_at')}}
        self.assertEqual([item['field'] for item in record['evidence_options']['metadata']], ['timestamp', 'duration'])
        for evidence, valid in [
            ({'field': 'timestamp', 'quote': '2026-11-08T12:00:00Z'}, True),
            ({'field': 'duration', 'quote': '16 秒'}, True),
            ({'quote': '16 秒'}, False),
            ({'field': 'duration', 'quote': '16'}, False),
            ({'field': 'timestamp', 'quote': '16 秒'}, False),
            ({'field': 'people', 'quote': '200'}, False),
        ]:
            with self.subTest(evidence=evidence):
                record['evidence'] = [{'path': 'raw/a.md', **evidence}]
                _, findings = self.fixture()
                data, stale = annotate_reviews(findings, state, [record], 'rules-v1')
                self.assertEqual(stale, 0 if valid else 1)
                self.assertEqual(data['records'][0]['status'], 'supported' if valid else 'pending')
        for content in ('---\nduration: 16\nduration: 17\n---\n',
                        '---\nduration: [16, 17]\n---\n', '---\nduration: true\n---\n'):
            self.assertEqual(metadata_evidence(content), [])

    def test_cross_page_review_requires_route_and_tracks_transitive_dependencies(self):
        state, approved = self.approved()
        state.originals.update({'wiki/linked.md': '链接页', 'wiki/intermediate.md': '中间页',
                                'raw/linked.md': 'only one succeeded'})
        state.documents['raw/linked.md'] = {'body': 'only one succeeded'}

        def findings():
            _, result = self.fixture()
            result[0][1]['cross_page_sources'] = {'wiki/linked.md': ['raw/linked.md']}
            result[0][1]['review_dependencies'] = list(state.originals)
            return result

        data, _ = annotate_reviews(findings(), state, [], 'rules-v1')
        record = {**data['records'][0], **{k: approved[k] for k in
                  ('status', 'reason', 'reviewer', 'reviewed_at')}}
        for via, valid in [(None, False), ('wiki/unrelated.md', False), ('wiki/linked.md', True)]:
            record['evidence'] = [{'path': 'raw/linked.md', 'quote': 'only one succeeded',
                                   **({'via': via} if via else {})}]
            data, stale = annotate_reviews(findings(), state, [record], 'rules-v1')
            self.assertEqual(stale, 0 if valid else 1)
        for path in ('wiki/linked.md', 'wiki/intermediate.md', 'raw/linked.md'):
            changed = copy.deepcopy(state)
            changed.originals[path] += ' changed'
            _, stale = annotate_reviews(findings(), changed, [record], 'rules-v1')
            self.assertEqual(stale, 1)

    def test_different_cross_page_routes_are_not_grouped_as_one_scope(self):
        _, first = self.fixture()
        _, second = self.fixture()
        first[0][1]['cross_page_sources'] = {'wiki/b.md': ['raw/b.md']}
        second[0][1]['cross_page_sources'] = {'wiki/c.md': ['raw/c.md']}
        self.assertIn('合为 2 组', build_report(first + second, 1).text)

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

    def test_cli_cross_page_scope_metadata_and_review_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(Path(directory) / 'kb')
            (kb / 'raw/a.md').write_text(page('source-material', 'A', '正文没有目标数值。'))
            (kb / 'raw/b.md').write_text(page('source-material', 'B', '总共不到200人。', duration='16 秒'))
            (kb / 'wiki/summaries/b.md').write_text(page('source-summary', 'B', '## 数据\n\n人数说明。',
                sources=[{'resource': '../../raw/b.md'}]))
            owner = kb / 'wiki/summaries/a.md'
            cmd = [sys.executable, str(ROOT / 'scripts/lint_wiki.py'), str(kb),
                   '--lint-files', 'wiki/summaries/a.md', '--details', '--fail-on', 'warning']
            cases = [
                ('[乙](b.md)：不足200人。', True),
                ('[[summaries/b|乙]]：不足200人。', True),
                ('[乙][b]：不足200人。\n\n[b]: b.md', True),
                ('[乙](b.md#数据)：不足200人。', True),
                ('[乙](b.md#不存在)：不足200人。', False),
                ('[乙](b.md)\n\n不足200人。', False),
                ('- [乙](b.md)\n- 不足200人。', False),
                ('| [乙](b.md) |\n| --- |\n| 不足200人。 |', False),
                ('`[乙](b.md)`：不足200人。', False),
                ('<!-- [乙](b.md) -->不足200人。', False),
                ('![乙](b.md)：不足200人。', False),
                ('![[summaries/b]]：不足200人。', False),
                ('[乙](https://example.com)：不足200人。', False),
                ('[甲](a.md)：不足200人。', False),
                ('[原文](../../raw/b.md)：不足200人。', False),
                ('[乙](b.md)说明。[^a]不足200人。\n\n[^a]: 甲', False),
            ]
            for index, (body, allowed) in enumerate(cases):
                with self.subTest(body=body):
                    owner.write_text(page('source-summary', 'A', '## 相关页面\n\n' + body,
                        sources=[{'id': 'a', 'resource': '../../raw/a.md'}]))
                    target = Path(directory) / f'reviews-{index}.json'
                    before = snapshot(kb)
                    result = subprocess.run(cmd + ['--review-template', str(target)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertEqual(snapshot(kb), before)
                    record = load_reviews(target)[0]
                    routes = record['evidence_options']['cross_page_sources']
                    self.assertEqual(routes, {'wiki/summaries/b.md': ['raw/b.md']} if allowed else {})
                    self.assertEqual('raw/b.md' in record['dependencies'], allowed)

            owner.write_text(page('source-summary', 'A', '## 相关页面\n\n[乙](b.md)：不足200人，视频时长16秒。',
                sources=[{'resource': '../../raw/a.md'}]))
            target = Path(directory) / 'approved.json'
            result = subprocess.run(cmd + ['--review-template', str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            data = json.loads(target.read_text())
            self.assertEqual(len(data['records']), 2)
            for record in data['records']:
                evidence = {'path': 'raw/b.md', 'via': 'wiki/summaries/b.md', 'quote': '总共不到200人'}
                if record['claim'] == '16秒':
                    evidence.update(field='duration', quote='16 秒')
                record.update(status='supported', reason='核对乙页所指来源及人数限定或视频时长。',
                              reviewer='Agent', reviewed_at='2026-11-16T12:00:00Z', evidence=[evidence])
            target.write_text(json.dumps(data, ensure_ascii=False))
            before = snapshot(kb)
            result = subprocess.run(cmd + ['--review-file', str(target)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('已有有效复核记录 2 个', result.stdout)
            self.assertIn('元数据复核入口', result.stdout)
            self.assertEqual(snapshot(kb), before)
            # Cyclic or incomplete linked source chains do not grant a route.
            for resource in ('b.md', 'missing.md', 'a.md'):
                linked = kb / 'wiki/summaries/b.md'
                linked.write_text(page('source-summary', 'B', '说明。', sources=[
                    {'resource': '../../raw/b.md'}, {'resource': resource}]))
                result = subprocess.run(cmd + ['--review-file', str(target)], capture_output=True, text=True)
                self.assertIn('已有有效复核记录 0 个', result.stdout)
                self.assertNotIn('跨页复核入口', result.stdout)


if __name__ == '__main__':
    unittest.main()
