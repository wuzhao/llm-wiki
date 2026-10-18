import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from wiki_config import SchemaError, infer_document_type, load_markdown_template, load_schema
from kb_fixture import initialize_kb, snapshot
from test_lint_wiki import page


SCHEMA = load_schema()


class SchemaTests(unittest.TestCase):
    def test_initialization_keeps_assets_inside_raw_and_outside_page_types(self):
        with tempfile.TemporaryDirectory() as temporary:
            kb = initialize_kb(temporary)
            self.assertEqual({path.name for path in kb.iterdir()}, {"AGENTS.md", "raw", "wiki"})
            self.assertTrue((kb / "raw/assets").is_dir())
            self.assertIsNone(infer_document_type("raw/assets/original.md", SCHEMA))
            self.assertEqual(infer_document_type("raw/note.md", SCHEMA), "source-material")

    def test_assets_outside_raw_are_rejected_at_load_time(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "schema.json"
            for assets in ("assets", "wiki/assets"):
                with self.subTest(assets=assets):
                    schema = copy.deepcopy(SCHEMA)
                    previous = schema["paths"]["assets"]
                    schema["paths"]["assets"] = assets
                    for key in ("required_paths", "link_roots"):
                        schema[key] = [assets if value == previous else value for value in schema[key]]
                    path.write_text(json.dumps(schema), encoding="utf-8")
                    with self.assertRaisesRegex(SchemaError, "paths.assets 必须位于 raw 内"):
                        load_schema(path)

    def test_named_paths_are_required_and_limits_are_positive(self):
        self.assertEqual(SCHEMA["okf_version"], "0.2")
        self.assertFalse(set(SCHEMA["paths"].values()) - set(SCHEMA["required_paths"]))
        self.assertTrue(all(
            isinstance(value, int) and not isinstance(value, bool) and value > 0
            for value in SCHEMA["limits"].values()
        ))

    def test_template_types_match_schema_path_mapping(self):
        cases = {
            "source-template.md": "wiki/summaries/example.md",
            "entity-template.md": "wiki/entities/example.md",
            "concept-template.md": "wiki/concepts/example.md",
            "archive-template.md": "wiki/analyses/example.md",
            "hub-template.md": "wiki/hubs/example.md",
            "overview-template.md": "wiki/overview.md",
            "log-template.md": "wiki/logs/202609.md",
        }
        for template_name, relative_path in cases.items():
            with self.subTest(template=template_name):
                content = (ROOT / "templates" / template_name).read_text(encoding="utf-8")
                match = re.search(r"^type:\s*([^\s#]+)", content, re.MULTILINE)
                self.assertIsNotNone(match)
                self.assertEqual(match.group(1), infer_document_type(relative_path, SCHEMA))

    def test_index_template_is_okf_0_2_root_index_without_example_links(self):
        content = load_markdown_template("index-template.md")
        metadata = yaml.safe_load(content.split("---\n", 2)[1])
        self.assertEqual(metadata, {"okf_version": SCHEMA["okf_version"]})
        self.assertNotIn("[[", content)

    def test_generated_actor_matches_skill_version(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        skill_metadata = yaml.safe_load(skill.split("---\n", 2)[1])
        expected_actor = f"llm-wiki/{skill_metadata['metadata']['version']}"
        for template_name in (
            "source-template.md",
            "entity-template.md",
            "concept-template.md",
            "archive-template.md",
            "hub-template.md",
            "overview-template.md",
            "log-template.md",
        ):
            with self.subTest(template=template_name):
                content = load_markdown_template(template_name)
                metadata = yaml.safe_load(content.split("---\n", 2)[1])
                self.assertEqual(metadata["generated"]["by"], expected_actor)

    def test_archive_wikilinks_are_wiki_root_relative(self):
        content = load_markdown_template("archive-template.md")
        self.assertNotIn("[[../", content)

    def test_tools_use_explicit_target_from_other_working_directories(self):
        with tempfile.TemporaryDirectory() as temporary:
            workspace = Path(temporary).resolve() / "工作区 with spaces"
            skill = workspace / "skills/llm-wiki"
            skill.mkdir(parents=True)
            for name in ("scripts", "references", "templates"):
                shutil.copytree(ROOT / name, skill / name, ignore=shutil.ignore_patterns("__pycache__"))
            for name in ("SKILL.md", "requirements.txt"):
                shutil.copyfile(ROOT / name, skill / name)
            agents = workspace / "AGENTS.md"
            agents.write_text("# Existing workspace instructions\n", encoding="utf-8")
            target = initialize_kb(workspace / "我的知识库")
            other = initialize_kb(workspace / "另一个知识库")
            # Neither the invocation directory nor a KB-local schema overrides the skill.
            for directory in (target, other):
                (directory / "references").mkdir()
                (directory / "references/schema.json").write_text("invalid schema", encoding="utf-8")
            source_file = workspace / "input with spaces.md"
            source_file.write_text("A note about workspace-target-keyword.\n", encoding="utf-8")
            protected_skill, protected_other = snapshot(skill), snapshot(other)
            protected_agents = agents.read_bytes()
            environment = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}

            def command(name, *arguments, cwd=other):
                result = subprocess.run(
                    [sys.executable, str(skill / "scripts" / name), str(target), *arguments],
                    cwd=cwd, env=environment, capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return result

            raw = Path(command("ingest_raw.py", "--file", str(source_file)).stdout.strip())
            self.assertTrue(raw.is_relative_to(target / "raw"))
            relative_raw = raw.relative_to(target).as_posix()
            concept = target / "wiki/concepts/target.md"
            concept.write_text(page(
                "concept", "Target", "# Target\n\nworkspace-target-keyword\n\n## 来源\n\n"
                f"[原始素材](../../{relative_raw})\n",
                sources=[{"id": "raw", "resource": "../../" + relative_raw}],
            ), encoding="utf-8")
            index = target / SCHEMA["paths"]["index"]
            index.write_text(index.read_text(encoding="utf-8")
                             .replace("概念: 0", "概念: 1")
                             .replace("## 概念\n", "## 概念\n\n- [Target](concepts/target.md)\n"),
                             encoding="utf-8")
            before = snapshot(target)
            for directory in (target, other, skill):
                with self.subTest(cwd=directory):
                    duplicate = command("ingest_raw.py", "--file", str(source_file), cwd=directory)
                    self.assertEqual(Path(duplicate.stdout.strip()), raw)
                    command("lint_wiki.py", "--fail-on", "error", cwd=directory)
                    search = json.loads(command("search_wiki.py", "workspace-target-keyword", cwd=directory).stdout)
                    self.assertEqual(search["total"], 1)
                    self.assertFalse(search["read_errors"])
                    impact = json.loads(command("impact_wiki.py", "--source", relative_raw, cwd=directory).stdout)
                    self.assertEqual({entry["path"] for entry in impact["affected"]}, {"wiki/concepts/target.md"})
                    self.assertFalse(impact["read_errors"])
            command("lint_wiki.py", "--fix", "--dry-run")
            self.assertEqual(snapshot(target), before)
            command("lint_wiki.py", "--fix")
            after = snapshot(target)
            changed = {path for path in before if before[path] != after[path]}
            self.assertEqual(len(changed), 1)
            log = changed.pop()
            self.assertTrue(log.startswith(SCHEMA["paths"]["logs"] + "/"))
            self.assertTrue(after[log].startswith(before[log]))
            self.assertEqual(set(after), set(before))
            for name in ("ingest_raw.py", "lint_wiki.py"):
                result = subprocess.run(
                    [sys.executable, "-I", "-S", str(skill / "scripts" / name), "--help"],
                    cwd=other, env=environment, capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(sys.executable, result.stderr)
                self.assertIn(str(skill / "requirements.txt"), result.stderr)
            self.assertEqual(snapshot(skill), protected_skill)
            self.assertEqual(snapshot(other), protected_other)
            self.assertEqual(agents.read_bytes(), protected_agents)

    def test_invalid_limit_is_rejected_at_load_time(self):
        schema = copy.deepcopy(SCHEMA)
        schema["limits"]["review_after_days"] = 0
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "schema.json"
            path.write_text(json.dumps(schema), encoding="utf-8")
            with self.assertRaisesRegex(SchemaError, "limits 必须是正整数"):
                load_schema(path)

    def test_invalid_okf_version_is_rejected_at_load_time(self):
        schema = copy.deepcopy(SCHEMA)
        schema["okf_version"] = 0.2
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "schema.json"
            path.write_text(json.dumps(schema), encoding="utf-8")
            with self.assertRaisesRegex(SchemaError, "okf_version"):
                load_schema(path)


    def test_missing_fields_and_inconsistent_mappings_are_rejected(self):
        cases = []
        schema = copy.deepcopy(SCHEMA)
        del schema["limits"]["max_page_bytes"]
        cases.append(schema)
        schema = copy.deepcopy(SCHEMA)
        del schema["paths"]["logs"]
        cases.append(schema)
        schema = copy.deepcopy(SCHEMA)
        del schema["document_types"]["prefix"]["wiki/concepts/"]
        cases.append(schema)
        schema = copy.deepcopy(SCHEMA)
        schema["index_sections"]["wiki/missing/"] = "不存在"
        cases.append(schema)
        schema = copy.deepcopy(SCHEMA)
        schema["link_roots"] = ["raw", "wiki", []]
        cases.append(schema)
        schema = copy.deepcopy(SCHEMA)
        schema["schema_version"] = 99
        cases.append(schema)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "schema.json"
            for schema in cases:
                with self.subTest(schema=schema):
                    path.write_text(json.dumps(schema), encoding="utf-8")
                    with self.assertRaises(SchemaError):
                        load_schema(path)

    def test_verification_examples_use_array_profile(self):
        for name in ("source-template.md", "entity-template.md", "concept-template.md", "archive-template.md"):
            with self.subTest(template=name):
                content = load_markdown_template(name)
                frontmatter = content.split("---\n", 2)[1]
                frontmatter = frontmatter.replace("# verified:", "verified:").replace("#   -", "  -")
                metadata = yaml.safe_load(frontmatter)
                self.assertIsInstance(metadata["verified"], list)
                self.assertEqual(set(metadata["verified"][0]), {"by", "at"})


if __name__ == "__main__":
    unittest.main()
