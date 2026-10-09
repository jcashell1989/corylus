"""Runner projection tests with an anonymized real schema-1 source snapshot.

The fixture preserves representative source columns, timestamps and shape.
Identifiers, repository labels and review heads are synthetic. Paths and URLs
were removed before writing it. Queued/decision records below are test cases.
"""

from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import runner_state as runner


def fixture():
    return json.loads(
        (Path(__file__).parent / "fixtures/runner_state_v1.json").read_text()
    )


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.state = fixture()

    def test_real_shape_is_projected_and_unknown_fields_are_ignored(self):
        self.state["private_extra"] = {"untrusted": "not public"}
        self.state["tickets"][0]["accounting"] = {"usd": 12}
        result = runner.normalize_state(self.state)
        self.assertTrue(result["available"])
        self.assertEqual(result["generated_at"], self.state["generated_at"])
        self.assertEqual(len(result["tickets"]), len(self.state["tickets"]))
        self.assertNotIn("private_extra", result)
        for ticket in result["tickets"]:
            self.assertNotIn("worktree", ticket)
            self.assertNotIn("decision_digest_path", ticket)
            self.assertNotIn("accounting", ticket)
            self.assertNotIn("title", ticket)
            self.assertNotIn("timeline", ticket)

    def test_queue_position_is_never_inferred_from_array_order(self):
        first, held, last = copy.deepcopy(self.state["tickets"][:3])
        first.update(id="td-000010", column="queued")
        held.update(id="td-000011", column="held")
        last.update(id="td-000012", column="queued")
        self.state["tickets"] = [first, held, last]
        result = runner.normalize_state(self.state)
        self.assertEqual(
            [t["queue_position"] for t in result["tickets"]], [None, None, None]
        )
        self.state["tickets"].reverse()
        self.assertTrue(
            all(
                t["queue_position"] is None
                for t in runner.normalize_state(self.state)["tickets"]
            )
        )

    def test_explicit_queue_position_extension_requires_positive_integer(self):
        self.state["tickets"][0]["column"] = "queued"
        for value in (1, 17, None):
            with self.subTest(value=value):
                self.state["tickets"][0]["queue_position"] = value
                result = runner.normalize_state(self.state)
                self.assertEqual(result["tickets"][0]["queue_position"], value)
        for value in (True, False, 0, -1, 1.5, "2", [], {}):
            with self.subTest(value=value):
                self.state["tickets"][0]["queue_position"] = value
                with self.assertRaises(runner.InvalidRunnerState):
                    runner.normalize_state(self.state)

    def test_decision_blockers_and_all_free_text_are_path_free(self):
        ticket = self.state["tickets"][0]
        ticket.update(
            column="needs_decision",
            repo="/private/projects/example-project",
            worktree="/private/worktrees/work",
            decision_digest_path="/private/decisions/digest.md",
            hold_reason="Waiting for /private/task.json",
            name="Run /private/worktree",
            model="vendor/model-name",
            engine="codex",
            phase="Check ~/private/config and C:\\private\\file on 10.23.45.67",
            blockers=[
                "Read /private/decision.md before approval",
                "See https://internal.invalid/item",
            ],
        )
        self.state["merges"][0]["message"] = "Merged from /private/worktree"
        result = runner.normalize_state(self.state)
        serialized = json.dumps(result)
        for private in ("/private", "C:\\", "10.23.45.67", "internal.invalid"):
            self.assertNotIn(private, serialized)
        self.assertEqual(result["tickets"][0]["repo"], "example-project")
        self.assertEqual(result["tickets"][0]["model"], "vendor/model-name")
        self.assertEqual(
            result["tickets"][0]["blockers"][0], "Read [path] before approval"
        )

    def test_only_safe_github_pr_links_are_exposed(self):
        good = "https://github.com/example/project/pull/123"
        for value, expected in [
            (good, good),
            ("http://github.com/example/project/pull/123", ""),
            ("https://user:pass@github.com/example/project/pull/123", ""),
            ("https://github.com/example/project/pull/123?access=private", ""),
            ("https://github.com.evil.invalid/example/project/pull/123", ""),
            ("https://internal.invalid/example/project/pull/123", ""),
            ("javascript:alert(1)", ""),
        ]:
            with self.subTest(value=value):
                self.state["tickets"][0]["pr_url"] = value
                self.assertEqual(
                    runner.normalize_state(self.state)["tickets"][0]["pr_url"], expected
                )

    def test_legacy_timestamps_and_merge_history_are_not_invented(self):
        self.state["merges"] = [
            {"ticket": "td-000001", "merged_at": "16:20:26", "message": "Merged"},
            {
                "ticket": "td-000001",
                "merged_at": "2026-10-09T16:20:26Z",
                "message": "Merged again",
            },
        ]
        result = runner.normalize_state(self.state)
        self.assertEqual(result["merges"], self.state["merges"])
        self.assertNotIn("merged_today_total", result)

    def test_malformed_fields_fail_closed(self):
        mutations = [
            lambda s: s.update(schema_version=True),
            lambda s: s.update(schema_version=2),
            lambda s: s.update(generated_at="16:20:26"),
            lambda s: s.update(generated_at="2026-10-09T16:20:26"),
            lambda s: s.update(tickets={}),
            lambda s: s.update(merges={}),
            lambda s: s["tickets"].append(s["tickets"][0]),
            lambda s: s["tickets"][0].update(column="launch"),
            lambda s: s["tickets"][0].update(column=[]),
            lambda s: s["tickets"][0].update(id="../../file"),
            lambda s: s["tickets"][0].update(round=True),
            lambda s: s["tickets"][0].update(round=-1),
            lambda s: s["tickets"][0].update(running="true"),
            lambda s: s["tickets"][0].update(reviewed_head="not-a-head"),
            lambda s: s["tickets"][0].update(blockers="reason"),
            lambda s: s["tickets"][0].update(blockers=[{}]),
            lambda s: s["tickets"][0].update(start_time="99:99:99"),
            lambda s: s["tickets"][0].update(last_event_time="2026-99-09T16:20:26Z"),
            lambda s: s["merges"][0].update(merged_at=None),
        ]
        for index, mutate in enumerate(mutations):
            with self.subTest(index=index):
                state = copy.deepcopy(self.state)
                mutate(state)
                with self.assertRaises(runner.InvalidRunnerState):
                    runner.normalize_state(state)

    def test_lists_and_text_have_bounds(self):
        for key, maximum in [
            ("tickets", runner.MAX_TICKETS),
            ("merges", runner.MAX_MERGES),
        ]:
            with self.subTest(key=key):
                state = copy.deepcopy(self.state)
                state[key] = [{}] * (maximum + 1)
                with self.assertRaises(runner.InvalidRunnerState):
                    runner.normalize_state(state)
        self.state["tickets"][0]["blockers"] = ["x"] * (runner.MAX_BLOCKERS + 1)
        with self.assertRaises(runner.InvalidRunnerState):
            runner.normalize_state(self.state)
        self.state["tickets"][0]["blockers"] = []
        self.state["tickets"][0]["phase"] = "x" * (runner.MAX_TEXT + 1)
        with self.assertRaises(runner.InvalidRunnerState):
            runner.normalize_state(self.state)

    def test_nullable_fields_must_still_exist_in_schema(self):
        for key in ("start_time", "last_event_time", "hold_reason"):
            with self.subTest(key=key):
                state = copy.deepcopy(self.state)
                del state["tickets"][0][key]
                with self.assertRaises(runner.InvalidRunnerState):
                    runner.normalize_state(state)


class ReaderTests(unittest.TestCase):
    def read(self, path):
        with mock.patch.dict(os.environ, {"CORYLUS_RUNNER_STATE_FILE": str(path)}):
            return runner.snapshot_from_environment()

    def test_missing_configuration_is_explicit(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                runner.snapshot_from_environment(),
                {
                    "available": False,
                    "error": "Runner state is not configured",
                },
            )

    def test_reads_updated_snapshot_without_caching_or_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            state = fixture()
            path.write_text(json.dumps(state))
            before = path.read_bytes()
            self.assertTrue(self.read(path)["available"])
            self.assertEqual(path.read_bytes(), before)
            state["tickets"][0]["phase"] = "New recorded event"
            path.write_text(json.dumps(state))
            self.assertEqual(
                self.read(path)["tickets"][0]["phase"], "New recorded event"
            )

    def test_file_errors_and_malformed_json_do_not_expose_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "private-snapshot.json"
            for data in [None, b"{", b"\xff", b"[]", b"{}"]:
                with self.subTest(data=data):
                    if data is not None:
                        path.write_bytes(data)
                    result = self.read(path)
                    self.assertFalse(result["available"])
                    self.assertNotIn(directory, json.dumps(result))
                    self.assertNotIn(path.name, json.dumps(result))

    def test_directories_fifo_and_oversize_files_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(self.read(directory)["available"])
            fifo = Path(directory) / "pipe"
            os.mkfifo(fifo)
            self.assertFalse(self.read(fifo)["available"])
            path = Path(directory) / "large.json"
            with path.open("wb") as handle:
                handle.truncate(runner.MAX_BYTES + 1)
            self.assertFalse(self.read(path)["available"])


if __name__ == "__main__":
    unittest.main()
