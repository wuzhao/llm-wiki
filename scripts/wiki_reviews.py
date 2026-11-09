"""Explicit semantic review records. Never approve findings or rewrite evidence."""
import hashlib
import json
from pathlib import Path

from wiki_metadata import parse_datetime


STATUSES = {'pending', 'supported', 'non-quantity', 'author-structure'}


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def load_reviews(path):
    if path is None:
        return []
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('records'), list):
        raise ValueError('复核文件必须包含 version: 1 与 records 数组')
    seen = set()
    for record in data['records']:
        if not isinstance(record, dict) or not isinstance(record.get('id'), str) or record['id'] in seen:
            raise ValueError('复核记录 id 缺失或重复')
        seen.add(record['id'])
        if record.get('status') not in STATUSES:
            raise ValueError('复核状态仅支持 pending、supported、non-quantity、author-structure')
        if record['status'] != 'pending':
            if any(not isinstance(record.get(k), str) or not record[k].strip()
                   for k in ('reason', 'reviewer', 'reviewed_at')) or not parse_datetime(record['reviewed_at']):
                raise ValueError('已复核记录必须提供 reason、reviewer 与有效 reviewed_at')
            if not isinstance(record.get('evidence'), list):
                raise ValueError('已复核记录必须提供 evidence 数组')
            if record['status'] == 'supported' and not record['evidence']:
                raise ValueError('supported 记录必须提供来源原文片段')
            for evidence in record['evidence']:
                if (not isinstance(evidence, dict) or
                        any(not isinstance(evidence.get(k), str) or not evidence[k].strip() for k in ('path', 'quote'))):
                    raise ValueError('evidence 条目必须提供 path 与非空 quote')
    return data['records']


def annotate_reviews(all_issues, snapshot, records, rules_fingerprint):
    """Bind each decision to the whole page, dependency chain and checker rules."""
    prior = {record['id']: record for record in records}
    exported, used = {}, set()
    hashes = {path: digest(text) for path, text in snapshot.originals.items()}
    for path, finding in all_issues:
        dependencies = sorted(set(finding.get('review_dependencies', []) + finding.get('sources', []) + [path]))
        complete = all(p in hashes for p in dependencies) and not snapshot.errors
        for detail in finding.get('details', []):
            identity = {'page': path, 'claim': detail['claim'], 'kind': detail['kind'],
                        'context': detail['context'], 'line': detail.get('line', finding.get('line')),
                        'dependencies': {p: hashes.get(p) for p in dependencies}, 'rules': rules_fingerprint}
            key = digest(json.dumps(identity, ensure_ascii=False, sort_keys=True))
            record = {'id': key, **identity, 'status': 'pending', 'reason': '',
                      'reviewer': '', 'reviewed_at': '', 'evidence': []}
            old = prior.get(key)
            if old and complete and all(old.get(k) == v for k, v in identity.items()):
                valid_evidence = all(
                    evidence['path'] in finding.get('sources', []) and
                    evidence['quote'] in snapshot.documents.get(evidence['path'], {}).get('body', '')
                    for evidence in old.get('evidence', []))
                if old['status'] == 'pending' or valid_evidence:
                    record.update({k: old.get(k, record[k]) for k in ('status', 'reason', 'reviewer', 'reviewed_at', 'evidence')})
                    used.add(key)
            detail['review_id'] = key
            if record['status'] != 'pending':
                detail['review'] = {k: record[k] for k in ('status', 'reason', 'reviewer', 'reviewed_at', 'evidence')}
            exported[key] = record
    stale = sum(record['status'] != 'pending' and record['id'] not in used for record in records)
    return {'version': 1, 'records': list(exported.values())}, stale


def checker_fingerprint():
    root = Path(__file__).parent
    return digest(''.join((root / name).read_text(encoding='utf-8') for name in
                         ('wiki_numbers.py', 'wiki_evidence.py', 'wiki_provenance.py', 'wiki_reviews.py')))
