"""Explicit source sections; hashes are change signals, not semantic approval."""
import json
import re

from markdown_links import mask_non_prose
from wiki_metadata import body_sha256


HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")


def source_fragments(body, body_start_line=1):
    """Index ATX sections, including descendants, code, notes and parent titles.

    Only line endings and empty lines at section boundaries are normalized.
    Whitespace inside prose/code and Markdown markup remain significant.
    Duplicate titles are intentionally not given unstable ordinal selectors.
    """
    body = body.replace("\r\n", "\n")
    lines = body.split('\n')
    if lines[-1] == '':
        lines.pop()
    masked = mask_non_prose(body).split('\n')
    headings, parents = [], []
    for index, line in enumerate(lines):
        if not re.match(r'^ {0,3}#{1,6}[ \t]+', masked[index]):
            continue
        match = HEADING.fullmatch(line)
        if not match:
            continue
        level, title = len(match[1]), match[2]
        while parents and parents[-1][0] >= level:
            parents.pop()
        headings.append((index, level, title, [title for _, title in parents]))
        parents.append((level, title))
    result = []
    for offset, (start, level, title, ancestors) in enumerate(headings):
        end = next((index for index, depth, _, _ in headings[offset + 1:] if depth <= level), len(lines))
        text = '\n'.join(lines[start:end]).strip('\n')
        payload = json.dumps(['section-v1', ancestors, text], ensure_ascii=False)
        result.append({'heading': title, 'sha256': body_sha256(payload),
                       'line': body_start_line + start, 'end_line': body_start_line + end - 1})
    return result


def select_fragments(document, headings):
    """Export only explicitly selected, unique sections for a reviewed source."""
    available = source_fragments(document['body'], document.get('body_start_line', 1))
    selected = []
    for heading in dict.fromkeys(headings):
        matches = [fragment for fragment in available if fragment['heading'] == heading]
        if len(matches) != 1:
            raise ValueError(f'来源片段标题必须唯一且存在: {heading}')
        selected.append(matches[0])
    return selected


def fragment_changes(document, recorded):
    """Return reasons; malformed, missing and ambiguous scopes fail closed."""
    if not isinstance(recorded, list) or not recorded:
        return ['fragments 必须为非空片段数组']
    available = source_fragments(document['body'], document.get('body_start_line', 1))
    reasons, seen = [], set()
    for fragment in recorded:
        if (not isinstance(fragment, dict) or not isinstance(fragment.get('heading'), str)
                or not fragment['heading'].strip() or not isinstance(fragment.get('sha256'), str)
                or not re.fullmatch(r'[a-fA-F0-9]{64}', fragment['sha256'])):
            reasons.append('fragments 条目须包含非空 heading 和有效 sha256')
            continue
        heading = fragment['heading']
        if heading in seen:
            reasons.append(f'片段「{heading}」重复记录')
        seen.add(heading)
        matches = [item for item in available if item['heading'] == heading]
        if not matches:
            reasons.append(f'片段「{heading}」已删除或标题已改名')
        elif len(matches) != 1:
            reasons.append(f'片段「{heading}」标题不唯一，无法定位')
        elif matches[0]['sha256'] != fragment['sha256'].lower():
            current = matches[0]
            reasons.append(f'片段「{heading}」指纹已变化（当前行 {current["line"]} 至 {current["end_line"]}）')
    return reasons
