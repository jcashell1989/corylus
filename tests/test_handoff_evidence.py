"""Non-Git attempts surface the handoff comment as run-log evidence (td-4952a9)."""

from __future__ import annotations

import unittest

import hermes_review as hr

BOT = {"id": hr.BOT_USER_ID, "username": hr.BOT_USERNAME}
HUMAN = {"id": 99, "username": "julian"}


def _comment(cid, text, author=BOT, created="2026-08-19T11:00:00-07:00"):
    return {"id": cid, "comment": text, "author": author, "created": created}


class MachineMarkerIdsTests(unittest.TestCase):
    def test_collects_attempt_judge_and_singleton_markers(self):
        machine = {
            "attempts": [{"_comment_id": 3}, {"_comment_id": 1}],
            "judges": [{"_comment_id": 5}],
            "control_comment_id": 2,
            "session_comment_id": None,
            "organizer_comment_id": 5,
        }
        self.assertEqual(hr._machine_marker_ids(machine), [1, 2, 3, 5])


class HandoffCommentTests(unittest.TestCase):
    def test_picks_bot_comment_between_attempt_marker_and_next_marker(self):
        # #80 shape: start note, attempt marker(416), handoff(417), judge
        # marker(422), judge-verdict echo(423). Handoff must win, not 423.
        attempt = {"n": 1, "_comment_id": 416}
        machine = {
            "attempts": [attempt],
            "judges": [{"_comment_id": 422}],
            "control_comment_id": None,
            "session_comment_id": None,
            "organizer_comment_id": None,
        }
        comments = [
            _comment(411, "Starting."),
            _comment(416, "<!-- hermes:attempt v1 -->\n{}"),
            _comment(417, "Handoff — task remains open for review."),
            _comment(422, "<!-- hermes:judge v1 -->\n{}"),
            _comment(423, "Judge verdict: APPROVE"),
        ]
        got = hr._handoff_comment(comments, machine, attempt)
        self.assertIsNotNone(got)
        self.assertEqual(got["id"], 417)

    def test_ignores_comments_from_non_bot_authors(self):
        attempt = {"n": 1, "_comment_id": 1}
        machine = {"attempts": [attempt], "judges": []}
        comments = [
            _comment(1, "<!-- hermes:attempt v1 -->\n{}"),
            _comment(2, "left this note", author=HUMAN),
        ]
        self.assertIsNone(hr._handoff_comment(comments, machine, attempt))

    def test_returns_none_without_attempt_comment_id(self):
        self.assertIsNone(hr._handoff_comment([], {}, {"n": 1}))

    def test_returns_none_when_no_comment_follows_the_marker(self):
        attempt = {"n": 1, "_comment_id": 5}
        machine = {"attempts": [attempt], "judges": []}
        comments = [_comment(5, "<!-- hermes:attempt v1 -->\n{}")]
        self.assertIsNone(hr._handoff_comment(comments, machine, attempt))


class HandoffLogLinesTests(unittest.TestCase):
    def test_splits_handoff_comment_into_paragraph_entries(self):
        attempt = {"n": 1, "_comment_id": 1}
        machine = {"attempts": [attempt], "judges": []}
        comments = [
            _comment(1, "<!-- hermes:attempt v1 -->\n{}"),
            _comment(
                2,
                "First paragraph.\n\nSecond paragraph.",
                created="2026-08-19T11:53-07:00",
            ),
        ]
        lines = hr._handoff_log_lines(comments, machine, attempt)
        self.assertEqual(
            lines,
            [
                {
                    "at": "2026-08-19T11:53-07:00",
                    "level": "handoff",
                    "msg": "First paragraph.",
                },
                {
                    "at": "2026-08-19T11:53-07:00",
                    "level": "handoff",
                    "msg": "Second paragraph.",
                },
            ],
        )

    def test_empty_when_no_handoff_comment_found(self):
        self.assertEqual(hr._handoff_log_lines([], {}, {"n": 1}), [])


if __name__ == "__main__":
    unittest.main()
