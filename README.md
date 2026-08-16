# Hermes Review

Catkin dashboard for judged Vikunja tasks. LAN / tailnet only.

- Binds `localhost:8789` (override `HERMES_REVIEW_HOST` / `HERMES_REVIEW_PORT`)
- Reads Vikunja + `hermes:attempt` / `hermes:judge` / `hermes:control` / `hermes:session` machine comments
- Diffs via `git-range` when an attempt has git pointers
- Writes dispositions back to Vikunja (labels + comments + `not_before`)
- Discuss column is a per-ticket Hermes session via loopback webui (`127.0.0.1:8787`). Browser never talks to `:8787`. Transcript is not copied to Vikunja.
- Token and webui password never leave the box

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
systemctl --user restart hermes-review
```
