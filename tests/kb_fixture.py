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
import yaml

from init_wiki import initialize_kb


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


NOW = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def markdown(metadata, body):
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n"


def page(document_type, title, body, generated_at=NOW, **extra):
    metadata = {
        "type": document_type,
        "title": title,
        "description": f"{title} 的测试页面。",
        "tags": ["test"],
        "generated": {"by": "llm-wiki-test/0.1.0", "at": generated_at},
    }
    metadata.update(extra)
    return markdown(metadata, body)
