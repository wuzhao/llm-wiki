#!/usr/bin/env python3
"""Read-only full-text search with explicit aliases and paginated candidates."""
import argparse
import json
import re
import sys
from pathlib import Path

from markdown_links import code_comment_spans
from wiki_config import SchemaError, is_knowledge_page, load_schema, validate_structure
from wiki_provenance import prose_blocks
from wiki_sources import load_documents


def normalize_term(value):
    return ' '.join(value.split()).casefold()


def first_term_span(text, terms):
    """Locate normalized whitespace/case matches while preserving source offsets."""
    folded = text.casefold()
    matches = [match for term in terms
               if (match := re.search(r'\s+'.join(re.escape(word) for word in term.split()), folded))]
    if not matches:
        return None
    match = min(matches, key=lambda value: (value.start(), -value.end()))
    if len(text) == len(folded):
        return match.span()
    # Case folding may expand a character (for example ß to ss).
    offset = start = 0
    for index, char in enumerate(text):
        end = offset + len(char.casefold())
        if offset <= match.start() < end:
            start = index
        if end >= match.end():
            return start, index + 1
        offset = end


def searchable_blocks(body):
    start = 0
    for left, right, kind in code_comment_spans(body):
        if kind == "code":
            continue
        yield from prose_blocks(body[start:left], start)
        if kind == "fence":
            yield left, body[left:right]
        start = right
    yield from prose_blocks(body[start:], start)


def match_snippet(text, span, limit):
    start, end = span
    left = text.rfind("\n", 0, start) + 1
    right = text.find("\n", end)
    prefix = " ".join(text[left:start].split())
    if prefix and text[start - 1].isspace():
        prefix += " "
    matched = " ".join(text[start:end].split())
    line = " ".join(text[left:right if right >= 0 else len(text)].split())
    # Centre on the original hit; keep the whole phrase when it fits.
    offset = max(0, len(prefix) - max(0, limit - len(matched)) // 2)
    return line[offset:offset + limit].rstrip()


def search_documents(documents, terms, schema, document_type=None, tag=None, domain=None):
    terms = {normalize_term(term) for term in terms if normalize_term(term)}
    expanded = set(terms)
    for document in documents.values():
        metadata = document["metadata"]
        aliases = metadata.get("aliases", [])
        names = [metadata.get("title", ""), *(aliases if isinstance(aliases, list) else [])]
        names = {normalize_term(name) for name in names if isinstance(name, str) and normalize_term(name)}
        if names & set(terms):
            expanded.update(names)
    results = []
    for path, document in documents.items():
        if not is_knowledge_page(path, schema):
            continue
        metadata = document["metadata"]
        if document_type and metadata.get("type") != document_type:
            continue
        if tag and (not isinstance(metadata.get("tags"), list) or tag not in metadata["tags"]):
            continue
        if domain and metadata.get("domain") != domain:
            continue
        title = metadata.get("title") or Path(path).stem
        metadata_original = json.dumps(metadata, ensure_ascii=False, default=str)
        metadata_text = normalize_term(metadata_original)
        body = document["body"]
        matched_body = set()
        line_index = None
        snippet_limit = schema["limits"]["max_search_snippet_chars"]
        for offset, block in searchable_blocks(body):
            normalized = normalize_term(block)
            found = {term for term in expanded if term in normalized}
            if found and line_index is None:
                span = first_term_span(block, found)
                line_index = body.count("\n", 0, offset + span[0])
                snippet = match_snippet(block, span, snippet_limit)
            matched_body.update(found)
        matched_metadata = {term for term in expanded if term in metadata_text}
        matched = matched_body | matched_metadata
        if not matched:
            continue
        if line_index is None:
            snippet = match_snippet(metadata_original, first_term_span(metadata_original, matched_metadata), snippet_limit)
        results.append({"path": path, "title": title, "type": metadata.get("type"), "status": metadata.get("status", "stable"),
                        "matched_terms": sorted(matched), "match_kind": [kind for kind, matches in (("metadata", matched_metadata), ("body", matched_body)) if matches],
                        "line": document.get("body_start_line", 1) + line_index if line_index is not None else 1,
                        "snippet": snippet})
    results.sort(key=lambda item: (-len(set(item["matched_terms"]) & set(terms)), -len(item["matched_terms"]), item["path"]))
    return results, expanded


class SearchSession:
    """Keep one query's candidates in memory; refresh explicitly after edits."""
    def __init__(self, base, schema, terms, document_type=None, tag=None, domain=None):
        self.base, self.schema, self.terms = base, schema, terms
        self.filters = document_type, tag, domain
        self.refresh()

    def refresh(self):
        documents, self.errors = load_documents(self.base, [self.schema["paths"]["wiki"]])
        self.results, self.expanded = search_documents(documents, self.terms, self.schema, *self.filters)

    def page(self, offset, limit):
        if (not isinstance(offset, int) or isinstance(offset, bool) or offset < 0
                or not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0):
            raise ValueError("offset 必须为非负整数，limit 必须为正整数")
        next_offset = offset + limit if offset + limit < len(self.results) else None
        return {"query_terms": sorted(self.terms), "expanded_terms": sorted(self.expanded), "total": len(self.results),
                "offset": offset, "next_offset": next_offset,
                "results": self.results[offset:offset + limit], "read_errors": self.errors}


def main():
    parser = argparse.ArgumentParser(description="Search wiki text and aliases without writing files")
    parser.add_argument("kb_dir")
    parser.add_argument("query", nargs="+")
    parser.add_argument("--type", dest="document_type")
    parser.add_argument("--tag")
    parser.add_argument("--domain")
    parser.add_argument("--limit", type=int, help="Candidate batch size; defaults to schema query budget")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--interactive", action="store_true", help="Reuse candidates; read JSON offset/limit/refresh requests from stdin")
    args = parser.parse_args()
    try:
        schema = load_schema()
        base = Path(args.kb_dir).resolve()
        missing = validate_structure(base, schema)
        if missing:
            parser.error("知识库结构不完整: " + ", ".join(missing))
        limit = args.limit if args.limit is not None else schema["limits"]["max_query_read_pages"]
        if limit <= 0 or args.offset < 0:
            parser.error("--limit 必须为正整数，--offset 不得为负数")
        terms = {normalize_term(value) for value in args.query if normalize_term(value)}
        if not terms:
            parser.error("查询词不能为空")
        session = SearchSession(base, schema, terms, args.document_type, args.tag, args.domain)
    except (SchemaError, OSError, ValueError) as exc:
        parser.error(str(exc))
    def emit(payload):
        print(json.dumps(payload, ensure_ascii=False, indent=None if args.interactive else 2), flush=True)

    emit(session.page(args.offset, limit))
    if args.interactive:
        for line in sys.stdin:
            try:
                request = json.loads(line)
                if not isinstance(request, dict) or set(request) - {"offset", "limit", "refresh"}:
                    raise ValueError("请求仅支持 offset、limit 和 refresh")
                if "refresh" in request and not isinstance(request["refresh"], bool):
                    raise ValueError("refresh 必须为布尔值")
                offset, batch_limit = request.get("offset", 0), request.get("limit", limit)
                session.page(offset, batch_limit)  # Validate before any refresh.
                if request.get("refresh"):
                    session.refresh()
                emit(session.page(offset, batch_limit))
            except (ValueError, OSError, SchemaError) as exc:
                emit({"error": str(exc)})
    return 1 if session.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
