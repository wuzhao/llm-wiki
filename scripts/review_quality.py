#!/usr/bin/env python3
"""Inject negative samples into a reviewer callback or score saved model responses."""
import argparse
import json
from pathlib import Path

from wiki_config import load_schema


AUDIT_CATEGORIES = ('derived', 'approximate')


def audit_samples(samples, reviewer=None, *, weekly_pending=0, schema=None):
    """Reviewer(sample) returns a status; count proposals as false support too.

    A sample supplies id, category, claim, source, quote and flaw. Its quote must
    actually occur in source; flaw describes the deliberately invalid inference.
    Without a callback, use the saved response in each sample's status field.
    """
    if not isinstance(samples, list):
        raise ValueError('负样本必须为 JSON 数组')
    if type(weekly_pending) is not int or weekly_pending < 0:
        raise ValueError('weekly_pending 必须是非负整数')
    limits = (schema if schema is not None else load_schema())['limits']
    max_pct = limits['max_review_false_support_pct']
    counts = {category: {'total': 0, 'false_supported': 0} for category in AUDIT_CATEGORIES}
    seen = set()
    for sample in samples:
        if (not isinstance(sample, dict) or
                any(not isinstance(sample.get(k), str) or not sample[k].strip()
                    for k in ('id', 'category', 'claim', 'source', 'quote', 'flaw'))
                or sample['category'] not in counts or sample['id'] in seen
                or sample['quote'] not in sample['source']):
            raise ValueError('负样本须有唯一 id、类别、主张、原文、真实引文与推导硬伤说明')
        seen.add(sample['id'])
        # Do not leak the expected failure explanation into the model input.
        status = reviewer({k: sample[k] for k in ('id', 'category', 'claim', 'source', 'quote')}) if reviewer else sample.get('status')
        if status not in ('supported', 'proposed-supported', 'pending', 'unsupported'):
            raise ValueError('样本响应须为 supported、proposed-supported、pending 或 unsupported')
        row = counts[sample['category']]
        row['total'] += 1
        row['false_supported'] += status in ('supported', 'proposed-supported')
    for row in counts.values():
        row['false_support_rate'] = row['false_supported'] / row['total'] if row['total'] else None
        row['passed'] = row['total'] > 0 and row['false_supported'] * 100 <= row['total'] * max_pct
    admission = weekly_pending > limits['review_weekly_admission_threshold']
    return {'categories': counts, 'threshold': max_pct / 100,
            'admission_required': admission,
            'automatic_proposals_allowed': not admission or all(row['passed'] for row in counts.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('samples', type=Path, help='JSON array of negative samples and saved statuses')
    parser.add_argument('--weekly-pending', type=int, default=0)
    args = parser.parse_args()
    try:
        result = audit_samples(json.loads(args.samples.read_text(encoding='utf-8')),
                               weekly_pending=args.weekly_pending)
    except (ValueError, OSError, TypeError) as exc:
        parser.exit(2, f'{exc}\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['automatic_proposals_allowed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
