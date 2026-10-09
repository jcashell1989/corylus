# Runner ontology

Written by an AI agent (Codex (GPT-6.1 Sol)).
This note records Julian's agreed model from October 9, 2026, on `td-00cf75`.
It defines the runner's entities and event contract. The
[runner design](runner-design.md) defines transition guards, recovery and approval
policy. This is documentation, not an implemented backend or board schema.

## Entities

| Entity   | Meaning                                                                       | Identity and relationships                                                                                                                                                                                                                                                 |
| -------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Ticket   | One td item and its intended outcome.                                         | The td ID is the durable identity. A ticket owns attempts and its event stream. Epics organize work but do not appear on the runner board.                                                                                                                                 |
| PR       | The ticket's proposed source change.                                          | One open-or-merged PR per ticket. A second PR means a new ticket; closed superseded PRs remain linked history. Attempts continue the ticket's existing PR.                                                                                                                 |
| Attempt  | One worker session's effort on a ticket.                                      | A fresh worktree or a new worker session starts a new attempt. Resuming the same worker session in its existing worktree keeps the attempt. Prior attempts and handoffs remain history.                                                                                    |
| Session  | A persistent execution identity, typed by what it may produce.                | Worker runs identify the attempt they contribute to. Related review, orchestrator and job sessions are associated with the attempt they act on; a standalone ticket job can have no attempt. A session owns runs and retains its harness and tracker identities on resume. |
| Run      | One invocation of a session.                                                  | A fresh run ID for every invocation, including resume, nudge and re-review. It records purpose, round, start/end, outcome and cost. A resumed session can have many runs.                                                                                                  |
| Finding  | A review observation with explicit blocking status and a proposed resolution. | Bound to a finding ID, review run, input revision and reviewed SHA. Resolution or waiver is subsequent evidence, not an overwrite.                                                                                                                                         |
| Event    | One durable observation or change in the ticket's history.                    | Appended to that ticket's JSONL stream. State, status, board projections and accounting are folds over these events.                                                                                                                                                       |
| Artifact | Sanitized supporting evidence or output.                                      | An opaque reference to a brief, report, findings packet, check receipt or other bounded evidence. It is not another source of mutable workflow state.                                                                                                                      |

An attempt is not a round. A worker can build in round 1, then resume for
remediation in round 2 within the same attempt. A fresh worker handling a nudge
starts a new attempt within the existing round. Attempt identity does not grant
another remediation round or reset a continuation's consumed budgets. Round
accounting remains the design's confirmed-worker-start rule, applied once per
build/remediation round rather than once per attempt. Review and other runs carry
the round they inspect or continue without independently charging a worker round.

## Session types and outputs

| Session type   | What it may produce                                                        | Constraints                                                                                                                                                                                                                               |
| -------------- | -------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `worker`       | Source commits and their PR, handoff and verification evidence.            | Works on the ticket's feature branch. A fresh worker session starts a new attempt.                                                                                                                                                        |
| `review`       | A verdict and findings, with supporting review evidence.                   | Must be a different session from the worker and every other session that committed the work under review. It inspects the exact SHA in a separate clean review worktree and produces no source commits. Tracker eligibility also applies. |
| `orchestrator` | Exceptional direct-edit commits during its final look before merge.        | Almost never used for edits. Every such commit invalidates the prior review and forces independent re-review. Decisions, briefs and nudges are also recorded with their actual actor.                                                     |
| `job`          | Artifacts only: reports, independent closer approval receipts and digests. | Produces no source commits. Authorized runbooks may perform bounded effects and record receipts; artifact-only output does not grant effect authority.                                                                                    |

These are output contracts, not a model hierarchy. If two types ever produce the
same things, merge the types instead of maintaining interchangeable labels.
The build/review loop still has worker and reviewer roles; `review` is the session
type for the reviewer role. An orchestrator session is not an alternative builder,
and a job is not an alternative reviewer. A job requesting a source fix hands it
to a worker continuation with normal review gates.

Each session persists both an opaque harness session reference and its actual td
session ID. Create a new isolated tracker context at session creation; reuse it
on resume. A new run alone does not create a new session. A reviewer or closer
must be eligible under the design's creator/implementer checks; an attribution
string cannot substitute for execution in the independent tracker session.

## Run purposes

Purpose is an open list. The following values are initially recognized. Only
the three marked rows change loop behavior; all other values describe why an
invocation happened. They do not independently select a transition, bypass a
gate, grant authority or reset accounting.

| Purpose       | Meaning                                                     | Changes loop behavior?                                                                                                           |
| ------------- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `build`       | Implement the ticket's brief.                               | No                                                                                                                               |
| `remediate`   | Address findings from a previous review.                    | No                                                                                                                               |
| `quickfix`    | Apply only trivial remaining blockers.                      | **Yes:** eligible only when all remaining blocking findings have `is_trivial: true`; retain verification and independent review. |
| `nudge`       | Finish a missing commit, push, handoff or repairable check. | No; the existing nudge budget still applies.                                                                                     |
| `resume`      | Continue an existing session with a new invocation.         | No; preserve session identity and the applicable continuation guards.                                                            |
| `rebase`      | Update the ticket branch against its base.                  | No; a changed head still invalidates review.                                                                                     |
| `investigate` | Gather evidence for a question or failure.                  | **Yes:** no commits permitted.                                                                                                   |
| `deploy`      | Execute an explicitly authorized deployment.                | **Yes:** Julian's approval is required and the run executes alone, with no concurrent runner runs.                               |
| `verify`      | Collect verification evidence.                              | No                                                                                                                               |
| `review`      | Inspect the proposed source change.                         | No; the session must satisfy the review output contract.                                                                         |
| `re-review`   | Review a changed head or refreshed input.                   | No; apply the same independence and exact-SHA checks.                                                                            |
| `other`       | A purpose not yet in the recognized list.                   | No; requires a nonempty free-text `purpose_reason`, allowing a recurring purpose to be added later.                              |

A run's purpose and session type are separate fields. The session's output
contract always applies: a job tagged `quickfix` still cannot commit, and a worker
tagged `investigate` cannot commit either. Ordinary purposes do not weaken job
authorization, deployment approval, concurrency limits or merge policy.

## Findings

Every blocking finding carries an explicit Boolean `is_trivial`; missing or
malformed classification cannot qualify a run for `quickfix`. Trivial means all
of the following: the reviewer gives the exact fix; it touches one file and about
10 lines or fewer; it changes no live service, host, credential or deployment;
and tests or lint can check it. All remaining blockers must meet that definition,
not just the first one. A general suggestion or a fix requiring investigation is
not trivial.

| Field            | Type                                                         | Meaning                                                                                        |
| ---------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `id`             | String                                                       | Stable finding ID within the ticket.                                                           |
| `reviewed_sha`   | String                                                       | Exact commit inspected; cannot apply a verdict to a different head.                            |
| `input_revision` | Integer                                                      | Brief/decision revision consumed by the review.                                                |
| `file`, `line`   | Repository-relative string or null; positive integer or null | Location, when applicable. Never installation paths.                                           |
| `severity`       | String                                                       | Review severity; does not replace explicit blocking status.                                    |
| `blocking`       | Boolean                                                      | Whether the finding prevents acceptance.                                                       |
| `summary`        | String                                                       | Concrete problem and its consequence.                                                          |
| `required_fix`   | String                                                       | Resolution needed to satisfy the finding.                                                      |
| `is_trivial`     | Boolean                                                      | Required for every blocking finding; true only under the definition above.                     |
| `exact_fix`      | String or null                                               | Reviewer's exact change; required when `is_trivial` is true.                                   |
| `verification`   | String                                                       | Tests or lint that can verify a trivial fix; evidence required for other fixes as appropriate. |

The event envelope identifies the ticket, attempt, review session and run.
Later findings events reference the same finding ID to record resolution evidence.
A waiver records the finding IDs, scope, authorized actor and exact SHA. A
reviewer's waiver recommendation is not an accepted waiver.

## Direct edits and merge identity

Direct edits occur almost never, and only during the orchestrator's final look
before merge. Record its committing session and the before/after SHAs, invalidate
affected checks and verdicts, then gate and independently re-review the new head.
After merge, even a one-line source fix always needs a new ticket and PR.

`has_direct_edits` is derived, never a manually set flag. It is true for an
attempt when that attempt has an orchestrator session that committed. The
ticket-level value is the OR across its attempts, so subsequent clean work does
not erase the history. A decision or waiver without a commit does not set it.
Merges occur only at the exact reviewed SHA, with the design's atomic forge
guard and approval/acceptance receipts. Direct edits do not waive that invariant.

## Event storage and schema

There is one append-only JSONL stream per ticket in the locally configured runner
state directory: `events/<ticket>.jsonl`. Appends are locked; one complete JSON
object occupies each line. Persist intent before effects and observations after
them. Every change is an event, including attempt/session/run starts and ends,
briefs, decisions, findings, waivers, verdicts, gates, nudges, holds, merges and
direct edits. Correct history by appending evidence, never by rewriting lines.

| Field      | Type           | Meaning                                                                                                             |
| ---------- | -------------- | ------------------------------------------------------------------------------------------------------------------- |
| `ts`       | String         | UTC timestamp in RFC 3339 format. Stream order, not timestamp sorting, determines replay order.                     |
| `ticket`   | String         | td ID matching the stream's ticket.                                                                                 |
| `attempt`  | String or null | Attempt association; null before an attempt exists or for a ticket-only job.                                        |
| `session`  | String or null | Stable typed session ID; null for an event outside an agent session.                                                |
| `run`      | String or null | Invocation ID; null for an event outside a run.                                                                     |
| `type`     | String         | Typed event name from the lifecycle or design transition vocabulary.                                                |
| `actor`    | String         | Actual human, session or runner component that emitted the event. A claimed actor string alone grants no authority. |
| `data`     | Object         | Allowlisted event-specific payload: purpose/round, findings, SHA, decision provenance, reason, receipt or cost.     |
| `artifact` | String or null | Opaque sanitized evidence reference; null when there is no artifact.                                                |

All nine fields are present; null associations are explicit. Lifecycle events
establish IDs before later events refer to them. `data` carries the journal's
schema version, per-ticket sequence and event/effect IDs where required by the
design's crash-recovery protocol, plus lane and repository references when
needed. These are payload metadata, not a competing top-level schema.
Reject malformed records; do not dispatch after a failed append. Recovery,
deduplication and incomplete-tail handling follow the design.

Events contain evidence references and bounded sanitized facts, not raw private
transcripts, credential values or installation details. State snapshots and
adapter status JSON are derived caches, not authorities. This model does not
claim that an existing producer already emits the complete stream.

## Event types

| Type                                                                                            | Payload and effect on projections                                                                                                                                                                                                                        |
| ----------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `brief.recorded`                                                                                | Versioned scope, acceptance and input reference.                                                                                                                                                                                                         |
| `attempt.started`, `attempt.finished`                                                           | Worker session/worktree association or final outcome and handoff reference.                                                                                                                                                                              |
| `session.started`, `session.finished`                                                           | Session type and identity evidence, or end outcome. Ending a run does not end a resumable session.                                                                                                                                                       |
| `run.start_requested`, `run.started`                                                            | Invocation identity, session type, purpose, round and launch intent/receipt. `other` includes `purpose_reason`.                                                                                                                                          |
| `run.progress`                                                                                  | Bounded useful-progress observation.                                                                                                                                                                                                                     |
| `run.finished`, `run.failed`, `run.launch_failed`                                               | Exit/outcome, reason, duration, usage/cost and receipt. Failed launch does not imply a confirmed start.                                                                                                                                                  |
| `findings.recorded`                                                                             | Finding entries bound to review SHA/input, or resolution evidence referring to existing IDs.                                                                                                                                                             |
| `review.verdict`                                                                                | APPROVE, REJECT or NEEDS-DECISION, reviewed SHA, input revision, independence and clean-HEAD evidence.                                                                                                                                                   |
| `decision.recorded`, `decision.invalid`                                                         | Authorized decision and its scope/provenance, or refusal reason.                                                                                                                                                                                         |
| `waiver.recorded`                                                                               | Accepted waiver, author, scope, finding IDs and SHA; mirror alongside its decision.                                                                                                                                                                      |
| `gate.passed`, `gate.failed`, `gate.error`, `checks.absent`, `judgment.result`                  | Gate name, head-bound receipts, findings or required policy. Existing transition guards still apply.                                                                                                                                                     |
| `nudge.requested`                                                                               | Reason, remaining budget and target continuation; subsequent run events record execution.                                                                                                                                                                |
| `hold.recorded`, `dependency.satisfied`                                                         | Hold reason, prerequisites and saved continuation, or evidence that every prerequisite merged.                                                                                                                                                           |
| `direct_edit.committed`                                                                         | Orchestrator session, commit SHA and prior SHA; derive `has_direct_edits` and invalidate stale review.                                                                                                                                                   |
| `tracker.approved`, `tracker.failed`                                                            | Independent reviewer/closer approval receipt or refusal; distinct from merge.                                                                                                                                                                            |
| `pr.ready`, `merge.requested`, `pr.merged`, `merge.blocked`, `merge.unsupported`                | Readiness, expected reviewed SHA, merge receipt/resulting merge SHA, or unresolved failure. Only confirmed success satisfies a merge prerequisite.                                                                                                       |
| `job.finished`, `job.verified`, `rollback.verified`, `rollback.failed`                          | Authorized job artifact/effect receipts and named verification/restoration outcome.                                                                                                                                                                      |
| `admission.checked`, `pause.requested`, `resume.requested`, `stop.requested`                    | Queue/control requests and guarded continuation evidence.                                                                                                                                                                                                |
| `effect.planned`, `effect.observed`, `effect.uncertain`, `recovery.observed`, `event.duplicate` | Durable effect identity, receipt, uncertainty or replay/deduplication observation.                                                                                                                                                                       |
| Other design observations                                                                       | Identity/workspace/head failures, deadlines, cancellation, storage failure, policy warnings and notification receipts retain the design's typed names and guards. Scheduler-wide observations have separate scope; they do not invent a planning ticket. |

The lifecycle additions enrich history; they do not create new state phases or
approval shortcuts. Their observation handling must be allowed alongside the
design's transition events. A state-changing event that enters a hold also
records its reason and continuation; `hold.recorded` can annotate it without
becoming a second transition. The board displays tickets, hides epics and folds
the stream to show current phase, active run/round, elapsed time, findings,
decision owner, last event and accounting.

Human-relevant decisions, waivers, verdicts and merges are mirrored to `td log`
with a pointer back to the ticket stream and sequence/event reference. The
complete stream is stored in the runner state directory, not in td. Failed
mirror delivery retains a retryable receipt; it cannot erase the event. A
ticket-scoped authorization originally recorded by a human in td remains input
with provenance; the mirror is not a new grant of authority.

Queue eligibility reads td dependencies. Launch the first queued ticket whose
prerequisites have all merged, skipping held entries. A prerequisite in
NEEDS-DECISION, failed or dead keeps dependents held with an actionable reason.
Tracker closure, approval or a successful unmerged job is not merge evidence.
See `td-c414ae`; the board consumer is `td-664dd4`.

## Accounting

Cost is recorded per run and rolled up to session, attempt and ticket. Record
duration and available token/meter receipts with the run ID, deduplicating
observations. Session totals sum its runs; attempt totals sum the runs attributed
to that attempt, grouped by session; ticket totals sum attempts plus ticket-only
job runs exactly once. A session that contributes to more than one attempt does
not cause its costs to be counted twice.
A resumed session's invocations remain separate cost-bearing runs. Review and
orchestrator costs belong to their associated attempt, not to the worker's
session. Corrections append new evidence with the original receipt identity.

Unknown cost is unavailable, not zero. Preserve partial-meter labels through
every rollup. Codex subscription runs report tokens when available and no dollar
figure; dollar totals include only gateway-billed runs with real meter evidence.
External budget meters remain optional and do not imply a runner spend cap.

## Worked event-stream example

This is a 15-line excerpt from one fictional ticket's stream, in append order.
It follows brief → build → review REJECT → decision → remediate → review APPROVE
→ merge. All identifiers, SHAs, checks and artifacts are fictional. The worker
resumes in the same attempt for round 2; the review session differs from it.
For length, reviewer session/run start/end events, remaining session endings,
launch intents, intermediate gates and journal metadata are omitted from this
excerpt; a stored stream includes them as well. Artifact labels are opaque
references. The excerpt alone is not a complete recovery journal.

```jsonl
{"ts":"2026-01-01T09:00:00Z","ticket":"td-f00001","attempt":null,"session":null,"run":null,"type":"brief.recorded","actor":"human-example","data":{"input_revision":1,"scope":"Validate example inputs"},"artifact":"brief-1"}
{"ts":"2026-01-01T09:01:00Z","ticket":"td-f00001","attempt":"a1","session":"w1","run":null,"type":"attempt.started","actor":"runner","data":{"worker_session":"w1","pr":42},"artifact":null}
{"ts":"2026-01-01T09:01:01Z","ticket":"td-f00001","attempt":"a1","session":"w1","run":null,"type":"session.started","actor":"runner","data":{"session_type":"worker"},"artifact":"worker-identity"}
{"ts":"2026-01-01T09:02:00Z","ticket":"td-f00001","attempt":"a1","session":"w1","run":"b1","type":"run.started","actor":"runner","data":{"purpose":"build","round":1},"artifact":"launch-b1"}
{"ts":"2026-01-01T09:12:00Z","ticket":"td-f00001","attempt":"a1","session":"w1","run":"b1","type":"run.finished","actor":"runner","data":{"exit":0,"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","input_tokens":900,"cost_usd":null,"billing":"subscription"},"artifact":"build-checks-1"}
{"ts":"2026-01-01T09:16:00Z","ticket":"td-f00001","attempt":"a1","session":"v1","run":"r1","type":"findings.recorded","actor":"v1","data":{"findings":[{"id":"F1","reviewed_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","input_revision":1,"file":"src/example.py","line":14,"severity":"high","blocking":true,"summary":"Malformed input is accepted","required_fix":"Reject malformed inputs and add regression coverage","is_trivial":false,"exact_fix":null,"verification":"Project tests and lint"}]},"artifact":"findings-1"}
{"ts":"2026-01-01T09:17:00Z","ticket":"td-f00001","attempt":"a1","session":"v1","run":"r1","type":"review.verdict","actor":"v1","data":{"verdict":"REJECT","reviewed_sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","input_revision":1,"round":1},"artifact":"review-1"}
{"ts":"2026-01-01T09:18:00Z","ticket":"td-f00001","attempt":"a1","session":null,"run":null,"type":"decision.recorded","actor":"human-example","data":{"decision":"Remediate F1 within the existing scope","finding_ids":["F1"],"input_revision":2},"artifact":"decision-1"}
{"ts":"2026-01-01T09:19:00Z","ticket":"td-f00001","attempt":"a1","session":"w1","run":"b2","type":"run.started","actor":"runner","data":{"purpose":"remediate","round":2,"resumed_session":true,"input_revision":2},"artifact":"launch-b2"}
{"ts":"2026-01-01T09:27:00Z","ticket":"td-f00001","attempt":"a1","session":"w1","run":"b2","type":"run.finished","actor":"runner","data":{"exit":0,"sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","input_tokens":600,"cost_usd":null,"billing":"subscription"},"artifact":"build-checks-2"}
{"ts":"2026-01-01T09:28:00Z","ticket":"td-f00001","attempt":"a1","session":null,"run":null,"type":"gate.passed","actor":"runner","data":{"gate":"checks","sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","input_revision":2},"artifact":"checks-2"}
{"ts":"2026-01-01T09:33:00Z","ticket":"td-f00001","attempt":"a1","session":"v1","run":"r2","type":"review.verdict","actor":"v1","data":{"verdict":"APPROVE","reviewed_sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","input_revision":2,"round":2,"resolved_findings":["F1"]},"artifact":"review-2-clean-head-and-independence"}
{"ts":"2026-01-01T09:34:00Z","ticket":"td-f00001","attempt":"a1","session":"v1","run":null,"type":"tracker.approved","actor":"v1","data":{"reviewed_sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"},"artifact":"eligible-tracker-approval"}
{"ts":"2026-01-01T09:35:00Z","ticket":"td-f00001","attempt":"a1","session":null,"run":null,"type":"pr.merged","actor":"runner","data":{"pr":42,"reviewed_sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","expected_sha":"bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb","merge_sha":"cccccccccccccccccccccccccccccccccccccccc"},"artifact":"atomic-merge-readback"}
{"ts":"2026-01-01T09:36:00Z","ticket":"td-f00001","attempt":"a1","session":null,"run":null,"type":"attempt.finished","actor":"runner","data":{"outcome":"done"},"artifact":"handoff-1"}
```

The final merge points to the same full SHA approved in the second review.
No new PR, attempt or worker session is needed merely because remediation ran.
The decision, both verdicts and the merge have td-log mirrors with stream
pointers. Review run costs appear in their omitted run-end records and are
included in the attempt and ticket rollups.
