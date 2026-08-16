# Hermes Review

Catkin dashboard for judged Vikunja tasks. LAN / tailnet only.

- Binds `localhost:8789` (override `HERMES_REVIEW_HOST` / `HERMES_REVIEW_PORT`)
- Reads Vikunja + `hermes:attempt` / `hermes:judge` / `hermes:control` machine comments
- Diffs via `git-range` when an attempt has git pointers
- Writes dispositions back to Vikunja (labels + comments + `not_before`)
- Token never leaves the box

Live Hermes chat is **Phase 5**. The discuss column posts ordinary Vikunja comments.

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user restart hermes-review
```
