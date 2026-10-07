#!/usr/bin/env python3
"""Exercise the complete viewer in Chromium against real, temporary td projects."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from td_flow import FlowServer, FlowStore, normalize_export, projects_from_specs  # noqa: E402


def run_td(binary, project, *args):
    result = subprocess.run(
        [binary, "--work-dir", str(project), *args],
        capture_output=True, check=True, timeout=15,
    )
    return json.loads(result.stdout) if "--json" in args else None


def read_fixture(project, binary):
    """Read temporary trackers without invoking TD's scheduled export writer."""
    issues = run_td(binary, project.path, "list", "--all", "--limit", "20000", "--json")
    def read_row(summary):
        issue = run_td(binary, project.path, "show", summary["id"], "--json")
        dependencies = run_td(binary, project.path, "dep", issue["id"], "--json")
        return {
            "issue": issue,
            "dependencies": [
                {"issue_id": issue["id"], "depends_on_id": prerequisite,
                 "relation_type": "depends_on"}
                for prerequisite in dependencies["dependencies"]
            ],
        }
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(read_row, issues))
    return normalize_export(rows, project)


def fixture(binary, project):
    project.mkdir()
    run_td(binary, project, "init")
    ids = {}

    def create(key, title, parent=None, prerequisites=(), kind="task"):
        command = [
            "create", title, "--type", kind, "--priority", "P1",
            "--description", "Browser fixture description. <script>window.injected=1</script>",
            "--acceptance", "The selected graph node and table row agree.",
        ]
        if parent:
            command.extend(["--parent", ids[parent]])
        for prerequisite in prerequisites:
            command.extend(["--depends-on", ids[prerequisite]])
        ids[key] = run_td(binary, project, *command, "--json")["id"]

    create("backend", "Backend", kind="epic")
    create("interface", "Interface", kind="epic")
    create("preflight", "Preflight")
    create("schema", "Define schema", "backend", ["preflight"])
    create("api", "Build API", "backend", ["schema"])
    create("auth", "Authentication", "backend", ["api"])
    create("table", "Ticket table", "interface", ["api"])
    create("canvas", "DAG canvas", "interface", ["table"])
    create("smoke", "Smoke tests", prerequisites=["auth", "canvas"])
    create("readme", "Update README")
    create("keys", "Add keyboard shortcuts")
    create("empty", "Polish empty states")
    create("independent_member", "Independent epic member", "backend")
    run_td(binary, project, "start", ids["api"])
    run_td(binary, project, "start", ids["readme"])
    run_td(binary, project, "block", ids["auth"], "--reason", "Browser fixture status")
    return ids


def graph_node(page, ticket_id):
    return page.locator(f'.node-card[data-ticket="{ticket_id}"]')


def table_row(page, ticket_id):
    return page.locator(f'.ticket-row[data-ticket="{ticket_id}"]')


def shelf_card(page, ticket_id):
    return page.locator(f'#independent-list [data-ticket="{ticket_id}"]')


def graph_area(page):
    return page.locator("#graph-scene").evaluate(
        "scene => { const bounds = scene.getBBox(); return bounds.width * bounds.height; }"
    )


def check_containment(page, ids):
    boxes = page.locator(".epic-boundary").evaluate_all(
        "nodes => nodes.map(n => {const r=n.getBoundingClientRect();"
        "return {x:r.x,y:r.y,right:r.right,bottom:r.bottom}})"
    )
    assert len(boxes) == 2
    for key in ("preflight", "smoke"):
        rect = graph_node(page, ids[key]).bounding_box()
        center_x = rect["x"] + rect["width"] / 2
        center_y = rect["y"] + rect["height"] / 2
        assert not any(
            box["x"] <= center_x <= box["right"]
            and box["y"] <= center_y <= box["bottom"]
            for box in boxes
        ), f"Unassigned {key} incorrectly enclosed by an epic"
    for key in ("schema", "api", "auth", "table", "canvas", "independent_member"):
        rect = graph_node(page, ids[key]).bounding_box()
        assert sum(
            box["x"] <= rect["x"] and box["y"] <= rect["y"]
            and box["right"] >= rect["x"] + rect["width"]
            and box["bottom"] >= rect["y"] + rect["height"]
            for box in boxes
        ) == 1, f"Epic member {key} lacks exactly one enclosing epic"


def check_browser(base_url, ids, binary, source, screenshots, executable):
    expect.set_options(timeout=15000)
    errors = []
    external = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=executable,
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        page = browser.new_page(viewport={"width": 1600, "height": 1000})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: external.append(request.url)
                if not request.url.startswith(base_url) else None)
        page.goto(base_url)
        expect(page.locator(".node-card")).to_have_count(8)
        expect(page.locator(".ticket-row")).to_have_count(13)
        expect(page.locator(".graph-edge")).to_have_count(7)
        expect(page.locator("#sample-badge")).to_be_hidden()
        check_containment(page, ids)
        full_graph_area = graph_area(page)
        expect(shelf_card(page, ids["preflight"])).to_have_count(0)
        expect(shelf_card(page, ids["independent_member"])).to_have_count(0)
        expect(graph_node(page, ids["independent_member"])).to_have_count(1)
        expect(table_row(page, ids["independent_member"]).locator("td").nth(5)).to_have_text("Backend")
        expect(page.locator("#independent-count")).to_have_text("3")
        print("PASS live td data, dependency arrows, epic containment and independent tickets")

        graph_node(page, ids["api"]).click()
        expect(table_row(page, ids["api"])).to_have_class("ticket-row selected")
        expect(page.locator(".detail-text").first).to_contain_text("<script>")
        assert page.evaluate("window.injected") is None
        table_row(page, ids["smoke"]).click()
        expect(graph_node(page, ids["smoke"])).to_have_class("node-card selected")
        shelf_card(page, ids["readme"]).click()
        expect(table_row(page, ids["readme"])).to_have_class("ticket-row selected")
        prerequisite = table_row(page, ids["schema"]).locator(".dependency-button").first
        prerequisite.focus()
        page.keyboard.press("Enter")
        expect(table_row(page, ids["preflight"])).to_have_class("ticket-row selected")
        expect(graph_node(page, ids["preflight"])).to_have_class("node-card selected")
        print("PASS linked graph/table/shelf selection and literal ticket content")

        page.locator("#search").fill("Build API")
        expect(page.locator(".node-card")).to_have_count(1)
        expect(page.locator(".ticket-row")).to_have_count(1)
        expect(shelf_card(page, ids["api"])).to_have_count(0)
        expect(page.locator(".node-context")).to_contain_text("hidden")
        assert graph_area(page) < full_graph_area * 0.5, "Search must shrink layout bounds"
        graph_node(page, ids["api"]).click()
        page.locator("#refresh").click()
        expect(page.locator("#refresh")).to_be_enabled()
        expect(page.locator("#search")).to_have_value("Build API")
        expect(table_row(page, ids["api"])).to_have_class("ticket-row selected")
        page.locator("#clear-filters").click()
        expect(page.locator(".node-card")).to_have_count(8)
        page.locator("#epic").select_option("__none__")
        expect(page.locator(".node-card")).to_have_count(2)
        expect(page.locator(".epic-boundary")).to_have_count(0)
        page.locator("#clear-filters").click()
        expect(page.locator(".node-card")).to_have_count(8)
        status_summary = page.locator("#status summary")
        status_summary.focus()
        page.keyboard.press("Enter")
        expect(page.locator("#status")).to_have_attribute("open", "")
        statuses = page.locator("#status-options input[type=checkbox]")
        expect(statuses).to_have_count(3)
        for checkbox in statuses.all():
            expect(checkbox).to_be_checked()
        blocked = page.locator('#status-options input[value="blocked"]')
        blocked.focus()
        page.keyboard.press("Space")
        expect(blocked).not_to_be_checked()
        expect(blocked).to_be_focused()
        expect(page.locator(".ticket-row")).to_have_count(12)
        expect(page.locator("#ticket-count")).to_have_text("12")
        expect(page.locator(".node-card")).to_have_count(7)
        expect(page.locator(".graph-edge")).to_have_count(5)
        expect(page.locator("#independent-count")).to_have_text("3")
        expect(table_row(page, ids["api"])).to_have_count(1)
        expect(table_row(page, ids["preflight"])).to_have_count(1)
        expect(table_row(page, ids["auth"])).to_have_count(0)
        page.locator('#status-options input[value="open"]').uncheck()
        expect(page.locator(".node-card")).to_have_count(1)
        expect(page.locator(".ticket-row")).to_have_count(2)
        assert graph_area(page) < full_graph_area * 0.5, "Status filters must relayout the graph"
        expect(page.locator("#ticket-count")).to_have_text("2")
        expect(page.locator("#independent-count")).to_have_text("1")
        expect(page.locator("#graph-summary")).to_have_text("1 connected · 1 epics · 0 links")
        expect(shelf_card(page, ids["readme"])).to_have_count(1)
        page.locator("#refresh").click()
        expect(page.locator("#refresh")).to_be_enabled()
        expect(page.locator(".ticket-row")).to_have_count(2)
        expect(page.locator('#status-options input[value="open"]')).not_to_be_checked()
        # A status disappearing and returning must preserve the explicit subset.
        run_td(binary, source, "unstart", ids["api"])
        run_td(binary, source, "unstart", ids["readme"])
        page.locator("#refresh").click()
        expect(page.locator("#refresh")).to_be_enabled()
        expect(page.locator('#status-options input[value="in_progress"]')).to_be_checked()
        expect(page.locator(".ticket-row")).to_have_count(0)
        run_td(binary, source, "start", ids["api"])
        run_td(binary, source, "start", ids["readme"])
        page.locator("#refresh").click()
        expect(page.locator("#refresh")).to_be_enabled()
        expect(page.locator(".ticket-row")).to_have_count(2)
        expect(blocked).not_to_be_checked()
        page.locator('#status-options input[value="in_progress"]').uncheck()
        expect(page.locator(".ticket-row")).to_have_count(0)
        expect(page.locator(".node-card")).to_have_count(0)
        expect(page.locator("#ticket-count")).to_have_text("0")
        expect(page.locator("#independent-count")).to_have_text("0")
        expect(page.locator("#graph-summary")).to_have_text("0 connected · 0 epics · 0 links")
        page.locator("#status-all").click()
        expect(page.locator(".ticket-row")).to_have_count(13)
        page.locator('#status-options input[value="blocked"]').uncheck()
        page.locator("#clear-filters").click()
        expect(page.locator(".node-card")).to_have_count(8)
        expect(page.locator(".ticket-row")).to_have_count(13)
        for checkbox in statuses.all():
            expect(checkbox).to_be_checked()
        status_summary.focus()
        page.keyboard.press("Escape")
        expect(page.locator("#status")).not_to_have_attribute("open", "")
        print("PASS keyboard multi-status filtering, synchronized counts, empty/all/clear and refresh")

        zoom_before = page.locator("#zoom-label").inner_text()
        page.locator("#zoom-in").click()
        assert page.locator("#zoom-label").inner_text() != zoom_before
        page.locator("#fit").click()
        viewport = page.locator("#graph-viewport").bounding_box()
        before = page.locator("#graph-scene").get_attribute("transform")
        page.mouse.move(viewport["x"] + 8, viewport["y"] + 8)
        page.mouse.down()
        page.mouse.move(viewport["x"] + 65, viewport["y"] + 35, steps=3)
        page.mouse.up()
        assert before != page.locator("#graph-scene").get_attribute("transform")
        page.locator("#fit").click()
        page.locator("#divider").focus()
        height_before = page.locator("#divider").get_attribute("aria-valuenow")
        page.keyboard.press("ArrowUp")
        assert height_before != page.locator("#divider").get_attribute("aria-valuenow")
        splitter = page.locator("#divider").bounding_box()
        page.mouse.move(splitter["x"] + splitter["width"] / 2, splitter["y"] + 3)
        page.mouse.down()
        page.mouse.move(splitter["x"] + splitter["width"] / 2, splitter["y"] + 30)
        page.mouse.up()
        page.locator("#graph-viewport").focus()
        page.keyboard.press("ArrowRight")
        expect(page.locator(".node-card.selected")).to_have_count(1)
        expect(page.locator(".ticket-row.selected")).to_have_count(1)
        print("PASS zoom, fit, panning, keyboard selection and pointer/keyboard pane resizing")

        run_td(binary, source, "create", "Live refresh ticket", "--json")
        page.locator("#refresh").click()
        expect(page.locator(".ticket-row")).to_have_count(14)
        page.locator("[data-sort='title']").click()
        titles = page.locator(".ticket-row td:nth-child(2)").all_text_contents()
        assert titles == sorted(titles, key=str.casefold)
        status_summary.click()
        page.locator('#status-options input[value="open"]').uncheck()
        expect(page.locator(".ticket-row")).to_have_count(3)
        page.locator("#project").select_option("alternate")
        expect(page.locator(".ticket-row")).to_have_count(1)
        expect(page.locator(".node-card")).to_have_count(0)
        expect(page.locator('#status-options input[value="open"]')).to_be_checked()
        assert "status" not in page.url
        page.reload()
        expect(page.locator(".ticket-row")).to_have_count(1)
        print("PASS live changes, table sorting, project switching and project URL reload")

        page.goto(base_url + "?demo=1")
        expect(page.locator(".node-card")).to_have_count(7)
        expect(page.locator(".ticket-row")).to_have_count(12)
        expect(page.locator("#sample-badge")).to_be_visible()
        expect(graph_node(page, "td-103")).to_have_class("node-card selected")
        page.screenshot(path=str(screenshots / "flow-desktop.png"), full_page=True)
        page.set_viewport_size({"width": 1440, "height": 900})
        page.locator("#fit").click()
        page.screenshot(path=str(screenshots / "flow-laptop.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        page.locator("#fit").click()
        expect(page.locator("#independent")).to_be_visible()
        expect(page.locator("#table-pane")).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(screenshots / "flow-mobile.png"), full_page=True)
        page.locator("#status summary").click()
        expect(page.locator("#status-all")).to_be_visible()
        menu = page.locator(".status-menu").bounding_box()
        assert menu["x"] >= 0 and menu["x"] + menu["width"] <= 390
        page.screenshot(path=str(screenshots / "flow-status-mobile.png"), full_page=True)
        page.locator("#status summary").press("Escape")
        print("PASS explicit sample mode and desktop/laptop/mobile screenshots")

        page.set_viewport_size({"width": 1600, "height": 1000})
        page.goto(base_url)
        expect(page.locator(".ticket-row")).to_have_count(14)
        page.route("**/api/flow?*", lambda route: route.fulfill(
            status=503, content_type="application/json",
            body=json.dumps({"error": "Test source unavailable."}),
        ))
        page.locator("#refresh").click()
        expect(page.locator("#updated")).to_contain_text("stale")
        expect(page.locator("#messages")).to_contain_text("last successful snapshot")
        expect(page.locator(".ticket-row")).to_have_count(14)
        page.unroute("**/api/flow?*")
        page.locator("#refresh").click()
        expect(page.locator("#updated")).to_contain_text("Updated")
        print("PASS failed refresh marks stale data and subsequent refresh recovers")

        page.route("**/api/flow?*", lambda route: route.fulfill(
            status=503, content_type="application/json",
            body=json.dumps({"error": "Initial source unavailable."}),
        ))
        page.goto(base_url)
        expect(page.locator("#updated")).to_have_text("Connection failed")
        page.locator("[data-sort='title']").click()
        expect(page.locator(".ticket-row")).to_have_count(0)
        expect(page.locator("#table-empty")).to_be_visible()
        page.unroute("**/api/flow?*")
        page.locator("#refresh").click()
        expect(page.locator(".ticket-row")).to_have_count(14)
        print("PASS initial source failure permits sorting and recovers without browser errors")

        broken = {
            "project": {"id": "fixture", "name": "Fixture"}, "epics": [], "warnings": [],
            "tickets": [
                {"id": ticket_id, "title": title, "type": "task", "status": "open",
                 "priority": "P2", "epic_id": None, "depends_on": prerequisites}
                for ticket_id, title, prerequisites in (
                    ("td-cycle-a", "Cycle A", ["td-cycle-b"]),
                    ("td-cycle-b", "Cycle B", ["td-cycle-a"]),
                    ("td-orphan", "Missing prerequisite", ["td-missing"]),
                )
            ],
            "edges": [
                {"source": "td-cycle-a", "target": "td-cycle-b"},
                {"source": "td-cycle-b", "target": "td-cycle-a"},
            ],
        }
        page.route("**/api/flow?*", lambda route: route.fulfill(
            content_type="application/json", body=json.dumps(broken),
        ))
        page.goto(base_url)
        expect(page.locator(".ticket-row")).to_have_count(3)
        expect(page.locator(".node-card")).to_have_count(3)
        expect(page.locator(".graph-edge")).to_have_count(2)
        expect(page.locator("#messages")).to_contain_text("not a valid DAG")
        expect(page.locator("#messages")).to_contain_text("missing ticket")
        expect(shelf_card(page, "td-orphan")).to_have_count(0)
        print("PASS cyclic and orphan relationships remain visible with warnings")
        broken["tickets"][2]["status"] = "paused"
        page.locator("#refresh").click()
        expect(page.locator("#refresh")).to_be_enabled()
        expect(page.locator(".ticket-row")).to_have_count(3)
        page.locator("#status summary").click()
        expect(page.locator('#status-options input[value="paused"]')).to_be_checked()
        page.locator('#status-options input[value="open"]').uncheck()
        expect(page.locator(".ticket-row")).to_have_count(1)
        broken["tickets"][0]["status"] = "custom_status"
        page.locator("#refresh").click()
        expect(page.locator("#refresh")).to_be_enabled()
        expect(page.locator('#status-options input[value="custom_status"]')).not_to_be_checked()
        expect(page.locator(".ticket-row")).to_have_count(1)
        page.locator("#status-all").click()
        expect(page.locator(".ticket-row")).to_have_count(3)
        expect(page.locator('#status-options input[value="custom_status"]')).to_be_checked()
        print("PASS all includes new statuses on refresh and explicit subsets exclude them")
        assert not errors, errors
        assert not external, external
        print("PASS no browser errors or external network requests")
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default=shutil.which("chromium"))
    parser.add_argument("--screenshots", type=Path, default=ROOT / "test-results")
    parser.add_argument("--td", default=shutil.which("td"))
    args = parser.parse_args()
    if not args.td:
        parser.error("td must be available to create the isolated real tracker fixtures")
    args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="corylus-browser-") as temporary:
        temporary = Path(temporary)
        source = temporary / "fixture"
        ids = fixture(args.td, source)
        alternate = temporary / "alternate"
        alternate.mkdir()
        run_td(args.td, alternate, "init")
        run_td(args.td, alternate, "create", "Alternate project ticket", "--json")
        projects = projects_from_specs([f"Fixture={source}", f"Alternate={alternate}"])
        server = FlowServer(("127.0.0.1", 0), FlowStore(
            projects, args.td, cache_seconds=0, exporter=read_fixture,
        ))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            check_browser(
                f"http://127.0.0.1:{server.server_port}/", ids,
                args.td, source, args.screenshots, args.chromium,
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    main()
