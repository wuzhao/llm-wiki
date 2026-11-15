# 复核记录工作流

用于将实际核对过的证据结论留给下次检查复用。记录格式与失效条件统一遵循 [来源策略](provenance-policy.md#agent-分流与复核复用)，报告选项见 [Lint Policy](lint-policy.md)。工具不会从日志、普通 Markdown 报告或历史对话自动推断批准。

## 第 1 步：查看摘要并导出候选

```bash
"<PYTHON>" "<SKILL_DIR>/scripts/lint_wiki.py" "<KB_DIR>" \
    --review-template "/outside-kb/reviews-new.json" \
    --report-file "/outside-kb/lint-full.md"
```

复核模板必须是知识库之外的新文件。终端显示摘要，完整报告保留每个问题的位置、来源范围、原文候选与 id。导出不代表已核验。

## 第 2 步：按页阅读证据

```bash
"<PYTHON>" "<SKILL_DIR>/scripts/lint_wiki.py" "<KB_DIR>" \
    --report-page wiki/concepts/example.md --report-category evidence
```

此处只筛选显示，扫描与退出码仍覆盖原范围。先核对主张所指对象、时期、单位、限定条件与实际原文，再判断 supported、non-quantity、author-structure 或继续 pending；同值和同词不能代替语义核对。

## 第 3 步：填写已经完成的复核

保留模板记录的 id、page、claim、kind、context、line、dependencies 和 rules，仅填写复核字段。下面只是需要填写的字段示例，必须将占位内容替换为实际核对结果，不能把它当作完整记录导入：

```json
{
  "status": "supported",
  "reason": "<实际核对的对象、期间、单位与支持关系>",
  "reviewer": "<实际复核者>",
  "reviewed_at": "<本次实际 ISO 时间>",
  "evidence": [
    {"path": "raw/example.md", "quote": "<该条来源范围内实际存在的原文片段>"}
  ]
}
```

泛指或作者自行组织条目可以使用对应状态并写清理由。缺材料、真实冲突或尚未核对的候选保持 pending。已有 Markdown 复核报告只能作为线索，仍需确认当前页面与原文后填写。

## 第 4 步：加载记录验证

```bash
"<PYTHON>" "<SKILL_DIR>/scripts/lint_wiki.py" "<KB_DIR>" \
    --review-file "/outside-kb/reviews-new.json" --fail-on warning
```

摘要会分别显示原始告警数、已有有效记录的主张数和仍待复核数。证据主张全部复核也可能返回 1，因为严格退出码继续使用原始诊断级别；这不表示记录没有加载。使用 `--details` 查看逐条理由与原文。

## 第 5 步：后续检查继续复用

每次显式传入 `--review-file`；需要导出新候选时同时传入 `--review-template` 并使用新的文件名，有效记录会保留在新模板中。页面、传递来源或检查规则变化后，对应记录会失效，重新核对后再填写。

局部扫描导出只包含本次范围的候选，不能覆盖全库旧记录。需要更新全库记录时使用全库扫描导出到新文件，保留旧文件供回查。复核记录不会补齐知识页来源，也不会修改 raw、wiki 或日志。
