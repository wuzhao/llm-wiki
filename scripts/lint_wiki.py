#!/usr/bin/env python3
import argparse
import datetime
import fcntl
import hashlib
import os
import re
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        f"缺少 PyYAML；使用当前解释器 {sys.executable} 安装依赖文件 "
        f"{Path(__file__).resolve().parents[1] / 'requirements.txt'} 中的依赖。"
    ) from exc

from wiki_config import (
    SchemaError,
    TemplateError,
    index_section_for,
    infer_document_type,
    is_asset_path,
    load_markdown_template,
    load_schema,
    resolve_within,
    validate_structure,
)
from wiki_io import atomic_write_text, checked_destination
from markdown_links import mask_non_prose, standard_link_occurrences, standard_link_spans, wikilink_spans, unescape_target
from wiki_links import build_target_index, is_allowed_target, resolve_standard_link, resolve_wikilink
from wiki_metadata import body_sha256, parse_datetime, split_frontmatter
from wiki_sources import latest_sources, load_documents, source_identity, walk_visible_files
from wiki_provenance import ProvenanceGraph


def make_issue(level, problem, action="", line=None, is_auto=False):
    return {
        "level": level,
        "line": line,
        "problem": problem,
        "action": action,
        "is_auto": is_auto,
    }


def yaml_scalar(value):
    dumped = yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=True,
        sort_keys=False,
    ).strip()
    if dumped.endswith("\n..."):
        dumped = dumped[:-4]
    return dumped


def set_frontmatter_value(frontmatter, key, value):
    replacement = f"{key}: {yaml_scalar(value)}"
    node = yaml.compose(frontmatter)
    if isinstance(node, yaml.MappingNode):
        for key_node, value_node in node.value:
            if key_node.value == key:
                start, end = key_node.start_mark.index, value_node.end_mark.index
                suffix = "\n" if frontmatter[start:end].endswith("\n") else ""
                return frontmatter[:start] + replacement + suffix + frontmatter[end:]
    if frontmatter and not frontmatter.endswith("\n"):
        frontmatter += "\n"
    return frontmatter + replacement


def replace_frontmatter_scalar(frontmatter, key, value):
    return set_frontmatter_value(frontmatter, key, value)


def h1_title(body, filepath):
    match = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return Path(filepath).stem


def check_and_fix_frontmatter(filepath, content, kb_dir, schema, apply_fixes=False):
    relative_path = Path(filepath).resolve().relative_to(Path(kb_dir).resolve()).as_posix()
    frontmatter, metadata, body, error = split_frontmatter(content)
    issues = []

    if relative_path == schema["paths"]["index"]:
        if error:
            issues.append(make_issue("🔴", error, "按 index 模板补充 okf_version", line=1))
            return content, issues, metadata, body
        expected_version = schema["okf_version"]
        if metadata.get("okf_version") != expected_version:
            frontmatter = replace_frontmatter_scalar(frontmatter, "okf_version", expected_version)
            metadata["okf_version"] = expected_version
            issues.append(make_issue(
                "🔴",
                f"index 的 okf_version 不是 {expected_version}",
                f"补全 okf_version 为 {expected_version}",
                line=1,
                is_auto=True,
            ))
            if apply_fixes:
                content = f"---\n{frontmatter.rstrip()}\n---\n{body}"
        extra_keys = sorted(set(metadata) - {"okf_version"})
        if extra_keys:
            issues.append(make_issue(
                "🔵",
                f"OKF {expected_version} index frontmatter 含非保留字段: {', '.join(extra_keys)}",
                "仅保留 okf_version，字段迁移需人工确认",
                line=1,
            ))
        return content, issues, metadata, body

    if error and error != "缺少 YAML frontmatter":
        issues.append(make_issue("🔴", error, "请先人工修复 YAML", line=1))
        return content, issues, metadata, body

    inferred_type = infer_document_type(relative_path, schema)
    if error and not frontmatter:
        if not inferred_type:
            issues.append(make_issue("🔴", error, "无法从目录推断 type，请人工补充", line=1))
            return content, issues, metadata, body
        metadata = {
            "type": inferred_type,
            "title": h1_title(body, filepath),
        }
        frontmatter = yaml.safe_dump(
            metadata,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        ).rstrip()
        if apply_fixes:
            content = f"---\n{frontmatter}\n---\n{body}"
        issues.extend([
            make_issue("🔴", "Frontmatter 缺少 type", f"补全 type 为 {inferred_type}", line=1, is_auto=True),
            make_issue("🔵", "Frontmatter 缺少 title", f"补全 title 为 {metadata['title']}", line=1, is_auto=True),
        ])
    else:
        changed = False
        current_type = metadata.get("type")
        if not isinstance(current_type, str) or not current_type.strip():
            if inferred_type:
                frontmatter = set_frontmatter_value(frontmatter, "type", inferred_type)
                metadata["type"] = inferred_type
                changed = True
                issues.append(make_issue("🔴", "Frontmatter 缺少非空 type", f"补全 type 为 {inferred_type}", line=1, is_auto=True))
            else:
                issues.append(make_issue("🔴", "Frontmatter 缺少非空 type", "无法从目录推断，请人工补充", line=1))
        elif inferred_type and current_type != inferred_type:
            issues.append(make_issue(
                "🔴",
                f"Frontmatter type 与路径不一致: {current_type}",
                f"按 schema 应为 {inferred_type}，请确认页面职责后人工修正",
                line=1,
            ))

        if not isinstance(metadata.get("title"), str) or not metadata.get("title", "").strip():
            title = h1_title(body, filepath)
            frontmatter = set_frontmatter_value(frontmatter, "title", title)
            metadata["title"] = title
            changed = True
            issues.append(make_issue("🔵", "Frontmatter 缺少 title", f"补全 title 为 {title}", line=1, is_auto=True))

        if changed and apply_fixes:
            content = f"---\n{frontmatter.rstrip()}\n---\n{body}"

    is_raw = relative_path.startswith(f"{schema['paths']['raw']}/")
    is_log = relative_path.startswith(f"{schema['paths']['logs']}/")
    if not is_raw and not is_log:
        if not metadata.get("description"):
            issues.append(make_issue("🔵", "Frontmatter 缺少推荐字段 description", "建议补充单句摘要", line=1))
        if "tags" not in metadata:
            issues.append(make_issue("🔵", "Frontmatter 缺少推荐字段 tags", "建议补充字符串数组", line=1))
        elif not isinstance(metadata.get("tags"), list):
            issues.append(make_issue("🔵", "Frontmatter 的 tags 不是数组", "改为 YAML 字符串数组", line=1))

    return content, issues, metadata, body


def file_sha256(filepath):
    digest = hashlib.sha256()
    with open(filepath, "rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_source_file_integrity(relative_path, metadata, kb_dir, schema, latest=None):
    raw_prefix = f"{schema['paths']['raw']}/"
    if not relative_path.startswith(raw_prefix):
        return []
    if latest is not None:
        current = latest.get(source_identity(metadata, kb_dir))
        if current and current != relative_path:
            return []
    source_path = metadata.get("source_file_path")
    expected_sha256 = metadata.get("source_file_sha256")
    if not source_path:
        return []

    if not isinstance(source_path, str):
        return [make_issue("🔴", "source_file_path 必须是字符串", "修正 frontmatter", line=1)]
    source_path = Path(source_path)
    if not source_path.is_absolute():
        source_path = Path(kb_dir) / source_path
    if not source_path.exists():
        return [make_issue("🔴", f"原始文件不可访问: {source_path}", "需重新投喂该文件")]
    if not expected_sha256:
        return []
    try:
        current_sha256 = file_sha256(source_path)
    except OSError as exc:
        return [make_issue("🟡", f"原始文件无法读取: {source_path}", f"需重新投喂该文件（{exc}）")]
    if current_sha256 != expected_sha256:
        return [make_issue("🟡", f"与当前原始文件不一致: {source_path}", "需重新投喂该文件")]
    return []


def check_raw_snapshot(relative_path, metadata, body, kb_dir, schema):
    if not relative_path.startswith(schema["paths"]["raw"] + "/"):
        return []
    issues = []
    if metadata.get("body_sha256") and metadata["body_sha256"] != body_sha256(body):
        issues.append(make_issue("🔴", "raw 正文与保存时的指纹不一致", "核对历史或原始快照，不自动重写正文或更新指纹", line=1))
    snapshot = metadata.get("source_snapshot")
    if snapshot:
        try:
            if not isinstance(snapshot, str):
                raise SchemaError("快照路径必须是字符串")
            path = resolve_within(kb_dir, snapshot)
            assets = resolve_within(kb_dir, schema["paths"]["assets"])
            if not path.is_relative_to(assets) or not path.is_file():
                raise SchemaError("快照不在 assets 内或文件不存在")
            expected = metadata.get("source_snapshot_sha256")
            if expected and file_sha256(path) != expected:
                issues.append(make_issue("🔴", "原始响应快照指纹不一致", "核对保存的原始响应，不自动覆盖", line=1))
        except (OSError, ValueError, SchemaError) as exc:
            issues.append(make_issue("🔴", f"原始响应快照不可用: {exc}", "恢复原始快照或重新摄入新版本", line=1))
    return issues


def heading_keys(filepath, content=None):
    if not filepath or Path(filepath).suffix.casefold() != ".md":
        return set(), set()
    if content is None:
        try:
            content = Path(filepath).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return set(), set()
    exact = set()
    slugs = set()
    content = mask_non_prose(content)
    counts = defaultdict(int)
    for match in re.finditer(r"^#{1,6}\s+(.+?)(?:\s+#+)?$", content, re.MULTILINE):
        heading = match.group(1).strip()
        exact.add(heading.casefold())
        slug = re.sub(r"[^\w\-\u4e00-\u9fff ]", "", heading.casefold())
        slug = re.sub(r"[\s\-]+", "-", slug).strip("-")
        count = counts[slug]
        counts[slug] += 1
        slugs.add(f"{slug}-{count}" if count else slug)
    blocks = set(re.findall(r"\^([A-Za-z0-9_-]+)\s*$", content, re.MULTILINE))
    return exact | blocks, slugs


def fragment_exists(relative_target, fragment, target_index):
    if not fragment:
        return True
    filepath = target_index["by_relative"].get(relative_target)
    if not filepath:
        return False
    cache = target_index["heading_cache"]
    if relative_target not in cache:
        content = target_index.get("content_cache", {}).get(relative_target)
        cache[relative_target] = heading_keys(filepath, content)
    exact, slugs = cache[relative_target]
    normalized = fragment.lstrip("^").casefold()
    return normalized in exact or normalized in slugs


def mask_code(content):
    return mask_non_prose(content)


def line_number(content, offset):
    return content.count("\n", 0, offset) + 1


def format_wikilink_target(source_relative, target_relative, original_target, schema):
    wiki_prefix = f"{schema['paths']['wiki']}/"
    if source_relative.startswith(wiki_prefix) and target_relative.startswith(wiki_prefix):
        result = target_relative[len(wiki_prefix):]
    else:
        result = target_relative
    original_base, separator, fragment = original_target.partition("#")
    if not Path(original_base).suffix and result.endswith(".md"):
        result = result[:-3]
    if separator:
        result += f"#{fragment}"
    return result


def format_standard_target(source_relative, target_relative, fragment):
    source_parent = Path(source_relative).parent
    relative = os.path.relpath(target_relative, source_parent.as_posix() or ".").replace("\\", "/")
    encoded = urllib.parse.quote(relative, safe="/._-")
    if fragment:
        encoded += "#" + urllib.parse.quote(fragment, safe="-_^\u4e00-\u9fff")
    return encoded


def scan_links(source_relative, content, target_index, schema, apply_fixes=False):
    raw_readonly = source_relative.startswith(schema["paths"]["raw"] + "/")
    apply_fixes = apply_fixes and not raw_readonly
    issues = []
    resolved_targets = set()
    replacements = []
    masked = mask_code(content)
    spans = [(start, end, False) for start, end in standard_link_spans(masked)]
    spans += [(start, end, True) for start, end in wikilink_spans(masked)]
    for start, end, is_wiki in sorted(set(spans)):
        target_text = content[start:end]
        result = (resolve_wikilink(source_relative, target_text, target_index, schema)
                  if is_wiki else resolve_standard_link(source_relative, target_text, target_index))
        if result.get("external"):
            continue
        relative = result.get("relative")
        line = line_number(content, start)
        label = "Wikilink" if is_wiki else "链接"
        fragment = result.get("fragment", "")
        if relative:
            resolved_targets.add(relative)
            if not fragment_exists(relative, fragment, target_index):
                issues.append(make_issue("🔴", f"{label} 锚点不存在: {target_text}", "修正或移除锚点", line=line))
            continue

        candidates = result.get("candidates", [])
        if len(candidates) == 1 and target_index.get("scan_errors"):
            issues.append(make_issue("🔴", f"{label} 候选范围不完整: {target_text}",
                                     f"目录扫描失败，不能判定唯一目标；已见候选: {candidates[0]}", line=line))
        elif len(candidates) == 1:
            if not fragment_exists(candidates[0], fragment, target_index):
                issues.append(make_issue("🔴", f"{label} 候选目标缺少锚点: {target_text}", "确认路径与锚点后人工修正", line=line))
                continue
            new_target = (format_wikilink_target(source_relative, candidates[0], target_text, schema)
                          if is_wiki else format_standard_target(source_relative, candidates[0], fragment))
            # Preserve query strings, angle brackets, titles, labels and aliases.
            if not is_wiki:
                query = urllib.parse.urlsplit(unescape_target(target_text)).query
                if query:
                    path_part, sep, anchor = new_target.partition("#")
                    new_target = path_part + "?" + query + (sep + anchor if sep else "")
            problem = f"发现失效 Wikilink: [[{target_text}]]" if is_wiki else f"发现死链: {target_text}"
            suggestion = f"[[{new_target}]]" if is_wiki else new_target
            issues.append(make_issue("🔴", problem, f"修正为 {suggestion}", line=line, is_auto=True))
            if apply_fixes:
                replacements.append((start, end, new_target))
                resolved_targets.add(candidates[0])
        elif len(candidates) > 1:
            problem = f"Wikilink 存在多个同名候选: {target_text}" if is_wiki else f"死链存在多个同名候选: {target_text}"
            issues.append(make_issue("🔴", problem, f"候选: {', '.join(candidates)}", line=line))
        else:
            problem = f"发现失效 Wikilink: [[{target_text}]]" if is_wiki else f"发现死链: {target_text}"
            issues.append(make_issue("🔴", problem, "请确认目标路径", line=line))
    for start, end, replacement in sorted(replacements, reverse=True):
        content = content[:start] + replacement + content[end:]
    if raw_readonly:
        for issue in issues:
            issue["is_auto"] = False
            issue["action"] = "raw 正文只读；请核对原始来源与链接基准，需要更新素材时重新摄入"
    return content, issues, resolved_targets


def check_sources(relative_path, metadata, target_index):
    """Sources provide provenance; they are not counted as knowledge backlinks."""
    issues = []
    sources = metadata.get("sources", [])
    if not isinstance(sources, list):
        return [make_issue("🔴", "sources 必须是数组", "修正 frontmatter", line=1)]
    for source in sources:
        resource = source.get("resource") if isinstance(source, dict) else None
        if not isinstance(resource, str) or not resource.strip():
            issues.append(make_issue("🔴", "sources 条目缺少有效 resource", "补充来源路径或 URI", line=1))
            continue
        result = resolve_standard_link(relative_path, resource, target_index)
        if result.get("external"):
            continue
        target = result.get("relative")
        if not target:
            issues.append(make_issue("🔴", f"来源文件不存在或越界: {resource}", "核对 sources[].resource", line=1))
        elif not fragment_exists(target, result.get("fragment", ""), target_index):
            issues.append(make_issue("🔴", f"来源锚点不存在: {resource}", "核对来源锚点", line=1))
    return issues


def check_conflicts(body):
    issues = []
    markers = list(re.finditer(r"^>\s*⚠️\s*注意：.*(?:观点冲突|事实冲突)", body, re.MULTILINE))
    for marker in markers:
        next_h2 = re.search(r"^##\s+", body[marker.end():], re.MULTILINE)
        end = marker.end() + next_h2.start() if next_h2 else len(body)
        block = body[marker.start():end]
        line = line_number(body, marker.start())
        required = ["### 观点 A", "### 观点 B", "### 当前处理"]
        missing = [heading for heading in required if heading not in block]
        if missing:
            issues.append(make_issue("🟡", "冲突记录结构不完整", f"缺少: {', '.join(missing)}", line=line))
        if block.count("- 来源：") < 2:
            issues.append(make_issue("🟡", "冲突双方缺少完整来源", "为观点 A 和观点 B 分别补充来源", line=line))
        status_match = re.search(r"^- 状态：\s*(.+)$", block, re.MULTILINE)
        if not status_match:
            issues.append(make_issue("🟡", "冲突记录缺少状态", "补充并存、已解决或延后", line=line))
        elif re.search(r"并存|待|open|unresolved", status_match.group(1), re.IGNORECASE):
            issues.append(make_issue("🟡", "存在尚未解决的冲突", "补充证据、人工裁决或设置复核时间", line=line))
            if not re.search(r"^- 复核时间：\s*(.+)$", block, re.MULTILINE):
                issues.append(make_issue("🔵", "未解决冲突缺少复核时间", "补充具体日期或明确标记为待定", line=line))

    if not markers:
        cue = re.search(r"^.*(?:与.+冲突|存在(?:事实|观点)?冲突|互相矛盾|contradicts|conflicts with).*$", body, re.MULTILINE | re.IGNORECASE)
        if cue:
            issues.append(make_issue("🟡", "发现未结构化的冲突候选", "使用冲突模板记录双方观点、来源和状态", line=line_number(body, cue.start())))
    return issues


def verification_dates(metadata):
    dates = []
    issues = []
    verified = metadata.get("verified", [])
    if isinstance(verified, dict):
        verified = [verified]
    if isinstance(verified, list):
        for item in verified:
            if isinstance(item, dict):
                value = item.get("at")
                parsed = parse_datetime(value)
                if parsed:
                    dates.append(parsed)
                elif value is not None:
                    issues.append(make_issue("🔵", "verified[].at 不是有效的 ISO 8601 时间", "修正 frontmatter", line=1))
            else:
                issues.append(make_issue("🔵", "verified 条目不是映射", "使用包含 at 和 source 的映射", line=1))
    else:
        issues.append(make_issue("🔵", "verified 不是数组或映射", "修正 frontmatter", line=1))
    for key in ("verified_at", "last_reviewed"):
        value = metadata.get(key)
        parsed = parse_datetime(value)
        if parsed:
            dates.append(parsed)
        elif value is not None:
            issues.append(make_issue("🔵", f"{key} 不是有效的 ISO 8601 时间", "修正 frontmatter", line=1))
    return dates, issues


def check_freshness(relative_path, metadata, schema, now=None):
    if not index_section_for(relative_path, schema):
        return []
    if str(metadata.get("status", "stable")).casefold() == "deprecated":
        return []

    issues = []
    now = now or datetime.datetime.now(datetime.timezone.utc)
    stale_after = metadata.get("stale_after")
    if stale_after:
        stale_at = parse_datetime(stale_after)
        if not stale_at:
            issues.append(make_issue("🔵", "stale_after 不是有效的 ISO 8601 时间", "修正 frontmatter", line=1))
        elif now >= stale_at:
            issues.append(make_issue("🟡", f"页面已超过 stale_after: {stale_at.isoformat()}", "重新核验来源并更新生命周期字段", line=1))
        return issues

    dates, date_issues = verification_dates(metadata)
    issues.extend(date_issues)
    if not dates:
        generated = metadata.get("generated")
        if isinstance(generated, dict):
            value = generated.get("at")
            generated_at = parse_datetime(value)
            if generated_at:
                dates.append(generated_at)
            elif value is not None:
                issues.append(make_issue("🔵", "generated.at 不是有效的 ISO 8601 时间", "修正 frontmatter", line=1))
        elif generated is not None:
            issues.append(make_issue("🔵", "generated 不是映射", "修正 frontmatter", line=1))
        timestamp_value = metadata.get("timestamp")
        timestamp = parse_datetime(timestamp_value)
        if timestamp:
            dates.append(timestamp)
        elif timestamp_value is not None:
            issues.append(make_issue("🔵", "timestamp 不是有效的 ISO 8601 时间", "修正 frontmatter", line=1))

    if dates:
        latest = max(dates)
        review_days = schema["limits"]["review_after_days"]
        if now - latest > datetime.timedelta(days=review_days):
            issues.append(make_issue("🔵", f"页面已超过 {review_days} 天未核验", "核对来源后补充 verified、verified_at 或 stale_after", line=1))
    return issues


def heuristic_checks(relative_path, body, metadata, schema):
    issues = []
    document_type = metadata.get("type")
    limits = schema["limits"]

    if relative_path.startswith(f"{schema['paths']['logs']}/"):
        if len(body.encode("utf-8")) > limits["max_log_bytes"]:
            issues.append(make_issue("🔵", "日志超过体积阈值", "建议开始新的日志分片，不移动或截断旧记录"))
        return issues

    if index_section_for(relative_path, schema) and not body.strip():
        issues.append(make_issue("🟡", "页面正文为空", "补充实际知识内容，完整的短定义无需扩写"))

    if index_section_for(relative_path, schema):
        line_count = len(body.splitlines())
        byte_count = len(body.encode("utf-8"))
        h2_count = len(re.findall(r"^##\s+", body, re.MULTILINE))
        if line_count > limits["max_page_lines"] or byte_count > limits["max_page_bytes"]:
            issues.append(make_issue("🔵", "页面超过体积阈值", "建议拆分为主页面和子页面"))
        if h2_count > limits["max_page_h2"]:
            issues.append(make_issue("🔵", "页面二级标题数量超过阈值", "建议按子主题拆分"))

    for section in schema["required_sections"].get(document_type if isinstance(document_type, str) else "", []):
        if not re.search(rf"^##\s+{re.escape(section)}\s*$", body, re.MULTILINE):
            issues.append(make_issue("🟡", f"缺少关键小节: {section}", "按对应页面模板补充"))
    return issues


def format_issue_location(relative_path, line=None):
    escaped = relative_path.replace("|", "\\|")
    return f"[[{escaped}]]:{line}" if line else f"[[{escaped}]]"


def format_report_item(relative_path, issue, action_label="修改建议"):
    item = f"- {issue['level']} {format_issue_location(relative_path, issue['line'])}\n  发现问题：{issue['problem']}"
    if issue["action"]:
        item += f"\n  {action_label}：{issue['action']}"
    return item


def add_index_entries(content, missing_pages, metadata_by_path, schema):
    issues = []
    grouped = defaultdict(list)
    wiki_prefix = f"{schema['paths']['wiki']}/"
    for relative_path in missing_pages:
        section = index_section_for(relative_path, schema)
        metadata = metadata_by_path.get(relative_path, {})
        title = metadata.get("title") or Path(relative_path).stem
        description = metadata.get("description") or "待补充摘要"
        target = relative_path[len(wiki_prefix):] if relative_path.startswith(wiki_prefix) else relative_path
        grouped[section].append(f"- [[{target}|{title}]]：{description}")
        issues.append(make_issue("🔴", f"index 缺少条目: {relative_path}", f"补充到 {section}", is_auto=True))

    for section, entries in grouped.items():
        heading = f"## {section}"
        block = "\n".join(sorted(entries))
        match = re.search(rf"^{re.escape(heading)}\s*$", content, re.MULTILINE)
        if match:
            content = content[:match.end()] + "\n\n" + block + content[match.end():]
        else:
            content = content.rstrip() + f"\n\n{heading}\n\n{block}\n"
    return content, issues


def check_index_consistency(content, pages, target_index, schema, source_relative=None):
    """Report duplicate entries, wrong sections, and stale optional counters."""
    issues = []
    source_relative = source_relative or schema["paths"]["index"]
    prose = mask_non_prose(content)
    headings = list(re.finditer(r"^##\s+(.+?)\s*$", prose, re.M))
    sections = set(schema["index_sections"].values())
    seen = set()
    spans = [(position, start, end, False) for position, start, end in standard_link_occurrences(prose)]
    spans += [(start, start, end, True) for start, end in wikilink_spans(prose)]
    for position, start, end, is_wiki in sorted(set(spans)):
        target = content[start:end]
        result = (resolve_wikilink(source_relative, target, target_index, schema)
                  if is_wiki else resolve_standard_link(source_relative, target, target_index))
        path = result.get("relative")
        if path not in pages:
            continue
        line = line_number(content, position)
        if path in seen:
            issues.append(make_issue("🟡", f"index 重复条目: {path}", "核对重复导航的意图，保留必要条目", line=line))
        seen.add(path)
        current = next((heading[1] for heading in reversed(headings) if heading.start() < position), None)
        expected = index_section_for(path, schema)
        if current in sections and current != expected:
            issues.append(make_issue("🟡", f"index 条目分区不一致: {path} 位于 {current}，应为 {expected}",
                                     "移动条目并保留已有说明，不自动重排索引", line=line))
    counts = defaultdict(int)
    for path in pages:
        counts[index_section_for(path, schema)] += 1
    # The shipped index uses shortened labels for these two section names.
    aliases = {"素材": "素材来源", "聚合": "主题聚合"}
    for line, text in enumerate(prose.splitlines(), 1):
        if not text.lstrip().startswith(">"):
            continue
        for match in re.finditer(r"(?:^|[>·|])[ \t]*([^:：·|]+)[：:][ \t]*(\d+)\b", text):
            label = match[1].strip()
            section = aliases.get(label, label)
            if section in sections and int(match[2]) != counts[section]:
                issues.append(make_issue("🟡", f"index 统计不一致: {label} 为 {match[2]}，实际为 {counts[section]}",
                                         "按实际内容页更新统计，重复链接只计一个页面", line=line))
    return issues


def create_or_append_log(kb_dir, schema, checked, issues, fixed, severity_counts):
    log_path, template = prepare_log(kb_dir, schema)
    now = datetime.datetime.now(datetime.timezone.utc)
    descriptor = os.open(log_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as log_file:
        fcntl.flock(log_file, fcntl.LOCK_EX)
        if os.fstat(log_file.fileno()).st_size == 0:
            log_file.write(template)
        log_file.write(f"\n## [{now:%Y-%m-%d}] lint | mode=fix\n\n")
        log_file.write(f"- Checked: {checked} files\n")
        log_file.write(
            f"- Issues: {issues} (严重 {severity_counts['🔴']} / 中等 {severity_counts['🟡']} / 轻微 {severity_counts['🔵']})\n"
        )
        log_file.write(f"- Auto-fixed: {fixed}\n")
        log_file.flush()
        os.fsync(log_file.fileno())


def prepare_log(kb_dir, schema):
    now = datetime.datetime.now(datetime.timezone.utc)
    relative = f"{schema['paths']['logs']}/{now:%Y%m}.md"
    log_path = checked_destination(kb_dir, relative)
    template = load_markdown_template("log-template.md")
    for placeholder, value in {
        "YYYY-MM-DDTHH:MM:SSZ": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "YYYY 年 MM 月": now.strftime("%Y 年 %m 月"),
        "YYYY-MM": now.strftime("%Y-%m"),
    }.items():
        template = template.replace(placeholder, value)
    return log_path, template


def main():
    parser = argparse.ArgumentParser(description="LLM Wiki Lint Tool")
    parser.add_argument("kb_dir", help="Path to the knowledge base directory")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--lint-dirs", nargs="*", help="Directories to lint, relative to kb_dir")
    scope.add_argument("--lint-files", nargs="+", help="Markdown files to lint, relative to kb_dir; always includes index")
    parser.add_argument("--index-file", help="Index file path, relative to kb_dir")
    parser.add_argument("--fix", action="store_true", help="Enable safe deterministic auto-fixes")
    parser.add_argument("--dry-run", action="store_true", help="Preview fixes without writing")
    parser.add_argument("--report-file", help="Path to save the markdown report")
    parser.add_argument("--fail-on", choices=("error", "warning", "any"),
                        help="Exit 1 when unresolved issues meet this severity threshold")
    args = parser.parse_args()

    try:
        schema = load_schema()
    except SchemaError as exc:
        parser.error(str(exc))
    kb_dir = Path(args.kb_dir).resolve()
    if not kb_dir.exists():
        parser.error(f"知识库目录不存在: {kb_dir}")

    missing = validate_structure(kb_dir, schema)
    if missing:
        parser.error("知识库结构不完整: " + ", ".join(missing))

    lint_dirs = [] if args.lint_files else (args.lint_dirs or [schema["paths"]["wiki"], schema["paths"]["raw"]])
    index_relative = args.index_file or schema["paths"]["index"]
    try:
        lint_roots = [resolve_within(kb_dir, path) for path in lint_dirs]
        selected_files = [resolve_within(kb_dir, path) for path in args.lint_files or []]
        index_path = resolve_within(kb_dir, index_relative)
    except SchemaError as exc:
        parser.error(str(exc))
    index_relative = index_path.relative_to(kb_dir).as_posix()
    if not index_path.is_file() or not index_relative.startswith(schema["paths"]["wiki"] + "/"):
        parser.error("index 必须是 wiki 内已存在的文件")
    if index_relative.startswith(schema["paths"]["logs"] + "/"):
        parser.error("历史日志不能用作 index")
    missing_lint_roots = [str(path) for path in lint_roots if not path.is_dir()]
    if missing_lint_roots:
        parser.error("lint 目录不存在: " + ", ".join(missing_lint_roots))
    assets_root = resolve_within(kb_dir, schema["paths"]["assets"])
    if any(path.is_relative_to(assets_root) for path in lint_roots):
        parser.error(f"lint 目录不能位于附件目录 {schema['paths']['assets']} 内")
    for path in selected_files:
        relative = path.relative_to(kb_dir).as_posix()
        if (not path.is_file() or path.suffix.casefold() != ".md"
                or is_asset_path(relative, schema)
                or not relative.startswith((schema["paths"]["wiki"] + "/", schema["paths"]["raw"] + "/"))):
            parser.error(f"lint 文件必须是 raw 或 wiki 内已存在的 Markdown 文件，附件除外: {relative}")

    write_enabled = args.fix and not args.dry_run
    if write_enabled:
        try:
            prepare_log(kb_dir, schema)
        except (SchemaError, TemplateError, OSError) as exc:
            parser.error(str(exc))
    target_index = build_target_index(kb_dir, schema)
    scan_errors = target_index["scan_errors"]
    report_path = Path(args.report_file).absolute() if args.report_file else None
    if report_path:
        report_target = report_path.resolve()
        if (report_path.is_symlink() or is_allowed_target(report_target, target_index)
                or report_target == kb_dir / "AGENTS.md"):
            parser.error("报告路径必须位于 raw、wiki 之外，且不能覆盖 AGENTS.md 或符号链接")
    markdown_files = set(selected_files)
    if args.lint_files:
        markdown_files.add(index_path)
    for root in lint_roots:
        for path in walk_visible_files(root, scan_errors, kb_dir, excluded_roots=[assets_root]):
            if path.suffix.casefold() != ".md":
                continue
            resolved = path.resolve()
            try:
                resolved.relative_to(kb_dir)
            except ValueError:
                continue
            markdown_files.add(resolved)
    markdown_files = sorted(markdown_files)

    # Reuse a single decoded inventory for selected pages, evidence, headings,
    # and backlinks. Invalid YAML remains in text_cache for read-only scans.
    text_cache = {}
    documents, document_errors = load_documents(
        kb_dir, [schema["paths"]["raw"], schema["paths"]["wiki"]], text_cache=text_cache,
        scan_errors=scan_errors, excluded_roots=[schema["paths"]["assets"]],
    )
    if scan_errors:
        write_enabled = False
    raw_documents = {path: document for path, document in documents.items()
                     if path.startswith(schema["paths"]["raw"] + "/")}
    latest = latest_sources(raw_documents, kb_dir)
    target_index["content_cache"] = text_cache

    def read_content(relative):
        if relative not in text_cache:
            if relative in document_errors:
                raise OSError(document_errors[relative])
            text_cache[relative] = (kb_dir / relative).read_bytes().decode("utf-8")
        return text_cache[relative]

    all_issues = []
    for relative, error in scan_errors.items():
        all_issues.append((relative, make_issue("🔴", f"扫描覆盖不完整: {error}",
                                              "恢复目录读取后重跑；本次不自动修复，也不判断孤儿页和索引统计")))
    selected_relatives = {path.relative_to(kb_dir).as_posix() for path in markdown_files}
    for relative, error in document_errors.items():
        if relative not in selected_relatives and relative not in scan_errors:
            all_issues.append((relative, make_issue("🟡", f"来源关系读取失败: {error}", "修复后重新检查来源版本与证据链")))
    batch_limit = schema["limits"]["max_lint_batch_pages"]
    if len(markdown_files) > batch_limit:
        all_issues.append((
            schema["paths"]["wiki"],
            make_issue(
                "🔵",
                f"本次扫描页面数超过批次阈值: {len(markdown_files)} > {batch_limit}",
                "后续按 topic 或目录分批执行深度语义检查",
            ),
        ))
    outbound_by_source = defaultdict(set)
    metadata_by_path = {}
    content_by_path = {}
    planned_writes = {}

    for filepath in markdown_files:
        relative = filepath.relative_to(kb_dir).as_posix()
        try:
            # Preserve raw body line endings when only frontmatter is repaired.
            content = read_content(relative)
        except (OSError, UnicodeDecodeError) as exc:
            all_issues.append((relative, make_issue("🔴", f"Markdown 文件无法读取: {exc}", "修复编码或文件权限")))
            continue

        original = content
        _, _, _, original_error = split_frontmatter(content)
        is_log = relative.startswith(schema["paths"]["logs"] + "/")
        page_writable = write_enabled and not is_log and original_error in ("", "缺少 YAML frontmatter")
        content, frontmatter_issues, metadata, body = check_and_fix_frontmatter(
            filepath,
            content,
            kb_dir,
            schema,
            apply_fixes=page_writable,
        )
        if content != original:
            _, proposed_metadata, _, proposed_error = split_frontmatter(content)
            if proposed_error or proposed_metadata != metadata:
                # Anchors/aliases can connect a repaired field to unknown fields.
                content = original
                _, metadata, body, _ = split_frontmatter(original)
                for issue in frontmatter_issues:
                    issue["is_auto"] = False
                frontmatter_issues.append(make_issue("🔴", "修复会破坏 YAML 引用或改变其他字段", "保留原文，请人工修复", line=1))
        content, link_issues, resolved_targets = scan_links(relative, content, target_index, schema, apply_fixes=page_writable)
        _, parsed_metadata, parsed_body, parse_error = split_frontmatter(content)
        if not parse_error:
            parsed_metadata.update(metadata)
            metadata = parsed_metadata
            body = parsed_body
        metadata_by_path[relative] = metadata
        content_by_path[relative] = content
        text_cache[relative] = content
        outbound_by_source[relative].update(resolved_targets)

        issues = frontmatter_issues + link_issues
        if not page_writable:
            for issue in issues:
                issue["is_auto"] = False if write_enabled else issue["is_auto"]
        issues += check_source_file_integrity(relative, metadata, kb_dir, schema, latest)
        issues += check_raw_snapshot(relative, metadata, body, kb_dir, schema)
        issues += check_sources(relative, metadata, target_index)
        issues += heuristic_checks(relative, body, metadata, schema)
        conflict_issues = check_conflicts(mask_code(body))
        body_offset = content.count("\n", 0, len(content) - len(body))
        for issue in conflict_issues:
            if issue["line"]:
                issue["line"] += body_offset
        issues += conflict_issues
        issues += check_freshness(relative, metadata, schema)
        all_issues.extend((relative, issue) for issue in issues)

        if page_writable and content != original:
            planned_writes[relative] = content

    for relative, content in content_by_path.items():
        _, metadata, body, error = split_frontmatter(content)
        if not error:
            documents[relative] = {"metadata": metadata, "body": body, "path": kb_dir / relative}
    provenance = ProvenanceGraph(kb_dir, schema, lambda source, target: resolve_standard_link(source, target, target_index), documents)
    for relative, content in content_by_path.items():
        _, metadata, body, error = split_frontmatter(content)
        if error:
            continue
        body_offset = content.count("\n", 0, len(content) - len(body))
        for issue in provenance.check(relative, body, metadata):
            if issue.pop("_body_line", False):
                issue["line"] += body_offset
            all_issues.append((relative, issue))

    eligible_pages = {
        path for path in metadata_by_path
        if index_section_for(path, schema)
    }
    # Scope limits checks and edits, not the graph used to establish backlinks.
    global_pages = {path for path in target_index["by_relative"] if index_section_for(path, schema) and path.endswith(".md")}
    graph_complete = not scan_errors
    for relative in sorted((global_pages | {index_relative}) - content_by_path.keys()):
        try:
            content = read_content(relative)
            _, _, targets = scan_links(relative, content, target_index, schema)
            outbound_by_source[relative] = targets
            if relative == index_relative:
                content_by_path[relative] = content
        except (OSError, UnicodeDecodeError) as exc:
            graph_complete = False
            all_issues.append((relative, make_issue("🔴", f"全库关系读取失败: {exc}", "修复后重跑；本次不判断孤儿页")))
    inbound = defaultdict(set)
    for source, targets in outbound_by_source.items():
        if source not in global_pages:
            continue
        for target in targets:
            if target in eligible_pages and target != source:
                inbound[target].add(source)
    for page in sorted(eligible_pages):
        if graph_complete and not inbound[page]:
            all_issues.append((page, make_issue("🟡", "孤儿页面，没有其他内容页指向此页", "从相关内容页建立入链")))

    index_content = content_by_path.get(index_relative)
    indexed_pages = outbound_by_source.get(index_relative, set())
    missing_index_pages = sorted(eligible_pages - indexed_pages)
    if index_content is not None and missing_index_pages:
        new_index_content, index_issues = add_index_entries(index_content, missing_index_pages, metadata_by_path, schema)
        all_issues.extend((index_relative, issue) for issue in index_issues)
        index_error = split_frontmatter(index_content)[3]
        if index_error:
            for issue in index_issues:
                issue["is_auto"] = False
            if index_relative not in {p.relative_to(kb_dir).as_posix() for p in markdown_files}:
                all_issues.append((index_relative, make_issue("🔴", index_error, "保留 index 原文，请人工修复", line=1)))
        if write_enabled and not index_error and new_index_content != index_content:
            planned_writes[index_relative] = new_index_content

    if index_content is not None and graph_complete:
        checked_index = planned_writes.get(index_relative, index_content)
        all_issues.extend((index_relative, issue) for issue in
                          check_index_consistency(checked_index, global_pages, target_index, schema, index_relative))

    severity_counts = {"🔴": 0, "🟡": 0, "🔵": 0}
    auto_fixed = []
    manual = {"🔴": [], "🟡": [], "🔵": []}
    for relative, issue in all_issues:
        severity_counts[issue["level"]] += 1
        if issue["is_auto"] and write_enabled:
            auto_fixed.append(format_report_item(relative, issue, "修复操作"))
        else:
            manual[issue["level"]].append(format_report_item(relative, issue))

    if write_enabled:
        report = "## Lint 报告\n\n"
        report += f"总页面 {len(markdown_files)} / 发现问题 {len(all_issues)} / 已修复 {len(auto_fixed)}\n\n"
    else:
        suffix = " (预览模式)" if args.dry_run else ""
        report = f"## Lint 报告{suffix}\n\n"
        report += f"总页面 {len(markdown_files)} / 发现问题 {len(all_issues)}\n\n"
    report += f"🔴 严重: {severity_counts['🔴']} 个（需要立刻解决）\n"
    report += f"🟡 中等: {severity_counts['🟡']} 个（建议补充完善）\n"
    report += f"🔵 轻微: {severity_counts['🔵']} 个（架构规范建议）\n\n"

    if all_issues and write_enabled:
        report += f"### ✅ 自动修复 ({len(auto_fixed)})\n\n"
        report += "\n".join(auto_fixed) + "\n\n" if auto_fixed else "无自动修复操作。\n\n"
        manual_count = sum(len(items) for items in manual.values())
        report += f"### ⚠️ 需要人工介入 ({manual_count})\n\n"
        for level in ("🔴", "🟡", "🔵"):
            if manual[level]:
                report += "\n".join(manual[level]) + "\n"
    elif all_issues:
        report += f"### ⚠️ 问题详情 ({len(all_issues)})\n\n"
        for level in ("🔴", "🟡", "🔵"):
            if manual[level]:
                report += "\n".join(manual[level]) + "\n"

    if write_enabled:
        written = []
        try:
            # Validate every destination before committing any page changes.
            for relative in planned_writes:
                checked_destination(kb_dir, relative)
            for relative, content in planned_writes.items():
                destination = checked_destination(kb_dir, relative)
                atomic_write_text(destination, content)
                written.append(relative)
            create_or_append_log(kb_dir, schema, len(markdown_files), len(all_issues), len(auto_fixed), severity_counts)
        except (OSError, SchemaError, TemplateError) as exc:
            print(f"lint 事务未完成: {exc}；已写入: {', '.join(written) or '无'}；请检查日志并恢复后重跑", file=sys.stderr)
            return 2

    if report_path:
        try:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(report_path, report.rstrip() + "\n")
        except OSError as exc:
            print(f"报告写入失败: {exc}" + ("；修复及日志已完成" if write_enabled else ""), file=sys.stderr)
            return 2
        print(f"Lint complete. Report saved to {report_path}")
    else:
        print(report)
    if scan_errors:
        print("目录扫描未完成，覆盖不完整；未执行自动修复或追加修复日志，请恢复目录读取后重跑", file=sys.stderr)
        return 2
    levels = {"error": {"🔴"}, "warning": {"🔴", "🟡"}, "any": {"🔴", "🟡", "🔵"}}
    if args.fail_on and any(manual[level] for level in levels[args.fail_on]):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
