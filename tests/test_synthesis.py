import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from kb_fixture import ROOT, initialize_kb, snapshot, unreadable_directory
from synthesis_wiki import CHECKPOINT_PREFIX, build_plan
from test_lint_wiki import page
from wiki_config import load_schema
from wiki_metadata import split_frontmatter


class SynthesisTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.kb = initialize_kb(self.temporary.name)
        self.schema = load_schema()
        self.log = next((self.kb / "wiki/logs").glob("*.md"))

    def tearDown(self):
        self.temporary.cleanup()

    def add_summary(self, name, content=None, **raw_metadata):
        raw = self.kb / f"raw/{name}.md"
        raw.write_text(page("source-material", name, content or f"Evidence about {name}.",
                            source_id=raw_metadata.pop("source_id", name), **raw_metadata), encoding="utf-8")
        relative = f"wiki/summaries/{name}.md"
        (self.kb / relative).write_text(page(
            "source-summary", name, f"# {name}\n\n## 摘要\n\nSummary of {name}.\n\n## 关键要点\n\nEvidence.",
            sources=[{"id": "raw", "resource": f"../../raw/{name}.md"}],
        ), encoding="utf-8")
        return relative

    def change_metadata(self, relative, **updates):
        path = self.kb / relative
        _, metadata, body, error = split_frontmatter(path.read_text(encoding="utf-8"))
        self.assertFalse(error)
        metadata.update(updates)
        path.write_text("---\n" + yaml.safe_dump(metadata, allow_unicode=True, sort_keys=False).rstrip()
                        + "\n---\n" + body, encoding="utf-8")

    def mark_batch(self, plan, deferred=None):
        for item in plan["batch"]:
            state = {"reviewed_sha256": item["reviewed_sha256"], "deferred": deferred or []}
            if plan["due"]:
                state["reviewed_in"] = plan["review_id"]
            self.change_metadata(item["path"], synthesis=state)

    def append_checkpoint(self, record):
        with self.log.open("a", encoding="utf-8") as output:
            output.write(f"\n## Synthesis review\n\n{record}\n")

    def finish_round(self, force=False):
        plan = build_plan(self.kb, self.schema, force=force)
        while plan["remaining"]:
            self.mark_batch(plan)
            plan = build_plan(self.kb, self.schema, force=force)
        self.assertIsNotNone(plan["checkpoint_record"])
        self.append_checkpoint(plan["checkpoint_record"])
        return plan

    def command(self, script="synthesis_wiki.py", *args):
        return subprocess.run([sys.executable, str(ROOT / "scripts" / script), str(self.kb), *args],
                              text=True, capture_output=True)

    def test_empty_and_incomplete_kbs_are_read_only(self):
        before = snapshot(self.kb)
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(json.loads(result.stdout)["due"])
        self.assertEqual(before, snapshot(self.kb))
        (self.kb / "wiki/entities").rmdir()
        before = snapshot(self.kb)
        result = self.command()
        self.assertEqual(result.returncode, 2)
        self.assertEqual(before, snapshot(self.kb))

    def test_legacy_backlog_resumes_in_a_new_process_and_checkpoints_once(self):
        size = self.schema["limits"]["max_query_read_pages"]
        paths = {self.add_summary(f"legacy-{number}") for number in range(size + 1)}
        before = snapshot(self.kb)
        first = self.command()
        self.assertEqual(first.returncode, 0, first.stderr)
        first = json.loads(first.stdout)
        self.assertEqual(first["reason"], "bootstrap")
        self.assertEqual(first["remaining"], len(paths))
        self.assertEqual(len(first["batch"]), size)
        self.assertEqual(before, snapshot(self.kb))
        self.mark_batch(first)
        resumed = json.loads(self.command().stdout)
        self.assertEqual(resumed["remaining"], 1)
        self.assertEqual(resumed["review_id"], first["review_id"])
        self.assertIsNone(resumed["checkpoint_record"])
        self.assertFalse({entry["path"] for entry in resumed["batch"]}
                         & {entry["path"] for entry in first["batch"]})
        self.mark_batch(resumed)
        complete = json.loads(self.command().stdout)
        self.assertEqual(complete["remaining"], 0)
        self.assertIsNotNone(complete["checkpoint_record"])
        log_before = self.log.read_bytes()
        self.append_checkpoint(complete["checkpoint_record"])
        self.assertTrue(self.log.read_bytes().startswith(log_before))
        before = snapshot(self.kb)
        done = json.loads(self.command().stdout)
        self.assertFalse(done["due"])
        self.assertIsNone(done["checkpoint_record"])
        self.assertEqual(done["new_source_contents"], 0)
        self.assertEqual(before, snapshot(self.kb))

    def test_period_is_source_content_based_and_not_a_page_creation_quota(self):
        self.add_summary("initial", "Initial evidence.")
        self.finish_round()
        interval = self.schema["limits"]["synthesis_review_interval"]
        for number in range(interval - 1):
            self.add_summary(f"new-{number}")
        plan = build_plan(self.kb, self.schema)
        self.assertFalse(plan["due"])
        self.assertEqual(plan["new_source_contents"], interval - 1)
        self.mark_batch(plan)
        self.assertFalse(build_plan(self.kb, self.schema)["due"])
        self.add_summary("last")
        plan = build_plan(self.kb, self.schema)
        self.assertTrue(plan["due"])
        self.assertEqual(plan["reason"], "interval")
        self.assertEqual(plan["remaining"], interval + 1)
        self.finish_round()
        self.assertEqual(list((self.kb / "wiki/entities").iterdir()), [])
        self.assertEqual(list((self.kb / "wiki/concepts").iterdir()), [])

    def test_duplicate_prose_and_retries_do_not_advance_period(self):
        self.add_summary("original", "Shared source prose.")
        self.finish_round()
        self.add_summary("reprint", "Shared source prose.")
        before = snapshot(self.kb)
        for _ in range(2):
            plan = build_plan(self.kb, self.schema)
            self.assertEqual(plan["new_source_contents"], 0)
            self.assertFalse(plan["due"])
            self.assertEqual(plan["unreviewed"], ["wiki/summaries/reprint.md"])
        self.assertEqual(before, snapshot(self.kb))

    def test_revision_counts_but_bookkeeping_and_navigation_edits_do_not(self):
        relative = self.add_summary("original", "Original prose.", source_id="stable-id")
        self.finish_round()
        path = self.kb / relative
        path.write_text(path.read_text() + "\nRelated navigation text.\n", encoding="utf-8")
        plan = build_plan(self.kb, self.schema)
        self.assertIn(relative, plan["unreviewed"])
        self.assertEqual(plan["new_source_contents"], 0)
        self.mark_batch(plan)
        self.assertEqual(build_plan(self.kb, self.schema)["unreviewed"], [])
        self.add_summary("revision", "Revised evidence.", source_id="stable-id", source_version=2)
        self.assertEqual(build_plan(self.kb, self.schema)["new_source_contents"], 1)

    def test_sources_change_invalidates_review_even_if_prose_does_not(self):
        relative = self.add_summary("original")
        self.finish_round()
        self.add_summary("revision")
        self.change_metadata(relative, sources=[{"id": "raw", "resource": "../../raw/revision.md"}])
        self.assertIn(relative, build_plan(self.kb, self.schema)["unreviewed"])

    def test_consecutive_versions_count_when_summary_keeps_only_latest_citation(self):
        relative = self.add_summary("original", "Original evidence.", source_id="stable-source")
        self.finish_round()
        interval = self.schema["limits"]["synthesis_review_interval"]
        for version in range(interval):
            name = f"revision-{version}"
            raw = self.kb / f"raw/{name}.md"
            raw.write_text(page("source-material", name, f"New evidence in version {version}.",
                                source_id="stable-source", source_version=version + 2), encoding="utf-8")
            self.change_metadata(relative, sources=[{"id": "raw", "resource": f"../../raw/{name}.md"}])
        plan = build_plan(self.kb, self.schema)
        self.assertEqual(plan["new_source_contents"], interval)
        self.assertTrue(plan["due"])
        self.assertEqual(plan["remaining"], 1)

    def test_forced_review_is_resumable_and_does_not_depend_on_interval(self):
        relative = self.add_summary("original")
        first = self.finish_round()
        self.assertFalse(build_plan(self.kb, self.schema)["due"])
        forced = json.loads(self.command("synthesis_wiki.py", "--force").stdout)
        self.assertEqual(forced["reason"], "requested")
        self.assertEqual([item["path"] for item in forced["batch"]], [relative])
        self.assertNotEqual(forced["review_id"], first["review_id"])
        self.mark_batch(forced)
        resumed = build_plan(self.kb, self.schema, force=True)
        self.assertEqual(resumed["remaining"], 0)
        self.assertEqual(resumed["review_id"], forced["review_id"])
        self.append_checkpoint(resumed["checkpoint_record"])
        self.assertFalse(build_plan(self.kb, self.schema)["due"])

    def test_deferred_candidates_survive_without_creating_placeholder_pages(self):
        relative = self.add_summary("mention")
        candidate = {"name": "Cache invalidation", "type": "concept", "aliases": ["缓存失效"],
                     "reason": "Only mentioned", "next_when": "A strategy or example becomes available"}
        plan = build_plan(self.kb, self.schema)
        self.mark_batch(plan, [candidate])
        plan = build_plan(self.kb, self.schema)
        self.assertEqual(plan["deferred"], [{**candidate, "summary": relative}])
        self.assertEqual(plan["remaining"], 0)
        self.assertIsNotNone(plan["checkpoint_record"])
        self.assertEqual(list((self.kb / "wiki/concepts").iterdir()), [])

    def test_unreadable_scope_cannot_produce_a_checkpoint(self):
        self.add_summary("original")
        self.mark_batch(build_plan(self.kb, self.schema))
        hidden = self.kb / "wiki/summaries/blocked"
        hidden.mkdir()
        with unreadable_directory(hidden):
            plan = build_plan(self.kb, self.schema)
        self.assertTrue(plan["read_errors"])
        self.assertIsNone(plan["checkpoint_record"])

    def test_missing_raw_evidence_cannot_complete_a_round(self):
        relative = self.add_summary("original")
        self.change_metadata(relative, sources=[])
        self.mark_batch(build_plan(self.kb, self.schema))
        result = self.command()
        self.assertEqual(result.returncode, 1)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["untraced_summaries"], [relative])
        self.assertIsNone(plan["checkpoint_record"])

    def test_code_example_cannot_act_as_checkpoint_and_malformed_state_is_reported(self):
        self.add_summary("original")
        self.mark_batch(build_plan(self.kb, self.schema))
        record = build_plan(self.kb, self.schema)["checkpoint_record"]
        with self.log.open("a", encoding="utf-8") as output:
            output.write(f"\n```markdown\n{record}\n```\n")
        self.assertEqual(build_plan(self.kb, self.schema)["reason"], "bootstrap")
        self.append_checkpoint(CHECKPOINT_PREFIX + '{"version":1} -->')
        before = snapshot(self.kb)
        result = self.command()
        self.assertEqual(result.returncode, 1)
        plan = json.loads(result.stdout)
        self.assertTrue(plan["read_errors"])
        self.assertIsNone(plan["checkpoint_record"])
        self.assertEqual(before, snapshot(self.kb))
        self.append_checkpoint(record)
        recovered = self.command()
        self.assertEqual(recovered.returncode, 0, recovered.stderr)
        self.assertFalse(json.loads(recovered.stdout)["due"])

    def test_invalid_candidate_state_is_reported_and_not_fixed_by_lint(self):
        relative = self.add_summary("original")
        self.change_metadata(relative, synthesis={"reviewed_sha256": "invalid", "deferred": [{"name": "X"}]})
        original = (self.kb / relative).read_bytes()
        result = self.command()
        self.assertEqual(result.returncode, 1)
        self.assertIn(relative, json.loads(result.stdout)["read_errors"])
        result = self.command("lint_wiki.py", "--lint-files", relative, "--fix", "--fail-on", "error")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("synthesis.reviewed_sha256", result.stdout)
        self.assertEqual((self.kb / relative).read_bytes(), original)

    def test_lint_reports_stale_review_without_refreshing_it(self):
        relative = self.add_summary("original")
        self.finish_round()
        path = self.kb / relative
        path.write_text(path.read_text() + "\nNew finding.\n", encoding="utf-8")
        before = snapshot(self.kb)
        result = self.command("lint_wiki.py", "--lint-files", relative)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("摘要提炼记录与当前内容不一致", result.stdout)
        self.assertEqual(before, snapshot(self.kb))

    def test_new_evidence_invalidates_an_unfinished_round(self):
        self.add_summary("first")
        old = build_plan(self.kb, self.schema)
        self.mark_batch(old)
        self.add_summary("second")
        current = build_plan(self.kb, self.schema)
        self.assertNotEqual(old["review_id"], current["review_id"])
        self.assertEqual(current["remaining"], 2)
        self.assertIsNone(current["checkpoint_record"])


if __name__ == "__main__":
    unittest.main()
