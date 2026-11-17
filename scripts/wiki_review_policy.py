"""Review categories and human confirmation contract, separate from evidence lookup."""
import re

from wiki_metadata import parse_datetime
from wiki_numbers import quantities
from wiki_provenance import PROCESSED_CLAIM


REVIEW_POLICY = 2
UNLOCATED_KINDS = {'not-found', 'quote-not-found'}
CATEGORIES = {'direct', 'derived', 'approximate'}
REVIEW_FIELDS = ('status', 'reason', 'reviewer', 'reviewed_at', 'evidence',
                 'source_values', 'derivation', 'approximation_span', 'human_confirmation')
DERIVATION = re.compile(
    r'计算|估算|推算|推导|折算|换算|合计|总计|平均|增幅|降幅|增长率|占比|相差|之和|之差|乘以|除以'
    r'|[×÷=＝]|\d\s*[+＋*/]\s*\d|\d\s+[-−]\s+\d'
    r'|\b(?:calculated|derived|estimated|sum|average|ratio|rounded)\b', re.I)


def claim_category(detail):
    """Use the full attributed segment; derived takes precedence over approximate."""
    context = detail.get('review_context', detail['context'])
    # Slash-separated dates (even ambiguous ones) are not division formulas.
    context = re.sub(r'\b\d{1,4}/\d{1,2}/\d{1,4}\b', '', context)
    if PROCESSED_CLAIM.search(context) or DERIVATION.search(context):
        return 'derived'
    values = quantities(detail['claim'])
    if (detail['kind'] == 'approximation-difference'
            or any(value.key and value.key[0] in ('approx', 'near') for value in values)):
        return 'approximate'
    return 'direct'


def nonempty(record, key):
    return isinstance(record.get(key), str) and bool(record[key].strip())


def validate_review_policy(record):
    """Validate submitted fields; category is also recomputed at reuse time."""
    if 'review_policy' not in record:
        return  # Legacy eligibility is checked against the exact rules fingerprint.
    if record['review_policy'] != REVIEW_POLICY or record.get('category') not in CATEGORIES:
        raise ValueError('复核记录须保留 review_policy 与工具生成的 category')
    status, category = record['status'], record['category']
    gated = category in ('derived', 'approximate')
    if status == 'proposed-supported' or (status == 'supported' and gated):
        if not gated:
            raise ValueError('直接陈述使用 supported，不使用 proposed-supported')
        explanation = 'derivation' if category == 'derived' else 'approximation_span'
        if not nonempty(record, 'source_values') or not nonempty(record, explanation):
            raise ValueError(f'提议须预填 source_values 与 {explanation}')
    confirmation = record.get('human_confirmation')
    if confirmation is not None or (status == 'supported' and gated):
        if (not isinstance(confirmation, dict) or not nonempty(confirmation, 'reviewer')
                or not nonempty(confirmation, 'confirmed_at')
                or not parse_datetime(confirmation['confirmed_at'])):
            raise ValueError('派生或近似主张转为 supported 须填写 human_confirmation 的 reviewer 与 confirmed_at')


def review_completed(detail):
    return detail.get('review', {}).get('status') in ('supported', 'non-quantity', 'author-structure')


def apply_review_severity(finding):
    """Only supported unlocated claims change level; mixed issues keep the maximum."""
    details = finding.get('details', [])
    if finding.get('category') != 'evidence' or not details:
        return
    for detail in details:
        if detail['kind'] in UNLOCATED_KINDS:
            detail['level'] = '🔵' if detail.get('review', {}).get('status') == 'supported' else '🟡'
    if finding['level'] != '🔴':
        finding['level'] = max((d['level'] for d in details), key={'🔵': 0, '🟡': 1, '🔴': 2}.get)
