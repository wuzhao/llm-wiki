"""Shared, lossless frontmatter parsing and content fingerprints."""
import datetime
import hashlib
import re

import yaml


FRONTMATTER_RE = re.compile(
    r"\A(?:\ufeff)?---\r?\n(?P<frontmatter>.*?)\r?\n---(?:\r?\n|\Z)", re.DOTALL,
)


class UniqueKeyLoader(yaml.SafeLoader):
    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                if key in seen:
                    raise yaml.constructor.ConstructorError(None, None, f"重复 YAML 键: {key}", key_node.start_mark)
                seen.add(key)
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(None, None, "YAML 键必须是标量", key_node.start_mark) from exc
        return super().construct_mapping(node, deep=deep)


def split_frontmatter(content):
    match = FRONTMATTER_RE.match(content)
    if not match:
        without_bom = content.removeprefix("\ufeff")
        if without_bom.startswith(("---\n", "---\r\n")):
            return "", {}, content, "YAML frontmatter 分隔符不完整"
        return "", {}, content, "缺少 YAML frontmatter"
    frontmatter, body = match.group("frontmatter"), content[match.end():]
    try:
        metadata = yaml.load(frontmatter, Loader=UniqueKeyLoader)
        if metadata is None:
            metadata = {}
    except yaml.YAMLError as exc:
        return frontmatter, {}, body, f"YAML frontmatter 无法解析: {str(exc).splitlines()[0]}"
    if not isinstance(metadata, dict):
        return frontmatter, {}, body, "YAML frontmatter 必须是映射"
    if any(not isinstance(key, str) for key in metadata):
        return frontmatter, {}, body, "YAML frontmatter 字段名必须是字符串"
    return frontmatter, metadata, body, ""


def body_sha256(body):
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def content_sha256(content):
    # Ignore only the final line terminator; indentation and other whitespace matter.
    return body_sha256(content.rstrip("\r\n"))


def raw_content(body):
    return body.removeprefix("\r\n") if body.startswith("\r\n") else body.removeprefix("\n")


def parse_datetime(value):
    if isinstance(value, datetime.datetime):
        result = value
    elif isinstance(value, datetime.date):
        result = datetime.datetime.combine(value, datetime.time.min)
    elif isinstance(value, str):
        try:
            result = datetime.datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=datetime.timezone.utc)
    return result.astimezone(datetime.timezone.utc)
