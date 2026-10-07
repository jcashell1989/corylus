# td project flow

The project flow viewer is a Corylus building block: a dependency graph above
a linked ticket table, backed by explicitly selected per-project `td` trackers.
The existing Vikunja review application remains a separate entry point.

## Run locally

Python 3.11+ and `td` on `PATH` are the only runtime requirements. The initial
adapter is verified against `td` 0.61.0's JSON export format. The font and layout
engine are served locally; the browser makes no CDN requests.

```bash
python3 td_flow.py
```

Open `http://127.0.0.1:8791/`. The default project is the current working
directory; it must already contain an initialized `td` tracker, or resolve to
one through `td`'s normal project resolution. The viewer never initializes or
imports a tracker on a visitor's behalf.

Select several local projects with explicit operator-owned arguments:

```bash
python3 td_flow.py \
  --project 'Corylus=/srv/projects/corylus' \
  --project 'Another project=/absolute/path/to/another-project' \
  --port 8791
```

Use `--td /absolute/path/to/td` if the service account's `PATH` does not include
the intended binary. The browser selects a project by its public identifier;
it cannot supply a directory or change the operator's allowlist.

`http://127.0.0.1:8791/?demo=1` explicitly loads fictional sample data from the
approved mockup. A visible **Sample data** badge distinguishes it from live
tracker data. Sample mode is never a fallback when a live tracker fails.

## How tickets are placed

- Arrows point from a prerequisite to the ticket that depends on it.
- Epic outlines describe membership. They do not imply dependency edges.
- Connected tickets without an epic remain on the canvas outside epic outlines.
- Tickets with no incoming **and** no outgoing dependency edges appear in the
  independent shelf. Epic membership is retained there as grouping.
- A ticket with no prerequisites but with dependents is a starting node in the
  graph. It is not independent.
- Classification uses the complete project graph. Filters do not move a
  connected ticket to the independent shelf just because its neighbor is
  hidden. The graph indicates connections outside the filtered view.
- Epics also remain available as records in the table. Hierarchical membership
  resolves through intermediate parent tickets to the nearest epic.

The layout uses network-simplex node placement, edge-length post-compaction,
and tighter card/edge spacing in both the root graph and each epic. It retains
left-to-right flow and orthogonal dependency arrows. Disconnected components
use ELK's existing component packing. Only matching cards and edges enter the
layout; changing filters lays out and fits the smaller graph. Connected cards
whose neighbors are hidden remain on the canvas with hidden-link indicators.
The [Homelab comparison](evidence/td-8a2b90/README.md) records measured bounds,
routed edge lengths, and before/after Chromium screenshots.

Selecting a card or table row highlights the same ticket in both panes and
reveals its description and acceptance criteria. Project, epic, status, priority
and text filters apply to both views. The table supports column sorting.
Drag the canvas to pan, use the zoom controls or scroll to zoom, and select
**Fit view** to reset the viewport. The horizontal divider resizes the two
panes and can also be adjusted with the keyboard.

Source failures, missing relationship targets and cycles are reported visibly.
A cyclic graph is displayed as a dependency graph with a warning; it is not
presented as a valid DAG. Previously loaded data must not be mistaken for a
successful refresh after a source failure.

## Data access and hosting

The service invokes a bounded `td export --all --format json` process for each
allowed project. There are no ticket write routes, review actions or direct
database writes in this building block. `td` itself may perform ordinary local
bookkeeping or migrations when opening a project; this is not a filesystem
immutability guarantee. The export is normalized before being sent to the
browser, and a short per-project cache prevents repeated work on rapid refresh.

The default listener is loopback. Host checking, an exact static-file allowlist
and project identifiers prevent the browser from turning the service into an
arbitrary filesystem reader. Errors and access logs omit configured source
paths and raw `td` output. Ticket content is intentionally visible to anyone
who can access the viewer. This viewer has no user authentication or per-record
authorization layer.

The homelab placement plan assigns **CT 103 (`dev`)** to development and
**CT 220 (`apps`)** to eventual Corylus hosting. Running locally on `dev` is
appropriate while the authoritative project trackers live there. Hosting on
`apps` requires a separately approved deployment and an explicit source-access
plan: project paths on `dev` are not automatically available on `apps`.
An approved data bridge or available local tracker copies must describe their
authority and freshness; stale copies cannot be presented as live project data.

Before exposing the service beyond loopback, use an approved listener address
and access protection for the ticket contents, refresh capacity and recovery
checks on the target guest, and verify the chosen source-access arrangement.
This implementation does not provision guests, change firewall/edge routes,
migrate trackers or install a persistent service.

## Development checks

Install dependencies only into the project environment:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
npm ci --ignore-scripts
make test lint PYTHON=.venv/bin/python
make browser-test PYTHON=.venv/bin/python
```

The Python development dependencies include `httpx` for the legacy tests,
Ruff for the new feature's Python code, and Playwright for browser checks.
ESLint checks the new application scripts and model tests. Existing review
tests run as regressions with fixture configuration and an empty temporary
Hermes home; the runner never reads a live Vikunja config or credential file.
The vendored ELK bundle is excluded from linting.

Browser checks use an installed Chromium executable or Playwright's Chromium.
They verify actual `td` fixture data as well as the labeled mockup sample,
selection, dependency placement, filters, zoom, panning, pane resizing,
responsive layout and error handling. Use `--help` on the browser-check script
for executable and screenshot options. Browser dependencies are development
tools; they are not needed to serve the viewer.

The implementation passed 71 Python tests, 47 JavaScript tests, Ruff and
ESLint, plus Chromium checks against real temporary `td` projects. The browser
checks cover project switching and URL reload, initial and refresh failures,
keyboard selection, cyclic and orphan relationships, literal ticket content,
and the absence of external network requests. Desktop, laptop and mobile
screenshots are saved under `test-results/`; mobile checks establish layout
visibility, not physical-device validation.

Independent source review found no outstanding issues after fixes for ancestry
lookup performance, sorting before data loads and keyboard activation of
prerequisite links. This evidence covers the local implementation; it does not
establish deployment, authentication or source freshness on another guest.
