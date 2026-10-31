# 维护验证历史

本文件保留以往版本的验证记录，不代表当前版本已通过；当前验收入口见 [Golden Sample](golden-sample.md)。

## 维护验证记录：2026-09-27

- 全量 unittest 回归通过，覆盖误写防护、局部图关系、来源引用、URL 处理、并发创建及写入失败。
- 临时知识库使用虚构 AtlasDB 实验素材完成 init、文件摄入、本地 HTTP URL 摄入及粘贴文本摄入，生成三份来源摘要、实体页和概念页。
- 两份实验给出相反性能结论，页面保留双方观点与来源。lint 无严重问题，仅报告预期的未解决冲突。
- 查询明确说明证据不足；探索建议补充实验条件、复核日期和独立实验，均保持只读。
- 对完整知识库执行 `--fix` 不改变内容页，仅追加操作日志；修改外部原始文件后，lint 正确提示来源变更。
- GitHub Actions 配置已加入；远端矩阵的实际执行结果需在推送后查看。

## 维护验证记录：2026-10-17

- 全量 unittest 回归 67 项通过；新增 raw 正文字节保护、来源元数据保留、按文件写后检查与错误参数不落盘的回归。
- 临时知识库完成初始化、本地文件、本地 HTTP URL 与粘贴文本摄入，生成三份来源摘要、实体页和概念页，冲突双方及来源保持可见。
- 故意写入不存在的概念链接，写后检查返回 1 且不改文件；核对修正后返回 0，再追加完成日志。
- 查询保留冲突与证据不足结论，探索建议补充独立实验，二者保持只读。
- 完整知识库执行 `--fix` 后 raw 文件逐字节不变，wiki 内容页不变，日志仅追加；CRLF 正文与元数据补齐同时发生的场景由自动化测试覆盖。

## 维护验证记录：2026-10-18

- 全量 unittest 功能回归 91 项通过，覆盖网页结构与原始响应快照、相同输入和并发重试、来源版本、证据链、依赖传播、全文搜索与分页。
- 临时知识库完成初始化、本地文件、本地 HTTP URL 与粘贴文本摄入；网页代码的缩进及连续空行、表格单元格和原始响应均保留。
- 重复本地文件摄入返回既有 raw 路径并提醒已摄入，知识库文件不变；查询通过别名与正文搜索分五批定位候选，保持只读。
- 修订本地素材后创建新版本，历史 raw 不再误报需重新投喂；影响清单覆盖来源摘要、实体及归档分析，归档分析保持历史正文并报告待复核。
- 虚构实验的冲突双方与来源保留；查询说明来源修订及证据分歧，探索建议独立复核。全库 `--fix` 不改变已保存 raw 或归档分析。
- 上述为现有 Golden Sample 与功能回归的延续，不新增知识质量评分或评测框架。

### 同日规则收敛验证

- 全量 unittest 功能回归 99 项通过，新增短页、脚注定义、索引一致性、读取复用与搜索会话刷新场景。
- 临时知识库完成初始化、三类摄入、冲突保留、写后检查失败与修正、重复输入、五批只读查询、归档及来源更新；历史 raw 和归档正文保持不变，完整库安全修复仅追加日志。

### 同日目录扫描与引用式索引修复验证

- 全量 unittest 功能回归 106 项通过，覆盖目录扫描不同阶段失败、零命中时的覆盖错误、修复不落盘，以及引用式链接的分区、重复次数和使用行号。
- Golden Sample 使用引用式索引完成三类摄入、冲突保留、写后检查、重复输入、分批查询、归档和来源更新；历史 raw 与归档保持不变，安全修复仅追加日志。

### 同日工作区与知识库路径验证

- 全量 unittest 功能回归 107 项通过；新增工作区局部技能安装、含中文与空格的目录、切换到其他知识库目录及依赖缺失诊断场景。
- 摄入、搜索、影响分析和安全修复始终使用显式目标与技能内置资源；目标库内的同名 schema 不覆盖技能配置，技能目录、另一个知识库和工作区原有 AGENTS 均保持不变。
- Golden Sample 完成初始化、三类摄入、冲突保留、写后检查修正、重复输入、分批只读查询与探索、影响分析及安全修复；原始素材不变，修复仅追加本次日志。

### 同日附件目录收敛验证

- 默认附件目录调整为 `raw/assets/`；初始化、URL 原始响应快照与模板使用新路径，链接候选按最长路径前缀区分素材正文与附件。
- 使用项目本地 `.venv` 执行全量 unittest，113 项通过；新增附件目录约束、目标去重、跨范围候选隔离，以及 Markdown 附件不参与摄入版本识别、来源图或 lint 修复的回归。
- 临时知识库完成初始化、本地文件、本地 HTTP URL 与粘贴文本摄入、冲突保留、写后检查失败与修正、重复输入及五批只读查询与探索；原始响应字节和指纹保持一致。
- 来源更新后的影响清单覆盖归档分析，历史 raw 与归档正文保持不变；全库安全修复只追加操作日志，Markdown 附件不被解析或改写。
- 此次只调整项目默认配置，已有知识库的顶层附件与引用需要单独迁移，不自动移动文件。

### 同日来源地址字段收敛验证

- 新摄入的 URL 只写 `resource`，`source_url` 作为旧 raw 扩展字段兼容读取；URL 来源身份优先使用 `resource`，历史文件不批量重写。
- 全量 unittest 116 项通过，覆盖仅含旧字段与双字段的重复摄入、地址优先级、新旧版本的依赖传播，以及字段冲突仅报告且不改写来源地址。
- 临时知识库完成初始化、三类摄入、冲突保留、写后检查失败与修正、重复输入、五批只读查询与探索、来源更新及影响分析；历史 raw、原始响应和归档正文保持不变，完整库安全修复只追加日志。

## 维护验证记录：2026-10-21

- 使用项目现有 `.venv` 执行全量 unittest，131 项通过；新增提炼回归 15 项，覆盖历史回扫、跨进程续扫、显式提前整理、周期去重、连续版本、暂缓候选、状态异常与覆盖缺口。
- 临时知识库完成初始化、本地文件、本地 HTTP URL 与粘贴文本摄入，建立三份摘要、一个实体页、两个概念页和一份显式归档分析。单篇充分说明当次成页；首次仅提及的概念先保留候选，后续素材补足定义与条件后建页并移除候选。
- 同义名称复用已有页，冲突保留双方与来源；重复输入无写入，只读检索不变更文件，显式整理可在周期前触发。历史回扫的分批恢复由独立进程回归覆盖。
- 来源修订后的影响清单包含归档分析，历史 raw 与归档正文保持不变；全库安全修复只追加本次日志，不补造提炼记录或知识页。
- schema、SKILL frontmatter 与护栏数量、页面模板类型、Markdown 结尾及本地文档链接检查通过，skill-creator 的 quick_validate 通过。建页语义按 Agent 场景核对，工具只负责只读规划与记录校验。

## 维护验证记录：2026-10-22

- 素材新增、来源更新、重复复用与未完成处理的补完统一使用 ingest；更新协议、提炼检查和写后收尾保持可达，新事务日志统一命名，历史日志不重写。
- 使用项目现有 `.venv` 执行全量 unittest，131 项通过；底层摄入工具复用既有入口，不新增重建模式或 CLI 参数。
- 临时知识库完成初始化、文件与本地 HTTP URL 及文本摄入、知识提炼、冲突保留、显式归档和来源更新。更新分支维护当前摘要与概念页，历史 raw 和归档分析保持不变，归档依赖变化继续报告待复核；再次输入复用当前 raw。
- 单独核对统一入口的文本身份分支：同标题不同正文保持不同来源，显式既有 `source_id` 追加版本，相同输入无写入，同文来自另一文件时保留独立出处。
- P0 一致性检查、Markdown 结尾与本地链接检查、skill-creator 的 quick_validate 和 git diff 空白检查通过；文档、任务路由与测试名称统一使用 ingest。

## 维护验证记录：2026-10-29

- 完成本次九项优化：代码注释边界、版本单一来源、bundle 根链接、增量提炼与检查点、外部来源分级、附件导入、正式初始化入口、lint 阶段分离及文档与 CI 一致性检查。
- 项目 `.venv` 中全量 unittest 149 项通过。新增用例验证真实附件字节、失败不落盘、初始化失败保护、版本自动渲染、增量范围、旧检查点兼容、候选重新触发和扫描后编辑保护。
- 临时知识库完成初始化、本地文件、本地 HTTP 网页与粘贴文本摄入；单篇充分信息形成实体与概念，首次仅提及的失效令牌在后续证据补足后成页，同义名称复用，实验冲突保留双方。
- 查询通过别名分页找到证据，探索指出复现实验缺口；来源修订传播到当前页面，旧 raw 与归档正文不变，重复输入无写入。显式全库整理完成后，安全修复只追加日志。
- `scripts/check_project.py`、skill-creator 的 quick_validate 与 `git diff --check` 通过。CI 已配置相同的项目一致性检查；远端矩阵需在推送后确认。
- 范围限制：局部 lint 仍读取全库关系，候选名称匹配仍需 Agent 补充语义检索；未执行真实大库性能基准。未提交或推送。

本次变更文件清单（包括新增文件）：

- .github：`.github/workflows/tests.yml`。
- 根目录：`AGENTS.md`、`README.en.md`、`README.md`、`SKILL.md`。
- references：`references/README.md`、`references/golden-sample.md`、`references/ingest-policy.md`、`references/init-files.md`、`references/lint-policy.md`、`references/maintenance-history.md`、`references/okf-frontmatter.md`、`references/scalability-policy.md`、`references/schema.md`、`references/synthesis-policy.md`。
- scripts：`scripts/check_project.py`、`scripts/ingest_attachment.py`、`scripts/ingest_raw.py`、`scripts/init_wiki.py`、`scripts/lint_wiki.py`、`scripts/markdown_links.py`、`scripts/synthesis_wiki.py`、`scripts/wiki_config.py`、`scripts/wiki_io.py`、`scripts/wiki_links.py`、`scripts/wiki_lint_report.py`、`scripts/wiki_provenance.py`、`scripts/wiki_scan.py`。
- templates：`templates/AGENTS-template.md`、`templates/archive-template.md`、`templates/concept-template.md`、`templates/entity-template.md`、`templates/hub-template.md`、`templates/log-template.md`、`templates/overview-template.md`、`templates/source-template.md`。
- tests：`tests/kb_fixture.py`、`tests/test_lint_wiki.py`、`tests/test_project_checks.py`、`tests/test_provenance_search.py`、`tests/test_schema.py`、`tests/test_synthesis.py`、`tests/test_wiki_io.py`、`tests/test_workflow_tools.py`。

## 发布前验证：2026-10-30

- 版本从 `0.2.0` 升至 `0.2.1`，模板通过统一渲染读取新版本，无需同步版本常量。
- 使用项目 `.venv` 重新执行全量 unittest，149 项通过；项目一致性检查、skill-creator 的 quick_validate 与 `git diff --check` 通过。
- 临时知识库重新完成三类摄入、单篇建页、跨篇候选补足、冲突保留、只读分页查询、来源更新与归档保护、显式全库整理；重复输入无写入，安全修复仅追加日志。
- 本记录对应当前分支提交前的本地验证，远端 macOS/Linux 测试矩阵结果需在推送后确认。

## 发布前验证：2026-10-31

- 版本从 `0.2.2` 升至 `0.2.3`，模板继续通过统一渲染读取版本。
- 数值核验支持带空格的复合数量和完整字面回查，跳过无明确数量的模糊量词；保留符号、单位、范围和限定词，不能跨脚注、换行或不同来源拼接数量，百分率与千分率分别核验。
- 明确标注的直接引文继续逐字回查；术语及强调引号不再自动视为直接引文。链接元数据、脚注标识和导航链接标题不作为数值主张，正文及导航说明中的数值继续检查。
- 冲突候选限定为知识页中的来源或证据矛盾，排除战争、并发和否定语句的误判；正式记录的未解决冲突继续报告。
- 使用项目 `.venv` 执行全量 unittest，166 项通过；项目一致性检查及 `git diff --check` 通过。
- Golden Sample 临时知识库完成初始化、三类摄入、单篇建页、跨篇候选补足、同义复用、冲突保留、只读分页查询与探索、来源更新及归档保护、显式全库整理；重复输入无写入，安全修复仅追加日志。
- 本地验证无失败项；真实知识库保持只读，证据缺口与来源维护事项仍需逐项复核，远端测试矩阵结果需在推送后确认。

### 同日数值语境与日期匹配发布验证

- 版本从 `0.2.3` 升至 `0.2.4`，模板继续通过统一渲染读取版本。
- 数值候选排除明确的词语和指代表达，保留实际人数、次数与金额；完整中英文日期支持等值匹配，并保留日期区间、限定词及非法或歧义写法的边界。
- 同一份 144 页快照只读对照中，告警从 291 条降至 270 条；按页面、段落和问题类型比较消除 21 条，无新增告警位置。原知识库 Markdown 内容指纹保持一致。
- 使用项目 `.venv` 执行全量 unittest，170 项通过；项目一致性检查及 `git diff --check` 通过。
- Golden Sample 临时知识库完成三类摄入、单篇建页、跨篇候选补足、同义复用、冲突保留、只读分页查询与探索、来源更新及归档保护、显式全库整理；重复输入无写入，安全修复仅追加日志。本地验证无失败项，远端测试矩阵结果需在推送后确认。
- 修改文件：`SKILL.md`、`references/provenance-policy.md`、`references/maintenance-history.md`、`scripts/wiki_numbers.py`、`tests/test_numeric_evidence.py`、`tests/test_provenance_search.py`。

### 同日证据诊断与表格引用发布验证

- 版本从 `0.2.4` 升至 `0.2.5`，模板继续通过统一渲染读取版本。
- 证据待复核项展开具体主张、诊断原因与 raw 候选行列及上下文；引用完整性独立展示，缺脚注不表示原文已含该数字。
- 百分率与千分率支持精确比例换算，保留符号、范围和限定词；数值部分相同但单位不同、单位省略及一般推导继续复核，不自动改写事实。
- 表格共享来源采用显式有界范围，行内脚注优先；跨页唯一共同候选汇总回查入口，保留所有影响位置和告警计数。
- 同一份 144 页快照只读对照中，告警仍为 270 条：161 条证据待复核、45 条缺脚注及 64 条其他问题。除标题更名与定位细化外，按页面与问题内容比较无增减；原知识库 Markdown 内容指纹保持一致。
- 使用项目 `.venv` 执行全量 unittest，183 项通过；项目一致性检查与 `git diff --check` 通过。
- Golden Sample 临时知识库完成三类摄入、单篇建页、跨篇候选补足、同义复用、冲突保留、只读分页查询与探索、来源更新及归档保护、显式全库整理；重复输入无写入，安全修复仅追加日志。本地验证无失败项，远端测试矩阵结果需在推送后确认。
- 修改文件：`SKILL.md`、`references/lint-policy.md`、`references/provenance-policy.md`、`references/maintenance-history.md`、`scripts/lint_wiki.py`、`scripts/wiki_evidence.py`、`scripts/wiki_lint_report.py`、`scripts/wiki_numbers.py`、`scripts/wiki_provenance.py`、`tests/test_evidence_diagnostics.py`、`tests/test_provenance_search.py`。
