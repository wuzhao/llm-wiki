"""File writes that preserve existing content on preparation failures."""
import os
import stat
import tempfile
from pathlib import Path

from wiki_config import SchemaError, resolve_within


def checked_destination(kb_dir, relative):
    path = Path(kb_dir) / relative
    resolved = resolve_within(kb_dir, relative)
    if path.is_symlink():
        raise SchemaError(f"拒绝写入符号链接: {relative}")
    if resolved.exists() and not resolved.is_file():
        raise SchemaError(f"写入目标不是普通文件: {relative}")
    return resolved


def atomic_write_text(path, content):
    """Write a complete sibling temporary file before replacing the destination."""
    path = Path(path)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            if path.exists():
                os.fchmod(output.fileno(), stat.S_IMODE(path.stat().st_mode))
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def create_unique_text(directory, base_name, content):
    """Reserve the destination exclusively; never overwrite an existing raw file."""
    directory = Path(directory)
    counter = 1
    while True:
        suffix = "" if counter == 1 else f"-{counter}"
        path = directory / f"{base_name}{suffix}.md"
        try:
            output = path.open("x", encoding="utf-8")
        except FileExistsError:
            counter += 1
            continue
        try:
            with output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            path.unlink()
            raise
        return path


def create_unique_bytes(directory, base_name, content, extension):
    """Exclusively create a captured source artifact without overwriting history."""
    directory = Path(directory)
    counter = 1
    while True:
        suffix = "" if counter == 1 else f"-{counter}"
        path = directory / f"{base_name}{suffix}{extension}"
        try:
            output = path.open("xb")
        except FileExistsError:
            counter += 1
            continue
        try:
            with output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            path.unlink()
            raise
        return path
