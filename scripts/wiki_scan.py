"""One decoded inventory shared by lint checks, provenance and repair planning."""
from dataclasses import dataclass, field
from pathlib import Path

from wiki_sources import load_documents


@dataclass
class WikiSnapshot:
    base: Path
    documents: dict
    text: dict
    errors: dict
    originals: dict = field(default_factory=dict)

    def read(self, relative):
        if relative not in self.text:
            if relative in self.errors:
                raise OSError(self.errors[relative])
            self.text[relative] = (self.base / relative).read_bytes().decode("utf-8")
            self.originals[relative] = self.text[relative]
        return self.text[relative]


def load_snapshot(kb_dir, schema, target_index):
    text = {}
    documents, errors = load_documents(
        kb_dir, [schema["paths"]["raw"], schema["paths"]["wiki"]], text_cache=text,
        scan_errors=target_index["scan_errors"], excluded_roots=[schema["paths"]["assets"]],
    )
    target_index["content_cache"] = text
    return WikiSnapshot(Path(kb_dir), documents, text, errors, dict(text))
