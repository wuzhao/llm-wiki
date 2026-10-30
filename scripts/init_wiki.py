#!/usr/bin/env python3
"""Initialize a new knowledge base from bundled templates without overwrites."""
import argparse
import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path

from wiki_config import (SchemaError, TemplateError, bundled_templates_path, load_schema,
                         render_markdown_template, validate_structure)
from wiki_metadata import split_frontmatter


def initialize_kb(directory):
    target = Path(directory).absolute()
    skill = Path(__file__).resolve().parents[1]
    if target.is_symlink() or target.resolve().is_relative_to(skill):
        raise SchemaError("知识库必须位于技能目录之外，目标不能是符号链接")
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise SchemaError("初始化只接受空目录或尚不存在的目录，已有内容保持不变")
    if not target.parent.is_dir():
        raise SchemaError(f"目标父目录不存在: {target.parent}")
    schema = load_schema()
    now = datetime.datetime.now(datetime.timezone.utc)
    files = {
        "AGENTS.md": (bundled_templates_path() / "AGENTS-template.md").read_text(encoding="utf-8"),
        schema["paths"]["index"]: render_markdown_template("index-template.md", now),
        schema["paths"]["overview"]: render_markdown_template("overview-template.md", now),
        f"{schema['paths']['logs']}/{now:%Y%m}.md": render_markdown_template("log-template.md", now),
    }
    for relative, content in files.items():
        if relative != "AGENTS.md":
            error = split_frontmatter(content)[3]
            if error:
                raise TemplateError(f"{relative}: {error}")
    stage = Path(tempfile.mkdtemp(prefix=".llm-wiki-init-", dir=target.parent))
    try:
        for relative in schema["required_paths"]:
            path = stage / relative
            (path.parent if relative.endswith(".md") else path).mkdir(parents=True, exist_ok=True)
        for relative, content in files.items():
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content.rstrip() + "\n", encoding="utf-8")
        missing = validate_structure(stage, schema)
        if missing:
            raise SchemaError("初始化结构不完整: " + ", ".join(missing))
        # Rename refuses to replace a nonempty directory created during staging.
        if target.is_symlink() or (target.exists() and (not target.is_dir() or any(target.iterdir()))):
            raise SchemaError("初始化期间目标已发生变化，保留目标内容")
        os.replace(stage, target)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return target.resolve()


def main():
    parser = argparse.ArgumentParser(description="Create a knowledge base in an empty or new directory")
    parser.add_argument("kb_dir")
    args = parser.parse_args()
    try:
        target = initialize_kb(args.kb_dir)
    except (OSError, SchemaError, TemplateError) as exc:
        parser.error(str(exc))
    print(json.dumps({"kb_dir": str(target), "created": sorted(path.relative_to(target).as_posix()
          for path in target.rglob("*") if path.is_file()), "next": "Run read-only lint, then append the init workflow log"},
          ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
