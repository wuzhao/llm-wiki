"""Render lint findings without inspecting or modifying the knowledge base."""
from dataclasses import dataclass


@dataclass
class LintReport:
    text: str
    severity_counts: dict
    fixed_count: int
    unresolved_levels: set


def format_issue_location(relative_path, line=None):
    escaped = relative_path.replace("|", "\\|")
    return f"[[{escaped}]]:{line}" if line else f"[[{escaped}]]"


def format_report_item(relative_path, issue, action_label="修改建议"):
    item = f"- {issue['level']} {format_issue_location(relative_path, issue['line'])}\n  发现问题：{issue['problem']}"
    if issue["action"]:
        item += f"\n  {action_label}：{issue['action']}"
    return item


def build_report(all_issues, checked, write_enabled=False, dry_run=False):
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
        report += f"总页面 {checked} / 发现问题 {len(all_issues)} / 已修复 {len(auto_fixed)}\n\n"
    else:
        suffix = " (预览模式)" if dry_run else ""
        report = f"## Lint 报告{suffix}\n\n"
        report += f"总页面 {checked} / 发现问题 {len(all_issues)}\n\n"
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

    return LintReport(report, severity_counts, len(auto_fixed), {level for level, items in manual.items() if items})
