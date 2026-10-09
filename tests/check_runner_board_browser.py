"""Exercise the isolated Board component with sanitized and synthetic fixtures.

This harness is verification scaffolding, not the integrated td viewer.
It never starts a tracker, exports data, or contacts external services.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

FIXTURE_SCRIPT = b"""
const fixtureTitles = {
  'td-000001': 'Merge history', 'td-000002': 'Waiting for prerequisite',
  'td-000003': 'Stopped run', 'td-000004': 'Build the runner board',
  'td-000005': 'Independent review', 'td-000006': 'Next eligible ticket',
  'td-000007': 'Second queued ticket', 'td-000008': 'Decision required'
};
window.RunnerBoard.initialize({
  lookupTicket: (_repo, id) => ({title: fixtureTitles[id], description: 'Fixture ticket details.'}),
  openTicket: (_repo, id) => {
    document.getElementById('fixture-ticket').hidden = false;
    document.getElementById('fixture-ticket').textContent = id;
  }
});
window.RunnerBoard.setVisible(true);
document.getElementById('fixture-refresh').addEventListener('click', () => window.RunnerBoard.refresh());
"""


def fixture_state():
    """Keep the real sanitized shape; add explicit queued/decision test cases."""
    state = json.loads((ROOT / "tests/fixtures/runner_state_v1.json").read_text())
    now = datetime.now(timezone.utc)
    state["generated_at"] = now.isoformat()
    for ticket in state["tickets"]:
        ticket["start_time"] = (now - timedelta(minutes=12)).isoformat()
        ticket["last_event_time"] = (now - timedelta(minutes=1)).isoformat()
        ticket["pr_url"] = "https://github.com/example/project/pull/1"
    seed = state["tickets"][3]
    for index, column in [(6, "queued"), (7, "queued"), (8, "needs_decision")]:
        ticket = copy.deepcopy(seed)
        ticket.update(id=f"td-{index:06d}", column=column, running=False, round=0)
        if column == "queued":
            ticket.update(
                start_time=None,
                last_event_time=None,
                phase="queued",
                queue_position=index - 5,
            )
        else:
            ticket.update(blockers=["Julian only: choose the viewer baseline."])
        state["tickets"].append(ticket)
    state["merges"] = [
        {
            "ticket": "td-000001",
            "merged_at": (now - timedelta(hours=1)).isoformat(),
            "message": "Recorded merge fixture",
        }
    ]
    return state


class FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        pass

    def do_GET(self):
        from runner_state import normalize_state

        if self.path == "/api/runner":
            self.server.requests += 1
            code = 503 if self.server.failed else 200
            body = json.dumps(normalize_state(self.server.state)).encode()
            mime = "application/json"
        elif self.path == "/fixture.js":
            code, body, mime = 200, FIXTURE_SCRIPT, "text/javascript"
        else:
            files = {
                "/": ("tests/runner_board_fixture.html", "text/html"),
                "/static/runner_board.css": ("static/runner_board.css", "text/css"),
                "/static/runner_board.js": (
                    "static/runner_board.js",
                    "text/javascript",
                ),
                "/static/runner_board_model.js": (
                    "static/runner_board_model.js",
                    "text/javascript",
                ),
                "/static/assets/logo-mark-black.svg": (
                    "static/assets/logo-mark-black.svg",
                    "image/svg+xml",
                ),
                "/static/fonts/ahn-upright-latin.woff2": (
                    "static/fonts/ahn-upright-latin.woff2",
                    "font/woff2",
                ),
            }
            if self.path not in files:
                code, body, mime = 404, b"Not found", "text/plain"
            else:
                name, mime = files[self.path]
                code, body = 200, (ROOT / name).read_bytes()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def check_browser(server, output, executable):
    base = f"http://127.0.0.1:{server.server_port}"
    errors, external = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=executable, headless=True)
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                external.append(request.url)
                if not request.url.startswith(base)
                else None
            ),
        )
        page.clock.install()
        page.goto(base)
        expect(page.get_by_text("Next up", exact=True)).to_be_visible()
        expect(page.get_by_text("2nd", exact=True)).to_be_visible()
        expect(page.get_by_role("heading", name="Merged today (1)")).to_be_visible()
        expect(page.get_by_text("Live", exact=True)).to_be_visible()
        held = page.locator(".runner-held")
        assert not held.evaluate("node => node.open")
        held.locator("summary").click()
        expect(held.get_by_text("Waiting for prerequisite", exact=True)).to_be_visible()
        page.get_by_role("button", name="td-000004: Build the runner board.").click()
        drawer = page.locator(".runner-drawer")
        expect(
            drawer.get_by_role("heading", name="Timeline", exact=True)
        ).to_be_visible()
        expect(drawer.get_by_text("Recorded start", exact=True)).to_be_visible()
        assert "$" not in drawer.inner_text()
        output.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
        drawer.get_by_role("button", name="Open in td view").click()
        expect(page.locator("#fixture-ticket")).to_have_text("td-000004")
        print(
            "PASS columns, queue badges, held group, drawer, ticket callback, Codex no dollars"
        )

        building = next(t for t in server.state["tickets"] if t["id"] == "td-000004")
        building.update(column="reviewing", round=2, phase="round 2: reviewer start")
        previous_requests = server.requests
        page.clock.fast_forward(20000)
        expect(
            drawer.get_by_text("Observed on refresh: Reviewing", exact=True)
        ).to_be_visible()
        assert held.evaluate("node => node.open")
        assert server.requests > previous_requests
        print(
            "PASS automatic 20-second poll, live transition, retained held expansion and drawer"
        )

        server.failed = True
        page.locator("#fixture-refresh").click()
        expect(page.get_by_text("Stale snapshot", exact=True)).to_be_visible()
        expect(
            page.get_by_text("Showing the last successful snapshot.", exact=False)
        ).to_be_visible()
        server.failed = False
        server.state["generated_at"] = datetime.now(timezone.utc).isoformat()
        page.locator("#fixture-refresh").click()
        expect(page.get_by_text("Live", exact=True)).to_be_visible()
        print("PASS refresh failure and recovery")

        building["phase"] = "<img src=x onerror=window.injected=1>"
        page.locator("#fixture-refresh").click()
        expect(drawer.get_by_text(building["phase"], exact=True).first).to_be_visible()
        assert page.evaluate("window.injected") is None
        page.set_viewport_size({"width": 420, "height": 900})
        expect(page.locator(".runner-drawer")).to_be_visible()
        assert not errors, errors
        assert not external, external
        browser.close()
        print(
            "PASS literal source text, small viewport, zero browser errors/external requests"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--screenshot", type=Path, default=Path("test-results/runner-board.png")
    )
    parser.add_argument("--chromium", default="chromium")
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
    server.state, server.failed, server.requests = fixture_state(), False, 0
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        check_browser(server, args.screenshot, args.chromium)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


if __name__ == "__main__":
    main()
