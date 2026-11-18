import copy
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from kb_fixture import initialize_kb
from lint_wiki import create_or_append_log
from review_quality import audit_samples
from wiki_config import SchemaError, load_schema, render_markdown_template


class MaintenanceDetailsTests(unittest.TestCase):
    def test_audit_uses_configured_limits_and_rejects_invalid_percentages(self):
        schema = load_schema()
        samples = [{'id': category, 'category': category, 'claim': '200人', 'source': '2人',
                    'quote': '2人', 'flaw': '数量错误', 'status': 'supported'}
                   for category in ('derived', 'approximate')]
        schema['limits']['review_weekly_admission_threshold'] = 1
        schema['limits']['max_review_false_support_pct'] = 100
        self.assertTrue(audit_samples(samples, weekly_pending=2, schema=schema)['automatic_proposals_allowed'])
        schema['limits']['max_review_false_support_pct'] = 0
        self.assertFalse(audit_samples(samples, weekly_pending=2, schema=schema)['automatic_proposals_allowed'])
        self.assertTrue(audit_samples(samples, weekly_pending=1, schema=schema)['automatic_proposals_allowed'])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'schema.json'
            for pct in (-1, 101, True, 0.5, '5', 0, 100):
                schema['limits']['max_review_false_support_pct'] = pct
                path.write_text(json.dumps(schema))
                if type(pct) is int and 0 <= pct <= 100:
                    self.assertEqual(load_schema(path)['limits']['max_review_false_support_pct'], pct)
                else:
                    with self.assertRaises(SchemaError): load_schema(path)

    def test_template_generation_does_not_claim_verification_or_expiration_time(self):
        now = datetime.datetime(2026, 11, 18, tzinfo=datetime.timezone.utc)
        for name in ('source', 'entity', 'concept', 'archive'):
            content = render_markdown_template(name + '-template.md', now)
            self.assertIn('at: 2026-11-18T00:00:00Z', content)
            self.assertIn('at: <实际核验 ISO 时间>', content)
            self.assertIn('# stale_after: <过期 ISO 时间>', content)
            self.assertFalse(any('2026-11-18' in line for line in content.splitlines() if line.startswith('# ')))

    def test_log_append_preserves_prefix_and_handles_lf_crlf_and_missing_newline(self):
        for ending, separator in ((b'', b'\n\n'), (b'\n', b'\n'), (b'\n\n', b''),
                                  (b'\n\n\n', b''), (b'\r\n', b'\n'), (b'\r\n\r\n', b'')):
            with self.subTest(ending=ending), tempfile.TemporaryDirectory() as directory:
                kb = initialize_kb(directory)
                now = datetime.datetime.now(datetime.timezone.utc)
                target = kb / f'wiki/logs/{now:%Y%m}.md'
                original = b'# Existing log' + ending
                target.write_bytes(original)
                create_or_append_log(kb, load_schema(), 1, 0, 0, {'🔴': 0, '🟡': 0, '🔵': 0})
                result = target.read_bytes()
                self.assertTrue(result.startswith(original + separator + b'## ['))
                create_or_append_log(kb, load_schema(), 1, 0, 0, {'🔴': 0, '🟡': 0, '🔵': 0})
                self.assertTrue(target.read_bytes().startswith(result + b'\n## ['))
