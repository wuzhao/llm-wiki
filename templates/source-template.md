# Source Template

```markdown
---
type: source-summary
title: <素材标题>
description: <一句话摘要>
resource: <原文 URL 或原始路径>
tags: [source, tag1, tag2]
generated: { by: "llm-wiki/{{SKILL_VERSION}}", at: YYYY-MM-DDTHH:MM:SSZ }
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

- <忠实转述的要点，单源直接转述使用页级 sources 即可>

<!-- 校准值、派生值与直接引文须就地使用 [^raw-source] 并补充唯一的脚注定义。校准保留原值、采用值与实际依据；派生列出有来源的分量和算法。多源或间接来源摘要的关键数字、日期与引文也须逐条标注，具体见 provenance-policy.md。 -->

<!-- 必须按 synthesis-policy.md 检查核心实体、概念和历史摘要。满足门槛时建页或更新，再添加真实的目标页链接；值得保留但证据不足的主题记录到 synthesis.deferred，不创建占位页。检查后记录工具返回的指纹，无候选时使用空数组。 -->
```
