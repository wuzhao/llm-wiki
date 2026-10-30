# Concept Template

```markdown
---
type: concept
title: <概念名称>
description: <一句话定义>
# resource: <存在 canonical URI 时填写>
tags: [concept, tag1, tag2]
aliases: []
generated: { by: "llm-wiki/{{SKILL_VERSION}}", at: YYYY-MM-DDTHH:MM:SSZ }
status: stable
# verified:
#   - { by: human:<id>, at: YYYY-MM-DDTHH:MM:SSZ }
# stale_after: YYYY-MM-DDTHH:MM:SSZ
domain: <领域>
sources:
  - id: source-summary
    resource: ../summaries/<slug>.md
    # body_sha256: <实际读取的来源正文 SHA256>
---

# <概念名称>

<概念的完整定义与适用条件，可以简短>

<!-- 关键数字、日期和直接引文先定位 raw，再使用 [^source-summary] 标注并补充脚注；推导须说明依据。 -->

<!-- 按实际信息添加详解、示例或应用场景。有实际关系且目标页存在时再添加相关概念或实体，无需保留空小节。 -->

## 来源
- [[summaries/<slug>]]：YYYY-MM-DD
```
