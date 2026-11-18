# 项目优化实施与验证记录

日期：2026-11-18。基线：`0.2.16`，提交 `e9918f9`。以下四步和性能数据记录前两轮评审后的实现。第三轮修正与复测见[维护验证历史](maintenance-history.md#第三轮优化复核2026-11-18)。

## 已完成变更

第 1 步：复核规则改用规范化 AST 指纹，排除 CLI 入口、日志与模板渲染，继续保护来源、路径、锚点和复核判断。兼容读取已认可的旧协议及 `0.2.16` 新版记录，新版记录仍执行人工确认校验。搜索按命令行参数保留完整短语，统一空白和大小写，修复多词别名扩展及长文本、跨行短语的摘要定位。

第 2 步：抽检业务阈值统一读取 schema，误判百分比校验为 0 至 100 的整数。复核者改为知识库指定角色，核验与过期时间使用待填写占位。日志持锁读取末尾，仅追加所需换行，保留原有内容及额外空行。

第 3 步：共用写入收尾的唯一定义迁入 SKILL；证据分级、复核字段、确认门与抽检集中到复核工作流。保留数值定位的能力边界，移除日常来源策略中的词法特例长清单；补齐回归矩阵、工具入口、短语语义、路径术语和中文语言说明。

第 4 步：同次 lint 按完整文本缓存 frontmatter 解析结果，返回独立 metadata 副本。页面内容变化时重新解析，解析错误同样保留，不写持久缓存。保留原有安全修复、行号及快照原文校验。

## 验证结果

- 全套 280 项单元测试通过；项目一致性检查与 Git 空白检查通过。
- 专项验证覆盖短语、别名、跨行摘要、配置边界、模板占位、日志 LF/CRLF、缓存隔离及规则指纹依赖边界。
- CLI 往返验证：从基线工具实际导出的 `0.2.16` 记录可被新工具复用；旧协议使用合成记录验证。两类记录均在来源变更后失效，读取过程不修改输入记录或知识库。
- 本机已有知识库按 `--lint-dirs wiki` 只读对比：135 页，374 条告警（严重 0、中等 322、轻微 52），520 个证据主张。前后完整报告仅规则绑定的复核 ID 不同，诊断正文、位置与计数一致。
- 未加载真实复核 JSON，因此本机对比不证明原先另一设备上的「228 条存量全部降蓝、待复核为 0」。该项仍需对应知识库版本及原始复核记录。

## 性能测量

固定临时知识库包含 200 个 raw 页面及 200 个来源摘要，另有初始化系统页面。基线与新实现各运行三次独立 lint 进程，取中位数，输入文件哈希前后保持一致。

| 实现 | 第一次耗时（秒） | 第二次耗时（秒） | 第三次耗时（秒） | 中位数（秒） |
| ---- | ---------------: | ---------------: | ---------------: | -----------: |
| 基线 | 2.524 | 2.460 | 2.477 | 2.477 |
| 本次 | 1.711 | 1.690 | 1.710 | 1.710 |

该样本中耗时中位数减少约 31%。完整报告除规则绑定的复核 ID 外一致。未修改页面的 frontmatter 解析专项验证从原先 6 次降为 1 次；此计数不包含元数据证据入口另行执行的结构定位。性能结果仅代表本机这份合成样本，不承诺其他知识库取得相同比例。

## 兼容边界

- 兼容映射只登记本次验证过的规则版本；新规则没有兼容映射时允许保守失效。
- 前两轮实现将混合职责的 lint 函数保守纳入指纹。第三轮已将证据编排独立到来源检查模块。未来新增证据依赖或相关配置时须复核保护范围。
- AST 规范化忽略位置、注释、docstring 和空可选字段；未来 Python 解析器变化仍需实际验证。
- 用户已有知识库、复核文件和本地指定复核者约定没有被迁移或改写。

## 修改文件清单

- [README.en.md](../README.en.md)
- [README.md](../README.md)
- [SKILL.md](../SKILL.md)
- [docs/optimization-validation.md](../docs/optimization-validation.md)
- [references/README.md](../references/README.md)
- [references/explore-policy.md](../references/explore-policy.md)
- [references/golden-sample.md](../references/golden-sample.md)
- [references/ingest-policy.md](../references/ingest-policy.md)
- [references/init-files.md](../references/init-files.md)
- [references/lint-policy.md](../references/lint-policy.md)
- [references/preflight.md](../references/preflight.md)
- [references/provenance-policy.md](../references/provenance-policy.md)
- [references/query-policy.md](../references/query-policy.md)
- [references/review-compatibility.json](../references/review-compatibility.json)
- [references/review-workflow.md](../references/review-workflow.md)
- [references/scalability-policy.md](../references/scalability-policy.md)
- [references/schema.json](../references/schema.json)
- [references/schema.md](../references/schema.md)
- [references/synthesis-policy.md](../references/synthesis-policy.md)
- [scripts/lint_wiki.py](../scripts/lint_wiki.py)
- [scripts/review_quality.py](../scripts/review_quality.py)
- [scripts/search_wiki.py](../scripts/search_wiki.py)
- [scripts/wiki_config.py](../scripts/wiki_config.py)
- [scripts/wiki_reviews.py](../scripts/wiki_reviews.py)
- [scripts/wiki_rule_fingerprint.py](../scripts/wiki_rule_fingerprint.py)
- [scripts/wiki_scan.py](../scripts/wiki_scan.py)
- [scripts/wiki_sources.py](../scripts/wiki_sources.py)
- [templates/AGENTS-template.md](../templates/AGENTS-template.md)
- [templates/archive-template.md](../templates/archive-template.md)
- [templates/concept-template.md](../templates/concept-template.md)
- [templates/entity-template.md](../templates/entity-template.md)
- [templates/overview-template.md](../templates/overview-template.md)
- [templates/source-template.md](../templates/source-template.md)
- [tests/test_maintenance_details.py](../tests/test_maintenance_details.py)
- [tests/test_parse_cache.py](../tests/test_parse_cache.py)
- [tests/test_provenance_search.py](../tests/test_provenance_search.py)
- [tests/test_review_policy.py](../tests/test_review_policy.py)
- [tests/test_rule_fingerprint.py](../tests/test_rule_fingerprint.py)
