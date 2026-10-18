"""Shared knowledge-base target inventory and link resolution.

Markdown syntax parsing lives in markdown_links; diagnostics and repairs live
in lint_wiki. This module only locates targets and same-root candidates.
"""
import urllib.parse
from collections import defaultdict
from pathlib import Path

from markdown_links import unescape_target
from wiki_config import resolve_within
from wiki_sources import walk_visible_files


def build_target_index(kb_dir, schema):
    base = Path(kb_dir).resolve()
    by_relative = {}
    by_name = defaultdict(list)
    by_stem = defaultdict(list)
    allowed_directories = set()
    roots = {}
    scan_errors = {}

    for root_name in schema["link_roots"]:
        root = resolve_within(base, root_name)
        allowed_directories.add(root)
        roots[root_name] = root
        for path in walk_visible_files(root, scan_errors, base):
            resolved = path.resolve()
            try:
                relative = resolved.relative_to(base).as_posix()
            except ValueError:
                continue
            by_relative[relative] = resolved
            by_name[resolved.name.casefold()].append(relative)
            by_stem[resolved.stem.casefold()].append(relative)

    return {
        "base": base,
        "by_relative": by_relative,
        "by_name": by_name,
        "by_stem": by_stem,
        "allowed_directories": allowed_directories,
        "roots": roots,
        "heading_cache": {},
        "scan_errors": scan_errors,
    }


def is_allowed_target(path, target_index):
    resolved = Path(path).resolve()
    for root in target_index["allowed_directories"]:
        if resolved == root or root in resolved.parents:
            return True
    return False


def target_relative(path, target_index):
    try:
        return Path(path).resolve().relative_to(target_index["base"]).as_posix()
    except ValueError:
        return None


def target_root_name(path, target_index):
    resolved = Path(path).resolve()
    for root_name, root in target_index["roots"].items():
        if resolved == root or root in resolved.parents:
            return root_name
    return None


def candidate_paths(target_text, target_index, root_name):
    if not root_name:
        return []
    decoded = urllib.parse.unquote(target_text).strip().strip("<>")
    name = Path(decoded).name
    if not name:
        return []
    if Path(name).suffix:
        candidates = target_index["by_name"].get(name.casefold(), [])
    else:
        candidates = target_index["by_stem"].get(name.casefold(), [])
    prefix = f"{root_name}/"
    return sorted({path for path in candidates if path == root_name or path.startswith(prefix)})


def resolve_standard_link(source_relative, target_text, target_index):
    raw_target = unescape_target(target_text.strip())
    try:
        parsed = urllib.parse.urlsplit(raw_target)
    except ValueError:
        return {"relative": None, "candidates": []}
    if parsed.scheme or raw_target.startswith("//"):
        return {"external": True}

    path_text = urllib.parse.unquote(parsed.path)
    fragment = urllib.parse.unquote(parsed.fragment)
    if not path_text:
        candidate = target_index["base"] / source_relative
    elif path_text.startswith("/"):
        candidate = target_index["base"] / path_text.lstrip("/")
    else:
        candidate = target_index["base"] / Path(source_relative).parent / path_text
    candidate = candidate.resolve()
    root_name = target_root_name(candidate, target_index)

    if is_allowed_target(candidate, target_index) and candidate.exists():
        return {"relative": target_relative(candidate, target_index), "fragment": fragment}
    return {
        "relative": None,
        "fragment": fragment,
        "candidates": candidate_paths(path_text, target_index, root_name),
    }


def resolve_wikilink(source_relative, target_text, target_index, schema):
    base_text, separator, fragment = target_text.partition("#")
    decoded = urllib.parse.unquote(base_text.replace("\\", "").strip())
    wiki_root = schema["paths"]["wiki"]
    root_names = tuple(f"{name}/" for name in schema["link_roots"])

    if not decoded:
        candidate = target_index["base"] / source_relative
    elif decoded.startswith("/"):
        candidate = target_index["base"] / decoded.lstrip("/")
    elif decoded.startswith(root_names):
        candidate = target_index["base"] / decoded
    elif source_relative.startswith(f"{wiki_root}/"):
        candidate = target_index["base"] / wiki_root / decoded
    else:
        candidate = target_index["base"] / decoded

    possible = [candidate]
    # A Wikilink normally omits the Markdown extension. Do not infer that a
    # dot in a page title (for example, "E21.中产") is an extension.
    if not candidate.name.casefold().endswith(".md"):
        possible.append(Path(f"{candidate}.md"))
    for path in possible:
        resolved = path.resolve()
        if is_allowed_target(resolved, target_index) and resolved.exists():
            return {"relative": target_relative(resolved, target_index), "fragment": fragment if separator else ""}

    root_name = target_root_name(candidate, target_index)
    if not root_name:
        source_path = target_index["base"] / source_relative
        root_name = target_root_name(source_path, target_index)

    return {
        "relative": None,
        "fragment": fragment if separator else "",
        "candidates": candidate_paths(decoded, target_index, root_name),
    }
