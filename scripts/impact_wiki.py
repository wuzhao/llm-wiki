#!/usr/bin/env python3
"""Report source dependencies and fingerprints without changing the wiki."""
import argparse
import json
from pathlib import Path

from wiki_links import build_target_index, resolve_standard_link
from wiki_config import SchemaError, load_schema, resolve_within, validate_structure
from wiki_metadata import body_sha256
from wiki_fragments import select_fragments
from wiki_provenance import ProvenanceGraph


def main():
    parser = argparse.ArgumentParser(description="Read-only wiki source impact analysis")
    parser.add_argument("kb_dir")
    parser.add_argument("--source", nargs="+", required=True, help="Existing raw or wiki source paths")
    parser.add_argument("--heading", action="append", help="Exact unique ATX heading to snapshot; repeat for multiple sections (one source only)")
    args = parser.parse_args()
    base = Path(args.kb_dir).resolve()
    try:
        schema = load_schema()
        missing = validate_structure(base, schema)
        if missing:
            parser.error("知识库结构不完整: " + ", ".join(missing))
        index = build_target_index(base, schema)
        graph = ProvenanceGraph(base, schema, lambda source, target: resolve_standard_link(source, target, index))
        sources = [resolve_within(base, path).relative_to(base).as_posix() for path in args.source]
        for source in sources:
            if source not in graph.documents:
                parser.error(f"来源必须是可解析的 raw 或 wiki Markdown 文件: {source}")
        if args.heading and len(sources) != 1:
            parser.error("--heading 必须且只能指定一个 --source")
        snapshots = []
        for path in sources:
            document = graph.documents[path]
            entry = {"path": path, "body_sha256": body_sha256(document["body"])}
            if args.heading:
                entry["fragments"] = select_fragments(document, args.heading)
            snapshots.append(entry)
    except (SchemaError, OSError, ValueError) as exc:
        parser.error(str(exc))
    errors = {**index["scan_errors"], **graph.errors}
    result = {"sources": snapshots,
              "affected": graph.affected(sources), "read_errors": errors}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
