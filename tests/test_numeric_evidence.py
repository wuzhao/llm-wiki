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
            ('百年', '100年'), ('千倍', '1000倍'), ('百万个', '100万个'),
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
            ('5.63‰', '5.63%'), ('5.63', '5.63‰'),
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
            ('2秒', '1GB/2s'),
        )
        for left, right in pairs:
            with self.subTest(left=left, right=right):
                self.assertTrue(missing_literals(left, right))
                # If both sides are in scope, they must also differ in reverse.
                if claim_literals(right):
                    self.assertTrue(missing_literals(right, left))

    def test_unsupported_forms_can_be_located_as_complete_original_tokens(self):
        for value in ('三五个', '一百二个', '一万二个', '1GB/s',
                      '10至20万个', '10 至 20 万个', '1,00条', '1e3个', '2026-02-30'):
            with self.subTest(value=value):
                self.assertEqual(missing_literals(value, value), [])
                self.assertEqual(missing_literals(value, '未提供相应数量。'), [value])
        for claim, evidence in (('30个', '三五个'), ('20个', '几十个'),
                                ('12000个', '一万二个'), ('50%', '约一半'),
                                ('1e3个', '11e3个'), ('1e3个', '-1e3个'),
                                ('1GB/s', '11GB/s'), ('1GB/s', '1GB/s2'),
                                ('1GB/s', '1GB/s²'), ('1GB/s', '1GB/s/年'),
                                ('1GB', '1GB/2s'), ('三五个', '三五个至六七个')):
            with self.subTest(claim=claim, evidence=evidence):
                self.assertEqual(missing_literals(claim, evidence), [claim])

    def test_vague_amounts_do_not_create_precise_numeric_claims(self):
        text = '多次、几十次、数十次、数百次、十几次、几条、约一半'
        self.assertEqual(claim_literals(text), set())
        self.assertEqual(missing_literals(text, '未提供数量。'), [])
        self.assertEqual(missing_literals('原文：「多次」', '未提供数量。'), ['多次'])
        self.assertEqual(missing_literals('50次', '数十次'), ['50次'])
        self.assertEqual(missing_literals('约40年', '未提供数量。'), ['约40年'])
        self.assertEqual(missing_literals('一项、两条', '两项、三条'), ['一项', '两条'])
        self.assertEqual(missing_literals('记录数1000条', '共有1000条'), [])
        self.assertEqual(missing_literals('记录数1000条', '共有1001条'), ['1000条'])
        for value in ('一千六百多', '百余项', '40多年', '半小时'):
            with self.subTest(value=value):
                self.assertEqual(missing_literals(value, '没有相应数量。'), [value])
                self.assertEqual(missing_literals(value, value), [])

    def test_composite_magnitudes_are_atomic_and_ignore_formatting_spaces(self):
        for left, right in (
            ('1 亿 9100 万', '就1亿9100万'),
            ('1亿9100万', '就 1 亿 9100 万'),
            ('1 亿 9100 万', '1.91亿'),
            ('1亿9100万个', '一亿九千一百万个'),
            ('1亿9100万', '191000000'),
            ('1 万 2 千 3 百', '12300'),
        ):
            with self.subTest(left=left, right=right):
                self.assertEqual(len(claim_literals(left)), 1)
                self.assertEqual(missing_literals(left, right), [])
                self.assertEqual(missing_literals(right, left), [])
        for claim, evidence in (
            ('1亿', '1 亿 9100 万'), ('9100万', '1亿9100万'),
            ('1.91亿', '1亿，另有9100万'), ('1.91亿', '1亿\n9100万'),
            ('1.91亿', '1亿 和 9100万'), ('1.91亿', '1亿[^a]9100万[^b]'),
            ('1亿9100万', '1亿9000万'), ('1亿9100万', '-1亿9100万'),
            ('1亿9100万', '约1亿9100万'), ('2亿', '1亿10000万'),
            ('2亿', '1亿1亿'),
        ):
            with self.subTest(claim=claim, evidence=evidence):
                self.assertTrue(missing_literals(claim, evidence))

    def test_chinese_quantities_are_checked_and_prose_is_not(self):
        self.assertEqual(missing_literals('有两个条件', '有三个条件'), ['两个'])
        self.assertEqual(claim_literals('一方面十分重要，另一方面千方百计。\n第 1 步：说明。'), set())
        self.assertEqual(claim_literals('42ms 和四十二毫秒'), {'42ms', '四十二毫秒'})

    def test_lexical_counts_and_selectors_do_not_become_cardinal_claims(self):
        for text in ('同一项目', '另一种思路', '每一条输入', '某一次运行', '下一次迭代',
                     '一次性补贴', '二次分配', '二次引用与二次创作', '二元对立与三元组',
                     '三元角色、三元分工与三元协作架构'):
            with self.subTest(text=text):
                self.assertEqual(claim_literals(text), set())
                self.assertEqual(missing_literals(text, '其他措辞'), [])
        self.assertEqual(claim_literals('一次性补贴200元，二次分配涉及3次转账。'), {'200元', '3次'})
        for claim, evidence in (('两人受伤', '三人受伤'), ('只有一人', '只有两人'),
                                ('发生一次事故', '发生两次事故'), ('重试两次', '重试三次'),
                                ('其中一项失败', '其中两项失败'), ('三元成本', '四元成本'),
                                ('至少一个', '一个'), ('有两个条件', '有三个条件')):
            with self.subTest(claim=claim, evidence=evidence):
                self.assertTrue(missing_literals(claim, evidence))
        self.assertEqual(missing_literals('原文：「一次性补贴」', '单笔补贴'), ['一次性补贴'])
        self.assertEqual(missing_literals('1条', '每一条输入'), ['1条'])
        self.assertEqual(missing_literals('3元', '三元组'), ['3元'])

    def test_complete_calendar_dates_match_across_languages(self):
        for value in ('2026年6月7日', '2026 年 6 月 7 日', '二〇二六年六月七日',
                      '二零二六年六月七号', 'June 7, 2026', 'Jun. 7, 2026', 'June 7,2026',
                      '7 June 2026', '7 JUN 2026'):
            with self.subTest(value=value):
                self.assertEqual(len(claim_literals(value)), 1)
                self.assertEqual(missing_literals(value, '2026-06-07'), [])
                self.assertEqual(missing_literals('2026-06-07', value), [])
        self.assertEqual(missing_literals('2024年2月29日', 'February 29, 2024'), [])
        self.assertEqual(missing_literals('2026年9月30日', '30 Sept. 2026'), [])
        self.assertEqual(missing_literals('约2026年6月7日', 'about June 7, 2026'), [])
        self.assertEqual(missing_literals('2026年6月7日之前', 'before June 7, 2026'), [])
        self.assertEqual(missing_literals('2026-06-07至2026-06-09', '7 June 2026 到 9 June 2026'), [])
        self.assertEqual(missing_literals('2026-06-07至2026-06-09', 'June 7, 2026 to June 9, 2026'), [])

    def test_calendar_dates_preserve_day_range_and_qualifiers(self):
        pairs = (
            ('2026年6月7日', '2026年6月8日'), ('2026年6月7日', 'July 6, 2026'),
            ('2026年6月7日', '06/07/2026'), ('2026年6月7日', '约2026年6月7日'),
            ('2026年6月7日', '2026年6月7日以前'), ('2026年6月7日', '截至2026年6月7日'),
            ('2026年6月7日', '负2026年6月7日'), ('2026-06-07', '-2026-06-07'),
            ('2026年6月7日', '2026年6月7日/年'),
            ('2026-06-08', '2026-06-07/2026-06-08'),
            ('2026年6月7日', 'before June 7, 2026'),
            ('2026年6月7日', 'June 7, 2026 to June 9'),
            ('2026-06-07至2026-06', '2026-06-07至2026-07'),
            ('2026年6月7日至2027年8月', '2026年6月7日至2027年9月'),
            ('2026年6月7日', '2026年6月7日至2026年6月9日'),
            ('2026年6月7日', '2026年6月7日至9日'),
            ('2026年6月7日至2026年6月9日', '2026年6月7日；2026年6月9日'),
            ('2026年6月7日', '2026年6月1日，2025年7月7日'),
            ('2026年6月7日', '2026年6月\n7日'),
            ('2026年6月7日', '2026年6月[^a]7日'),
            ('2026年', '2026年6月7日'), ('6月', '2026年6月7日'),
            ('1.91亿', '1亿 2026年6月7日 9100万'),
        )
        for claim, evidence in pairs:
            with self.subTest(claim=claim, evidence=evidence):
                self.assertTrue(missing_literals(claim, evidence))
        for value in ('2026-02-30', '2026年2月29日', 'February 30, 2026',
                      '06/07/2026', '2026年6月7日至9日'):
            with self.subTest(value=value):
                self.assertEqual(missing_literals(value, value), [])
                self.assertEqual(missing_literals(value, '没有日期。'), [value])

    def test_direct_quotes_still_require_exact_wording(self):
        self.assertEqual(missing_literals('原文：「有2个条件」', '有两个条件'), ['有2个条件'])
        self.assertEqual(missing_literals('原文：「有2个条件」', '有2个条件'), [])
        self.assertEqual(missing_literals('原话是「缓存」', '缓冲'), ['缓存'])
        self.assertEqual(missing_literals('原文：「June 7, 2026」', '2026年6月7日'), ['June 7, 2026'])

    def test_markdown_and_punctuation_do_not_change_numeric_meaning(self):
        self.assertEqual(missing_literals('有2个条件', '- 两个条件'), [])
        self.assertEqual(missing_literals('有2个条件', '+ 两个条件'), [])
        self.assertEqual(missing_literals('变化为3.5%', '变化为 - 3.5%'), ['3.5%'])
        self.assertEqual(claim_literals(' ' * 10000 + '\n1000，已记录。'), {'1000'})


if __name__ == '__main__':
    unittest.main()
