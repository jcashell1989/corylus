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


if __name__ == "__main__":
    unittest.main()
