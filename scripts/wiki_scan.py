"""One decoded inventory shared by lint checks, provenance and repair planning."""
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from wiki_sources import load_documents
from wiki_metadata import split_frontmatter


@dataclass
class WikiSnapshot:
    base: Path
    documents: dict
    text: dict
    errors: dict
    originals: dict = field(default_factory=dict)
    parsed: dict = field(default_factory=dict)

    def parse(self, content):
        """Cache exact text per scan, returning isolated mutable metadata."""
        if content not in self.parsed:
            self.parsed[content] = split_frontmatter(content)
        frontmatter, metadata, body, error = self.parsed[content]
        return frontmatter, deepcopy(metadata), body, error

    def read(self, relative):
        if relative not in self.text:
            if relative in self.errors:
                raise OSError(self.errors[relative])
            self.text[relative] = (self.base / relative).read_bytes().decode("utf-8")
            self.originals[relative] = self.text[relative]
        return self.text[relative]


def load_snapshot(kb_dir, schema, target_index):
    text, parsed = {}, {}
    documents, errors = load_documents(
        kb_dir, [schema["paths"]["raw"], schema["paths"]["wiki"]], text_cache=text,
        scan_errors=target_index["scan_errors"], excluded_roots=[schema["paths"]["assets"]],
        parse_cache=parsed,
    )
    target_index["content_cache"] = text
    return WikiSnapshot(Path(kb_dir), documents, text, errors, dict(text), parsed)
