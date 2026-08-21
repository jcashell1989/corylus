# URL state reference

Restorable view state lives in the query string. Clicks and keyboard
navigation call `history.pushState` (no full reload). Reloads, pasted links,
and browser back/forward re-apply the same fields. Invalid or unknown
parameters fall back to the defaults below.

| Param | Meaning | Default if missing or invalid |
|---|---|---|
| `view` | `home` · `review` · `queue` · `human` · `blocked` · `timeline` · `stats` | `home` |
| `task` | Vikunja task id in the review pane | none |
| `cursor` | index in the pending review list | `0` |
| `filter` | `all` · `low` · `high` · or a verdict (`approve` / `remediate` / `split` / `human` / `thin`) | `all` |
| `open` | comma-separated open review sections | `description,attempt,history` |
| `human` | expanded row on the human-only list | none |
| `blocked` | expanded row on the blocked list | none |
| `window` | Activity/Metrics time window: `24h` · `7d` · `all` | `7d` |
| `akind` | event kind: `all` · `attempt` · `judge` · `preflight` · `disposition` · `reaper` · `call` | `all` |
| `lane` | `all` · `worker` · `worker-escalate` · `judge` · `judge-escalate` | `all` |
| `model` | exact judge/call model string | `all` |

Not encoded: drafts, toasts, discard/revise overlays, pane widths,
multi-select, artifact/compare expand.
