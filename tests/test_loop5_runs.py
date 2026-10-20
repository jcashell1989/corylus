"""Synthetic-only hand-counted loop5 observations; no captured production text."""

import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from loop5_runs import RunsStore


def write_fixture(directory: Path) -> dict:
    """Create deterministic fixture sources for Python and real-browser checks.

    Hand count: atlas has 2 finished builds (10m, 30m), 1 timeout, 1 budget,
    1 failed, 1 running. sage has 2 finished judges (REJECT then APPROVE).
    Unknown has one skipped judge and one finished legacy job. Ten runs total.
    td-a001 has two recorded build rounds before its APPROVE.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "serial").mkdir(exist_ok=True)
    start = "2026-10-19T10:"
    entries = [
        ("00:00", "td-a001 build-r1 start"),
        ("10:00", "td-a001 build-r1 FINISHED (exit 0)"),
        ("11:00", "td-a001 judge-r1 start"),
        ("12:00", "td-a001 judge-r1 FINISHED (exit 0)"),
        ("13:00", "td-a001 build-r2 start"),
        ("43:00", "td-a001 build-r2 FINISHED (exit 0)"),
        ("44:00", "td-a001 judge-r2 start"),
        ("45:00", "td-a001 judge-r2 FINISHED (exit 0)"),
        ("46:00", "serial lane1 td-a001 judge-r2 done"),
        ("47:00", "serial lane1 all jobs done"),
        ("00:00", "td-a002 build start"),
        ("01:00", "td-a002 build FAILED (exit 1)"),
        ("02:00", "td-a003 build-s1 start"),
        ("03:00", "td-a003 build-s1 FAILED (exit 1)"),
        ("03:00", "serial lane2 td-a003 build-s1 hit gateway budget; waiting 15m before retry"),
        ("04:00", "td-a004 build start"),
        ("05:00", "td-a004 build FAILED (exit 2)"),
        ("06:00", "serial lane3 td-a004 judge skipped: previous build in this lane failed"),
        ("07:00", "serial lane3 all jobs done"),
        ("08:00", "td-a005 build start"),
        ("09:00", "td-a006 legacy FINISHED (exit 0)"),
    ]
    (directory / "status.txt").write_text(
        "\n".join(
            f'{start}{minute}+00:00 {event}\tloop5={{"purpose":"other"}}'
            for minute, event in entries
        )
        + "\n"
    )
    (directory / "state.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "tickets": [
                    {"id": "td-a001", "points": 3, "column": "stopped"},
                    {"id": "td-a002", "points": 1, "column": "stopped"},
                    {
                        "id": "td-a003",
                        "points": 5,
                        "column": "building",
                        "model": "lab/atlas",
                        "running": True,
                    },
                    {"id": "td-a004", "points": 0, "column": "stopped"},
                    {
                        "id": "td-a005",
                        "points": "",
                        "column": "building",
                        "model": "lab/atlas",
                        "running": True,
                    },
                ],
            }
        )
    )
    (directory / "serial/lane1.txt").write_text(
        "build td-a001 build-r1 /private/root /private/prompt\ncodex td-a001 judge-r1 lab/sage /private/prompt\nbuild td-a001 build-r2 /private/root /private/prompt\ncodex td-a001 judge-r2 lab/sage /private/prompt\n"
    )
    (directory / "serial/lane2.txt").write_text(
        "build td-a003 build /private/root /private/prompt\ncodex td-a003 judge lab/sage /private/prompt\n"
    )
    (directory / "serial/lane3.txt").write_text(
        "build td-a004 build /private/root /private/prompt\ncodex td-a004 judge lab/sage /private/prompt\n"
    )
    (directory / "serial/lane4.txt").write_text(
        "codex td-a005 build lab/atlas /private/prompt\ncodex td-a005 judge lab/sage /private/prompt\n"
    )
    for ticket, label in [
        ("td-a001", "build-r1"),
        ("td-a001", "build-r2"),
        ("td-a002", "build"),
        ("td-a003", "build-s1"),
        ("td-a004", "build"),
        ("td-a005", "build"),
    ]:
        session = directory / f"sessions/omp-{ticket}-{label}"
        session.mkdir(parents=True, exist_ok=True)
        (session / "roles.yml").write_text("modelRoles:\n  default: lab/atlas\n")
    (directory / "td-a001.judge-r1.out.log").write_text(
        "OpenAI Codex v0.0\nmodel: lab/sage\nuser\nmodel: lab/prompt-bait\nVERDICT: APPROVE\n"
    )
    (directory / "td-a001.judge-r2.out.log").write_text(
        "OpenAI Codex v0.0\nmodel: lab/sage\nuser\nmodel: lab/prompt-bait\nVERDICT: APPROVE\n"
    )
    (directory / "td-a001.judge-r1.out").write_text("VERDICT: REJECT\n")
    (directory / "td-a001.judge-r2.out").write_text("VERDICT: APPROVE\n")
    (directory / "td-a002.build.out.log").write_text("Error: Deadline exceeded\n")
    (directory / "td-a003.build-s1.out.log").write_text("Error: ExceededBudget\n")
    (directory / "td-a004.build.out.log").write_text("provider failed\n")
    (directory / "td-a005.build.out.log").write_text(
        "model: lab/atlas\nSYNTHETIC_PRIVATE_OUTPUT /private/full/path .env token=sk-synthetic-never-real\n"
    )
    return {"td-a001": 2, "td-a002": None}


class RunsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.points = write_fixture(self.directory)

    def snapshot(self):
        return RunsStore(self.directory, lambda: self.points).get()

    def test_hand_counted_outcomes_models_and_durations(self):
        snapshot = self.snapshot()
        self.assertTrue(snapshot["available"])
        self.assertEqual(len(snapshot["runs"]), 10)
        self.assertEqual(
            Counter((r["model"], r["state"]) for r in snapshot["runs"]),
            Counter(
                {
                    ("lab/atlas", "finished"): 2,
                    ("lab/atlas", "timed_out"): 1,
                    ("lab/atlas", "waiting_budget"): 1,
                    ("lab/atlas", "failed"): 1,
                    ("lab/atlas", "running"): 1,
                    ("lab/sage", "finished"): 2,
                    ("unknown", "skipped"): 1,
                    ("unknown", "finished"): 1,
                }
            ),
        )
        builds = [r for r in snapshot["runs"] if r["kind"] == "build" and r["state"] == "finished"]
        self.assertEqual([r["duration_seconds"] for r in builds], [600, 1800])
        self.assertEqual([r["points"] for r in builds], [2, 2])
        self.assertEqual([r["points_source"] for r in builds], ["td", "td"])
        self.assertEqual(
            [
                r["verdict"]
                for r in snapshot["runs"]
                if r["kind"] == "judge" and r["state"] == "finished"
            ],
            ["REJECT", "APPROVE"],
        )
        self.assertEqual(
            [r["builder_model"] for r in snapshot["runs"] if r["verdict"]],
            ["lab/atlas", "lab/atlas"],
        )

    def test_lane_current_next_finished_and_wait_retry(self):
        s = self.snapshot()
        lanes = {lane["id"]: lane for lane in s["lanes"]}
        self.assertTrue(lanes["lane1"]["finished"])
        self.assertTrue(lanes["lane3"]["finished"])
        self.assertIsNotNone(lanes["lane3"]["current_run_id"])
        self.assertEqual(lanes["lane2"]["state"], "waiting_budget")
        self.assertEqual(lanes["lane2"]["next_job"]["kind"], "judge")
        current = next(r for r in s["runs"] if r["id"] == lanes["lane2"]["current_run_id"])
        self.assertEqual(current["next_retry"], "2026-10-19T10:18:00+00:00")
        current = next(r for r in s["runs"] if r["id"] == lanes["lane4"]["current_run_id"])
        self.assertEqual(current["kind"], "build")
        self.assertEqual(len(s["queue"]), 2)

    def test_points_fallback_unpointed_and_zero(self):
        runs = self.snapshot()["runs"]
        by_ticket = {r["ticket"]: r for r in runs}
        self.assertEqual(by_ticket["td-a002"]["points"], 1)
        self.assertEqual(by_ticket["td-a002"]["points_source"], "state")
        self.assertEqual(by_ticket["td-a004"]["points"], 0)
        self.assertIsNone(by_ticket["td-a005"]["points"])
        self.assertEqual(by_ticket["td-a005"]["points_source"], "unpointed")

    def test_private_contents_and_paths_never_returned(self):
        output = json.dumps(self.snapshot())
        for private in [
            "SYNTHETIC_PRIVATE_OUTPUT",
            "/private/",
            "sk-synthetic",
            ".env",
            "roles.yml",
            str(self.directory),
        ]:
            self.assertNotIn(private, output)
        with (self.directory / "status.txt").open("a") as file:
            file.write("2026-10-19T11:00:00Z td-a001 sk-syntheticcredential start\n")
        self.assertNotIn("sk-syntheticcredential", json.dumps(self.snapshot()))

    def test_missing_directory_and_provider_failure(self):
        self.assertFalse(RunsStore(self.directory / "missing").get()["available"])

        def broken():
            raise Exception("/private/path token=sk-synthetic")

        snapshot = RunsStore(self.directory, broken).get()
        self.assertTrue(snapshot["available"])
        self.assertIn(
            "Current td points are unavailable; state points are used where recorded.",
            snapshot["warnings"],
        )
        self.assertNotIn("sk-synthetic", json.dumps(snapshot))

    def test_file_and_parent_symlinks_not_read(self):
        secret = self.directory / "bait"
        secret.write_text("model: lab/leaked\nVERDICT: APPROVE\n")
        (self.directory / "td-a004.build.out.log").unlink()
        (self.directory / "td-a004.build.out.log").symlink_to(secret)
        fake = self.directory / "sessions/omp-td-a006-legacy"
        fake.symlink_to(self.directory / "sessions/omp-td-a005-build", target_is_directory=True)
        s = self.snapshot()
        self.assertNotIn("lab/leaked", json.dumps(s))
        legacy = next(r for r in s["runs"] if r["label"] == "legacy")
        self.assertEqual(legacy["model"], "unknown")
        root_link = self.directory / "root-link"
        root_link.symlink_to(self.directory, target_is_directory=True)
        self.assertFalse(RunsStore(root_link).get()["available"])

    def test_reused_label_does_not_backfill_old_file_evidence(self):
        with (self.directory / "status.txt").open("a") as file:
            file.write("2026-10-19T12:00:00Z td-a001 build-r1 start\n")
        runs = [r for r in self.snapshot()["runs"] if r["label"] == "build-r1"]
        self.assertEqual(len(runs), 2)
        self.assertEqual(runs[0]["model"], "unknown")
        self.assertEqual(runs[1]["model"], "lab/atlas")

    def test_queue_round_events_and_association(self):
        (self.directory / "status.txt").write_text(
            "\n".join(
                [
                    "2026-10-19T10:00:00Z td-b001 round 1: implementer start",
                    "2026-10-19T10:10:00Z td-b001 round 1: implementer done; reviewer start (head abc123)",
                    "2026-10-19T10:12:00Z td-b001 round 1: VERDICT: APPROVE",
                ]
            )
        )
        (self.directory / "td-b001.impl.r1.log").write_text(
            "OpenAI Codex v0.0\nmodel: lab/atlas\nuser\n"
        )
        (self.directory / "td-b001.review.r1.log").write_text(
            "OpenAI Codex v0.0\nmodel: lab/sage\nuser\nmodel: lab/prompt-bait\nVERDICT: APPROVE\n"
        )
        runs = self.snapshot()["runs"]
        self.assertEqual(
            [(r["kind"], r["state"], r["duration_seconds"]) for r in runs],
            [("build", "finished", 600), ("judge", "finished", 120)],
        )
        self.assertEqual(runs[1]["builder_model"], "lab/atlas")
        self.assertEqual(runs[1]["verdict"], "APPROVE")

    def test_output_mentions_and_old_files_cannot_classify_current_attempt(self):
        output = self.directory / "td-a005.build.out"
        output.write_text("We document the Deadline exceeded error and ExceededBudget for users.\n")
        run = next(r for r in self.snapshot()["runs"] if r["ticket"] == "td-a005")
        self.assertEqual(run["state"], "running")
        log = self.directory / "td-a005.build.out.log"
        log.write_text("model: lab/stale\nDeadline exceeded\n")
        os.utime(log, (1, 1))
        run = next(r for r in self.snapshot()["runs"] if r["ticket"] == "td-a005")
        self.assertEqual(run["state"], "running")
        self.assertNotEqual(run["model"], "lab/stale")
        self.assertIsNone(run["verdict"])

    def test_explicit_stop_terminates_queue_run_as_unknown(self):
        (self.directory / "status.txt").write_text(
            "\n".join(
                [
                    "2026-10-19T10:00:00Z td-b001 round 1: implementer start",
                    "2026-10-19T10:10:00Z td-b001 NEEDS-DECISION: finish gate failed after nudge",
                    "2026-10-19T10:11:00Z td-b002 round 1: reviewer start",
                    "2026-10-19T10:12:00Z td-b002 round 1: VERDICT: NEEDS-DECISION",
                ]
            )
        )
        runs = self.snapshot()["runs"]
        self.assertEqual([r["state"] for r in runs], ["unknown", "unknown"])
        self.assertTrue(all(r["end_time"] for r in runs))

    def test_queue_does_not_resurrect_old_budget_attempt(self):
        with (self.directory / "status.txt").open("a") as file:
            file.write("2026-10-19T11:00:00Z td-a003 build-s2 start\n")
            file.write("2026-10-19T11:01:00Z td-a003 build-s2 FINISHED (exit 0)\n")
        record = next(q for q in self.snapshot()["queue"] if q["ticket"] == "td-a003")
        self.assertIsNotNone(record["current_run_id"])
        self.assertEqual(record["state"], "finished")
        self.assertEqual(record["label"], "build-s2")
        self.assertIsNone(record["next_retry"])

    def test_prompt_models_and_verdicts_cannot_become_provenance(self):
        (self.directory / "td-a004.build.out.log").write_text(
            "CLI warning\nOpenAI Codex v0.0\nmodel: lab/actual\nuser\nmodel: lab/prompt-bait\nVERDICT: APPROVE\n"
        )
        (self.directory / "td-a004.build.out").write_text("VERDICT: APPROVE\n")
        run = next(
            r for r in self.snapshot()["runs"] if r["ticket"] == "td-a004" and r["kind"] == "build"
        )
        self.assertEqual(run["model"], "lab/actual")
        self.assertIsNone(run["verdict"])
        judge = next(r for r in self.snapshot()["runs"] if r["label"] == "judge-r1")
        self.assertEqual(judge["model"], "lab/sage")
        self.assertEqual(judge["verdict"], "REJECT")

    def test_recorded_75_minute_timeout_is_not_an_elapsed_time_guess(self):
        (self.directory / "status.txt").write_text(
            "2026-10-19T10:00:00Z td-b001 build start\n"
            "2026-10-19T11:15:00Z td-b001 build FAILED (exit 1)\n"
            "2026-10-19T10:00:00Z td-b002 build start\n"
            "2026-10-19T11:15:00Z td-b002 build FAILED (exit 1)\n"
        )
        (self.directory / "td-b001.build.out.log").write_text("Deadline exceeded\n")
        runs = self.snapshot()["runs"]
        self.assertEqual([r["state"] for r in runs], ["timed_out", "failed"])
        self.assertEqual([r["duration_seconds"] for r in runs], [4500, 4500])

    def test_active_session_mtime_is_activity_without_reading_transcript(self):
        (self.directory / "status.txt").write_text("2026-10-19T10:00:00Z td-b001 build start\n")
        session = self.directory / "sessions/omp-td-b001-build"
        session.mkdir(parents=True)
        transcript = session / "messages.jsonl"
        transcript.write_text("SYNTHETIC_TRANSCRIPT_TOKEN sk-never-real\n")
        os.utime(transcript, (1792404300, 1792404300))
        run = self.snapshot()["runs"][0]
        self.assertEqual(run["last_activity"], "2026-10-19T10:05:00+00:00")
        self.assertNotIn("SYNTHETIC_TRANSCRIPT_TOKEN", json.dumps(self.snapshot()))

    def test_current_builder_model_fallback_does_not_rewrite_run_analytics(self):
        (self.directory / "status.txt").write_text(
            "2026-10-19T10:00:00Z td-b001 round 1: implementer start\n"
            "2026-10-19T10:00:00Z td-b002 round 1: reviewer start\n"
        )
        (self.directory / "state.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "tickets": [
                        {
                            "id": "td-b001",
                            "column": "building",
                            "running": True,
                            "model": "lab/current",
                        },
                        {
                            "id": "td-b002",
                            "column": "reviewing",
                            "running": True,
                            "model": "lab/builder",
                        },
                    ],
                }
            )
        )
        snapshot = self.snapshot()
        self.assertEqual([r["model"] for r in snapshot["runs"]], ["unknown", "unknown"])
        queue = {row["ticket"]: row for row in snapshot["queue"]}
        self.assertEqual(queue["td-b001"]["model"], "lab/current")
        self.assertEqual(queue["td-b002"]["model"], "unknown")

    def test_missing_history_or_state_is_reported_without_false_zero_success(self):
        (self.directory / "status.txt").write_text("")
        snapshot = self.snapshot()
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["runs"], [])
        self.assertTrue(
            any("run counts are unavailable" in warning for warning in snapshot["warnings"])
        )
        (self.directory / "status.txt").write_text("2026-10-19T10:00:00Z td-b001 build start\n")
        (self.directory / "state.json").write_text("")
        snapshot = self.snapshot()
        self.assertTrue(snapshot["available"])
        self.assertEqual(snapshot["queue"], [])
        self.assertTrue(
            any(
                "queue and fallback points are unavailable" in warning
                for warning in snapshot["warnings"]
            )
        )

    def test_malformed_records_and_unsupported_schema_are_safe(self):
        (self.directory / "state.json").write_text('{"schema_version":100,"tickets":[]}')
        with (self.directory / "status.txt").open("a") as file:
            file.write(
                "broken time td-a002 build start\n2026-10-19T13:00:00Z td-a008 build start\n"
            )
        s = self.snapshot()
        self.assertEqual(len(s["queue"]), 0)
        self.assertEqual(s["runs"][-1]["model"], "unknown")
        self.assertTrue(s["warnings"])

    def test_unsupported_start_formats_warn_without_inventing_runs(self):
        with (self.directory / "status.txt").open("a") as file:
            file.write("2026-10-19T13:00:00Z legacy-subject old-job start\n")
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot["runs"]), 10)
        self.assertIn(
            "Some older event formats cannot be classified; only recognized recorded runs are counted.",
            snapshot["warnings"],
        )


if __name__ == "__main__":
    unittest.main()
