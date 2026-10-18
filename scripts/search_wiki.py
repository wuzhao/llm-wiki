#!/usr/bin/env python3
"""Read-only full-text search with explicit aliases and paginated candidates."""
import argparse
import json
import re
import sys
from pathlib import Path

from wiki_config import SchemaError, index_section_for, load_schema, validate_structure
from wiki_sources import load_documents


def search_documents(documents, terms, schema, document_type=None, tag=None, domain=None):
    expanded = set(terms)
    for document in documents.values():
        metadata = document["metadata"]
        aliases = metadata.get("aliases", [])
        names = [metadata.get("title", ""), *(aliases if isinstance(aliases, list) else [])]
        names = {name.casefold() for name in names if isinstance(name, str) and name}
        if names & set(terms):
            expanded.update(names)
    results = []
    for path, document in documents.items():
        if not index_section_for(path, schema):
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
        metadata_text = metadata_original.casefold()
        body = document["body"]
        matched_body = {term for term in expanded if term in body.casefold()}
        matched_metadata = {term for term in expanded if term in metadata_text}
        matched = matched_body | matched_metadata
        if not matched:
            continue
        lines = body.splitlines()
        line_index = next((i for i, line in enumerate(lines) if any(term in line.casefold() for term in matched_body)), None)
        snippet = lines[line_index].strip() if line_index is not None else metadata_original
        snippet_limit = schema["limits"]["max_search_snippet_chars"]
        first_match = min((snippet.casefold().find(term) for term in matched if term in snippet.casefold()), default=0)
        start = max(0, first_match - snippet_limit // 2)
        snippet = snippet[start:start + snippet_limit]
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
        terms = {term.casefold() for value in args.query for term in re.findall(r"\S+", value)}
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
