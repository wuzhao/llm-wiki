---
name: llm-wiki
description: 管理由 raw/（含 raw/assets/ 附件）与 wiki/ 组成的本地 Markdown 知识库，用于初始化、素材摄入与更新、基于库内证据的查询、知识探索和健康维护。
metadata:
  version: 0.3.0
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
| lint，健康检查 | `references/lint-policy.md`；处理证据候选时补读 `references/review-workflow.md` |
| cleanup，删除内容 | 本文件的「清理内容」 |

- 摄入、投喂、重新摄入、重新投喂及更新素材的请求均执行 ingest，由来源身份、内容变化与编译进度决定分支，不因再次输入就强制新增版本或重建页面。
- 写入前补读 `references/guardrails.md`、`references/okf-frontmatter.md`，只加载本次产物需要的 `templates/` 模板；用 `scripts/wiki_config.py --template <模板文件名>` 渲染当前版本与 UTC 时间，再填写知识内容。
- 回查原始证据时读 `references/provenance-policy.md`；填写或复用复核记录、运行 `scripts/review_quality.py` 抽检时读 `references/review-workflow.md`；发现容量问题或用户要求结构治理时读 `references/scalability-policy.md`。
- 引用粒度按 `references/provenance-policy.md` 的来源结构规则执行：单源摘要的直接转述可用页级来源；多源或聚合页的关键数字、日期和引文，以及任何知识页的校准值、派生值与直接引文须就地标注。
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

只读 query/explore 不触发本节。init、ingest、synthesize、query 归档、explore 落盘与 cleanup 统一执行以下收尾。Agent 先维护本次变更影响的索引条目和计数，保留手工说明；仅在领域分布、主要结论或近期重要事件变化时更新 overview，不为微小修改全量重写导航。然后执行：

```bash
"<PYTHON>" "<SKILL_DIR>/scripts/lint_wiki.py" "<KB_DIR>" \
    --lint-files wiki/summaries/<本次变更页>.md wiki/concepts/<受影响页>.md \
    --fail-on error
```

- 文件清单使用知识库相对路径，覆盖本次新增、修改的 wiki 页面，以及全局引用搜索发现的受影响页面；修改过的 overview 也应列入。index 始终检查，无需重复列出。
- 删除或重命名后只列出现存页面，并包含引用旧路径或旧锚点的页面。无法确定影响范围时，改用目录检查或全库检查。
- 检查保持只读，不自动追加 `--fix`。严重问题返回 1，Agent 核对后在本次授权范围内修正并重查；无法修正或运行失败时，报告已写入文件和未解决问题，记录未完成状态。
- 返回 0 后追加本次 workflow 的完成日志；中等和轻微问题仍需在结果中说明。该检查验证结构、链接和索引，不证明知识论断正确。
- 一次 workflow 中相互依赖的变更只追加一条汇总日志。未通过且无法完成修正时记录未完成状态；日志追加失败时报告已写入文件，不声明事务完整成功。
- 写后检查只覆盖本次范围，不额外触发 lint 策略中的全库语义巡检。
- ingest 的主题检查与增量复核是编译流程的一部分，按 `references/synthesis-policy.md` 在本节之前完成。lint 通过不能替代提炼完成标准，未完成检查需如实记录。
- `lint --fix` 自身按现有专用入口记录修复及未解决问题，不递归触发另一次写后流程。

## 清理内容

先全局搜索引用，给出影响范围报告，逐项列明目标路径和关联页面。删除、重命名或批量改链接的授权边界见 `references/guardrails.md`。

用户批准仅适用于报告中的确切目标，新增目标须重新报告并获准。获准后删除文件、清理残留引用，再执行共用写入收尾。
