"""Board list membership for Review (td-893a3b)."""

from __future__ import annotations

import unittest
from unittest import mock

import hermes_review as hr

L = hr.L


class BoardBucketTests(unittest.TestCase):
    def test_blocked(self):
        self.assertEqual(hr._board_bucket({L["blocked"]}), "blocked")

    def test_human_wins_over_blocked(self):
        self.assertEqual(hr._board_bucket({L["blocked"], L["human_only"]}), "human")

    def test_review_wins_over_blocked(self):
        self.assertEqual(hr._board_bucket({L["blocked"], L["needs_review"]}), "review")

    def test_worker_queue(self):
        self.assertEqual(hr._board_bucket({L["worker_ready"]}), "queue")

    def test_blocked_wins_over_stale_worker_lanes(self):
        self.assertEqual(
            hr._board_bucket({L["blocked"], L["worker_ready"]}), "blocked"
        )
        self.assertEqual(
            hr._board_bucket({L["blocked"], L["worker_escalate"]}), "blocked"
        )

    def test_ready_action_does_not_duplicate_existing_worker_ready(self):
        class Response:
            status_code = 204

            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "labels": [
                        {"title": L["blocked"]},
                        {"title": L["worker_ready"]},
                    ]
                }

        class Client:
            def __init__(self):
                self.calls = []

            def get(self, path):
                self.calls.append(("GET", path))
                return Response()

            def put(self, path, json=None):
                self.calls.append(("PUT", path, json))
                return Response()

            def delete(self, path):
                self.calls.append(("DELETE", path))
                return Response()

        client = Client()
        context = mock.MagicMock()
        context.__enter__.return_value = client
        context.__exit__.return_value = False
        with mock.patch.object(hr, "load_env"), mock.patch.object(
            hr, "_client", return_value=context
        ), mock.patch.object(
            hr, "_labels", return_value={
                L["blocked"]: 1,
                L["worker_ready"]: 2,
                L["worker_escalate"]: 3,
            }
        ), mock.patch.object(hr, "_comment") as comment:
            self.assertEqual(hr.blocked_action(8, "ready"), {"ok": True})

        self.assertIn(("DELETE", "/tasks/8/labels/1"), client.calls)
        self.assertNotIn(("PUT", "/tasks/8/labels", {"label_id": 2}), client.calls)
        comment.assert_called_once()

    def test_unclassified(self):
        self.assertIsNone(hr._board_bucket(set()))
