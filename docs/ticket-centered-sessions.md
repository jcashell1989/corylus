# Corylus × Hermes: Ticket-Centered Work Sessions

**Design document — for a reader who knows nothing about the current setup**

Status: design proposal v2 (revised after external review), not an implementation approval. Owner: Julian.
Date: 2026-09-09 (US Pacific). Companion documents: `alpha-plan.md` (Corylus planning draft), Corylus `README.md`.
Authoring context: this document came out of a design conversation between Julian and his coordination agent (nomos), with research/evaluation input from a planning agent (pandora). Where this document says "Julian wants" or "nomos assessed," those are positions held in that conversation, recorded here so a cold reader can reconstruct the reasoning.
Revision note: v2 incorporates an external review (GPT-6 Astra) whose material contributions are: the **state/note split** (§5.1v2), the **Ticket → Attempt → Session hierarchy** (§5.2v2), **event-driven canonical state** (§5.7), and a **weakened empirical claim** in §4 (the 72-ticket sample bounds today's rework causes, not the value of continuity in general). Convergent validation: the Attempt abstraction Astra proposed is already implemented in the existing pipeline (`hermes:attempt v1` markers with attempt number `n`, per AGENTS.md machine-comment spec) — the reviewer re-derived the system's own concept from the document alone.

---

## 0. Read this first (the one-paragraph version)

Work in this ecosystem is done by AI agents executing "tickets" (units of work with an ID, a description, comments, and a lifecycle). Today, each time an agent works on a ticket, it runs in a **fresh, disconnected session** — like a new employee with amnesia clocking in every night. Julian proposed that instead **each ticket should get one continuous session that persists for the ticket's whole life**. Through discussion, the design evolved: rather than making sessions literally persistent (which has safety and complexity costs), **group all of a ticket's sessions under the ticket itself, and maintain one living, human-readable status note per ticket**. The ticket becomes the single place anyone — human or agent — looks to know what's happening. The goal is not smarter agents; the goal is an **ergonomic system for Julian**: he should never have to hunt through session transcripts to find which session is doing what.

---

## 1. Background: the ecosystem as it exists today

A cold reader needs four facts about the current system (Hermes + Vikunja + Corylus):

### 1.1 The cast

| Component | What it is | Role in work |
|---|---|---|
| **Hermes Agent** | A self-hosted AI agent runtime. Multiple "profiles" (named agents) run on one host, each with its own configuration, memory, and chat surface. | The *workers*. A scheduler spawns an agent process, gives it a task, the agent works via tools (shell, files, APIs). |
| **Vikunja** | A self-hosted project-tracking service (tickets, projects, comments, labels). | The *tracker of record*. Every piece of work lives here as a ticket with an ID. |
| **Corylus** | A net-new application being designed (see `alpha-plan.md`): "the control layer for an automated agentic work pipeline." | The *future* shared space where humans and agents discuss, maintain knowledge, and manage work. Currently in planning; a repo exists with UI groundwork and a planning draft. |
| **The judge** | A separate agent identity that reviews a worker's finished ticket. | Quality gate. Its independence rule ("never self-close": no agent may approve its own work) is a core safety property. |

### 1.2 How a piece of work flows today

1. A ticket exists in Vikunja (created by a human or an agent).
2. A nightly scheduler picks dispatchable tickets (by priority) and **spawns a fresh Hermes worker session** for each, one at a time.
3. The worker session orients itself: reads the ticket, all its comments, the project files, any task-plan state. Then it works.
4. When done (or when its time/spend budget runs out), the worker **posts a handoff** to the ticket — what it did, what it skipped, what needs checking — and labels the ticket for review.
5. A separate judge agent reads the ticket and the work artifacts and writes a verdict (approve / send back for fixes / etc.).
6. The human (Julian) reviews judged work and closes tickets he's satisfied with.

This pipeline works and has produced dozens of accepted tickets. The complaint that generated this design document is **not about the pipeline's judgment** — it's about **findability**.

### 1.3 The session model, precisely

- A "session" is one agent run: it starts when the scheduler (or a human) invokes the agent, and ends when the run completes. Sessions are typically **minutes to a couple of hours** long.
- Every dispatch is a **new session**. There is no worker process that stays alive between dispatches.
- Session transcripts (the full record of what the agent did and said) are stored and searchable, but they are **linear, per-run logs** — not organized by ticket.
- A ticket accumulates its story in **append-only comments** on the tracker: claim notes, progress, handoffs, judge verdicts. This is the durable, shared record.
- There is a hard interrupt (~3 minutes) on unattended runs in some lanes; a run can also end on budget. A later session resumes the work cold, relying on the ticket comments.

### 1.4 The problems observed (evidence from real operations)

1. **Re-orientation cost.** Every fresh session re-reads the ticket, comments, files, and plan state. Measured: workers average ~81 tool-call exchanges per run; roughly the first 8 are pure orientation. With prompt caching, this is a minor *money* cost but a real *latency and quality* cost: the worker spends its freshest attention rebuilding context that already exists.
2. **Session scatter.** The work on one ticket is smeared across many session transcripts (morning run, evening run, remediation run, judge run…). The *human* — Julian — has no single place to look to answer "what's the state of this ticket?" He must either read the ticket comments (if the agents were disciplined) or dig through sessions. **This is the primary pain this design targets.**
3. **Rework driven by verification gaps, not memory gaps.** Of 72 judged tickets in recent operations, 30 (≈42%) came back for rework. Post-mortems show the cause was almost never "the worker forgot something from a previous session" — it was "the worker didn't *verify* before handing off" (tests not runnable from a clean checkout, undocumented canonical commands, wrong kwarg names). Fresh eyes didn't catch these because the *ritual of checking* wasn't forced.

---

## 2. The two positions, distinguished (as requested)

This is the heart of the document. Two positions were articulated; they are **not the same design**, and the difference matters.

### Position A — Julian's: one continuous persistent session per ticket

> "One ticket gets one persistent agent session. One worker thread per ticket. Maybe a second thread for the judge."

**Mechanics as literally stated:** when a ticket is claimed, a session starts and *stays alive* — same running context, same conversation — until the ticket is done. The judge, if also persistent, has its own thread. The session is the unit of continuity.

**What it optimizes for:** the agent's working state never evaporates. No re-orientation, ever. The worker's understanding of the ticket grows richer over its lifetime, like a case file a dedicated caseworker keeps in their head.

**What it costs / risks:**
- **Drift risk.** A long-lived session accumulates beliefs ("the label is X," "the fix is in file Y") that may no longer be true. Real failure observed in this ecosystem: an agent acting on remembered ticket numbers instead of looking them up, twice in one week. Persistent memory without forced re-grounding makes this *worse*, not better.
- **Failure states get heavier.** A crashed or wedged persistent session is a *stateful* problem: what does "resume" even mean when the session's context is gone? Today's system sidesteps this — a fresh session is always a clean, provable state.
- **Infrastructure complexity.** Requires session lifecycle management, crash recovery, possibly checkpointing *anyway* (to survive restarts) — at which point the "persistent" part has quietly become "checkpointed."
- **It doesn't actually solve Julian's stated pain** (see §3): richer sessions are still scattered sessions. Finding "which session is doing what" remains a hunt across long-lived blobs.

### Position B — nomos's (evolved with Julian's motivation): ticket as the organizing principle on the backend

> "All of a ticket's sessions get grouped under the ticket. The ticket owns one living, human-readable status note. Sessions stay stateless; the ticket holds the continuity."

**Mechanics:**
1. **Backend grouping:** the ticket record gains a `sessions` collection — every session that ever touched the ticket is linked to it (they already are, via comments/machine markers; this makes it first-class and queryable).
2. **One living status note per ticket** (the "checkpoint"): a structured, human-first document, updated by the worker at every check-out:
   - *Where I am* — current state of the work in plain language
   - *What I believe* — working assumptions worth carrying
   - *What's next* — the next concrete step
   - *What I ran, and proof it passed* — verification manifest: exact commands, interpreters, test results (this field is nomos's addition, justified in §4)
3. **Check-in ritual preserved:** the next session reads the note **alongside** — never instead of — the live ticket, comments, and files. Authoritative state always wins over the note. The note is a briefing, not a source of truth.
4. **Human-first writing:** the note is written so *Julian* can read it. That's not a nicety; it's the point.

**What it optimizes for:** Julian's findability (§3), plus a bounded slice of the agent-continuity benefit — without persistent-process risk.

**What it costs / risks:**
- The note can go stale or become boilerplate if workers treat it as paperwork (mitigation below).
- It adds one artifact to write per check-out (a few hundred tokens of effort).
- It does not give the *agent* literal memory across runs; if re-orientation cost were the dominant problem, this solves less of it than Position A. (Measurement says it isn't — see §4.)

### The difference in one table

| Dimension | A: Persistent session | B: Ticket-grouped sessions + living note |
|---|---|---|
| Unit of continuity | The running session | The ticket (a backend grouping + a document) |
| Agent memory across runs | Full, in-context | None in-context; partial via the note |
| Re-grounding against reality | Must be *added* (risk of drift) | Built-in (check-in ritual) |
| Crash/wedge recovery | Hard (stateful process) | Trivial (next session = clean state + note) |
| Julian finds state by… | Opening "the" session (which may be huge) | Opening **the ticket** |
| Never-self-close / judge independence | Judge thread needs a visibility firewall | Unchanged; judge sees artifacts only |
| Matches the human's actual pain? | Partially at best | Directly |

### Where the positions agree (the shared core)

- Continuity for a piece of work should live **with the ticket**, not in an agent's head or an arbitrary session transcript.
- The re-orientation ritual — re-reading live state on every clock-in — is a **feature** (drift-catcher), and any design must keep it.
- The judge's independence is about **what the judge sees** (handoff artifacts, never the worker's private reasoning) regardless of session longevity.
- Sessions should remain **bounded and disposable**; nothing safety-critical should live only in a long-running process.

---

## 3. The actual goal: ergonomic for Julian

This section exists because the conversation corrected itself here, and the correction changes the design's emphasis. Julian's words:

> "I want to keep everything really well organized so I don't have to search across a bunch of sessions and try to figure out exactly what I'm doing in each session… It's not a question of digging through a session for context. It's trying to just find the right session."

That is a **findability** requirement, not an agent-memory requirement. Restated as design requirements:

- **R1 — One place to look.** For any ticket, there is exactly one canonical "what's happening" surface: the ticket itself. Opening it must answer the question in under a minute, without opening any session transcript.
- **R2 — Zero session archaeology.** Julian should never need to search session logs to locate work. Sessions are background evidence, consulted deliberately, never the index.
- **R3 — Human-readable state.** The status note is written in plain language for the human first, agent second.
- **R4 — Always current.** The note is updated at every check-out by whoever worked last; staleness is visible (last-updated stamp, linked sessions).
- **R5 — Works today and later.** The mechanism must function within the *current* Hermes+Vikunja pipeline (as a discipline + a small tooling change) **and** be a first-class primitive in Corylus's design (where the backend grouping is native).

The acceptance test for the whole design, in one sentence: **Julian can open any active ticket cold and know exactly what's going on — current state, next step, where the work lives, whether the last run's proof passed — without opening a single session.**

---

## 4. Evidence and reasoning that led here

For the cold reader: this is the reasoning chain, with the data, so the design's assumptions can be re-checked rather than trusted.

1. **The trigger.** Julian observed the fresh-session-amnesia pattern and proposed persistent per-ticket sessions (Position A).
2. **The pushback.** Evaluation (pandora, then nomos) found: (a) the re-orientation ritual is a drift-catcher — real incidents confirmed agents go wrong when acting on carried context; (b) persistent processes introduce stateful failure modes the current model avoids; (c) the never-self-close gate needs protecting from any "persistent judge" that could see worker internals.
3. **The reframe.** Rather than persistence, **checkpointed working context**: the note at check-out, loaded alongside live state at check-in. Continuity + grounding.
4. **The measurement.** Token/call accounting on the existing worker: ~81 average tool-call exchanges per run; ~8 orientation; orientation is a small *cost* share (prompt caching makes re-reads cheap). Conclusion: pure persistence is solving a near-non-problem *on cost*. The worthwhile benefits are latency-to-work and quality — and the rework data shows quality problems are verification gaps, not memory gaps.
5. **The rework data.** 72 judged tickets, 30 reworked (≈42%). Every examined rework was "didn't verify before handoff" (artifact not testable clean; canonical runner undocumented; a renamed kwarg missed). None were "forgot prior context." **Therefore the note must include a verification manifest** — forcing the check at the moment of hand-off, and giving the judge exactly the artifacts it should see.
6. **The motivation correction.** Julian clarified the driver: findability for *him* (R1–R5), not agent efficiency. This flipped the design's emphasis from "agent memory" to "ticket as the one place to look," and promoted human-first writing of the note from nice-to-have to core requirement.
7. **The synthesis.** Position B (ticket-grouped sessions + living status note + verification manifest), designed to work in today's pipeline and to be native in Corylus.
8. **External-review correction (v2).** A reviewer (GPT-6 Astra) accepted the synthesis and challenged one inference: the 72-ticket sample establishes that *known* rework is not currently attributable to context loss — it does **not** establish that session continuity has negligible quality value. Context loss could manifest as slower execution, repeated exploration, or poorer coherence, and land downstream in categories this sample never sees. The design conclusion survives on findability and architectural-cost grounds without the stronger claim; persistence therefore remains an *orthogonal, permitted-later optimization* (see §6 and the principle: **semantic continuity belongs to the ticket; runtime continuity is optional**).

---

## 5. The design, concretely

> **v2 structure note:** §5.1–5.4 below are the original (v1) design, kept for the reasoning trail. §5.1v2–§5.7 supersede them where they conflict — read v2 as canonical and v1 as rationale.

### 5.1 The living status note (per ticket) — v1, superseded by §5.1v2

Structure (fixed headings; content free-form):

```
## Status (written by <agent>, <timestamp>)
Where I am: <plain-language current state, 1–3 sentences>
What I believe: <working assumptions that matter for the next shift>
What's next: <the single next concrete step>
Proof: <commands run + results: interpreter, test counts, exit codes>
Files/branch: <where the work lives>
Sessions: <list of session records linked to this ticket>
```

Rules:
- Written (replaced, not appended) by the worker at **every check-out** — success, partial, blocked, or handed-off. One note per ticket, always current.
- Human-first: readable by Julian in under a minute.
- **Never authoritative.** If the note disagrees with the live ticket/files, the live state wins, and fixing the note is part of the next check-in.
- On blocked/interrupted exits, the note says so explicitly (a "blocked" note is more valuable than a silent one).

### 5.2 Backend grouping (sessions under ticket)

- Every session that works a ticket is **recorded against it**: ID, start/end, agent identity, outcome. (Today this is recoverable from comments and runtime records; in Corylus it becomes a first-class relation — the ticket *owns* its session list.)
- The ticket page shows: current status note, the session list (each with one-line outcome), and the standard comment stream beneath.
- This is the "organizing principle on the backend": **the ticket is the primary key of work; sessions are its children; transcripts are evidence attached to sessions.**

### 5.3 The check-in ritual (unchanged, now explicit)

On every clock-in, the worker:
1. Reads the status note (briefing, not truth).
2. Re-reads **live** state: ticket, comments, labels, files, plan.
3. Reconciles: if the note disagrees with live state, corrects the note and proceeds on live state.
4. Works. At check-out, rewrites the note (including Proof).

### 5.4 Judge interaction (unchanged in substance)

The judge sees: ticket, comments, diff/work artifacts, and the status note — including **Proof**. The judge never sees the worker's session internals. The Proof field also makes the judge's job sharper: it can check claims against artifacts rather than vibes. (Never-self-close is preserved: the judge is a different identity; the note doesn't change visibility rules.)

### 5.5 In Corylus (how this becomes native)

Mapping onto the alpha-plan (the reader should treat the alpha-plan as authoritative for Corylus generally; this section proposes where the design slots in):

- **Tickets** (the Work area) gain two first-class elements: a **status-note field** (one per ticket, versioned like page revisions so history is preserved) and a **sessions relation** (run records owned by the ticket).
- The **check-in/compact-check-in** concept in the alpha plan already expects agents to re-ground on live state; the status note is the worker-authored half of that exchange.
- The **librarian** (knowledge-tending role) can flag stale notes (no update across N check-ins while the ticket moved) — an extension of its existing review duties, requiring no privileged path.
- **Guardrails** unchanged. The note is an artifact, not an action.
- **Provenance:** notes cite the session that wrote them, satisfying the alpha plan's attributable-records requirements.
- Alpha acceptance addition: *"Ticket-state findability: for any seeded active ticket, a human reads the ticket page and correctly states current state, next step, and last verification result in under one minute, without opening session records."*

### 5.6 Interim implementation on today's pipeline (optional, small)

Before Corylus exists, the same discipline can run on Hermes+Vikunja with:
1. A `status-note` convention: a pinned/first comment (or a linked file in the project repo) following the §5.1 template.
2. A worker-prompt addition (supervisor dispatch prompt): "at check-out, rewrite the status note per template."
3. A small digest/report addition: "tickets whose status note is older than their latest comment" (staleness flag) — fits the existing governance digest.
This is deliberately **not** filed as a ticket in this document; it's listed so the reader knows the design doesn't wait for Corylus to deliver value. (Decision to file it is Julian's.)

---

## 5v2. The revised architecture (canonical, after external review)

External review (GPT-6 Astra) endorsed Position B as the design direction — "reject Position A as a foundational architecture and adopt Position B" — with three structural upgrades and one evidential correction. This section is the **canonical design**; §5.1–5.5 above are retained as reasoning. The upgrades share one theme: **stop asking agents to transcribe what the system already knows.**

### 5.1v2 Separate durable state from the worker's narrative

v1's status note did too many jobs: current state, beliefs, next action, verification evidence, artifact locations, and a session index — some of that is *state*, some *worker interpretation*, some *provenance*, some *relationships the database already knows*. An LLM-maintained markdown blob must not become a miniature database.

The model becomes structured state + a small worker-authored note, rendered together into one human-facing ticket surface:

```
Ticket
├── lifecycle state            (system: open / in progress / blocked / in review / done)
├── current summary            (worker: one to three sentences)
├── next action                (worker: the single next concrete step)
├── blockers                   (worker: what's stopped and why)
├── artifacts[]                (system + worker: file paths, branches, links as references)
├── verification[]             (system of record, worker as author: commands, interpreters, results)
├── sessions[]                 (system: auto-captured, never agent-written)
├── reviews[]                  (system: judge identity, verdict, evidence)
└── worker notebook            (worker: current understanding, assumptions — the only free-form part)
```

Key assignments:
- **`Sessions:` must not be text written by an agent.** Corylus knows the relationship. (Interim exception: in today's pipeline nothing machine-readable records sessions per ticket, so the interim note keeps a Sessions line until Corylus replaces it — marked as load-bearing-there, deprecated-in-Corylus.)
- **`Files/branch` becomes artifact references**, not prose.
- **Verification becomes structured evidence** (command, interpreter, exit code, timestamp, citing session) rather than "pytest … 37 passed" prose — though the rendered human view can still read as one line.
- The **narrowed human-readable note** is exactly four fields: `Current state / Next / Blocked by / Worker notes (assumptions)`. This preserves the ergonomic property — open the ticket, know the state in under a minute — without a second database.

### 5.2v2 The missing abstraction: attempts

A session is an *infrastructure* concept (one runtime execution). An **attempt** is a *work* concept (one coherent effort to advance the ticket). The hierarchy:

```
Ticket → Attempt → Session(s)
```

Example shape:

```
Ticket #412
├── Attempt 1 — vulcan
│   ├── session abc
│   ├── artifacts
│   └── verification
├── Review 1 — archon  → rejected: clean checkout fails
├── Attempt 2 — vulcan
│   ├── session def
│   ├── artifacts
│   └── verification
└── Review 2 — archon  → accepted
```

This tells you what a flat sessions list cannot: which executions form one coherent attempt, and which work was remediation following a review. It matters increasingly once agents wake multiple times, delegate, hit limits, or span execution environments — one logical attempt may involve several runtime sessions.

**Convergent validation (worth the cold reader's attention):** this abstraction is not speculative — the existing pipeline already implements it. Worker handoffs post `hermes:attempt v1` machine comments carrying an attempt number `n`, and judge verdicts reference the attempt they judged (see AGENTS.md, "Machine comments"). The external reviewer re-derived the system's own concept from this document alone, which is evidence the boundary is natural rather than invented. Corylus's job is to make it a first-class object instead of a comment convention.

### 5.7 Event-driven canonical state (update semantics, revised)

"Worker rewrites the note at every checkout" is reasonable for an alpha but must not become the fundamental consistency mechanism. The canonical system is **event-driven**:

```
session.started · artifact.changed · verification.recorded
session.completed · review.requested · review.completed
ticket.blocked · ticket.resumed
```

Corylus derives machine-known state (lifecycle, sessions, verification records, review history) from these events. The agent supplies only the genuinely semantic information the system cannot infer: what I think is happening, why I made this decision, what should happen next.

This structurally reduces the failure mode v1 could only mitigate through re-grounding: `actual state = X, status note says Y`. Better than reconciling the discrepancy is not asking the agent to manually duplicate machine-known state in the first place.

**Two-tier reality check:** today's Hermes pipeline has no event bus — worker-authored text is the only mechanism that exists there. So the tiers are:
- **Interim (today):** the narrowed four-field note + verification manifest + Sessions line, rewritten at check-out. Re-grounding ritual stays load-bearing.
- **Corylus (native):** events carry the machine-known state; the worker note shrinks to the semantic four fields; sessions and artifacts are captured by the backend, not transcribed by agents.

### 5.8 Persistence, repositioned (the principle)

> **Semantic continuity belongs to the ticket. Runtime continuity is optional.**

Because the ticket now carries the durable state and the worker note carries the semantic context, a runtime session is a disposable implementation detail. Whether Corylus resumes an existing Hermes session or creates a fresh one hydrated from the ticket becomes a per-runtime optimization:

```
ticket → attempt → resume existing session? yes → resume
                                    no  → create new session + hydrate from ticket
```

Nothing above that layer cares. Position A is thereby *permittable later* without being load-bearing now — which resolves the v1 tension between Julian's continuity instinct and the drift/recovery risks: the instinct is honored at the semantic layer, the risk is contained at the runtime layer.

### 5.9 The conceptual hierarchy (summary table)

| Layer | Concept | Nature |
|---|---|---|
| Parent ticket | planning container; its work is its children | planning |
| Ticket (leaf) | durable identity and canonical state | work |
| Attempt | coherent effort to advance the ticket | work |
| Session | disposable runtime execution | infrastructure |
| Artifact | produced work | evidence |
| Verification | evidence about that work | evidence |
| Review | independent judgment | evidence |
| Transcript | forensic/debugging record | evidence (secondary) |
| Worker note | semantic context that can't be derived | judgment |

### 5.10v2 The ticket page as the first-class interface (UX)

The interface mirrors the backend hierarchy: the ticket is the primary key of work (§5v2), so the ticket page is the primary *surface* of work. Everything else — sessions, verdicts, artifacts, transcripts — renders **inside** the ticket page rather than being a place the user navigates to.

Layout skeleton (structure, not visual design — the alpha plan defers visual identity):

```
┌ TICKET #412 — [state: in review] — p2 — attempt 2 · vulcan
├─ Worker note:  Current state · Next · Blocked by · Assumptions   ← the 30-second scan
├─ Last verification: ✅ 37/37, clean checkout (attempt 2, 14:02)
├─ Artifacts: branch · diff · docs
├─ Timeline
│   ├ Attempt 1 — vulcan — 2 sessions — ⚠ remediated
│   │  └ Review 1 — archon → rejected: clean checkout fails
│   └ Attempt 2 — vulcan — 1 session
│      └ Review 2 — archon → accepted (0.9)
│      (each attempt expands: sessions w/ runtime metadata, artifacts, verification, transcript)
└─ Actions: approve · send back · discard · comment              ← the human judgment surface
```

Principles:

1. **State first, evidence folded.** Progressive disclosure is load-bearing: the default view (state, worker note, last verification, collapsed timeline) must satisfy the one-minute acceptance criterion even on a ticket with many attempts and sessions. Forensics (session transcripts, full verification records) are one click away — never zero, never on the default surface. This is how the page stays calm and spacious per the alpha-plan UI principles while carrying deep evidence.
2. **Sessions are not top-level navigation.** A session is infrastructure (§5.9); it appears only as metadata within an attempt (start/end, duration, runtime). The user experience consequence: **there is no "go to session" place in the interface at all** — the session-scatter problem is dissolved by making sessions un-navigable rather than better-organized.
3. **The ticket page is the action surface, not only a reading surface.** Human judgments (approve / send back / discard, per the Corylus README flow) happen on the ticket page, aimed at the attempt or review they judge. Verdicts render where the work happened (the timeline); verdicts *needing action* additionally surface in the attention zone (alpha plan: keep requests for attention distinct from general activity). Responsive-UI requirements apply to these actions (immediate feedback, pending vs. confirmed state, drafts preserved).
4. **Every path converges on the ticket page.** Digest entries, landing-page attention items, and inbox mentions deep-link to ticket pages. The ticket page is the destination of the entire notification graph; nothing routes the user to a raw session or transcript view.
5. **Consistency rule for the build:** nothing appears in the interface that is not in the §5.9 hierarchy, and every element of the hierarchy has an explicit rendering decision (visible / folded / on-demand). This is the guard against the ticket page accreting into a dashboard-in-a-page.

### 5.11v2 Recursive tickets: atomic work, planned parents

Requirement (Julian): the **leaf ticket is the atomic unit of work from a planning perspective**, and tickets may be **children of other tickets**. These compose into one rule:

- **Leaf ticket (no children):** the atomic unit of work. Everything in §5v2 binds here — claims, attempts, sessions, verification, reviews, the worker note. Planning happens *before* a leaf exists (proposals) or *above* it (its parent).
- **Parent ticket (has children):** a planning container. It is never claimed, dispatched, or worked directly; its "work" is its children. It carries the planning note (why this decomposition, what "done" means for the whole) and a **derived rollup** of child state.

A ticket becomes a parent the moment it gains a child and returns to leaf-hood if its children are removed or completed away — so the common "this is bigger than I thought, split it" moment needs no migration step.

**Why this is validated, not speculative:** the existing pipeline already runs this exact pattern across two systems — a deliverable tracker task with a tactical tree beneath it (an epic with bounded children, per-child claim/review gates, parent completion gated on all children passing). Native recursion removes the *seam* between those systems, whose friction is well documented operationally (dual id spaces, stale child-id snapshots, close procedures that must re-discover children live, status not derivable from the tracker alone). The design carries those operational lessons forward as constraints:

1. **Rollup is derived at read-time, never cached as truth.** Parent state recomputes from live children on every render. A cached "parent done" flag is the class of bug this pattern exists to kill.
2. **Never-self-close at both levels, independently.** Children are judged as work. A parent's completion gets its own verification review by an identity that did not work the children — parent completion is a review gate, not arithmetic.
3. **Decomposition children enter through the proposal mechanism** — subject to promotion policy and duplicate checks like any ticket. This is the firewall against agent child-spam; children-per-parent and promotion rate are measured quantities (alpha plan: proposal volume discipline), not vibes.
4. **Depth is unbounded by rule; governed by measurement and rendering.** No hard depth cap. The two risks depth could create are handled directly: (a) the one-minute read survives any depth via collapse-by-default rendering at every level — a depth-5 subtree folded reads the same as depth-2 unfolded; (b) zombie visibility comes from inactivity propagation (constraint 5), which is depth-independent. Subtree depth distribution is a measured quantity surfaced in governance views alongside children-per-parent. Unusual depth triggers review *attention* — a reviewer examines the decomposition and may flatten it — but never mechanical denial.
5. **Inactivity propagates up.** A stalled child flags its parent; a parent with no child movement is itself flaggable. Zombies must be visible at the level where intervention happens.
6. **One worker at a time per leaf; parents have no worker.** Claim semantics stay leaf-only, preserving concurrent-ownership rules unchanged.

**UX composition:** the §5.10v2 ticket page needs no new view type. A parent page *is* the ticket page with the timeline band rendering **children instead of attempts** (each child row: state chip + one-line note, clicking through to the same component). The acceptance criterion scales: open a parent, read the whole subtree in under a minute.

**New failure modes this introduces (and their counters):** zombie parents (decomposed, children stalled) → upward inactivity propagation + parent-level flags; rollup lies (parent says done, a child isn't) → derive-at-read; over-decomposition → promotion policy for children + measured children-per-parent; runaway depth → collapse-by-default rendering + depth-distribution measurement + review attention (never mechanical denial); render cost of deep derived rollups → trivial at alpha scale, and a perf cache invalidated by child events is acceptable *because it is a cache*, not truth (distinct from constraint 1).

---

## 6. Failure modes and mitigations

| Failure mode | Mitigation |
|---|---|
| Note becomes boilerplate / stale | Rewrite (not append) at every check-out; staleness is a visible, flagged condition (§5.6.3, librarian in 5.5); note includes writer + timestamp |
| Note contains wrong info; next agent trusts it | Check-in ritual: live state always wins; note is a briefing; disagreements are corrected as step 3 |
| Worker skips the note (hustle) | It's in the dispatch prompt as a check-out requirement; handoff completeness is judge-reviewable |
| Proof field gamed (claimed, not run) | Judge verifies Proof against artifacts; a false Proof is a rework verdict (this is exactly today's judge behavior, made easier) |
| Ticket with many sessions → clutter | Session list collapses to one-line outcomes; transcripts remain on demand |
| Note conflicts with judge verdict | Verdict is a comment; note must be rewritten to reflect it at next check-out — conflict stays visible in history |
| Persistence temptation returns ("just keep the session alive") | Re-read §4: measurement + rework data. If latency-to-work ever *is* measured as a real cost, revisit with data — the checkpoint design doesn't preclude later persistence; it sequences it safely |
| Ticket page bloats into a dashboard-in-a-page | §5.10v2 principle 5: every UI element must map to a §5.9 hierarchy element with an explicit rendering decision (visible/folded/on-demand); anything else is out of scope for the page |
| User tries to navigate to "a session" directly | §5.10v2 principle 2: sessions are attempt metadata only; deep links always resolve to the owning ticket page with the attempt expanded |

## 7. What this design deliberately does NOT do

- Does not make any agent process long-lived.
- Does not give agents hidden memory across runs (per-agent memory architecture is governed separately by the #206 decision chain; per-bank asymmetry is Julian's established position — each agent knows what its role calls for, not a uniform profile).
- Does not change judge visibility rules or the never-self-close gate.
- Does not alter Vikunja's role as tracker of record in the current pipeline, and does not authorize any implementation in the current alpha stage of Corylus.

## 8. Open questions for the Corylus design pass

1. Where does the worker note live — a ticket field (single mutable document, versioned) vs. a distinguished first comment? (Lean: versioned field, revisions preserved — matches page-first knowledge.)
2. Session auto-capture vs. worker-reported: v2 leans hard to auto-capture (§5.1v2) — the open part is the capture mechanism (API observation vs. runtime attestation vs. worker attestation as fallback).
3. Does the verification record get a standardized schema per project type (code vs. ops vs. research)? (Lean: yes, light per-project templates; structured at the record level, rendered as one human line.)
4. Staleness thresholds: what counts as "the note is behind" — time, or check-ins-since-update? (Lean: check-ins, not wall-clock.)
5. Does the judge *write back* to the note (e.g., appending "verdict received") or strictly comment? (Lean: judge writes `review.completed` events and comments; the note belongs to workers.)
6. Attempt boundaries: what *starts* attempt n+1 — a review rejection, a worker-initiated handoff, a wake-after-limit? (Lean: review rejection and explicit re-dispatch both start one; a mid-run wake that continues the same coherent effort does not.)
7. Event vocabulary: is the §5.7 list complete and minimal for alpha, or do `attempt.started` / `attempt.abandoned` need to be first-class events? (Lean: yes — attempts deserve their own events so review-rejection → re-attempt chains are queryable.)
8. Verdict-action UX: when a human sends work back from the ticket page, does that automatically open attempt n+1 (a new attempt record awaiting claim), or does the re-dispatch remain a separate human/agent action? (Lean: sending back creates the attempt shell immediately; claiming it is a separate act — matches capture/promotion separation in the alpha plan.)
9. Parent completion review: who verifies a parent whose children all passed — a dedicated reviewer identity, the librarian, or a configured policy per workspace? (Lean: policy-configurable with a default distinct-identity review, mirroring the existing epic-review step; the parent gate must stay a review, not arithmetic.)
10. Child re-parenting: when a decomposition is flattened or reorganized mid-flight, what happens to completed children, their attempts, and their review records? (Lean: records follow the ticket, provenance preserved; the move is an attributed event, matching page-move tolerance in the alpha plan.)
11. Rollup rendering for deep trees: does the parent page ever aggregate below level 1 (grandchildren folded into a child's chip), or always show direct children only? (Lean: direct children only, each expandable — consistent collapse-by-default; aggregated counts as a measured governance view, not the working surface.)

## 9. Summary for the decision-maker

- **Julian's position** (persistent session per ticket) identified the true requirement — continuity per ticket — and motivated the investigation. v2 honors it at the *semantic* layer (§5.8): the ticket carries the continuity, and runtime session-resume becomes a permitted-later optimization, not a foundation.
- **nomos's position** (ticket as the backend organizing principle) directly serves the stated goal — Julian never hunts for the right session — while preserving the safety properties (re-grounding, stateless workers, judge independence) that the current pipeline's track record depends on.
- **External review (GPT-6 Astra)** endorsed Position B as the direction, contributed the state/note split, the Ticket → Attempt → Session hierarchy, event-driven canonical state, and a correction to the empirical claim in §4 (kept, with credit, as reasoning-trail).
- **The v2 architecture in one line:** `ticket + attempts + sessions + structured state/evidence + a small human-readable worker note` — with the hierarchy: Ticket = durable identity · Attempt = coherent effort · Session = disposable execution · Artifact/Verification/Review/Transcript = evidence · Worker note = the judgment that can't be derived.
- **The central acceptance criterion is unchanged:** open one ticket and understand the work in under a minute — now met by rendered structured state plus a four-field note, without turning an LLM-maintained blob into a second database.
- **UX encoding (Julian, this revision):** the ticket page is the first-class interface (§5.10v2) — sessions have no top-level navigation, verdicts render in the attempt timeline, and all human judgment actions live on the ticket page. The interface is the backend hierarchy, made visible.
- **Recursion (Julian, this revision):** the leaf ticket is the atomic unit of work; parents are planning containers (§5.11v2). Depth is unbounded by rule — governed by collapse-by-default rendering, measured depth distribution, and review attention, never mechanical denial. Validated by the existing two-tracker epic pattern; native recursion removes that seam.
- **Next step:** fold §5v2 into the Corylus alpha-plan's design pass (Stage 2: shared records and interfaces) as proposed requirements — notably attempts as first-class objects (upgrading the existing `hermes:attempt` comment convention), the event vocabulary of §5.7, the ticket-first interface rules of §5.10v2, and recursive tickets with leaf-atomic work semantics (§5.11v2); the interim discipline (§5.6, narrowed note) is available immediately on today's pipeline if Julian wants it filed as a ticket.
