# Corylus work and evidence ontology

Written by an AI agent: **Codex (GPT-6)**, on Julian's behalf, November 7, 2026.
Current scope: **td-48a9a4**, applied by **td-e59184**. This supersedes conflicting
October entity/output and repair rules. It is a contract plan, not evidence of an
implemented backend or deployed schema. The [runner design](runner-design.md)
defines current authority, recovery and acceptance requirements.

## Entities

| Entity | Meaning and identity |
|---|---|
| Ticket | One td objective identified by stable project identity plus ticket ID. Epics organize objectives and are not execution work. |
| PR/revision | An explicitly associated proposed source slice and exact full head SHA. Several PRs may serve one continuing objective; superseded PRs remain history. A genuinely new objective needs a new ticket. |
| Attempt | One worker session's effort on the objective. A fresh worker session starts a new attempt; resuming the same actual session preserves it. Attempts cannot reset repair or overall work bounds. |
| Session | Actual persistent harness and tracker identities. Reviewers differ from all source authors and ineligible creator/implementer contexts. Resume retains the real context; a new invocation alone is not a fresh session. |
| Run | One invocation, including resume or re-review, with its own ID, purpose, limits, start/end and actual outcome/usage evidence. |
| Finding | A material blocker or follow-up bound to its review run, input revision and inspected SHA, with problem, evidence and required resolution. |
| Command/receipt | A scoped durable effect intent and its observed actual result. Unknown results remain uncertain until reconciled; deduplication never invents success. |
| Artifact | Bounded supporting evidence with access and publication policy. It is not another mutable workflow authority. |
| Decision | Authenticated scoped authority with author, project/ticket, relevant revision and any applicable expiry/revocation. A recommendation or delivery acknowledgment is not a decision. |

## Event storage and schema

Current records carry the scoped identities and evidence above using the owning
implementation's schema. The historical formal table refers to the old envelope
`{ts, ticket, attempt, session, run, type, actor, data, artifact}`. That reference
preserves vocabulary; it does not require a new custom JSONL workflow authority.

## Ownership and sessions

td owns objectives and dependencies. The selected workflow engine owns workflow
progress; harness sessions own their retained run evidence. Scoped command
receipts protect actual effects. Views derive from these owning records, without
another authoritative state or memory database. Do not require a new custom
Python event store beside accepted durable machinery.

Worker, reviewer, orchestrator and job labels describe the work being done, not
special model privileges or an exceptional edit phase. Any authorized contributor
who changes source is an author of that revision and cannot review it. Reviewer
sessions remain read-only, use a separate clean worktree and verify actual HEAD
against the full requested SHA before inspection and verdict. Read-only
investigation cannot acquire write permission from a purpose label.

Routine independent reviewer approval may use standing scoped authority. A closer
is optional when the workflow actually needs one, and must be truly eligible.
Execution in the actual independent tracker context matters; a named reviewer in
an author's command does not create independence. No self-approval.

## Purposes and bounds

Purposes such as build, repair, resume, review, investigate and report explain an
invocation. They do not grant authority, bypass checks or reset limits. Unknown
purposes need a useful reason. One finite repair policy and an overall finite
work bound replace nudge/quickfix entitlements and rung resets. No mandatory
triviality classification, file/line-count exception, five-rung routing or
prediction contract remains.

Deployment is outside the runner's work-state machine. Corylus may submit or
observe the declared deployment path and display its verified outcome, keeping
source acceptance, deployment result and intended-workflow acceptance distinct.

## Findings

A finding has a stable ID, inspected full SHA, input revision, explicit blocking
status, concrete summary, relevant evidence and required resolution. Include a
source location and verification evidence where useful. Resolution and accepted
waiver evidence retain provenance rather than overwrite history. No mandatory
`is_trivial`, exact ten-line fix or single-file eligibility field. Every changed
revision still needs applicable checks and independent exact-head review.

## Outcome evidence and dependencies

Source prerequisites require confirmed merge of independently accepted work at
its exact reviewed revision. Human/no-code prerequisites require authenticated
current acceptance for the declared scope. Verified-job prerequisites require
actual successful effect/verification receipts. Ticket type and closed status
cannot substitute for any of these. Software releases eligible dependents without
a supervising model. Missing, stale or unknown evidence holds visibly.

Persist command intent before effects and observed receipts after them. Reconcile
lost launch, approval and merge responses before retry. Proof the old writer
stopped precedes ownership release or replacement; scheduler or unreachable-node
status is insufficient. Limits and consumed repair work survive fresh attempts,
resume, model override and restart. Event or receipt corrections preserve history.

Durably saved work does not depend on immediate NATS delivery. Notifications can
retry with deduplicated delivery IDs, but neither delivery nor agent prose can
approve, merge or impersonate a human decision.

## Accounting and useful failure evidence

Record available actual model/effort, requested binding, tokens, duration and
genuinely metered cost per invocation. Deduplicate source receipt IDs across
session, attempt and ticket rollups. Unknown cost is unavailable, not zero; partial
coverage stays partial. Subscription usage gains no invented dollar charge. The
gateway retains shared dollar-budget authority. Optional estimates remain td
metadata; no required rung fold or prediction comparison.

Outcome, reason, evidence and next action are sufficient initial reporting.
Investigate repeated or consequential failures against retained records; do not
require universal cause classes, confidence, cheapest-control fields or correction
lineage for every rejection or legitimate decision. Scoped retrieval can use td
and authorized Markdown/wiki sources, without a second memory service.

## Private views and public projections

Authenticated private views retain useful authorized links and paths, including
safe configured forge links and evidence locations. Apply safe schemes,
destination controls, escaping, access checks and secret exclusion. Public source,
examples and exported/published views strip private hosts, absolute installation
paths, IP addresses and credentials. Do not expose arbitrary raw logs.

Graph/Table/Board remain the chosen experience. Transitional readers show actual
available data with explicit missing/stale states. Exhaustive legacy telemetry,
every retired screen and optional analysis modules are not release prerequisites.
Retained conversation, steering and parallel-worker workflows remain later open
outcomes until actual acceptance.
