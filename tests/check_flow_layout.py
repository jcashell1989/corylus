#!/usr/bin/env python3
"""Chromium epic geometry checks and safe scheduled-snapshot comparisons.

The optional tracker comparison only reads an existing scheduled snapshot.
Screenshots anonymize ticket text while retaining the real topology and statuses.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from td_flow import FlowServer, FlowStore, normalize_export, projects_from_specs  # noqa: E402


def ticket(ticket_id, *, kind="task", parent=None, dependencies=(), status="open"):
    return {
        "id": ticket_id, "title": ticket_id, "type": kind, "status": status,
        "priority": "P1", "parent_id": parent, "depends_on": list(dependencies),
        "description": "Fixture description", "acceptance": "Containment and selection agree.",
    }


def payload(tickets):
    return {
        "project": {"id": "fixture", "name": "Fixture"}, "tickets": tickets,
        "epics": [t for t in tickets if t["type"] == "epic"], "warnings": [],
        "edges": [{"source": prerequisite, "target": t["id"]}
                  for t in tickets for prerequisite in t["depends_on"]],
    }


def nested_fixture():
    return payload([
        ticket("A", kind="epic"),
        ticket("B", kind="epic", parent="A", dependencies=["D"]),
        ticket("C", parent="B"), ticket("D", status="closed"),
        ticket("a-task", parent="A"), ticket("another-a-task", parent="A"),
        ticket("E", kind="epic", parent="A"), ticket("e-task", parent="E"),
        ticket("F", kind="epic", dependencies=["B"]), ticket("f-task", parent="F"),
        ticket("G", kind="epic"), ticket("g-task", parent="G"),
        ticket("shelf"),
    ])


@contextmanager
def server_for(data, static_dir=None):
    projects = projects_from_specs([f"Fixture={ROOT}"])
    store = FlowStore(projects, cache_seconds=0, exporter=lambda *_: copy.deepcopy(data))
    server = FlowServer(("127.0.0.1", 0), store, static_dir=static_dir or ROOT / "static")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def bounds(page, selector):
    """Use unscaled SVG coordinates, independent of fit zoom and panning."""
    return page.locator(selector).evaluate(
        "node => { const r=node.getBBox(), m=node.transform?.baseVal.consolidate()?.matrix;"
        "return {x:r.x+(m?.e||0), y:r.y+(m?.f||0), width:r.width, height:r.height}; }"
    )


def epic_selector(ticket_id):
    return f'.epic-container[data-ticket="{ticket_id}"] .epic-boundary'


def card_selector(ticket_id):
    return f'.node-card[data-ticket="{ticket_id}"]'


def contains(outer, inner):
    epsilon = 0.01
    return (
        outer["x"] <= inner["x"] + epsilon and outer["y"] <= inner["y"] + epsilon
        and outer["x"] + outer["width"] >= inner["x"] + inner["width"] - epsilon
        and outer["y"] + outer["height"] >= inner["y"] + inner["height"] - epsilon
    )


def wait_graph(page):
    expect(page.locator("#refresh")).to_be_enabled()
    expect(page.locator(".node-card, .epic-boundary").first).to_be_visible()
    expect(page.locator("#messages")).not_to_contain_text("Graph layout failed")


def check_fixture(browser, screenshots):
    errors = []
    page = browser.new_page(viewport={"width": 1900, "height": 1050})
    page.on("pageerror", lambda error: errors.append(str(error)))
    data = nested_fixture()
    with server_for(data) as url:
        page.goto(url)
        expect(page.locator(".ticket-row")).to_have_count(13)
        wait_graph(page)
        initial = page.locator("#graph-scene").evaluate(
            "n => {const m=n.transform.baseVal.consolidate().matrix; return {y:m.f,scale:m.a};}",
        )
        assert initial["y"] == 16, "Initial graph framing must anchor the top"
        assert initial["scale"] >= 0.5, "Initial epic cards must remain readable"
        membership = page.evaluate(
            "data => Object.fromEntries(FlowModel.prepare(data).membership)", data,
        )
        assert membership["B"] == "A", membership
        assert membership["C"] == "B", membership
        a, b, e = (bounds(page, epic_selector(key)) for key in ("A", "B", "E"))
        assert contains(a, b), "Nested epic B must be enclosed by A"
        assert contains(b, bounds(page, card_selector("C"))), "C must be inside B"
        assert contains(a, bounds(page, card_selector("a-task")))
        assert abs(b["y"] - e["y"]) < 0.01, "Nested sibling epic boxes must be top-aligned"
        expect(page.locator('.ticket-row[data-ticket="B"] td').nth(5)).to_have_text("A")
        expect(page.locator('#independent-list [data-ticket]')).to_have_count(1)
        expect(page.locator('#independent-list [data-ticket="shelf"]')).to_have_count(1)
        for key in ("C", "a-task", "e-task", "f-task", "g-task"):
            expect(page.locator(card_selector(key))).to_have_count(1)
            expect(page.locator(f'#independent-list [data-ticket="{key}"]')).to_have_count(0)
        for source, target in (("D", "B"), ("B", "F")):
            expect(page.locator(f'.graph-edge[data-source="{source}"][data-target="{target}"]')).to_have_count(1)
        label = page.locator('.epic-container[data-ticket="B"] .epic-label')
        label.focus()
        page.keyboard.press("Enter")
        expect(label).to_be_focused()
        expect(page.locator('.ticket-row[data-ticket="B"]')).to_have_class("ticket-row selected")
        page.keyboard.press("Space")
        expect(label).to_be_focused()
        expect(page.locator('.ticket-row[data-ticket="B"]')).to_have_class("ticket-row selected")
        page.screenshot(path=str(screenshots / "nested-desktop.png"), full_page=True)
        wide = {key: bounds(page, epic_selector(key)) for key in ("A", "F", "G")}
        for key in ("F", "G"):
            assert abs(wide[key]["y"] - wide["A"]["y"]) < 0.01, "Desktop root epic row must be top-aligned"
        page.set_viewport_size({"width": 800, "height": 1050})
        page.wait_for_function(
            """() => {const a=document.querySelector('.epic-container[data-ticket="A"] .epic-boundary');
            const f=document.querySelector('.epic-container[data-ticket="F"] .epic-boundary');
            return a && f && f.getBBox().y > a.getBBox().y;}""",
        )
        narrow = {key: bounds(page, epic_selector(key)) for key in ("A", "F", "G")}
        assert narrow["F"]["y"] > narrow["A"]["y"], "Viewport resize must wrap epic boxes"
        assert narrow["F"]["x"] < wide["F"]["x"], "Wrapped row must restart at the left"
        page.screenshot(path=str(screenshots / "nested-wrapped.png"), full_page=True)
        page.set_viewport_size({"width": 1900, "height": 1050})
        page.wait_for_function(
            """() => {const a=document.querySelector('.epic-container[data-ticket="A"] .epic-boundary');
            const f=document.querySelector('.epic-container[data-ticket="F"] .epic-boundary');
            return a && f && Math.abs(f.getBBox().y-a.getBBox().y)<.01;}""",
        )
        print("PASS nested epic membership, containment, labels, strict shelf, cross-epic edges and resize wrapping")
    horizontal = payload([
        ticket("root-epic", kind="epic"),
        ticket("source", parent="root-epic"),
        ticket("target", parent="root-epic", dependencies=["nested-target"]),
        ticket("source-epic", kind="epic", parent="root-epic"),
        ticket("target-epic", kind="epic", parent="root-epic"),
        ticket("nested-source", parent="source-epic", dependencies=["source"]),
        ticket("nested-target", parent="target-epic", dependencies=["nested-source"]),
    ])
    with server_for(horizontal) as url:
        page.goto(url)
        expect(page.locator(".ticket-row")).to_have_count(7)
        wait_graph(page)
        page.evaluate("""() => {
          const layout=FlowModel.layout;
          window.horizontalLayoutCompletions=0;
          FlowModel.layout=async (...args) => {
            const result=await layout(...args);
            window.horizontalLayoutCompletions++;
            return result;
          };
        }""")
        for width in (1900, 800):
            page.set_viewport_size({"width": width, "height": 1050})
            if width == 800:
                page.wait_for_function("() => window.horizontalLayoutCompletions > 0")
            # All linked blocks stay in one horizontal group at either viewport width.
            for source, target in (("source", "nested-source"),
                                   ("nested-source", "nested-target"),
                                   ("nested-target", "target")):
                assert bounds(page, card_selector(source))["x"] < bounds(page, card_selector(target))["x"], (
                    f"Epic-local dependency {source} -> {target} must flow horizontally")
            root = bounds(page, epic_selector("root-epic"))
            for key in ("source-epic", "target-epic"):
                assert contains(root, bounds(page, epic_selector(key)))
        page.screenshot(path=str(screenshots / "horizontal-nested.png"), full_page=True)
        print("PASS horizontal epic-local dependencies across nested boxes and disconnected local blocks")
    umbrella = payload([
        ticket("umbrella", kind="epic"),
        ticket("a", kind="epic", parent="umbrella"), ticket("a1", parent="a"),
        ticket("b", kind="epic", parent="umbrella"), ticket("b1", parent="b", dependencies=["a1"]),
        ticket("c", kind="epic", parent="umbrella"), ticket("c1", parent="c"),
    ])
    with server_for(umbrella) as url:
        page.goto(url)
        expect(page.locator(".ticket-row")).to_have_count(7)
        wait_graph(page)
        expect(page.locator(epic_selector("umbrella"))).to_have_count(0)
        expect(page.locator(".epic-boundary")).to_have_count(3)
        for key in ("a", "b", "c"):
            expect(page.locator(epic_selector(key))).to_have_count(1)
        expect(page.locator('.graph-edge[data-source="a1"][data-target="b1"]')).to_have_count(1)
        expect(page.locator('#independent-list [data-ticket]')).to_have_count(0)
        page.screenshot(path=str(screenshots / "umbrella-frame.png"), full_page=True)
        page.locator("#search").fill("a1")
        expect(page.locator(".ticket-row")).to_have_count(1)
        expect(page.locator(".epic-boundary")).to_have_count(1)
        expect(page.locator(epic_selector("umbrella"))).to_have_count(0)
        assert contains(bounds(page, epic_selector("a")), bounds(page, card_selector("a1")))
        page.locator("#clear-filters").click()
        expect(page.locator(".epic-boundary")).to_have_count(3)
        expect(page.locator(epic_selector("umbrella"))).to_have_count(0)
        print("PASS umbrella epic is the page frame with child boxes and dependencies preserved")
    assert not errors, errors
    page.close()


def read_snapshot(path):
    raw = path.read_bytes()
    project = next(iter(projects_from_specs([f"Fixture={ROOT}"]).values()))
    data = normalize_export(json.loads(raw), project)
    # Titles and ticket details can contain private infrastructure information.
    # Strip all free text from public comparison screenshots, preserving topology.
    for issue in data["tickets"]:
        issue["title"] = issue["id"]
        issue["description"] = issue["acceptance"] = issue["updated_at"] = ""
        issue["labels"] = []
    for epic in data["epics"]:
        epic["title"] = epic["id"]
    data["warnings"] = []
    data["project"]["name"] = "Homelab topology (ticket text anonymized)"
    return data, hashlib.sha256(raw).hexdigest()


def direction_metrics(page, data):
    """Measure card and epic endpoints, including links to nested epic boxes."""
    return page.evaluate("""data => {
      const membership=FlowModel.prepare(data).membership;
      const positions=new Map();
      for (const node of document.querySelectorAll('.node-card, .epic-container')) {
        const shape=node.classList.contains('epic-container') ? node.querySelector('.epic-boundary') : node;
        const r=shape.getBBox(), m=shape.transform?.baseVal.consolidate()?.matrix;
        positions.set(node.dataset.ticket,{x:r.x+(m?.e||0),y:r.y+(m?.f||0)});
      }
      const edges=data.edges.filter(e=>positions.has(e.source)&&positions.has(e.target)).map(e=>{
        const a=positions.get(e.source), b=positions.get(e.target);
        const epic=membership.get(e.source);
        return {...e,epic:epic||null,same_epic:Boolean(epic && epic===membership.get(e.target)),
          direction:b.x>a.x+.01 ? 'right' : b.x<a.x-.01 ? 'left' : 'vertical',
          source_x:a.x,target_x:b.x,source_y:a.y,target_y:b.y};
      });
      const counts=items=>Object.fromEntries(['right','left','vertical'].map(d=>[d,items.filter(e=>e.direction===d).length]));
      return {same_epic:counts(edges.filter(e=>e.same_epic)),
        other:counts(edges.filter(e=>!e.same_epic)),same_epic_edges:edges.filter(e=>e.same_epic)};
    }""", data)


def focus_snapshot(page, data, epic_id, screenshot):
    """Capture an anonymized epic at readable scale after its filtered layout settles."""
    expected = page.evaluate("""({data,epic}) => {
      const ids=[];
      function visit(node) {
        if (node.id !== 'root') ids.push(node.id.replace(/^epic:/,''));
        (node.children||[]).forEach(visit);
      }
      visit(FlowModel.prepare(data,{epic}).graph);
      return ids.sort();
    }""", {"data": data, "epic": epic_id})
    page.locator("#epic").select_option(epic_id)
    page.wait_for_function("""expected => {
      const ids=[...document.querySelectorAll('.node-card, .epic-container')].map(n=>n.dataset.ticket).sort();
      return JSON.stringify(ids)===JSON.stringify(expected);
    }""", arg=expected)
    wait_graph(page)
    page.locator("#fit").click()
    page.screenshot(path=str(screenshot), full_page=True)


def measure(browser, data, static_dir, screenshot, focus_epic=None):
    page = browser.new_page(viewport={"width": 1716, "height": 1100})
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    with server_for(data, static_dir) as url:
        started = time.monotonic()
        page.goto(url)
        expect(page.locator(".ticket-row")).to_have_count(len(data["tickets"]))
        wait_graph(page)
        elapsed = time.monotonic() - started
        initial = page.locator("#graph-scene").evaluate(
            "n => {const m=n.transform.baseVal.consolidate().matrix; return {x:m.e,y:m.f,scale:m.a};}",
        )
        if screenshot.stem.endswith("after"):
            assert initial["y"] == 16, "Real tracker initial framing must start at the top"
            assert initial["scale"] >= 0.5, "Real tracker initial cards must remain readable"
            page.screenshot(path=str(screenshot.with_name("homelab-after-initial.png")), full_page=True)
        for _ in range(6):
            page.locator("#divider").press("ArrowDown")
        page.locator("#fit").click()
        viewport = page.locator("#graph-viewport").bounding_box()
        scene = page.locator("#graph-scene").bounding_box()
        assert contains(viewport, scene), "Explicit Fit must include every wrapped graph row"
        page.screenshot(path=str(screenshot), full_page=True)
        result = page.evaluate("""() => {
          const bounds=document.querySelector('#graph-scene').getBBox();
          return {width:bounds.width,height:bounds.height,area:bounds.width*bounds.height,
            cards:document.querySelectorAll('.node-card').length,
            epic_boxes:document.querySelectorAll('.epic-boundary').length,
            edge_paths:document.querySelectorAll('.graph-edge').length,
            shelf:document.querySelectorAll('#independent-list [data-ticket]').length,
            viewport:document.querySelector('#graph-viewport').clientWidth};
        }""")
        result["dependency_direction"] = direction_metrics(page, data)
        if focus_epic:
            focus_snapshot(page, data, focus_epic,
                           screenshot.with_name(f"homelab-{focus_epic}-{screenshot.stem.split('-')[-1]}.png"))
        result["page_ready_seconds"] = round(elapsed, 3)
        result["initial_transform"] = initial
        assert not errors, errors
        page.close()
        return result


def compare_snapshot(browser, path, baseline_ref, screenshots, focus_epic=None):
    data, digest = read_snapshot(path)
    with tempfile.TemporaryDirectory(prefix="corylus-layout-before-") as directory:
        static = Path(directory) / "static"
        shutil.copytree(ROOT / "static", static)
        for name in ("flow_model.js", "flow.js", "flow.css", "flow.html"):
            original = subprocess.run(
                ["git", "show", f"{baseline_ref}:static/{name}"], cwd=ROOT,
                capture_output=True, check=True,
            ).stdout
            (static / name).write_bytes(original)
        before = measure(browser, data, static, screenshots / "homelab-before.png", focus_epic)
    after = measure(browser, data, ROOT / "static", screenshots / "homelab-after.png", focus_epic)
    result = {
        "snapshot_sha256": digest, "snapshot_records": len(data["tickets"]),
        "snapshot_dependencies": len(data["edges"]), "baseline_ref": baseline_ref,
        "ticket_text_anonymized": True, "before": before, "after": after,
        "area_change_percent": round((after["area"] / before["area"] - 1) * 100, 2),
    }
    (screenshots / "homelab-layout-metrics.json").write_text(json.dumps(result, indent=2) + "\n")
    summary = copy.deepcopy(result)
    for phase in ("before", "after"):
        del summary[phase]["dependency_direction"]["same_epic_edges"]
    print(json.dumps(summary, indent=2))
    same_epic = after["dependency_direction"]["same_epic"]
    assert same_epic["right"] > 0, "Real tracker must exercise dependencies within epics"
    assert same_epic["left"] == same_epic["vertical"] == 0, "Epic-local prerequisites must flow left to right"
    assert after["area"] <= before["area"] * 1.05, "Real tracker must stay compact (maximum 5% area growth)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default=shutil.which("chromium"))
    parser.add_argument("--screenshots", type=Path, default=ROOT / "test-results" / "epic-layout")
    parser.add_argument("--snapshot", type=Path, help="Existing scheduled .todos/export.json; read only")
    parser.add_argument("--baseline-ref", default="c14112c")
    parser.add_argument("--focus-epic", help="Also screenshot this anonymized epic before and after")
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=args.chromium, headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            check_fixture(browser, args.screenshots)
            if args.snapshot:
                compare_snapshot(browser, args.snapshot, args.baseline_ref, args.screenshots, args.focus_epic)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
