# Hermes Review

Catkin dashboard for judged Vikunja tasks. LAN / tailnet only.

- Binds `localhost:8789` (override `HERMES_REVIEW_HOST` / `HERMES_REVIEW_PORT`)
- Reads Vikunja + `hermes:attempt` / `hermes:judge` / `hermes:control` / `hermes:session` machine comments
- Diffs via `git-range` when an attempt has git pointers
- Writes dispositions back to Vikunja (labels + comments + `not_before`)
- Discuss column is a per-ticket Hermes session via loopback webui (`127.0.0.1:8787`). Browser never talks to `:8787`. Transcript is not copied to Vikunja.
- Vikunja API token never leaves the box. Writes require a per-start `X-Hermes-Review-Token` (injected into the HTML) and `Host: localhost`. That is CSRF / rebinding protection, not a tailnet ACL: a peer who loads the page can scrape the token. `Host: localhost` is refused on purpose so this Mac can use the tailnet bind.

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user restart hermes-review
```

## URL state

Restorable view state lives in the query string. Clicks and keyboard navigation call `history.pushState` (no full reload). Reloads, pasted links, and browser back/forward re-apply the same fields. Invalid or unknown parameters fall back to the defaults below.

| Param | Meaning | Default if missing or invalid |
|---|---|---|
| `view` | `home` · `review` · `queue` · `human` · `timeline` · `stats` | `home` |
| `task` | Vikunja task id in the review pane | none |
| `cursor` | index in the pending review list | `0` |
| `filter` | `all` · `low` · `high` · or a verdict (`approve` / `remediate` / `split` / `human` / `thin`) | `all` |
| `open` | comma-separated open review sections | `description,attempt,history` |
| `human` | expanded row on the human-only list | none |

Not encoded: drafts, toasts, discard/revise overlays, pane widths, multi-select, artifact/compare expand.

Example: `http://localhost:8789/?view=review&task=52`

```bash
node --test tests/test_url_state.js tests/test_disposition.js
~/.hermes/hermes-agent/venv/bin/python -m unittest tests/test_write_auth.py
```
