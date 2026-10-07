# Left-to-right epic dependencies

Written by an AI agent (Codex).

Chromium comparison against `cda18d5`, using the existing scheduled homelab
snapshot on 2026-10-07. No export command, deployment, or tracker snapshot
modification. Ticket text is anonymized; screenshots retain real topology,
ticket IDs, priorities, and statuses. The snapshot hash is in the metrics file.

The baseline already uses ELK `RIGHT` for connected local chains. Its wrapping
places two dependencies between local components and nested epic boxes
vertically or backward. Keep these linked groups horizontal inside each epic;
unrelated groups and dependency-ordered root epic rows still wrap. Tighten gaps
to 8px and give nested boxes the remaining horizontal space to retain compact
bounds. Cards and epic labels retain their dimensions.

| Evidence | Before | After |
| --- | ---: | ---: |
| Tickets / dependency paths | 245 / 116 | 245 / 116 |
| Cards / epic boxes / sidebar cards | 184 / 21 / 39 | 184 / 21 / 39 |
| Immediate-epic edges right / left / vertical | 60 / 1 / 1 | 62 / 0 / 0 |
| Shared rendered epic ancestor edges right / left / vertical | 62 / 3 / 1 | 66 / 0 / 0 |
| Rendered bounds | 1408 × 6392 | 1584 × 5800 |
| Rendered area | 8,999,936 | 9,187,200 (+2.08%) |

The unchanged compactness gate allows at most 5% area growth. All 72 JavaScript
tests, the Python suite (72 tests, one scheduled-export restriction skip), Ruff,
ESLint, and both Chromium suites pass. New direction tests fail twice against
the baseline and pass with the fix; nested containment, sidebar membership,
top anchors, wrapping, selection, filters, and complete Fit remain covered.
A bounded ELK-call test covers deep nested epics; placement caching and a strict
width-reduction guard prevent repeated work at unchanged widths.

Round 1 review reproduced an acyclic diamond: epic E contains a, b, and nested
epic N(n), with edges a → b, a → n, and n → b. Contracting a and b into one
local block introduced a cycle in the block ordering and placed n after b.
Only local components in a projected cycle through a nested box now split
into topological slices; unaffected components retain their compact ELK layout.
ELK and Chromium regressions at widths 1400 and 450 require a.x < n.x < b.x,
all three routes, and nested containment. Before: a.x=24, n.x=420, b.x=216;
after: a.x=24, n.x=228, b.x=432. Diamond bounds remain 640 × 228.

The snapshot gate now includes dependencies across nested boxes with a shared
rendered epic ancestor. Flattened umbrella page frames retain their intentional
root-row wrapping. The refreshed round 2 snapshot comparison passes that gate
and preserves the original area and node/path counts.

![Focused before](round2/homelab-td-f136a9-before.png)
![Focused after](round2/homelab-td-f136a9-after.png)

[Full before](round2/homelab-before.png), [full after](round2/homelab-after.png),
[initial framing after](round2/homelab-after-initial.png),
[machine-readable metrics](round2/homelab-layout-metrics.json),
[desktop diamond](round2/horizontal-diamond-1400.png),
[narrow diamond](round2/horizontal-diamond-450.png).

Root epic rows retain dependency order and wrap to the viewport. Cross-epic
arrows can span rows; cyclic relationships cannot all point right. Orthogonal
routes retain the existing limitation of no intervening-box obstacle avoidance.
This is local source evidence; independent review and orchestrator deployment
remain separate.

Reproduce without exporting:

```sh
uv run --no-project --with playwright==1.55.0 --with httpx python tests/check_flow_layout.py \
  --snapshot /srv/projects/homelab/.todos/export.json \
  --baseline-ref cda18d5 --focus-epic td-f136a9 \
  --screenshots /tmp/td-1e9ebe-evidence
```
