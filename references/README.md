# LLM Wiki references

这个目录存放 LLM Wiki 的共享规范。

任务路由和核心护栏以根目录 `SKILL.md` 为准，本文件只说明维护分工。

## 规则归属

- `schema.json`：目录、页面类型、索引分区、必需小节与阈值；`schema.md` 解释字段含义。
- `okf-frontmatter.md`：字段语义与各类页面 profile。
- `guardrails.md`：授权边界与环境异常处理；`preflight.md`：结构校验与参数解析。
- 各 workflow 策略：只描述该任务特有的行为。
- `lint-policy.md` 的「写后检查」：所有写入任务共用的索引维护、验证、修正和事务日志。
- `provenance-policy.md`：论断证据与来源变化的传播协议；`query-policy.md`：搜索和分批读取。
- `scalability-policy.md`：出现容量问题时的治理选择；`golden-sample.md`：发布前回归。

模板只物化产物结构；知识库 AGENTS 保留独立使用时必要的简短底线，详细流程引用对应策略，不复制另一份规范。
