import shutil
import tempfile
import unittest
from pathlib import Path

from kb_fixture import ROOT
from check_project import check_project


class ProjectChecksTests(unittest.TestCase):
    def test_repository_passes_release_checks(self):
        self.assertEqual(check_project(ROOT), [])

    def test_checks_catch_broken_docs_and_duplicate_threshold_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('scripts', 'templates', 'references'):
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


if __name__ == '__main__':
    unittest.main()
