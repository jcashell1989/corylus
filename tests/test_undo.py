"""Undo restores Vikunja snapshot (td-12084f).

Run on personal from ~/projects/hermes-review:

    ~/.hermes/hermes-agent/venv/bin/python -m unittest tests.test_undo
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hermes_review as hr


class LabelOpsTests(unittest.TestCase):
    def test_approve_restore_puts_needs_review_back(self):
        add, remove = hr.label_restore_ops(
            {"judged"}, {"needs-review", "judged"}
        )
        self.assertEqual(add, ["needs-review"])
        self.assertEqual(remove, [])

    def test_human_restore_drops_human_only(self):
        add, remove = hr.label_restore_ops(
            {"human-only", "judged"}, {"needs-review", "judged"}
        )
        self.assertEqual(add, ["needs-review"])
        self.assertEqual(remove, ["human-only"])


class UndoTokenTests(unittest.TestCase):
    def setUp(self):
        hr.UNDO_TOKENS.clear()

    def tearDown(self):
        hr.UNDO_TOKENS.clear()

    def test_unknown_token_does_not_pretend(self):
        with self.assertRaisesRegex(RuntimeError, "no longer available"):
            hr.apply_undo("missing")

    def test_stale_approve_refuses_when_not_done(self):
        token = hr.stash_undo(
            74,
            "approve",
            {"done": False, "percent_done": 0, "labels": ["needs-review"], "control": {}},
        )
        task = {"done": False, "percent_done": 0, "labels": [{"title": "judged"}]}

        class R:
            def __init__(self, data, status=200):
                self._data = data
                self.status_code = status

            def json(self):
                return self._data

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)

        class C:
            def get(self, path):
                if path == "/labels":
                    return R([{"title": "needs-review", "id": 1}, {"title": "judged", "id": 2}])
                return R(task)

        with mock.patch.object(hr, "load_env"), mock.patch.object(
            hr, "_client"
        ) as client_cm, mock.patch.object(hr.hmc, "list_machine", return_value={}):
            client_cm.return_value.__enter__.return_value = C()
            client_cm.return_value.__exit__.return_value = False
            with self.assertRaisesRegex(RuntimeError, "stale"):
                hr.apply_undo(token)
        self.assertIn(token, hr.UNDO_TOKENS)

    def test_restore_rewrites_labels_and_done(self):
        token = hr.stash_undo(
            74,
            "approve",
            {
                "done": False,
                "percent_done": 0,
                "labels": ["needs-review", "judged"],
                "control": {},
            },
        )
        task = {
            "done": True,
            "percent_done": 100,
            "labels": [{"title": "judged"}],
        }
        calls = []

        class R:
            def __init__(self, data, status=200):
                self._data = data
                self.status_code = status

            def json(self):
                return self._data

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(self.status_code)

        class C:
            def get(self, path):
                calls.append(("GET", path))
                if path == "/labels":
                    return R(
                        [
                            {"title": "needs-review", "id": 10},
                            {"title": "judged", "id": 11},
                        ]
                    )
                return R(task)

            def put(self, path, json=None):
                calls.append(("PUT", path, json))
                return R({})

            def post(self, path, json=None):
                calls.append(("POST", path, json))
                return R({})

        with mock.patch.object(hr, "load_env"), mock.patch.object(
            hr, "_client"
        ) as client_cm, mock.patch.object(
            hr.hmc, "list_machine", return_value={}
        ), mock.patch.object(hr.hmc, "upsert_control") as upsert:
            client_cm.return_value.__enter__.return_value = C()
            client_cm.return_value.__exit__.return_value = False
            got = hr.apply_undo(token)
        self.assertEqual(got["ok"], True)
        self.assertNotIn(token, hr.UNDO_TOKENS)
        self.assertTrue(any(c[0] == "PUT" and c[1].endswith("/labels") for c in calls))
        self.assertTrue(
            any(
                c[0] == "POST" and c[1] == "/tasks/74" and c[2].get("done") is False
                for c in calls
            )
        )
        upsert.assert_not_called()


if __name__ == "__main__":
    unittest.main()
