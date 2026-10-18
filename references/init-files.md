# Init Files

初始化时仅在空目录执行。若任一目标目录或关键文件已存在，则停止并保留原文件。

按 `preflight.md` 确定 `SKILL_DIR` 与 `KB_DIR`，从技能目录读取模板，向独立的知识库目录生成文件；初始化不复制技能源码，也不改写工作区或技能项目原有的 `AGENTS.md`。

## 初始化结构

- 读取 `schema.json` 的 `required_paths` 和 `paths` 创建目录及基础文件。
- 不在本文件重复维护目录列表。
- 所有时间占位符使用初始化时的 UTC 时间替换。

## 基础文件

- 将 `templates/AGENTS-template.md` 渲染为知识库根目录的 `AGENTS.md`。
- 将 `templates/index-template.md` 中的 Markdown 代码块渲染为 `wiki/index.md`。
- 将 `templates/overview-template.md` 中的 Markdown 代码块渲染为 `wiki/overview.md`。
- 将 `templates/log-template.md` 中的 Markdown 代码块渲染为当月的 `wiki/logs/YYYYMM.md`。

模板是基础文件内容的唯一来源，初始化策略不得内联另一份模板。

## 初始化日志

基础文件创建后，先按 `lint-policy.md` 的「写后检查」验证 index 与 overview；通过后追加 init 完成记录。

当月日志的首条记录使用：

```markdown
## [YYYY-MM-DD] init | 初始化知识库

- Created: AGENTS.md, wiki/index.md, wiki/logs/YYYYMM.md, wiki/overview.md
```

## 初始化后动作

- 输出已创建文件列表。
- 提示下一步执行 `ingest`。
