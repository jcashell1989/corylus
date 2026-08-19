"""Monitor aggregations (td-8f0fa2).

Run on personal from ~/projects/hermes-review:

    ~/.hermes/hermes-agent/venv/bin/python -m unittest tests.test_monitor
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import monitor as mon

TZ = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 8, 19, 10, 0, tzinfo=TZ)


class ParseTests(unittest.TestCase):
    def test_api_call_regex_ignores_msg_lines(self):
        text = (
            "2026-08-18 19:28:18,928 INFO [abc] agent.turn_context: "
            "conversation turn: session=abc model=deepseek/deepseek-v4-flash "
            "msg='secret please ignore'\n"
            "2026-08-18 19:28:40,751 INFO [abc] agent.conversation_loop: "
            "API call #1: model=deepseek/deepseek-v4-flash provider=openrouter "
            "in=100 out=20 total=120 latency=2.5s\n"
        )
        calls = mon.parse_api_calls(text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["model"], "deepseek/deepseek-v4-flash")
        self.assertEqual(calls[0]["inn"], 100)
        self.assertEqual(calls[0]["latency_s"], 2.5)
        blob = str(calls)
        self.assertNotIn("secret", blob)
        self.assertNotIn("msg=", blob)

    def test_preflight_parse(self):
        text = (
            "2026-08-18T17:30:23-07:00 eligible=25 judge_eligible=0 "
            "reaped=0 action=worker_orchestrated,judge_idle\n"
            "not a tick\n"
        )
        ticks = mon.parse_preflight_log(text)
        self.assertEqual(len(ticks), 1)
        self.assertEqual(ticks[0]["eligible"], 25)
        self.assertEqual(ticks[0]["kind"], "preflight")


class SpendTests(unittest.TestCase):
    def test_unknown_model_is_unknown_not_zero(self):
        calls = [
            {
                "model": "mystery/model",
                "inn": 100,
                "out": 10,
            }
        ]
        got = mon.estimate_spend(calls, {})
        self.assertIsNone(got["usd"])
        self.assertEqual(got["unknown"], 1)
        self.assertEqual(got["known"], 0)

    def test_known_model_multiplies_list_prices(self):
        calls = [{"model": "m", "inn": 1000, "out": 100}]
        prices = {"m": {"prompt": 0.001, "completion": 0.002}}
        got = mon.estimate_spend(calls, prices)
        self.assertEqual(got["usd"], 1.2)
        self.assertEqual(got["known"], 1)


class ClaimTests(unittest.TestCase):
    def test_listed_but_not_stranded_while_worker_live(self):
        tasks = [
            {"id": 10, "identifier": "#10", "title": "x", "labels": ["in-progress"]}
        ]
        rows = mon.claim_rows(tasks, "in-progress", worker_live=True, judge_live=False)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["stranded"])
        self.assertEqual(rows[0]["status"], "claimed")

    def test_stranded_when_both_idle(self):
        tasks = [
            {"id": 10, "identifier": "#10", "title": "x", "labels": ["in-progress"]}
        ]
        rows = mon.claim_rows(tasks, "in-progress", worker_live=False, judge_live=False)
        self.assertTrue(rows[0]["stranded"])
        self.assertEqual(rows[0]["status"], "stranded")


class WindowTests(unittest.TestCase):
    def test_window_filter(self):
        now = NOW
        recent = now - timedelta(hours=2)
        old = now - timedelta(days=10)
        self.assertTrue(mon.in_window(recent, "24h", now))
        self.assertFalse(mon.in_window(old, "24h", now))
        self.assertTrue(mon.in_window(old, "all", now))
        self.assertFalse(mon.in_window(None, "7d", now))
        self.assertTrue(mon.in_window(None, "all", now))


class OutcomeTests(unittest.TestCase):
    def test_null_verdict_skipped(self):
        events = [
            {
                "ts": NOW,
                "kind": "judge",
                "verdict": None,
                "id": 1,
                "n": 1,
            },
            {
                "ts": NOW,
                "kind": "judge",
                "verdict": "approve",
                "id": 2,
                "n": 1,
            },
        ]
        m = mon.metrics_for_window(
            events=events,
            calls=[],
            ticks=[],
            window="all",
            now=NOW,
            prices={},
            claims=[],
            depths={"worker": 0, "judge": 0, "review": 1},
            problems_n=0,
        )
        self.assertEqual(m["throughput_judges"], 1)
        self.assertEqual(m["judge_outcomes"], {"approve": 1})
        self.assertNotIn(None, m["judge_outcomes"])
        self.assertNotIn("thin", m["judge_outcomes"])


class BuildTests(unittest.TestCase):
    def test_problems_link_stranded_task(self):
        claims = [
            {
                "id": 74,
                "ref": "#74",
                "title": "x",
                "stranded": True,
                "status": "stranded",
            }
        ]
        probs = mon.problems(
            units={"hermes-gateway": True},
            claims=claims,
            preflight_missing=False,
            preflight_age_s=60,
            worker_used=1,
            worker_cap=3,
            judge_used=0,
            judge_cap=6,
            truncated=[],
        )
        hit = [p for p in probs if p["kind"] == "stranded"]
        self.assertEqual(hit[0]["id"], 74)

    def test_missing_preflight_is_a_problem(self):
        probs = mon.problems(
            units={},
            claims=[],
            preflight_missing=True,
            preflight_age_s=None,
            worker_used=0,
            worker_cap=3,
            judge_used=0,
            judge_cap=6,
            truncated=["open task list hit per_page 100"],
        )
        kinds = {p["kind"] for p in probs}
        self.assertIn("preflight missing", kinds)
        self.assertIn("truncated read", kinds)


class StampTests(unittest.TestCase):
    def test_comment_created_fills_missing_finished_at(self):
        machine = {
            "judges": [{"verdict": "approve", "_comment_id": 9}],
            "attempts": [{"n": 1, "_comment_id": 8}],
        }
        comments = [
            {"id": 8, "created": "2026-08-19T09:00:00-07:00"},
            {"id": 9, "created": "2026-08-19T09:10:00-07:00"},
        ]
        mon.stamp_comment_times(machine, comments)
        self.assertEqual(
            machine["judges"][0]["finished_at"], "2026-08-19T09:10:00-07:00"
        )
        self.assertEqual(
            machine["attempts"][0]["finished_at"], "2026-08-19T09:00:00-07:00"
        )

    def test_does_not_overwrite_existing_finished_at(self):
        machine = {
            "judges": [{"verdict": "approve", "_comment_id": 9, "finished_at": "kept"}]
        }
        mon.stamp_comment_times(machine, [{"id": 9, "created": "other"}])
        self.assertEqual(machine["judges"][0]["finished_at"], "kept")


class EventStampTests(unittest.TestCase):
    def test_assembled_judge_finished_at_counts_in_24h(self):
        ticket = {
            "id": 3,
            "identifier": "#3",
            "labels": ["needs-review"],
            "attempt": {
                "n": 1,
                "finished_at": "2026-08-19T01:54:26-07:00",
                "summary": ["x"],
            },
            "judge": {
                "verdict": "approve",
                "model": "z-ai/glm-5.2",
                "finished_at": "2026-08-19T02:00:00-07:00",
            },
            "judges": [],
            "history": [],
            "disposition": None,
            "chat": [],
        }
        events = mon.events_from_ticket(ticket)
        judges = [e for e in events if e["kind"] == "judge"]
        self.assertEqual(len(judges), 1)
        self.assertEqual(judges[0]["at"], "2026-08-19T02:00:00-07:00")
        self.assertTrue(mon.in_window(judges[0]["ts"], "24h", NOW))
        m = mon.metrics_for_window(
            events=events,
            calls=[],
            ticks=[],
            window="24h",
            now=NOW,
            prices={},
            claims=[],
            depths={},
            problems_n=0,
        )
        self.assertEqual(m["throughput_judges"], 1)
        self.assertEqual(m["judge_outcomes"], {"approve": 1})

    def test_judges_list_does_not_duplicate_pane_judge(self):
        ticket = {
            "id": 3,
            "labels": ["needs-review"],
            "judge": {
                "verdict": "approve",
                "finished_at": "2026-08-19T02:00:00-07:00",
            },
            "judges": [
                {
                    "verdict": "approve",
                    "attempt": 1,
                    "finished_at": "2026-08-19T02:00:00-07:00",
                }
            ],
        }
        events = mon.events_from_ticket(ticket)
        self.assertEqual(sum(1 for e in events if e["kind"] == "judge"), 1)

    def test_history_and_disposition_use_at(self):
        ticket = {
            "id": 72,
            "labels": ["needs-review"],
            "attempt": {"n": 2, "finished_at": "2026-08-16T00:10:31-07:00"},
            "history": [{"at": "2026-08-16T00:10:30-07:00", "head": "attempt 1"}],
            "disposition": {
                "kind": "remediate",
                "at": "2026-08-17T12:00:00-07:00",
            },
        }
        events = mon.events_from_ticket(ticket)
        hist = [
            e
            for e in events
            if e["kind"] == "attempt" and "attempt 1" in (e.get("text") or "")
        ]
        disp = [e for e in events if e["kind"] == "disposition"]
        self.assertIsNotNone(hist[0]["ts"])
        self.assertIsNotNone(disp[0]["ts"])


class CallFeedTests(unittest.TestCase):
    def test_calls_feed_is_newest_first(self):
        old = {
            "at": "2026-07-30 17:55:38",
            "ts": mon.parse_ts("2026-07-30 17:55:38"),
            "kind": "call",
            "model": "old",
        }
        new = {
            "at": "2026-08-19 10:00:00",
            "ts": mon.parse_ts("2026-08-19 10:00:00"),
            "kind": "call",
            "model": "new",
        }
        built = mon.build_monitor(
            assembled=[],
            extra_events=[],
            ticks=[],
            calls=[old, new],
            prices={},
            claims=[],
            depths={},
            units={},
            worker_live=False,
            judge_live=False,
            preflight_missing=False,
            preflight_age_s=None,
            worker_used=0,
            worker_cap=3,
            judge_used=0,
            judge_cap=6,
            truncated=[],
            now=NOW,
        )
        self.assertEqual(built["calls"][0]["model"], "new")
        self.assertEqual(built["calls"][1]["model"], "old")


if __name__ == "__main__":
    unittest.main()
