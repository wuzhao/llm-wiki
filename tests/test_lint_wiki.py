import datetime
import copy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

from lint_wiki import heuristic_checks, split_frontmatter
from wiki_links import build_target_index, resolve_standard_link, resolve_wikilink
from kb_fixture import snapshot, unreadable_directory
from wiki_config import load_markdown_template, load_schema


SCRIPT = SCRIPTS / "lint_wiki.py"
SCHEMA = load_schema()
NOW = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def markdown(metadata, body):
    frontmatter = yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
    return f"---\n{frontmatter}\n---\n\n{body.rstrip()}\n"


def page(document_type, title, body, generated_at=NOW, **extra):
    metadata = {
        "type": document_type,
        "title": title,
        "description": f"{title} 的测试页面。",
        "tags": ["test"],
        "generated": {"by": "llm-wiki-test/0.1.0", "at": generated_at},
    }
    metadata.update(extra)
    return markdown(metadata, body)


class LintWikiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.kb = Path(self.temp.name)
        for relative in SCHEMA["required_paths"]:
            path = self.kb / relative
            if relative == "AGENTS.md":
                path.write_text("# AGENTS.md\n", encoding="utf-8")
            elif relative == SCHEMA["paths"]["index"]:
                sections = "\n\n".join(f"## {name}" for name in SCHEMA["index_sections"].values())
                path.write_text(
                    markdown({"okf_version": SCHEMA["okf_version"]}, f"# 索引\n\n{sections}"),
                    encoding="utf-8",
                )
            elif relative == SCHEMA["paths"]["overview"]:
                path.write_text(
                    page("overview", "概览", "# 概览\n\n当前知识库的测试概览。"),
                    encoding="utf-8",
                )
            elif Path(relative).suffix:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            else:
                path.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.temp.cleanup()

    def write_concept(self, name, extra_body="", generated_at=NOW, **metadata):
        body = (
            f"# {name}\n\n"
            "这是用于验证知识图谱检查的概念页面，包含足够的信息以避免被识别为薄页。"
            "页面内容用于测试链接、孤儿页、冲突和陈旧性检查。\n\n"
            f"{extra_body}\n\n"
            "## 相关概念\n\n暂无。\n\n"
            "## 来源\n\n测试来源。"
        )
        path = self.kb / "wiki" / "concepts" / f"{name}.md"
        path.write_text(page("concept", name, body, generated_at=generated_at, **metadata), encoding="utf-8")
        return path

    def run_lint(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(self.kb), *args],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def add_index_link(self, target):
        index_path = self.kb / SCHEMA["paths"]["index"]
        with index_path.open("a", encoding="utf-8") as index_file:
            index_file.write(f"\n- [[{target}]]\n")

    def render_template(self, template_name):
        now = datetime.datetime.now(datetime.timezone.utc)
        content = load_markdown_template(template_name)
        replacements = {
            "YYYY-MM-DDTHH:MM:SSZ": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "YYYY 年 MM 月": now.strftime("%Y 年 %m 月"),
            "YYYY-MM-DD": now.strftime("%Y-%m-%d"),
            "YYYY-MM": now.strftime("%Y-%m"),
        }
        for placeholder, value in replacements.items():
            content = content.replace(placeholder, value)
        return content

    def test_index_and_self_links_do_not_hide_orphan(self):
        self.write_concept("alpha", "[[concepts/alpha]]")
        self.add_index_link("concepts/alpha")
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[[wiki/concepts/alpha.md]]", result.stdout)
        self.assertIn("孤儿页面，没有其他内容页指向此页", result.stdout)

    def test_content_page_inbound_link_clears_target_orphan(self):
        self.write_concept("alpha")
        self.write_concept("beta", "[[concepts/alpha]]")
        self.add_index_link("concepts/alpha")
        self.add_index_link("concepts/beta")
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        alpha_orphan = "[[wiki/concepts/alpha.md]]\n  发现问题：孤儿页面"
        self.assertNotIn(alpha_orphan, result.stdout)

    def test_wrong_wikilink_path_is_repaired_only_with_unique_knowledge_candidate(self):
        self.write_concept("alpha")
        beta = self.write_concept("beta", "[[wrong/alpha]]")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[[concepts/alpha]]", beta.read_text(encoding="utf-8"))

        outside = self.kb / "templates"
        outside.mkdir()
        (outside / "outside-only.md").write_text("# outside\n", encoding="utf-8")
        gamma = self.write_concept("gamma", "[[wrong/outside-only]]")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[[wrong/outside-only]]", gamma.read_text(encoding="utf-8"))

    def test_wikilink_repair_does_not_cross_raw_and_wiki_roots(self):
        raw = self.kb / "raw" / "alpha.md"
        raw.write_text(
            markdown({"type": "source-material", "title": "alpha"}, "# alpha\n\n原始内容。"),
            encoding="utf-8",
        )
        beta = self.write_concept("beta", "[[wrong/alpha]]\n\n[alpha](missing/alpha.md)")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        beta_content = beta.read_text(encoding="utf-8")
        self.assertIn("[[wrong/alpha]]", beta_content)
        self.assertIn("[alpha](missing/alpha.md)", beta_content)
        self.assertNotIn("修正为 [[raw/alpha", result.stdout)

    def test_explicit_raw_wikilink_is_repaired_within_raw_root(self):
        raw = self.kb / "raw" / "alpha.md"
        raw.write_text(
            markdown({"type": "source-material", "title": "alpha"}, "# alpha\n\n原始内容。"),
            encoding="utf-8",
        )
        beta = self.write_concept("beta", "[[raw/missing/alpha]]")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[[raw/alpha]]", beta.read_text(encoding="utf-8"))

    def test_nested_assets_have_unique_targets_and_separate_repair_candidates(self):
        raw = self.kb / "raw/alpha.md"
        raw.write_text(markdown({"type": "source-material", "title": "alpha"}, "Original material"))
        asset = self.kb / "raw/assets/alpha.md"
        asset.write_text("# Original attachment\n")
        (self.kb / "raw/assets/attachment-only.md").write_text("# Attachment only\n")
        (self.kb / "raw/material-only.md").write_text("# Material only\n")
        index = build_target_index(self.kb, SCHEMA)
        self.assertEqual(index["by_name"]["alpha.md"].count("raw/assets/alpha.md"), 1)
        self.assertEqual(index["by_stem"]["alpha"].count("raw/assets/alpha.md"), 1)
        for resolver, targets in (
            (lambda target: resolve_wikilink("wiki/concepts/beta.md", target, index, SCHEMA),
             ("raw/missing/alpha", "raw/assets/missing/alpha", "raw/missing/attachment-only", "raw/assets/missing/material-only")),
            (lambda target: resolve_standard_link("wiki/concepts/beta.md", target, index),
             ("../../raw/missing/alpha.md", "../../raw/assets/missing/alpha.md", "../../raw/missing/attachment-only.md", "../../raw/assets/missing/material-only.md")),
        ):
            with self.subTest(targets=targets):
                self.assertEqual(resolver(targets[0])["candidates"], ["raw/alpha.md"])
                self.assertEqual(resolver(targets[1])["candidates"], ["raw/assets/alpha.md"])
                self.assertEqual(resolver(targets[2])["candidates"], [])
                self.assertEqual(resolver(targets[3])["candidates"], [])
        beta = self.write_concept("beta", "[[raw/missing/alpha]]\n[[raw/assets/missing/alpha]]")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[[raw/alpha]]", beta.read_text())
        self.assertIn("[[raw/assets/alpha]]", beta.read_text())
        self.assertEqual(asset.read_text(), "# Original attachment\n")

    def test_markdown_attachments_are_linkable_but_never_linted_or_repaired(self):
        attachment = self.kb / "raw/assets/original.md"
        attachment.write_bytes(b"---\ntitle: invalid: yaml\n---\n# Original\n\n[[missing]]\n")
        original = attachment.read_bytes()
        self.write_concept("alpha", "[Attachment](../../raw/assets/original.md)\n[[raw/assets/original]]")
        for scope in ([], ["--lint-dirs", "raw"], ["--lint-files", "wiki/concepts/alpha.md"]):
            with self.subTest(scope=scope):
                result = self.run_lint(*scope, "--fix", "--fail-on", "error")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertNotIn("[[raw/assets/original.md]]", result.stdout)
                self.assertEqual(attachment.read_bytes(), original)
        for scope in (["--lint-files", "raw/assets/original.md"], ["--lint-dirs", "raw/assets"]):
            with self.subTest(scope=scope):
                before = snapshot(self.kb)
                result = self.run_lint(*scope, "--fix")
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertEqual(snapshot(self.kb), before)

    def test_standard_markdown_link_is_repaired_relative_to_current_page(self):
        self.write_concept("alpha")
        beta = self.write_concept("beta", "[Alpha](missing/alpha.md)")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[Alpha](alpha.md)", beta.read_text(encoding="utf-8"))

    def test_duplicate_basenames_and_missing_anchor_are_reported(self):
        self.write_concept("alpha")
        entity = self.kb / "wiki" / "entities" / "alpha.md"
        entity.write_text(
            page(
                "entity",
                "alpha entity",
                "# alpha entity\n\n足够长的实体说明内容，用于验证同名候选不会被脚本猜测。"
                "这里继续补充内容，确保它不会仅仅因为篇幅过短而影响断言。\n\n"
                "## 相关概念\n\n暂无。\n\n## 来源\n\n测试来源。",
            ),
            encoding="utf-8",
        )
        self.write_concept("beta", "[[alpha]]\n\n[[concepts/alpha#不存在的标题]]")
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Wikilink 存在多个同名候选", result.stdout)
        self.assertIn("Wikilink 锚点不存在", result.stdout)

    def test_commented_links_and_external_schemes_are_ignored(self):
        self.write_concept(
            "alpha",
            "<!-- [[missing-commented-page]] -->\n\n[邮件](mailto:test@example.com)",
        )
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("missing-commented-page", result.stdout)
        self.assertNotIn("mailto:test@example.com", result.stdout)

    def test_type_mismatch_and_invalid_verification_date_are_reported(self):
        path = self.write_concept("alpha", verified_at="not-a-date")
        content = path.read_text(encoding="utf-8").replace("type: concept", "type: entity", 1)
        path.write_text(content, encoding="utf-8")
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Frontmatter type 与路径不一致", result.stdout)
        self.assertIn("verified_at 不是有效的 ISO 8601 时间", result.stdout)

    def test_symlink_to_file_outside_knowledge_base_is_skipped(self):
        outside_directory = tempfile.TemporaryDirectory()
        self.addCleanup(outside_directory.cleanup)
        outside = Path(outside_directory.name) / "outside.md"
        outside.write_text("# outside\n", encoding="utf-8")
        (self.kb / "wiki" / "concepts" / "outside.md").symlink_to(outside)
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_unresolved_conflict_and_stale_page_are_reported(self):
        conflict = (
            "> ⚠️ 注意：以下内容存在观点冲突，暂不做删旧保新。\n\n"
            "### 观点 A\n\n- 结论：支持。\n- 来源：来源 A\n\n"
            "### 观点 B\n\n- 结论：不支持。\n- 来源：来源 B\n\n"
            "### 当前处理\n\n- 状态：并存\n- 原因：待复核。"
        )
        self.write_concept("conflicted", conflict, generated_at="2020-01-01T00:00:00Z")
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("存在尚未解决的冲突", result.stdout)
        self.assertIn("未核验", result.stdout)

    def test_fix_creates_monthly_log(self):
        self.write_concept("alpha")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        log_paths = list((self.kb / "wiki" / "logs").glob("*.md"))
        self.assertEqual(len(log_paths), 1)
        log_path = log_paths[0]
        month = log_path.stem
        log_content = log_path.read_text(encoding="utf-8")
        log_metadata = yaml.safe_load(log_content.split("---\n", 2)[1])
        self.assertEqual(log_metadata["generated"]["by"], "llm-wiki/0.1.0")
        self.assertNotIn("timestamp", log_metadata)
        self.assertIn(f"# Wiki Log {month[:4]}-{month[4:]}", log_content)
        self.assertIn("lint | mode=fix", log_content)

    def test_raw_profile_does_not_require_wiki_recommended_fields(self):
        raw = self.kb / "raw" / "minimal.md"
        raw.write_text(markdown({"type": "source-material"}, "# minimal\n\n原始内容。"), encoding="utf-8")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        updated = raw.read_text(encoding="utf-8")
        self.assertIn("title: minimal", updated)
        self.assertNotIn("description:", updated)
        self.assertNotIn("tags:", updated)
        self.assertNotIn("Frontmatter 缺少推荐字段 description", result.stdout)
        self.assertNotIn("Frontmatter 缺少推荐字段 tags", result.stdout)

    def test_raw_metadata_repair_preserves_body_bytes_and_source_fields(self):
        target = self.kb / "raw" / "target.md"
        target.write_text(markdown({"type": "source-material", "title": "target"}, "# target\n"))
        raw = self.kb / "raw" / "source.md"
        metadata = {
            "resource": "https://example.com/article",
            "source_url": "https://example.com/article",
            "timestamp": "2026-10-17T08:30:00Z",
            "custom": {"captured_by": "original-tool"},
        }
        body = '\r\n# source\r\n\r\n[Source](missing/target.md)  \r\n[[raw/missing/target]]\r\n\r\n'
        header = yaml.safe_dump(metadata, sort_keys=False).replace("\n", "\r\n")
        raw.write_bytes(("---\r\n" + header + "---\r\n" + body).encode("utf-8"))

        result = self.run_lint("--fix", "--fail-on", "error")
        self.assertEqual(result.returncode, 1, result.stderr)
        _, repaired, actual_body, error = split_frontmatter(raw.read_bytes().decode("utf-8"))
        self.assertEqual(error, "")
        self.assertEqual(actual_body.encode("utf-8"), body.encode("utf-8"))
        self.assertEqual(repaired["type"], "source-material")
        self.assertEqual(repaired["title"], "source")
        for key, value in metadata.items():
            self.assertEqual(repaired[key], value)
        self.assertIn("raw 正文只读", result.stdout)
        self.assertIn("需要人工介入 (2)", result.stdout)

        before = raw.read_bytes()
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(raw.read_bytes(), before)

    def test_raw_missing_frontmatter_keeps_entire_original_body(self):
        raw = self.kb / "raw" / "source.md"
        original = b'# source\r\n\r\n[Original](missing.md)  \r\n\r\n'
        raw.write_bytes(original)
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        _, metadata, body, error = split_frontmatter(raw.read_bytes().decode("utf-8"))
        self.assertEqual(error, "")
        self.assertEqual(metadata["type"], "source-material")
        self.assertEqual(body.encode("utf-8"), original)

    def test_invalid_raw_frontmatter_remains_byte_identical(self):
        raw = self.kb / "raw" / "source.md"
        original = b'---\r\ntype: source-material\r\ntitle: a: b\r\n---\r\n# source\r\n'
        raw.write_bytes(original)
        result = self.run_lint("--fix", "--fail-on", "error")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(raw.read_bytes(), original)

    def test_rendered_init_templates_are_lint_clean(self):
        (self.kb / SCHEMA["paths"]["index"]).write_text(
            self.render_template("index-template.md"),
            encoding="utf-8",
        )
        (self.kb / SCHEMA["paths"]["overview"]).write_text(
            self.render_template("overview-template.md"),
            encoding="utf-8",
        )
        month = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m")
        (self.kb / SCHEMA["paths"]["logs"] / f"{month}.md").write_text(
            self.render_template("log-template.md"),
            encoding="utf-8",
        )
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("发现问题 0", result.stdout)

    def test_fix_updates_index_okf_version_without_duplicate_key(self):
        index = self.kb / SCHEMA["paths"]["index"]
        index.write_text(
            markdown({"okf_version": "0.1"}, "# 索引"),
            encoding="utf-8",
        )
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        content = index.read_text(encoding="utf-8")
        self.assertEqual(content.count("okf_version:"), 1)
        metadata = yaml.safe_load(content.split("---\n", 2)[1])
        self.assertEqual(metadata["okf_version"], SCHEMA["okf_version"])

    def test_invalid_yaml_is_reported_without_rewrite(self):
        path = self.kb / "wiki" / "concepts" / "invalid.md"
        original = "---\ntype: concept\ntitle: 标题: 非法\n---\n\n# invalid\n"
        path.write_text(original, encoding="utf-8")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("YAML frontmatter 无法解析", result.stdout)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_incomplete_frontmatter_is_reported_without_rewrite(self):
        path = self.kb / "wiki" / "concepts" / "incomplete.md"
        original = "---\ntype: concept\ntitle: incomplete\n\n# incomplete\n"
        path.write_text(original, encoding="utf-8")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("YAML frontmatter 分隔符不完整", result.stdout)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_report_only_keeps_original_line_numbers_when_frontmatter_is_missing(self):
        path = self.kb / "wiki" / "concepts" / "no-frontmatter.md"
        original = "# no frontmatter\n\n[[missing-page]]\n"
        path.write_text(original, encoding="utf-8")
        result = self.run_lint("--dry-run")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[[wiki/concepts/no-frontmatter.md]]:3", result.stdout)
        self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_page_limits_are_read_from_schema(self):
        schema = copy.deepcopy(SCHEMA)
        schema["limits"]["max_page_lines"] = 2
        body = "# 标题\n第一行\n第二行\n第三行"
        issues = heuristic_checks(
            "wiki/concepts/limit.md",
            body,
            {"type": "concept"},
            schema,
        )
        self.assertTrue(any(issue["problem"] == "页面超过体积阈值" for issue in issues))


    def test_partial_lint_keeps_index_and_uses_external_inbound_links(self):
        self.write_concept("alpha")
        (self.kb / "wiki/entities/beta.md").write_text(page("entity", "beta", "[[concepts/alpha]]"))
        self.add_index_link("concepts/alpha")
        original = (self.kb / "wiki/index.md").read_bytes()
        result = self.run_lint("--lint-dirs", "wiki/concepts", "--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("孤儿页面", result.stdout)
        self.assertNotIn("index 缺少条目", result.stdout)
        self.assertEqual((self.kb / "wiki/index.md").read_bytes(), original)

    def test_post_write_file_check_fails_then_passes_without_writes(self):
        changed = self.write_concept("alpha", "[[concepts/rga]]")
        old = self.kb / "wiki/entities/old.md"
        old.write_text(page("entity", "old", "[[concepts/alpha]]\n[[unrelated-old-error]]"))
        self.add_index_link("concepts/alpha")
        self.add_index_link("entities/old")
        before = snapshot(self.kb)

        result = self.run_lint("--lint-files", "wiki/concepts/alpha.md", "--fail-on", "error")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("concepts/rga", result.stdout)
        self.assertNotIn("unrelated-old-error", result.stdout)
        self.assertNotIn("孤儿页面", result.stdout)
        self.assertEqual(snapshot(self.kb), before)

        changed.write_text(changed.read_text().replace("[[concepts/rga]]", "[[#alpha]]"))
        before = snapshot(self.kb)
        result = self.run_lint("--lint-files", "wiki/concepts/alpha.md", "--fail-on", "error")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(snapshot(self.kb), before)

    def test_file_scope_always_checks_index_links(self):
        self.write_concept("alpha")
        self.add_index_link("concepts/alpha")
        self.add_index_link("concepts/deleted")
        result = self.run_lint("--lint-files", "wiki/concepts/alpha.md", "--fail-on", "error")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("concepts/deleted", result.stdout)

    def test_invalid_file_scope_fails_before_any_writes(self):
        self.write_concept("alpha")
        before = snapshot(self.kb)
        for arguments in (
            ("--lint-files", "wiki/concepts/missing.md"),
            ("--lint-files", "AGENTS.md"),
            ("--lint-files", "../outside.md"),
            ("--lint-files", "wiki/concepts/alpha.md", "--lint-dirs", "wiki/concepts"),
        ):
            with self.subTest(arguments=arguments):
                result = self.run_lint(*arguments, "--fix")
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(snapshot(self.kb), before)

    def test_historical_log_is_unchanged_and_current_log_only_appends(self):
        self.write_concept("alpha")
        old = self.kb / "wiki/logs/200001.md"
        old.write_text("# historical log\n[[wrong/alpha]]\n")
        month = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m")
        current = self.kb / "wiki/logs" / f"{month}.md"
        current.write_text("# current log\n[[wrong/alpha]]\n")
        original, prefix = old.read_bytes(), current.read_bytes()
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(old.read_bytes(), original)
        self.assertTrue(current.read_bytes().startswith(prefix))
        self.assertIn("lint | mode=fix", current.read_text())

    def test_external_log_symlink_stops_all_fixes(self):
        page_path = self.write_concept("alpha")
        page_path.write_text("# alpha\n")
        with tempfile.TemporaryDirectory() as external:
            target = Path(external) / "outside.md"
            target.write_text("outside\n")
            month = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m")
            (self.kb / "wiki/logs" / f"{month}.md").symlink_to(target)
            before = snapshot(self.kb)
            result = self.run_lint("--fix")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(snapshot(self.kb), before)
            self.assertEqual(target.read_text(), "outside\n")

    def test_invalid_yaml_and_duplicate_keys_protect_entire_file(self):
        self.write_concept("alpha")
        path = self.kb / "wiki/concepts/broken.md"
        for frontmatter in ("type: concept\ntitle: a: b", "type: concept\ntype: entity"):
            with self.subTest(frontmatter=frontmatter):
                original = f"---\n{frontmatter}\n---\n[[wrong/alpha]]\n"
                path.write_text(original)
                result = self.run_lint("--fix")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("YAML frontmatter 无法解析", result.stdout)
                self.assertEqual(path.read_text(), original)

    def test_frontmatter_fix_replaces_fields_and_preserves_unknown_data(self):
        path = self.kb / "wiki/concepts/alpha.md"
        path.write_text('---\ntype: []\ntitle: ""\ncustom: {nested: [1, 2]} # keep\n---\n# alpha\n')
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        content = path.read_text()
        self.assertEqual(content.count("type:"), 1)
        self.assertEqual(content.count("title:"), 1)
        self.assertIn("# keep", content)
        _, metadata, _, error = split_frontmatter(content)
        self.assertEqual(error, "")
        self.assertEqual(metadata["custom"], {"nested": [1, 2]})
        self.assertEqual(metadata["title"], "alpha")

    def test_fix_preserves_code_and_link_attributes_and_resolves_references(self):
        self.write_concept("alpha")
        code = '~~~md\n[[wrong/alpha]]\n~~~\n\n````md\n```\n[[wrong/alpha]]\n```\n````\n\n`[[wrong/alpha]]`'
        path = self.write_concept("beta", code + '\n[A](missing/alpha.md "说明")\n[ref][r]\n[r]: <missing/alpha.md> "标题"')
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        content = path.read_text()
        self.assertIn(code, content)
        self.assertIn('[A](alpha.md "说明")', content)
        self.assertIn('[r]: <alpha.md> "标题"', content)

    def test_self_anchor_reference_links_and_repair_anchor_validation(self):
        self.write_concept("alpha", '[[#alpha]]\n[x][r]\n[r]: not-found.md\n[[wrong/alpha#missing-heading]]')
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("锚点不存在: #alpha", result.stdout)
        self.assertIn("not-found.md", result.stdout)
        self.assertIn("候选目标缺少锚点", result.stdout)
        self.assertIn("[[wrong/alpha#missing-heading]]", (self.kb / "wiki/concepts/alpha.md").read_text())

    def test_sources_check_paths_and_anchors_without_hiding_orphans(self):
        self.write_concept("alpha")
        self.write_concept("beta", sources=[
            {"id": "good", "resource": "alpha.md"},
            {"id": "bad", "resource": "../summaries/missing.md"},
            {"id": "anchor", "resource": "alpha.md#not-found"},
            {"id": "external", "resource": "https://example.com"},
        ])
        result = self.run_lint()
        self.assertIn("来源文件不存在或越界", result.stdout)
        self.assertIn("来源锚点不存在", result.stdout)
        self.assertIn("[[wiki/concepts/alpha.md]]\n  发现问题：孤儿页面", result.stdout)

    def test_report_and_fix_dry_run_preserve_all_files(self):
        path = self.write_concept("alpha")
        path.write_text("# alpha\n[[wrong/alpha]]\n")
        before = snapshot(self.kb)
        for args in ((), ("--dry-run",), ("--fix", "--dry-run")):
            with self.subTest(args=args):
                result = self.run_lint(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(snapshot(self.kb), before)

    def test_second_fix_changes_only_append_only_log(self):
        self.write_concept("alpha", "[[wrong/beta]]")
        self.write_concept("beta", "[[concepts/alpha]]")
        first = self.run_lint("--fix")
        self.assertEqual(first.returncode, 0, first.stderr)
        before = snapshot(self.kb)
        second = self.run_lint("--fix")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertIn("已修复 0", second.stdout)
        after = snapshot(self.kb)
        for name, data in before.items():
            if name.startswith("wiki/logs/"):
                self.assertTrue(after[name].startswith(data))
            else:
                self.assertEqual(after[name], data)

    def test_fail_on_and_report_collision(self):
        path = self.write_concept("alpha", "[[does-not-exist]]")
        before = snapshot(self.kb)
        result = self.run_lint("--fail-on", "error")
        self.assertEqual(result.returncode, 1)
        self.assertIn("does-not-exist", result.stdout)
        result = self.run_lint("--report-file", str(path))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(self.kb), before)

    def test_bad_index_yaml_is_never_rewritten(self):
        self.write_concept("alpha")
        index = self.kb / "wiki/index.md"
        original = "---\nokf_version: [\n---\n[[wrong/alpha]]\n"
        index.write_text(original)
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(index.read_text(), original)


    def test_yaml_alias_cannot_be_broken_by_field_repair(self):
        path = self.kb / "wiki/concepts/alpha.md"
        original = '---\ntype: concept\ntitle: &original ""\ncustom: *original\n---\n# alpha\n'
        path.write_text(original)
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("修复会破坏 YAML 引用", result.stdout)
        self.assertEqual(path.read_text(), original)

    def test_log_failure_reports_completed_writes_without_success(self):
        import contextlib
        import io
        from unittest.mock import patch
        from lint_wiki import main
        path = self.kb / "wiki/concepts/alpha.md"
        path.write_text("# alpha\n")
        out, err = io.StringIO(), io.StringIO()
        with patch("sys.argv", ["lint_wiki.py", str(self.kb), "--fix"]), \
                patch("lint_wiki.create_or_append_log", side_effect=OSError("log unavailable")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main()
        self.assertEqual(code, 2)
        self.assertIn("事务未完成", err.getvalue())
        self.assertIn("wiki/concepts/alpha.md", err.getvalue())
        self.assertEqual(out.getvalue(), "")
        self.assertIn("type: concept", path.read_text())

    def test_report_cannot_overwrite_a_new_monthly_log(self):
        self.write_concept("alpha")
        before = snapshot(self.kb)
        month = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m")
        result = self.run_lint("--fix", "--report-file", str(self.kb / "wiki/logs" / f"{month}.md"))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot(self.kb), before)

    def test_anchor_cache_avoids_repeated_target_reads(self):
        from unittest.mock import patch
        from lint_wiki import scan_links, heading_keys
        self.write_concept("alpha", "## Section\n\n## Section\n")
        index = build_target_index(self.kb, SCHEMA)
        with patch("lint_wiki.heading_keys", wraps=heading_keys) as reader:
            _, issues, _ = scan_links("wiki/concepts/beta.md",
                "[[concepts/alpha#section]]\n[[concepts/alpha#section-1]]", index, SCHEMA)
            self.assertEqual(issues, [])
            self.assertEqual(reader.call_count, 1)

    def test_unused_reference_does_not_hide_orphan(self):
        self.write_concept("alpha")
        self.write_concept("beta", "[unused]: alpha.md")
        result = self.run_lint()
        self.assertIn("[[wiki/concepts/alpha.md]]\n  发现问题：孤儿页面", result.stdout)

    def test_short_complete_pages_and_code_only_pages_do_not_require_padding(self):
        for body in ("准确定义。\n\n## 来源\n\n原始资料。", "```python\npass\n```\n\n## 来源\n"):
            with self.subTest(body=body):
                self.assertEqual(heuristic_checks("wiki/concepts/short.md", body, {"type": "concept"}, SCHEMA), [])
        issues = heuristic_checks("wiki/concepts/empty.md", "\n", {"type": "concept"}, SCHEMA)
        self.assertTrue(any(issue["problem"] == "页面正文为空" for issue in issues))

    def test_index_duplicates_sections_and_counts_are_reported_without_reordering(self):
        self.write_concept("alpha")
        index = self.kb / "wiki/index.md"
        content = self.render_template("index-template.md")
        content = content.replace("## 实体", "## 实体\n\n- [[concepts/alpha]]\n- [Alpha](concepts/alpha.md)")
        index.write_text(content, encoding="utf-8")
        original = index.read_bytes()
        result = self.run_lint("--lint-files", "wiki/concepts/alpha.md", "--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        for problem in ("index 重复条目", "index 条目分区不一致", "index 统计不一致: 概念 为 0，实际为 1"):
            self.assertIn(problem, result.stdout)
        self.assertEqual(index.read_bytes(), original)

    def test_partial_index_counts_include_other_directories_and_ignore_code_examples(self):
        self.write_concept("alpha")
        (self.kb / "wiki/entities/beta.md").write_text(page("entity", "beta", "[[concepts/alpha]]"))
        index = self.kb / "wiki/index.md"
        content = self.render_template("index-template.md").replace("实体: 0", "实体: 1").replace("概念: 0", "概念: 1")
        content = content.replace("## 概念", "## 概念\n\n- [[concepts/alpha]]\n\n```markdown\n[[concepts/alpha]]\n```")
        content = content.replace("## 实体", "## 实体\n\n- [[entities/beta]]")
        index.write_text(content, encoding="utf-8")
        result = self.run_lint("--lint-files", "wiki/concepts/alpha.md")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("index 重复条目", result.stdout)
        self.assertNotIn("index 条目分区不一致", result.stdout)
        self.assertNotIn("index 统计不一致", result.stdout)

    def test_lint_reads_markdown_once_for_checks_provenance_anchors_and_backlinks(self):
        import contextlib
        import io
        from collections import Counter
        from unittest.mock import patch
        from lint_wiki import main
        self.write_concept("alpha", "## Details\n")
        (self.kb / "wiki/entities/beta.md").write_text(page("entity", "beta", "[[concepts/alpha#details]]"))
        (self.kb / "raw/source.md").write_text(page("source-material", "source", "Evidence"))
        self.add_index_link("concepts/alpha#details")
        counts = Counter()
        read_bytes, read_text = Path.read_bytes, Path.read_text

        def counted(method):
            def read(path, *args, **kwargs):
                if path.resolve().is_relative_to(self.kb.resolve()) and path.suffix == ".md":
                    counts[path] += 1
                return method(path, *args, **kwargs)
            return read

        before = snapshot(self.kb)
        with patch.object(Path, "read_bytes", counted(read_bytes)), patch.object(Path, "read_text", counted(read_text)), \
                patch("sys.argv", [str(SCRIPT), str(self.kb), "--lint-files", "wiki/concepts/alpha.md"]), \
                contextlib.redirect_stdout(io.StringIO()):
            result = main()
        self.assertEqual(result, 0)
        self.assertTrue(counts)
        self.assertTrue(all(count == 1 for count in counts.values()), counts)
        self.assertEqual(snapshot(self.kb), before)

    def test_unreadable_directory_blocks_repairs_and_coverage_conclusions(self):
        import contextlib
        import io
        from unittest.mock import patch
        from lint_wiki import main, scan_links
        hidden = self.kb / "wiki/concepts/hidden"
        for name in ("hidden", "visible"):
            directory = self.kb / "wiki/concepts" / name
            directory.mkdir()
            (directory / "alpha.md").write_text(page("concept", "alpha", "Alpha"))
        changed = self.write_concept("changed", "[[missing/alpha]]\n[Alpha](missing/alpha.md)")
        changed.write_text(changed.read_text().replace("type: concept\n", "", 1))
        before = snapshot(self.kb)
        with unreadable_directory(hidden):
            partial_index = build_target_index(self.kb, SCHEMA)
            text = "[[missing/alpha]]\n[Alpha](missing/alpha.md)"
            proposed, issues, _ = scan_links("wiki/concepts/changed.md", text, partial_index, SCHEMA, apply_fixes=True)
        self.assertEqual(len(partial_index["by_stem"]["alpha"]), 1)
        self.assertEqual(proposed, text)
        self.assertTrue(issues)
        self.assertTrue(all(not issue["is_auto"] for issue in issues))

        for inventory_only in (False, True):
            for mode in ([], ["--fix"], ["--fix", "--dry-run"]):
                with self.subTest(inventory_only=inventory_only, mode=mode):
                    complete_index = build_target_index(self.kb, SCHEMA)
                    output, error = io.StringIO(), io.StringIO()
                    with contextlib.ExitStack() as stack:
                        if inventory_only:
                            stack.enter_context(patch("lint_wiki.build_target_index", return_value=complete_index))
                        stack.enter_context(unreadable_directory(hidden))
                        stack.enter_context(patch("sys.argv", [str(SCRIPT), str(self.kb), "--lint-files", "wiki/concepts/changed.md", *mode]))
                        stack.enter_context(contextlib.redirect_stdout(output))
                        stack.enter_context(contextlib.redirect_stderr(error))
                        status = main()
                    self.assertEqual(status, 2, output.getvalue() + error.getvalue())
                    self.assertIn("wiki/concepts/hidden", output.getvalue())
                    self.assertIn("覆盖不完整", output.getvalue())
                    self.assertNotIn("孤儿页面", output.getvalue())
                    self.assertNotIn("index 统计不一致", output.getvalue())
                    self.assertEqual(snapshot(self.kb), before)

    def test_reference_index_sections_use_link_occurrences_not_definitions(self):
        self.write_concept("alpha")
        index = self.kb / "wiki/index.md"
        cases = (
            ("[Alpha][a]", "[a]: concepts/alpha.md"),
            ("[Alpha][]", "[Alpha]: concepts/alpha.md"),
            ("[Alpha]", "[Alpha]: concepts/alpha.md"),
            ("[Alpha](concepts/alpha.md)", "[Alpha]: concepts/alpha.md"),
        )
        for use, definition in cases:
            with self.subTest(use=use):
                content = markdown({"okf_version": "0.2"},
                                   f"# 索引\n\n## 概念\n\n- {use}\n\n## 主题聚合\n\n{definition}")
                index.write_text(content)
                before = snapshot(self.kb)
                result = self.run_lint("--lint-files", "wiki/concepts/alpha.md")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("index 条目分区不一致", result.stdout)
                self.assertNotIn("index 重复条目", result.stdout)
                self.assertNotIn("index 缺少条目", result.stdout)
                self.assertEqual(snapshot(self.kb), before)

    def test_repeated_reference_index_entries_report_the_actual_use_line(self):
        from lint_wiki import check_index_consistency
        self.write_concept("alpha")
        content = markdown({"okf_version": "0.2"},
                           "# 索引\n\n## 概念\n\n- [Alpha][a]\n\n## 实体\n\n- [Again][a]\n\n## 主题聚合\n\n[a]: concepts/alpha.md")
        issues = check_index_consistency(content, {"wiki/concepts/alpha.md"}, build_target_index(self.kb, SCHEMA), SCHEMA)
        use_line = content[:content.index("[Again]")].count("\n") + 1
        self.assertEqual(len(issues), 2, issues)
        self.assertTrue(all(issue["line"] == use_line for issue in issues))
        self.assertTrue(any("index 重复条目" in issue["problem"] for issue in issues))
        self.assertTrue(any("位于 实体，应为 概念" in issue["problem"] for issue in issues))

    def test_shared_reference_definition_is_safely_repaired_once(self):
        self.write_concept("alpha")
        changed = self.write_concept("beta", "[Alpha][a]\n[Again][a]\n\n[a]: missing/alpha.md 'original title'\n[unused]: missing/unused.md")
        result = self.run_lint("--fix")
        self.assertEqual(result.returncode, 0, result.stderr)
        body = changed.read_text()
        self.assertIn("[a]: alpha.md 'original title'", body)
        self.assertIn("[Alpha][a]\n[Again][a]", body)
        self.assertIn("[unused]: missing/unused.md", body)


if __name__ == "__main__":
    unittest.main()
