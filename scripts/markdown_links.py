"""Conservative Markdown link spans for edits that preserve surrounding text.

Offsets always refer to the original document. Code, comments and frontmatter
are masked rather than deleted. Unrecognized syntax is left unchanged.
"""
import re


def blank(text):
    return "".join("\n" if c == "\n" else " " for c in text)


def mask_non_prose(content):
    """Mask syntax in context; comment markers inside code are literal text."""
    text = re.sub(r"\A\ufeff?---\r?\n.*?\r?\n---(?:\r?\n|$)",
                  lambda m: blank(m.group()), content, count=1, flags=re.S)
    edits = []
    fence = None
    position = 0
    while position < len(text):
        if position == 0 or text[position - 1] == "\n":
            end = text.find("\n", position)
            end = len(text) if end < 0 else end + 1
            line = text[position:end]
            inner = re.sub(r"^(?: {0,3}>[ \t]?)+", "", line)
            marker = re.match(r"^\s*(?:[-+*] |\d+[.)] )?(`{3,}|~{3,})(.*)$", inner)
            if fence or marker or inner.startswith(("    ", "\t")):
                if fence:
                    if marker and marker[1][0] == fence[0] and len(marker[1]) >= fence[1] and not marker[2].strip():
                        fence = None
                elif marker:
                    fence = (marker[1][0], len(marker[1]))
                edits.append((position, end))
                position = end
                continue
        if text.startswith("<!--", position) and not escaped(text, position):
            end = text.find("-->", position + 4)
            end = len(text) if end < 0 else end + 3
            edits.append((position, end))
            position = end
            continue
        if text[position] == "`" and not escaped(text, position):
            opening = re.match(r"`+", text[position:])[0]
            start = position + len(opening)
            # Code spans cannot consume a new paragraph or a fenced code block.
            boundary = re.search(r"\n[ \t]*\n|\n {0,3}(?:`{3,}|~{3,})", text[start:])
            end = start + boundary.start() if boundary else len(text)
            closing = re.search(r"(?<!`)" + re.escape(opening) + r"(?!`)", text[start:end])
            if closing:
                end = start + closing.end()
                edits.append((position, end))
                position = end
                continue
            position = start
            continue
        position += 1
    chunks = []
    previous = 0
    for start, end in edits:
        chunks.extend((text[previous:start], blank(text[start:end])))
        previous = end
    chunks.append(text[previous:])
    return "".join(chunks)


def escaped(text, index):
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == "\\":
        backslashes += 1
        index -= 1
    return backslashes % 2 == 1


def destination_span(text, start):
    """Return only the destination, leaving angle brackets and titles untouched."""
    if start >= len(text):
        return None
    if text[start] == "<":
        end = start + 1
        while end < len(text) and text[end] != "\n":
            if text[end] == ">" and not escaped(text, end):
                return start + 1, end, end + 1
            end += 1
        return None
    depth = 0
    end = start
    while end < len(text):
        char = text[end]
        if escaped(text, end):
            end += 1
            continue
        if char.isspace():
            break
        if char == "(":
            depth += 1
        elif char == ")":
            if depth == 0:
                break
            depth -= 1
        end += 1
    if depth:
        return None
    return start, end, end


def inline_end(text, offset):
    while offset < len(text) and text[offset].isspace():
        offset += 1
    if offset >= len(text):
        return None
    if text[offset] in {'"', "'", "("}:
        closing = ")" if text[offset] == "(" else text[offset]
        offset += 1
        while offset < len(text) and (text[offset] != closing or escaped(text, offset)):
            offset += 1
        offset += 1
        while offset < len(text) and text[offset].isspace():
            offset += 1
    return offset + 1 if offset < len(text) and text[offset] == ")" else None


def _inline_link_occurrences(text):
    stack = []
    for index, char in enumerate(text):
        if escaped(text, index):
            continue
        if char == "[":
            stack.append(index)
        elif char == "]" and stack:
            opening = stack.pop()
            if text[opening:opening + 2] == "[[" or text[index + 1:index + 2] != "(":
                continue
            start = index + 2
            while start < len(text) and text[start].isspace():
                start += 1
            span = destination_span(text, start)
            closing = inline_end(text, span[2]) if span else None
            if closing is not None:
                yield opening, span[0], span[1], closing


def standard_link_occurrences(text):
    """Yield (use offset, destination start, destination end) for each link use.

    Reference uses share a destination in their definition, but keep their own
    locations for section checks and duplicate-entry detection.
    """
    definitions = {}
    prose = text
    for match in re.finditer(r"^ {0,3}\[(?![\[^])[^\]\n]+\]:[ \t]*(?:\n[ \t]*)?", text, re.M):
        span = destination_span(text, match.end())
        if span:
            label = match.group().split("[", 1)[1].split("]", 1)[0]
            definitions.setdefault(" ".join(label.split()).casefold(), (span[0], span[1]))
            end = text.find("\n", span[2])
            if end == -1:
                end = len(text)
            prose = prose[:match.start()] + blank(prose[match.start():end]) + prose[end:]
    for opening, start, end, closing in _inline_link_occurrences(prose):
        yield opening, start, end
        # Inline labels and destinations are not shortcut reference uses.
        prose = prose[:opening] + blank(prose[opening:closing]) + prose[closing:]
    for match in re.finditer(r"(?<![\\\[])\[([^\[\]\n]+)\](?!\])(?:\[([^\]\n]*)\])?", prose):
        label = match[2] or match[1]
        span = definitions.get(" ".join(label.split()).casefold())
        if span:
            yield match.start(), span[0], span[1]


def standard_link_spans(text):
    """Yield each destination once for safe replacements, including references."""
    emitted = set()
    for _, start, end in standard_link_occurrences(text):
        if (start, end) not in emitted:
            yield start, end
            emitted.add((start, end))


def wikilink_spans(text):
    for match in re.finditer(r"\[\[([^\]\n|]+?)(?:\\?\|[^\]\n]*)?\]\]", text):
        if not escaped(text, match.start()):
            start, end = match.span(1)
            # The slash escaping a table's alias separator is not part of the path.
            if text[end - 1:end] == "\\":
                end -= 1
            yield start, end


def mask_link_metadata(text, hide_label_at=None):
    """Keep visible claims, masking targets/titles and optional navigation labels."""
    edits = []
    for opening, start, end, closing in _inline_link_occurrences(text):
        label_end = text.rfind("](", opening, start) + 1
        edits.append((opening if hide_label_at and hide_label_at(opening) else label_end, closing))
    for match in re.finditer(r"^ {0,3}\[(?![\[^])[^\]\n]+\]:[ \t]*(?:\n[ \t]*)?", text, re.M):
        span = destination_span(text, match.end())
        if span:
            end = text.find("\n", span[2])
            end = len(text) if end < 0 else end
            # A continued title is metadata; arbitrary indented prose is not.
            title = re.match(r'''\n[ \t]+(?:"[^"\n]*"|'[^'\n]*'|\([^)\n]*\))[ \t]*(?=\n|$)''', text[end:])
            edits.append((match.start(), end + title.end() if title else end))
    if hide_label_at:
        for opening, _, _ in standard_link_occurrences(text):
            if hide_label_at(opening):
                use = re.match(r"\[[^\]\n]+\](?:\[[^\]\n]*\])?", text[opening:])
                if use:
                    edits.append((opening, opening + use.end()))
    for match in re.finditer(r"\[\[([^\]\n|]+?)(?:\\?\|([^\]\n]*))?\]\]", text):
        if escaped(text, match.start()):
            continue
        if hide_label_at and hide_label_at(match.start()):
            edits.append(match.span())
        elif match[2] is not None:
            # Retain brackets as boundaries between adjacent linked quantities.
            edits.append((match.start() + 2, match.start(2)))
    # Spans may overlap (e.g. a whole navigation link and its destination).
    masked = list(text)
    for start, end in edits:
        masked[start:end] = blank(text[start:end])
    return "".join(masked)


def unescape_target(text):
    return re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])", r"\1", text)
