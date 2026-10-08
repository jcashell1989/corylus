# Corylus runner: a harness-agnostic build and review loop

**Design document.** Status: draft for review, not an implementation approval. Owner: Julian.
Date: 2026-10-08 (US Pacific). Written by an AI agent (Claude Code, acting as Julian's orchestrator).
Companion: `docs/ticket-centered-sessions.md` (v2.1, on branch `docs/ticket-centered-sessions`), whose Ticket → Attempt → Session model and event-driven state this document adopts.

---

## 0. The one-paragraph version

Corylus's README describes it as the control layer for an automated agentic work pipeline: agents build, an independent agent judges, Julian decides. The part that actually *runs* that pipeline has lived outside Corylus as a set of shell scripts (internally "loop5") that an orchestrating agent edits in place. It works, but in one week it produced a string of operational bugs that tests would have caught. This document proposes a **runner** module inside Corylus: a headless engine that takes a ticket, runs a worker and then an independent reviewer through any agent harness chosen by configuration, enforces finishing gates, merges only the reviewed revision, and records everything as typed events that the Corylus UI can show. The engine is public and generic; anything specific to one installation (hosts, paths, credentials, house rules) lives in private local config.

## 1. Background: what loop5 does today

For each ticket (from the `td` tracker):

1. **Build.** A worker harness (OMP on a cheap model, or Codex) gets a prompt built from shared rules, a role template and a per-ticket guide. It works in its own git worktree, commits, pushes and opens a PR.
2. **Finish gate.** The engine checks that the work is committed, pushed and has a PR, and that lint and tests pass for the changed files. If not, it resumes the worker once with a short "finish" prompt; if the gate still fails, it stops without spending a review.
3. **Review.** A fresh reviewer session (Codex) reads the ticket and the PR, reproduces where it can, and ends with exactly one `VERDICT:` line.
4. **Remediate.** On REJECT, the worker session is resumed with the findings, up to a round limit. On NEEDS-DECISION the loop stops for a human.
5. **Merge.** On APPROVE, the engine merges the PR only if its head is still the SHA that was reviewed.

Around that: a status log, a monitor for deaths and stalls, one-off runbook jobs (deploys) started by hand, and an orchestrator choosing which tickets fill a fixed number of slots.

### 1.1 What went wrong (2026-10-07 to 10-08), and what each implies

| Incident | Root cause | Design implication |
|---|---|---|
| Workers edited the admin checkout instead of their worktree | Harness launched with the repo root as its working directory | The engine owns workspace creation and always launches workers inside it (§4.4) |
| `VERDICT: NEEDS-DECISION` read as "NEEDS" | Verdict parsed with a regex over free text | Strict, tested verdict contract (§3.2) |
| A loop script lost its executable bit and failed silently | Live scripts edited with `sed` and `mv` | No live editing: installed releases only, tests in CI (§9) |
| Watcher missed deaths, hangs and some failure lines | State inferred by grepping a log | Typed state and events; monitor built in (§5, §6) |
| A new PR was "missing" for ~15 s | Forge search index lag | Forge adapter owns lookup and retry semantics (§4.3) |
| Reviews, resumes after waivers, and deploys run by hand | The loop covered only the happy path | First-class commands for review-only, resume-with-note and jobs (§7) |
| Flash vs DeepSeek comparison was anecdotal | No per-ticket results | Usage and outcome recorded per attempt (§5.3) |

## 2. Goals and non-goals

**Goals**
- Any harness can fill the **worker** or **reviewer** role, chosen by configuration, not code.
- Headless and testable: the runner works and is tested with no UI running.
- Independent review is enforced, not hoped for.
- Every state change is a typed event; the UI and notifications only read events.
- A clean public/private split.
- Small enough that cheap builders can implement most of it in single-file tickets.

**Non-goals (for now)**
- Replacing the tracker. `td` stays the tracker of record; the runner talks to it through an adapter.
- Deploying. Deploys stay out of the loop; one-off **jobs** (§3.4) cover runbook execution with the same monitoring.
- Persistent agent sessions as an architectural dependency (per the companion doc §5.8, resume is an optimization).
- Multi-host distribution. One runner process on one machine.

## 3. Roles and contracts

There are exactly two loop roles, plus a job mode.

### 3.1 Worker
Input: the rendered prompt and a worktree. Contract: leave the work **committed, pushed and in an open PR**, and request review on the tracker. The engine does not trust the worker's final message for any of this; the finish gate checks it.

### 3.2 Reviewer
Input: the rendered prompt, the PR, prior findings, and its own review worktree at the PR head. Contract: the **last line of the final message** is exactly one of `VERDICT: APPROVE`, `VERDICT: REJECT`, `VERDICT: NEEDS-DECISION`. Anything else is treated as a failed review run (not as REJECT). An optional fenced `findings` JSON block (file, line, severity, summary) is parsed when present and stored with the verdict.

### 3.3 Independence
Configurable per pipeline: `session` (default), `model` or `harness`.
- `session`: the reviewer must be a different session from every worker session on the ticket. Always enforced.
- If the reviewer uses the **same model** as the worker, the run proceeds but the engine emits a warning event and stores `same_model: true` on the verdict.
- `model` / `harness` make that condition a hard refusal instead.

### 3.4 Job mode
`corylus-run job TICKET --profile P --prompt-file F` runs one harness session with no review: the same adapter, limits, events and death/stall detection, ending in a `job.finished` event with the exit status and final message. Use it for runbook tasks (deploys, migrations) that a human has approved. A post-merge hook may start a job only if config explicitly allows it for that pipeline.

## 4. Interfaces

### 4.1 Harness adapter

```python
class Harness(Protocol):
    name: str
    def start(self, req: RunRequest) -> RunHandle: ...
    def resume(self, req: RunRequest, prior: SessionRef) -> RunHandle: ...
    def poll(self, h: RunHandle) -> RunState: ...      # running | exited(code) | timed_out
    def result(self, h: RunHandle) -> RunResult: ...
    def cancel(self, h: RunHandle) -> None: ...

@dataclass(frozen=True)
class RunRequest:
    ticket: str
    role: Literal["worker", "reviewer", "job"]
    attempt: int
    prompt: str               # fully rendered
    cwd: Path                 # worker: its worktree; reviewer: its review worktree
    model: str
    params: Mapping[str, str] # harness-specific, e.g. thinking level
    limits: Limits            # wall time, idle timeout, spend tag
    artifacts: Path           # logs, session data, final message

@dataclass(frozen=True)
class RunResult:
    exit_code: int
    final_message: str
    session: SessionRef | None   # opaque; used for resume
    usage: Usage | None          # tokens/cost when the harness reports them
    log: Path
```

Most harnesses need **no code**: a generic CLI adapter is driven by declarative config (§8.2). A Python plugin entry point covers harnesses that need an API instead of a CLI.

The adapter, not the engine, knows how to: pass the prompt (argument, stdin or file), find the session id (session directory, log regex or file), read the final message (stdout or an output file), resume, scrub environment variables, close stdin, and enforce the wall-clock and idle limits. Every harness gets a hard wall-clock limit; idle detection uses log and artifact activity.

### 4.2 Tracker

```python
class Tracker(Protocol):        # td first
    def get(self, ticket: str) -> Ticket: ...
    def log(self, ticket: str, message: str) -> None: ...
    def submit_for_review(self, ticket: str) -> None: ...
    def approve(self, ticket: str, reviewed_by: str, reason: str) -> None: ...
```

The engine records the approval after a valid APPROVE, attributing it to the reviewer session (`reviewed_by`), so no separate "closer" role is needed.

### 4.3 Forge

```python
class Forge(Protocol):          # GitHub first
    def find_pr(self, ticket: str, branch: str) -> PR | None: ...   # by head branch, search as fallback
    def head(self, pr: PR) -> str: ...
    def mark_ready(self, pr: PR) -> None: ...
    def merge(self, pr: PR, expected_sha: str) -> MergeResult: ...  # refuses if head != expected_sha
```

The adapter owns forge quirks: search-index lag (look up by head branch first, retry search), draft PRs (mark ready before merge), and API deprecations.

### 4.4 Workspace

```python
class Workspace(Protocol):
    def ensure_worktree(self, ticket: str, base: str) -> Worktree: ...  # creates branch + worktree if missing
    def review_worktree(self, ticket: str, sha: str) -> Worktree: ...   # detached, read-only by convention
```

Worktrees live under a configured private parent directory. Workers are launched *inside* their worktree, never in the main checkout.

### 4.5 Gates

```python
class Gate(Protocol):
    name: str
    def check(self, ctx: GateContext) -> list[Failure]: ...
```

Built in: `finish` (committed, pushed, PR open, nothing unpushed) and `checks` (lint and tests chosen from the changed files, fail-closed on discovery errors). Pipelines list their gates. A failed gate triggers one resumed "finish" run; a second failure stops the ticket before review.

## 5. State, events and results

### 5.1 Per-ticket state (`state.json`, written atomically)

```text
ticket, pipeline, phase (queued | building | gating | reviewing | merging | done | stopped | needs_decision | failed)
attempts[]: n, worker {profile, session, pid, started, ended, exit}, gate results,
            review {profile, session, verdict, same_model, findings_ref}, usage
pr {number, branch}, reviewed_sha, merged_sha
```

State answers "what is running and where": the engine never infers it from logs.

### 5.2 Events (`events.jsonl`, append-only)

`ticket.queued`, `attempt.started`, `run.started`, `run.finished`, `gate.failed`, `gate.passed`, `review.verdict`, `pr.merged`, `ticket.stopped`, `ticket.needs_decision`, `run.died`, `run.stalled`, `job.finished`, `runner.heartbeat`, `policy.warning`.

Each event: timestamp, ticket, attempt, run id, type, small payload. The human-readable status line is rendered *from* events and is never parsed. Notification hooks (for example Telegram) subscribe by event type.

### 5.3 Results

Each attempt records: rounds used, wall time per run, gate failures, verdict and findings count, and usage (tokens and cost) from the harness or from a gateway spend tag. `corylus-run results --by profile` answers "which builder works best for which kind of ticket" from data.

These map directly onto the companion doc: ticket → attempts → sessions, with reviews and verification as evidence (§5.9 there). The Corylus ticket page reads the same state and events.

## 6. Scheduler and monitor

- A **queue** of tickets with a pipeline and optional per-ticket overrides.
- A **concurrency cap** (global, and optionally per profile). When a slot frees, the next queued ticket starts.
- The **monitor** runs inside the runner: on every tick it checks that each running run's process is alive (`run.died` otherwise), that its artifacts are changing (`run.stalled` after the idle limit), and emits a `runner.heartbeat`. Deaths and stalls follow a configured policy: stop, or retry once.
- A **launch check**: a run that does not reach `run.started` within a deadline is a failure event, never silence.

## 7. Command line

```text
corylus-run run TICKET [--pipeline P] [--worker PROFILE] [--reviewer PROFILE] [--max-rounds N]
corylus-run review TICKET [--reviewer PROFILE]        # review-only: work done elsewhere
corylus-run resume TICKET --note "waiver: …"          # resume the worker session with a message
corylus-run job TICKET --profile P --prompt-file F    # one-off, no review
corylus-run stop TICKET | pause TICKET
corylus-run queue add TICKET… | queue list
corylus-run status [TICKET]                            # rendered from state/events
corylus-run results [--by profile|pipeline]
corylus-run daemon                                     # scheduler + monitor
corylus-run config check | config show
```

## 8. Configuration

### 8.1 Format: TOML
TOML is read by the Python standard library (`tomllib`), which fits Corylus's minimal-dependency stance; our config is flat, named tables, where TOML is at its best; and it has comments and explicit types. YAML (a dependency, plus implicit type coercion), KDL (a dependency, little tooling) and CUE/Pkl/Nickel (an extra toolchain) were considered and rejected. Ergonomics come from tooling rather than syntax:

- **Layering:** packaged defaults, then the private local file, then CLI flags.
- **`config check`:** schema validation with errors that name the table and key (unknown placeholder, role not allowed for profile, missing harness).
- **`config show`:** the effective merged config, annotated with where each value came from.

### 8.2 Shape

```toml
[harness.omp]
command   = ["omp", "-p", "--auto-approve", "--model", "{model}", "--thinking", "{thinking}",
             "--cwd", "{cwd}", "--session-dir", "{session_dir}", "{prompt}"]
resume    = ["omp", "-p", "--auto-approve", "--model", "{model}", "--cwd", "{cwd}",
             "--session-dir", "{session_dir}", "-c", "{prompt}"]
session   = { from = "session_dir" }        # session_dir | log_regex | file
final     = "stdout"                         # stdout | file:{out}
env_unset = ["CLAUDECODE"]
billing   = "metered"                        # metered | subscription

[harness.codex]
command = ["codex", "exec", "-m", "{model}", "-C", "{cwd}", "-o", "{out}", "{prompt}"]
resume  = ["codex", "exec", "resume", "{session_id}", "-m", "{model}", "-o", "{out}", "{prompt}"]
session = { log_regex = "session id: ([0-9a-f-]+)" }
final   = "file:{out}"
billing = "subscription"

[profile.cheap-worker]
harness = "omp"; model = "provider/some-flash-model"; thinking = "medium"
roles = ["worker"]; max_wall = "60m"; idle_timeout = "20m"

[profile.strong-reviewer]
harness = "codex"; model = "some-large-model"; roles = ["worker", "reviewer"]; max_wall = "90m"

[pipeline.default]
worker = "cheap-worker"; reviewer = "strong-reviewer"
max_rounds = 2; gates = ["finish", "checks"]; independence = "session"

[policy]
forbid = [{ harness = "claude", billing = "metered" }]   # example of an installation rule
```

### 8.3 Public versus private
- **Public (this repo):** the engine, adapters, generic role templates, an example config, and tests with stub harnesses.
- **Private (local file, outside any repo):** real profiles and models, harness flags that encode local policy, worktree parent, forge/tracker settings, credentials by file path, and the installation's house rules, which are appended to role prompts.

## 9. Testing and release

- **Stub harness:** a scriptable fake CLI (exit code, final message, session id, delay, hang, crash, edits to the worktree). It drives the whole loop in CI: happy path, REJECT then APPROVE, NEEDS-DECISION, malformed verdict, gate failure then nudge, gate failure twice, death, stall, launch failure, head moved before merge, draft PR, search lag.
- **No live editing.** The runner is installed from a tagged release or main at a known commit. Local changes go through a PR, review and CI like any other ticket.

## 10. Migration from loop5

1. Build the runner in small tickets (§11) while loop5 keeps running, frozen except for urgent fixes.
2. Run both on a few low-risk tickets; compare events and outcomes.
3. Switch the orchestrator to `corylus-run`; retire loop5. Its lessons (§1.1) become regression tests.
4. The Corylus UI's ticket page then reads runner state and events.

Also: isolate or retire Corylus's legacy Hermes/Vikunja pipeline code so the runner does not build on it.

## 11. Implementation tickets (sized for cheap builders where marked)

1. Config schema, layering, `config check` / `config show` (small)
2. State file and event log library, atomic writes, rendering a status line (small)
3. Stub harness CLI for tests (small)
4. Generic CLI harness adapter: start, resume, session id, final message, limits (medium)
5. Verdict and findings parser (small)
6. td tracker adapter (small)
7. GitHub forge adapter with head-branch lookup, draft handling, SHA-guarded merge (small)
8. Workspace adapter (small)
9. Gates: port `finish` and `checks` from the homelab versions (small)
10. Engine: one ticket through build → gate → review → remediate → merge, on stub harnesses (Codex)
11. Scheduler, monitor and daemon (Codex)
12. CLI (small, after 10)
13. Results and per-profile report (small)
14. End-to-end CI scenarios (§9) (medium)

## 12. Open questions

1. Where does the daemon run, and should it start at boot?
2. Should job mode require an explicit human approval token per run, or is config allowance enough?
3. Per-ticket spend caps: enforce through the gateway (spend tags and key budgets), in the runner, or both?
4. How should the ticket page show `same_model` warnings and policy refusals?
