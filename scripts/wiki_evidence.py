"""Literal evidence lookup and review candidates; never adjudicate facts."""
import bisect
import hashlib
import re

from markdown_links import blank, escaped, mask_link_metadata
from wiki_numbers import UNITS, WIDTH, quantities


CONTEXT_RADIUS = 45
MAX_CANDIDATES = 3
QUOTE_INTRO = re.compile(
    r"(?:(?:原文|原话|原句|直接引文|逐字引用|直接引用)(?:写道|写的是|表述为|说|称|是|为|如下)?\s*[:：]?"
    r"|(?:写道|说道|说|表示|指出|称)\s*[:：]|(?:verbatim|quote)\s*:)\s*$", re.I)
DIAGNOSTICS = {
    "predicate-count": ("否定谓语中的计数需语义核对", "由 Agent 核对找不到所指对象与否定范围；不按不到的数量上界比较，也不凭裸计数自动通过"),
    "year-abbreviation": ("可能是年份缩写，也可能是时长", "核对上下文与世纪；不自动将两位数年补为四位年份"),
    "approximation-difference": ("数值相同，仅普通近似词不同", "建议核对约、左右等表达与断言强度；不视为原文精确支持"),
    "qualifier-difference": ("数值相同但限定词不同", "保留原文的近似、上下界或序数含义，核对后再修改论断"),
    "unit-difference": ("数值部分相同但单位不同", "核对指标与单位；校准须将支持采用值的实际依据加入本条脚注的 raw 来源链"),
    "unit-missing": ("候选存在单位省略或补全", "核对原文语境中的单位，不自动接受补全"),
    "not-found": ("未找到可比较的数值候选", "回查原文；派生值列出有来源的分量和公式，校准值补充依据"),
    "quote-not-found": ("直接引文措辞未定位", "核对原句；转述应明确标示，不能当作逐字引文"),
    "translated-count": ("跨语言计数候选", "核对文件、文件夹等计数对象与归因；通用量词不能自动证明对象相同"),
}


def claim_text(text):
    # Keep a hard boundary between quantities separated by citations.
    return re.sub(r"\[\^[^\]\n]+\]", lambda m: ";" + blank(m.group()[1:]), mask_link_metadata(text))


def quoted_literals(text):
    values = set()
    for match in re.finditer(r'「([^「」\n]+)」|"([^"\n]+)"', text):
        if escaped(text, match.start()):
            continue
        prefix = text[:match.start()].replace("**", "").replace("__", "")
        if QUOTE_INTRO.search(prefix) or re.search(r"(?:^|\n) {0,3}>[ \t]*$", prefix):
            values.add(match[1] or match[2])
    return values


def claim_literals(text):
    text = claim_text(text)
    return {value.literal for value in quantities(text)} | quoted_literals(text)


def excerpt(text, start, end):
    left, right = max(0, start - CONTEXT_RADIUS), min(len(text), end + CONTEXT_RADIUS)
    return ("..." if left else "") + re.sub(r"\s+", " ", text[left:right]).strip() + ("..." if right < len(text) else "")


def related_quantity(claim, source):
    """Suggest bounded differences, without approving equivalence or inference."""
    if (claim.key is None or source.key is None or not claim.units or not source.units
            or len(claim.units) != len(source.units)):
        return None
    if claim.key[1:] == source.key[1:] and claim.key[0] != source.key[0]:
        if {claim.key[0], source.key[0]} <= {"exact", "approx"}:
            return "approximation-difference"
        return "qualifier-difference"
    if claim.key[0] != source.key[0]:
        return None
    if (claim.units == source.units == ("年",)
            and re.fullmatch(r"[0-9]{2}\s*年", source.literal.translate(WIDTH))
            and 1000 <= claim.key[1][1] <= 9999
            and claim.key[1][1].denominator == 1
            and claim.key[1][1] % 100 == source.key[1][1]):
        return "year-abbreviation"
    claim_values = tuple(value / UNITS.get(unit, ("number", 1))[1]
                         for (_, value), unit in zip(claim.key[1:], claim.units))
    source_values = tuple(value / UNITS.get(unit, ("number", 1))[1]
                          for (_, value), unit in zip(source.key[1:], source.units))
    if claim_values != source_values:
        return None
    if len(claim.units) == 1:
        count_units = {'count:folder': {'个', '项'}, 'count:file': {'个', '项'},
                       'count:resource': {'个', '项', '种'}, 'count:time': {'次', '倍'}}
        if (claim.units[0] in count_units.get(source.key[1][0], set())
                or source.units[0] in count_units.get(claim.key[1][0], set())):
            return "translated-count"
    if ((all(not unit for unit in claim.units) and all(source.units))
            or (all(not unit for unit in source.units) and all(claim.units))):
        return "unit-missing"
    families = lambda q: tuple("proportion" if dim in ("ratio", "个百分点") else dim for dim, _ in q.key[1:])
    if all(claim.units) and all(source.units) and claim.units != source.units and families(claim) == families(source):
        return "unit-difference"
    return None


class EvidenceDocument:
    def __init__(self, path, body, body_start_line=1):
        self.path, self.body, self.body_start_line = path, body, body_start_line
        self.quantities = quantities(claim_text(body))
        self.line_starts = [0] + [match.end() for match in re.finditer("\n", body)]
        self.fingerprint = hashlib.sha256(body.encode()).hexdigest()

    def candidate(self, quantity):
        line_index = bisect.bisect_right(self.line_starts, quantity.start) - 1
        return {"path": self.path, "line": self.body_start_line + line_index,
                "column": quantity.start - self.line_starts[line_index] + 1,
                "start": quantity.start, "end": quantity.end, "fingerprint": self.fingerprint,
                "literal": quantity.literal, "context": excerpt(self.body, quantity.start, quantity.end)}


class EvidenceIndex:
    def __init__(self, documents):
        self.documents = list(documents)
        self.values = [(document, value) for document in self.documents for value in document.quantities]
        self.keys = {value.key for _, value in self.values if value.key is not None}
        self.literal_forms = {value.literal for _, value in self.values}

    def contains(self, value):
        if value.key is None:
            return value.literal in self.literal_forms
        if value.key in self.keys:
            return True
        if value.adjacent_range and value.key[0] == "approx":
            (_, (dimension, low), (_, high)) = value.key
            # Directional location only: a source point can locate an approximate
            # claim, but a source approximation cannot establish an exact point.
            return any(len(key) == 2 and key[0] == "exact" and key[1][0] == dimension
                       and low <= key[1][1] <= high for key in self.keys)
        return False

    def missing(self, text):
        text = claim_text(text)
        missing = {value.literal for value in quantities(text) if not self.contains(value)}
        return sorted(missing | {value for value in quoted_literals(text)
                                 if not any(value in document.body for document in self.documents)})

    def diagnose(self, text):
        normalized = claim_text(text)
        details = {}
        for value in quantities(normalized):
            if self.contains(value) or value.literal in details:
                continue
            candidates = []
            for document, original in self.values:
                kind = related_quantity(value, original)
                if kind:
                    candidates.append((kind, document.candidate(original)))
            # An approximate candidate cannot hide a competing boundary, unit,
            # or ordinal difference. Ambiguous attribution still needs review.
            candidates.sort(key=lambda item: (item[0] == "approximation-difference",
                                               item[0], item[1]["path"], item[1]["start"]))
            kind = value.diagnostic or (candidates[0][0] if candidates else "not-found")
            selected = [candidate for reason, candidate in candidates if reason == kind]
            details[value.literal] = self.detail(value.literal, kind, text, value.start, value.end, selected)
        for value in quoted_literals(normalized):
            if not any(value in document.body for document in self.documents):
                start = normalized.find(value)
                details[value] = self.detail(value, "quote-not-found", text, start, start + len(value), [])
        return [details[key] for key in sorted(details)]

    @staticmethod
    def detail(literal, kind, text, start, end, candidates):
        label, action = DIAGNOSTICS[kind]
        level = "🔵" if kind == "approximation-difference" else "🟡"
        return {"claim": literal, "kind": kind, "label": label, "action": action, "level": level,
                "start": start, "context": excerpt(text, start, end),
                "candidates": candidates[:MAX_CANDIDATES], "candidate_count": len(candidates)}


def missing_literals(text, evidence):
    return EvidenceIndex([EvidenceDocument("", evidence)]).missing(text)
