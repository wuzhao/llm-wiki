"""Review categories and human confirmation contract, separate from evidence lookup."""
import re

from wiki_metadata import parse_datetime
from wiki_numbers import WIDTH, quantities
from wiki_provenance import PROCESSED_CLAIM


REVIEW_POLICY = 2
CATEGORIES = {'direct', 'derived', 'approximate'}
REVIEW_FIELDS = ('status', 'reason', 'reviewer', 'reviewed_at', 'evidence',
                 'source_values', 'derivation', 'approximation_span', 'human_confirmation')
DERIVATION = re.compile(
    r'计算|估算|推算|推导|折算|换算|合计|总计|平均|增幅|降幅|增长率|占比|相差|之和|之差|乘以|除以'
    r'|[×÷=＝]|\d\s*[+＋*/]\s*\d|\d\s+[-−]\s+\d'
    r'|\b(?:calculated|derived|estimated|sum|average|ratio|rounded)\b', re.I)


# Unsupported quantity keys can still carry an explicit approximation marker.
DURATION_NUMBER = r"(?:半|[零〇一二两三四五六七八九十百千万0-9]+[多余]?)"
DURATION_UNIT = r"(?:年|个月|天|整天|小时|分钟|毫秒|秒)"
APPROX_DURATION = re.compile(
    rf"(?:大约|大概|约为|约){DURATION_NUMBER}{DURATION_UNIT}(?:左右|上下)?"
    rf"|{DURATION_NUMBER}{DURATION_UNIT}(?:左右|上下)"
    rf"|[零〇一二两三四五六七八九十百千万0-9]+[余多]{DURATION_UNIT}")


def claim_category(detail):
    """Use the full attributed segment; derived takes precedence over approximate."""
    context = detail.get('review_context', detail['context'])
    # Slash-separated dates (even ambiguous ones) are not division formulas.
    context = re.sub(r'\b\d{1,4}/\d{1,2}/\d{1,4}\b', '', context)
    if PROCESSED_CLAIM.search(context) or DERIVATION.search(context):
        return 'derived'
    values = quantities(detail['claim'])
    if (detail['kind'] == 'approximation-difference'
            or any(value.key and value.key[0] in ('approx', 'near') for value in values)
            or APPROX_DURATION.fullmatch(re.sub(r'\s+', '', detail['claim'].translate(WIDTH)))):
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
    """Lower a warning only when every bound review qualifies for a downgrade."""
    details = finding.get('details', [])
    if finding.get('category') != 'evidence' or not details:
        return
    # Keep the diagnostic levels so re-annotation after a stale review restores them.
    original = finding.setdefault('diagnostic_level', finding['level'])
    all_eligible = True
    for detail in details:
        base = detail.setdefault('diagnostic_level', detail['level'])
        eligible = review_completed(detail) and (
            detail['review_category'] == 'direct' or detail['review'].get('human_confirmation'))
        detail['level'] = '🔵' if eligible and base == '🟡' else base
        if not eligible:
            all_eligible = False
    finding['level'] = '🔵' if all_eligible and original == '🟡' else original
