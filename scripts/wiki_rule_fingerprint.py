"""Conservative AST fingerprints for evidence rules, independent of display settings."""
import ast
import hashlib
import json
from pathlib import Path


CORE_MODULES = (
    'wiki_numbers.py', 'wiki_evidence.py', 'wiki_provenance.py', 'wiki_reviews.py',
    'markdown_links.py', 'wiki_links.py', 'wiki_sources.py', 'wiki_metadata.py',
    'wiki_fragments.py', 'wiki_review_policy.py', 'wiki_scan.py', 'wiki_rule_fingerprint.py',
)
CONFIG_INCLUDED = {'resolve_within', 'is_asset_path', 'infer_document_type',
                   'is_knowledge_page', 'index_section_for', 'SchemaError'}


class WithoutDocstrings(ast.NodeTransformer):
    def generic_visit(self, node):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.body and isinstance(node.body[0], ast.Expr):
                value = node.body[0].value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    node.body = node.body[1:]
        return super().generic_visit(node)


def canonical_ast(node):
    """Ignore positions and empty optional fields introduced by newer Python ASTs.

    Nonempty new syntax still participates. This is a structural contract, not
    a promise that arbitrary future Python parser changes are equivalent.
    """
    if isinstance(node, ast.AST):
        return [type(node).__name__, {key: canonical_ast(value)
                for key, value in ast.iter_fields(node) if value is not None and value != []}]
    if isinstance(node, list):
        return [canonical_ast(value) for value in node]
    if isinstance(node, (bytes, complex)) or node is Ellipsis:
        return [type(node).__name__, repr(node)]
    return node


def module_rules(source, name):
    tree = ast.parse(source)
    if name == 'wiki_config.py':
        tree.body = [node for node in tree.body
                     if isinstance(node, (ast.Import, ast.ImportFrom))
                     or isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in CONFIG_INCLUDED]
    return canonical_ast(WithoutDocstrings().visit(tree))


def checker_fingerprint(root=None):
    root = Path(root) if root is not None else Path(__file__).parent
    modules = {name: module_rules((root / name).read_text(encoding='utf-8'), name)
               for name in (*CORE_MODULES, 'wiki_config.py')}
    schema = json.loads((root.parent / 'references/schema.json').read_text(encoding='utf-8'))
    # Current limits control maintenance, display, ingestion and audit volume;
    # none changes evidence matching. Review this boundary when adding a limit.
    schema.pop('limits')
    payload = {'format': 'evidence-ast-v1', 'modules': modules, 'schema': schema}
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
