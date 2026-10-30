---
name: llm-wiki
description: 管理由 raw/（含 raw/assets/ 附件）与 wiki/ 组成的本地 Markdown 知识库，用于初始化、素材摄入与更新、基于库内证据的查询、知识探索和健康维护。
metadata:
  version: 0.2.3
  compatibility: macOS / Linux
---

# LLM Wiki

采用「编译优先，按需检索」：把用户素材编译为有来源的知识页，再以全文搜索和分批阅读回答问题。确定性操作使用 `scripts/`，语义判断由 Agent 阅读证据完成。

## 按任务读取

先读 `references/preflight.md`，确定技能目录、知识库目标与解释器，使用绝对路径调用工具。配套 CLI 已执行结构校验时复用结果；手工检查或初始化时再读取 `references/schema.json`，不维护另一份目录与阈值。

| 任务 | 执行策略 |
| ---- | -------- |
| init，初始化空知识库 | `references/init-files.md`、`references/schema.md` |
| ingest，摄入素材（含更新与补完） | `references/ingest-policy.md`、`references/provenance-policy.md` |
| synthesize，整理已有摘要、提炼知识页 | `references/synthesis-policy.md` |
| query，基于库内内容回答 | `references/query-policy.md` |
| explore，研究方向与知识缺口 | `references/explore-policy.md` |
| lint，健康检查 | `references/lint-policy.md`；核验来源时补读 `references/provenance-policy.md` |
| cleanup，删除内容 | 本文件的「清理内容」 |

- 摄入、投喂、重新摄入、重新投喂及更新素材的请求均执行 ingest，由来源身份、内容变化与编译进度决定分支，不因再次输入就强制新增版本或重建页面。
- 写入前补读 `references/guardrails.md`、`references/okf-frontmatter.md`，只加载本次产物需要的 `templates/` 模板；用 `scripts/wiki_config.py --template <模板文件名>` 渲染当前版本与 UTC 时间，再填写知识内容。
- 回查原始证据时读 `references/provenance-policy.md`；发现容量问题或用户要求结构治理时读 `references/scalability-policy.md`。
- 本地工具异常时按 `references/guardrails.md` 的环境处理规则诊断。
- 回归或发布前读 `references/golden-sample.md`。
- ingest 必须执行 `references/synthesis-policy.md` 的主题检查与增量复核；首次整理及显式全库整理覆盖历史摘要。满足建页门槛时在本次任务内创建或更新，不以「按需」推迟。

## 5 条护栏（必须执行）

1. 能力声明真实：声明与实现一致。
2. 前置检查硬校验：非 init 场景缺结构即停止。
3. YAML frontmatter 遵循 OKF 0.2：概念文档仅 `type` 始终必填，raw、wiki 与系统页分别使用 `references/okf-frontmatter.md` 定义的 profile。
4. lint 自动修复边界：默认 report-only；显式 `--fix` 才对安全子集自动补齐。raw 仅允许补齐可确定的 frontmatter 字段，正文始终只读；启发式项保持 report-only，禁止任何隐式破坏性改写。
5. 日志 append-only：每个产生文件变更的 workflow 事务完成后追加一条记录，`wiki/logs/YYYYMM.md` 按月存储，只追加，不截断。

## 共用写入收尾

init、ingest、synthesize、query 归档、explore 落盘与 cleanup 统一执行 `references/lint-policy.md` 的「写后检查」，由该策略定义索引维护、只读检查、修正与事务日志。只读 query/explore 不触发收尾流程。

## 清理内容

先全局搜索引用，给出影响范围报告，逐项列明目标路径和关联页面。删除、重命名或批量改链接的授权边界见 `references/guardrails.md`。

用户批准仅适用于报告中的确切目标，新增目标须重新报告并获准。获准后删除文件、清理残留引用，再执行共用写入收尾。
