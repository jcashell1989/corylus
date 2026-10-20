"""Runs integration: inherited HTTP guards and read-only current-points lookup."""
import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import td_flow as flow


class PointsTests(unittest.TestCase):
    def setUp(self):
        self.projects = {"sample": flow.Project("sample", "Sample", Path("/private/project"))}

    def test_current_points_only_from_allowlisted_list_command(self):
        with patch.object(flow, "_td_json", return_value=[
            {"id": "td-alpha", "points": 3, "description": "private text"},
            {"id": "td-beta", "points": None},
            {"id": "td-gamma", "points": 0},
        ]) as reader:
            self.assertEqual(flow.read_td_points(self.projects),
                             {"td-alpha": 3, "td-beta": None, "td-gamma": 0})
        self.assertEqual(reader.call_args.args,
                         (self.projects["sample"],
                          ["list", "--all", "--limit", "20000", "--json"], "td"))
        self.assertEqual(reader.call_args.kwargs, {"timeout": 2.0})

    def test_partial_project_failure_retains_available_current_points(self):
        projects = {**self.projects, "second": flow.Project("second", "Second", Path("/other"))}
        def read(project, *_args, **_kwargs):
            if project.id == "second":
                raise flow.FlowError("A source is unavailable.")
            return [{"id": "td-alpha", "points": 8}]
        with patch.object(flow, "_td_json", side_effect=read):
            self.assertEqual(flow.read_td_points(projects), {"td-alpha": 8, "_incomplete": True})

    def test_invalid_and_conflicting_points_do_not_guess(self):
        projects = {**self.projects, "second": flow.Project("second", "Second", Path("/other"))}
        with patch.object(flow, "_td_json", side_effect=[
            [{"id": "td-alpha", "points": 3}], [{"id": "td-alpha", "points": 5}],
        ]), self.assertRaises(flow.FlowError):
            flow.read_td_points(projects)
        with patch.object(flow, "_td_json", return_value=[{"id": "td-alpha", "points": True}]):
            self.assertEqual(flow.read_td_points(self.projects), {"td-alpha": None})


class RunsHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.static = Path(self.temp.name)
        for name in ("flow.html", "runs.html", "runs.js", "runs_model.js", "runs.css"):
            (self.static / name).write_text("synthetic fixture")
        self.runs = Mock()
        self.runs.get.return_value = {"available": True, "runs": [], "lanes": [], "queue": []}
        project = flow.Project("fixture", "Fixture", Path("/private/project"))
        store = flow.FlowStore({"fixture": project}, exporter=lambda *_: {"tickets": []})
        self.server = flow.FlowServer(("127.0.0.1", 0), store, static_dir=self.static,
                                      runs_store=self.runs)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def request(self, path, method="GET", headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=3)
        try:
            connection.request(method, path, headers=headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def test_guarded_api_static_and_no_source_disclosure(self):
        status, headers, body = self.request("/api/runs")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["runs"], [])
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("connect-src 'self'", headers["Content-Security-Policy"])
        self.assertEqual(self.request("/api/runs", method="HEAD")[2], b"")
        for name in ("/runs", "/runs.html", "/static/runs.html", "/runs.js",
                     "/static/runs_model.js", "/static/runs.css"):
            self.assertEqual(self.request(name)[0], 200)
        for name in ("/loop5_runs.py", "/status.txt", "/state.json", "/sessions/roles.yml",
                     "/runs?directory=/private", "/static/runs.js?demo=1"):
            self.assertEqual(self.request(name)[0], 404)

    def test_queries_hosts_origins_and_writes_rejected_before_read(self):
        for query in ("?project=fixture", "?path=/private", "?a=1&a=2", "?demo=1"):
            self.assertEqual(self.request("/api/runs" + query)[0], 400)
        for headers in ({"Host": "evil.example"}, {"Origin": "https://evil.example"}):
            self.assertEqual(self.request("/api/runs", headers=headers)[0], 403)
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertEqual(self.request("/api/runs", method=method)[0], 405)
        self.runs.get.assert_not_called()

    def test_disabled_source_and_unexpected_errors_keep_viewer_available(self):
        self.runs.get.return_value = flow.RunsStore(None).get()
        status, _, body = self.request("/api/runs")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["available"])
        self.assertEqual(self.request("/api/projects")[0], 200)
        self.assertEqual(self.request("/api/flow?project=fixture")[0], 200)
        self.runs.get.side_effect = OSError("/private/path private source text")
        status, _, body = self.request("/api/runs")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"error": "Loop5 runs are unavailable."})


if __name__ == "__main__":
    unittest.main()
