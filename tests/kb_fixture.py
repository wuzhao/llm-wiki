"""Render a fresh knowledge base from the shipped schema and templates."""
import datetime
import errno
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from wiki_config import load_markdown_template, load_schema


def initialize_kb(directory):
    directory = Path(directory)
    schema = load_schema()
    now = datetime.datetime.now(datetime.timezone.utc)
    for relative in schema["required_paths"]:
        path = directory / relative
        if path.suffix == ".md":
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            path.mkdir(parents=True, exist_ok=True)
    (directory / "AGENTS.md").write_text((ROOT / "templates/AGENTS-template.md").read_text(), encoding="utf-8")
    files = {
        schema["paths"]["index"]: "index-template.md",
        schema["paths"]["overview"]: "overview-template.md",
        f"{schema['paths']['logs']}/{now:%Y%m}.md": "log-template.md",
    }
    for relative, template in files.items():
        content = load_markdown_template(template)
        for old, new in {
            "YYYY-MM-DDTHH:MM:SSZ": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "YYYY 年 MM 月": now.strftime("%Y 年 %m 月"),
            "YYYY-MM-DD": now.strftime("%Y-%m-%d"),
            "YYYY-MM": now.strftime("%Y-%m"),
        }.items():
            content = content.replace(old, new)
        (directory / relative).write_text(content, encoding="utf-8")
    return directory


def snapshot(directory):
    return {p.relative_to(directory).as_posix(): p.read_bytes()
            for p in Path(directory).rglob("*") if p.is_file()}


@contextmanager
def unreadable_directory(directory):
    """Simulate an OS traversal error consistently on supported platforms."""
    directory = Path(directory).resolve()
    original = os.scandir

    def scandir(path):
        if Path(path).resolve() == directory:
            raise PermissionError(errno.EACCES, "Permission denied", str(directory))
        return original(path)

    with patch("os.scandir", scandir):
        yield
