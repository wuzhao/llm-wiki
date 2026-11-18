"""Explicit semantic review records. Never approve findings or rewrite evidence."""
import hashlib
import json
from pathlib import Path

import yaml

from wiki_metadata import parse_datetime, split_frontmatter
from wiki_rule_fingerprint import checker_fingerprint
from wiki_review_policy import (REVIEW_FIELDS, REVIEW_POLICY, apply_review_severity,
                                claim_category, validate_review_policy)


STATUSES = {'pending', 'proposed-supported', 'supported', 'non-quantity', 'author-structure'}
TEMPORAL_FIELDS = {'timestamp', 'published_at', 'published_date', 'publication_date',
                   'published', 'captured_at', 'collected_at', 'duration',
                   'duration_seconds', 'video_duration'}


def metadata_evidence(content, parse=split_frontmatter):
    """Expose explicit temporal scalar values, never index all YAML as prose."""
    frontmatter, _, _, error = parse(content)
    if error:
        return []
    node = yaml.compose(frontmatter)
    if not isinstance(node, yaml.MappingNode):
        return []
    return [{'field': key.value, 'quote': value.value, 'line': value.start_mark.line + 2}
            for key, value in node.value if key.value in TEMPORAL_FIELDS
            and isinstance(value, yaml.ScalarNode) and value.value.strip()
            and value.tag not in ('tag:yaml.org,2002:null', 'tag:yaml.org,2002:bool')]


def valid_evidence(evidence, finding, snapshot, metadata_cache):
    path = evidence['path']
    via = evidence.get('via')
    if via is not None:
        if path not in finding.get('cross_page_sources', {}).get(via, []):
            return False
    elif path not in finding.get('sources', []):
        return False
    if 'field' in evidence:
        return any(item['field'] == evidence['field'] and item['quote'] == evidence['quote']
                   for item in metadata_cache[path])
    return evidence['quote'] in snapshot.documents.get(path, {}).get('body', '')


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
            raise ValueError('复核状态仅支持 pending、proposed-supported、supported、non-quantity、author-structure')
        if record['status'] == 'proposed-supported' and 'review_policy' not in record:
            raise ValueError('提议必须使用新版复核模板')
        validate_review_policy(record)
        if record['status'] != 'pending':
            if any(not isinstance(record.get(k), str) or not record[k].strip()
                   for k in ('reason', 'reviewer', 'reviewed_at')) or not parse_datetime(record['reviewed_at']):
                raise ValueError('已复核记录必须提供 reason、reviewer 与有效 reviewed_at')
            if not isinstance(record.get('evidence'), list):
                raise ValueError('已复核记录必须提供 evidence 数组')
            if record['status'] in ('supported', 'proposed-supported') and not record['evidence']:
                raise ValueError('supported 或提议记录必须提供来源原文片段')
            for evidence in record['evidence']:
                if (not isinstance(evidence, dict) or
                        any(not isinstance(evidence.get(k), str) or not evidence[k].strip() for k in ('path', 'quote'))):
                    raise ValueError('evidence 条目必须提供 path 与非空 quote')
                for key in ('field', 'via'):
                    if key in evidence and (not isinstance(evidence[key], str) or not evidence[key].strip()):
                        raise ValueError(f'evidence 的 {key} 必须为非空字符串')
                if 'field' in evidence and evidence['field'] not in TEMPORAL_FIELDS:
                    raise ValueError('frontmatter 证据只支持已定义的日期、采集时间和时长字段')
    return data['records']


def compatible_review_rules(rules_fingerprint):
    """Explicit, exact release aliases only; never ignore rules or content hashes."""
    path = Path(__file__).parent.parent / 'references/review-compatibility.json'
    return json.loads(path.read_text(encoding='utf-8')).get(rules_fingerprint, [])


def legacy_review_rules():
    path = Path(__file__).parent.parent / 'references/review-compatibility.json'
    return json.loads(path.read_text(encoding='utf-8')).get('legacy_review_rules', [])


def annotate_reviews(all_issues, snapshot, records, rules_fingerprint):
    """Bind each decision to the whole page, dependency chain and checker rules."""
    prior = {record['id']: record for record in records}
    exported, used = {}, set()
    hashes = {path: digest(text) for path, text in snapshot.originals.items()}
    metadata_cache = {}
    compatible_rules = compatible_review_rules(rules_fingerprint)
    legacy_rules = legacy_review_rules()
    for path, finding in all_issues:
        options = []
        routes = [(None, finding.get('sources', [])), *finding.get('cross_page_sources', {}).items()]
        for via, sources in routes:
            for source in sources:
                if source not in metadata_cache:
                    metadata_cache[source] = metadata_evidence(snapshot.originals.get(source, ''), snapshot.parse)
                options.extend({'path': source, **item, **({'via': via} if via else {})}
                               for item in metadata_cache[source])
        finding['metadata_evidence'] = options
        dependencies = sorted(set(finding.get('review_dependencies', []) + finding.get('sources', []) + [path]))
        complete = all(p in hashes for p in dependencies) and not snapshot.errors
        for detail in finding.get('details', []):
            detail.pop('review', None)
            category = claim_category(detail)
            identity = {'page': path, 'claim': detail['claim'], 'kind': detail['kind'],
                        'context': detail['context'], 'line': detail.get('line', finding.get('line')),
                        'dependencies': {p: hashes.get(p) for p in dependencies}, 'rules': rules_fingerprint}
            key = digest(json.dumps(identity, ensure_ascii=False, sort_keys=True))
            record = {'id': key, **identity, 'status': 'pending', 'reason': '',
                      'reviewer': '', 'reviewed_at': '', 'evidence': [],
                      'review_policy': REVIEW_POLICY, 'category': category,
                      'source_values': '', 'derivation': '', 'approximation_span': '',
                      'human_confirmation': None}
            record['evidence_options'] = {
                'metadata': finding.get('metadata_evidence', []),
                'cross_page_sources': finding.get('cross_page_sources', {}),
            }
            old = prior.get(key)
            # A compatible legacy record retains its original identity on export.
            # New or stale claims always receive the current policy and rules.
            if old is None:
                for rules in compatible_rules:
                    legacy_identity = {**identity, 'rules': rules}
                    legacy_key = digest(json.dumps(legacy_identity, ensure_ascii=False, sort_keys=True))
                    legacy = prior.get(legacy_key)
                    if legacy and legacy['status'] != 'pending':
                        old, identity, key = legacy, legacy_identity, legacy_key
                        break
            if old and complete and all(old.get(k) == v for k, v in identity.items()):
                evidence_valid = all(valid_evidence(evidence, finding, snapshot, metadata_cache)
                                     for evidence in old.get('evidence', []))
                policy_valid = (old.get('review_policy') == REVIEW_POLICY and old.get('category') == category)
                legacy_valid = ('review_policy' not in old and old['rules'] in compatible_rules
                                and old['rules'] in legacy_rules)
                if (policy_valid or legacy_valid) and (old['status'] == 'pending' or evidence_valid):
                    validate_review_policy(old)
                    if legacy_valid:
                        record = {**old, 'evidence_options': record['evidence_options']}
                    else:
                        record.update(id=key, rules=identity['rules'])
                        record.update({field: old.get(field, record[field]) for field in REVIEW_FIELDS})
                    used.add(key)
            detail['review_id'] = record['id']
            detail['review_category'] = category
            if record['status'] != 'pending':
                detail['review'] = {k: record.get(k) for k in REVIEW_FIELDS}
            exported[record['id']] = record
        apply_review_severity(finding)
    stale = sum(record['status'] != 'pending' and record['id'] not in used for record in records)
    return {'version': 1, 'records': list(exported.values())}, stale
