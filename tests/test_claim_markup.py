import unittest

import kb_fixture  # Adds scripts to sys.path.
from lint_wiki import check_conflicts
from wiki_provenance import claim_literals, mask_claim_markup, missing_literals


class ClaimMarkupTests(unittest.TestCase):
    def test_terms_and_emphasis_are_not_automatically_verbatim_quotes(self):
        for text in ('这称为「现场部署工程师（FDE）」。', '作者主张「Code is truth」。',
                     '「Always-on 不等于 Always-running」是本页的归纳。', 'Use "memory" here.'):
            with self.subTest(text=text):
                self.assertEqual(claim_literals(text), set())
                self.assertEqual(missing_literals(text, '其他措辞'), [])
        self.assertEqual(missing_literals('「增长50%」', '增长150%'), ['50%'])

    def test_explicit_direct_quotes_still_require_the_original_wording(self):
        for text in ('原文：「缓存」', '原话是「缓存」', '**原文**：「缓存」',
                     '作者写道：「缓存」', '> 「缓存」', 'Verbatim: "缓存"'):
            with self.subTest(text=text):
                self.assertEqual(missing_literals(text, '缓冲'), ['缓存'])
                self.assertEqual(missing_literals(text, '使用缓存。'), [])

    def test_link_targets_titles_and_footnote_ids_are_not_claims(self):
        text = '[报告](<../2026/report(123).md> "说明 500%")。[^20261031]'
        self.assertEqual(claim_literals(mask_claim_markup(text)), set())
        self.assertEqual(missing_literals(text, ''), [])
        # Visible numeric claims must remain checked even when linked.
        self.assertEqual(missing_literals('[50%](../2026/report.md)', '150%'), ['50%'])
        self.assertEqual(missing_literals('[[reports/2026|50%]]', '150%'), ['50%'])
        self.assertEqual(missing_literals('2026', '[报告](../2026)'), ['2026'])
        self.assertEqual(missing_literals('1.91亿', '[[a|1亿]][[b|9100万]]'), ['1.91亿'])
        self.assertEqual(claim_literals('[report]: ../2026\n  增长99%。'), {'99%'})
        self.assertEqual(claim_literals('[report]:\n  ../2026\n  "说明 500%"\n实际99%。'), {'99%'})

    def test_navigation_labels_are_masked_but_descriptions_and_body_are_preserved(self):
        text = ('## 相关页面\n\n'
                '- [2026 年报告](report.md)：结论增长50%。\n'
                '- [2025 年报告][report]\n'
                '- [[reports/2024|2024 年报告]]\n\n'
                '[report]: ../2025/report.md "报告 100%"\n\n'
                '## 统计结果\n\n[2023 年](report.md)增长150%。\n\n'
                '相关阅读：[2022 年报告](report.md)。\n')
        masked = mask_claim_markup(text)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.count('\n'), text.count('\n'))
        self.assertEqual(claim_literals(masked), {'50%', '2023 年', '150%'})

    def test_conflict_candidates_require_an_evidence_disagreement(self):
        for text in ('媒体与读者关注俄乌冲突。', '资料介绍了工作区隔离与多智能体并发不冲突。',
                     '来源引用历史数据（如海湾战争与过去 30 年中东 7 次冲突黄金表现）。',
                     '资料不存在事实冲突。', '两个来源并不互相矛盾。',
                     'Source A does not conflict with source B.'):
            with self.subTest(text=text):
                self.assertEqual(check_conflicts(text), [])
        for text in ('存在事实冲突。', '两个来源互相矛盾。', '不同来源存在事实冲突。',
                     '这条记录与另一条记录冲突。', 'Source A contradicts source B.',
                     '这里没有观点冲突，但两个来源互相矛盾。'):
            with self.subTest(text=text):
                self.assertEqual(len(check_conflicts(text)), 1)
                self.assertEqual(check_conflicts(text)[0]['problem'], '发现未结构化的冲突候选')


if __name__ == '__main__':
    unittest.main()
