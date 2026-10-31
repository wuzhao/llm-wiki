"""Conservative, exact quantity equivalence for evidence lookup, not fact checking."""
import re
from dataclasses import dataclass, field
from datetime import date
from fractions import Fraction


# One-to-one translation keeps diagnostic spans in the original text intact.
WIDTH = str.maketrans({**{chr(n): chr(n - 0xFEE0) for n in range(0xFF01, 0xFF5F)},
                      "\u3000": " ", "−": "-"})
DIGITS = dict(zip("零〇一二三四五六七八九", (0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9)))
DIGITS["两"] = 2
SMALL = {"十": 10, "百": 100, "千": 1000}
CN = "零〇一二两三四五六七八九十百千万亿点几多余半"
SPACE = r"[^\S\n]*"
# 百 in 百分点 belongs to the unit, not the preceding numeric value.
NUMBER = rf"(?:数{SPACE}(?=[十百千万亿]))?(?:(?:(?!百分点)[0-9{CN}])+(?:,[0-9]+)*(?:\.[0-9]+)?(?:(?!百分点)[十百千万亿])*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
# Keep adjacent magnitude components atomic, including unsupported orders. Do
# not join across punctuation, citations, line breaks or repeated explicit units.
COMPOSITE = rf"(?:[0-9]+{SPACE}[十百千万亿]{SPACE})+[0-9]+{SPACE}[十百千万亿](?![0-9{CN}])"

# Only explicit aliases and exact conversions. Counts and percentages keep their
# dimensions; decimal storage units are deliberately separate from binary units.
UNITS = {unit: (unit, Fraction(1)) for unit in
         ("个", "条", "项", "种", "次", "人", "位", "家", "年", "月", "倍", "元", "美元", "%", "‰", "个百分点")}
for aliases, dimension, factor in (
    (("%",), "ratio", Fraction(1, 100)),
    (("‰",), "ratio", Fraction(1, 1000)),
    (("ms", "毫秒"), "time", Fraction(1, 1000)),
    (("s", "秒"), "time", 1),
    (("分钟",), "time", 60),
    (("小时",), "time", 3600),
    (("MB",), "bytes", 1000 ** 2),
    (("GB",), "bytes", 1000 ** 3),
    (("TB",), "bytes", 1000 ** 4),
    (("MiB",), "binary-bytes", 1024 ** 2),
    (("GiB",), "binary-bytes", 1024 ** 3),
    (("TiB",), "binary-bytes", 1024 ** 4),
    (("百分点",), "个百分点", 1),
):
    UNITS.update({alias: (dimension, Fraction(factor)) for alias in aliases})
UNIT = "(?:" + "|".join(sorted(UNITS, key=len, reverse=True)) + ")"
QUALIFIERS = {
    "大约": "approx", "大概": "approx", "约为": "approx", "约": "approx", "左右": "approx", "上下": "approx",
    "≈": "approx", "~": "approx", "～": "approx",
    "近": "near", "至少": "gte", "不少于": "gte", "不低于": "gte", "以上": "gte", "≥": "gte", ">=": "gte",
    "至多": "lte", "不超过": "lte", "以下": "lte", "以内": "lte", "≤": "lte", "<=": "lte",
    "大于等于": "gte", "不小于": "gte", "小于等于": "lte", "不大于": "lte",
    "超过": "gt", "多于": "gt", "大于": "gt", "高于": "gt", ">": "gt",
    "不足": "lt", "不到": "lt", "少于": "lt", "小于": "lt", "低于": "lt", "<": "lt", "第": "ordinal",
    "about": "approx", "approximately": "approx", "around": "approx",
    "at least": "gte", "at most": "lte", "more than": "gt", "less than": "lt",
}
PREFIX = "(?:" + "|".join(re.escape(q) for q in sorted(QUALIFIERS, key=len, reverse=True)
                          if not q.isascii()) + r"|>=|<=|>|<|~|(?i:\babout|\bapproximately|\baround|\bat least|\bat most|\bmore than|\bless than))"
SUFFIX = r"(?:以上|以下|以内|左右|上下)"

# Full dates are atomic. Numeric month/day order without a leading year remains
# opaque, while named English months and Chinese 年/月/日 are unambiguous.
MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December")
MONTHS = {name.lower(): index for index, name in enumerate(MONTH_NAMES, 1)}
MONTHS.update({name[:3].lower(): index for index, name in enumerate(MONTH_NAMES, 1)})
MONTHS["sept"] = 9
MONTH = "(?i:" + "|".join(sorted(MONTHS, key=len, reverse=True)) + r")\.?"
DATE_DIGITS = "零〇一二三四五六七八九十"
DATE_PART = rf"[0-9{DATE_DIGITS}]{{1,3}}"
DATE_YEAR_GAP = r"(?:[ \t]*,[ \t]*|[ \t]+)"
DATE = (
    rf"(?:[0-9]{{4}}-[0-9]{{1,2}}-[0-9]{{1,2}}"
    rf"|[0-9零〇一二三四五六七八九]{{4}}{SPACE}年{SPACE}{DATE_PART}{SPACE}月{SPACE}{DATE_PART}{SPACE}[日号]"
    rf"|{MONTH}[ \t]+[0-9]{{1,2}}{DATE_YEAR_GAP}[0-9]{{4}}"
    rf"|[0-9]{{1,2}}[ \t]+{MONTH}{DATE_YEAR_GAP}[0-9]{{4}}"
    rf"|[0-9]{{1,2}}/[0-9]{{1,2}}/[0-9]{{4}})"
)
DATE_QUALIFIERS = {**QUALIFIERS, "早于": "before", "之前": "before", "以前": "before",
                   "晚于": "after", "之后": "after", "以后": "after", "截至": "through",
                   "不早于": "not-before", "不晚于": "not-after", "自": "from", "起": "from",
                   "before": "before", "after": "after", "on or before": "not-after",
                   "on or after": "not-before", "by": "through", "from": "from"}
DATE_TOKEN = re.compile(
    rf"(?<![A-Za-z0-9_.{CN}])(?:(?P<prefix>{PREFIX}|不早于|不晚于|截至|早于|晚于|自|[+\-正负]"
    rf"|(?i:\bon or before|\bon or after|\bbefore|\bafter|\bby|\bfrom)){SPACE})?"
    rf"(?P<date>{DATE})"
    rf"(?:{SPACE}(?P<range>至|到|[-–—~～]|(?i:\bto\b)){SPACE}"
    rf"(?P<end>{DATE}|[0-9]{{4}}-[0-9]{{1,2}}"
    rf"|(?:[0-9{DATE_DIGITS}]{{4}}{SPACE}年{SPACE})?{DATE_PART}{SPACE}月(?:{SPACE}{DATE_PART}{SPACE}[日号])?"
    rf"|{MONTH}[ \t]+[0-9]{{1,2}}(?![0-9])|[0-9]{{1,2}}[ \t]+{MONTH}"
    rf"|[0-9{DATE_DIGITS}]{{1,4}}{SPACE}[年月日号]?|今|目前|现在))?"
    rf"(?:{SPACE}(?P<suffix>{SUFFIX}|之前|之后|以前|以后|起))?"
)
LEXICAL_COUNT = re.compile(
    r"一次性|二次(?:分配|引用|创作|转载|开发|传播|函数|方程)"
    r"|[二三]元(?:组|关系|结构|架构|对立|区分|逻辑|论|角色|分工|协作)"
)
COMPOUND_UNIT = re.compile(r"(?:[/·][A-Za-z0-9\u4e00-\u9fff/·²³^+\-]+|[²³])")
# A sign can be spoken as 负的; lexical 自负/担负/背负/胜负 are not signs.
SIGN = rf"(?:[+\-]|正(?:{SPACE}的)?|(?<![自担背胜])负(?:{SPACE}的)?)"


def endpoint(suffix):
    return (rf"(?:(?P<sign{suffix}>{SIGN}){SPACE})?"
            rf"(?:(?P<percent{suffix}>百分之){SPACE})?"
            rf"(?:(?P<inner_sign{suffix}>{SIGN}){SPACE})?"
            rf"(?P<number{suffix}>{COMPOSITE}|{NUMBER}(?:[^\S\n]+(?!百分点)[十百千万亿])?)"
            rf"(?:{SPACE}(?P<unit{suffix}>{UNIT}))?")


TOKEN = re.compile(
    rf"(?<![A-Za-z0-9_.{CN}])"
    rf"(?:(?P<prefix>{PREFIX}){SPACE})?{endpoint('1')}"
    rf"(?:{SPACE}(?P<range>至|到|[-–—~～]){SPACE}{endpoint('2')})?"
    rf"(?:{SPACE}(?P<suffix>{SUFFIX}))?"
)


@dataclass(frozen=True)
class Quantity:
    literal: str
    key: tuple | None
    start: int = field(default=0, compare=False)
    end: int = field(default=0, compare=False)
    units: tuple = field(default=(), compare=False)


def chinese_integer(text):
    """Reject abbreviated/ambiguous forms such as 三五, 一百二 and 一万二."""
    if text in SMALL or text in ("万", "亿"):
        return {**SMALL, "万": 10000, "亿": 100000000}[text]
    for unit, factor in (("亿", 100000000), ("万", 10000)):
        if unit in text:
            if text.count(unit) != 1:
                return None
            left, right = text.split(unit)
            high = chinese_integer(left)
            # A trailing digit without 零 or an explicit place is ambiguous.
            if right and not right.startswith(("零", "〇")) and not any(u in right for u in (*SMALL, "万")):
                return None
            low = chinese_integer(right.lstrip("零〇")) if right.lstrip("零〇") else 0
            if high is None or not high or low is None or low >= factor:
                return None
            return high * factor + low
    if len(text) == 1:
        return DIGITS.get(text)
    total, digit, last_place, zero = 0, None, 10000, False
    for char in text:
        if char in DIGITS:
            value = DIGITS[char]
            if value == 0:
                if digit is not None:
                    return None
                zero = True
            else:
                if digit is not None:
                    return None
                digit = value
        elif char in SMALL:
            place = SMALL[char]
            if place >= last_place or (digit is None and not (place == 10 and total == 0)):
                return None
            total += (digit if digit is not None else 1) * place
            last_place, digit, zero = place, None, False
        else:
            return None
    if digit is not None:
        if last_place not in (10, 10000) and not zero:
            return None
        total += digit
    return total if total else None


def number_value(text, unit):
    text = re.sub(r"[^\S\n]+", "", text)
    scales = {**SMALL, "万": 10000, "亿": 100000000}
    if re.fullmatch(r"(?:[0-9]+[十百千万亿]){2,}", text):
        total, previous = 0, None
        for digits, magnitude in re.findall(r"([0-9]+)([十百千万亿])", text):
            scale = scales[magnitude]
            component = int(digits) * scale
            if previous is not None and (scale >= previous or component >= previous):
                return None
            total += component
            previous = scale
        return Fraction(total)
    arabic = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?|\.[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]+)?)([十百千万亿]?)", text)
    if arabic:
        scale = {"": 1, **SMALL, "万": 10000, "亿": 100000000}[arabic[2]]
        return Fraction(arabic[1].replace(",", "")) * scale
    if unit == "年" and len(text) == 4 and all(c in DIGITS and c != "两" for c in text):
        return Fraction(int("".join(str(DIGITS[c]) for c in text)))
    scale = 1
    if "点" in text and text[-1:] in ("万", "亿"):
        scale = {"万": 10000, "亿": 100000000}[text[-1]]
        text = text[:-1]
    pieces = text.split("点")
    integer = chinese_integer(pieces[0])
    if integer is None or len(pieces) > 2:
        return None
    if len(pieces) == 1:
        return Fraction(integer)
    if not pieces[1] or any(c not in DIGITS or c == "两" for c in pieces[1]):
        return None
    fraction = "".join(str(DIGITS[c]) for c in pieces[1])
    return (Fraction(integer) + Fraction(int(fraction), 10 ** len(fraction))) * scale


def calendar_date(text):
    iso = re.fullmatch(r"([0-9]{4})-([0-9]{1,2})-([0-9]{1,2})", text)
    chinese = re.fullmatch(rf"([0-9零〇一二三四五六七八九]{{4}}){SPACE}年{SPACE}"
                          rf"({DATE_PART}){SPACE}月{SPACE}({DATE_PART}){SPACE}[日号]", text)
    english = re.fullmatch(rf"({MONTH})[ \t]+([0-9]{{1,2}}){DATE_YEAR_GAP}([0-9]{{4}})", text)
    day_first = re.fullmatch(rf"([0-9]{{1,2}})[ \t]+({MONTH}){DATE_YEAR_GAP}([0-9]{{4}})", text)
    try:
        if iso:
            parts = [int(value) for value in iso.groups()]
        elif chinese:
            year = int("".join(str(DIGITS[c]) if c in DIGITS else c for c in chinese[1]))
            parts = [year, *(int(value) if value.isascii() else chinese_integer(value) for value in chinese.groups()[1:])]
        elif english:
            parts = [int(english[3]), MONTHS[english[1].rstrip(".").lower()], int(english[2])]
        elif day_first:
            parts = [int(day_first[3]), MONTHS[day_first[2].rstrip(".").lower()], int(day_first[1])]
        else:
            return None
        return date(*parts)
    except (TypeError, ValueError):
        return None


def date_key(match):
    if match["prefix"] in ("+", "-", "正", "负"):
        return None
    values = [calendar_date(match["date"])]
    if match["range"]:
        values.append(calendar_date(match["end"]))
    if any(value is None for value in values) or (len(values) == 2 and values[0] > values[1]):
        return None
    prefix = DATE_QUALIFIERS.get((match["prefix"] or "").lower(), "exact")
    suffix = DATE_QUALIFIERS.get(match["suffix"], "exact")
    if prefix != "exact" and suffix != "exact" and prefix != suffix:
        return None
    return ("date", prefix if prefix != "exact" else suffix, *values)


def quantity_units(match):
    units = [match["unit1"] or ("%" if match["percent1"] else ""),
             match["unit2"] or ("%" if match["percent2"] else "")]
    if match["range"]:
        units = [units[0] or units[1], units[1] or units[0]]
    return tuple(units[:2 if match["range"] else 1])


def quantity_key(match):
    units = quantity_units(match)
    if match["range"]:
        # Shared magnitudes (10 至 20 万) need language interpretation.
        if (match["number2"].endswith(tuple("百千万亿")) and not match["unit1"]
                and not any(c in match["number1"] for c in "百千万亿")):
            return None
    values = []
    for index in range(1, 3 if match["range"] else 2):
        try:
            value = number_value(match[f"number{index}"], units[index - 1])
        except ValueError:  # E.g. Python's limit on extremely long integer strings.
            return None
        if value is None or (match[f"percent{index}"] and match[f"unit{index}"]):
            return None
        dimension, factor = UNITS.get(units[index - 1], ("number", 1))
        if match[f"sign{index}"] and match[f"inner_sign{index}"]:
            return None
        sign_text = match[f"sign{index}"] or match[f"inner_sign{index}"] or ""
        sign = -1 if sign_text.startswith(("-", "负")) else 1
        values.append((dimension, value * factor * sign))
    if len(values) == 2 and (values[0][0] != values[1][0] or values[0][1] > values[1][1]):
        return None
    prefix = QUALIFIERS.get((match["prefix"] or "").lower(), "exact")
    suffix = QUALIFIERS.get(match["suffix"], "exact")
    if prefix != "exact" and suffix != "exact" and prefix != suffix:
        return None
    return (prefix if prefix != "exact" else suffix, *values)


def nonquantitative_count(text, match):
    # Only complete lexical forms and explicit selectors are excluded. Bare
    # 一项/两条 and asserted counts such as 只有一人 or 重试两次 remain claims.
    if match["range"] or match["prefix"] or match["suffix"] or match["sign1"] or match["percent1"]:
        return False
    if LEXICAL_COUNT.match(text, match.start()):
        return True
    return (match["number1"] == "一" and match["unit1"] in ("个", "条", "项", "种", "次", "人", "位", "家")
            and re.search(r"[同另每某这那上下][ \t]*$", text[:match.start()]) is not None)


def quantities(text):
    """Extract complete candidates, preserving unsupported forms for review."""
    normalized = text.translate(WIDTH)
    # Markdown list markers are not arithmetic signs. Keep offsets unchanged.
    normalized = re.sub(r"(?m)^([ \t]*)[-+](?=[ \t])", lambda m: m[1] + " ", normalized)
    result = []
    numeric_text = list(normalized)
    consumed_end = 0
    for match in DATE_TOKEN.finditer(normalized):
        if match.start() < consumed_end:
            continue
        compound = COMPOUND_UNIT.match(normalized, match.end())
        end = compound.end() if compound else match.end()
        consumed_end = end
        following = normalized[match.end():match.end() + 1]
        if not following or not re.match(rf"[A-Za-z0-9_{CN}]", following):
            result.append((match.start(), Quantity(text[match.start():end].strip(), None if compound else date_key(match), match.start(), end)))
        # Keep a hard boundary so quantities cannot merge across a masked date.
        numeric_text[match.start():end] = ";" + " " * (end - match.start() - 1)
    numeric_text = "".join(numeric_text)
    consumed_end = 0
    for match in TOKEN.finditer(numeric_text):
        if match.start() < consumed_end:
            continue
        # Never accept a prefix of a larger numeric token or identifier.
        following = normalized[match.end():match.end() + 1]
        if (following and re.match(rf"[A-Za-z0-9_{CN}%]", following)
                or re.match(r"\.[0-9]", normalized[match.end():])):
            continue
        number = match["number1"] or ""
        if nonquantitative_count(normalized, match):
            continue
        # Keep anchored amounts (四十多年, 百余项, 半小时) in scope even when
        # unsupported. Generic 多次/几十次 and unitless 一半 are not precise claims.
        endpoints = [(match[f"number{i}"] or "", match[f"unit{i}"]) for i in (1, 2)]
        if any(any(char in value for char in "几数") or value in ("多", "余")
               or (value in ("半", "一半") and not unit) for value, unit in endpoints):
            continue
        bare_arabic = any(c.isdigit() for c in number) and (
            any(c in number for c in ".十百千万亿") or sum(c.isdigit() for c in number) >= 3)
        anchored_chinese = number.endswith(("多", "余")) and any(char in DIGITS for char in number)
        if not (match["unit1"] or match["unit2"] or match["percent1"] or match["percent2"]
                or bare_arabic or anchored_chinese):
            continue
        # An unparsed compound unit must not supply its scalar prefix as evidence.
        compound = COMPOUND_UNIT.match(normalized, match.end())
        end = compound.end() if compound else match.end()
        consumed_end = end
        result.append((match.start(), Quantity(text[match.start():end].strip(), None if compound else quantity_key(match),
                                             match.start(), end, quantity_units(match))))
    return [quantity for _, quantity in sorted(result, key=lambda item: item[0])]
