import unittest

import kb_fixture  # Adds the project's scripts to sys.path.
from wiki_provenance import claim_literals, missing_literals


class NumericEvidenceTests(unittest.TestCase):
    def test_equivalent_quantities_match_in_both_directions(self):
        pairs = (
            ('2个', '两个'), ('2 个', '二个'), ('42ms', '四十二毫秒'),
            ('50%', '百分之五十'), ('3.5%', '百分之三点五'),
            ('-3.5%', '负百分之三点五'), ('-3.5%', '百分之负三点五'),
            ('+3.5%', '正百分之三点五'), ('0.5%', '百分之零点五'),
            ('1000条', '1,000 条'), ('１２３４．５％', '1,234.5%'),
            ('1.2万个', '一万两千个'), ('1.5万个', '一点五万个'),
            ('1.2 万个', '12000个'), ('1000', '1 千'),
            ('105个', '一百零五个'), ('10001条', '一万零一条'),
            ('2026年', '二〇二六年'), ('2026年', '二零二六年'),
            ('0.042秒', '42毫秒'), ('1秒', '1000 ms'), ('120秒', '两分钟'),
            ('1GB', '1000MB'), ('1GiB', '1024MiB'),
            ('10至20ms', '十到二十毫秒'), ('1秒至2秒', '1000–2000ms'),
            ('约50%', '大约百分之五十'), ('50%左右', '约50%'),
            ('至少50%', '50%以上'), ('不超过50%', '≤百分之五十'),
            ('50%以上', 'at least 50%'), ('约50%', 'About 50%'),
            ('约50%', '≈50%'), ('约50%', '~50%'),
            ('3个百分点', '三百分点'),
            ('2026-10-30', '２０２６-１０-３０'), ('1000', '1000，结果已记录。'),
        )
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                self.assertTrue(claim_literals(left))
                self.assertTrue(claim_literals(right))
                self.assertEqual(missing_literals(left, right), [])
                self.assertEqual(missing_literals(right, left), [])

    def test_material_differences_are_not_hidden(self):
        pairs = (
            ('50%', '150%'), ('1000条', '11000条'), ('42ms', '142ms'),
            ('3.5%', '-3.5%'), ('负3.5%', '正3.5%'),
            ('50%', '50个百分点'), ('50%', '0.5'), ('2个', '2条'),
            ('1GB', '1024MB'), ('1GB', '1GiB'), ('1MB', '1mb'),
            ('50%', '约50%'), ('至少50%', '超过50%'), ('50%', '不足50%'),
            ('50%', 'about 50%'), ('50%', '50%以上'), ('2年', '第2年'),
            ('50%', '大概50%'), ('50%', '~50%'), ('50%', '低于50%'),
            ('10ms', '10至20ms'), ('20ms', '10至20ms'),
            ('10至20ms', '10ms 和 20ms'), ('10至20ms', '10至30ms'),
            ('2026', '2026-10-30'), ('2026-10-30', '2026-10-31'),
            ('3.5%', '1e3.5%'), ('1000', 'item_1000'),
            ('1.2', '版本 1.2.3'),
            ('1GB', '1GB/s'), ('50%', '50%/年'),
        )
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                self.assertTrue(missing_literals(left, right))
                # If both sides are in scope, they must also differ in reverse.
                if claim_literals(right):
                    self.assertTrue(missing_literals(right, left))

    def test_ambiguous_or_unsupported_forms_remain_review_candidates(self):
        for value in ('几十个', '三五个', '一百二个', '一万二个', '约一半',
                      '10至20万个', '10 至 20 万个', '1,00条', '1e3个', '2026-02-30'):
            with self.subTest(value=value):
                self.assertEqual(missing_literals(value, value), [value])
        for claim, evidence in (('30个', '三五个'), ('20个', '几十个'),
                                ('12000个', '一万二个'), ('50%', '约一半')):
            with self.subTest(claim=claim, evidence=evidence):
                self.assertEqual(missing_literals(claim, evidence), [claim])

    def test_chinese_quantities_are_checked_and_prose_is_not(self):
        self.assertEqual(missing_literals('有两个条件', '有三个条件'), ['两个'])
        self.assertEqual(claim_literals('一方面十分重要，另一方面千方百计。\n第 1 步：说明。'), set())
        self.assertEqual(claim_literals('42ms 和四十二毫秒'), {'42ms', '四十二毫秒'})

    def test_direct_quotes_still_require_exact_wording(self):
        self.assertEqual(missing_literals('「有2个条件」', '有两个条件'), ['有2个条件'])
        self.assertEqual(missing_literals('「有2个条件」', '有2个条件'), [])
        self.assertEqual(missing_literals('「缓存」', '缓冲'), ['缓存'])

    def test_markdown_and_punctuation_do_not_change_numeric_meaning(self):
        self.assertEqual(missing_literals('有2个条件', '- 两个条件'), [])
        self.assertEqual(missing_literals('有2个条件', '+ 两个条件'), [])
        self.assertEqual(missing_literals('变化为3.5%', '变化为 - 3.5%'), ['3.5%'])
        self.assertEqual(claim_literals(' ' * 10000 + '\n1000，已记录。'), {'1000'})


if __name__ == '__main__':
    unittest.main()
