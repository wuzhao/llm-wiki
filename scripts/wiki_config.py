#!/usr/bin/env python3
import json
import re
from pathlib import Path, PurePosixPath


class SchemaError(ValueError):
    pass


class TemplateError(ValueError):
    pass


MARKDOWN_TEMPLATE_RE = re.compile(r"```markdown\r?\n(?P<body>.*?)\r?\n```", re.DOTALL)
REQUIRED_PATH_KEYS = {
    "raw", "assets", "wiki", "summaries", "entities", "concepts", "analyses",
    "hubs", "logs", "index", "overview",
}
REQUIRED_LIMIT_KEYS = {
    "max_page_lines", "max_page_bytes", "max_page_h2",
    "max_query_read_pages", "max_search_snippet_chars", "max_lint_batch_pages", "max_log_bytes", "review_after_days",
    "max_source_bytes", "url_timeout_seconds",
}


def bundled_schema_path():
    return Path(__file__).resolve().parent.parent / "references" / "schema.json"


def bundled_templates_path():
    return Path(__file__).resolve().parent.parent / "templates"


def load_markdown_template(template_name):
    root = bundled_templates_path().resolve()
    path = (root / template_name).resolve()
    if path.parent != root:
        raise TemplateError(f"模板路径无效: {template_name}")
    try:
        wrapper = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateError(f"无法读取模板: {path} ({exc})") from exc
    match = MARKDOWN_TEMPLATE_RE.search(wrapper)
    if not match:
        raise TemplateError(f"模板缺少 markdown 代码块: {path}")
    return match.group("body").rstrip() + "\n"


def _validate_relative_path(value, label):
    if not isinstance(value, str) or not value.strip():
        raise SchemaError(f"{label} 必须是非空字符串")
    path = PurePosixPath(value)
    if (path.is_absolute() or ".." in path.parts or not path.parts
            or "\\" in value or path.as_posix() != value.rstrip("/")):
        raise SchemaError(f"{label} 必须是知识库内相对路径: {value}")


def load_schema(schema_path=None):
    path = Path(schema_path).resolve() if schema_path else bundled_schema_path()
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SchemaError(f"无法读取 schema: {path} ({exc})") from exc

    if not isinstance(schema, dict):
        raise SchemaError("schema 顶层必须是对象")

    required_keys = {
        "schema_version",
        "okf_version",
        "paths",
        "required_paths",
        "document_types",
        "index_sections",
        "link_roots",
        "required_sections",
        "limits",
    }
    missing = sorted(required_keys - set(schema))
    if missing:
        raise SchemaError(f"schema 缺少字段: {', '.join(missing)}")

    if not isinstance(schema["schema_version"], int) or isinstance(schema["schema_version"], bool):
        raise SchemaError("schema_version 必须是整数")
    if schema["schema_version"] != 1:
        raise SchemaError("不支持此 schema_version，请先迁移配置")
    if not isinstance(schema["okf_version"], str) or not re.fullmatch(r"\d+\.\d+", schema["okf_version"]):
        raise SchemaError("okf_version 必须是 major.minor 字符串")

    paths = schema["paths"]
    if not isinstance(paths, dict) or not paths:
        raise SchemaError("paths 必须是非空对象")
    if REQUIRED_PATH_KEYS - paths.keys():
        raise SchemaError("paths 缺少字段: " + ", ".join(sorted(REQUIRED_PATH_KEYS - paths.keys())))
    for key, value in paths.items():
        _validate_relative_path(value, f"paths.{key}")
        if value.endswith("/"):
            raise SchemaError(f"paths.{key} 不应以 / 结尾")
    if len(set(paths.values())) != len(paths):
        raise SchemaError("paths 中存在重复目标路径")
    for key in REQUIRED_PATH_KEYS - {"raw", "assets", "wiki"}:
        if not paths[key].startswith(paths["wiki"] + "/"):
            raise SchemaError(f"paths.{key} 必须位于 wiki 内")
    raw, assets, wiki = (PurePosixPath(paths[key]) for key in ("raw", "assets", "wiki"))
    if raw in wiki.parents or wiki in raw.parents:
        raise SchemaError("raw 与 wiki 根目录不能相互嵌套")
    if raw not in assets.parents:
        raise SchemaError("paths.assets 必须位于 raw 内")

    required_paths = schema["required_paths"]
    if not isinstance(required_paths, list):
        raise SchemaError("required_paths 必须是数组")
    for index, value in enumerate(required_paths):
        _validate_relative_path(value, f"required_paths[{index}]")
    if len(set(required_paths)) != len(required_paths):
        raise SchemaError("required_paths 存在重复项")
    if "AGENTS.md" not in required_paths:
        raise SchemaError("required_paths 缺少 AGENTS.md")
    uncovered = sorted(set(paths.values()) - set(required_paths))
    if uncovered:
        raise SchemaError(f"required_paths 未覆盖 paths: {', '.join(uncovered)}")

    document_types = schema["document_types"]
    if not isinstance(document_types, dict):
        raise SchemaError("document_types 必须是对象")
    for section in ("exact", "prefix"):
        mapping = document_types.get(section)
        if not isinstance(mapping, dict):
            raise SchemaError(f"document_types.{section} 必须是对象")
        for path, document_type in mapping.items():
            _validate_relative_path(path, f"document_types.{section} 路径")
            if section == "prefix" and (not path.endswith("/") or path[:-1] not in paths.values()):
                raise SchemaError(f"document_types.prefix 必须引用 paths 目录并以 / 结尾: {path}")
            if section == "exact" and path not in paths.values():
                raise SchemaError(f"document_types.exact 未引用 paths: {path}")
            if not isinstance(document_type, str) or not document_type.strip():
                raise SchemaError(f"document_types.{section} 的 type 必须是非空字符串")

    for key in ("index_sections", "required_sections"):
        if not isinstance(schema[key], dict):
            raise SchemaError(f"{key} 必须是对象")
    for prefix, section in schema["index_sections"].items():
        if (prefix not in document_types["prefix"] or not prefix.startswith(paths["wiki"] + "/")
                or prefix == paths["logs"] + "/" or not isinstance(section, str) or not section.strip()):
            raise SchemaError(f"index_sections 映射无效: {prefix}")
    for key in ("raw", "summaries", "entities", "concepts", "analyses", "hubs", "logs"):
        if paths[key] + "/" not in document_types["prefix"]:
            raise SchemaError(f"document_types 缺少 paths.{key} 的映射")
    if paths["overview"] not in document_types["exact"]:
        raise SchemaError("document_types 缺少 overview 的映射")
    for key in ("summaries", "entities", "concepts", "analyses", "hubs"):
        if paths[key] + "/" not in schema["index_sections"]:
            raise SchemaError(f"index_sections 缺少 paths.{key} 的映射")

    link_roots = schema["link_roots"]
    if not isinstance(link_roots, list) or not link_roots:
        raise SchemaError("link_roots 必须是非空数组")
    for index, value in enumerate(link_roots):
        _validate_relative_path(value, f"link_roots[{index}]")
        if value not in paths.values():
            raise SchemaError(f"link_roots 未引用 paths 中的路径: {value}")
    if len(link_roots) != 3 or set(link_roots) != {paths[key] for key in ("raw", "assets", "wiki")}:
        raise SchemaError("link_roots 必须包含 raw、assets 与 wiki 三个链接范围")

    for document_type, sections in schema["required_sections"].items():
        if not isinstance(document_type, str) or not isinstance(sections, list):
            raise SchemaError("required_sections 必须将 type 映射到小节数组")
        if any(not isinstance(section, str) or not section.strip() for section in sections):
            raise SchemaError(f"required_sections.{document_type} 包含无效小节")
        if document_type not in set(document_types["exact"].values()) | set(document_types["prefix"].values()):
            raise SchemaError(f"required_sections 引用了未知 type: {document_type}")

    limits = schema["limits"]
    if not isinstance(limits, dict) or not limits:
        raise SchemaError("limits 必须是非空对象")
    if REQUIRED_LIMIT_KEYS - limits.keys():
        raise SchemaError("limits 缺少字段: " + ", ".join(sorted(REQUIRED_LIMIT_KEYS - limits.keys())))
    invalid_limits = sorted(
        key for key, value in limits.items()
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0
    )
    if invalid_limits:
        raise SchemaError(f"limits 必须是正整数: {', '.join(invalid_limits)}")
    return schema


def resolve_within(base_dir, relative_path):
    base = Path(base_dir).resolve()
    candidate = (base / relative_path).resolve()
    if candidate != base and base not in candidate.parents:
        raise SchemaError(f"路径越出知识库: {relative_path}")
    return candidate


def validate_structure(kb_dir, schema):
    """Validate path kinds as well as containment, without creating anything."""
    invalid = []
    file_paths = {"AGENTS.md", schema["paths"]["index"], schema["paths"]["overview"]}
    for relative in schema["required_paths"]:
        try:
            path = resolve_within(kb_dir, relative)
            is_file = relative in file_paths or relative.endswith(".md")
            if not (path.is_file() if is_file else path.is_dir()):
                invalid.append(relative + ("（需要文件）" if is_file else "（需要目录）"))
        except (SchemaError, OSError, RuntimeError):
            invalid.append(relative + "（路径无效或越界）")
    return invalid


def is_asset_path(relative_path, schema):
    rel = Path(relative_path).as_posix().lstrip("./")
    assets = schema["paths"]["assets"]
    return rel == assets or rel.startswith(assets + "/")


def infer_document_type(relative_path, schema):
    rel = Path(relative_path).as_posix().lstrip("./")
    if is_asset_path(rel, schema):
        return None
    exact = schema["document_types"]["exact"]
    if rel in exact:
        return exact[rel]
    for prefix, document_type in sorted(schema["document_types"]["prefix"].items(), key=lambda item: -len(item[0])):
        if rel.startswith(prefix):
            return document_type
    return None


def index_section_for(relative_path, schema):
    rel = Path(relative_path).as_posix().lstrip("./")
    for prefix, section in sorted(schema["index_sections"].items(), key=lambda item: -len(item[0])):
        if rel.startswith(prefix):
            return section
    return None
