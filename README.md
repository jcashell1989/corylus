# Corylus

Corylus is the control layer for an automated agentic work pipeline: fast,
reliable human judgment over everything the machines ship.

## Why

Lately, I've found myself in a loop: writing tickets, having agents perform them, 
then having another agent rip it apart before I judge it for myself. It's a 
useful pattern for producing somewhat pressure-tested code, but I started to get 
tired of triggering review skills and manually telling the agent to keep going.

So I automated myself out of it. 

## What

Corylus sits in between three services:

1. Hermes Agent as an agent runtime
2. Vikunja as a project-tracking service
3. Me, I'm a service. (MIaS)

Cronjobs in the Hermes runtime trigger on a reasonable schedule, the agent picks
up a ticket based on priority and urgency ranking. Once it's done, a separate judge
agent reads its work and gives a verdict with a confidence score (a SWAG rn). Then I 
take a look and determine whether to approve, send it back, discard, etc.

## Experience

I create a bunch of tickets in Vikunja and in the morning a bunch of completed work
is sitting in the review queue for me.

## Capabilities

- [x] Reads `hermes:attempt` / `hermes:judge` / `hermes:control` / `hermes:session` machine comments from Vikunja
- [x] Diff review via `git-range` when an attempt carries git pointers
- [x] Dispositions written back to Vikunja: labels, comments, `not_before` snoozes
- [x] Activity and Metrics views over the pipeline: health, problems, claims, API-call feed, token-spend estimates
- [x] Per-ticket Discuss sessions through the loopback Hermes webui — the browser never talks to it directly
- [x] Restorable URL state: every view, filter, and pane is a shareable link
- [x] Token-gated write path (see Security)

## Security

The Vikunja API token never leaves the box. Writes require a per-start
`X-Hermes-Review-Token` (injected into the served HTML) and a `Host` header
matching the configured bind host. That is CSRF / DNS-rebinding protection,
not an ACL: a peer who can load the page can scrape the token. Bind to
loopback or a network you control — Corylus is not meant for the open
internet.

## Running

```bash
python3 hermes_review.py
```

Binds `localhost:8789`. Requires Python 3.11+ and
[`httpx`](https://pypi.org/project/httpx/). Corylus grew inside a
[Hermes Agent](https://github.com/NousResearch/hermes-agent) household; the
three sibling modules it talks to (`vikunja_config`,
`hermes_machine_comments`, `vikunja_preflight`) are vendored in this repo —
clone, install `httpx`, run.

| Env var | Default | Meaning |
|---|---|---|
| `HERMES_REVIEW_HOST` | `localhost` | Bind address; the `Host` header must match it for writes |
| `HERMES_REVIEW_PORT` | `8789` | Listen port |
| `HERMES_REVIEW_TAILNET` | RFC 6598 CGNAT /10 | Network whose peers get host-relative Vikunja UI links |
| `VIKUNJA_URL` | config, else `localhost:8788` | Vikunja API base |
| `HERMES_WEBUI_URL` | `http://127.0.0.1:8787` | Loopback webui base for Discuss sessions |

## View state

Every click is a link. View, selected task, list cursor, filters, open
sections, and time windows live in the query string via `history.pushState`
— reloads, pasted URLs, and back/forward all re-apply exactly, and unknown
parameters fall back to defaults.

```
?view=review&task=52        the review pane for task 52
?view=blocked&blocked=8     the blocked list, row 8 expanded
```

Full parameter reference: [`docs/url-state.md`](docs/url-state.md)

## Tests

```bash
node --test tests/test_url_state.js tests/test_disposition.js
python3 -m unittest tests/test_write_auth.py tests/test_serialize_judge.py \
  tests/test_judge_for_attempt.py tests/test_undo.py tests/test_monitor.py \
  tests/test_board_bucket.py
```

The Python lane needs `httpx` on the interpreter.

## The Name

It's the genus of hazel trees and it sounds pretty. It's a family thing.
