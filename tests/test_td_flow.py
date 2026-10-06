"""TD source-contract, bounded execution and HTTP boundary tests."""
import http.client
import json
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import td_flow as flow


def record(issue_id, title="Ticket", **fields):
    issue = {"id": issue_id, "title": title, "type": "task", "status": "open", "priority": "P2"}
    issue.update(fields)
    return {"issue": issue, "dependencies": []}


def dependency(record_, prerequisite):
    record_["dependencies"].append({"issue_id": record_["issue"]["id"], "depends_on_id": prerequisite, "relation_type": "depends_on"})
    return record_


class NormalizeTests(unittest.TestCase):
    def setUp(self):
        self.project = flow.Project("sample", "Sample", Path("/private/project"))

    def test_epic_ancestor_cross_epic_and_unassigned_edges(self):
        epic = record("td-epic", "Epic", type="epic")
        child = record("td-child", parent_id="td-epic")
        nested = record("td-nested", parent_id="td-child", labels=["backend"])
        outside = dependency(record("td-outside"), "td-nested")
        independent = record("td-independent", parent_id="td-epic")
        payload = flow.normalize_export([epic, child, nested, outside, independent], self.project)
        by_id = {issue["id"]: issue for issue in payload["tickets"]}
        self.assertEqual(by_id["td-nested"]["epic_id"], "td-epic")
        self.assertIsNone(by_id["td-outside"]["epic_id"])
        self.assertEqual(by_id["td-outside"]["depends_on"], ["td-nested"])
        self.assertEqual(payload["edges"], [{"source": "td-nested", "target": "td-outside"}])
        self.assertIn("td-epic", by_id)
        self.assertEqual(payload["warnings"], [])
        self.assertNotIn("/private/project", json.dumps(payload))

    def test_deleted_closed_orphans_and_cycles_remain_visible(self):
        a = dependency(record("td-a", parent_id="td-b"), "td-b")
        b = dependency(record("td-b", parent_id="td-a"), "td-a")
        orphan = dependency(record("td-orphan", parent_id="td-missing"), "td-deleted")
        closed = record("td-closed", status="closed")
        deleted = record("td-deleted", deleted_at="2026-01-01T00:00:00Z")
        payload = flow.normalize_export([a, b, orphan, closed, deleted], self.project)
        self.assertEqual({issue["id"] for issue in payload["tickets"]}, {"td-a", "td-b", "td-orphan", "td-closed"})
        self.assertEqual(len(payload["edges"]), 2)
        self.assertEqual(next(issue for issue in payload["tickets"] if issue["id"] == "td-orphan")["depends_on"], ["td-deleted"])
        self.assertTrue(any("Hierarchy cycle" in warning for warning in payload["warnings"]))
        self.assertTrue(any("Dependency cycle" in warning for warning in payload["warnings"]))
        self.assertTrue(any("unavailable parent" in warning for warning in payload["warnings"]))
        self.assertTrue(any("unavailable ticket" in warning for warning in payload["warnings"]))

    def test_invalid_source_never_becomes_empty_success(self):
        bad_cases = [None, {}, [None], [{"issue": {}}], [record("td-a"), record("td-a")]]
        invalid_dep = record("td-a")
        invalid_dep["dependencies"] = [{"issue_id": "td-a", "depends_on_id": "td-b", "relation_type": "unknown"}]
        bad_cases.append([invalid_dep])
        for export in bad_cases:
            with self.subTest(export=export), self.assertRaises(flow.FlowError):
                flow.normalize_export(export, self.project)

    def test_large_chain_has_no_recursion_limit(self):
        rows = [record(f"td-{index}", parent_id=f"td-{index - 1}" if index else None) for index in range(1100)]
        payload = flow.normalize_export(rows, self.project)
        self.assertEqual(len(payload["tickets"]), 1100)
        self.assertFalse(payload["warnings"])


class SourceTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("td"), "TD executable unavailable")
    def test_real_td_export_schema_direction_and_deletion(self):
        with tempfile.TemporaryDirectory(prefix="td-flow-integration-") as directory:
            def td(*args):
                return subprocess.run(["td", "-w", directory, *args], capture_output=True, text=True, check=True).stdout
            td("init")
            epic_id = json.loads(td("create", "Integration epic", "--type", "epic", "--json"))["id"]
            first_id = json.loads(td("create", "Prerequisite", "--parent", epic_id, "--labels", "test,source", "--json"))["id"]
            next_id = json.loads(td("create", "Unassigned dependent", "--depends-on", first_id, "--json"))["id"]
            doomed_id = json.loads(td("create", "Deleted issue", "--json"))["id"]
            td("delete", doomed_id)
            project = flow.Project("integration", "Integration", Path(directory))
            payload = flow.export_td(project)
            by_id = {issue["id"]: issue for issue in payload["tickets"]}
            self.assertEqual(by_id[first_id]["epic_id"], epic_id)
            self.assertIsNone(by_id[next_id]["epic_id"])
            self.assertEqual(by_id[next_id]["depends_on"], [first_id])
            self.assertEqual(payload["edges"], [{"source": first_id, "target": next_id}])
            self.assertNotIn(doomed_id, by_id)
            self.assertEqual(by_id[first_id]["labels"], ["test", "source"])

    def test_failed_cli_does_not_disclose_stderr(self):
        with tempfile.TemporaryDirectory() as directory:
            project = flow.Project("bad", "Bad", Path(directory))
            script = Path(directory) / "fail"
            script.write_text("#!/usr/bin/env python3\nimport sys\nsys.stderr.write('/private/path SECRET')\nsys.exit(1)\n")
            script.chmod(0o700)
            with self.assertRaises(flow.FlowError) as error:
                flow.export_td(project, str(script))
            self.assertNotIn("SECRET", str(error.exception))
            self.assertNotIn(directory, str(error.exception))

    def test_missing_binary_timeout_and_output_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            project = flow.Project("test", "Test", Path(directory))
            with self.assertRaisesRegex(flow.FlowError, "could not be started"):
                flow.export_td(project, str(Path(directory) / "missing"))
            script = Path(directory) / "slow"
            script.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(5)\n")
            script.chmod(0o700)
            started = time.monotonic()
            with self.assertRaisesRegex(flow.FlowError, "timed out"):
                flow.export_td(project, str(script), timeout=0.15)
            self.assertLess(time.monotonic() - started, 2)
            script.write_text("#!/usr/bin/env python3\nprint('x' * 8192)\n")
            with self.assertRaisesRegex(flow.FlowError, "output size"):
                flow.export_td(project, str(script), max_bytes=1024)

    def test_cache_only_success_and_coalesces_concurrent_reads(self):
        project = flow.Project("test", "Test", Path("/tmp"))
        exporter = mock.Mock(return_value={"tickets": [{"id": "td-a"}]})
        store = flow.FlowStore({"test": project}, exporter=exporter, cache_seconds=10)
        threads = [threading.Thread(target=store.get, args=("test",)) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        first = store.get("test")
        first["tickets"].clear()
        self.assertEqual(len(store.get("test")["tickets"]), 1)
        self.assertEqual(exporter.call_count, 1)
        store.cache_seconds = 0
        exporter.side_effect = flow.FlowError("Export failed.")
        with self.assertRaises(flow.FlowError):
            store.get("test")

    def test_allowlist_slugs_and_duplicate_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            result = flow.projects_from_specs([f"My Project={directory}"])
            self.assertEqual(list(result), ["my-project"])
            self.assertEqual(result["my-project"].public(), {"id": "my-project", "name": "My Project"})
            with self.assertRaises(ValueError):
                flow.projects_from_specs([f"My Project={directory}", f"my-project={directory}"])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.static = Path(self.temp.name)
        (self.static / "flow.html").write_text("<!doctype html><title>Flow</title>")
        (self.static / "private.txt").write_text("PRIVATE")
        project = flow.Project("test", "Test", Path("/private/project"))
        self.exporter = mock.Mock(return_value=flow.normalize_export([record("td-a")], project))
        self.server = flow.FlowServer(("127.0.0.1", 0), flow.FlowStore({"test": project}, exporter=self.exporter), static_dir=self.static)
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

    def test_project_and_flow_contract_no_paths(self):
        status, headers, body = self.request("/api/projects")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"projects": [{"id": "test", "name": "Test"}]})
        self.assertNotIn(b"/private", body)
        status, _, body = self.request("/api/flow?project=test")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["tickets"][0]["id"], "td-a")
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_static_allowlist_traversal_and_source_exposure(self):
        self.assertEqual(self.request("/")[0], 200)
        self.assertEqual(self.request("/?demo=1")[0], 200)
        self.assertEqual(self.request("/?demo=2")[0], 404)
        for path in ("/../td_flow.py", "/%2e%2e/td_flow.py", "/static/../td_flow.py", "/private.txt", "/index.html", "/app.js", "/.todos/issues.db", "/?path=private.txt"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)

    def test_selected_project_html_reload_and_query_validation(self):
        for path in ("/?project=test", "/flow.html?project=test", "/static/flow.html?project=test", "/?demo=1&project=test", "/?demo=1&project=corylus-demo"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 200)
        for path in ("/?project=unknown", "/?project=test&project=test", "/?project=test&path=private.txt", "/?demo=2&project=test", "/flow.js?project=test"):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)
        self.assertFalse(self.exporter.called)

    def test_unknown_duplicate_extra_and_path_projects(self):
        for path, status in (("/api/flow", 400), ("/api/flow?project=test&project=test", 400), ("/api/flow?project=test&path=/tmp", 400), ("/api/flow?project=/private/project", 404), ("/api/flow?project=missing", 404), ("/api/projects?path=/tmp", 404)):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], status)
        self.assertFalse(self.exporter.called)

    def test_host_rebinding_and_cross_origin(self):
        for headers in ({"Host": f"evil.example:{self.server.server_port}"}, {"Host": "127.0.0.1:12345"}, {"Host": f"127.0.0.1:{self.server.server_port}@evil.example"}, {"Origin": "https://evil.example"}, {"Origin": "http://[invalid"}):
            with self.subTest(headers=headers):
                self.assertEqual(self.request("/api/projects", headers=headers)[0], 403)
        self.assertFalse(self.exporter.called)

    def test_read_only_http_and_failures(self):
        for method in ("POST", "PUT", "PATCH", "DELETE", "OPTIONS"):
            self.assertEqual(self.request("/api/flow?project=test", method=method)[0], 405)
        self.exporter.side_effect = flow.FlowError("TD export failed.")
        status, _, body = self.request("/api/flow?project=test")
        self.assertEqual(status, 503)
        self.assertEqual(json.loads(body), {"error": "TD export failed."})
        self.assertFalse("tickets" in json.loads(body))


if __name__ == "__main__":
    unittest.main()
