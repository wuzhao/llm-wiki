import ast
import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kb_fixture import ROOT
import test_reviews
from wiki_reviews import annotate_reviews
from wiki_rule_fingerprint import canonical_ast, checker_fingerprint, module_rules


class RuleFingerprintTests(unittest.TestCase):
    def test_comments_docstrings_and_empty_new_ast_fields_are_ignored(self):
        first = '"""old"""\ndef f(x):\n    """old"""\n    return x + 1\n'
        second = '# comment\n"""new"""\n\ndef f(x):\n    """new"""\n    return (x + 1)  # note\n'
        self.assertEqual(module_rules(first, 'core.py'), module_rules(second, 'core.py'))
        self.assertNotEqual(module_rules(first, 'core.py'), module_rules(first.replace('+ 1', '+ 2'), 'core.py'))
        tree = ast.parse('def f(): return 1')
        original = canonical_ast(tree)
        tree.body[0]._fields += ('future_optional_field',)
        tree.body[0].future_optional_field = []
        self.assertEqual(canonical_ast(tree), original)
        tree.body[0].future_optional_field = [ast.Constant(value=1)]
        self.assertNotEqual(canonical_ast(tree), original)

    def test_dependency_boundaries_and_unknown_rules(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(ROOT / 'scripts', root / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
            shutil.copytree(ROOT / 'references', root / 'references')
            baseline = checker_fingerprint(root / 'scripts')
            edits = [
                ('scripts/lint_wiki.py', 'Read semantic reviews;', 'Load semantic reviews;', False),
                ('scripts/lint_wiki.py', 'lint | mode=fix', 'lint | mode=repair', False),
                ('scripts/lint_wiki.py', '孤儿页面，没有其他内容页指向此页', '孤儿页面', False),
                ('scripts/wiki_provenance.py', 'resolve_claim_link=resolve_claim_link)', 'resolve_claim_link=None)', True),
                ('scripts/wiki_links.py', 'normalized in exact or normalized in slugs', 'normalized in exact', True),
                ('scripts/wiki_config.py', '(base / relative_path).resolve()', '(base / relative_path).absolute()', True),
                ('scripts/wiki_config.py', '缺少有效的 metadata.version', '缺少模板版本', False),
                ('scripts/wiki_numbers.py', '"大约": "approx"', '"大约": "exact"', True),
                ('scripts/wiki_review_policy.py', "('approx', 'near')", "('approx',)", True),
                ('scripts/wiki_scan.py', 'excluded_roots=[schema["paths"]["assets"]]', 'excluded_roots=[]', True),
            ]
            for name, old, new, changes in edits:
                with self.subTest(name=name, old=old):
                    path = root / name
                    original = path.read_text()
                    self.assertIn(old, original)
                    path.write_text(original.replace(old, new))
                    self.assertEqual(checker_fingerprint(root / 'scripts') != baseline, changes)
                    path.write_text(original)
            path = root / 'references/schema.json'
            original = json.loads(path.read_text())
            for field in ('limits', 'link_roots'):
                schema = copy.deepcopy(original)
                if field == 'limits': schema[field]['max_page_lines'] += 1
                else: schema[field] = ['raw', 'wiki']
                path.write_text(json.dumps(schema))
                self.assertEqual(checker_fingerprint(root / 'scripts') != baseline, field != 'limits')

    def test_new_policy_records_reuse_alias_without_legacy_exemption(self):
        fixture = test_reviews.ReviewTests()
        state, record = fixture.approved()
        record.pop("human_confirmation")
        record.pop("source_values")
        record["unexpected"] = True
        original = copy.deepcopy(record)
        with patch('wiki_reviews.compatible_review_rules', return_value=['rules-v1']), \
                patch('wiki_reviews.legacy_review_rules', return_value=[]):
            _, findings = fixture.fixture()
            data, stale = annotate_reviews(findings, state, [record], 'rules-v2')
            self.assertEqual(stale, 0)
            self.assertEqual(findings[0][1]['level'], '🔵')
            exported = data['records'][0]
            self.assertEqual(exported['id'], record['id'])
            self.assertEqual(exported['rules'], record['rules'])
            self.assertEqual(exported['source_values'], '')
            self.assertIsNone(exported['human_confirmation'])
            self.assertNotIn('unexpected', exported)
            self.assertEqual(record, original)
            record.pop('review_policy')
            _, findings = fixture.fixture()
            _, stale = annotate_reviews(findings, state, [record], 'rules-v2')
            self.assertEqual(stale, 1)
            self.assertEqual(findings[0][1]['level'], '🟡')
