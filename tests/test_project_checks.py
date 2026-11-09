import shutil
import tempfile
import unittest
from pathlib import Path

from kb_fixture import ROOT
from check_project import check_project, markdown_style_errors


class ProjectChecksTests(unittest.TestCase):
    def test_repository_passes_release_checks(self):
        self.assertEqual(check_project(ROOT), [])

    def test_checks_catch_broken_docs_and_duplicate_threshold_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('scripts', 'templates', 'references', 'docs'):
                shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns('__pycache__'))
            for path in [*ROOT.glob('*.md'), ROOT / '.gitignore']:
                shutil.copyfile(path, root / path.name)
            (root / 'README.md').write_text('[Missing](references/not-here.md)\n\n')
            (root / 'scripts/bad_default.py').write_text('value = limits.get("max_page_lines", 99)\n')
            skill = root / 'SKILL.md'
            skill.write_text(skill.read_text().replace('## 5 条护栏', '## 6 条护栏'))
            errors = '\n'.join(check_project(root))
            for expected in ('本地文档断链', '换行符', '阈值', '护栏标题'):
                self.assertIn(expected, errors)

    def test_markdown_style_checks_prose_but_not_code_yaml_or_examples(self):
        bad = '中文“引号”和省略号…\n---\n下一段。\n\n| 名称 | 金额 |\n| --- | --- |\n| **商品** | ¥3.80 |\n'
        errors = '\n'.join(markdown_style_errors(bad))
        for expected in ('禁用标点', '分隔线', '不能加粗', '须右对齐'):
            self.assertIn(expected, errors)
        good = '''---
title: 中文“原值”…
---

中文使用「引号」和...，代码 `中文“原值”…` 保留。
中文[链接](https://example.com/a--b "中文“原值”…") 保留地址与 title。

---

| 名称 | 金额 |
| --- | ---: |
| 商品 | ¥3.80 |

```markdown
中文“反例”…
---
| **商品** | 3 |
```
<!-- 中文“注释”… -->
English “quotes” and an ellipsis…
'''
        self.assertEqual(markdown_style_errors(good), [])


if __name__ == '__main__':
    unittest.main()
