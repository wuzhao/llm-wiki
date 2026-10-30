"""Read-only source graphs, dependency drift, and literal evidence candidates."""
import re
from collections import defaultdict, deque

from markdown_links import blank, escaped, mask_non_prose
from wiki_metadata import body_sha256, parse_datetime
from wiki_sources import document_content_hash, latest_sources, load_documents, source_identity


def issue(level, problem, action, line=1, body_line=False):
    return {"level": level, "problem": problem, "action": action, "line": line, "is_auto": False, "_body_line": body_line}


def claim_literals(text):
    literals = set(re.findall(r"(?<![A-Za-z0-9_])(?:\d{4}-\d{2}-\d{2}|\d+(?:\.\d+)?\s*(?:%|ms|GB|MB|TB|毫秒|秒|倍|万|亿|年|条|个)|\d+\.\d+|\d{3,})(?![A-Za-z0-9_])", text))
    literals.update(value for pair in re.findall(r'「([^「」\n]+)」|"([^"\n]+)"', text) for value in pair if value)
    return literals


class ProvenanceGraph:
    def __init__(self, kb_dir, schema, resolve, documents=None):
        self.schema, self.kb_dir = schema, kb_dir
        if documents is None:
            self.documents, self.errors = load_documents(
                kb_dir, [schema["paths"]["raw"], schema["paths"]["wiki"]],
                excluded_roots=[schema["paths"]["assets"]],
            )
        else:
            self.documents, self.errors = documents, {}
        raw_prefix = schema["paths"]["raw"] + "/"
        self.raw = {path: document for path, document in self.documents.items() if path.startswith(raw_prefix)}
        self.latest = latest_sources(self.raw, kb_dir)
        self.edges = defaultdict(set)
        self.current_edges = defaultdict(set)
        self.reverse = defaultdict(set)
        self.entries = {}
        self.walk_cache = {}
        self.drift = defaultdict(set)
        for path, document in self.documents.items():
            sources = document["metadata"].get("sources", [])
            entries = []
            for source in sources if isinstance(sources, list) else []:
                if not isinstance(source, dict) or not isinstance(source.get("resource"), str):
                    continue
                result = resolve(path, source["resource"])
                target = result.get("relative")
                entries.append((source, target, result.get("external", False)))
                if target:
                    self.edges[path].add(target)
                    if source.get("historical") is not True:
                        self.current_edges[path].add(target)
                        self.reverse[target].add(path)
            self.entries[path] = entries
        for path, entries in self.entries.items():
            owner_date = self.generated_at(path)
            for source, target, _ in entries:
                if source.get("historical") is True:
                    continue
                document = self.documents.get(target)
                if document is None:
                    continue
                expected = source.get("body_sha256")
                if expected and expected != body_sha256(document["body"]):
                    self.drift[path].add(f"{target} 的正文指纹已变化")
                current = self.latest.get(source_identity(document["metadata"], kb_dir)) if target in self.raw else None
                if current and current != target and document_content_hash(self.raw[current]) != document_content_hash(document):
                    self.drift[path].add(f"{target} 已有新版本 {current}")
                target_date = self.generated_at(target)
                if not expected and owner_date and target_date and target_date > owner_date:
                    self.drift[path].add(f"{target} 的内容更新时间晚于派生页")

    def generated_at(self, path):
        metadata = self.documents[path]["metadata"]
        generated = metadata.get("generated")
        return parse_datetime(generated.get("at")) if isinstance(generated, dict) else None

    def dependency_drift(self, path):
        reachable, queue = {path}, [path]
        while queue:
            for target in self.current_edges[queue.pop()]:
                if target not in reachable:
                    reachable.add(target)
                    queue.append(target)
        return sorted({reason for upstream in reachable for reason in self.drift[upstream]})

    def walk(self, start):
        if start in self.walk_cache:
            return self.walk_cache[start]
        seen, active, leaves = set(), set(), set()
        cycle = False
        stack = [(start, False)]
        while stack:
            path, exiting = stack.pop()
            if exiting:
                active.discard(path)
                continue
            if path in active:
                cycle = True
                continue
            if path in seen:
                continue
            seen.add(path)
            if path in self.raw:
                leaves.add(path)
                continue
            active.add(path)
            stack.append((path, True))
            stack.extend((target, False) for target in sorted(self.edges[path], reverse=True))
        self.walk_cache[start] = leaves, seen, cycle
        return self.walk_cache[start]

    def check(self, path, body, metadata):
        required_roots = tuple(self.schema["paths"][key] + "/" for key in ("summaries", "entities", "concepts", "analyses"))
        if not path.startswith(required_roots):
            return []
        issues = []
        entries = self.entries.get(path, [])
        if not metadata.get("sources"):
            issues.append(issue("🟡", "知识页缺少来源证据", "补充 sources 并将派生链追溯到 raw；不得编造来源"))
        leaves, _, cycle = self.walk(path)
        if cycle:
            issues.append(issue("🔴", "来源链存在循环引用", "核对派生关系并补充原始证据，不自动改写"))
        if entries and not leaves:
            issues.append(issue("🟡", "来源链未到达 raw 原始快照", "保留外部出处，并补充可回查的 raw 快照"))
        reasons = self.dependency_drift(path)
        if reasons:
            snapshot = path.startswith(self.schema["paths"]["analyses"] + "/")
            action = "归档快照仅标记待复核，不覆盖历史结论" if snapshot else "核对受影响结论并更新来源快照，保留历史及冲突"
            issues.append(issue("🟡", "来源依赖需要复核: " + "; ".join(reasons), action))
        by_id = {}
        for source, target, _ in entries:
            key = source.get("id")
            if isinstance(key, str) and key:
                if key in by_id:
                    issues.append(issue("🔴", f"来源 id 重复: {key}", "为逐条引用设置唯一、稳定的 sources[].id"))
                by_id[key] = target
            fingerprint = source.get("body_sha256")
            if fingerprint is not None and (not isinstance(fingerprint, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", fingerprint)):
                issues.append(issue("🟡", "来源 body_sha256 格式无效", "从影响分析输出获取来源正文指纹，不猜测指纹"))
        prose = mask_non_prose(body)
        definitions = {}
        definition_pattern = r"^ {0,3}\[\^([^\]\n]+)\]:.*$"
        for definition in re.finditer(definition_pattern, prose, re.M):
            key = definition[1]
            if key in definitions:
                line = body.count("\n", 0, definition.start()) + 1
                issues.append(issue("🔴", f"脚注定义重复: {key}", "保留唯一的脚注定义并核对引用", line, True))
            definitions[key] = definition.start()
        prose = re.sub(definition_pattern, lambda match: blank(match.group()), prose, flags=re.M)
        for paragraph in re.finditer(r"(?:[^\n]+\n?)+", prose):
            text = paragraph.group()
            reference_matches = [match for match in re.finditer(r"\[\^([^\]\n]+)\]", text) if not escaped(text, match.start())]
            references = {match[1] for match in reference_matches}
            literals = claim_literals(text)
            line = body.count("\n", 0, paragraph.start()) + 1
            unknown = references - by_id.keys()
            if unknown:
                issues.append(issue("🔴", "逐条引用没有对应来源 id: " + ", ".join(sorted(unknown)), "核对脚注与 sources[].id", line, True))
            missing_definitions = references - definitions.keys()
            if missing_definitions:
                issues.append(issue("🔴", "逐条引用缺少脚注定义: " + ", ".join(sorted(missing_definitions)), "补充 [^来源-id]: 定义并核对原文，不自动编造脚注", line, True))
            if literals and not references:
                issues.append(issue("🟡", "关键数值或引文缺少逐条来源", "为论断补充 [^来源-id]，并先核对 raw 原文", line, True))
            cursor = 0
            for attribution in re.finditer(r"(?:\[\^[^\]\n]+\][ \t]*)+", text):
                if escaped(text, attribution.start()):
                    continue
                keys = set(re.findall(r"\[\^([^\]\n]+)\]", attribution.group()))
                targets = {by_id[key] for key in keys if by_id.get(key)}
                raw_paths = {leaf for target in targets for leaf in self.walk(target)[0]}
                evidence = "\n".join(self.raw[raw]["body"] for raw in sorted(raw_paths))
                missing = sorted(value for value in claim_literals(text[cursor:attribution.start()]) if value not in evidence)
                if missing:
                    issues.append(issue("🟡", "原文未定位到数值或引文候选: " + ", ".join(missing), "人工核对语境；派生计算须列出有来源的分量，不自动更正事实", line, True))
                cursor = attribution.end()
            if references and claim_literals(text[cursor:]):
                issues.append(issue("🟡", "后续数值或引文缺少逐条来源", "为后续论断补充来源，不沿用前一论断的脚注", line, True))
        return issues

    def affected(self, sources):
        seeds = set(sources)
        identities = {source_identity(self.raw[path]["metadata"], self.kb_dir) for path in seeds if path in self.raw}
        identities.discard(None)
        seeds.update(path for path, document in self.raw.items() if source_identity(document["metadata"], self.kb_dir) in identities)
        seen = set(seeds)
        queue = deque(sorted(seeds))
        while queue:
            for parent in sorted(self.reverse[queue.popleft()]):
                if parent not in seen:
                    seen.add(parent)
                    queue.append(parent)
        return [{"path": path, "action": "review-snapshot" if path.startswith(self.schema["paths"]["analyses"] + "/") else "update-or-review"}
                for path in sorted(seen - seeds)]
