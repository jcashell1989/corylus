"""Write-auth gate for Hermes Review (td-c5dcda).

Run on personal from ~/projects/hermes-review:

    ~/.hermes/hermes-agent/venv/bin/python -m unittest tests.test_write_auth
"""
from __future__ import annotations

import http.client
import json
import sys
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import hermes_review as hr

VIKUNJA = AssertionError("gate leaked a Vikunja write")


class WriteAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), hr.Handler)
        cls.port = cls.httpd.server_address[1]
        t = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        t.start()
        cls.thread = t

    @classmethod
    def tearDownClass(cls) -> None:
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def conn(self) -> http.client.HTTPConnection:
        return http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)

    def good_host(self) -> str:
        return f"{hr.HOST}:{self.port}"

    def headers(self, token: str | None = "good", host: str | None = "good", **extra):
        h = {"Content-Type": "application/json"}
        if host == "good":
            h["Host"] = self.good_host()
        elif host:
            h["Host"] = host
        if token == "good":
            h[hr.TOKEN_HEADER] = hr.WRITE_TOKEN
        elif token:
            h[hr.TOKEN_HEADER] = token
        h.update(extra)
        return h

    def test_get_wrong_host_is_403_and_hides_token(self) -> None:
        c = self.conn()
        c.request("GET", "/", headers={"Host": "evil.example"})
        r = c.getresponse()
        body = r.read().decode()
        self.assertEqual(r.status, 403)
        self.assertNotIn(hr.WRITE_TOKEN, body)
        self.assertNotIn("{{HERMES_REVIEW_TOKEN}}", body)

    def test_get_index_injects_token(self) -> None:
        c = self.conn()
        c.request("GET", "/", headers={"Host": self.good_host()})
        r = c.getresponse()
        page = r.read().decode()
        self.assertEqual(r.status, 200)
        self.assertIn(hr.WRITE_TOKEN, page)
        self.assertNotIn("{{HERMES_REVIEW_TOKEN}}", page)

    def test_get_board_stays_open_with_bind_host(self) -> None:
        c = self.conn()
        with mock.patch.object(hr, "build_board", return_value={"tasks": []}) as board:
            c.request("GET", "/api/board", headers={"Host": self.good_host()})
            r = c.getresponse()
            body = json.loads(r.read())
        self.assertEqual(r.status, 200)
        self.assertEqual(body, {"tasks": []})
        board.assert_called_once()

    def test_post_without_token_is_403_and_does_not_write(self) -> None:
        c = self.conn()
        with (
            mock.patch.object(hr, "apply_decision", side_effect=VIKUNJA) as decide,
            mock.patch.object(hr, "human_action", side_effect=VIKUNJA),
        ):
            c.request(
                "POST",
                "/api/tasks/74/decide",
                body=b'{"kind":"approve"}',
                headers=self.headers(token=None),
            )
            r = c.getresponse()
            body = r.read()
        self.assertEqual(r.status, 403)
        self.assertNotIn(hr.WRITE_TOKEN.encode(), body)
        decide.assert_not_called()

    def test_post_wrong_token_is_403_and_does_not_write(self) -> None:
        c = self.conn()
        with mock.patch.object(hr, "apply_decision", side_effect=VIKUNJA) as decide:
            c.request(
                "POST",
                "/api/tasks/74/decide",
                body=b'{"kind":"approve"}',
                headers=self.headers(token="nope"),
            )
            r = c.getresponse()
            r.read()
        self.assertEqual(r.status, 403)
        decide.assert_not_called()

    def test_post_wrong_host_is_403_even_with_token(self) -> None:
        c = self.conn()
        with mock.patch.object(hr, "apply_decision", side_effect=VIKUNJA) as decide:
            c.request(
                "POST",
                "/api/tasks/74/decide",
                body=b'{"kind":"approve"}',
                headers=self.headers(host="evil.example"),
            )
            r = c.getresponse()
            r.read()
        self.assertEqual(r.status, 403)
        decide.assert_not_called()

    def test_post_localhost_host_is_403_when_bound_elsewhere(self) -> None:
        c = self.conn()
        with mock.patch.object(hr, "HOST", "review.internal"), mock.patch.object(
            hr, "apply_decision", side_effect=VIKUNJA
        ) as decide:
            c.request(
                "POST",
                "/api/tasks/74/decide",
                body=b'{"kind":"approve"}',
                headers=self.headers(host=f"localhost:{self.port}"),
            )
            r = c.getresponse()
            r.read()
        self.assertEqual(r.status, 403)
        decide.assert_not_called()

    def test_post_undo_without_token_is_403_and_does_not_write(self) -> None:
        c = self.conn()
        with mock.patch.object(hr, "apply_undo", side_effect=VIKUNJA) as undo:
            c.request(
                "POST",
                "/api/undo",
                body=json.dumps({"token": "x"}),
                headers=self.headers(token=None),
            )
            r = c.getresponse()
            r.read()
        self.assertEqual(r.status, 403)
        undo.assert_not_called()

    def test_post_good_token_reaches_decide_mock(self) -> None:

        c = self.conn()
        with mock.patch.object(
            hr, "apply_decision", return_value={"ok": True, "id": 74}
        ) as decide:
            c.request(
                "POST",
                "/api/tasks/74/decide",
                body=b'{"kind":"approve","note":""}',
                headers=self.headers(),
            )
            r = c.getresponse()
            body = json.loads(r.read())
        self.assertEqual(r.status, 200)
        self.assertEqual(body, {"ok": True, "id": 74})
        decide.assert_called_once_with(74, "approve", "", None)

    def test_keep_alive_after_403_still_serves(self) -> None:
        c = self.conn()
        with mock.patch.object(hr, "apply_decision", side_effect=VIKUNJA):
            c.request(
                "POST",
                "/api/tasks/74/decide",
                body=b'{"kind":"approve"}',
                headers=self.headers(token=None),
            )
            r = c.getresponse()
            r.read()
            self.assertEqual(r.status, 403)
        c.request("GET", "/", headers={"Host": self.good_host()})
        r = c.getresponse()
        page = r.read().decode()
        self.assertEqual(r.status, 200)
        self.assertIn(hr.WRITE_TOKEN, page)

    def test_app_js_sends_header(self) -> None:
        js = (hr.STATIC / "app.js").read_text(encoding="utf-8")
        self.assertIn("X-Hermes-Review-Token", js)
        self.assertIn("window.HERMES_REVIEW_TOKEN", js)


if __name__ == "__main__":
    unittest.main()
