# Source Template

```markdown
---
type: source-summary
title: <素材标题>
description: <一句话摘要>
resource: <原文 URL 或原始路径>
tags: [source, tag1, tag2]
generated: { by: llm-wiki/0.1.0, at: YYYY-MM-DDTHH:MM:SSZ }
status: stable
# verified:
#   - { by: human:<id>, at: YYYY-MM-DDTHH:MM:SSZ }
# stale_after: YYYY-MM-DDTHH:MM:SSZ
sources:
  - id: raw-source
    resource: ../../raw/<slug>.md
    # body_sha256: <实际读取的来源正文 SHA256>
---

# <素材标题>

## 摘要

## 关键要点

- 要点 1。[^raw-source]

[^raw-source]: 原始素材，关键数字与引文须先核对其原文及适用条件。

<!-- 必须按 synthesis-policy.md 检查核心实体、概念和历史摘要。满足门槛时建页或更新，再添加真实的目标页链接；值得保留但证据不足的主题记录到 synthesis.deferred，不创建占位页。检查后记录工具返回的指纹，无候选时使用空数组。 -->
```
