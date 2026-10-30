#!/usr/bin/env python3
"""Plan semantic reviews and resumable synthesis rounds without writing files."""
import argparse
import json
import re
from pathlib import Path

from markdown_links import mask_non_prose
from wiki_config import SchemaError, load_schema, validate_structure
from wiki_links import build_target_index, resolve_standard_link
from wiki_metadata import body_sha256
from wiki_provenance import ProvenanceGraph
from wiki_sources import document_content_hash, source_identity


CHECKPOINT_PREFIX = "<!-- llm-wiki:synthesis-checkpoint "
HASH_RE = re.compile(r"[a-f0-9]{64}")


def is_hash(value):
    return isinstance(value, str) and HASH_RE.fullmatch(value) is not None


def review_fingerprint(document):
    """Ignore review bookkeeping; include prose and the evidence it attributes."""
    metadata = document["metadata"]
    content = {key: metadata.get(key) for key in ("title", "aliases", "sources")}
    content["body"] = document["body"]
    return body_sha256(json.dumps(content, ensure_ascii=False, sort_keys=True, default=str))


def validate_synthesis(metadata):
    """Validate optional summary state without judging semantic decisions."""
    if "synthesis" not in metadata:
        return []
    state = metadata["synthesis"]
    if not isinstance(state, dict):
        return ["synthesis 必须是对象"]
    errors = []
    if not is_hash(state.get("reviewed_sha256")):
        errors.append("synthesis.reviewed_sha256 必须是工具返回的 SHA256")
    if "reviewed_in" in state and not is_hash(state["reviewed_in"]):
        errors.append("synthesis.reviewed_in 必须是工具返回的回扫标识")
    deferred = state.get("deferred")
    if not isinstance(deferred, list):
        return errors + ["synthesis.deferred 必须是数组，无候选时使用空数组"]
    seen = set()
    for position, candidate in enumerate(deferred):
        label = f"synthesis.deferred[{position}]"
        if not isinstance(candidate, dict):
            errors.append(f"{label} 必须是对象")
            continue
        for key in ("name", "reason", "next_when"):
            if not isinstance(candidate.get(key), str) or not candidate[key].strip():
                errors.append(f"{label}.{key} 必须是非空字符串")
        if candidate.get("type") not in ("entity", "concept"):
            errors.append(f"{label}.type 必须是 entity 或 concept")
        aliases = candidate.get("aliases", [])
        if not isinstance(aliases, list) or any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
            errors.append(f"{label}.aliases 必须是非空字符串数组")
        if isinstance(candidate.get("name"), str) and isinstance(candidate.get("type"), str):
            key = candidate["type"], candidate["name"].strip().casefold()
            if key in seen:
                errors.append(f"{label} 与同一摘要中的候选重复")
            seen.add(key)
    return errors


def read_checkpoint(documents, logs_prefix):
    """Replay v2 deltas while accepting existing v1 full snapshots unchanged."""
    checkpoint, errors = None, {}
    seen = set()
    for path, document in sorted(documents.items()):
        if not path.startswith(logs_prefix):
            continue
        body = document["body"]
        # Expose just checkpoint comments to the prose masker, so examples in
        # fenced/indented code remain masked and cannot become live state.
        exposed = body.replace(CHECKPOINT_PREFIX, "NOTE" + CHECKPOINT_PREFIX[4:])
        exposed = mask_non_prose(exposed)
        for match in re.finditer(r"^<!-- llm-wiki:synthesis-checkpoint (.*?) -->[ \t]*$", body, re.M):
            if not exposed[match.start():match.end()].strip():
                continue
            try:
                value = json.loads(match[1])
                if (not isinstance(value, dict) or not isinstance(value.get("version"), int) or value.get("version") not in (1, 2)
                        or isinstance(value.get("version"), bool)
                        or not is_hash(value.get("review_id"))):
                    raise ValueError("检查点需要有效的 version 和 review_id")
                key = "fingerprints" if value["version"] == 1 else "added_fingerprints"
                if not isinstance(value.get(key), list) or not all(is_hash(item) for item in value[key]):
                    raise ValueError(f"检查点需要 {key} 指纹数组")
                if value["version"] == 1:
                    seen = set(value[key])
                else:
                    previous = checkpoint["review_id"] if checkpoint else None
                    if "previous" not in value or value["previous"] != previous:
                        raise ValueError("增量检查点 previous 与已完成轮次不一致")
                    # A malformed record cannot silently disappear in a delta.
                    if errors and checkpoint is not None:
                        raise ValueError("先修复检查点链缺口，或追加完整 v1 恢复快照")
                    seen.update(value[key])
                checkpoint = {"review_id": value["review_id"]}
                errors.clear()
            except (ValueError, TypeError) as exc:
                errors[path] = f"提炼回扫检查点无效: {exc}"
    if checkpoint is not None:
        checkpoint["fingerprints"] = sorted(seen)
    return checkpoint, errors


def build_plan(kb_dir, schema, force=False, details=False):
    index = build_target_index(kb_dir, schema)
    graph = ProvenanceGraph(kb_dir, schema, lambda owner, target: resolve_standard_link(owner, target, index))
    errors = {**index["scan_errors"], **graph.errors}
    checkpoint, checkpoint_errors = read_checkpoint(graph.documents, schema["paths"]["logs"] + "/")
    errors.update(checkpoint_errors)
    summaries = {path: document for path, document in graph.documents.items()
                 if path.startswith(schema["paths"]["summaries"] + "/")}
    compiled_raw = set()
    untraced = []
    for path in summaries:
        leaves, _, cycle = graph.walk(path)
        compiled_raw.update(leaves)
        if not leaves or cycle:
            untraced.append(path)
    identities = {source_identity(graph.raw[path]["metadata"], kb_dir) for path in compiled_raw}
    identities.discard(None)
    # Summaries commonly replace a citation with its latest version. Include the
    # captured history of those sources so consecutive revisions still accrue.
    raw_hashes = {path: document_content_hash(document) for path, document in graph.raw.items()}
    evidence = {raw_hashes[path] for path, document in graph.raw.items()
                if path in compiled_raw or source_identity(document["metadata"], kb_dir) in identities}
    # Keep earlier fingerprints even when a summary now cites only a new version.
    # Retries, retransmissions and returns to previously seen prose add no quota.
    seen = set(checkpoint["fingerprints"]) if checkpoint else set()
    inventory = seen | evidence
    new_hashes = evidence - seen
    new_count = len(new_hashes)
    interval = schema["limits"]["synthesis_review_interval"]
    due = bool(summaries) and (force or checkpoint is None or new_count >= interval)
    reason = "bootstrap" if due and checkpoint is None else "requested" if due and force else "interval" if due else "local"
    round_basis = {"previous": checkpoint["review_id"] if checkpoint else None,
                   "fingerprints": sorted(inventory), "mode": reason}
    review_id = body_sha256(json.dumps(round_basis, sort_keys=True))
    new_evidence = ("\n".join(document["body"] for path, document in graph.raw.items()
                              if raw_hashes[path] in new_hashes).casefold()
                    if reason in ("interval", "local") else "")
    unreviewed, remaining, deferred = [], [], []
    fingerprints = {}
    reasons_by_path = {}
    for path, document in sorted(summaries.items()):
        fingerprints[path] = review_fingerprint(document)
        state_errors = validate_synthesis(document["metadata"])
        if state_errors:
            errors[path] = "; ".join(state_errors)
        state = document["metadata"].get("synthesis", {})
        state = state if isinstance(state, dict) else {}
        current = state.get("reviewed_sha256") == fingerprints[path] and not state_errors
        if not current:
            unreviewed.append(path)
        reasons = []
        if not current:
            reasons.append("changed-or-unreviewed")
        if reason in ("bootstrap", "requested"):
            reasons.append("full-review")
        if graph.dependency_drift(path):
            reasons.append("dependency-drift")
        for candidate in state.get("deferred", []) if isinstance(state.get("deferred"), list) else []:
            if isinstance(candidate, dict):
                deferred.append({**candidate, "summary": path})
                aliases = candidate.get("aliases", [])
                names = [candidate.get("name"), *(aliases if isinstance(aliases, list) else [])]
                if any(isinstance(name, str) and name.strip() and name.casefold() in new_evidence for name in names):
                    reasons.append("deferred-evidence-match")
        if reasons and (not current or state.get("reviewed_in") != review_id):
            remaining.append(path)
            reasons_by_path[path] = sorted(set(reasons))
    pending = remaining
    batch = pending[:schema["limits"]["max_query_read_pages"]]
    review_scope = "full" if reason in ("bootstrap", "requested") else "incremental"
    reviewed_count = sum(document["metadata"].get("synthesis", {}).get("reviewed_in") == review_id
                         for document in summaries.values() if isinstance(document["metadata"].get("synthesis"), dict))
    record = None
    if due and not remaining and not errors and not untraced:
        value = json.dumps({"version": 2, "review_id": review_id,
                            "previous": checkpoint["review_id"] if checkpoint else None,
                            "scope": review_scope, "reviewed_count": reviewed_count,
                            "added_fingerprints": sorted(new_hashes)}, separators=(",", ":"))
        record = f"{CHECKPOINT_PREFIX}{value} -->"
    return {
        "due": due,
        "reason": reason,
        "scope": review_scope,
        "reviewed_count": reviewed_count,
        "new_source_contents": new_count,
        "review_interval": interval,
        "review_id": review_id,
        "unreviewed_count": len(unreviewed),
        "unreviewed": unreviewed if details else [path for path in batch if path in unreviewed],
        "remaining": len(pending),
        "batch": [{"path": path, "reviewed_sha256": fingerprints[path], "reasons": reasons_by_path[path]} for path in batch],
        "fingerprints": fingerprints if details else {path: fingerprints[path] for path in batch},
        "deferred_count": len(deferred),
        "deferred": deferred if details else [candidate for candidate in deferred if candidate["summary"] in batch],
        "untraced_summaries": untraced,
        "checkpoint_record": record,
        "read_errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="Read-only synthesis review plan and checkpoint proposal")
    parser.add_argument("kb_dir")
    parser.add_argument("--force", action="store_true", help="Review all summaries on an explicit synthesis request")
    parser.add_argument("--details", action="store_true", help="Include the full fingerprint and deferred-candidate inventories")
    args = parser.parse_args()
    try:
        schema = load_schema()
        base = Path(args.kb_dir).resolve()
        missing = validate_structure(base, schema)
        if missing:
            parser.error("知识库结构不完整: " + ", ".join(missing))
        result = build_plan(base, schema, force=args.force, details=args.details)
    except (SchemaError, OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if result["read_errors"] or result["untraced_summaries"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
