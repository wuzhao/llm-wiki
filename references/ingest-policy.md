# Ingest Policy

摄入目标：把来源素材编译为可追溯的结构化知识。

## 输入类型

支持三类输入：

- 文件路径
- 粘贴文本
- URL

非文本附件（图片、PDF、截图等）统一保存到原始素材层的 `raw/assets/` 下，按月命名子目录（例如 `raw/assets/YYYYMM/`）。附件保留原始文件，不作为 raw 素材页解析或修复。

URL 获取失败时：

- 明确告知失败原因
- 请求用户粘贴正文
- 不做空写入

## 原始素材写入（由脚本托管）

摄入时所有原始素材的物理写入动作，**严禁 Agent 手动执行**，必须调用基础设施 `scripts/ingest_raw.py` 完成。后续仅维护 frontmatter 时遵循 `lint-policy.md`，不能改写既有正文。

**脚本调用规范：**

```bash
# 场景 1：直接投喂 URL
"<PYTHON>" "<SKILL_DIR>/scripts/ingest_raw.py" "<KB_DIR>" --url "https://..." [--title "可选覆盖标题"]

# 场景 2：从本地文件中导入
"<PYTHON>" "<SKILL_DIR>/scripts/ingest_raw.py" "<KB_DIR>" --file "/path/to/file.md"

# 场景 3：直接写入纯文本素材
"<PYTHON>" "<SKILL_DIR>/scripts/ingest_raw.py" "<KB_DIR>" --text "大段文本内容..." --title "必填标题"
```

**参数说明与 Agent 注意事项：**

- 所有原始素材固定写入 `<KB_DIR>/raw/`，不支持自定义 raw 写入目录。
- `--url`、`--file`、`--text` 互斥，一次调用只允许一种来源。
- 脚本执行共享 preflight，知识库必须先完成初始化。空正文、空标题（文本输入）、读取失败和结构异常均不产生写入。
- URL 超时与素材大小限制读取 `schema.json`；URL 支持 HTTP、HTTPS 和 data URI，二进制响应明确报错，附件仍保存到 `raw/assets/`。
- 文本按响应声明的编码解码；HTML 在响应未声明编码时尝试读取 charset，保留标题、链接、图片地址、列表、代码块与普通表格。带合并单元格或复杂内容的表格保留为 HTML。无法解码时报告失败，不忽略字节继续写入。
- URL 的原始响应字节保存到 `raw/assets/YYYYMM/`，raw 素材页记录快照路径、SHA256、媒体类型、最终地址及提取器版本；当前不自动下载网页图片或提取二进制附件。
- 粘贴文本的明确版本更新可传 `--source-id <既有来源身份>`，文件与 URL 的身份由脚本确定，不需要手工传入。

该脚本会自动完成以下确定性操作：

1. 以排他创建方式新建 `raw/` 文件并处理同名冲突（如追加 `-2`），并发写入也不覆盖已有版本。
2. 从 URL 或正文中提取基础文本与标题。
3. 按 raw profile 生成可解析 Frontmatter，包含 `type: source-material`、采集 `timestamp` 和可用的来源字段；来源地址统一写入 `resource`。
4. 本地文件投喂时，记录 `source_file_path` 与 `source_file_sha256`，供后续 `lint` 发现原始文件在投喂后是否发生变化。
5. 在标准输出（stdout）返回生成的**绝对文件路径**，供 Agent 接管后续流程。
6. 记录稳定的 `source_id`、递增的 `source_version`、前一版本 `supersedes`，以及正文与内容指纹。未提供显式身份的粘贴文本按内容识别来源。

raw 写入工具不单独追加 workflow 日志；完整事务由 Agent 按 `lint-policy.md` 收尾。写入失败时不输出成功路径。

同一来源的正文和采集内容均未变化时，脚本在 stderr 提醒「已有相同内容 ingested」，stdout 返回既有 raw 路径，不新增文件。Agent 应读取该提醒，不能仅凭返回路径就宣称完成了一次新摄入。

来源内容变化、回滚到历史内容，或同文来自另一出处时，保留新的来源快照并提示已有同文。raw 的元数据与正文维护边界见 `okf-frontmatter.md`。

## 编译到 wiki

- 新素材建立可回查的来源摘要，或补充已有对应摘要的来源记录。
- 已有实体与概念按实际信息增量维护，可以只补充来源、适用条件或链接；不强制新增概念或大改正文。
- 重复输入且已有摘要完整时，只提醒既有 raw 与摘要路径，不重复编译、不刷新页面时间，也不追加一次虚假的新摄入完成日志。
- 重复输入但此前只保存了 raw、尚未完成编译时，使用既有 raw 补全摘要和后续流程，明确说明是在补完已有素材。
- 页面围绕明确主题；完整短页无需扩写，模板中的示例、应用和关系小节按实际信息选择，不能补造内容或链接来填满模板。

模板见：

- `templates/source-template.md`
- `templates/entity-template.md`
- `templates/concept-template.md`

## 合并规则

- 语义相同主题：优先更新已有页。
- 明显新概念：创建新页。
- 同一素材可同时触发「更新旧页 + 新建新页」。
- 影响分析、逐条证据引用与传播完成标准按 `provenance-policy.md` 执行。

当前事实、历史状态与冲突的区分统一按 `provenance-policy.md`；需要冲突片段时使用 `templates/conflict-note-template.md`。

## 关系维护

完成主写入后再做：

- 对有明确语义关系且能改善导航的已有页面补充链接或必要的反向链接。
- 孤儿页优先报告，确有关系时才补链；不为消除告警制造关系。
- 术语按需加链接或解释，无需在每次出现时重复标记。

## 索引/概览/日志

按 `lint-policy.md` 的「写后检查」统一维护索引、必要的概览、验证和事务日志，不全量重建导航或覆盖手工说明。

## 长文档防失控（ingest 阶段）

- 写后 lint 报告单页体积超过阈值时，再按 `scalability-policy.md` 给出治理建议。
- 默认不自动拆分页面，避免静默结构改写。

日志格式示例：

```markdown
## [YYYY-MM-DD] ingest | <素材标题>
- Raw: raw/<file>.md
- Source: wiki/summaries/<file>.md
- Created: <本次实际新建的页面，没有则省略>
- Updated: <本次实际更新的页面，没有则省略>
- Unchanged: <已核对且无需正文改动的页面及原因>
- Pending-review: <仍需复核的页面及原因，没有则省略>
```
