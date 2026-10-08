# Corylus runner: a harness-agnostic build and review loop

**Design proposal, revised for review.** Owner: Julian. Date: 2026-10-08 (US Pacific).
Written by an AI agent (Codex (GPT-6.1 Sol)), revising the original Claude Code draft.
Julian must approve this design before any build ticket starts. This document authorizes no implementation, deployment or merge.

## 0. The one-paragraph version

Corylus is the control layer for an automated agentic work pipeline: agents build, an independent agent judges, Julian decides. Its proposed headless runner takes a tracker ticket through build, verification, review and bounded remediation. It supports any harness in either role through configuration, maintains durable state, and keeps a persistent queue scheduler watching for work without an orchestrator staying online. Each ticket workflow and each worker, reviewer or job run finishes independently; the scheduler remains available for later arrivals. Automatic merge after independent approval is the default, guarded by the exact reviewed SHA; pipelines such as design review can require human acceptance and manual merge. There are two roles, **worker** and **reviewer**, plus **job mode** for bounded runbook work. The engine and tests are public; installation settings stay private. The first Corylus lane runs one ticket at a time.

## 1. Background and inputs

This revision draws on these sources, summarized without installation identifiers:

- **Julian's decisions, 2026-10-08**, recorded in `td-a8a0af` and its revision brief: configurable harnesses in both roles; TOML; different sessions by default; the same model warns rather than refuses; two roles plus job mode; a serial Corylus lane. Later decisions require automatic merge by default, no initial spend caps and further exploration of job authorization (§12). The newest queue-persistence clarification supersedes drain-to-exit for the scheduler; individual runs still exit after their work.
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
| A queue runner with a slot cap was needed to keep work moving without the orchestrator | A persistent scheduler owns queue filling and monitoring, including arrivals after an empty queue; durable queue and lane caps survive restart (§6). |
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
- **Single ownership:** an invocation ownership lock plus ticket leases prevent duplicate execution. Gate, tracker, forge and notification calls also have finite deadlines and retries. Cancellation uses `limits.cancel_grace_seconds`; rollback has a separate `limits.rollback_timeout_seconds` so an expired ticket deadline cannot abandon restoration.

## 3. Roles and contracts

### 3.1 Worker

Receives the live ticket, rendered rules/guide, prior findings and its worktree. Leaves committed, pushed work in an open PR, with verification evidence and a tracker review request. The engine verifies those facts independently. A finish nudge uses the configured budget (§8.2, proposed one per attempt), resuming the same session when supported; otherwise it starts a fresh session with the persisted handoff. It remains the same round.

### 3.2 Reviewer

Receives the ticket, exact PR head, verification evidence, prior findings and a separate review worktree. It never receives private worker reasoning. Its final message ends with exactly one of:

```text
VERDICT: APPROVE
VERDICT: REJECT
VERDICT: NEEDS-DECISION
```

Allow one terminal newline; match the whole last line. Duplicate/conflicting verdict lines, malformed findings, an unknown enum or unsuccessful harness exit produce a failed review run, never approval. An optional fenced `findings` JSON block contains bounded entries `{file, line, severity, summary}`; repository-relative paths only. Store the SHA and reviewer session with every verdict. A changed head invalidates it.

`REJECT` enters `queued` for remediation while `pipeline.*.max_rounds` permits another round, otherwise `round_exhausted`. `NEEDS-DECISION` enters `needs_decision`; invalid output enters `failed` with a diagnostic. The proposed cap and accounting are decisions in §12, not accepted defaults.

### 3.3 Independence, approval and waivers

Each run has **two identities**: an opaque harness session reference for resume, and a tracker session ID for authorization. For td, give each fresh run its own `TD_CONTEXT_ID`, run `td usage --new-session` at context creation, and verify the resulting session with `td current`. Persist the context-to-session mapping; resume reuses it without creating a new session. Supply that context only to the child and its tracker command executor; never switch the runner invocation's own session. An adapter must demonstrate isolated session propagation before supporting approval.

The reviewer must differ from every worker harness session and from all ticket creator/implementer tracker sessions. Unknown identity or ineligible reviewer enters `needs_decision` before approval; an explicit tracker approval refusal enters `failed`. Profiles may use either role; the same normalized model in both roles emits `policy.warning` and stores `same_model: true`. It does not refuse review. There is no third loop role.

Normal acceptance:

1. Reviewer finishes with APPROVE for SHA S. Persist the evidence, session IDs and verdict; this alone does not close td or merge.
2. With a valid independent verdict, execute `td approve TICKET --reason REASON` **with the reviewer's persisted `TD_CONTEXT_ID`**, verifying `td current` still matches before acting. The reason references SHA S and review evidence. Human acceptance is required only by pipeline policy (for example design review); when required, record it before this command. Verify td's resulting status and reviewer-of-record; save a receipt. Never use the orchestrator's session, `--self-review`, or name-only `--reviewed-by` as a substitute.
3. In the default automatic pipeline, independent approval authorizes the SHA-guarded merge (§4.3). A manual pipeline ends this invocation at `finished_awaiting_human` with no merge event; a later explicitly authorized resume can merge. A tracker approval, a merged PR and deployment acceptance are distinct facts. An unresolved draft/check failure or failed/uncertain merge enters `awaiting_merge`; a changed head enters `needs_decision` and invalidates acceptance.

Waiver flow: the reviewer records findings and recommends a specific waiver, ending NEEDS-DECISION. Julian may accept or change it; an explicitly delegated “orchestrator waiver” counts only when the ticket records that authority. Persist the decision, scope, author and SHA. An **independent closer job**, using an eligible tracker session, rereads the live ticket, accepted waiver, review and exact head, then records approval in its own session with that evidence. It is job mode, not another role. A recommendation alone cannot close a ticket. A waiver does not bypass session eligibility, secret rules or SHA checks. Code changes require a new review. Declined human acceptance enters `acceptance_declined` without tracker approval. An accepted waiver queues a closer continuation of the **same ticket**, with a linked job run and fresh eligible session; it does not create another ticket or approve directly. Pipeline-required human acceptance precedes closer approval as well. §5.1 defines both paths.

Resume with a note does not itself approve or waive anything. Reviewers and closers must not create or implement the ticket they approve. td rejection is a policy stop, never a reason to retry under a fabricated identity. Where an installed td offers weaker trusted-mode shortcuts, the adapter still enforces this design's stricter boundary and validates supported commands at setup.

### 3.4 Job mode

One configured harness runs a bounded task without the build/review loop. It records authorization policy/evidence, effects, verification and a named workflow outcome. `job.finished` is a run event: standalone success enters `job_succeeded`; a closer returns to `approving`, not ticket completion. Config allowance, a ticket-scoped note and a per-run token are alternatives still under discussion (§12); no per-run token is required by default. This unresolved choice does not weaken closer eligibility or the authorization required for service changes. A closer is one job kind; service runbooks are another. Success of a harness process alone is not success of the runbook. Post-merge jobs are disabled unless both pipeline policy and recorded authorization permit them.

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

The CLI adapter uses argv templates, never shell strings; prompts use stdin or a file. Preflight executable, cwd, placeholders and output permissions. Persist a claim before launch and a receipt afterward, keyed by effect ID. Confirmed start emits `run.started`; failure emits `run.launch_failed`. Reconcile an uncertain launch into `needs_decision`, never duplicate it. A confirmed absent child permits `pipeline.*.launch_retries`; exhaustion enters `failed` for worker/reviewer/closer or `job_failed` for a standalone job (§5.1).

A per-run supervisor survives runner death, enforces wall/idle deadlines, stores sanitized progress/exit receipts and kills the child group at its limits. It exits with the run and cannot dispatch, approve or merge. The restarted scheduler or next one-shot invocation polls its durable handle; parent-only process waiting cannot adopt an orphan.

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

`Ticket` includes creator/implementer identities, review state and decisions. `ApprovalRequest` includes ticket, SHA, review reference, decision reference and effect ID. `approve` checks eligibility, executes in `actor`'s isolated context and reads back the recorded reviewer/status. On restart, inspect existing approval before repeating. Capability/schema errors enter `failed`. Tracker logs include stable effect IDs for reconciliation. Do not run `td export` or edit its scheduled export file.

### 4.3 Forge

`Forge.find_pr(repo, branch, recorded_id)`, `head(pr)`, `mark_ready(pr)` and `merge(pr, expected_sha)` return typed results or explicit errors. Lookup uses recorded ID, then exact repository/head branch, then bounded search retries. A draft stays draft until independent approval and required checks permit readiness under automatic pipeline policy, or a recorded manual readiness decision permits it. An unresolved draft or failed required check enters `awaiting_merge`; record `pr.ready` after readiness and read it back before merging. Immediately before merge, reread the head and required checks; the merge API must enforce `expected_sha` atomically. A pre-call comparison alone is insufficient. Unsupported SHA enforcement enters `failed` without a merge call. Read back the merge receipt, including reviewed head and resulting merge SHA. Review and merge use only the expected PR; never pick a search result by title alone.

### 4.4 Workspace

`Workspace.ensure(ticket, repo, base, effect_id)` creates/reuses a dedicated feature branch and worktree; `Workspace.review(ticket, sha)` creates a separate checkout pinned to that SHA. Verify repository identity, branch and cwd before launch. Never switch the main checkout's branch or launch there. Preserve dirty work; uncertain ownership enters `needs_decision`. Review worktrees forbid source edits through adapter policy; any modification invalidates review. Cleanup is explicit, never an automatic destructive recovery step.

### 4.5 Gates and optional judgment

```python
class Gate(Protocol):
    name: str
    def check(self, context: GateContext) -> GateResult: ...
```

`GateContext`: stage, ticket/attempt, repo/worktree, expected SHA, evidence references and sanitized progress packet. `GateResult`: pass/fail/error/advisory, bounded findings and verification receipts. A required deterministic gate error enters `failed`; missing check policy or required judgment availability enters `needs_decision`.

- **Finish:** clean worktree, commit equals upstream head, expected open PR and complete handoff. Check discovery errors fail closed.
- **Checks:** project-configured lint/tests for the changed scope, tied to that SHA. Record exact command, exit and bounded sanitized output. No applicable lint/test requires an explicit policy decision, never an invented pass. The shared `pipeline.*.finish_nudges` budget covers repairable finish/check failures; exhaustion enters `failed` before review. A recorded no-check exemption is scoped to the head and gate, then gating resumes.
- **Service verification (jobs only):** require a backup receipt, authorized change/reload and checks under the actual service user after reload. Failure triggers restore plus reload and re-verification. Successful rollback enters `job_rolled_back`; failed rollback enters `job_rollback_failed` and alerts. Neither is job success. It is not part of every code ticket's finish gate.
- **Optional Typesafe/Jev:** off by default. Harness-side runner code calls a fixed structured API packet at a build/review/closer suspected stall/loop or before review; service jobs use deterministic runbook gates. Packet: stage, elapsed time, progress counters, repeated-error hashes, gate summaries and bounded sanitized evidence; no credentials, private transcripts or arbitrary model-selected questions. Schema-validate a response such as `continue | flag_loop | flag_review_gap | needs_decision`, with reasons and confidence. Bound call duration, retries and frequency; provider and gateway budgets remain external. Record advisory evidence; it cannot approve, waive or replace deterministic checks or the reviewer. Default API failure records `unavailable` and retains normal gates/timeouts; an explicitly required policy enters `needs_decision` on failure. Flags enter `needs_decision` for inspection; `continue` retains the current state. The provider schema remains to be verified when that optional ticket is built.

## 5. State, events and results

### 5.1 Durable state and recovery

Use one fsynced, append-only event journal as authority and an atomically replaced `state.json` snapshot as a read cache. Each journal record has schema version, sequence, event ID, time, ticket, attempt, run and lane, plus an allowlisted payload. Replay rebuilds a missing/stale snapshot; reject malformed records and recover only a provably incomplete trailing write. A failed journal write stops dispatch.

State includes lane/repository, lease, identities, run handles/deadlines, round and retry counters, gate receipts, PR/head, reviewed and merged SHAs, decisions, approval receipts, pending effects and a saved continuation. The following is the single state vocabulary. **Terminal** means the workflow cannot resume; a **hold** ends a one-shot invocation but permits an authorized continuation. Both release a slot only after child exit/receipt (and required rollback). `queued` is pending, not terminal. Scheduler states have separate scope and no ticket slot.

| State | Scope / meaning | Terminal | Resumable hold | One-shot exit |
|---|---|---|---|---|
| `queued` | Workflow; pending build, remediation, review-only, merge or closer continuation | No | No | — |
| `building` | Worker launch/run, including a finish nudge | No | No | — |
| `gating` | Finish/check/judgment verification | No | No | — |
| `reviewing` | Independent reviewer launch/run | No | No | — |
| `awaiting_acceptance` | Julian's pipeline-required acceptance | No | Yes | 2 |
| `approving` | Eligible reviewer/closer tracker approval and readback | No | No | — |
| `merging` | Readiness, atomic SHA-guarded merge and readback | No | No | — |
| `job_authorizing` | Standalone job policy/evidence check | No | No | — |
| `job_running` | Authorized standalone job launch/run | No | No | — |
| `job_verifying` | Authorized service job backup/change/reload/probe | No | No | — |
| `job_rolling_back` | Restore/reload/re-verify after failed or canceled service work | No | No | — |
| `closer_running` | Same-ticket waiver continuation; independent linked job run | No | No | — |
| `quiescing` | Cancel/reap active run before completing a control or hold | No | No | — |
| `done` | Exact reviewed head merged, receipt recorded | Yes | No | 0 |
| `job_succeeded` | Standalone job effects and verification succeeded | Yes | No | 0 |
| `finished_awaiting_human` | Approved manual lane, pending explicit merge authorization | No | Yes | 0 |
| `needs_decision` | Policy, identity, stale head or uncertain effect attention | No | Yes | 2 |
| `dependency_blocked` | Queued prerequisite not satisfied | No | Yes | 2 |
| `paused` | Explicit pause, saved continuation and no live child | No | Yes | 2 |
| `awaiting_merge` | Approved work; draft/check/API/readback prevents confirmed merge | No | Yes | 2 |
| `failed` | Build/review/approval/gate/launch failure, reason recorded | Yes | No | 1 |
| `stopped` | Explicit stop, cancellation/recovery receipt recorded | Yes | No | 2 |
| `round_exhausted` | Another worker round required but cap reached | Yes | No | 1 |
| `acceptance_declined` | Julian declined required acceptance | Yes | No | 2 |
| `job_failed` | Standalone job failure with no effects requiring rollback | Yes | No | 1 |
| `job_rolled_back` | Failed service work restored and re-verified | Yes | No | 1 |
| `job_rollback_failed` | Restoration or its verification failed; alert recorded | Yes | No | 1 |
| `scheduler_recovering` | Scheduler replay/ownership/effect reconciliation | No | No | — |
| `scheduler_watching` | Persistent admission/monitoring, including an empty queue | No | No | — |
| `scheduler_stopping` | Explicit shutdown; drain admitted work, refuse admission | No | No | — |
| `scheduler_stopped` | Clean explicit scheduler shutdown | Yes | No | 0 |
| `scheduler_failed` | Scheduler storage/ownership/recovery failure | Yes | No | 1 |

**Transition semantics.** Rows are exhaustive; unlisted events are rejected without effects. Fresh events must pass schema/version and current run/effect/head checks; duplicate IDs take only the deduplication row. Verdicts with failed exits normalize to run.failed; invalid identity to identity.refused and stale heads to head.changed. Sets below are finite aliases expanded into individual rows by the future Lean model. Guards on overlapping events are disjoint. All admitting rows require satisfied dependencies, a free slot and valid continuation evidence; the explicit dependency/no-slot/invalid-evidence rows cover their complements. Cancellation targets only verified process identities; unknown identity remains a decision hold with its lease retained. Every row writes the event/state and effect intent durably before executing its effect; receipt observation is a separate event. Persistence failure uses the owner’s storage.failed row below; its result state may be nondurable and it executes no new effect. Recovery replays the last durable workflow state.

- `W` = `queued`, `building`, `gating`, `reviewing`, `awaiting_acceptance`, `approving`, `merging`, `job_authorizing`, `job_running`, `job_verifying`, `job_rolling_back`, `closer_running`, `quiescing`, `finished_awaiting_human`, `needs_decision`, `dependency_blocked`, `paused`, `awaiting_merge`.
- `R` = `building`, `reviewing`, `job_running`, `closer_running`; `B` = `building`, `reviewing`, `closer_running`; `J` = `job_running`, `job_verifying`; `H` = `needs_decision`, `paused`, `dependency_blocked`.
- `S` is the finite set of all states in the state table. `return_state` is a saved active phase (`building`, `gating`, `reviewing`, `approving`, `merging`, `job_authorizing`, `job_running`, `job_verifying`, `closer_running`), never a terminal state. Resuming `building` requests a same-attempt continuation, not an automatic new round; a new round requires the run-failure/remediation rows. `launch_pending`, run kind, effect IDs and counters are durable data, not additional phases. Entry into a run state requests launch unless a live reconciled run or completed approval receipt already exists.
- Proposed accounting: a round is consumed on the first **confirmed worker start** for that attempt, even if it later crashes/times out. Launch retries before that start, reviewer/closer runs and nudges consume no additional round. Reconciled starts count once. The proposed `pipeline.*.round_accounting = "confirmed_worker_start"` selects this accounting rule. Run-failure retries are bounded per run stage/attempt; a worker retry after a confirmed start opens a new round. Counters and existing run deadlines never reset on recovery or hold/resume; a new bounded run gets its own deadlines, and the ticket deadline spans all runs; §12 asks Julian to accept/change these rules.

| From-state | Event | Guard | To-state | Effect |
|---|---|---|---|---|
| `queued` | admission.checked | Dependency unmet/failed | `dependency_blocked` | Record prerequisite and attention |
| `dependency_blocked` | dependency.satisfied | All prerequisites satisfied | `queued` | Restore queue eligibility |
| `queued` | admission.checked | Dependencies satisfied; no free slot | `queued` | Wait; no child/effect |
| `queued` | admission.checked | Slot free; continuation = build; rounds below cap | `building` | Lease slot; ensure workspace; request worker launch |
| `queued` | admission.checked | Slot free; continuation = build; rounds at cap | `round_exhausted` | Record exhaustion; release slot |
| `queued` | admission.checked | Slot free; continuation = review; valid work/head/gates | `reviewing` | Lease slot; pin review workspace; fresh reviewer |
| `queued` | admission.checked | Slot free; continuation = merge; authorized exact head | `merging` | Lease slot; revalidate approval/head/checks |
| `queued` | admission.checked | Slot free; continuation = closer; accepted scoped waiver | `closer_running` | Lease same-ticket slot; launch independent closer job |
| `queued` | admission.checked | Slot free; continuation = job | `job_authorizing` | Lease slot; evaluate chosen job policy |
| `queued` | admission.checked | Slot free; continuation = saved_phase; validated return_state and reconciled effects | Saved return_state | Lease slot; resume pending gates/action or same-attempt run |
| `queued` | admission.checked | Slot free; continuation evidence invalid | `needs_decision` | Record missing/stale evidence; no launch |
| `building`, `reviewing` | workspace.failed | Known setup failure | `failed` | Record diagnostic; no launch |
| `building`, `reviewing` | workspace.uncertain | Ownership/cwd/head cannot be established | `needs_decision` | Save continuation; no launch |
| `R` | run.started | Claimed effect; valid identities/cwd; first start receipt; start confirmed before launch deadline | Same from-state | Save handle/deadlines; count worker round once |
| `R` | run.started | Claimed effect; valid identities/cwd; first start receipt; launch deadline already expired | Same from-state | Save handle; count worker round once; emit run.failed with launch-deadline reason |
| `reviewing`, `closer_running` | identity.refused | Unknown or ineligible session; no live child | `needs_decision` | Save receipt/diagnostic |
| `reviewing`, `closer_running` | identity.refused | Unknown or ineligible session; live known child | `quiescing` | Save needs_decision target; cancel/reap; no approval |
| `R` | run.launch_failed | Child confirmed absent; launch retry budget remains | Same from-state | Increment launch retries; fresh launch intent |
| `building`, `reviewing`, `closer_running` | run.launch_failed | Child absent; launch budget exhausted | `failed` | Record launch failure |
| `job_running` | run.launch_failed | Child absent; launch budget exhausted | `job_failed` | Record launch failure |
| `W` | effect.uncertain | Process/approval/job result cannot be reconciled (merge uncertainty uses merge.blocked) | `needs_decision` | Preserve effect ID and saved continuation; prohibit repeat |
| `building` | run.finished | Exit 0; sanitized result available | `gating` | Record handoff; run gates at head |
| `building` | run.finished | Exit 0; required result/handoff unavailable | `failed` | Record result-contract failure |
| `building`, `reviewing`, `closer_running` | run.failed | Crash/nonzero/idle/wall deadline; confirmed safe retry; budget remains; if worker, another round available | Same from-state | Cancel/reap; increment retry; worker opens new attempt; fresh run |
| `building` | run.failed | Safe retry available but no worker round capacity | `round_exhausted` | Cancel/reap; record exhausted cap |
| `building`, `reviewing`, `closer_running` | run.failed | Retry disabled/exhausted or known unsafe to repeat | `failed` | Cancel/reap; record timeout/stall/crash reason |
| `gating` | gate.passed | More configured gates remain | `gating` | Save SHA-bound receipt; request next gate |
| `gating` | gate.passed | All required gates passed/exempted at current head | `reviewing` | Pin head; request independent reviewer |
| `gating` | gate.failed | Repairable finish/check failure; nudge budget remains | `building` | Increment shared nudge counter; resume/fresh worker, same round |
| `gating` | gate.failed | Repairable failure; nudge budget exhausted | `failed` | Record finish/check failure; no review |
| `gating` | gate.failed | Nonrepairable deterministic required gate failure | `failed` | Record diagnostic; no review |
| `gating` | gate.error | Deterministic required gate/discovery error | `failed` | Record diagnostic; no review |
| `gating` | checks.absent | No applicable check and no recorded exemption | `needs_decision` | Save gating continuation; request SHA-scoped policy |
| `gating`, `B` | judgment.unavailable | Judgment optional | Same from-state | Record unavailable; retain deterministic gates/deadlines |
| `gating`, `B` | judgment.unavailable | Judgment required; no live child | `needs_decision` | Record policy blocker |
| `B` | judgment.unavailable | Judgment required; live known child | `quiescing` | Save needs_decision target; cancel/reap |
| `gating`, `B` | judgment.result | Valid response = continue | Same from-state | Record advisory evidence |
| `gating`, `B` | judgment.result | Valid response = flag_loop/flag_review_gap/needs_decision; no live child | `needs_decision` | Save continuation and inspection packet |
| `B` | judgment.result | Valid flag response; live known child | `quiescing` | Save needs_decision target/packet; cancel/reap |
| `reviewing` | review.verdict | Malformed/duplicate/unknown/findings invalid; exit 0 | `failed` | Save diagnostic; no approval |
| `reviewing` | review.verdict | Valid REJECT; exit 0; another round available | `queued` | Save findings; continuation = build; release slot |
| `reviewing` | review.verdict | Valid REJECT; exit 0; round cap reached | `round_exhausted` | Save findings; release slot |
| `reviewing` | review.verdict | Valid NEEDS-DECISION; exit 0 | `needs_decision` | Save findings/waiver recommendation |
| `reviewing` | review.verdict | Valid APPROVE; exit 0; head/identity current; human acceptance required | `awaiting_acceptance` | Save independent verdict; release slot; no tracker approval |
| `reviewing` | review.verdict | Valid APPROVE; exit 0; head/identity current; no human acceptance required | `approving` | Request tracker approval in reviewer context |
| `reviewing`, `awaiting_acceptance`, `approving`, `merging`, `closer_running` | head.changed | Reviewed/waived head changed or reviewer edited worktree; no live child | `needs_decision` | Invalidate verdict/acceptance; require gated review of new head |
| `reviewing`, `closer_running` | head.changed | Head changed or review worktree edited; live known child | `quiescing` | Save needs_decision target; invalidate verdict; cancel/reap |
| `awaiting_acceptance` | decision.recorded | Authorized acceptance; normal reviewer continuation; exact head valid; slot available | `approving` | Reacquire slot; request reviewer-context approval |
| `awaiting_acceptance` | decision.recorded | Authorized acceptance; normal reviewer continuation; exact head valid; no slot | `awaiting_acceptance` | Save acceptance; retry slot acquisition, no approval yet |
| `awaiting_acceptance` | acceptance.ready | Saved acceptance current; normal reviewer continuation; slot now free | `approving` | Lease slot; request reviewer-context approval |
| `awaiting_acceptance` | decision.recorded | Authorized acceptance; closer continuation; head/waiver current | `queued` | Save acceptance; continuation = closer; admission enforces caps |
| `awaiting_acceptance` | decision.recorded | Authorized acceptance declined | `acceptance_declined` | Save refusal; no tracker approval/merge |
| `needs_decision` | decision.recorded | Authorized accepted waiver; scope/head/review current; no live/unknown child or unresolved effect; deadline not expired; human acceptance unnecessary/already recorded | `queued` | Save waiver; continuation = closer; no direct approval |
| `needs_decision` | decision.recorded | Authorized accepted waiver; scope/head/review current; safe effects/child exit; deadline not expired; required human acceptance missing | `awaiting_acceptance` | Save waiver and closer continuation; no approval yet |
| `closer_running` | job.finished | Exit 0; eligible independent closer; required human acceptance satisfied; approval receipt verified at head | `approving` | Save closer receipt; emit tracker.approved; do not repeat approval |
| `closer_running` | job.finished | Exit 0 but required approval evidence missing/refused | `failed` | Record closer failure; no merge |
| `approving` | tracker.approved | Readback/actor/head valid; merge policy manual | `finished_awaiting_human` | Save receipt/pending merge; release slot; no merge event |
| `approving` | tracker.approved | Readback/actor/head valid; merge policy automatic | `merging` | Save receipt; request readiness/head/check revalidation |
| `approving` | tracker.failed | Explicit refusal, schema error or definitive failed readback | `failed` | Record approval failure; never substitute actor |
| `merging` | merge.blocked | Draft unready, required check failed/pending, known API failure, or unconfirmed readback | `awaiting_merge` | Save accepted head/pending effect; prohibit blind repeat |
| `merging` | merge.unsupported | Forge cannot atomically enforce expected SHA | `failed` | Record capability error; no merge call |
| `merging` | pr.ready | Approved head/current checks authorize readiness; draft readback ready | `merging` | Record readiness; atomically merge expected SHA |
| `merging` | merge.requested | Already ready; approval/head/checks valid | `merging` | Atomically merge expected SHA |
| `merging`, `awaiting_merge` | pr.merged | Reconciled receipt proves expected head merged | `done` | Save resulting merge SHA; release slot |
| `awaiting_merge` | resume.requested | Explicit authorization; same accepted head; pending effects reconciled absent; deadline not expired | `queued` | Continuation = merge; revalidate checks/readiness |
| `finished_awaiting_human` | resume.requested | Recorded manual merge authorization; same accepted head; deadline not expired | `queued` | Continuation = merge; revalidate all merge guards |
| `finished_awaiting_human`, `awaiting_merge` | resume.requested | Accepted head stale | `needs_decision` | Invalidate acceptance; require new gated review |
| `finished_awaiting_human`, `awaiting_merge` | resume.requested | Head current but authority/reconciliation/deadline guard false | Same from-state | Reject request; no effect |
| `H` | resume.requested | Recorded decision resolves blocker; saved continuation valid; no live/unknown child or unresolved effect; deadline not expired | `queued` | Schedule saved continuation under caps; preserve budgets |
| `H` | resume.requested | Successful-resume guard false | Same from-state | Reject request; record diagnostic; no effects |
| `job_authorizing` | authorization.checked | Chosen job policy satisfied | `job_running` | Save evidence; request bounded job launch |
| `job_authorizing` | authorization.checked | Policy undecided or required evidence absent | `needs_decision` | Save job continuation; no effects |
| `job_running` | job.finished | Exit 0; non-service; required effect/verification receipts valid | `job_succeeded` | Save run and workflow outcome; release slot |
| `job_running` | job.finished | Exit 0; authorized service runbook | `job_verifying` | Reconcile step receipts; execute only missing authorized steps; service-user probe |
| `job_running` | job.finished | Exit 0 but non-service success evidence missing | `job_failed` | Record evidence failure |
| `J` | job.failed | Known failure; no changed service state | `job_failed` | Cancel/reap; record diagnostic |
| `job_running` | run.failed | Confirmed no effects; safe retry budget remains | `job_running` | Cancel/reap; increment run retry; fresh bounded job |
| `job_running` | run.failed | No changed service state; safe retry guard false | `job_failed` | Cancel/reap; record timeout/stall/crash |
| `J` | job.failed / run.failed | Service state changed; backup receipt available | `job_rolling_back` | Cancel/reap; restore backup; reload; re-verify |
| `J` | job.failed / run.failed | Service state changed; backup unavailable | `job_rollback_failed` | Cancel/reap; record recovery failure; alert |
| `job_verifying` | run.failed | No changed service state | `job_failed` | Record timeout/crash; cancel/reap |
| `job_verifying` | job.verified | All runbook receipts valid; probe passed | `job_succeeded` | Save success; release slot |
| `job_rolling_back` | rollback.verified | Restore/reload/probe passed; no control target | `job_rolled_back` | Save failed-job/recovery receipts; release slot |
| `job_rolling_back` | rollback.verified | Restore/reload/probe passed; control target paused/stopped | Saved control target | Save recovery/cancellation receipt; release slot |
| `job_rolling_back` | rollback.failed | Restore/reload/probe failed or timed out | `job_rollback_failed` | Save failure; alert; release only after child exit |
| `W` | stop.requested / pause.requested | No changed service state; not rolling back or quiescing | `quiescing` | Save stopped/paused target respectively and continuation; cancel/reap child |
| `W` | stop.requested / pause.requested | Service effect safety unknown outside J/rollback | `needs_decision` | Record control request; retain lease; require recovery decision |
| `quiescing` | cancel.verified | Child absent/exited; cancellation receipt durable | Saved control target | Record receipt; release slot |
| `quiescing` | cancel.failed | Cannot confirm child exit or effect safety | `needs_decision` | Alert; retain slot while live/unknown child |
| `quiescing` | stop.requested / pause.requested | Cancellation in progress | `quiescing` | Update saved stopped/paused target; continue cancellation |
| `J` | stop.requested / pause.requested | Service state changed; backup available | `job_rolling_back` | Save control target; cancel/reap; restore/reload/probe |
| `J` | stop.requested / pause.requested | Service state changed; backup unavailable | `job_rollback_failed` | Cancel/reap; record recovery failure; alert |
| `job_rolling_back` | stop.requested / pause.requested | Rollback in progress | `job_rolling_back` | Save control target; finish rollback before releasing slot |
| `W` | ticket.deadline | Enabled persisted deadline expired; no changed service state; not rolling back or quiescing | `quiescing` | Save stopped target/deadline reason; cancel/reap |
| `W` | ticket.deadline | Expired; service effect safety unknown outside J/rollback | `needs_decision` | Alert; retain lease; require recovery decision |
| `J` | ticket.deadline | Deadline expired; changed service state; backup available | `job_rolling_back` | Save stopped target; restore/reload/probe under rollback timeout |
| `J` | ticket.deadline | Deadline expired; changed service state; backup unavailable | `job_rollback_failed` | Cancel/reap; alert |
| `job_rolling_back` | ticket.deadline | Deadline expired | `job_rolling_back` | Save stopped target; finish bounded rollback |
| `quiescing` | ticket.deadline | Deadline expired | `quiescing` | Save stopped target; finish bounded cancellation |
| `W` | recovery.observed | Known live supervised child or verified receipt | Same from-state | Adopt or replay receipt event; never reset deadlines/rounds |
| `R` | recovery.observed | Dead child; no exit receipt; safe effect state established | Same from-state | Emit run.failed with died reason; apply retry rows |
| `S` | effect.observed | Matching pending effect ID; verified receipt | Same from-state | Save receipt; active phases emit typed result event; terminal/hold phases retain cleanup receipts |
| `S` | lease.release_requested | Terminal/hold outcome; leased slot; child exit and required rollback receipts valid | Same from-state | Release slot; never release a live/unknown child |
| `W` | result.unsafe | Secret/unsafe result rejected before persistence; child/effects require reconciliation | `needs_decision` | Store sanitized reason only; cancel known child; retain slot until safe |
| `S` | command.invalid / decision.invalid | Invalid input or missing authority | Same from-state | Reject request; no external effect |
| `S` | event.duplicate | Already observed effect/event ID | Same from-state | Deduplicate; no repeat |
| `S` | observation.recorded | Allowlisted progress/usage/heartbeat/notification/warning/start-intent | Same from-state | Store sanitized evidence only; grant no authority |
| `S` | resume.requested | Terminal state | Same from-state | Reject; require new explicitly authorized workflow ID |
| `needs_decision` | decision.recorded | Authorized non-waiver blocker resolution | `needs_decision` | Store resolution/exemption; resume still required |
| `needs_decision` | decision.recorded | Waiver declined | `needs_decision` | Save refusal; no closer/approval |
| `scheduler_recovering` | recovery.complete | Ownership/replay valid; uncertain tickets held; live handles reconciled | `scheduler_watching` | Resume monitor and admission |
| `scheduler_recovering` | recovery.failed | Ownership/storage/global schema failure | `scheduler_failed` | No dispatch; report failure |
| `scheduler_watching` | scheduler.tick / queue.added | Owner valid | `scheduler_watching` | Monitor limits; admit eligible FIFO work under caps; empty queue waits |
| `scheduler_watching` | shutdown.requested | Explicit scheduler shutdown | `scheduler_stopping` | Refuse admission; continue monitor/receipts for admitted work |
| `scheduler_stopping` | scheduler.tick | Active workflows/children remain | `scheduler_stopping` | Continue monitoring to terminal/hold; no admission |
| `scheduler_stopping` | scheduler.tick | No active workflows/children; receipts durable | `scheduler_stopped` | Save runner.finished; release ownership |
| `scheduler_recovering`, `scheduler_watching`, `scheduler_stopping` | storage.failed | Journal cannot be safely written | `scheduler_failed` | Stop dispatch; supervisors retain child deadlines; this failure may exist only in the process result |
| `W` | storage.failed | One-shot owner; journal cannot be safely written | `failed` | Report nondurable failure/exit 1; no new effect; recovery retains last durable state and supervised deadlines |

Initial states are `queued` (new workflow, validated continuation) and `scheduler_recovering` (new scheduler owner). There is no transition out of a terminal outcome into active work. Duplicate queue requests normalize to `event.duplicate`; invalid commands/decisions to their table events; allowlisted lifecycle observations to `observation.recorded`. A known dead child with a result receipt replays that result event; an unknown process/effect uses `effect.uncertain`. Slash-separated events/values and saved-target destinations expand into separate guarded rows; “Same from-state” is a self-transition, not an extra state.

Each external effect follows **intent → action → observed receipt**. On every owner start, replay, validate process identities/deadlines and reconcile pending IDs before admission. A lost merge response remains `awaiting_merge` until readback proves completion or absence; a lost approval response uses `effect.uncertain` if reconciliation cannot establish the actor/result. No automatic repeat of an uncertain non-idempotent effect. Exactly-once external execution is not assumed; missing evidence never means success.

### 5.2 Events and notification delivery

State-changing events and their guards are defined exclusively by §5.1. Adapters normalize `run.died`, `run.stalled` and `run.timed_out` to `run.failed` with a reason. Lifecycle/observational events additionally include `effect.planned`, `run.start_requested`, `run.progress`, `runner.started`, `runner.heartbeat`, `runner.finished`, `policy.warning` and notification receipts. `job.finished` describes a run, while the persisted workflow state describes its outcome.

Events contain evidence references and reason codes, not raw prompts/output or secret configuration. Render status from events; never parse status text back into state. Notifications use a durable consumer cursor and delivery ID: at-least-once delivery, deduplication where supported, bounded retries and visible terminal failure. An offline notification sink must not lose the ticket's decision state.

### 5.3 Results

Record duration, rounds, gate failures, review findings, outcome and optional token/cost usage per attempt/profile. Unknown cost is “unavailable,” not zero. Results and the future UI consume journal-derived records. A ticket owns attempts; attempts own disposable sessions and verification/review evidence. A worker note carries assumptions and next steps without becoming a second database.

## 6. Scheduler and monitor

The **queue scheduler is persistent**: it watches the durable queue, admits work as slots free and waits when empty. Tickets added later need no restart. Individual worker/reviewer/job processes and one-shot workflow invocations start for assigned work and exit at their outcome; none is a per-run daemon. This supersedes the earlier drain-to-exit scheduler decision without changing per-run lifetime. Service/boot/restart policy remains a §12 decision, not an installed service.

The queue stores ticket, repository, pipeline, lane and validated overrides. Read dependencies from td; enqueue leaf tickets, not planning parents. One execution ownership lock prevents competing schedulers/one-shot executors. Short journal-write locks let commands append requests. With a scheduler active, one-shot commands submit and wait for their workflow instead of becoming another executor; a second scheduler returns busy.

Global and per-lane caps apply; `corylus` has cap **1**. Workers, reviewers and internal closers run sequentially in that ticket's slot; a closer never queues behind itself. Terminal outcomes and holds release slots only after child exit/receipts and necessary rollback. Resume reacquires a slot. Use eligible FIFO in lanes and round-robin across lanes. Dependency holds remain visible; other eligible work continues.

Each bounded tick checks identity, launch/wall/idle deadlines, persisted ticket deadlines and controls. Retry only a reconciled safe run under the explicit budgets in §8.2; uncertainty enters `needs_decision`. Pause quiesces active work, saves its continuation and prevents admission; stop cancels it. Service effects must be restored before either control completes. Notifications use durable cursors and bounded delivery retries; failures are visible but do not stop admission.

Explicit scheduler shutdown stops admission, monitors admitted workflows to terminal/hold, records `runner.finished` and exits. Empty or dependency-blocked queues do **not** shut it down. Scheduler crash stops new effects; surviving per-run supervisors keep deadlines and receipts. Every restart recovers before admission (§5.1). Manual completion expects no merge event and is never reported as a dead run.

## 7. Command line

```text
corylus-run config check | config show
corylus-run scheduler [--lane L] | scheduler stop
corylus-run run TICKET [--pipeline P] [--worker PROFILE] [--reviewer PROFILE]
corylus-run review TICKET [--reviewer PROFILE]
corylus-run decision TICKET --file FILE
corylus-run resume TICKET --note-file FILE
corylus-run job TICKET --profile P --prompt-file FILE [--authorization REF]
corylus-run stop TICKET | pause TICKET
corylus-run queue add TICKET --lane L | queue list
corylus-run status [TICKET]
corylus-run results [--by profile|pipeline|lane]
```

`scheduler` recovers and watches until explicit shutdown or fatal owner failure. `run`, `review`, `resume` and `job` recover/drive one workflow, or submit to the active scheduler and wait, then exit at a terminal/hold outcome. `review` requires existing work with valid gates at the pinned head. `resume` queues a validated saved continuation under the tables' guards. Queue/control commands persist requests and return after acknowledgment; `queue add` alone starts no executor. Status/results need no active scheduler.

| Exit | Exact state mapping for workflow/scheduler commands |
|---|---|
| 0 | `done`, `job_succeeded`, `finished_awaiting_human`, `scheduler_stopped` |
| 1 | `failed`, `round_exhausted`, `job_failed`, `job_rolled_back`, `job_rollback_failed`, `scheduler_failed` |
| 2 | `awaiting_acceptance`, `needs_decision`, `dependency_blocked`, `paused`, `awaiting_merge`, `stopped`, `acceptance_declined` |

Read-only/control/config commands return 0 for successful validation/read/acknowledgment, 1 for local/API failure, 2 for busy ownership or invalid/unauthorized requests; they do not manufacture a terminal workflow state. A persistent scheduler has no exit code while watching. Notification failures appear separately in status/evidence and do not change a successful workflow's code.

Decision files record acceptance, manual merge authority, check exemptions or scoped waivers. Missing authority is rejected; a resume note grants none. Job authorization remains optional syntax checked against the still-undecided policy (§12). Standalone jobs inherit `pipeline.default` run-limit/retry keys; loop roles and merge settings do not apply. No flags bypass independence, gates or reconciliation. Every published PR body/comment identifies its AI author; adapters enforce this and the finish gate checks worker publication evidence.

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

The limits below are **proposals for separate decisions in §12**. Profile overrides win over harness limits, which win over `[limits]`; every effective harness limit must be positive, including Codex. Zero disables only the optional ticket deadline. Retry counters are per attempt/stage, not per scheduler restart.

```toml
[limits]
max_wall_seconds = 5400
idle_timeout_seconds = 1200
launch_timeout_seconds = 30
cancel_grace_seconds = 15
rollback_timeout_seconds = 300

[harness.generic]
command = ["example-agent", "run", "--model", "{model}"]
resume = ["example-agent", "resume", "{session_id}"]
prompt = "stdin"
session = { from = "output_json", field = "session_id" }
final = { from = "output_json", field = "final_message" }
billing = "metered"

# Illustrative adapter contract; validate actual CLI/session formats in its build slice.
[harness.codex]
command = ["codex", "exec", "--model", "{model}"]
prompt = "stdin"
max_wall_seconds = 5400
idle_timeout_seconds = 1200
launch_timeout_seconds = 30

[profile.codex]
harness = "codex"
model = "example-codex-model"
roles = ["worker", "reviewer"]

[profile.builder]
harness = "generic"
model = "example-small-model"
roles = ["worker", "reviewer"]
max_wall_seconds = 5400
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
round_accounting = "confirmed_worker_start"
finish_nudges = 1
launch_retries = 1
run_failure_retries = 0
ticket_deadline_seconds = 0
gates = ["finish", "checks"]
independence = "session"
human_acceptance = false
merge = "automatic"

[pipeline.design]
worker = "builder"
reviewer = "reviewer"
max_rounds = 2
round_accounting = "confirmed_worker_start"
finish_nudges = 1
launch_retries = 1
run_failure_retries = 0
ticket_deadline_seconds = 0
gates = ["finish", "checks"]
independence = "session"
human_acceptance = true
merge = "manual"

[scheduler]
global_cap = 1
poll_interval_seconds = 5
# Deployment metadata proposals; config check must not install/enable services.
service = "user"
start_at_boot = false
restart = "on-failure"
restart_delay_seconds = 5

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
- Crash before/after every effect; recovery on scheduler/one-shot start; snapshot replay; duplicate queue/resume; no duplicate launch, approval or merge. Surviving children keep their deadlines and are adopted; orphan supervisors enforce limits without the runner.
- Creator/worker approval refusal, actual reviewer-context approval, same-model warning, accepted waiver → independent closer, and unauthorized waiver refusal.
- Lane cap 1, other lanes, slot recovery, held tickets and internal closer without deadlock. Persistent scheduler fills slots without the orchestrator, stays alive when empty/blocked, admits later arrivals without restart and shuts down only on request/fatal failure.
- Manual lane ends at independent approval with no merge event: persist `finished_awaiting_human`, release the slot and exit the one-shot invocation while the scheduler watches; the monitor never emits false `run.died`. Resume revalidates the accepted SHA. Default automatic pipeline readies a permitted draft and merges only that SHA.
- Draft handling, delayed PR discovery, forge errors, atomic SHA guard and lost merge response.
- Notification outage/retry, sanitization before persistence, judgment unavailable/malformed output and unchanged deterministic gates.
- Authorized service job: backup, reload, service-user verification; job failure, successful/failed rollback, stop/pause/deadline during changed service state; unknown effects never repeat.
- Every §5.1 expanded transition and exit mapping; launch/nudge/run-retry exhaustion, timed-out/crashed round accounting, human acceptance decline, blocked draft and policy holds.

Run targeted Python unit tests and Ruff; end-to-end fakes run in CI. Install from a reviewed known commit/tag, preserving executable permissions. No edits to a running release. Scheduler/recovery probes must show start events, working monitor/notification delivery, empty-queue survival and admission after later enqueue. Kill/restart the scheduler during a stub run and verify supervised deadlines and reconciliation before admission; verify one-shot terminal exits and graceful scheduler shutdown. Installation policy awaits §12 approval.

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
| 14. Single-ticket engine | `runner/engine.py`: pure transitions emitting effect requests | Expanded §5.1 transition matrix, budgets/round accounting, holds; automatic merge and manual `finished_awaiting_human` with no merge event; no success on missing receipt | Codex; 1, 8, 13 |
| 15. Effect driver/recovery | `runner/driver.py`: execute/reconcile engine effects | Stub full workflow; recovery on start around launch/approval/merge; adopt supervised children without resetting deadlines; no duplicate effects | Codex; 3, 5, 7, 10–14 |
| 16. Monitor | `runner/monitor.py`: tick/deadline/cancel decisions | Fake clock death, PID reuse, log-only activity, all harness idle/wall/launch and optional ticket deadlines; manual completion never reported dead | Codex; 3, 6, 7 |
| 17. Queue/lanes | `runner/scheduler.py`: durable enqueue/admission/leases | Corylus cap 1, global/profile caps, FIFO/fairness, dependency holds, slot recovery | Cheap; 2, 3 |
| 18. Persistent scheduler / one-shot driver | `runner/invocation.py`: ownership, recover-on-start, persistent queue watch, monitor ticks, graceful shutdown and one-shot waiting; injectable job executor | Orchestrator disconnect, crash/restart before admission, empty/blocked queue stays alive, later arrivals admitted without restart, one-shot exit, concurrent commands, hold release, manual completion, closer slot reuse | Codex; 15–17 |
| 19. Jobs/closer | `runner/jobs.py`: bounded jobs with configurable authorization and independent closer | Same-ticket waiver continuation + eligible closer approval; chosen job-policy authorization; job_succeeded/job_failed states; uncertain effect needs_decision | Codex; 7, 10, 13, 15, 18 |
| 20. CLI | `runner/cli.py`: §7 commands | Argument validation, sanitized config/status, lease-safe enqueue, scheduler watch/stop, busy owner, exact state/exit mapping, review-only, decisions and jobs | Cheap; 2, 3, 18, 19 |
| 21. Notifications/results | `runner/notify.py`, `runner/results.py`: cursor delivery and reports | Outage/retry/dedup, visible delivery failure, unavailable cost, deterministic replay reports | Cheap; 3, 18 |
| 22. Service-job gate | `runner/service_gate.py`: runbook effect receipts and service-user probe | Fake backup/change/reload/verify; failed/canceled/deadline-expired work restores/reloads; named rollback outcomes; failed rollback alerts | Codex; 12, 19 |
| 23. Optional judgment | `runner/judgment.py`: fixed packets behind Gate, disabled by default | Sanitization, bounded call, bad schema, unavailable, flag pauses, never grants approval | Cheap; 2, 12, 16 |
| 24. Release/regression suite | `tests/runner/test_e2e.py`, `.github/workflows/runner.yml`; release notes in `docs/runner-release.md` | §9 matrix, targeted/unit CI and Ruff; installed executable/start/recovery/later-enqueue/shutdown probes; approved user-service restart/boot policy | Codex; 1–23 |

Lean model/proofs in `td-e81ba4` follow this design review and feed step 14’s transition tests; they are not implemented here. §12 decisions must be resolved before their consuming slices. Step 24 has three files because CI and the release runbook accompany the integration suite; it implements no new runtime behavior. UI consumption is a later design/build slice, preserving existing workflows. Approval of this proposal is not approval to start all tickets unattended.

## 12. Decisions for Julian

**Decide these individually.** Values in §8.2 illustrate recommendations, not an accepted bundle. Queue persistence is now decided; how it is hosted and the run limits remain open. Job authorization must be settled before its policy slice; no token default has been selected.

| Decision | Config key / recommended default | Reason / alternative |
|---|---|---|
| A. Each harness's wall-clock limit, including Codex | `harness.<name>.max_wall_seconds` = **5400**; `[limits]` fallback, `profile.<name>` override | 90 minutes bounds a stuck run while allowing substantial work. Decide each installed harness separately; tune from measured runs, never omit Codex. |
| B. Each harness's idle limit, including Codex | `harness.<name>.idle_timeout_seconds` = **1200**; same inheritance | 20 minutes tolerates slow tools but bounds lack of useful progress. Adapter progress must distinguish useful work from log noise. |
| C. Round cap | `pipeline.<name>.max_rounds` = **2** | Initial build/review plus one remediation; a larger cap increases unattended repetition. |
| D. Does timeout/crash consume a round? | `pipeline.<name>.round_accounting` = **"confirmed_worker_start"** (yes, including timeout/crash) | Work already occurred. Reviewer failure consumes no extra worker round; launch failure before confirmed start and nudges do not. Recovery counts each start once. Alternative: count only completed workers; this needs revised retry semantics before implementation. Agree/change this rule independently of cap C. |
| E. Finish/check nudge budget | `pipeline.<name>.finish_nudges` = **1** | One bounded chance to commit/push/fix checks; shared across finish/check gates per attempt. Zero stops immediately. |
| F. Launch retry budget | `pipeline.<name>.launch_retries` = **1**; `harness.<name>.launch_timeout_seconds` = **30** | Retry once only after proving no child/effect exists. Unknown launch requires a decision. Launch attempts do not consume rounds until start is confirmed. |
| G. Timeout/crash retry budget | `pipeline.<name>.run_failure_retries` = **0** (allowed 0–1) | Stop with evidence by default. Opt-in one safe reconciled retry; worker retry consumes a new round, reviewer/job retry uses this separate budget. Never repeat uncertain live effects. |
| H. Optional per-ticket deadline | `pipeline.<name>.ticket_deadline_seconds` = **0** (disabled) | Long tasks/holds need no artificial ticket lifetime initially. If enabled, starts at first admission; includes holds/retries, survives restart, and cancels/rolls back at expiry. No spend cap. |
| I. Persistent scheduler hosting | `scheduler.service` = **"user"** | Recommend a supervised user service under one execution account; shell foreground mode remains available. No per-job daemon; service installation is separate work. |
| J. Start scheduler at boot? | `scheduler.start_at_boot` = **false** | Preserve earlier no-boot preference unless Julian changes it. User service persistence after logout requires an explicit account/session-lifetime choice; no implicit linger or boot enablement. |
| K. Restart scheduler after crash? | `scheduler.restart` = **"on-failure"**, `restart_delay_seconds` = **5** | Recover-before-admission permits unattended recovery; restart never resets child deadlines. Explicit clean shutdown stays stopped. Service manager must rate-limit crash loops. |
| Cancellation / restoration bounds | `limits.cancel_grace_seconds` = **15**, `rollback_timeout_seconds` = **300** | Short grace before kill; separate five-minute restoration budget remains active after a ticket deadline. Expired/failed rollback alerts. |
| Job authorization | **Open:** options below; no chosen `allow_jobs` authority default | Choose capability/note/token policy before job-policy implementation. Closer evidence/eligibility and service-change authorization remain mandatory. |
| Merge policy | **Decided:** `pipeline.<name>.merge` = **"automatic"** | Independent approval, exact reviewed SHA and atomic forge guard. Design pipeline: human acceptance plus manual merge; no merge authorized by this ticket. |
| UI warnings / optional judgment | Same-model warning; `gate.judgment.enabled` = **false** | Preserve chosen UI; show reason/next action with folded evidence. Advisory flags require inspection; unavailable optional judgment retains deterministic checks. |

| Job authorization option | Trade-off |
|---|---|
| Config allowance only | Least friction for recurring jobs; config grants bounded capabilities. Needs narrow job-kind/effect allowlists and clear audit records; a mistaken allowance can authorize repeated effects. |
| Allowance plus ticket-scoped note | Config permits the capability; a durable note approves the ticket's specific work. More context and accountability without per-run tokens; define expiry/reuse when resuming or retrying. |
| Per-run token | Explicit authorization for each execution, with narrow scope/expiry. More ceremony and token lifecycle/recovery work; slows unattended queues. This is an option, not a required default. |

### 12.1 Future work

Per-ticket spend caps are **deferred**, not part of initial runner configuration or build acceptance. Built-in run limits are hard wall-clock and idle timeouts, with launch deadlines for start failures. Provider and gateway budgets remain external. Optional usage/cost reporting is observational and labels unavailable metering. A future cap proposal must define enforcement with missing/delayed usage; it does not block this design or its initial build plan.
