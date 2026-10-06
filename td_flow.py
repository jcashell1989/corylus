"""Read-only TD project flow server. Only configured projects are accessible."""
from __future__ import annotations

import argparse
import copy
import json
import mimetypes
import os
import re
import selectors
import socket
import subprocess
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
EXPORT_TIMEOUT = 10.0
EXPORT_MAX_BYTES = 16 * 1024 * 1024
MAX_ISSUES = 20000
CACHE_SECONDS = 2.0
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
STATIC_FILES = {
    "/": "flow.html", "/flow.html": "flow.html",
    "/flow.css": "flow.css", "/flow.js": "flow.js",
    "/flow_model.js": "flow_model.js", "/flow_fixture.json": "flow_fixture.json",
    "/vendor/elk.bundled.js": "vendor/elk.bundled.js",
    "/static/flow.html": "flow.html", "/static/flow.css": "flow.css",
    "/static/flow.js": "flow.js", "/static/flow_model.js": "flow_model.js",
    "/static/flow_fixture.json": "flow_fixture.json",
    "/static/flow_demo.json": "flow_demo.json",
    "/static/vendor/elk.bundled.js": "vendor/elk.bundled.js",
}
for _asset in (
    "fonts/ahn-upright-latin.woff2", "fonts/ahn-italic-latin.woff2",
    "fonts/maple-mono-regular.woff2", "fonts/maple-mono-bold.woff2",
    "assets/favicon.svg", "assets/brake-traced.svg", "assets/brake-traced-cream.svg",
    "assets/logo-mark-black.svg", "assets/lockup-black.svg",
):
    STATIC_FILES["/" + _asset] = _asset
    STATIC_FILES["/static/" + _asset] = _asset


class FlowError(Exception):
    """Public, deliberately path-free source error."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    path: Path

    def public(self):
        return {"id": self.id, "name": self.name}


def projects_from_specs(specs, cwd=None):
    cwd = Path(cwd or Path.cwd())
    specs = specs or [f"{cwd.name}={cwd}"]
    result = {}
    for spec in specs:
        name, separator, path = spec.partition("=")
        if not separator or not name.strip() or not path:
            raise ValueError("Projects must be supplied as NAME=PATH.")
        name = name.strip()
        if len(name) > 100 or any(ord(char) < 32 for char in name):
            raise ValueError("Invalid project display name.")
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        if not slug or slug in result:
            raise ValueError("Project names must have unique nonempty identifiers.")
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_dir():
            raise ValueError("A configured project directory is unavailable.")
        result[slug] = Project(slug, name, resolved)
    return result


def _string(value, field, default=""):
    if value is None:
        return default
    if not isinstance(value, str):
        raise FlowError(f"TD export contains an invalid {field} field.")
    return value


def _identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise FlowError(f"TD export contains an invalid {field} identifier.")
    return value


def _cycles(adjacency):
    """Find back edges without recursion (large project chains are supported)."""
    colors = {}
    found = set()
    for start in adjacency:
        if colors.get(start):
            continue
        colors[start] = 1
        stack = [(start, iter(adjacency[start]))]
        while stack:
            node, neighbors = stack[-1]
            neighbor = next(neighbors, None)
            if neighbor is None:
                colors[node] = 2
                stack.pop()
            elif colors.get(neighbor) == 1:
                found.add((node, neighbor))
            elif not colors.get(neighbor):
                colors[neighbor] = 1
                stack.append((neighbor, iter(adjacency.get(neighbor, ()))))
    return sorted(found)


def normalize_export(export, project):
    if not isinstance(export, list) or len(export) > MAX_ISSUES:
        raise FlowError("TD export has an unsupported schema or exceeds the ticket limit.")
    issues = {}
    dependencies = {}
    deleted = set()
    for row in export:
        if not isinstance(row, dict) or not isinstance(row.get("issue"), dict):
            raise FlowError("TD export has an unsupported schema.")
        issue = row["issue"]
        issue_id = _identifier(issue.get("id"), "ticket")
        if issue_id in issues or issue_id in deleted:
            raise FlowError("TD export contains duplicate ticket identifiers.")
        if issue.get("deleted_at") or issue.get("status") == "deleted":
            deleted.add(issue_id)
            continue
        for required in ("title", "type", "status", "priority"):
            if required not in issue or not isinstance(issue[required], str) or not issue[required]:
                raise FlowError(f"TD export contains an invalid {required} field.")
        parent = issue.get("parent_id") or None
        if parent is not None:
            parent = _identifier(parent, "parent")
        labels = issue.get("labels") or []
        if not isinstance(labels, list) or any(not isinstance(label, str) for label in labels):
            raise FlowError("TD export contains invalid ticket labels.")
        deps = row.get("dependencies")
        if not isinstance(deps, list):
            raise FlowError("TD export contains invalid dependencies.")
        issues[issue_id] = {
            "id": issue_id, "title": issue["title"], "type": issue["type"],
            "status": issue["status"], "priority": issue["priority"],
            "parent_id": parent, "epic_id": None,
            "description": _string(issue.get("description"), "description"),
            "acceptance": _string(issue.get("acceptance"), "acceptance"),
            "labels": labels, "updated_at": _string(issue.get("updated_at"), "updated_at"),
            "depends_on": [],
        }
        dependencies[issue_id] = deps
    warnings = []
    edges = set()
    for issue_id, deps in dependencies.items():
        for dep in deps:
            if not isinstance(dep, dict):
                raise FlowError("TD export contains invalid dependencies.")
            owner = _identifier(dep.get("issue_id"), "dependency owner")
            prerequisite = _identifier(dep.get("depends_on_id"), "dependency")
            if owner != issue_id or dep.get("relation_type") != "depends_on":
                raise FlowError("TD export contains an unsupported dependency relation.")
            issues[issue_id]["depends_on"].append(prerequisite)
            if prerequisite not in issues:
                warnings.append(f"Ticket {issue_id} depends on unavailable ticket {prerequisite}.")
            else:
                edges.add((prerequisite, issue_id))
        issues[issue_id]["depends_on"] = sorted(set(issues[issue_id]["depends_on"]))
    ancestors = {}
    parents = {issue_id: [] for issue_id in issues}
    for issue_id, issue in issues.items():
        parent = issue["parent_id"]
        if parent in issues:
            parents[issue_id].append(parent)
        elif parent:
            warnings.append(f"Ticket {issue_id} has unavailable parent {parent}.")
        if issue_id not in ancestors:
            trail = []
            visited = set()
            current = issue_id
            nearest = None
            while current in issues and current not in visited:
                if current in ancestors:
                    nearest = ancestors[current]
                    break
                visited.add(current)
                trail.append(current)
                ancestor_id = issues[current]["parent_id"]
                if ancestor_id in issues and issues[ancestor_id]["type"] == "epic":
                    nearest = ancestor_id
                    break
                current = ancestor_id
            for descendant in trail:
                ancestors[descendant] = nearest
        issue["epic_id"] = ancestors[issue_id]
    for node, parent in _cycles(parents):
        warnings.append(f"Hierarchy cycle detected between {node} and {parent}.")
    graph = {issue_id: [] for issue_id in issues}
    for source, target in sorted(edges):
        graph[source].append(target)
    for source, target in _cycles(graph):
        warnings.append(f"Dependency cycle detected between {source} and {target}; this project is not a DAG.")
    tickets = sorted(issues.values(), key=lambda issue: issue["id"])
    return {
        "project": project.public(), "tickets": tickets,
        "epics": [{"id": issue["id"], "title": issue["title"], "parent_id": issue["parent_id"]}
                  for issue in tickets if issue["type"] == "epic"],
        "edges": [{"source": source, "target": target} for source, target in sorted(edges)],
        "warnings": sorted(set(warnings)),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def export_td(project, td_binary="td", timeout=EXPORT_TIMEOUT, max_bytes=EXPORT_MAX_BYTES):
    """Bound stdout in memory, discard stderr, and kill/reap on every failure."""
    try:
        process = subprocess.Popen(
            [td_binary, "export", "--all", "--format", "json"], cwd=project.path,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            env={**os.environ, "TD_ANALYTICS": "false"},
        )
    except OSError as exc:
        raise FlowError("TD could not be started for this project.") from exc
    output = bytearray()
    deadline = time.monotonic() + timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise FlowError("TD export timed out. Try refreshing after checking the project.")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = key.fileobj.read1(65536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    output.extend(chunk)
                    if len(output) > max_bytes:
                        raise FlowError("TD export exceeds the permitted output size.")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FlowError("TD export timed out. Try refreshing after checking the project.")
        try:
            code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            raise FlowError("TD export timed out. Try refreshing after checking the project.") from exc
        if code:
            raise FlowError("TD export failed. Check that the configured project has an initialized TD database.")
        try:
            parsed = json.loads(output)
        except (ValueError, UnicodeDecodeError) as exc:
            raise FlowError("TD returned an invalid JSON export.") from exc
        return normalize_export(parsed, project)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdout.close()


class FlowStore:
    def __init__(self, projects, td_binary="td", cache_seconds=CACHE_SECONDS, exporter=None):
        self.projects = projects
        self.td_binary = td_binary
        self.cache_seconds = cache_seconds
        self.exporter = exporter or export_td
        self._cache = {}
        self._locks = {key: threading.Lock() for key in projects}
        self._exports = threading.BoundedSemaphore(2)

    def get(self, project_id):
        project = self.projects[project_id]
        if not self._locks[project_id].acquire(timeout=EXPORT_TIMEOUT + 1):
            raise FlowError("Project export is busy. Try refreshing shortly.")
        try:
            cached = self._cache.get(project_id)
            if cached and time.monotonic() - cached[0] < self.cache_seconds:
                return copy.deepcopy(cached[1])
            if not self._exports.acquire(timeout=0.1):
                raise FlowError("Project exports are busy. Try refreshing shortly.")
            try:
                payload = self.exporter(project, self.td_binary)
            finally:
                self._exports.release()
            self._cache[project_id] = (time.monotonic(), payload)
            return copy.deepcopy(payload)
        finally:
            self._locks[project_id].release()


class FlowServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, store, allowed_hosts=None, static_dir=STATIC_DIR):
        self.store = store
        self.static_dir = Path(static_dir).resolve()
        self.allowed_hosts = {host.lower() for host in (allowed_hosts or [address[0]])}
        if address[0] in ("localhost", "127.0.0.1", "::1"):
            self.allowed_hosts.update(("localhost", "127.0.0.1", "::1"))
        self._requests = threading.BoundedSemaphore(16)
        if ":" in address[0]:
            self.address_family = socket.AF_INET6
        super().__init__(address, FlowHandler)

    def process_request(self, request, client_address):
        if not self._requests.acquire(blocking=False):
            try:
                request.sendall(b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n")
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._requests.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._requests.release()

    def handle_error(self, request, client_address):
        # Default HTTPServer logs a traceback with local source paths.
        pass


class FlowHandler(BaseHTTPRequestHandler):
    server_version = "CorylusFlow"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def log_message(self, format, *args):
        # Tickets, project paths and malicious URLs must not enter logs.
        pass

    def _reply(self, code, body, content_type="application/json; charset=utf-8", head=False):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def send_error(self, code, message=None, explain=None):
        self._reply(code, {"error": "Request rejected."})

    def _safe_host(self):
        headers = self.headers.get_all("Host", [])
        if len(headers) != 1 or len(headers[0]) > 255:
            return False
        try:
            authority = urlsplit("//" + headers[0])
            return (authority.hostname in self.server.allowed_hosts and
                    authority.port in (None, self.server.server_port, 80, 443) and
                    not authority.username and not authority.password and
                    not authority.path and not authority.query and not authority.fragment)
        except ValueError:
            return False

    def _get(self, head=False):
        if not self._safe_host():
            self._reply(403, {"error": "Host is not allowed."}, head=head)
            return
        if len(self.path) > 2048:
            self._reply(414, {"error": "Request is too long."}, head=head)
            return
        origin = self.headers.get("Origin")
        if origin:
            try:
                parsed_origin = urlsplit(origin)
                origin_allowed = (parsed_origin.scheme in ("http", "https") and
                                  parsed_origin.netloc.lower() == self.headers["Host"].lower() and
                                  not parsed_origin.path and not parsed_origin.query and not parsed_origin.fragment)
            except ValueError:
                origin_allowed = False
            if not origin_allowed:
                self._reply(403, {"error": "Origin is not allowed."}, head=head)
                return
        try:
            url = urlsplit(self.path)
            if url.scheme or url.netloc or url.fragment:
                raise ValueError()
            query = parse_qs(url.query, keep_blank_values=True, strict_parsing=True, max_num_fields=4)
        except ValueError:
            self._reply(400, {"error": "Invalid request."}, head=head)
            return
        if url.path == "/api/projects" and not query:
            self._reply(200, {"projects": [p.public() for p in self.server.store.projects.values()]}, head=head)
        elif url.path == "/api/flow":
            if set(query) != {"project"} or len(query["project"]) != 1:
                self._reply(400, {"error": "Choose one configured project."}, head=head)
                return
            project_id = query["project"][0]
            if project_id not in self.server.store.projects:
                self._reply(404, {"error": "Unknown project."}, head=head)
                return
            try:
                self._reply(200, self.server.store.get(project_id), head=head)
            except FlowError as exc:
                self._reply(503, {"error": str(exc)}, head=head)
            except Exception:  # noqa: BLE001 -- sanitize unexpected source failures at the HTTP boundary
                self._reply(503, {"error": "Project flow is unavailable."}, head=head)
        elif url.path in STATIC_FILES and self._static_query_allowed(url.path, query):
            asset = self.server.static_dir / STATIC_FILES[url.path]
            if not asset.resolve().is_relative_to(self.server.static_dir):
                self._reply(404, {"error": "Not found."}, head=head)
                return
            try:
                body = asset.read_bytes()
            except OSError:
                self._reply(404, {"error": "Not found."}, head=head)
                return
            content_type = mimetypes.guess_type(asset.name)[0] or "application/octet-stream"
            self._reply(200, body, content_type, head=head)
        else:
            self._reply(404, {"error": "Not found."}, head=head)

    def _static_query_allowed(self, path, query):
        if not query:
            return True
        if path not in ("/", "/flow.html", "/static/flow.html"):
            return False
        if not set(query).issubset({"demo", "project"}):
            return False
        if "demo" in query and query["demo"] != ["1"]:
            return False
        if "project" in query:
            values = query["project"]
            if len(values) != 1:
                return False
            known = values[0] in self.server.store.projects
            demo = query.get("demo") == ["1"] and values[0] == "corylus-demo"
            if not known and not demo:
                return False
        return True

    def do_GET(self):
        self._get()

    def do_HEAD(self):
        self._get(head=True)

    def _read_only(self):
        self._reply(405, {"error": "This application is read-only."})

    do_POST = _read_only
    do_PUT = _read_only
    do_PATCH = _read_only
    do_DELETE = _read_only
    do_OPTIONS = _read_only


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", action="append", metavar="NAME=PATH", help="Explicit project allowlist; repeat for multiple projects.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8791)
    parser.add_argument("--td", default="td", help="TD executable.")
    parser.add_argument("--allow-host", action="append", default=[], help="Additional trusted HTTP hostname (without port), e.g. a reverse proxy hostname.")
    args = parser.parse_args(argv)
    try:
        projects = projects_from_specs(args.project)
    except ValueError as exc:
        parser.error(str(exc))
    if args.host in ("0.0.0.0", "::") and not args.allow_host:
        parser.error("Wildcard binding requires at least one explicit --allow-host.")
    if not 0 <= args.port <= 65535:
        parser.error("Port must be between 0 and 65535.")
    allowed = args.allow_host + ([] if args.host in ("0.0.0.0", "::") else [args.host])
    try:
        server = FlowServer((args.host, args.port), FlowStore(projects, args.td), allowed_hosts=allowed)
    except OSError:
        parser.error("The server could not bind the requested address.")
    print(f"Corylus TD Flow listening on port {server.server_port}; {len(projects)} configured project(s).")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
