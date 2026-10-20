#!/usr/bin/env python3
"""Exercise the runs page over synthetic on-disk sources, never production data."""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from loop5_runs import RunsStore  # noqa: E402
from td_flow import FlowServer, FlowStore, normalize_export, projects_from_specs  # noqa: E402
from test_loop5_runs import write_fixture  # noqa: E402


def check(base, server, source, screenshots, chromium):
    errors, external = [], []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chromium, headless=True,
                                             args=["--no-sandbox", "--disable-dev-shm-usage"])
        page = browser.new_page(viewport={"width": 1600, "height": 1100})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("request", lambda request: external.append(request.url)
                if not request.url.startswith(base) else None)
        page.goto(base + "/?demo=1")
        page.get_by_role("link", name="Loop5 runs", exact=True).click()
        expect(page.locator("#updated")).to_contain_text("Last source refresh")
        expect(page.locator(".lane")).to_have_count(4)
        expect(page.locator(".lane").filter(has=page.get_by_role("heading", name="lane3", exact=True))).to_contain_text("Skipped")
        expect(page.locator("#queue tbody tr")).to_have_count(2)
        page.locator("#window").select_option("all")
        expect(page.locator("#selection")).to_contain_text("10 recorded runs selected")
        atlas = page.locator("#models tbody tr").filter(has_text="lab/atlas")
        assert atlas.locator("td").all_text_contents()[1:6] == ["2", "1", "1", "1", "1"]
        assert atlas.locator("td").all_text_contents()[6:] == ["20.0 min", "30.0 min", "2"]
        verdict = page.locator("#verdicts tbody tr").filter(has_text="lab/atlas")
        assert verdict.locator("td").all_text_contents() == ["lab/atlas", "1", "1"]
        output = json.dumps(page.request.get(base + "/api/runs").json())
        for forbidden in ("SYNTHETIC_PRIVATE_OUTPUT", "/private/", "sk-synthetic", ".env",
                          str(source), "roles.yml"):
            assert forbidden not in output
            assert forbidden not in page.locator("body").inner_text()
        print("PASS fixture parser to DOM, exact hand counts, verdicts and private-data exclusion")

        page.locator("#points-mode").select_option("value")
        page.locator("#points-value").fill("2")
        expect(page.locator("#selection")).to_contain_text("4 recorded runs selected")
        page.locator("#points-mode").select_option("range")
        page.locator("#points-min").fill("1")
        page.locator("#points-max").fill("2")
        expect(page.locator("#selection")).to_contain_text("5 recorded runs selected")
        page.locator("#points-mode").select_option("unpointed")
        expect(page.locator("#selection")).to_contain_text("2 recorded runs selected")
        page.locator("#points-mode").select_option("all")
        page.locator("#view").select_option("normalized")
        expect(page.locator("#normalized")).to_be_visible()
        assert atlas.locator("td").all_text_contents()[6:] == ["10.00", "2"]
        expect(page.locator("#point-outcomes")).to_contain_text("2 / 2 (100.0%)")
        print("PASS single/range/unpointed points filters and normalized hand-counted rates")

        page.locator("#view").select_option("runs")
        page.screenshot(path=str(screenshots / "loop5-runs-fixture.png"), full_page=True)
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        page.screenshot(path=str(screenshots / "loop5-runs-mobile-fixture.png"), full_page=True)
        page.set_viewport_size({"width": 1600, "height": 1100})

        # A new source record must appear from polling without a click or navigation.
        with (source / "status.txt").open("a") as file:
            file.write("2026-10-19T11:00:00Z td-a007 build start\n")
        expect(page.locator("#selection")).to_contain_text("11 recorded runs selected", timeout=22000)
        print("PASS automatic polling reflects new source records without manual reload")

        page.route("**/api/runs", lambda route: route.fulfill(status=503, body="{}"))
        page.locator("#refresh").click()
        expect(page.locator("#messages")).to_contain_text("last successful snapshot")
        expect(page.locator("#models tbody tr")).to_have_count(3)
        page.unroute("**/api/runs")
        page.locator("#refresh").click()
        expect(page.locator("#messages")).to_be_hidden()
        server.runs_store = RunsStore(source / "missing")
        page.locator("#refresh").click()
        expect(page.locator("#messages")).to_contain_text("missing or unreadable")
        page.get_by_role("link", name="Corylus project flow").click()
        expect(page.locator("#refresh")).to_be_enabled()
        assert page.request.get(base + "/api/projects").ok
        print("PASS stale-data failure/recovery, missing-directory message and viewer isolation")
        assert not errors, errors
        assert not external, external
        browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default=shutil.which("chromium"))
    parser.add_argument("--screenshots", type=Path, default=ROOT / "test-results")
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="corylus-runs-browser-") as directory:
        source = Path(directory)
        points = write_fixture(source)
        projects = projects_from_specs([f"Fixture={source}"])
        store = FlowStore(projects, exporter=lambda project, _: normalize_export([], project))
        server = FlowServer(("127.0.0.1", 0), store,
                            runs_store=RunsStore(source, points_provider=lambda: points))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            check(f"http://127.0.0.1:{server.server_port}", server, source,
                  args.screenshots, args.chromium)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    main()
