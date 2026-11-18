# Archive Template

```markdown
---
type: analysis
title: <分析标题>
description: <一句话摘要>
tags: [analysis, tag1, tag2]
generated: { by: "llm-wiki/{{SKILL_VERSION}}", at: YYYY-MM-DDTHH:MM:SSZ }
status: stable
# verified:
#   - { by: human:<id>, at: <实际核验 ISO 时间> }
# stale_after: <过期 ISO 时间>
sources:
  - { id: evidence-source, resource: <实际读取的来源相对路径> }
---

# <分析标题>

## 问题

## 结论

## 证据

<!-- 列出实际证据，关键数值和引文补充 [^evidence-source] 与对应脚注；无需同时存在实体和概念两类来源。 -->

## 盲点与后续
```
