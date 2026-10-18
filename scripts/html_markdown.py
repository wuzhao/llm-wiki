"""Conservative HTML-to-Markdown extraction; complex tables remain HTML."""
import html
import re
import urllib.parse
from html.parser import HTMLParser


class Node:
    def __init__(self, tag="", attrs=()):
        self.tag = tag
        self.attrs = dict(attrs)
        self.children = []


VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
HIDDEN = {"head", "script", "style", "template"}
BLOCKS = {"p", "div", "section", "article", "header", "footer", "aside", "nav", "main", "figure", "figcaption", "dl", "dt", "dd"}


def plain_text(node):
    if isinstance(node, str):
        return node
    if node.tag == "br":
        return "\n"
    return "".join(plain_text(child) for child in node.children)


def serialize(node):
    if isinstance(node, str):
        return html.escape(node, quote=False)
    attrs = "".join(f' {key}="{html.escape(value or "", quote=True)}"' for key, value in node.attrs.items())
    opening = f"<{node.tag}{attrs}>"
    if node.tag in VOID:
        return opening
    return opening + "".join(serialize(child) for child in node.children) + f"</{node.tag}>"


class ArticleTextParser(HTMLParser):
    def __init__(self, base_url=""):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.title = []
        self.base_url = base_url

    def handle_starttag(self, tag, attrs):
        # HTML permits omitted closing tags for these common structures.
        if tag in {"li", "tr", "td", "th", "p"} and self.stack[-1].tag == tag:
            self.stack.pop()
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)
        if any(node.tag == "title" for node in self.stack):
            self.title.append(data)

    def url(self, value):
        return urllib.parse.urljoin(self.base_url, value or "")

    def render_table(self, table):
        rows = []
        complex_table = False
        def collect(node):
            nonlocal complex_table
            if isinstance(node, str):
                return
            if node.tag == "table" and node is not table:
                complex_table = True
                return
            if node.tag == "tr":
                cells = [child for child in node.children if isinstance(child, Node) and child.tag in {"td", "th"}]
                if cells:
                    rows.append(cells)
            for child in node.children:
                collect(child)
        collect(table)
        for row in rows:
            for cell in row:
                if any(cell.attrs.get(key, "1") != "1" for key in ("rowspan", "colspan")):
                    complex_table = True
                if any(isinstance(child, Node) and child.tag in {"pre", "ul", "ol", "table"} for child in cell.children):
                    complex_table = True
        widths = {len(row) for row in rows}
        if complex_table or not rows or len(widths) != 1:
            return "\n\n" + serialize(table) + "\n\n"
        rendered = [[self.children(cell).strip().replace("|", "\\|").replace("\n", "<br>") for cell in row] for row in rows]
        has_header = all(cell.tag == "th" for cell in rows[0])
        header = rendered[0] if has_header else [""] * len(rows[0])
        data = rendered[1:] if has_header else rendered
        alignment = []
        for column in range(len(header)):
            values = [row[column] for row in data if row[column]]
            numeric = values and all(re.fullmatch(r"[\d.,%￥¥$+\-\s]+", value) for value in values)
            alignment.append("---:" if numeric or rows[0][column].attrs.get("align") == "right" else "---")
        lines = ["| " + " | ".join(row) + " |" for row in [header, alignment, *data]]
        caption = next((self.children(child).strip() for child in table.children if isinstance(child, Node) and child.tag == "caption"), "")
        return "\n\n" + (caption + "\n\n" if caption else "") + "\n".join(lines) + "\n\n"

    def children(self, node):
        return "".join(self.render(child) for child in node.children)

    def render(self, node):
        if isinstance(node, str):
            text = re.sub(r"\s+", " ", node)
            text = re.sub(r"&(?=(?:#[0-9]+|#x[0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);)", "&amp;", text)
            text = text.replace("<", "&lt;").replace(">", "&gt;")
            return re.sub(r"([\\`*_\[\]])", r"\\\1", text)
        tag = node.tag
        if tag in HIDDEN:
            return ""
        if tag == "pre":
            code = plain_text(node)
            runs = re.findall(r"`+", code)
            fence = "`" * max(3, max((len(run) + 1 for run in runs), default=0))
            language = ""
            for child in [node, *node.children]:
                if isinstance(child, Node):
                    match = re.search(r"(?:language-|lang-)([\w+-]+)", child.attrs.get("class", ""))
                    if match:
                        language = match[1]
                        break
            return "\n\n" + fence + language + "\n" + code + ("" if code.endswith("\n") else "\n") + fence + "\n\n"
        if tag == "code":
            code = plain_text(node)
            fence = "`" * (max((len(run) for run in re.findall(r"`+", code)), default=0) + 1)
            padding = " " if code.startswith("`") or code.endswith("`") else ""
            return fence + padding + code + padding + fence
        if tag == "table":
            return self.render_table(node)
        inner = self.children(node)
        if re.fullmatch(r"h[1-6]", tag):
            return "\n\n" + "#" * int(tag[1]) + " " + inner.strip() + "\n\n"
        if tag == "a" and node.attrs.get("href"):
            return "[" + inner.strip() + "](<" + self.url(node.attrs["href"]).replace(">", "%3E") + ">)"
        if tag == "img":
            return "![" + node.attrs.get("alt", "").replace("]", "\\]") + "](<" + self.url(node.attrs.get("src")).replace(">", "%3E") + ">)"
        if tag in {"strong", "b"}:
            return "**" + inner + "**"
        if tag in {"em", "i"}:
            return "*" + inner + "*"
        if tag == "br":
            return "\n"
        if tag == "blockquote":
            return "\n\n" + "\n".join("> " + line for line in inner.strip().splitlines()) + "\n\n"
        if tag in {"ul", "ol"}:
            items = [child for child in node.children if isinstance(child, Node) and child.tag == "li"]
            start = node.attrs.get("start", "1")
            number = int(start) if start.isdigit() else 1
            lines = []
            for offset, child in enumerate(items):
                prefix = f"{number + offset}. " if tag == "ol" else "- "
                item = self.children(child).strip()
                lines.append(prefix + item.replace("\n", "\n" + " " * len(prefix)))
            return "\n\n" + "\n".join(lines) + "\n\n"
        if tag in BLOCKS:
            return "\n\n" + inner.strip() + "\n\n"
        return inner

    def text(self):
        lines = []
        fence = None
        html_pre = 0
        blank_line = False
        for line in self.children(self.root).splitlines(keepends=True):
            opening_pre = len(re.findall(r"<pre(?:\s[^>]*)?>", line, re.I))
            closing_pre = len(re.findall(r"</pre\s*>", line, re.I))
            if html_pre or opening_pre:
                lines.append(line)
                html_pre = max(0, html_pre + opening_pre - closing_pre)
                continue
            marker = re.match(r"^(`{3,})", line)
            if fence:
                lines.append(line)
                if marker and len(marker[1]) == fence and line.strip() == marker[1]:
                    fence = None
                continue
            if marker:
                fence = len(marker[1])
            if not line.strip():
                if blank_line:
                    continue
                blank_line = True
            else:
                blank_line = False
            lines.append(line)
        return "".join(lines).strip()
