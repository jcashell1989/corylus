# Corylus

Corylus is the genus of the hazel; the dashboard's internal codename was Catkin —
the hazel's flower — so the lineage is real. A review queue for judged agent work
on Vikunja. Runs on loopback or a private network; not meant for the open internet.

- Binds `localhost:8789` (override `HERMES_REVIEW_HOST` / `HERMES_REVIEW_PORT`)
- Reads Vikunja + `hermes:attempt` / `hermes:judge` / `hermes:control` / `hermes:session` machine comments
- Diffs via `git-range` when an attempt has git pointers
- Writes dispositions back to Vikunja (labels + comments + `not_before`)
- Activity / Metrics are pipeline ops views (health, problems, claims, agent.log API calls). Spend is an estimate from tokens × OpenRouter list prices, not billed.
- Discuss column is a per-ticket Hermes session via loopback webui (`127.0.0.1:8787`). Browser never talks to `:8787`. Transcript is not copied to Vikunja.
- Vikunja API token never leaves the box. Writes require a per-start `X-Hermes-Review-Token` (injected into the HTML) and a `Host` header matching the configured bind host. That is CSRF / DNS-rebinding protection, not an ACL: a peer who can load the page can scrape the token. Bind to loopback or a network you control.

## Configuration

| Env var | Default | Meaning |
|---|---|---|
| `HERMES_REVIEW_HOST` | `localhost` | Bind address; the `Host` header must match it for writes |
| `HERMES_REVIEW_PORT` | `8789` | Listen port |
| `HERMES_REVIEW_TAILNET` | RFC 6598 CGNAT /10 | Network whose peers get host-relative Vikunja UI links |
| `VIKUNJA_URL` | config, else `localhost:8788` | Vikunja API base |
| `HERMES_WEBUI_URL` | `http://127.0.0.1:8787` | Loopback webui base for Discuss sessions |

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user restart hermes-review
```

## URL state

Restorable view state lives in the query string. Clicks and keyboard navigation call `history.pushState` (no full reload). Reloads, pasted links, and browser back/forward re-apply the same fields. Invalid or unknown parameters fall back to the defaults below.

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

Not encoded: drafts, toasts, discard/revise overlays, pane widths, multi-select, artifact/compare expand.

Example: `http://localhost:8789/?view=review&task=52` · blocked: `?view=blocked&blocked=8`

```bash
node --test tests/test_url_state.js tests/test_disposition.js
~/.hermes/hermes-agent/venv/bin/python -m unittest tests/test_write_auth.py tests/test_serialize_judge.py tests/test_judge_for_attempt.py tests/test_undo.py tests/test_monitor.py tests/test_board_bucket.py
```
