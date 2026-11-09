"""Render lint findings without inspecting or modifying the knowledge base."""
from dataclasses import dataclass
from collections import Counter, defaultdict
import html
import re


@dataclass
class LintReport:
    text: str
    severity_counts: dict
    fixed_count: int
    unresolved_levels: set


def format_issue_location(relative_path, line=None):
    escaped = relative_path.replace("|", "\\|")
    return f"[[{escaped}]]:{line}" if line else f"[[{escaped}]]"


def inline_text(value):
    # Source material is data, not Markdown instructions or report headings.
    value = html.escape(re.sub(r"\s+", " ", value), quote=False)
    return re.sub(r"([\\`*_{}\[\]\|])", r"\\\1", value)


def candidate_groups(all_issues):
    groups = defaultdict(list)
    for path, issue in all_issues:
        for detail in issue.get("details", []):
            if detail["candidate_count"] != 1:
                continue
            candidate = detail["candidates"][0]
            key = (candidate["path"], candidate["fingerprint"], candidate["start"], candidate["end"],
                   detail["kind"], detail["claim"])
            groups[key].append((path, issue, detail, candidate))
    groups = [uses for uses in groups.values() if len({use[0] for use in uses}) > 1]
    if not groups:
        return ""
    result = "\n### 共同原文候选\n\n以下仅汇总重复回查入口，不增加告警计数；不是已确认的共同事实，仍须逐处核对指标、时间与归因。\n\n"
    for uses in groups:
        candidate = uses[0][3]
        result += f"- 候选 {inline_text(candidate['literal'])}，{format_issue_location(candidate['path'], candidate['line'])}，列 {candidate['column']}\n"
        result += f"  原文片段：{inline_text(candidate['context'])}\n"
        for path, issue, detail, _ in uses:
            result += f"  - 影响 {format_issue_location(path, detail.get('line', issue['line']))}：{inline_text(detail['context'])}\n"
    return result


def format_report_item(relative_path, issue, action_label="修改建议"):
    label = "复核线索" if issue.get("category") == "evidence" else "发现问题"
    item = f"- {issue['level']} {format_issue_location(relative_path, issue['line'])}\n  {label}：{issue['problem']}"
    if issue["action"]:
        item += f"\n  {action_label}：{issue['action']}"
    for detail in issue.get("details", []):
        item += f"\n  - {detail.get('level', issue['level'])} 主张 {inline_text(detail['claim'])}：{detail['label']}。{detail['action']}"
        if detail.get('review'):
            review = detail['review']
            item += f"\n    已复核（{inline_text(review['status'])}）：{inline_text(review['reason'])}；复核者 {inline_text(review['reviewer'])}"
        for candidate in detail["candidates"]:
            item += (f"\n    - 原文候选 {inline_text(candidate['literal'])}，"
                     f"{format_issue_location(candidate['path'], candidate['line'])}，列 {candidate['column']}："
                     f"{inline_text(candidate['context'])}")
        if detail["candidate_count"] > len(detail["candidates"]):
            item += f"\n    - 共 {detail['candidate_count']} 处候选，仅展示前 {len(detail['candidates'])} 处；需消歧。"
    return item


def review_groups(all_issues):
    groups = defaultdict(list)
    for path, finding in all_issues:
        for detail in finding.get('details', []):
            key = (path, detail['claim'], detail['kind'], tuple(finding.get('sources', [])))
            groups[key].append((finding, detail))
    if not groups:
        return ''
    reviewed = sum(bool(d.get('review')) for rows in groups.values() for _, d in rows)
    total = sum(map(len, groups.values()))
    pending_groups = sum(any(not d.get('review') for _, d in rows) for rows in groups.values())
    result = (f'### Agent 复核工作台\n\n{total} 个主张按同页、同表达、同诊断与同来源范围合为 {len(groups)} 组；'
              f'其中 {pending_groups} 组待复核，{reviewed} 个主张已有有效复核记录。'
              '分组不代表同一事实，需核对组内每处语境；原始告警数、严重级别与退出码不变。\n\n'
              'Agent 先核对泛指、作者自编结构、翻译候选与已有记录；只有证据缺口、冲突或需要用户取舍的内容进入用户决策清单。\n\n')
    for (path, claim, kind, sources), rows in groups.items():
        pending = any(not d.get('review') for _, d in rows)
        state = '待复核' if pending else '已复核'
        result += f'<details>\n<summary>{state}：{inline_text(path)}，{inline_text(claim)}，{len(rows)} 处</summary>\n\n'
        result += rows[0][1]['label'] + '。\n\n'
        if sources:
            result += '来源范围：' + '、'.join(format_issue_location(p) for p in sources) + '\n\n'
        for finding, detail in rows:
            result += f"- {format_issue_location(path, detail.get('line', finding.get('line')))}：{inline_text(detail['context'])}\n"
            if detail.get('review'):
                review = detail['review']
                result += f"  已复核：{inline_text(review['reason'])}（{inline_text(review['reviewer'])}，{inline_text(review['reviewed_at'])}）\n"
            if detail.get('review_id'):
                result += f"  复核 id：`{detail['review_id']}`\n"
        result += '\n</details>\n\n'
    return result


def format_categories(items, level=None):
    result = ""
    for category, title in (("evidence", "证据待复核"), ("citation", "引用完整性"), ("other", "其他检查")):
        selected = [item for kind, item in items if kind == category]
        if selected:
            if category == "evidence" and level == "🔵":
                title = "证据表达建议"
            result += f"\n#### {title} ({len(selected)})\n\n" + "\n".join(selected) + "\n"
    return result


def diagnostic_summary(all_issues):
    counts = Counter(detail["label"] for _, issue in all_issues for detail in issue.get("details", []))
    levels = Counter((detail["label"], detail.get("level", issue["level"]))
                     for _, issue in all_issues for detail in issue.get("details", []))
    if not counts:
        return ""
    report = ("### 证据诊断概览\n\n以下按未匹配的主张计数，一条告警可包含多个主张；不增加告警总数。"
              "分类仅帮助安排复核，候选未定位或口径差异均不能据此判为事实正确。\n\n"
              "| 诊断 | 主张数 | 🟡 待复核 | 🔵 建议 |\n| ---- | -----: | -------: | ------: |\n")
    for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        report += f"| {label} | {count} | {levels[label, '🟡']} | {levels[label, '🔵']} |\n"
    return report + "\n"


def unlocated_review_queue(all_issues):
    pages = defaultdict(list)
    for path, issue in all_issues:
        for detail in issue.get("details", []):
            if detail["kind"] == "not-found":
                pages[path].append(detail.get("line", issue["line"]))
    if not pages:
        return ""
    report = ("### 未定位数值复核队列（按页）\n\n"
              f"共 {len(pages)} 页、{sum(map(len, pages.values()))} 个未定位主张，仅提供回查导航，不增加告警计数。"
              "未定位不等于编造，也不能直接认定为格式噪声。优先核对影响结论的数字、单位、期间和派生依据，"
              "不按数量机械清零；完整论断与来源范围见下方详情。\n\n"
              "| 页面与起始位置 | 未定位主张数 |\n| -------------- | -----------: |\n")
    for path, lines in sorted(pages.items(), key=lambda item: (-len(item[1]), item[0])):
        line = min((line for line in lines if line), default=None)
        report += f"| {format_issue_location(path, line)} | {len(lines)} |\n"
    return report + "\n"


def build_report(all_issues, checked, write_enabled=False, dry_run=False, *, fix_requested=False):
    severity_counts = {"🔴": 0, "🟡": 0, "🔵": 0}
    auto_fixed = []
    manual = {"🔴": [], "🟡": [], "🔵": []}
    show_repairs = write_enabled or (fix_requested and dry_run)
    for relative, issue in all_issues:
        severity_counts[issue["level"]] += 1
        if issue["is_auto"] and show_repairs:
            auto_fixed.append(format_report_item(relative, issue, "修复操作"))
        else:
            manual[issue["level"]].append((issue.get("category", "other"), format_report_item(relative, issue)))

    if write_enabled:
        report = "## Lint 报告\n\n"
        report += f"总页面 {checked} / 发现问题 {len(all_issues)} / 已修复 {len(auto_fixed)}\n\n"
    else:
        suffix = " (预览模式)" if dry_run else ""
        report = f"## Lint 报告{suffix}\n\n"
        report += f"总页面 {checked} / 发现问题 {len(all_issues)}"
        report += f" / 可自动修复 {len(auto_fixed)}（未写入）\n\n" if show_repairs else "\n\n"
    report += f"🔴 严重: {severity_counts['🔴']} 个（需要立刻解决）\n"
    report += f"🟡 中等: {severity_counts['🟡']} 个（建议补充完善）\n"
    report += f"🔵 轻微: {severity_counts['🔵']} 个（表达或架构建议）\n\n"
    report += diagnostic_summary(all_issues)
    report += unlocated_review_queue(all_issues)
    report += review_groups(all_issues)

    if all_issues and show_repairs:
        title = "✅ 自动修复" if write_enabled else "计划自动修复"
        report += f"### {title} ({len(auto_fixed)})\n\n"
        report += "\n".join(auto_fixed) + "\n\n" if auto_fixed else "无自动修复操作。\n\n"
        manual_count = sum(len(items) for items in manual.values())
        title = "需要人工介入" if write_enabled else "修复后仍需人工介入"
        report += f"### ⚠️ {title} ({manual_count})\n\n"
        for level in ("🔴", "🟡", "🔵"):
            if manual[level]:
                report += format_categories(manual[level], level)
    elif all_issues:
        other_findings = [(path, finding) for path, finding in all_issues if not finding.get('details')]
        if other_findings:
            report += '### 引用、来源与结构检查\n\n'
            for level in ('🔴', '🟡', '🔵'):
                selected = [(finding.get('category', 'other'), format_report_item(path, finding))
                            for path, finding in other_findings if finding['level'] == level]
                report += format_categories(selected, level)
        evidence_findings = [(path, finding) for path, finding in all_issues if finding.get('details')]
        if evidence_findings:
            report += '<details>\n<summary>完整证据逐条诊断（保留全部证据告警与原文候选）</summary>\n\n'
            report += f"### ⚠️ 证据问题详情 ({len(evidence_findings)})\n\n"
            for level in ("🔴", "🟡", "🔵"):
                selected = [(finding.get('category', 'evidence'), format_report_item(path, finding))
                            for path, finding in evidence_findings if finding['level'] == level]
                report += format_categories(selected, level)
            report += '\n</details>\n'

    report += candidate_groups(all_issues)
    unresolved = ({level for level, items in manual.items() if items} if write_enabled
                  else {issue["level"] for _, issue in all_issues})
    return LintReport(report, severity_counts, len(auto_fixed) if write_enabled else 0, unresolved)
