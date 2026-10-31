"""Read-only source graphs, dependency drift, and literal evidence candidates."""
import re
from collections import defaultdict, deque

from markdown_links import blank, escaped, mask_link_metadata, mask_non_prose
from wiki_metadata import body_sha256, parse_datetime
from wiki_evidence import EvidenceDocument, EvidenceIndex, claim_literals, claim_text, missing_literals, quoted_literals
from wiki_sources import document_content_hash, latest_sources, load_documents, source_identity


def issue(level, problem, action, line=1, body_line=False, **details):
    return {"level": level, "problem": problem, "action": action, "line": line, "is_auto": False, "_body_line": body_line, **details}


NAVIGATION_LABELS = {"来源", "参考资料", "相关页面", "关联阅读", "相关阅读", "关联知识", "相关知识", "相关概念", "相关导航", "子主题导航"}
PROCESSED_CLAIM = re.compile(
    r"校准|校正|更正|修正|派生值|(?:自行|本页|本摘要|编者)(?:计算|估算|推算|推导)"
    r"|(?:计算|估算|推算|推导)(?:得到|得出|结果)|[=＝]")


def requires_inline_citation(text):
    """Explicit quotes and processing markers cannot inherit page-level attribution."""
    return bool(quoted_literals(claim_text(text)) or PROCESSED_CLAIM.search(text))


def mask_claim_markup(text):
    navigation, offset, navigation_level = set(), 0, None
    for line in text.splitlines(keepends=True):
        heading = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", line.rstrip("\n"))
        if heading:
            if navigation_level is not None and len(heading[1]) <= navigation_level:
                navigation_level = None
            if heading[2] in NAVIGATION_LABELS:
                navigation_level = len(heading[1])
        prefix = re.match(r"^\s*(?:[-*+]\s+)?([^：:\n]+)[：:]", line)
        if navigation_level is not None or (prefix and prefix[1] in NAVIGATION_LABELS):
            navigation.add(offset)
        offset += len(line)
    return mask_link_metadata(text, lambda at: text.rfind("\n", 0, at) + 1 in navigation)


def claim_blocks(prose):
    """Only an explicit caption grants scope to the immediately following table."""
    lines = prose.splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    tables = {}
    for index, line in enumerate(lines):
        caption = re.fullmatch(r"[ \t]*本表(?:数据)?来源：[ \t]*((?:\[\^[^\]\n]+\][ \t]*)+)[ \t]*\n?", line)
        if not caption:
            continue
        start = index + 1
        if start < len(lines) and not lines[start].strip():
            start += 1
        if start + 1 >= len(lines) or not lines[start].lstrip().startswith("|"):
            continue
        if not re.fullmatch(r"[ \t]*\|(?:[ \t]*:?-{3,}:?[ \t]*\|)+[ \t]*\n?", lines[start + 1]):
            continue
        end = start + 2
        while end < len(lines) and lines[end].lstrip().startswith("|"):
            end += 1
        tables[start] = (end, caption[1].strip())
    cursor = 0
    for start, (end, references) in tables.items():
        for paragraph in re.finditer(r"(?:[^\n]+\n?)+", prose[cursor:offsets[start]]):
            yield cursor + paragraph.start(), paragraph.group()
        for row in range(start, end):
            if row == start + 1:
                continue
            text = lines[row].rstrip("\n")
            if not any(not escaped(text, match.start()) for match in re.finditer(r"\[\^[^\]\n]+\]", text)):
                text += references
            yield offsets[row], text
        cursor = offsets[end] if end < len(lines) else len(prose)
    for paragraph in re.finditer(r"(?:[^\n]+\n?)+", prose[cursor:]):
        yield cursor + paragraph.start(), paragraph.group()


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
        self.evidence_documents = {}
        self.evidence_indexes = {}
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

    def evidence_index(self, raw_paths):
        key = tuple(sorted(raw_paths))
        if key not in self.evidence_indexes:
            for path in key:
                if path not in self.evidence_documents:
                    document = self.raw[path]
                    self.evidence_documents[path] = EvidenceDocument(path, document["body"], document.get("body_start_line", 1))
            self.evidence_indexes[key] = EvidenceIndex(self.evidence_documents[path] for path in key)
        return self.evidence_indexes[key]

    def single_raw_summary(self, path, metadata):
        # One reachable leaf does not imply direct transcription: an intermediary
        # can aggregate or process it, and an unresolved second source can be lost.
        sources = metadata.get("sources")
        entries = self.entries.get(path, [])
        if (path.startswith(self.schema["paths"]["summaries"] + "/")
                and isinstance(sources, list) and len(sources) == len(entries) == 1):
            _, target, external = entries[0]
            if not external and target in self.raw:
                return target
        return None

    def evidence_issues(self, path, text, raw_paths, body_start):
        details = self.evidence_index(raw_paths).diagnose(text) if raw_paths else []
        if not details:
            return []
        body = self.documents[path]["body"]
        for detail in details:
            detail["line"] = (body.count("\n", 0, body_start + detail["start"])
                              + self.documents[path].get("body_start_line", 1))
        line = body.count("\n", 0, body_start + min(detail["start"] for detail in details)) + 1
        level = "🟡" if any(detail["level"] == "🟡" for detail in details) else "🔵"
        label = "数值表达建议: " if level == "🔵" else "数值或引文证据待复核: "
        return [issue(level, label + ", ".join(detail["claim"] for detail in details),
                      "候选仅供回查，须核对指标、时间与归因；不自动更正事实", line, True,
                      category="evidence", details=details, sources=sorted(raw_paths))]

    def check(self, path, body, metadata):
        required_roots = tuple(self.schema["paths"][key] + "/" for key in ("summaries", "entities", "concepts", "analyses", "hubs"))
        if not path.startswith(required_roots):
            return []
        prose = mask_claim_markup(mask_non_prose(body))
        if (path.startswith(self.schema["paths"]["hubs"] + "/")
                and not metadata.get("sources") and not claim_literals(prose)
                and not re.search(r"\[\^[^\]\n]+\]", prose)):
            return []
        issues = []
        entries = self.entries.get(path, [])
        page_raw = self.single_raw_summary(path, metadata)
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
        definitions = {}
        definition_pattern = r"^ {0,3}\[\^([^\]\n]+)\]:.*$"
        for definition in re.finditer(definition_pattern, prose, re.M):
            key = definition[1]
            if key in definitions:
                line = body.count("\n", 0, definition.start()) + 1
                issues.append(issue("🔴", f"脚注定义重复: {key}", "保留唯一的脚注定义并核对引用", line, True, category="citation"))
            definitions[key] = definition.start()
        prose = re.sub(definition_pattern, lambda match: blank(match.group()), prose, flags=re.M)
        for block_start, text in claim_blocks(prose):
            reference_matches = [match for match in re.finditer(r"\[\^([^\]\n]+)\]", text) if not escaped(text, match.start())]
            references = {match[1] for match in reference_matches}
            literals = claim_literals(text)
            line = body.count("\n", 0, block_start) + 1
            unknown = references - by_id.keys()
            if unknown:
                issues.append(issue("🔴", "逐条引用没有对应来源 id: " + ", ".join(sorted(unknown)), "核对脚注与 sources[].id", line, True, category="citation"))
            missing_definitions = references - definitions.keys()
            if missing_definitions:
                issues.append(issue("🔴", "逐条引用缺少脚注定义: " + ", ".join(sorted(missing_definitions)), "补充 [^来源-id]: 定义并核对原文，不自动编造脚注", line, True, category="citation"))
            if literals and not references and (not page_raw or requires_inline_citation(text)):
                issues.append(issue("🟡", "关键数值或引文缺少逐条来源", "此项仅表示引用不完整，尚未核对证据；核对 raw 后补充 [^来源-id]", line, True, category="citation"))
            cursor = 0
            for attribution in re.finditer(r"(?:\[\^[^\]\n]+\][ \t]*)+", text):
                if escaped(text, attribution.start()):
                    continue
                keys = set(re.findall(r"\[\^([^\]\n]+)\]", attribution.group()))
                targets = {by_id[key] for key in keys if by_id.get(key)}
                raw_paths = {leaf for target in targets for leaf in self.walk(target)[0]}
                segment = text[cursor:attribution.start()]
                # Broken source chains are unavailable evidence, not absent facts.
                if not raw_paths and keys <= by_id.keys() and claim_literals(segment):
                    issues.append(issue("🟡", "该条引用无法回查 raw 证据", "补全该条引用的来源链；其他论断的可用来源不能代替它", line, True, category="evidence"))
                issues += self.evidence_issues(path, segment, raw_paths, block_start + cursor)
                cursor = attribution.end()
            remainder = text[cursor:]
            if (references and claim_literals(remainder)
                    and (not page_raw or requires_inline_citation(remainder))):
                issues.append(issue("🟡", "后续数值或引文缺少逐条来源", "此项尚未核对证据；为后续论断补充来源，不沿用前一论断的脚注", line, True, category="citation"))
            if page_raw:
                # The exemption only changes citation completeness. Uncited
                # summary claims still undergo literal lookup in their sole raw.
                issues += self.evidence_issues(path, remainder, {page_raw}, block_start + cursor)
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
