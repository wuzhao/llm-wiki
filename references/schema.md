# Schema

## 单一事实来源

`references/schema.json` 是目录、页面类型、index 分区、链接根目录、关键小节和运行阈值的唯一规范来源。

- Agent 初始化或手工前置检查时读取该文件，配套 CLI 通过 `scripts/wiki_config.py` 读取并校验；同次调用可复用结果。
- README 和策略文件只解释字段语义，不维护另一套规范值。
- 模板为生成内容而物化必要的路径和 `type`，自动化测试负责校验其与 schema 一致。

## 配置字段

- `schema_version`：schema 版本。
- `okf_version`：wiki bundle 使用的 OKF 版本。
- `paths`：知识库标准路径。
- `required_paths`：非 init workflow 的前置必需结构。
- `document_types`：文件路径到 OKF `type` 的映射。
- `index_sections`：内容目录到 index 分区的映射。
- `link_roots`：允许知识链接指向的目录范围；嵌套目录按最长路径前缀识别归属。
- `required_sections`：页面类型必须包含的关键小节。
- `limits`：页面体积、单批查询页数、搜索片段长度 `max_search_snippet_chars`、lint 批次、陈旧性复核阈值，以及摄入的 `max_source_bytes` 和 `url_timeout_seconds`。采集字节数和解码后的 UTF-8 正文均受素材大小限制。

实体与概念只要求保留来源小节，相关概念、示例和应用场景按实际内容添加。不设置正文最少字数，完整短页与空正文分别处理。

## 路径职责

- `raw`：原始素材层，包含素材正文与附件；素材页在摄入与重新摄入时只追加，历史正文始终只读，显式 `lint --fix` 仅可补齐可确定的 frontmatter 字段。
- `assets`：位于 `raw/assets/` 的网页原始响应、图片、PDF、截图等附件；不参与素材页解析、版本识别或 frontmatter 修复，仍作为链接目标和快照校验对象。
- `summaries`：对应 raw 素材的摘要页。
- `entities`：项目、工具、组织、人物等实体页。
- `concepts`：术语、方法、原理等概念页。
- `analyses`：query 的归档输出。
- `hubs`：主题聚合与结构化导航页。
- `logs`：append-only 操作日志。
- `index`：全局内容索引。
- `overview`：知识库概览。

## 命名规范

- 文件名优先使用 `kebab-case`。
- 分析页使用 `YYYYMMDD - <topic>.md`。
- 中文术语可以保留中文文件名。
- 同名冲突使用从 `-2` 开始的数字后缀。

## 链接规范

- 标准 Markdown 相对链接以当前文件目录为基准，以 `/` 开头时以知识库根目录为基准。
- Wiki 页面中的 Wikilink 默认以 `wiki/` 为根；指向原始素材或附件时写出完整的 `raw/` 或 `raw/assets/` 前缀。
- 页面身份使用知识库相对完整路径，不使用 basename 代替路径。
- 失效链接的同名候选只在原链接意图指向的 `link_roots` 范围内查找，不跨素材正文、附件与 wiki 猜测；`raw/assets/` 中的文件优先归属附件范围，不同时作为 raw 素材页候选。
- 省略目录的 basename 链接仅在同一链接根目录内唯一匹配时有效。
- index、overview、logs 和页面自链接不计入孤儿页的知识入链。

## Frontmatter

Frontmatter 规范只在 `okf-frontmatter.md` 定义，路径到 `type` 的映射只在 `schema.json` 定义。

## 一致性要求

修改目录、类型、关键小节或阈值时，先修改 `schema.json`，然后运行自动化测试验证脚本、模板和文档没有残留旧值。

加载时必须校验脚本需要的全部路径键与阈值键、配置版本、目录到类型及索引分区的映射。raw 与 wiki 根目录不可相互嵌套，assets 必须位于 raw 内。配置缺项时应在读取或修改知识文件前报错。

当前 CLI 统一读取技能内置 schema，不读取知识库内同名文件。独立 schema 与已有知识库的目录迁移尚未提供，不能通过直接修改配置自动迁移页面。

旧知识库的顶层 `assets/` 需要单独迁移到 `raw/assets/`，并同步更新 `source_snapshot`、正文链接及知识库 `AGENTS.md`；仅移动目录会造成引用失效。升级默认配置不自动移动已有文件。
