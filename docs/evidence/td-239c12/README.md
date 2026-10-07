Written by an AI agent (Codex).

# Epic columns: td-239c12

Reproduced deployed base `752f8d5` using the existing scheduled Homelab snapshot,
read only. No `td export` commands ran, and `.todos/export.json` was not edited.
Snapshot: 245 tickets and 116 dependencies. This older scheduled snapshot has
22 epic records and 96 connected non-epic tickets; it differs from Julian's
newer deployed screenshot (23 epics, 141 connected tickets). The comparison
preserves its complete topology. Free text is anonymized; raw data is not stored.

| Metric | Before | After |
| --- | ---: | ---: |
| Unscaled bounds | 1584 × 5852 | 13082 × 2204 |
| Root epic y positions | 16 through 5716 | all 16 |
| Acyclic cross-root dependencies facing backward | 8 / 10 | 0 / 10 |
| Rendered cards / epic boxes / arrows / sidebar cards | 184 / 21 / 116 / 39 | 184 / 21 / 116 / 39 |
| Shared-epic-ancestor dependencies facing right | 66 / 66 | 66 / 66 |

The new map is landscape (5.94:1). Its unscaled area grows 211.05%: one row of
columns and vertical unlinked-member lists trade packing density for the latest
layout requirement. The old 5% area gate tested wrapped rows; it is replaced
with landscape, equal sibling tops, induced acyclic dependency order and exact
rendered-count preservation checks. The original synthetic 15% compaction gate
still passes. Induced epic dependencies include 34 edges within cycles, where
strict left-to-right order is impossible; SCCs use stable priority then id and
preserve ordering between components. Iterative SCC passes avoid recursion limits.

Automatic framing remains top anchored with a readable 50% minimum scale;
explicit Fit includes the full map. Unlinked epic members share one vertical
list rather than a wide grid. Nested membership, sidebar classification,
all dependency routes, both nested/page diamonds, containment, filters and
keyboard interactions remain covered. Cross-box paths retain the existing
limitation: they do not avoid intervening boxes in dense or cyclic maps.

- [Before: full Homelab Fit](homelab-before.png)
- [After: full Homelab Fit](homelab-after.png)
- [After: readable initial framing](homelab-after-initial.png)
- [Desktop columns/list fixture](epic-columns-1400.png)
- [Narrow columns/list fixture](epic-columns-450.png)
- [Machine-readable metrics](homelab-layout-metrics.json)

Validation: `npm test` 77 pass, 0 fail; Python runner 72 tests OK, one explicit
export-restriction skip; viewer Ruff and ESLint pass; Chromium geometry and
complete browser suites pass. Full scheduled map ready in approximately 1.6s;
synthetic 290-ticket layout stays below the existing ten-second budget.

No deployment or live changes. Orchestrator retains independent acceptance and
redeployment.
