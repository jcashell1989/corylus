# Corylus runner: a harness-agnostic build and review loop

**Design proposal, revised for review.** Owner: Julian. Date: 2026-10-08 (US Pacific).
Written by an AI agent (Codex (GPT-6.1 Sol)), revising the original Claude Code draft.
Julian must approve this design before any build ticket starts. This document authorizes no implementation, deployment or merge.

## 0. The one-paragraph version

Corylus is the control layer for an automated agentic work pipeline: agents build, an independent agent judges, Julian decides. Its proposed headless runner takes a tracker ticket through build, verification, review and bounded remediation. It supports any harness in either role through configuration, maintains durable state, drains a ticket or queue without an orchestrator staying online, and exits when that invocation finishes. Automatic merge after independent approval is the default, guarded by the exact reviewed SHA; pipelines such as design review can require human acceptance and manual merge. There are two roles, **worker** and **reviewer**, plus **job mode** for bounded runbook work. The engine and tests are public; installation settings stay private. The first Corylus lane runs one ticket at a time.

## 1. Background and inputs

This revision draws on these sources, summarized without installation identifiers:

- **Julian's decisions, 2026-10-08**, recorded in `td-a8a0af` and its revision brief: configurable harnesses in both roles; TOML; different sessions by default; the same model warns rather than refuses; two roles plus job mode; a serial Corylus lane. The later decisions recorded on the same ticket require an ephemeral runner, automatic merge by default, no initial spend caps, and further exploration of job authorization (§12).
- **Tracker approval constraint**, supplied in the same brief: the session that created or worked a ticket cannot approve it. The approval command must execute in the reviewer's eligible tracker session or an independent closer job. Naming the reviewer in a command issued by the orchestrator is insufficient.
- **Shell-loop operational report, 2026-10-07–08**, supplied in the revision brief: the incidents in §1.1. These are reported observations, not newly reproduced incidents.
- **Typesafe/Jev research summary**, supplied in the revision brief: a cheap structured-judgment API, best called from harness code with fixed packets rather than exposed as a model tool. This motivates an optional plug-in (§4.5), not a verified integration or quality claim. The previous revision reported the detailed source unavailable; this design uses the supplied summary.
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
| A queue runner with a slot cap was needed to keep work moving without the orchestrator | An ephemeral drain invocation owns queue filling and monitoring; durable queue and lane caps allow a later invocation to resume (§6). |
| Draft PRs blocked merges | Read draft state directly; only mark ready after authorization and review gates (§4.3). |
| Forge search lag temporarily hid new PRs | Prefer recorded PR IDs and exact head-branch lookup; bounded retries; an API error is not “no PR” (§4.3). |
| A service's config changed but its daemon never reloaded it (resolver incident) | For authorized service jobs, gate backup → change → reload → verify as the service user; restore and reload on failed verification (§4.5). |
| Reviews, waiver handling and deployment jobs required manual recovery | Explicit review, decision, resume and job commands; persist evidence before each action (§7). |
| A manual/no-merge lane finished at review approval but was reported as dead | Persist `finished_awaiting_human` as an invocation-terminal outcome; no merge event is expected (§5–6). |
| Builder comparisons were anecdotal | Record per-attempt usage, duration and outcome; label missing cost data (§5.3). |

## 2. Goals, scope and non-functional requirements

Goals: configurable harnesses, independent review, headless operation, typed events, a public/private split and small build tickets. Preserve Corylus's chosen UI and ticket workflows; this proposal adds a runner backend, not a replacement interface.

Non-goals: replacing td, distributing execution across hosts, automatic deployment, or requiring persistent agent contexts. Job mode can execute an explicitly authorized runbook; it does not turn code acceptance into deployment authorization. Legacy Hermes/Vikunja pipeline code is not the runner's foundation.

### Non-functional requirements

- **Crash safety:** durably write the next state and action intent before acting. Record a receipt afterward. Failed persistence prevents the action.
- **Idempotent restart:** reconcile unfinished actions against process, tracker and forge state before resuming. Never blindly relaunch, re-approve, re-merge or repeat a live job.
- **Secret exclusion:** no secrets in events, logs, prompts retained by the runner or published text. Use allowlisted fields and scrub output before storage; reject unsafe output rather than persist it. Credentials stay in the harness/provider's private credential mechanism.
- **Bounded runs:** every worker, reviewer and job has positive wall-clock, idle and launch timeouts. Cancel the process group, wait a bounded grace period, then kill and record the outcome. Harness output activity alone does not prove useful progress.
- **Single ownership:** an invocation ownership lock plus ticket leases prevent duplicate execution. Gate, tracker, forge and notification calls also have finite deadlines and retries.

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

Each run has **two identities**: an opaque harness session reference for resume, and a tracker session ID for authorization. For td, give each fresh run its own `TD_CONTEXT_ID`, run `td usage --new-session` at context creation, and verify the resulting session with `td current`. Persist the context-to-session mapping; resume reuses it without creating a new session. Supply that context only to the child and its tracker command executor; never switch the runner invocation's own session. An adapter must demonstrate isolated session propagation before supporting approval.

The reviewer must differ from every worker harness session and from all ticket creator/implementer tracker sessions. Unknown identity or eligibility fails closed. Profiles may use either role; the same normalized model in both roles emits `policy.warning` and stores `same_model: true`. It does not refuse review. There is no third loop role.

Normal acceptance:

1. Reviewer finishes with APPROVE for SHA S. Persist the evidence, session IDs and verdict; this alone does not close td or merge.
2. With a valid independent verdict, execute `td approve TICKET --reason REASON` **with the reviewer's persisted `TD_CONTEXT_ID`**, verifying `td current` still matches before acting. The reason references SHA S and review evidence. Human acceptance is required only by pipeline policy (for example design review); when required, record it before this command. Verify td's resulting status and reviewer-of-record; save a receipt. Never use the orchestrator's session, `--self-review`, or name-only `--reviewed-by` as a substitute.
3. In the default automatic pipeline, independent approval authorizes the SHA-guarded merge (§4.3). A manual pipeline ends this invocation at `finished_awaiting_human` with no merge event; a later explicitly authorized resume can merge. A tracker approval, a merged PR and deployment acceptance are distinct facts. If merge fails, report accepted work awaiting merge, not completion.

Waiver flow: the reviewer records findings and recommends a specific waiver, ending NEEDS-DECISION. Julian may accept or change it; an explicitly delegated “orchestrator waiver” counts only when the ticket records that authority. Persist the decision, scope, author and SHA. An **independent closer job**, using an eligible tracker session, rereads the live ticket, accepted waiver, review and exact head, then records approval in its own session with that evidence. It is job mode, not another role. A recommendation alone cannot close a ticket. A waiver does not bypass session eligibility, secret rules or SHA checks. Code changes require a new review.

Resume with a note does not itself approve or waive anything. Reviewers and closers must not create or implement the ticket they approve. td rejection is a policy stop, never a reason to retry under a fabricated identity. Where an installed td offers weaker trusted-mode shortcuts, the adapter still enforces this design's stricter boundary and validates supported commands at setup.

### 3.4 Job mode

One configured harness runs a bounded task without the build/review loop. It records the applicable authorization policy/evidence, effects, verification, exit and `job.finished`. Config allowance, a ticket-scoped note and a per-run token are alternatives still under discussion (§12); no per-run token is required by default. This unresolved choice does not weaken closer eligibility or the authorization required for service changes. A closer is one job kind; service runbooks are another. Success of a harness process alone is not success of the runbook. Post-merge jobs are disabled unless both pipeline policy and recorded authorization permit them.

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

`RunRequest`: ticket, attempt, run/effect ID, mode (`worker`, `reviewer`, `job`), prompt, cwd, profile/model, tracker context, output destination and limits. `RunHandle`: supervisor/child PIDs plus process start identities, launch receipt and session references. `RunState`: starting/running/exited/timed_out with last activity/progress. `RunResult`: exit, sanitized final message, both session identities, optional usage and artifact references.

The CLI adapter uses argv templates, never shell strings; prompts use stdin or a file. Preflight executable, cwd, placeholders and output permissions. Persist a claim before launch and a receipt afterward, keyed by effect ID. Confirmed start emits `run.started`; failure emits `run.launch_failed`. Reconcile an uncertain launch or pause, never duplicate it.

A per-run supervisor survives runner death, enforces wall/idle deadlines, stores sanitized progress/exit receipts and kills the child group at its limits. It exits with the run and cannot dispatch, approve or merge. The next invocation polls its durable handle; parent-only process waiting cannot adopt an orphan.

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

`Forge.find_pr(repo, branch, recorded_id)`, `head(pr)`, `mark_ready(pr)` and `merge(pr, expected_sha)` return typed results or explicit errors. Lookup uses recorded ID, then exact repository/head branch, then bounded search retries. A draft stays draft until independent approval and required checks permit readiness under automatic pipeline policy, or a recorded manual readiness decision permits it. An unresolved draft blocks merge; record `pr.ready` after readiness and read it back before merging. Immediately before merge, reread the head and required checks; the merge API must enforce `expected_sha` atomically. A pre-call comparison alone is insufficient. Unsupported SHA enforcement fails closed. Read back the merge receipt, including reviewed head and resulting merge SHA. Review and merge use only the expected PR; never pick a search result by title alone.

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
- **Optional Typesafe/Jev:** off by default. Harness-side runner code calls a fixed structured API packet at a suspected stall/loop or before review. Packet: stage, elapsed time, progress counters, repeated-error hashes, gate summaries and bounded sanitized evidence; no credentials, private transcripts or arbitrary model-selected questions. Schema-validate a response such as `continue | flag_loop | flag_review_gap | needs_decision`, with reasons and confidence. Bound call duration, retries and frequency; provider and gateway budgets remain external. Record advisory evidence; it cannot approve, waive or replace deterministic checks or the reviewer. Default API failure records `unavailable` and retains normal gates/timeouts; an explicitly required policy blocks on failure. Flags pause for inspection rather than automatically repeating work. The provider schema remains to be verified when that optional ticket is built.

## 5. State, events and results

### 5.1 Durable state and recovery

Use one fsynced, append-only event journal as authority and an atomically replaced `state.json` snapshot as a read cache. Each journal record has schema version, sequence, event ID, time, ticket, attempt, run and lane, plus an allowlisted payload. Replay rebuilds a missing/stale snapshot; reject malformed records and recover only a provably incomplete trailing write. A failed journal write stops dispatch.

State includes phase, lane/repository, lease, all worker/reviewer identities, run handles/deadlines, attempts, gate receipts, PR/head, reviewed and merged SHAs, decisions, approval receipts and pending effects. Phases: queued → building → gating → reviewing → approving → merging → done. A pipeline requiring human acceptance inserts awaiting_acceptance before approving. Manual merge ends at `finished_awaiting_human` after tracker approval, carrying the accepted SHA and pending merge. Stopped, failed and needs_decision are explicit exits. These holds and `finished_awaiting_human` are terminal for the current invocation and resumable in durable ticket state. Job state uses the same run/effect records; successful jobs close with `job.finished`.

Each external effect follows **intent → action → observed receipt**. On every new invocation, acquire the ownership lock, replay, validate supervisor/child identities and deadlines, and reconcile pending effects using their IDs before admitting new work. A lost merge response is checked through the forge; a lost approval response through td. A live supervised child is adopted without relaunch; its elapsed wall time and idle deadline do not reset. A dead child with an exit receipt is reconciled, and one without a receipt becomes `run.died`, not a successful run. Unknown processes or non-idempotent job effects pause for a decision. Exactly-once external execution is not assumed. Missing evidence never means success.

### 5.2 Events and notification delivery

Core events: `ticket.queued`, `attempt.started`, `effect.planned`, `effect.observed`, `run.start_requested`, `run.started`, `run.launch_failed`, `run.finished`, `run.died`, `run.stalled`, `run.timed_out`, `gate.passed`, `gate.failed`, `review.verdict`, `decision.recorded`, `tracker.approved`, `pr.ready`, `pr.merged`, `ticket.finished_awaiting_human`, `ticket.stopped`, `ticket.needs_decision`, `job.finished`, `runner.started`, `runner.heartbeat`, `runner.finished`, `policy.warning` and `judgment.unavailable`.

Events contain evidence references and reason codes, not raw prompts/output or secret configuration. Render status from events; never parse status text back into state. Notifications use a durable consumer cursor and delivery ID: at-least-once delivery, deduplication where supported, bounded retries and visible terminal failure. An offline notification sink must not lose the ticket's decision state.

### 5.3 Results

Record duration, rounds, gate failures, review findings, outcome and optional token/cost usage per attempt/profile. Unknown cost is “unavailable,” not zero. Results and the future UI consume journal-derived records. A ticket owns attempts; attempts own disposable sessions and verification/review evidence. A worker note carries assumptions and next steps without becoming a second database.

## 6. Scheduler and monitor

The runner is **ephemeral**: start it for a ticket, job or lane to drain. Queue filling, monitoring and notification delivery belong to that invocation. No daemon or boot hook starts it. It continues after orchestrator disconnect while its process lives; durable state supports the next invocation without starting one automatically.

The durable queue stores ticket, repository, pipeline, lane and overrides. Read dependencies/holds from td; enqueue leaf tickets, not planning parents. Duplicate enqueue is idempotent. An execution ownership lock prevents competing invocations. Short journal-write locks let commands append queue/control requests for the owner to reconcile.

Support global and **per-lane caps**, selected by repository or queue. Lane `corylus` has cap **1**: one ticket workflow or standalone job. Worker, reviewer and closer run sequentially in that slot; an internal closer never queues behind itself. Human holds release the slot after child exit; resume reacquires it. Never release a slot with a live child. Other lanes run within the global cap, optionally restricted by profile caps. Use eligible FIFO within lanes and round-robin between lanes.

Drain fills slots after exits. Every monitor tick checks process identity, exit, launch/wall deadlines and idle progress; heartbeats and optional judgment do not replace these checks. Death/stall stops work by default; configured retry permits one reconciled safe retry. Persist stop/pause intent before acting: pause prevents admission, stop cancels active work with a receipt. Notifications use durable cursors and bounded retries; failures remain visible for the next invocation.

Ticket/job invocations exit at their terminal outcome. Drain exits when its queue is empty and admitted work is terminal, including `finished_awaiting_human`. Record `runner.finished` with outcomes and pending human actions. Acceptance/decision holds are invocation-terminal, not child deaths. A blocked queue returns attention instead of polling forever; failed dependencies block dependents. Include notification failures in the exit summary. New work after exit needs another invocation.

Runner death stops new dispatch, approval and merge. Existing harnesses can finish or time out under their supervisors (§4.1). On the next start, reconcile identities, receipts, deadlines, leases and effects **before** admitting work. Adopt known live runs, record deaths/timeouts and pause uncertain effects. A manual lane with no merge event is finished awaiting a human, never dead. Recovery requires the next invocation.

## 7. Command line

```text
corylus-run config check | config show
corylus-run run TICKET [--pipeline P] [--worker PROFILE] [--reviewer PROFILE]
corylus-run drain LANE [--lane OTHER]
corylus-run review TICKET [--reviewer PROFILE]
corylus-run decision TICKET --file FILE
corylus-run resume TICKET --note-file FILE
corylus-run job TICKET --profile P --prompt-file FILE [--authorization REF]
corylus-run stop TICKET | pause TICKET
corylus-run queue add TICKET --lane L | queue list
corylus-run status [TICKET]
corylus-run results [--by profile|pipeline|lane]
```

`run`, `review`, `resume`, `job` and `drain` acquire execution ownership, recover state, drive the engine in the foreground and exit when their work reaches an invocation-terminal outcome. A conflicting owner returns a clear busy result, never a second launch. Queue/control commands persist requests for the active or next invocation; `queue add` alone launches nothing. Read-only status/results need no running executor. Successful completion returns 0, failures return 1, and human/dependency attention returns 2; a completed manual lane returns 0 with its pending human action displayed.

Review-only discovers existing work and pins its head. Decision files record required human acceptance, manual merge authorization or a scoped waiver; missing authority is rejected. Job authorization is optional in the command syntax and checked against the policy chosen in §12; it is not an implicit token requirement. Resume notes are sanitized and preserved as evidence. No flags bypass independence, gates or effect reconciliation. Every published PR body/comment identifies its AI author; adapters enforce this for runner-authored text, and the finish gate checks worker publication evidence.

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
human_acceptance = false
merge = "automatic"

[pipeline.design]
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
- Crash before/after every effect; recovery on the next start; snapshot replay; duplicate queue/resume; no duplicate launch, approval or merge. Surviving children keep their deadlines and are adopted; orphan supervisors enforce limits without the runner.
- Creator/worker approval refusal, actual reviewer-context approval, same-model warning, accepted waiver → independent closer, and unauthorized waiver refusal.
- Lane cap 1, other lanes, slot recovery, held tickets and internal closer without deadlock. Drain fills slots without the orchestrator, exits on an empty terminal queue, and reports blocked/attention queues without hanging.
- Manual lane ends at independent approval with no merge event: persist `finished_awaiting_human`, release the slot and exit; the monitor never emits false `run.died`. Resume revalidates the accepted SHA. Default automatic pipeline readies a permitted draft and merges only that SHA.
- Draft handling, delayed PR discovery, forge errors, atomic SHA guard and lost merge response.
- Notification outage/retry, sanitization before persistence, judgment unavailable/malformed output and unchanged deterministic gates.
- Authorized service job: backup, reload, service-user verification and rollback on failure.

Run targeted Python unit tests and Ruff; end-to-end fakes run in CI. Install from a reviewed known commit/tag, preserving executable permissions. No edits to a running release. Invocation/recovery probes must show a start event, working monitor/notification consumer and terminal exit, not just a live PID. Kill the runner during a stub run and verify supervised deadlines plus reconciliation on the next start; install no boot service.

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
| 6. Durable launcher | `runner/launcher.py`, `runner/supervisor.py`: claim/spawn/receipt, per-run deadline supervision and process-group control | Missing executable, start deadline, uncertain spawn, identity mismatch, cancellation; runner death retains child limits/receipts | Codex; 1, 3, 4 |
| 7. CLI harness | `runner/harness.py`: Harness implementation and scrub-before-store output boundary | stdin prompt, argv placeholders, session/final parsing, resume/fresh fallback, limits, secret-output refusal | Codex; 2, 4, 6 |
| 8. Verdict parser | `runner/verdict.py`: final-line enum and findings | Hyphenated verdict, duplicates, invalid JSON, unsafe paths, failed exit | Cheap; 1 |
| 9. Tracker read/session | `runner/tracker.py`: get/context/log/submit | Isolated tracker contexts, live identity discovery, malformed capability/schema, effect-tagged logs | Codex; 1 |
| 10. Tracker approval | Extend `runner/tracker.py`: eligibility and approval/readback | Real temporary td project: worker/creator refusal, reviewer succeeds, refusal stops; lost response reconciliation | Codex; 3, 9 |
| 11. Forge | `runner/forge.py`: lookup/head/ready/atomic merge | Exact branch, search lag, draft, API errors, moved head, lost response | Cheap; 1 |
| 12. Finish/check gates | `runner/gates.py`: Gate plus finish/check implementations | Clean/upstream/PR checks, discovery fails closed, commands and receipts tied to SHA | Cheap; 1, 5, 11 |
| 13. Review policy | `runner/policy.py`: identities/model warning, acceptance/waiver validation | Unknown identity refusal, same-model warning, unauthorized/stale waiver, reviewer versus closer eligibility; automatic versus manual acceptance/merge policy | Cheap; 1, 8, 9 |
| 14. Single-ticket engine | `runner/engine.py`: pure transitions emitting effect requests | Build/gate/review/remediation, one nudge, round bound, holds; automatic merge and manual `finished_awaiting_human` with no merge event; no success on missing receipt | Codex; 1, 8, 13 |
| 15. Effect driver/recovery | `runner/driver.py`: execute/reconcile engine effects | Stub full workflow; recovery on start around launch/approval/merge; adopt supervised children without resetting deadlines; no duplicate effects | Codex; 3, 5, 7, 10–14 |
| 16. Monitor | `runner/monitor.py`: tick/deadline/cancel decisions | Fake clock death, PID reuse, log-only activity, idle/wall/launch deadlines; manual completion never reported dead | Codex; 3, 6, 7 |
| 17. Queue/lanes | `runner/scheduler.py`: durable enqueue/admission/leases | Corylus cap 1, global/profile caps, FIFO/fairness, dependency holds, slot recovery | Cheap; 2, 3 |
| 18. Ephemeral invocation | `runner/invocation.py`: ownership, recover-on-start, scheduling/monitor ticks and drain-to-exit; injectable job executor | Orchestrator disconnect, runner death/restart, empty drain exit, blocked queue attention, simultaneous commands, human hold release, manual completion, closer slot reuse with fake job | Codex; 15–17 |
| 19. Jobs/closer | `runner/jobs.py`: bounded jobs with configurable authorization and independent closer | Waiver recommendation + accepted decision + independent approval; chosen job-policy authorization; missing authority; uncertain live effect pauses | Codex; 7, 10, 13, 15, 18 |
| 20. CLI | `runner/cli.py`: §7 commands | Argument validation, sanitized config/status, lease-safe enqueue, drain-and-exit, busy owner, exit codes, review-only, decisions and jobs | Cheap; 2, 3, 18, 19 |
| 21. Notifications/results | `runner/notify.py`, `runner/results.py`: cursor delivery and reports | Outage/retry/dedup, visible delivery failure, unavailable cost, deterministic replay reports | Cheap; 3, 18 |
| 22. Service-job gate | `runner/service_gate.py`: runbook effect receipts and service-user probe | Fake backup/change/reload/verify; failed verification restores/reloads; failed rollback alerts | Codex; 12, 19 |
| 23. Optional judgment | `runner/judgment.py`: fixed packets behind Gate, disabled by default | Sanitization, bounded call, bad schema, unavailable, flag pauses, never grants approval | Cheap; 2, 12, 16 |
| 24. Release/regression suite | `tests/runner/test_e2e.py`, `.github/workflows/runner.yml`; release notes in `docs/runner-release.md` | §9 matrix, targeted/unit CI and Ruff; installed executable/start/restart smoke checks | Codex; 1–23 |

Step 24 has three files because CI and the release runbook accompany the integration suite; it implements no new runtime behavior. UI consumption is a later design/build slice, preserving existing workflows. Approval of this proposal is not approval to start all tickets unattended.

## 12. Decisions and open questions

Julian can accept or change the recommendations below. Job authorization is deliberately unresolved: there is no selected default, and it must be settled before the job-policy slice is built. That does not block the rest of the design review.

| Question | Decision or recommended default |
|---|---|
| Runner lifetime and installation binding? | **Decided:** ephemeral invocation; no daemon or start-at-boot. Recommend one local execution account with private installation bindings. Start it for a ticket/job or lane and exit at its terminal outcome; recover on the next invocation. |
| Does job mode need config allowance, a ticket note or a per-run token? | **Open:** compare the three options below. No per-run token by default; Julian chooses the authority model before that slice starts. Closer review/waiver evidence remains mandatory in all options. |
| How should the ticket page show same-model warnings and policy refusals? | Warning alongside review evidence, without blocking acceptance. Refusal/NEEDS-DECISION in the ticket's attention area with reason and next action; detailed evidence folded into the attempt timeline. Preserve the current interface. |
| When may the runner merge after review? | **Decided:** automatic after independent approval, for the exact reviewed SHA with atomic forge enforcement and a recorded merge event. Manual merge is a per-pipeline option; design review requires Julian's acceptance and ends at `finished_awaiting_human`. |
| Should Typesafe/Jev flags stop work automatically? | Off initially; when enabled, advisory flags pause for inspection. Benchmark false positives before enabling stronger policy. Unavailable optional judgment never disables deterministic safety checks. |

| Job authorization option | Trade-off |
|---|---|
| Config allowance only | Least friction for recurring jobs; config grants bounded capabilities. Needs narrow job-kind/effect allowlists and clear audit records; a mistaken allowance can authorize repeated effects. |
| Allowance plus ticket-scoped note | Config permits the capability; a durable note approves the ticket's specific work. More context and accountability without per-run tokens; define expiry/reuse when resuming or retrying. |
| Per-run token | Explicit authorization for each execution, with narrow scope/expiry. More ceremony and token lifecycle/recovery work; slows unattended queues. This is an option, not a required default. |

### 12.1 Future work

Per-ticket spend caps are **deferred**, not part of initial runner configuration or build acceptance. Built-in run limits are hard wall-clock and idle timeouts, with launch deadlines for start failures. Provider and gateway budgets remain external. Optional usage/cost reporting is observational and labels unavailable metering. A future cap proposal must define enforcement with missing/delayed usage; it does not block this design or its initial build plan.
