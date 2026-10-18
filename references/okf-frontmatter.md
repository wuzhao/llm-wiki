# OKF Frontmatter Profile

本文件定义 LLM Wiki 对 [Open Knowledge Format v0.2](https://github.com/GoogleCloudPlatform/open-knowledge-format/blob/main/SPEC.md) 的本地 profile。

## OKF 0.2 基线

- 概念文档是带 YAML frontmatter 的 UTF-8 Markdown 文件。
- `type` 是概念文档唯一始终必填的字段。
- `title`、`description`、`resource` 与 `tags` 是推荐字段。
- `sources`、`generated`、`verified`、`status` 与 `stale_after` 是可选的来源、信任和生命周期字段。
- `generated.by` 和 `verified[].by` 使用 actor 约定：Agent 或工具写为 `<producer>/<version>`，人工写为 `human:<id>`，自动过程写为 `process:<id>`。
- 所有 OKF 时间字段使用带明确 UTC offset 的 ISO 8601 datetime。
- 允许生产者增加自定义字段，消费者应在往返写入时保留未知字段。

## LLM Wiki profile

### wiki 概念文档

适用于 `wiki/summaries/`、`wiki/entities/`、`wiki/concepts/`、`wiki/analyses/`、`wiki/hubs/` 和 `wiki/overview.md` 下的概念文档：

- `type` 必填，并与 `schema.json` 的路径类型映射一致。
- 本项目 lint 推荐 `title`、`description` 与 `tags`；`resource` 只在存在 canonical URI 时使用。
- 新模板用 `generated.at` 记录最后一次有意义的内容变更。
- 新模板用 `sources` 记录来源，并用 `verified` 记录核验事件。
- `status` 只使用 `draft`、`stable` 或 `deprecated`；缺失时按 `stable` 解释。
- 本地 profile 支持可选 `aliases` 字符串数组供搜索使用；`sources[].body_sha256` 记录实际读取的来源正文指纹，`sources[].historical: true` 表示该来源仅支撑明确保留的历史内容。逐条证据引用与依赖更新见 `provenance-policy.md`，不改变 OKF 的最小必填要求。

### bundle index

`wiki/` 是知识 bundle 根目录，`wiki/index.md` 是 OKF 0.2 的根 index：

- frontmatter 只包含 `okf_version: "0.2"`。
- index 不要求 `type`、`title`、`description`、`tags` 或时间字段。
- index 的正文按分区列出内容页，空知识库的分区可以为空。

### raw 素材页

`raw/**/*.md` 是知识 bundle 之外的摄入存储，使用独立 raw profile：

- `type` 必填，固定由路径推断为 `source-material`。
- `title` 用于辨识素材，缺失时 lint 可以安全补齐。
- `resource`、`source_url`、`source_file_path` 与 `source_file_sha256` 按来源类型选填。
- `timestamp` 表示采集时间，是 LLM Wiki 自定义字段，不是 OKF 0.2 推荐字段。
- `source_id`、`source_version`、`supersedes` 分别记录来源身份、版本与前一快照的知识库相对路径；`content_sha256` 用于相同内容提醒，`body_sha256` 用于检测 raw 正文是否改变。
- URL 的 `source_snapshot` 指向 `assets/` 中的原始响应，`source_snapshot_sha256` 校验响应字节，`source_media_type`、`source_encoding`、`resolved_url` 与 `extraction_version` 描述提取过程；这些都是本项目扩展。
- lint 不要求 raw 提供 wiki profile 的 `description`、`tags`、`generated`、`verified`、`status` 或 `stale_after`。
- 首次摄入正常生成元数据；既有 raw 正文连同链接、空白和换行保持只读。显式 `lint --fix` 仅补齐可确定的 `type` 与 `title`，保留来源地址、采集时间及未知字段。其他元数据纠正须有来源依据并记录日志，不能猜测地址或时间。

### 系统页

- `wiki/overview.md` 作为普通概念文档，使用 `type: overview`。
- `wiki/logs/YYYYMM.md` 不是 OKF 保留文件名 `log.md`，使用 `type: operation-log`；lint 不要求日志提供内容页的推荐字段。

## 链接扩展

OKF 0.2 推荐标准 Markdown 链接。LLM Wiki 同时支持 Obsidian Wikilink 作为本地扩展；可移植性优先的内容应使用标准 Markdown 的 bundle-root 绝对路径或相对路径。

## 示例

```yaml
---
type: concept
title: 向量数据库
description: 面向语义检索与 RAG 场景的向量索引与召回能力。
tags: [concept, retrieval, rag]
generated: { by: llm-wiki/0.1.0, at: 2026-09-14T08:30:00Z }
status: stable
sources:
  - id: source-summary
    resource: ../summaries/vector-database.md
verified:
  - { by: human:reviewer, at: 2026-09-14T09:00:00Z }
stale_after: 2027-03-14T00:00:00Z
---
```

## 兼容与校验

- 无法解析的 YAML 只报告，不自动重写。
- 旧 wiki 页面中的 `timestamp`、`verified_at` 与 `last_reviewed` 仍可用于陈旧性判断，但新模板不再生成这些字段。
- profile 的具体 lint 行为见 `lint-policy.md`，路径到 `type` 的映射和 OKF 版本见 `schema.json`。
