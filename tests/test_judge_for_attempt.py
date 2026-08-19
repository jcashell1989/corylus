"""Judge pane uses this attempt, not judges[-1] (td-b2b873).

Run on personal from ~/projects/hermes-review:

    ~/.hermes/hermes-agent/venv/bin/python -m unittest tests.test_judge_for_attempt
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hermes_review as hr


class JudgeForAttemptTests(unittest.TestCase):
    def setUp(self):
        self.judges = [
            {"attempt": 1, "verdict": "remediate", "confidence": 0.2},
            {"attempt": 2, "verdict": "approve", "confidence": 0.9},
        ]

    def test_matches_attempt_not_last(self):
        got = hr.judge_for_attempt(self.judges, 1)
        self.assertEqual(got["verdict"], "remediate")
        self.assertNotEqual(got, self.judges[-1])

    def test_latest_attempt_still_works(self):
        got = hr.judge_for_attempt(self.judges, 2)
        self.assertEqual(got["verdict"], "approve")

    def test_missing_judge_does_not_fall_back_to_previous(self):
        judges = [{"attempt": 1, "verdict": "thin", "confidence": 0.1}]
        raw = hr.judge_for_attempt(judges, 2)
        self.assertEqual(raw, {})
        pane = hr.serialize_judge(raw)
        self.assertIsNone(pane["verdict"])
        self.assertNotEqual(pane["verdict"], "thin")

    def test_no_attempt_number_is_empty(self):
        self.assertEqual(hr.judge_for_attempt(self.judges, 0), {})
        self.assertEqual(hr.judge_for_attempt(self.judges, None), {})


if __name__ == "__main__":
    unittest.main()
