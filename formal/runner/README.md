# Runner state-machine model

Written by an AI agent (Codex (GPT-6.1 Sol)).

This Lake project checks the runner proposal in [runner-design.md](../../docs/runner-design.md), especially its state and transition tables in §5.1. It is a specification model for `td-e81ba4`, not an implementation of the runner. Its source branch stacks on the design revision in PR #6.

## Build

Install elan for your user, then run from this directory:

```sh
lake build
python3 check_mapping.py
```

The repository also exposes `make formal`. The checked-in `lean-toolchain` pins Lean 4. The project uses Lean's bundled libraries; it does not depend on Mathlib. Executable examples print state sequences during the build.

| File | Purpose |
|---|---|
| `Runner/Model.lean` | Vocabulary, configuration, state and total transition function |
| `Runner/Proofs.lean` | Universally quantified invariants and finite-trace results |
| `Runner/Safety.lean` | Independent approval identities and exact-head merge guards |
| `Runner/Progress.lean` | Terminal reachability, safe explicit-stop progress and standalone-job merge exclusion |
| `Runner/Traces.lean` | Executable happy paths, holds, failures and design counterexamples |
| `Runner.lean` | Build entry point importing the model, proofs and traces |
| `rows.tsv` | Numbered §5.1 source rows and expanded phase/event/target vocabulary |
| `check_mapping.py` | Checks 32 phases, 53 events, 129 exact source rows and model row references against the design |

The source checker compares the state/event vocabulary and each numbered row's from-state, event, guard and target with the design. It also checks that every source row is referenced in the implementation. This is a drift check, not a second proof that an implementation comment has the right semantics.

## Scope and evidence

The model represents workflow and scheduler phases, normalized events, transition guards, bounded counters, queue and pause continuations, control targets, merge policy, reviewed/head identity, and reviewer/worker/creator eligibility. A total transition function rejects an event whose phase or guards are inapplicable by leaving the state unchanged. Each transition implementation points back to §5.1.

The harness, forge, tracker, filesystem, journal, supervisor, network, clock, and service runbooks remain abstract. Guard facts stand for their validated evidence; a successful guard is not evidence that a real adapter can obtain it. The model does not parse raw verdict text, execute processes, authorize real changes, approve td tickets, or merge PRs. It reasons about normalized verdict classifications and abstract receipts, not about the correctness of their parsers or adapters.

`Config` supplies limits, workflow mode, merge/acceptance policy, and configured session identities. Its constructor defaults include synthetic example values `maxRounds := 3` and `runRetries := 1`. Julian's accepted runtime defaults are `max_rounds = 2` and `run_failure_retries = 0`. Proofs quantify over `Config`; this model selects no runtime configuration. Session references and SHAs are opaque natural-number labels used only for equality. Eligibility flags stand for the remaining full identity/history checks in §3.3. `State` carries the current head/review/waiver/approval facts and durable counters. `Event.facts` supplies normalized guard evidence for the current event; its default values are synthetic examples, not trusted runtime defaults. No constructor contains production identifiers or secret data.

`step : Config → State → Event → State` returns a state rather than executing effects. An abstract `mergeRequests` counter distinguishes valid `pr.ready`/`merge.requested` merge intents from rejected requests, even though both retain the `merging` phase. The model checks those intents and the merged receipt (`pr.merged → done`). It cannot establish that a real forge call is issued exactly once or uses an atomic expected-SHA guard. Those require the effect-driver and adapter tests in §9 and §11.

Timeout and recovery events stand for already observed deadline/receipt facts. There is no continuous clock or scheduling fairness assumption. An existential progress result says that a suitable finite event sequence reaches a terminal outcome; it does not claim that every sequence terminates. Invalid events, observation events, optional judgment, empty scheduler ticks, and holds can otherwise stutter indefinitely.

The universal `canTerminate` theorem uses `storage.failed` as its witness. The table permits a fatal owner outcome from every nonterminal workflow/scheduler phase, including states with unknown process or service safety. This outcome may be nondurable and does not prove cleanup, rollback, lease release, successful work, or a usable continuation. Separately, `healthyStopTerminates` proves `stop.requested → cancel.verified → stopped` when the child is already absent, service state is unchanged, and effects are resolved; an in-progress rollback is excluded.

The design distinguishes an invocation-ending hold from a terminal workflow. In particular, `finished_awaiting_human` is a resumable hold even though its one-shot exit code is zero. `queued`, `needs_decision`, and `paused` are not terminal outcomes. A manual merge requires a separately recorded authorization before resume. A resume note itself supplies no authority.

The model's terminal-absorption claim concerns the phase. The design permits `effect.observed`, `lease.release_requested`, and `observation.recorded` in every phase, including terminal phases. A concrete runtime may therefore add cleanup receipts, release a safe lease, or append sanitized evidence without changing a terminal phase. Absorption must not be interpreted as forbidding those changes to a full persisted record.

Verified matching recovery receipts can also record an absent child, changed/restored service state, or backup evidence while a workflow is held. These observations update evidence, not effects or authority; a resume still checks the hold's safety and continuation guards.

The design document describes the §8.2 values and §12 recommendations as proposals. Julian's 2026-10-08 decision on `td-3830f9` accepts the recommended defaults A–K and job authorization option 2: config allowance plus a ticket-scoped note, with configuration where meaningful. This recorded acceptance supersedes the document's pending-decision wording for those choices. Quantified results remain conditional on the modeled configuration and validated starting state; this project implements no runner runtime or job authorization policy.

The budget invariant includes an available next round when a worker attempt has not yet started. Its initialization theorem requires a positive round cap; arbitrary hand-constructed states can violate counters and are not covered by that invariant. The standalone-job invariant additionally restricts queued continuations and saved pause/control origins to the job lane. It is proved from `initial` and preserved by normalized events, rather than assumed for arbitrary state records.

## Design findings

These requested claims conflict with the design as written. They are retained as counterexamples rather than silently replaced with stronger guards:

| Requested claim | Design trace or limitation | Relevant sections |
|---|---|---|
| Merge only under automatic policy | A manual approval reaches `finished_awaiting_human`; recorded manual merge authority permits `resume.requested → queued → merging → done`. | §3.3, §5.1 manual tracker approval, manual resume, merge admission and `pr.merged` rows |
| REJECT or malformed verdict requires a later APPROVE before any merge | Malformed output reaches terminal `failed`. A REJECT can be followed by NEEDS-DECISION, an accepted scoped waiver, and independent closer approval; that authorized path can merge without a later reviewer APPROVE. | §3.3 waiver flow; §5.1 rejection, decision, closer completion and tracker approval rows |
| A configured measure bounds every worker launch per ticket | §5.1 bounds first confirmed starts of worker attempts. Nudges and retries have explicit budgets, but pause/resume can request a same-attempt worker continuation and §3.1 permits a fresh harness session when resume is unavailable. No separate budget is stated for those resumed launches. | §3.1, §4.1, §5.1 pause continuations and round accounting; §12 C–G |
| Terminal states never change any persisted data | The `S` observation and lease rows preserve the phase while recording receipts or releasing a safe slot. | §5.1 `effect.observed`, `lease.release_requested`, `observation.recorded` |

An independent closer is job mode, but it participates in the same ticket's acceptance workflow. The guarantee that jobs cannot merge applies to a standalone job workflow. Applying it to every workflow that invokes a closer would contradict the explicit waiver lane.

`Runner/Traces.lean` makes these counterexamples executable: `authorizedManualMerge`, `rejectThenWaiver`, and `repeatedPauseResumes`. The last supports the quantified theorem `worker_launches_unbounded`: for any proposed finite launch bound there is a reachable trace with more launches, one consumed round, and no consumed nudge/run-retry budget. This is a refutation of a total launch bound, not merely one over-budget example.

## Name mapping

The source tables are authoritative for names. Lean constructors retain their spelling with case conversion only; aliases such as `W`, `R`, and `S` denote finite sets and are not extra phases. Slash-separated events expand to separate events; “Same from-state” is a self-transition, not a phase.

`Phase` maps as follows. Names without a separator are unchanged.

| Doc state | `Phase` constructor |
|---|---|
| `queued` | `queued` |
| `building` | `building` |
| `gating` | `gating` |
| `reviewing` | `reviewing` |
| `awaiting_acceptance` | `awaitingAcceptance` |
| `approving` | `approving` |
| `merging` | `merging` |
| `job_authorizing` | `jobAuthorizing` |
| `job_running` | `jobRunning` |
| `job_verifying` | `jobVerifying` |
| `job_rolling_back` | `jobRollingBack` |
| `closer_running` | `closerRunning` |
| `quiescing` | `quiescing` |
| `done` | `done` |
| `job_succeeded` | `jobSucceeded` |
| `finished_awaiting_human` | `finishedAwaitingHuman` |
| `needs_decision` | `needsDecision` |
| `dependency_blocked` | `dependencyBlocked` |
| `paused` | `paused` |
| `awaiting_merge` | `awaitingMerge` |
| `failed` | `failed` |
| `stopped` | `stopped` |
| `round_exhausted` | `roundExhausted` |
| `acceptance_declined` | `acceptanceDeclined` |
| `job_failed` | `jobFailed` |
| `job_rolled_back` | `jobRolledBack` |
| `job_rollback_failed` | `jobRollbackFailed` |
| `scheduler_recovering` | `schedulerRecovering` |
| `scheduler_watching` | `schedulerWatching` |
| `scheduler_stopping` | `schedulerStopping` |
| `scheduler_stopped` | `schedulerStopped` |
| `scheduler_failed` | `schedulerFailed` |

`EventKind` removes each dot or underscore and capitalizes the following word. This is a one-to-one mapping of all §5.1 event names; for example, `run.launch_failed → runLaunchFailed`, `lease.release_requested → leaseReleaseRequested`, and `event.duplicate → eventDuplicate`. The complete mapping is:

| Doc event | `EventKind` constructor |
|---|---|
| `admission.checked` | `admissionChecked` |
| `dependency.satisfied` | `dependencySatisfied` |
| `workspace.failed` | `workspaceFailed` |
| `workspace.uncertain` | `workspaceUncertain` |
| `run.started` | `runStarted` |
| `identity.refused` | `identityRefused` |
| `run.launch_failed` | `runLaunchFailed` |
| `effect.uncertain` | `effectUncertain` |
| `run.finished` | `runFinished` |
| `run.failed` | `runFailed` |
| `gate.passed` | `gatePassed` |
| `gate.failed` | `gateFailed` |
| `gate.error` | `gateError` |
| `checks.absent` | `checksAbsent` |
| `judgment.unavailable` | `judgmentUnavailable` |
| `judgment.result` | `judgmentResult` |
| `review.verdict` | `reviewVerdict` |
| `head.changed` | `headChanged` |
| `decision.recorded` | `decisionRecorded` |
| `acceptance.ready` | `acceptanceReady` |
| `job.finished` | `jobFinished` |
| `tracker.approved` | `trackerApproved` |
| `tracker.failed` | `trackerFailed` |
| `merge.blocked` | `mergeBlocked` |
| `merge.unsupported` | `mergeUnsupported` |
| `pr.ready` | `prReady` |
| `merge.requested` | `mergeRequested` |
| `pr.merged` | `prMerged` |
| `resume.requested` | `resumeRequested` |
| `authorization.checked` | `authorizationChecked` |
| `job.failed` | `jobFailed` |
| `job.verified` | `jobVerified` |
| `rollback.verified` | `rollbackVerified` |
| `rollback.failed` | `rollbackFailed` |
| `stop.requested` | `stopRequested` |
| `pause.requested` | `pauseRequested` |
| `cancel.verified` | `cancelVerified` |
| `cancel.failed` | `cancelFailed` |
| `ticket.deadline` | `ticketDeadline` |
| `recovery.observed` | `recoveryObserved` |
| `effect.observed` | `effectObserved` |
| `lease.release_requested` | `leaseReleaseRequested` |
| `result.unsafe` | `resultUnsafe` |
| `command.invalid` | `commandInvalid` |
| `decision.invalid` | `decisionInvalid` |
| `event.duplicate` | `eventDuplicate` |
| `observation.recorded` | `observationRecorded` |
| `recovery.complete` | `recoveryComplete` |
| `recovery.failed` | `recoveryFailed` |
| `scheduler.tick` | `schedulerTick` |
| `queue.added` | `queueAdded` |
| `shutdown.requested` | `shutdownRequested` |
| `storage.failed` | `storageFailed` |

`Verdict.approve`, `Verdict.reject`, and `Verdict.needsDecision` map to `APPROVE`, `REJECT`, and `NEEDS-DECISION`. `Verdict.malformed` classifies invalid review output, not an additional successful verdict. `Judgment.continueRun` maps to `continue`; its suffix avoids a Lean keyword. The remaining judgment values use the same snake-to-camel conversion. Queue `Continuation.savedPhase` maps to `saved_phase`; other continuation and merge-policy names are unchanged.

| Doc finite alias | Lean predicate |
|---|---|
| `W` | `workflow` |
| `R` | `running` |
| `B` | `buildReviewCloser` |
| `J` | `serviceJob` |
| `H` | `blockerHold` |
| `I` | `identityPhase` |
| `A` | `active` |
| `P` | `hold` |
| `S` | All constructors of `Phase` |

## Theorem index

Row IDs below number the 129 source rows in order, as recorded in `rows.tsv` and model comments. The expanded aliases retain those source-row IDs.

| Theorem | Claim and assumptions | Doc sections and source rows |
|---|---|---|
| `terminalPhase_rowStep` | Dispatch preserves a terminal phase for every event; cleanup data may change. | §5.1 terminal vocabulary; R113–R119 universal observation/cleanup/invalid/resume rows |
| `terminalPhase_absorbing` | The total `step`, including schema/current/duplicate filtering, preserves a terminal phase. | §5.1 transition semantics and R113–R119 |
| `terminalPhase_trace` | Every finite event sequence preserves an initially terminal phase. | §5.1 terminal-resume prohibition, R119; derived from one-step absorption |
| `invalid_event_unchanged` | Invalid schema, stale run/effect identity and duplicate receipt events leave the entire state unchanged. | §5.1 transition semantics; R117 |
| `initial_withinLimits` | Initialization satisfies the counter/reserved-round invariant when `maxRounds` is positive. | §5.1 initial-state and round-accounting prose; §8.2 limits |
| `budgets_rowStep` | Table dispatch preserves valid round/nudge/launch-retry/run-retry counters and the reserved next round. | §5.1 R004–R005, R014–R015, R021–R023, R027–R029, R032–R034, R044–R045, R086–R087; holds/recovery retain budgets |
| `budgets_preserved` | Event filtering and table dispatch preserve the budget invariant. | §5.1 transition semantics and the counter rows above |
| `budgets_trace` | Every finite trace preserves an initially valid budget invariant. | §5.1 counter accounting; derived from one-step preservation |
| `initial_trace_budgets` | Every finite trace from initialization respects a positive round cap and per-attempt/stage nudge/retry caps. | §5.1 accounting; §8.2 retry/nudge limits; §12 C–G |
| `workerRound_measure` | A newly consumed worker round strictly decreases remaining round capacity. This bounds attempts, not every process launch. | §5.1 R014–R015 and confirmed-worker-start accounting; §12 D |
| `malformed_never_merges` | A malformed normalized review verdict reaches `failed` and every subsequent finite trace stays there. | §3.2; §5.1 R043 and terminal semantics |
| `reviewer_identity_distinct` | Eligible reviewer differs from the configured worker and creator sessions. | §3.3 identity boundary |
| `closer_identity_distinct` | Eligible independent closer differs from worker and creator sessions. | §3.3 waiver/closer boundary |
| `reviewer_approval_identity` | A review event actually entering approval/acceptance has a valid APPROVE and an independent reviewer. | §3.2–3.3; §5.1 R047–R048 |
| `tracker_approval_identity` | A newly acquired tracker approval-session receipt uses an independent actor. | §3.3; §5.1 R060–R061 |
| `closer_approval_identity` | A newly acquired closer approval-session receipt uses an independent closer. | §3.3 waiver flow; §5.1 R058 |
| `tracker_approval_acquisition` | Changing tracker approval from false to true requires an independent actor. | §3.3; §5.1 R060–R061 |
| `closer_approval_acquisition` | Changing closer approval from false to true requires an independent closer. | §3.3 waiver flow; §5.1 R058 |
| `initial_approvalInvariant` | Initialization has no approval and satisfies the independent exact-head approval invariant. | §5.1 initial states |
| `approvalInvariant_rowStep` | Every table row preserves an independent recorded actor and exact current SHA whenever approval is present. | §3.3–4.3; §5.1 R049–R050, R058, R060–R061, R113; complete transition matrix |
| `approvalInvariant_step` | Schema/current/duplicate filtering preserves the approval invariant too. | §5.1 transition semantics; R117 |
| `approvalInvariant_run` | Every finite event sequence preserves an initially valid approval invariant. | §3.3–4.3; derived from one-step preservation |
| `reachable_approval_independent_exact` | Every reachable approved state records an actor distinct from worker/creator and review for its current head. | §3.3–4.3; §5.1 R058, R060–R061 and head invalidation |
| `merge_ready_guard` | A `pr.ready` merge intent requires approval, exact reviewed/current head and valid readiness/checks. | §4.3; §5.1 R065 |
| `merge_requested_guard` | An already-ready merge intent requires the same approval/head/check guards. | §4.3; §5.1 R066 |
| `merged_receipt_guard` | A new `done` outcome requires the expected merged receipt and approval for its exact head. | §4.3; §5.1 R067 |
| `canTerminate` | Every nonterminal raw state has a finite event sequence reaching a terminal phase; the witness is a fatal storage outcome, not successful completion. | §5.1 R128–R129 storage failure; terminal vocabulary |
| `healthyStopTerminates` | With absent child, unchanged service and no unresolved effect, stop plus a valid cancellation receipt reaches `stopped`; excludes in-progress rollback. | §5.1 R095, R097, R099, R101; §6 controls |
| `initial_jobInvariant` | A standalone job starts with a job continuation, job return origin and no approval/merge authority. | §3.4; §5.1 initial states and R009 |
| `jobInvariant_rowStep` | Table dispatch preserves standalone job phases, continuations, control origins and absence of approval/merge authority. | §5.1 R009–R010, R080–R094, R095–R114, R120–R121, R129; all other event rows must preserve the invariant |
| `jobInvariant_step` | Schema/current/duplicate filtering also preserves the standalone-job invariant. | §5.1 transition semantics; R117 |
| `jobInvariant_run` | The standalone-job invariant holds over every finite normalized event sequence. | §3.4; derived from the complete one-step transition matrix |
| `standaloneJob_never_merges` | Every standalone-job trace avoids `merging` and `done`, and makes zero merge requests. Independent closer continuations are a separate mode. | §3.4; §5.1 R009, R080–R094; absence of access to R065–R067 |
| `Examples.pause_resume_normal_form` | Repeating the documented pause/resume cycle yields its symbolic state and launch count. | §5.1 R010, R014, R095, R099, R076; same-attempt accounting prose |
| `Examples.worker_launches_unbounded` | For every finite bound, a reachable trace exceeds it with one round and zero nudges/run retries. | §3.1, §5.1 R010, R014, R095, R099, R076; §12 disabled optional deadline |
| `Examples.terminal_cleanup_phase`, `Examples.terminal_cleanup_data_counterexample`, `Examples.terminal_cleanup_receipt` | A terminal trace remains `done` while an observed receipt changes its cleanup data. | §5.1 R067, R113 |
| `Examples.manual_merge_counterexample`, `Examples.manual_merge_request_counterexample` | Recorded manual authority permits both merge intent and the merged outcome under manual policy. | §3.3; §5.1 R060, R069, R007, R066–R067 |
| `Examples.malformed_verdict_failure_example` | Invalid review output reaches `failed` and subsequent approval/merge events cannot revive it. | §3.2; §5.1 R043, R119 |
| `Examples.reject_waiver_counterexample`, `Examples.reject_waiver_has_reject`, `Examples.reject_waiver_no_approve`, `Examples.reject_waiver_closer_approval` | A trace containing REJECT and no APPROVE merges via a scoped waiver and independent closer receipt. | §3.3; §5.1 R044, R046, R056, R008, R058, R061, R066–R067 |
| `Examples.worker_new_sha_merge`, `Examples.worker_new_sha_head`, `Examples.worker_new_sha_review`, `Examples.worker_new_sha_approval` | A worker-produced new head is gated, reviewed, approved and merged at that head. | §4.3–4.5; §5.1 R025, R031, R048, R061, R067, R113 |
| `Examples.stale_review_sha_refused`, `Examples.stale_tracker_sha_refused`, `Examples.stale_merge_receipt_sha_refused` | Old-SHA verdict, approval and merge-receipt events leave the corresponding phase unchanged. | §3.2–4.3; §5.1 transition semantics, R048, R061, R067 |
| Private `jobReturn_phase`, `jobPauseReturn_phase` | Job return/pause origins are subsets of standalone-job phases. | §5.1 finite aliases A/P and saved origins; R010, R076–R077 |
| Private `Examples.run_append` | Composing two event sequences equals running their concatenation. | §5.1 replay/composition semantics; structural list-fold helper |
| Private `Examples.pause_cycle` | One pause/resume cycle increments the symbolic worker-launch count while retaining the attempt. | §5.1 R010, R014, R095, R099, R076 |
