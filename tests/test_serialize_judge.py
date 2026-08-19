"""Empty judges must not serialize as verdict thin (td-b4f126).

Run on personal from ~/projects/hermes-review:

    ~/.hermes/hermes-agent/venv/bin/python -m unittest tests.test_serialize_judge
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hermes_review as hr


class SerializeJudgeTests(unittest.TestCase):
    def test_empty_dict_does_not_invent_thin(self):
        got = hr.serialize_judge({})
        self.assertIsNone(got["verdict"])
        self.assertNotEqual(got["verdict"], "thin")
        self.assertIsNone(got["confidence"])

    def test_none_does_not_invent_thin(self):
        got = hr.serialize_judge(None)
        self.assertIsNone(got["verdict"])
        self.assertIsNone(got["confidence"])
        self.assertIsNone(got["model"])

    def test_empty_judges_list_path(self):
        judges = []
        latest_j = judges[-1] if judges else {}
        got = hr.serialize_judge(latest_j)
        self.assertIsNone(got["verdict"])
        self.assertNotEqual(got.get("verdict"), "thin")

    def test_real_thin_verdict_is_kept(self):
        got = hr.serialize_judge(
            {"verdict": "thin", "confidence": 0.4, "model": "z-ai/glm-5.2"}
        )
        self.assertEqual(got["verdict"], "thin")
        self.assertEqual(got["confidence"], 0.4)
        self.assertEqual(got["model"], "z-ai/glm-5.2")

    def test_approve_passes_through(self):
        got = hr.serialize_judge(
            {"verdict": "approve", "confidence": 0.9, "notes": ["ok"]}
        )
        self.assertEqual(got["verdict"], "approve")
        self.assertEqual(got["notes"], ["ok"])


if __name__ == "__main__":
    unittest.main()
