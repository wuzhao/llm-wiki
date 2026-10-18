# Entity Template

```markdown
---
type: entity
title: <实体名称>
description: <一句话定义>
# resource: <存在 canonical URI 时填写>
tags: [entity, tag1, tag2]
aliases: []
generated: { by: llm-wiki/0.1.0, at: YYYY-MM-DDTHH:MM:SSZ }
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

# <实体名称>

<说明实体是什么，以及已有证据支持的当前状态，可以简短>

<!-- 区分当前事实、已被替代的历史和未解决冲突。关键数字与引文使用稳定来源 id 逐条引用。 -->

<!-- 按实际信息添加详情。有实际关系且目标页存在时再添加相关实体或概念，无需保留空小节。 -->

## 来源
- [[summaries/<slug>]]：YYYY-MM-DD
```
