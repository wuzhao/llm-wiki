#!/usr/bin/env python3
"""Preserve an attachment as bytes; extraction is a separate Agent task."""
import argparse
import datetime
import hashlib
import json
import mimetypes
import re
from pathlib import Path

from ingest_raw import raw_lock
from wiki_config import SchemaError, load_schema, resolve_within, validate_structure
from wiki_io import checked_destination, create_unique_bytes


def store_attachment(kb_dir, source, schema):
    base, source = Path(kb_dir).resolve(), Path(source).resolve()
    missing = validate_structure(base, schema)
    if missing:
        raise SchemaError("知识库结构不完整: " + ", ".join(missing))
    if not source.is_file():
        raise ValueError("附件必须是可读取的普通文件")
    with source.open("rb") as stream:
        data = stream.read(schema["limits"]["max_source_bytes"] + 1)
    if not data or len(data) > schema["limits"]["max_source_bytes"]:
        raise ValueError("附件为空或超过 max_source_bytes")
    digest = hashlib.sha256(data).hexdigest()
    extension = source.suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,16}", extension):
        extension = ".bin"
    relative = f"{schema['paths']['assets']}/{datetime.datetime.now(datetime.timezone.utc):%Y%m}"
    directory = resolve_within(base, relative)
    assets = resolve_within(base, schema["paths"]["assets"])
    if not directory.is_relative_to(assets):
        raise SchemaError("附件目录越出 assets")
    with raw_lock(resolve_within(base, schema["paths"]["raw"])):
        created_directory = not directory.exists()
        try:
            destination = checked_destination(base, f"{relative}/attachment-{digest}{extension}")
            directory.mkdir(exist_ok=True)
            reused = destination.exists() and destination.read_bytes() == data
            if not reused:
                destination = create_unique_bytes(directory, f"attachment-{digest}", data, extension)
        except BaseException:
            if created_directory and directory.exists():
                directory.rmdir()
            raise
    return {"path": destination.relative_to(base).as_posix(), "sha256": digest, "bytes": len(data),
            "original_name": source.name, "media_type": mimetypes.guess_type(source.name)[0] or "application/octet-stream",
            "reused": reused}


def main():
    parser = argparse.ArgumentParser(description="Copy an attachment into raw/assets without decoding or overwriting it")
    parser.add_argument("kb_dir")
    parser.add_argument("--file", required=True)
    args = parser.parse_args()
    try:
        result = store_attachment(args.kb_dir, args.file, load_schema())
    except (OSError, SchemaError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
