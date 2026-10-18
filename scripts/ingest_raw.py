#!/usr/bin/env python3
import argparse
import datetime
import fcntl
import hashlib
import os
import re
import sys
import urllib.parse
import urllib.request
from contextlib import contextmanager
from pathlib import Path

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        f"缺少 PyYAML；使用当前解释器 {sys.executable} 安装依赖文件 "
        f"{Path(__file__).resolve().parents[1] / 'requirements.txt'} 中的依赖。"
    ) from exc

from wiki_config import SchemaError, infer_document_type, load_schema, resolve_within, validate_structure
from wiki_io import checked_destination, create_unique_bytes, create_unique_text
from html_markdown import ArticleTextParser
from wiki_metadata import body_sha256, content_sha256
from wiki_sources import document_content_hash, raw_inventory, source_identity


def clean_filename(title):
    # Remove invalid characters from filename
    return re.sub(r'[\\/*?:"<>|]', "", title).strip()


def fetch_url_content(url, limits, capture=None):
    if urllib.parse.urlsplit(url).scheme not in {"http", "https", "data"}:
        raise ValueError("URL 仅支持 http、https 或 data；本地文件请使用 --file")
    req = urllib.request.Request(url, headers={"User-Agent": "LLM-Wiki/0.1"})
    with urllib.request.urlopen(req, timeout=limits["url_timeout_seconds"]) as response:
        media_type = response.headers.get_content_type()
        if not (media_type.startswith("text/") or media_type == "application/xhtml+xml"):
            raise ValueError(f"URL 返回非文本内容 {media_type}，请将附件保存到 assets 后提取正文")
        data = response.read(limits["max_source_bytes"] + 1)
        if len(data) > limits["max_source_bytes"]:
            raise ValueError("URL 内容超过 max_source_bytes")
        encoding = response.headers.get_content_charset()
        if not encoding and media_type in {"text/html", "application/xhtml+xml"}:
            match = re.search(br'charset\s*=\s*[\x22\x27]?([a-zA-Z0-9._-]+)', data[:4096], re.I)
            if match:
                encoding = match.group(1).decode("ascii")
        text = data.decode(encoding or "utf-8-sig")
        resolved_url = response.geturl() if hasattr(response, "geturl") else url
    if capture is not None:
        capture.update(data=data, media_type=media_type, resolved_url=resolved_url,
                       encoding=encoding or "utf-8-sig")
    if media_type not in {"text/html", "application/xhtml+xml"}:
        return text, ""
    parser = ArticleTextParser(resolved_url)
    parser.feed(text)
    parser.close()
    return parser.text(), "".join(parser.title).strip()


def read_file_content(path, max_bytes):
    with open(path, "rb") as f:
        raw_bytes = f.read(max_bytes + 1)
    if len(raw_bytes) > max_bytes:
        raise ValueError("文件内容超过 max_source_bytes")
    return raw_bytes.decode("utf-8"), hashlib.sha256(raw_bytes).hexdigest()


@contextmanager
def raw_lock(directory):
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def store_material(kb_dir, raw_destination, base_name, content, metadata, capture, schema):
    """Serialize inventory checks and writes so identical retries do not duplicate raw."""
    with raw_lock(raw_destination):
        documents, latest, errors = raw_inventory(kb_dir, schema)
        if errors:
            raise ValueError("无法安全检查已有素材: " + ", ".join(sorted(errors)))
        identity = source_identity(metadata, kb_dir)
        previous = latest.get(identity)
        fingerprint = content_sha256(content)
        previous_metadata = documents[previous]["metadata"] if previous else {}
        same_capture = (not metadata.get("source_file_sha256") or metadata["source_file_sha256"] == previous_metadata.get("source_file_sha256"))
        if previous_metadata.get("body_sha256"):
            same_capture = same_capture and previous_metadata["body_sha256"] == body_sha256(documents[previous]["body"])
        if capture:
            digest = hashlib.sha256(capture["data"]).hexdigest()
            try:
                snapshot = previous_metadata.get("source_snapshot")
                path = resolve_within(kb_dir, snapshot) if isinstance(snapshot, str) and snapshot else None
                assets = resolve_within(kb_dir, schema["paths"]["assets"])
                same_capture = (same_capture and digest == previous_metadata.get("source_snapshot_sha256")
                                and path is not None and path.is_relative_to(assets)
                                and path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest)
            except (OSError, SchemaError, RuntimeError):
                same_capture = False
        if previous and document_content_hash(documents[previous]) == fingerprint and same_capture:
            print(f"已有相同内容 ingested: {previous}；未新增 raw，请核对既有摘要是否完整", file=sys.stderr)
            return documents[previous]["path"]
        same_content = [relative for relative, document in documents.items() if document_content_hash(document) == fingerprint]
        if same_content:
            print("已有相同内容 ingested: " + ", ".join(same_content) + "；本次保存来源的新快照，知识页无需机械改写", file=sys.stderr)
        metadata["source_id"] = identity
        metadata["source_version"] = 1
        if previous:
            version = documents[previous]["metadata"].get("source_version", 0)
            metadata["source_version"] = (version if isinstance(version, int) and not isinstance(version, bool) else 0) + 1
            metadata["supersedes"] = previous
        metadata["content_sha256"] = fingerprint
        body = "\n" + content + ("" if content.endswith("\n") else "\n")
        metadata["body_sha256"] = body_sha256(body)
        created_snapshot = None
        month_directory = None
        created_month = False
        try:
            if capture:
                relative_month = f"{schema['paths']['assets']}/{datetime.datetime.now(datetime.timezone.utc):%Y%m}"
                month_directory = resolve_within(kb_dir, relative_month)
                if not month_directory.is_relative_to(resolve_within(kb_dir, schema["paths"]["assets"])):
                    raise SchemaError("原始响应快照目录越出 assets")
                created_month = not month_directory.exists()
                month_directory.mkdir(exist_ok=True)
                extension = ".html" if capture["media_type"] in {"text/html", "application/xhtml+xml"} else ".txt"
                digest = hashlib.sha256(capture["data"]).hexdigest()
                destination = checked_destination(kb_dir, f"{relative_month}/source-{digest}{extension}")
                if not destination.exists() or destination.read_bytes() != capture["data"]:
                    destination = create_unique_bytes(month_directory, f"source-{digest}", capture["data"], extension)
                    created_snapshot = destination
                metadata.update(source_snapshot=destination.relative_to(Path(kb_dir).resolve()).as_posix(),
                                source_snapshot_sha256=digest, extraction_version="html-markdown/1",
                                source_media_type=capture["media_type"], source_encoding=capture["encoding"],
                                resolved_url=capture["resolved_url"])
            frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False, default_flow_style=False).rstrip()
            return create_unique_text(raw_destination, base_name, f"---\n{frontmatter}\n---\n{body}")
        except BaseException:
            if created_snapshot is not None:
                created_snapshot.unlink()
            if created_month:
                try:
                    month_directory.rmdir()
                except OSError:
                    pass
            raise


def main():
    parser = argparse.ArgumentParser(description="Deterministic raw material ingestion tool for LLM Wiki")
    parser.add_argument("kb_dir", help="Path to the knowledge base directory")
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--url", help="Fetch content from URL")
    source_group.add_argument("--file", help="Read content from a local file")
    source_group.add_argument("--text", help="Direct text content to ingest")
    parser.add_argument("--title", help="Title of the material")
    parser.add_argument("--source-id", help="Reuse an explicit source identity for pasted-text revisions")
    
    args = parser.parse_args()
    if args.text is not None and not (args.title or "").strip():
        parser.error("使用 --text 时必须同时提供 --title")
    if args.source_id is not None and (args.text is None or not args.source_id.strip()):
        parser.error("--source-id 仅用于为粘贴文本指定非空来源身份")
    kb_dir = os.path.abspath(args.kb_dir)
    try:
        schema = load_schema()
        raw_destination = str(resolve_within(kb_dir, schema["paths"]["raw"]))
    except SchemaError as exc:
        parser.error(str(exc))
    
    missing = validate_structure(kb_dir, schema)
    if missing:
        parser.error("知识库结构不完整: " + ", ".join(missing) + "；请先执行初始化 workflow")
        
    content = ""
    title = args.title or ""
    source_url = ""
    source_file_path = ""
    source_file_sha256 = ""
    capture = {}
    
    if args.url:
        source_url = args.url
        try:
            fetched_content, fetched_title = fetch_url_content(args.url, schema["limits"], capture)
        except (OSError, ValueError, LookupError) as exc:
            parser.error(f"URL 获取失败: {exc}；请粘贴正文后重试")
        content = fetched_content
        if not title and fetched_title:
            title = fetched_title
    elif args.file:
        try:
            source_file_path = os.path.abspath(args.file)
            content, source_file_sha256 = read_file_content(source_file_path, schema["limits"]["max_source_bytes"])
            if not title:
                title = os.path.splitext(os.path.basename(source_file_path))[0]
        except (OSError, ValueError) as exc:
            parser.error(f"读取文件失败: {exc}")
    elif args.text is not None:
        content = args.text

    if not content.strip():
        parser.error("素材正文为空，未写入文件；请提供有效正文")
    if len(content.encode("utf-8")) > schema["limits"]["max_source_bytes"]:
        parser.error("素材正文超过 max_source_bytes")
        
    if not title:
        title = "Untitled Material"

    today_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
    clean_title = clean_filename(title)
    if not clean_title:
        clean_title = "Untitled"
        
    base_name = f"{today_str} - {clean_title}"
    
    now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
    
    metadata = {
        "type": infer_document_type(f"{schema['paths']['raw']}/material.md", schema),
        "title": title,
        "timestamp": now_iso,
    }
    if source_url:
        metadata["resource"] = source_url
        metadata["source_url"] = source_url
    if source_file_path:
        metadata["resource"] = source_file_path
        metadata["source_file_path"] = source_file_path
        metadata["source_file_sha256"] = source_file_sha256
    if args.text is not None:
        metadata["source_id"] = args.source_id.strip() if args.source_id else "text:" + content_sha256(content)
    
    try:
        filepath = store_material(kb_dir, raw_destination, base_name, content, metadata, capture, schema)
    except (OSError, ValueError, SchemaError) as exc:
        parser.error(f"raw 写入失败: {exc}")
        
    # Output only the absolute path to stdout so the Agent can easily capture it
    print(filepath)

if __name__ == "__main__":
    main()
