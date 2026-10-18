"""Raw source identity, version selection, and safe read-only inventories."""
import datetime
import hashlib
import os
import urllib.parse
from collections import defaultdict
from pathlib import Path

from wiki_metadata import content_sha256, parse_datetime, raw_content, split_frontmatter


def source_identity(metadata, kb_dir):
    source_file = metadata.get("source_file_path")
    resource = metadata.get("resource")
    url = metadata.get("source_url") if not resource else None
    if isinstance(resource, str) and resource.lstrip().lower().startswith(("http:", "https:", "data:")):
        url = resource
    if isinstance(source_file, str) and source_file:
        path = Path(source_file)
        material = "file:" + str((Path(kb_dir) / path).resolve())
    elif isinstance(url, str) and url:
        try:
            parsed = urllib.parse.urlsplit(url)
        except ValueError:
            return None
        material = "url:" + urllib.parse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))
    else:
        return metadata.get("source_id") if isinstance(metadata.get("source_id"), str) else None
    return "sha256:" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def walk_visible_files(root, errors=None, kb_dir=None, excluded_roots=()):
    """Collect visible files; never silently treat a failed walk as complete."""
    root = Path(root)
    base = Path(kb_dir) if kb_dir is not None else None
    excluded = [Path(path).resolve() for path in excluded_roots]

    def is_excluded(path):
        if not excluded:
            return False
        resolved = path.resolve()
        return any(resolved.is_relative_to(directory) for directory in excluded)

    if is_excluded(root):
        return []

    def onerror(error):
        if errors is None:
            raise error
        path = Path(error.filename) if error.filename is not None else root
        try:
            relative = path.relative_to(base).as_posix() if base is not None else path.as_posix()
        except ValueError:
            relative = path.as_posix()
        errors[relative] = f"目录遍历失败: {error}"

    files = []
    for current, directories, filenames in os.walk(root, onerror=onerror):
        directories[:] = [name for name in directories
                          if not name.startswith(".") and not is_excluded(Path(current) / name)]
        files.extend(Path(current) / name for name in filenames
                     if not name.startswith(".") and not is_excluded(Path(current) / name))
    return files


def load_documents(kb_dir, roots, text_cache=None, scan_errors=None, excluded_roots=()):
    base = Path(kb_dir).resolve()
    documents = {}
    errors = {}
    scan_errors = {} if scan_errors is None else scan_errors
    excluded = [base / path for path in excluded_roots]
    for relative_root in roots:
        root = (base / relative_root).resolve()
        if not root.is_relative_to(base):
            errors[relative_root] = "素材目录越出知识库"
            continue
        for path in walk_visible_files(root, scan_errors, base, excluded_roots=excluded):
            if path.suffix.casefold() != ".md":
                continue
            path = path.resolve()
            if not path.is_relative_to(root):
                continue
            relative = path.relative_to(base).as_posix()
            try:
                text = path.read_bytes().decode("utf-8")
                if text_cache is not None:
                    text_cache[relative] = text
                _, metadata, body, error = split_frontmatter(text)
                if error and error != "缺少 YAML frontmatter":
                    errors[relative] = error
                    continue
                documents[relative] = {"metadata": metadata, "body": body, "path": path,
                                       "body_start_line": text.count("\n", 0, len(text) - len(body)) + 1}
            except (OSError, UnicodeError) as exc:
                errors[relative] = str(exc)
    errors.update(scan_errors)
    return documents, errors


def raw_inventory(kb_dir, schema):
    documents, errors = load_documents(kb_dir, [schema["paths"]["raw"]],
                                      excluded_roots=[schema["paths"]["assets"]])
    latest = latest_sources(documents, kb_dir)
    return documents, latest, errors


def latest_sources(documents, kb_dir):
    groups = defaultdict(list)
    for relative, document in documents.items():
        identity = source_identity(document["metadata"], kb_dir)
        if identity:
            groups[identity].append(relative)
    oldest = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
    def rank(relative):
        document = documents[relative]
        metadata = document["metadata"]
        version = metadata.get("source_version", 0)
        if not isinstance(version, int) or isinstance(version, bool):
            version = 0
        return (version, parse_datetime(metadata.get("timestamp")) or oldest,
                document["path"].stat().st_mtime_ns, relative)
    return {identity: max(paths, key=rank) for identity, paths in groups.items()}


def document_content_hash(document):
    return content_sha256(raw_content(document["body"]))
