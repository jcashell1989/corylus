# Corylus runner: a harness-agnostic build and review loop

**Design proposal, revised for review.** Owner: Julian. Date: 2026-10-08 (US Pacific).
Written by an AI agent (Codex (GPT-6.1 Sol)), revising the original Claude Code draft.
Julian must approve this design before any build ticket starts. This document authorizes no implementation, deployment or merge.

## 0. The one-paragraph version

Corylus is the control layer for an automated agentic work pipeline: agents build, an independent agent judges, Julian decides. Its proposed headless runner takes a tracker ticket through build, verification, review and bounded remediation. It supports any harness in either role through configuration, maintains durable state, schedules work without an orchestrator staying online, and merges only an independently reviewed revision with the required human authorization. There are two roles, **worker** and **reviewer**, plus **job mode** for bounded runbook work. The engine and tests are public; installation settings stay private. The first Corylus lane runs one ticket at a time.

## 1. Background and inputs

This revision draws on these sources, summarized without installation identifiers:

- **Julian's decisions, 2026-10-08**, recorded in `td-a8a0af` and its revision brief: configurable harnesses in both roles; TOML; different sessions by default; the same model warns rather than refuses; two roles plus job mode; a serial Corylus lane.
- **Tracker approval constraint**, supplied in the same brief: the session that created or worked a ticket cannot approve it. The approval command must execute in the reviewer's eligible tracker session or an independent closer job. Naming the reviewer in a command issued by the orchestrator is insufficient.
- **Shell-loop operational report, 2026-10-07–08**, supplied in the revision brief: the incidents in §1.1. These are reported observations, not newly reproduced incidents.
- **Typesafe/Jev research summary**, supplied in the revision brief: a cheap structured-judgment API, best called from harness code with fixed packets rather than exposed as a model tool. This motivates an optional plug-in (§4.5), not a verified integration or quality claim. The specific research report was unavailable through Executor wiki search during this revision.
- **Corylus [README](../README.md)** and the companion *Ticket-Centered Work Sessions* design (v2.1, `docs/ticket-centered-sessions.md` on branch `docs/ticket-centered-sessions`): Ticket → Attempt → Session grouping, evidence and event-driven state. The companion is a proposal on a separate branch; its historical tracker references do not supersede td.

Today's shell loop renders a ticket guide, launches a worker in a worktree, checks finishing evidence, launches a fresh reviewer, then remediates a rejection or stops for a decision. A merge requires the reviewed SHA. Monitoring, queue filling, notifications and runbook jobs were added around that loop. The runner brings those responsibilities into tested interfaces.

### 1.1 Operational lessons and design implications

| Reported incident | Design implication |
|---|---|
| Editing a live script dropped its executable bit; launch failed silently and no start event appeared | Install immutable releases; preflight executability; persist launch intent, enforce a start deadline and emit `run.launch_failed` (§4.1, §5). |
| A verdict regex missed `NEEDS-DECISION` | Parse the complete final-line enum; malformed or conflicting verdicts cannot approve (§3.2). |
| Workers launched in the main checkout and edited it | Engine-owned worktrees; check actual launch cwd; prohibit main-checkout execution (§4.4). |
| A detached watcher never notified | Durable event subscriptions with delivery receipts and retries; attachment to a terminal is irrelevant (§6). |
| A monitor ignored deaths and hangs until rebuilt | Monitor process identity and progress on every tick; test death, idle and wall deadlines (§6, §9). |
| A queue runner with a slot cap was needed to keep work moving without the orchestrator | Persistent daemon, durable queue and lane caps; reclaim slots after terminal outcomes (§6). |
| Draft PRs blocked merges | Read draft state directly; only mark ready after authorization and review gates (§4.3). |
| Forge search lag temporarily hid new PRs | Prefer recorded PR IDs and exact head-branch lookup; bounded retries; an API error is not “no PR” (§4.3). |
| A service's config changed but its daemon never reloaded it (resolver incident) | For authorized service jobs, gate backup → change → reload → verify as the service user; restore and reload on failed verification (§4.5). |
| Reviews, waiver handling and deployment jobs required manual recovery | Explicit review, decision, resume and job commands; persist evidence before each action (§7). |
| Builder comparisons were anecdotal | Record per-attempt usage, duration and outcome; label missing cost data (§5.3). |

## 2. Goals, scope and non-functional requirements

Goals: configurable harnesses, independent review, headless operation, typed events, a public/private split and small build tickets. Preserve Corylus's chosen UI and ticket workflows; this proposal adds a runner backend, not a replacement interface.

Non-goals: replacing td, distributing execution across hosts, automatic deployment, or requiring persistent agent contexts. Job mode can execute an explicitly authorized runbook; it does not turn code acceptance into deployment authorization. Legacy Hermes/Vikunja pipeline code is not the runner's foundation.

### Non-functional requirements

- **Crash safety:** durably write the next state and action intent before acting. Record a receipt afterward. Failed persistence prevents the action.
- **Idempotent restart:** reconcile unfinished actions against process, tracker and forge state before resuming. Never blindly relaunch, re-approve, re-merge or repeat a live job.
- **Secret exclusion:** no secrets in events, logs, prompts retained by the runner or published text. Use allowlisted fields and scrub output before storage; reject unsafe output rather than persist it. Credentials stay in the harness/provider's private credential mechanism.
- **Bounded runs:** every worker, reviewer and job has positive wall-clock, idle and launch timeouts. Cancel the process group, wait a bounded grace period, then kill and record the outcome. Harness output activity alone does not prove useful progress.
- **Single ownership:** a daemon lock plus ticket leases prevent duplicate execution. Gate, tracker, forge and notification calls also have finite deadlines and retries.

## 3. Roles and contracts

### 3.1 Worker

Receives the live ticket, rendered rules/guide, prior findings and its worktree. Leaves committed, pushed work in an open PR, with verification evidence and a tracker review request. The engine verifies those facts independently. A finish nudge may resume the same session once; missing resume support means a fresh session with the persisted handoff.

### 3.2 Reviewer

Receives the ticket, exact PR head, verification evidence, prior findings and a separate review worktree. It never receives private worker reasoning. Its final message ends with exactly one of:

```text
VERDICT: APPROVE
VERDICT: REJECT
VERDICT: NEEDS-DECISION
```

Allow one terminal newline; match the whole last line. Duplicate/conflicting verdict lines, malformed findings, an unknown enum or unsuccessful harness exit produce a failed review run, never approval. An optional fenced `findings` JSON block contains bounded entries `{file, line, severity, summary}`; repository-relative paths only. Store the SHA and reviewer session with every verdict. A changed head invalidates it.

`REJECT` starts the next attempt within `max_rounds` (the total number of build/review attempts, default 2). `NEEDS-DECISION` pauses for Julian. Invalid output stops with a diagnostic; it does not spend an unbounded retry budget.

### 3.3 Independence, approval and waivers

Each run has **two identities**: an opaque harness session reference for resume, and a tracker session ID for authorization. For td, give each fresh run its own `TD_CONTEXT_ID`, run `td usage --new-session` at context creation, and verify the resulting session with `td current`. Persist the context-to-session mapping; resume reuses it without creating a new session. Supply that context only to the child and its tracker command executor; never switch the daemon's global session. An adapter must demonstrate isolated session propagation before supporting approval.

The reviewer must differ from every worker harness session and from all ticket creator/implementer tracker sessions. Unknown identity or eligibility fails closed. Profiles may use either role; the same normalized model in both roles emits `policy.warning` and stores `same_model: true`. It does not refuse review. There is no third loop role.

Normal acceptance:

1. Reviewer finishes with APPROVE for SHA S. Persist the evidence, session IDs and verdict; this alone does not close td or merge.
2. After the configured human acceptance gate (required by default), execute `td approve TICKET --reason REASON` **with the reviewer's persisted `TD_CONTEXT_ID`**, verifying `td current` still matches before acting. The reason references SHA S, review and acceptance evidence. Verify td's resulting status and reviewer-of-record; save a receipt. Never use the orchestrator's session, `--self-review`, or name-only `--reviewed-by` as a substitute.
3. Perform a separately authorized, SHA-guarded merge (§4.3). A tracker approval, a merged PR and deployment acceptance are distinct facts. If merge fails, report accepted work awaiting merge, not completion.

Waiver flow: the reviewer records findings and recommends a specific waiver, ending NEEDS-DECISION. Julian may accept or change it; an explicitly delegated “orchestrator waiver” counts only when the ticket records that authority. Persist the decision, scope, author and SHA. An **independent closer job**, using an eligible tracker session, rereads the live ticket, accepted waiver, review and exact head, then records approval in its own session with that evidence. It is job mode, not another role. A recommendation alone cannot close a ticket. A waiver does not bypass session eligibility, secret rules or SHA checks. Code changes require a new review.

Resume with a note does not itself approve or waive anything. Reviewers and closers must not create or implement the ticket they approve. td rejection is a policy stop, never a reason to retry under a fabricated identity. Where an installed td offers weaker trusted-mode shortcuts, the adapter still enforces this design's stricter boundary and validates supported commands at setup.

### 3.4 Job mode

One configured harness runs a bounded, approved task without the build/review loop. It records authorization, effects, verification, exit and `job.finished`. A closer is one job kind; service runbooks are another. Success of a harness process alone is not success of the runbook. Post-merge jobs are disabled unless both pipeline policy and recorded authorization permit them.

## 4. Interfaces

Proposed code lives under `runner/`; none exists as a result of this design. Shared dataclasses in `runner/contracts.py` define requests, results, sessions, effects and gate packets. Adapters receive dependencies explicitly and can be tested with fakes.

### 4.1 Harness

```python
class Harness(Protocol):
    def start(self, request: RunRequest) -> RunHandle: ...
    def resume(self, request: RunRequest, prior: SessionRef) -> RunHandle: ...
    def poll(self, handle: RunHandle) -> RunState: ...
    def result(self, handle: RunHandle) -> RunResult: ...
    def cancel(self, handle: RunHandle) -> None: ...
```

`RunRequest`: ticket, attempt, run/effect ID, mode (`worker`, `reviewer`, `job`), prompt, cwd, profile/model, tracker context, output destination and limits. `RunHandle`: PID plus process start identity, launch receipt and session references. `RunState`: starting/running/exited/timed_out with last activity/progress. `RunResult`: exit, sanitized final message, both session identities, optional usage and artifact references.

A generic CLI adapter takes argv templates, never shell strings; prompts use stdin or a file, not command-line arguments. Preflight executable, cwd, placeholders and output permissions. A launcher persists a claim/receipt keyed by effect ID before starting the child and supervises its process group. Only confirmed start creates `run.started`; failure creates `run.launch_failed`. On an uncertain launch after a crash, reconcile the receipt/process identity or stop for investigation rather than duplicate it.

Harness-specific parsing covers session IDs, final output and progress signals. Resume capability is explicit; fresh-start fallback uses ticket evidence. A Python plug-in can implement an API harness. Configuration examples express the adapter contract, not verified CLI flag compatibility.

### 4.2 Tracker

```python
class Tracker(Protocol):
    def get(self, ticket: str) -> Ticket: ...
    def context(self, run_id: str, prior: TrackerSession | None) -> TrackerSession: ...
    def log(self, ticket: str, message: str, actor: TrackerSession) -> Receipt: ...
    def submit(self, ticket: str, actor: TrackerSession) -> Receipt: ...
    def approve(self, request: ApprovalRequest, actor: TrackerSession) -> Receipt: ...
```

`Ticket` includes creator/implementer identities, review state and decisions. `ApprovalRequest` includes ticket, SHA, review reference, decision reference and effect ID. `approve` checks eligibility, executes in `actor`'s isolated context and reads back the recorded reviewer/status. On restart, inspect existing approval before repeating. Capability/schema errors stop. Tracker logs include stable effect IDs for reconciliation. Do not run `td export` or edit its scheduled export file.

### 4.3 Forge

`Forge.find_pr(repo, branch, recorded_id)`, `head(pr)`, `mark_ready(pr)` and `merge(pr, expected_sha)` return typed results or explicit errors. Lookup uses recorded ID, then exact repository/head branch, then bounded search retries. A draft stays draft until readiness is authorized. Immediately before merge, reread the head and required checks; the merge API must enforce `expected_sha` atomically. A pre-call comparison alone is insufficient. Unsupported SHA enforcement fails closed. Read back the merge receipt, including reviewed head and resulting merge SHA. Review and merge use only the expected PR; never pick a search result by title alone.

### 4.4 Workspace

`Workspace.ensure(ticket, repo, base, effect_id)` creates/reuses a dedicated feature branch and worktree; `Workspace.review(ticket, sha)` creates a separate checkout pinned to that SHA. Verify repository identity, branch and cwd before launch. Never switch the main checkout's branch or launch there. Preserve dirty work; uncertain ownership requires a decision. Review worktrees forbid source edits through adapter policy; any modification invalidates review. Cleanup is explicit, never an automatic destructive recovery step.

### 4.5 Gates and optional judgment

```python
class Gate(Protocol):
    name: str
    def check(self, context: GateContext) -> GateResult: ...
```

`GateContext`: stage, ticket/attempt, repo/worktree, expected SHA, evidence references and sanitized progress packet. `GateResult`: pass/fail/error/advisory, bounded findings and verification receipts. A required gate error blocks progress.

- **Finish:** clean worktree, commit equals upstream head, expected open PR and complete handoff. Check discovery errors fail closed.
- **Checks:** project-configured lint/tests for the changed scope, tied to that SHA. Record exact command, exit and bounded sanitized output. No applicable lint/test requires an explicit policy decision, never an invented pass. One finish nudge per attempt covers repairable finish/check failures; a second failure stops before review.
- **Service verification (jobs only):** require a backup receipt, authorized change/reload and checks under the actual service user after reload. Failure triggers restore plus reload and re-verification. Failed rollback stops and alerts. It is not part of every code ticket's finish gate.
- **Optional Typesafe/Jev:** off by default. Harness-side runner code calls a fixed structured API packet at a suspected stall/loop or before review. Packet: stage, elapsed time, progress counters, repeated-error hashes, gate summaries and bounded sanitized evidence; no credentials, private transcripts or arbitrary model-selected questions. Schema-validate a response such as `continue | flag_loop | flag_review_gap | needs_decision`, with reasons and confidence. Bound call duration, cost, retries and frequency. Record advisory evidence; it cannot approve, waive or replace deterministic checks or the reviewer. Default API failure records `unavailable` and retains normal gates/timeouts; an explicitly required policy blocks on failure. Flags pause for inspection rather than automatically repeating work. The provider schema remains to be verified when that optional ticket is built.

## 5. State, events and results

### 5.1 Durable state and recovery

Use one fsynced, append-only event journal as authority and an atomically replaced `state.json` snapshot as a read cache. Each journal record has schema version, sequence, event ID, time, ticket, attempt, run and lane, plus an allowlisted payload. Replay rebuilds a missing/stale snapshot; reject malformed records and recover only a provably incomplete trailing write. A failed journal write stops dispatch.

State includes phase, lane/repository, lease, all worker/reviewer identities, run handles/deadlines, attempts, gate receipts, PR/head, reviewed and merged SHAs, decisions, approval receipts and pending effects. Phases: queued → building → gating → reviewing → awaiting_acceptance → approving → awaiting_merge/merging → done; stopped, failed and needs_decision are explicit exits. Job state uses the same run/effect records.

Each external effect follows **intent → action → observed receipt**. After restart, reclaim the daemon lock, replay, validate child identity, and reconcile pending effects using their IDs. A lost merge response is checked through the forge; a lost approval response through td. A live child remains monitored without relaunch. Unknown processes or non-idempotent job effects pause for a decision. Exactly-once external execution is not assumed. Missing evidence never means success.

### 5.2 Events and notification delivery

Core events: `ticket.queued`, `attempt.started`, `effect.planned`, `effect.observed`, `run.start_requested`, `run.started`, `run.launch_failed`, `run.finished`, `run.died`, `run.stalled`, `run.timed_out`, `gate.passed`, `gate.failed`, `review.verdict`, `decision.recorded`, `tracker.approved`, `pr.merged`, `ticket.stopped`, `ticket.needs_decision`, `job.finished`, `runner.heartbeat`, `policy.warning` and `judgment.unavailable`.

Events contain evidence references and reason codes, not raw prompts/output or secret configuration. Render status from events; never parse status text back into state. Notifications use a durable consumer cursor and delivery ID: at-least-once delivery, deduplication where supported, bounded retries and visible terminal failure. An offline notification sink must not lose the ticket's decision state.

### 5.3 Results

Record duration, rounds, gate failures, review findings, outcome and optional token/cost usage per attempt/profile. Unknown cost is “unavailable,” not zero. Results and the future UI consume journal-derived records. A ticket owns attempts; attempts own disposable sessions and verification/review evidence. A worker note carries assumptions and next steps without becoming a second database.

## 6. Scheduler and monitor

A durable queue stores ticket, repository, pipeline, lane and validated overrides. Dependencies and human holds come from live tracker state. A leaf ticket has one lease; parents are planning containers, not worker jobs. Duplicate enqueue is idempotent.

Support global and **per-lane caps**, with lanes selected by repository or queue. For now, lane `corylus` has cap **1**: only one Corylus ticket workflow or standalone job is active. Its worker, reviewer and closer run sequentially within that slot; an internal closer does not enqueue behind itself. Waiting for a human releases the slot; resumed work reacquires it. Never release a slot while its child is alive. Additional lanes can run independently within the global cap. Optional profile caps further restrict admission. FIFO among eligible work, round-robin across lanes, avoids starvation.

The daemon fills free slots after exits even if the orchestrator disconnects. Each monitor tick checks process start identity, exits, launch deadlines, wall deadline and idle progress. The hard idle timeout is independent of an optional judgment detector. Stop by default on death/stall; a configured retry is limited to one safe, reconciled retry. A heartbeat does not excuse missing per-run checks. Stop/pause persists intent before cancellation; pause prevents new work, while stop cancels active work with a receipt. Notification delivery runs in the daemon, not a detached watcher.

## 7. Command line

```text
corylus-run config check | config show
corylus-run run TICKET [--pipeline P] [--worker PROFILE] [--reviewer PROFILE]
corylus-run review TICKET [--reviewer PROFILE]
corylus-run decision TICKET --file FILE
corylus-run resume TICKET --note-file FILE
corylus-run job TICKET --profile P --prompt-file FILE --authorization REF
corylus-run stop TICKET | pause TICKET
corylus-run queue add TICKET --lane L | queue list
corylus-run status [TICKET]
corylus-run results [--by profile|pipeline|lane]
corylus-run daemon
```

Foreground commands enqueue/drive the same engine; they cannot compete with a daemon's lease. Review-only discovers existing work and pins its head. Decision files record acceptance, merge authorization or a scoped waiver; missing authority is rejected. Resume notes are sanitized and preserved as evidence. No flags bypass independence, gates or effect reconciliation. Every published PR body/comment identifies its AI author; adapters enforce this for runner-authored text, and the finish gate checks worker publication evidence.

## 8. Configuration

### 8.1 Why TOML

| Format | Assessment |
|---|---|
| TOML | Standard-library `tomllib` on Python 3.11+, typed named tables, comments; recommended and accepted by Julian. |
| YAML | Familiar but adds a parser dependency and implicit-type pitfalls. |
| KDL | Readable but adds a dependency and less common tooling. |
| CUE / Pkl / Nickel | Strong validation but an extra toolchain for a small runner. |

Layer packaged defaults → private local config → validated CLI overrides. `config check` names invalid tables/keys, role mismatches, unknown placeholders, absent harnesses, invalid lane mappings and missing timeouts. `config show` explains value provenance using an allowlist; omits credential values and locations. Freeze an effective config digest per attempt; policy changes require explicit reconciliation at resume.

### 8.2 Illustrative valid TOML

```toml
[harness.generic]
command = ["example-agent", "run", "--model", "{model}"]
resume = ["example-agent", "resume", "{session_id}"]
prompt = "stdin"
session = { from = "output_json", field = "session_id" }
final = { from = "output_json", field = "final_message" }
billing = "metered"

[profile.builder]
harness = "generic"
model = "example-small-model"
roles = ["worker", "reviewer"]
max_wall_seconds = 3600
idle_timeout_seconds = 1200
launch_timeout_seconds = 30

[profile.reviewer]
harness = "generic"
model = "example-large-model"
roles = ["worker", "reviewer"]
max_wall_seconds = 5400
idle_timeout_seconds = 1200
launch_timeout_seconds = 30

[pipeline.default]
worker = "builder"
reviewer = "reviewer"
max_rounds = 2
gates = ["finish", "checks"]
independence = "session"
human_acceptance = true
merge = "manual"

[scheduler]
global_cap = 1

[lane.corylus]
cap = 1
repositories = ["corylus"]

[gate.judgment]
enabled = false
required = false
stages = ["suspected_stall", "pre_review"]
```

`roles` restricts the two loop roles; job-enabled profiles additionally require a separate `allow_jobs` policy. Real harness argv/session formats need adapter conformance tests. Models in examples are placeholders. Installation policy may forbid a harness/billing combination; it never silently substitutes a different harness.

### 8.3 Public versus private

Public: engine, interfaces, generic templates, synthetic examples and stub tests. Private: repository bindings, workspace locations, real models/harness flags, rules, service runbooks and provider configuration. Reference credentials through the existing private harness/provider mechanism; do not copy them into runner config or serialize environment values. Restrict state/artifact permissions to the runner user. Never publish installation hosts, addresses, paths or credential locations from private inputs.

## 9. Testing and release

Use a scriptable fake CLI and temporary Git/td projects, plus fake forge, clock, judgment and notification services. No production credentials or live service changes in tests. Required scenarios:

- APPROVE, REJECT then APPROVE, NEEDS-DECISION, malformed/duplicate verdicts and invalid findings.
- Finish nudge success, second failure, failed lint/test discovery and stale-SHA evidence.
- Missing executable, lost launch receipt, death, hang, idle/wall deadlines and child cleanup.
- Crash before/after every effect; snapshot replay; duplicate queue/resume; no duplicate launch, approval or merge.
- Creator/worker approval refusal, actual reviewer-context approval, same-model warning, accepted waiver → independent closer, and unauthorized waiver refusal.
- Lane cap 1, other lanes, slot recovery, held tickets and internal closer without deadlock.
- Draft handling, delayed PR discovery, forge errors, atomic SHA guard and lost merge response.
- Notification outage/retry, sanitization before persistence, judgment unavailable/malformed output and unchanged deterministic gates.
- Authorized service job: backup, reload, service-user verification and rollback on failure.

Run targeted Python unit tests and Ruff; end-to-end fakes run in CI. Install from a reviewed known commit/tag, preserving executable permissions. No edits to a running release. Restart/readiness probes must show a start event and working monitor/notification consumer, not just a live PID.

## 10. Migration from the shell loop

After Julian accepts the design, create the §11 tickets. Build alongside the existing loop, without changing it through this ticket. First compare captured evidence offline. Then run the new runner on selected low-risk tickets in its own lane: **one executor owns a ticket**, never two live loops acting on it. Verify restart and timeout drills before enabling unattended scheduling. Keep the old loop recoverable until acceptance. Integrate journal-derived records into the existing ticket UI in a separately reviewed change; do not replace the interface or depend on legacy tracker code.

## 11. Ordered build plan

These are proposed slices, not created or started tickets. Names and files form a suggested contract; each slice delivers a testable unit using fakes before its consumers exist. Tests live in `tests/runner/`. “Cheap” means a bounded cheap-builder task; “Codex” marks lifecycle or safety complexity. Each step lists explicit predecessor numbers. Package scaffolding belongs to step 1; later steps add one or two production files plus tests where practical.

| # / ticket | Files and interface delivered | Acceptance tests | Size / dependencies |
|---|---|---|---|
| 1. Shared contracts | `runner/__init__.py`, `runner/contracts.py`: requests/results, identities, effect/receipt, gate/event/state types | Reject invalid enum, identity and timeout fields; serialization round-trip | Cheap; none |
| 2. Configuration | `runner/config.py`, `runner/example.toml`: load/layer/validate/redacted show | Parse example; precedence, unknown keys, roles, caps and missing limits | Cheap; 1 |
| 3. Durable journal | `runner/store.py`: append/replay/snapshot, intent/receipt IDs and lock | Crash boundaries, fsync failure, partial tail, replay, lock contention | Codex; 1 |
| 4. Stub harness | `tests/runner/stub_cli.py`: programmable output/session/exit/progress behavior | Subprocess emits success, crash, hang and invalid verdict fixtures | Cheap; 1 |
| 5. Workspace | `runner/workspace.py`: ensure/review worktrees | Temporary repo; idempotent ensure, main-cwd refusal, dirty preservation, pinned head | Cheap; 1 |
| 6. Durable launcher | `runner/launcher.py`: claim/spawn/receipt/process-group control | Missing executable, start deadline, uncertain spawn, identity mismatch, cancellation | Codex; 1, 3, 4 |
| 7. CLI harness | `runner/harness.py`: Harness implementation and scrub-before-store output boundary | stdin prompt, argv placeholders, session/final parsing, resume/fresh fallback, limits, secret-output refusal | Codex; 2, 4, 6 |
| 8. Verdict parser | `runner/verdict.py`: final-line enum and findings | Hyphenated verdict, duplicates, invalid JSON, unsafe paths, failed exit | Cheap; 1 |
| 9. Tracker read/session | `runner/tracker.py`: get/context/log/submit | Isolated tracker contexts, live identity discovery, malformed capability/schema, effect-tagged logs | Codex; 1 |
| 10. Tracker approval | Extend `runner/tracker.py`: eligibility and approval/readback | Real temporary td project: worker/creator refusal, reviewer succeeds, refusal stops; lost response reconciliation | Codex; 3, 9 |
| 11. Forge | `runner/forge.py`: lookup/head/ready/atomic merge | Exact branch, search lag, draft, API errors, moved head, lost response | Cheap; 1 |
| 12. Finish/check gates | `runner/gates.py`: Gate plus finish/check implementations | Clean/upstream/PR checks, discovery fails closed, commands and receipts tied to SHA | Cheap; 1, 5, 11 |
| 13. Review policy | `runner/policy.py`: identities/model warning, acceptance/waiver validation | Unknown identity refusal, same-model warning, unauthorized/stale waiver, reviewer versus closer eligibility | Cheap; 1, 8, 9 |
| 14. Single-ticket engine | `runner/engine.py`: pure transitions emitting effect requests | Build/gate/review/remediation, one nudge, round bound, holds and no success on missing receipt | Codex; 1, 8, 13 |
| 15. Effect driver/recovery | `runner/driver.py`: execute/reconcile engine effects | Stub full workflow; crashes around launch/approval/merge; no duplicate effects | Codex; 3, 5, 7, 10–14 |
| 16. Monitor | `runner/monitor.py`: tick/deadline/cancel decisions | Fake clock death, PID reuse, log-only activity, idle/wall/launch deadlines | Codex; 3, 6, 7 |
| 17. Queue/lanes | `runner/scheduler.py`: durable enqueue/admission/leases | Corylus cap 1, global/profile caps, FIFO/fairness, dependency holds, slot recovery | Cheap; 2, 3 |
| 18. Daemon | `runner/daemon.py`: ownership, scheduling, driver/monitor ticks and injectable job executor | Orchestrator disconnect, restart, simultaneous commands, human hold release, closer slot reuse with fake job | Codex; 15–17 |
| 19. Jobs/closer | `runner/jobs.py`: authorized bounded jobs and independent closer | Waiver recommendation + accepted decision + independent approval; missing authority; uncertain live effect pauses | Codex; 7, 10, 13, 15, 18 |
| 20. CLI | `runner/cli.py`: §7 commands | Argument validation, sanitized config/status, lease-safe enqueue, review-only, decisions and jobs | Cheap; 2, 3, 18, 19 |
| 21. Notifications/results | `runner/notify.py`, `runner/results.py`: cursor delivery and reports | Outage/retry/dedup, visible delivery failure, unavailable cost, deterministic replay reports | Cheap; 3, 18 |
| 22. Service-job gate | `runner/service_gate.py`: runbook effect receipts and service-user probe | Fake backup/change/reload/verify; failed verification restores/reloads; failed rollback alerts | Codex; 12, 19 |
| 23. Optional judgment | `runner/judgment.py`: fixed packets behind Gate, disabled by default | Sanitization, bounded call, bad schema, unavailable, flag pauses, never grants approval | Cheap; 2, 12, 16 |
| 24. Release/regression suite | `tests/runner/test_e2e.py`, `.github/workflows/runner.yml`; release notes in `docs/runner-release.md` | §9 matrix, targeted/unit CI and Ruff; installed executable/start/restart smoke checks | Codex; 1–23 |

Step 24 has three files because CI and the release runbook accompany the integration suite; it implements no new runtime behavior. UI consumption is a later design/build slice, preserving existing workflows. Approval of this proposal is not approval to start all tickets unattended.

## 12. Open questions with recommended defaults

| Question | Recommended default for Julian to accept or change |
|---|---|
| Where does the daemon run, and should it start at boot? | One designated local runner account/machine, supervised and enabled at boot **after** restart drills pass. Installation binding stays private; initially run manually. |
| Does job mode need an explicit human approval token per run, or is config allowance enough? | Require a durable per-run authorization reference scoped to ticket, job kind and allowed effects. Config enables capability; it does not grant authority. A closer needs accepted review/waiver evidence. |
| Per-ticket spend caps: gateway, runner or both? | Both where supported: provider enforces the hard budget, runner stops on reported usage and always enforces timeouts. Missing metering is visible; refuse a strict monetary cap that cannot actually be enforced. |
| How should the ticket page show same-model warnings and policy refusals? | Warning alongside review evidence, without blocking acceptance. Refusal/NEEDS-DECISION in the ticket's attention area with reason and next action; detailed evidence folded into the attempt timeline. Preserve the current interface. |
| When may the runner merge after review? | `merge = "manual"` initially. Later enable runner merge only with a recorded human authorization for the exact reviewed head and atomic forge enforcement. |
| Should Typesafe/Jev flags stop work automatically? | Off initially; when enabled, advisory flags pause for inspection. Benchmark false positives before enabling stronger policy. Unavailable optional judgment never disables deterministic safety checks. |
