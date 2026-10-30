#!/usr/bin/env python3
"""Read-only release checks for the skill repository, not a user knowledge base."""
import argparse
import ast
import re
import urllib.parse
from pathlib import Path

from lint_wiki import heading_keys
from markdown_links import mask_non_prose, standard_link_spans, unescape_target
from wiki_config import MARKDOWN_TEMPLATE_RE, SchemaError, infer_document_type, load_schema
from wiki_metadata import split_frontmatter


def check_project(root):
    root = Path(root).resolve()
    errors = []
    try:
        schema = load_schema(root / "references/schema.json")
    except SchemaError as exc:
        return [str(exc)]
    ignore = root / ".gitignore"
    patterns = set(ignore.read_text().splitlines()) if ignore.is_file() else set()
    if not {".env", "__pycache__/"}.issubset(patterns):
        errors.append(".gitignore 必须忽略 .env 和 __pycache__/")
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    _, metadata, body, error = split_frontmatter(skill)
    if error:
        errors.append(f"SKILL.md: {error}")
    version = metadata.get("metadata", {})
    version = version.get("version") if isinstance(version, dict) else None
    if not isinstance(version, str) or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.append("SKILL.md metadata.version 必须为 x.y.z")
    heading = re.search(r"^## (\d+) 条护栏[^\n]*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    if not heading or [int(n) for n in re.findall(r"^(\d+)\. ", heading[2], re.M)] != list(range(1, int(heading[1]) + 1)):
        errors.append("SKILL.md 护栏标题与条目数量或编号不一致")

    template_paths = {"source": "summaries", "entity": "entities", "concept": "concepts",
                      "archive": "analyses", "hub": "hubs", "overview": "overview", "log": "logs", "index": "index"}
    for name, key in template_paths.items():
        path = root / "templates" / f"{name}-template.md"
        match = MARKDOWN_TEMPLATE_RE.search(path.read_text(encoding="utf-8"))
        if not match:
            errors.append(f"{path.name}: 缺少 Markdown 模板代码块")
            continue
        rendered = match["body"].replace("{{SKILL_VERSION}}", str(version))
        _, fields, _, error = split_frontmatter(rendered)
        relative = schema["paths"][key]
        if not relative.endswith(".md"):
            relative += "/example.md"
        if error:
            errors.append(f"{path.name}: {error}")
        elif name == "index":
            if fields != {"okf_version": schema["okf_version"]}:
                errors.append("index 模板字段与 schema 不一致")
        elif fields.get("type") != infer_document_type(relative, schema):
            errors.append(f"{path.name}: type 与 schema 不一致")
        if name != "index":
            if "llm-wiki/{{SKILL_VERSION}}" not in match["body"]:
                errors.append(f"{path.name}: generated.by 必须引用统一版本占位符")

    documents = sorted([*root.glob("*.md"), *root.glob("references/**/*.md"), *root.glob("templates/**/*.md")])
    for path in documents:
        text = path.read_bytes().decode("utf-8")
        relative = path.relative_to(root)
        if not text.endswith("\n") or text.endswith("\n\n"):
            errors.append(f"{relative}: Markdown 必须且仅以一个换行符结尾")
        for start, end in standard_link_spans(mask_non_prose(text)):
            target = urllib.parse.urlsplit(unescape_target(text[start:end]))
            if target.scheme or target.netloc:
                continue
            destination = (path.parent / urllib.parse.unquote(target.path)).resolve() if target.path else path
            if not destination.is_relative_to(root) or not destination.exists():
                errors.append(f"{relative}: 本地文档断链 {text[start:end]}")
            elif target.fragment and destination.suffix == ".md":
                exact, slugs = heading_keys(destination)
                if urllib.parse.unquote(target.fragment).casefold() not in exact | slugs:
                    errors.append(f"{relative}: 文档锚点不存在 {text[start:end]}")
        # Also validate concrete skill resource paths written as inline code.
        for match in re.finditer(r"`((?:references|templates|scripts)/[\w./-]+\.(?:md|json|py))`", text):
            if not (root / match[1]).exists():
                errors.append(f"{relative}: 资源路径不存在 {match[1]}")

    limits = schema["limits"]
    for path in (root / "scripts").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and len(node.args) > 1:
                if isinstance(node.args[0], ast.Constant) and node.args[0].value in limits:
                    errors.append(f"{path.name}:{node.lineno}: 阈值不得提供重复的默认值")
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Constant):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    name = target.id if isinstance(target, ast.Name) else None
                    if isinstance(target, ast.Subscript) and isinstance(target.slice, ast.Constant):
                        name = target.slice.value
                    if name in limits:
                        errors.append(f"{path.name}:{node.lineno}: 阈值必须读取 schema")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    try:
        errors = check_project(args.root)
    except (OSError, ValueError, SyntaxError) as exc:
        errors = [str(exc)]
    for error in errors:
        print(error)
    if not errors:
        print("Project consistency checks passed.")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
