import copy
import json
import subprocess
import sys
import tempfile
import unittest

from kb_fixture import ROOT, initialize_kb, page, snapshot
from wiki_config import load_schema
from wiki_fragments import fragment_changes, select_fragments, source_fragments
from wiki_metadata import body_sha256, split_frontmatter
from wiki_provenance import ProvenanceGraph


BODY = '# 实验\n\n## 结果\n\n延迟为42ms。\n\n### 条件\n\n仅限本地。\n\n## 维护\n\n旧注记。\n'


class SourceFragmentTests(unittest.TestCase):
    def document(self, body=BODY):
        return {'body': body, 'metadata': {}, 'body_start_line': 10}

    def source(self):
        return {'id': 'a', 'resource': 'raw/a.md', 'body_sha256': body_sha256(BODY),
                'fragments': select_fragments(self.document(), ['结果'])}

    def graph(self, body, source=None, downstream=False):
        documents = {'raw/a.md': self.document(body),
                     'wiki/concepts/a.md': {'body': '转述。', 'metadata': {'sources': [
                         self.source() if source is None else source]}}}
        if downstream:
            documents['wiki/analyses/b.md'] = {'body': '归档。', 'metadata': {'sources': [
                {'resource': 'wiki/concepts/a.md'}]}}
        return ProvenanceGraph(ROOT, load_schema(), lambda _, target: {'relative': target}, documents)

    def drift_findings(self, graph, path='wiki/concepts/a.md'):
        document = graph.documents[path]
        return [f for f in graph.check(path, document['body'], document['metadata'])
                if f['problem'].startswith('来源依赖')]

    def test_outside_change_is_advice_and_propagates_without_becoming_warning(self):
        graph = self.graph(BODY.replace('旧注记', '新注记并补充脚注'), downstream=True)
        for path in ('wiki/concepts/a.md', 'wiki/analyses/b.md'):
            finding, = self.drift_findings(graph, path)
            self.assertEqual(finding['level'], '🔵')
            self.assertIn('引用片段未变', finding['problem'])
            self.assertFalse(graph.dependency_drift(path))

    def test_section_descendant_and_parent_context_changes_remain_warnings(self):
        for body in (BODY.replace('42ms', '99ms'), BODY.replace('仅限本地', '仅限远程'),
                     BODY.replace('# 实验', '# 另一实验')):
            with self.subTest(body=body):
                graph = self.graph(body, downstream=True)
                finding, = self.drift_findings(graph, 'wiki/analyses/b.md')
                self.assertEqual(finding['level'], '🟡')
                self.assertIn('片段「结果」指纹已变化', finding['problem'])
                self.assertIn('当前行 12', finding['problem'])
                self.assertIn('不覆盖历史结论', finding['action'])

    def test_missing_renamed_and_ambiguous_headings_need_review(self):
        for body, reason in [(BODY.replace('## 结果', '## 新结果'), '已删除或标题已改名'),
                             (BODY + '\n## 结果\n\n其他。\n', '标题不唯一')]:
            finding, = self.drift_findings(self.graph(body))
            self.assertEqual(finding['level'], '🟡')
            self.assertIn(reason, finding['problem'])

    def test_section_relocation_survives_line_shifts(self):
        body = BODY.replace('# 实验\n', '# 实验\n\n增加引言。\n')
        self.assertEqual(fragment_changes(self.document(body), self.source()['fragments']), [])
        self.assertNotEqual(select_fragments(self.document(body), ['结果'])[0]['line'],
                            self.source()['fragments'][0]['line'])

    def test_only_boundary_newlines_are_normalized(self):
        expected = self.source()['fragments']
        for body in (BODY.replace('\n', '\r\n'), BODY.replace('\n## 维护', '\n\n\n## 维护')):
            self.assertEqual(fragment_changes(self.document(body), expected), [])
        for body in (BODY.replace('42ms', '42 ms'), BODY.replace('仅限本地', '**仅限本地**'),
                     BODY.replace('延迟', '    延迟'), BODY.replace('42ms。', '42ms。  ')):
            self.assertTrue(fragment_changes(self.document(body), expected))

    def test_code_comments_and_footnotes_inside_section_are_hashed(self):
        body = '# 结果\n\n```md\n# 假标题\n```\n\n<!-- # 注释\u2028继续 -->\n\n[^a]: 说明。\n'
        doc = self.document(body)
        self.assertEqual([f['heading'] for f in source_fragments(body)], ['结果'])
        saved = select_fragments(doc, ['结果'])
        for old, new in [('假标题', '新代码'), ('注释', '维护'), ('说明', '修正')]:
            self.assertTrue(fragment_changes(self.document(body.replace(old, new)), saved))

    def test_inline_code_titles_are_selected_using_original_text(self):
        doc = self.document('# `缓存`\n\n说明。\n')
        saved = select_fragments(doc, ['`缓存`'])
        self.assertEqual(fragment_changes(doc, saved), [])

    def test_invalid_records_do_not_silently_downgrade_even_with_same_body(self):
        for fragments in (None, [], {}, ['结果'], [{'heading': '结果', 'sha256': 1}],
                          [{'heading': '', 'sha256': 'a' * 64}],
                          self.source()['fragments'] * 2):
            with self.subTest(fragments=fragments):
                source = self.source()
                source['fragments'] = fragments
                finding, = self.drift_findings(self.graph(BODY, source))
                self.assertEqual(finding['level'], '🟡')

    def test_legacy_hash_and_timestamp_fallback_stay_conservative(self):
        source = self.source()
        del source['fragments']
        finding, = self.drift_findings(self.graph(BODY.replace('旧注记', '新注记'), source))
        self.assertEqual(finding['level'], '🟡')
        self.assertIn('无法定位差异', finding['problem'])
        documents = self.graph(BODY).documents
        for scoped, level in ((False, '🟡'), (True, '🔵')):
            source = self.source() if scoped else {'resource': 'raw/a.md'}
            source.pop('body_sha256', None)
            documents['wiki/concepts/a.md']['metadata'] = {'sources': [source], 'generated': {'at': '2026-01-01'}}
            documents['raw/a.md']['metadata'] = {'generated': {'at': '2026-02-01'}}
            graph = ProvenanceGraph(ROOT, load_schema(), lambda _, target: {'relative': target}, documents)
            finding, = self.drift_findings(graph)
            self.assertEqual(finding['level'], level)

    def test_unchanged_and_historical_sources_do_not_drift(self):
        self.assertEqual(self.drift_findings(self.graph(BODY)), [])
        source = self.source()
        source['historical'] = True
        self.assertEqual(self.drift_findings(self.graph(BODY.replace('42ms', '99ms'), source)), [])

    def test_all_selected_sections_must_match_and_uppercase_hashes_work(self):
        source = self.source()
        source['fragments'] = select_fragments(self.document(), ['结果', '维护'])
        for fragment in source['fragments']:
            fragment['sha256'] = fragment['sha256'].upper()
        self.assertEqual(self.drift_findings(self.graph(BODY, source)), [])
        finding, = self.drift_findings(self.graph(BODY.replace('旧注记', '新注记'), source))
        self.assertEqual(finding['level'], '🟡')
        self.assertIn('片段「维护」', finding['problem'])

    def test_upstream_warning_is_not_hidden_by_unchanged_downstream_section(self):
        graph = self.graph(BODY.replace('42ms', '99ms'), downstream=True)
        documents = copy.deepcopy(graph.documents)
        documents['wiki/concepts/a.md']['body'] = '# 摘要\n\n结论。\n'
        documents['wiki/analyses/b.md']['metadata']['sources'][0]['fragments'] = select_fragments(
            documents['wiki/concepts/a.md'], ['摘要'])
        graph = ProvenanceGraph(ROOT, load_schema(), lambda _, target: {'relative': target}, documents)
        finding, = self.drift_findings(graph, 'wiki/analyses/b.md')
        self.assertEqual(finding['level'], '🟡')

    def test_new_raw_version_remains_warning_even_if_selected_old_section_is_unchanged(self):
        documents = self.graph(BODY).documents
        documents['raw/a.md']['metadata'] = {'source_id': 'test', 'timestamp': '2026-01-01'}
        documents['raw/new.md'] = self.document(BODY.replace('42ms', '99ms'))
        documents['raw/new.md']['metadata'] = {'source_id': 'test', 'timestamp': '2026-02-01'}
        for path in ('raw/a.md', 'raw/new.md'):
            documents[path]['path'] = ROOT / 'SKILL.md'
        graph = ProvenanceGraph(ROOT, load_schema(), lambda _, target: {'relative': target}, documents)
        finding, = self.drift_findings(graph)
        self.assertEqual(finding['level'], '🟡')
        self.assertIn('已有新版本', finding['problem'])

    def test_cli_exports_explicit_sections_and_lint_thresholds_remain_read_only(self):
        with tempfile.TemporaryDirectory() as directory:
            kb = initialize_kb(directory)
            raw = kb / 'raw/a.md'
            raw.write_text(page('source-material', 'A', BODY))
            def command(script, *args):
                return subprocess.run([sys.executable, str(ROOT / 'scripts' / script), str(kb), *args],
                                      capture_output=True, text=True)
            before = snapshot(kb)
            result = command('impact_wiki.py', '--source', 'raw/a.md', '--heading', '结果', '--heading', '维护')
            self.assertEqual(result.returncode, 0, result.stderr)
            exported, = json.loads(result.stdout)['sources']
            self.assertEqual([f['heading'] for f in exported['fragments']], ['结果', '维护'])
            self.assertEqual(exported['body_sha256'], body_sha256(split_frontmatter(raw.read_text())[2]))
            for args in (('--source', 'raw/a.md', '--heading', '不存在'),
                         ('--source', 'raw/a.md', 'raw/a.md', '--heading', '结果')):
                self.assertNotEqual(command('impact_wiki.py', *args).returncode, 0)
            self.assertEqual(snapshot(kb), before)
            exported.pop('path')
            exported['resource'] = '../../raw/a.md'
            exported['fragments'] = exported['fragments'][:1]
            (kb / 'wiki/summaries/a.md').write_text(page('source-summary', 'A',
                '## 摘要\n\n转述。\n\n## 关键要点\n\n结论。', sources=[exported]))
            index = kb / 'wiki/index.md'
            index.write_text(index.read_text().replace('## 素材来源', '## 素材来源\n\n- [[summaries/a]]')
                             .replace('素材: 0', '素材: 1'))
            raw.write_text(raw.read_text().replace('旧注记', '新注记'))
            before = snapshot(kb)
            for threshold, code in (('warning', 0), ('any', 1)):
                result = command('lint_wiki.py', '--lint-files', 'wiki/summaries/a.md', '--details', '--fail-on', threshold)
                self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                self.assertIn('来源依赖变更提示', result.stdout)
                self.assertNotIn('来源依赖需要复核', result.stdout)
                self.assertEqual(snapshot(kb), before)
            raw.write_text(raw.read_text().replace('42ms', '99ms'))
            before = snapshot(kb)
            result = command('lint_wiki.py', '--lint-files', 'wiki/summaries/a.md', '--details', '--fail-on', 'warning')
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn('片段「结果」指纹已变化', result.stdout)
            self.assertEqual(snapshot(kb), before)


if __name__ == '__main__':
    unittest.main()
