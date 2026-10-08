import Runner.Model

namespace Runner

set_option maxHeartbeats 2000000

/-- §5.1 R128–R129: every nonterminal phase admits an observed fatal-storage
outcome. This is existential outcome reachability, possibly nondurable. It
does not claim productive completion, child cleanup, or safe lease release. -/
theorem canTerminate (c : Config) (s : State) (h : terminal s.phase = false) :
    ∃ events : List Event, terminal (run c s events).phase = true := by
  refine ⟨[{ kind := .storageFailed }], ?_⟩
  cases hp : s.phase <;> simp [terminal, hp] at h
  all_goals
    simp [run, step, rowStep, scheduler, workflow, withPhase, hp, terminal]

/-- §5.1 R095, R097, R099, R101: with no changed service state, no live child
or unresolved effect, explicit stop plus a verified cancellation receipt
reaches stopped. Restoration already in progress must finish separately. -/
theorem healthyStopTerminates (c : Config) (s : State)
    (hw : workflow s.phase = true)
    (hr : s.phase ≠ .jobRollingBack)
    (hs : s.service = .unchanged)
    (hc : s.child = .absent)
    (he : s.effectUnresolved = false) :
    (run c s [{ kind := .stopRequested }, { kind := .cancelVerified }]).phase = .stopped := by
  cases hp : s.phase <;> simp [workflow, hp] at hw
  all_goals
    simp_all [run, step, rowStep, workflow, serviceJob, safe, control, quiesce,
      pauseOriginValid, active, hold]

/-- Standalone jobs have only job, control, blocker and terminal outcomes.
Closer jobs deliberately belong to the ticket workflow, not this set. -/
def JobPhase (p : Phase) : Prop := p ∈ [Phase.queued, .jobAuthorizing, .jobRunning,
  .jobVerifying, .jobRollingBack, .quiescing, .jobSucceeded, .needsDecision,
  .dependencyBlocked, .paused, .failed, .stopped, .jobFailed, .jobRolledBack,
  .jobRollbackFailed]

def JobReturn (p : Phase) : Prop := p ∈ [Phase.jobAuthorizing, .jobRunning, .jobVerifying]

def JobPauseReturn (p : Phase) : Prop := p ∈ [Phase.queued, .jobAuthorizing,
  .jobRunning, .jobVerifying, .needsDecision, .dependencyBlocked]

private theorem jobReturn_phase (p : Phase) (h : JobReturn p) : JobPhase p := by
  cases p <;> simp_all [JobReturn, JobPhase]

private theorem jobPauseReturn_phase (p : Phase) (h : JobPauseReturn p) : JobPhase p := by
  cases p <;> simp_all [JobPauseReturn, JobPhase]

def JobInvariant (s : State) : Prop :=
  JobPhase s.phase ∧
  (s.continuation = .job ∨ s.continuation = .savedPhase) ∧
  JobReturn s.returnState ∧ JobPauseReturn s.pauseReturnState ∧
  (s.controlTarget = none ∨ s.controlTarget = some .paused ∨
    s.controlTarget = some .stopped ∨ s.controlTarget = some .needsDecision) ∧
  s.approved = false ∧ s.reviewedSha = none ∧ s.waiverAccepted = false ∧
  s.waiverSha = none ∧ s.mergeRequests = 0

attribute [local irreducible] JobInvariant

theorem initial_jobInvariant (c : Config) (hm : c.mode = .standaloneJob) :
    JobInvariant (initial c) := by
  simp [initial, hm, JobInvariant, JobPhase, JobReturn, JobPauseReturn]

-- The same simplification sets serve all finite phase/event cases; a lemma
-- needed in one case may be unused in another. Keep the exemption local.
set_option linter.unusedSimpArgs false in
/-- All table events preserve the standalone lane, including hostile review,
waiver, merge, saved-phase, and control events. -/
theorem jobInvariant_rowStep (c : Config) (s : State) (e : Event)
    (hs : JobInvariant s) : JobInvariant (rowStep c s e) := by
  have hsaved := hs
  simp only [JobInvariant] at hs
  rcases hs with ⟨hp, hcont, hret, hpause, htarget, happ, hreview, hwaiver, hwaiverSha, hmerge⟩
  have hretPhase := jobReturn_phase s.returnState hret
  have hpausePhase := jobPauseReturn_phase s.pauseReturnState hpause
  have ne : ∀ p, ¬ JobPhase p → s.phase ≠ p := by
    intro p hn heq
    exact hn (heq ▸ hp)
  have hb := ne .building (by simp [JobPhase])
  have hg := ne .gating (by simp [JobPhase])
  have hrev := ne .reviewing (by simp [JobPhase])
  have hac := ne .awaitingAcceptance (by simp [JobPhase])
  have hap := ne .approving (by simp [JobPhase])
  have hmer := ne .merging (by simp [JobPhase])
  have hcloser := ne .closerRunning (by simp [JobPhase])
  have hman := ne .finishedAwaitingHuman (by simp [JobPhase])
  have ham := ne .awaitingMerge (by simp [JobPhase])
  have hsr := ne .schedulerRecovering (by simp [JobPhase])
  have hsw := ne .schedulerWatching (by simp [JobPhase])
  have hss := ne .schedulerStopping (by simp [JobPhase])
  clear ne
  simp only [JobPhase, List.mem_cons, List.mem_singleton] at hp
  rcases hp with hp | hp | hp | hp | hp | hp | hp | hp | hp | hp | hp | hp | hp | hp | hp
  all_goals rcases e with ⟨kind, facts⟩
  all_goals cases kind <;> simp_all [rowStep, Id.run, pure]
  all_goals repeat (any_goals (split <;> try simp_all only [Id.run, pure]))
  all_goals
    simp_all [JobInvariant, JobPhase, JobReturn, JobPauseReturn, withPhase,
      launchAt, saveDecisionHold, invalidate, quiesce, rollBack, control,
      workflow, running, buildReviewCloser, serviceJob, identityPhase, active,
      hold, blockerHold, scheduler, pauseOriginValid, acceptedHead, exactHead]
  all_goals
    repeat (any_goals (first | (split <;> try simp_all [Id.run, pure, JobInvariant, JobPhase, JobReturn,
      JobPauseReturn, withPhase, launchAt, saveDecisionHold, invalidate, quiesce,
      rollBack, control, workflow, running, buildReviewCloser, serviceJob,
      identityPhase, active, hold, blockerHold, scheduler, pauseOriginValid,
      acceptedHead, exactHead]) | omega))
  all_goals grind

theorem jobInvariant_step (c : Config) (s : State) (e : Event)
    (hs : JobInvariant s) : JobInvariant (step c s e) := by
  unfold step
  split
  · exact hs
  · exact jobInvariant_rowStep c s e hs

theorem jobInvariant_run (c : Config) (s : State) (events : List Event)
    (hs : JobInvariant s) : JobInvariant (run c s events) := by
  induction events generalizing s with
  | nil => exact hs
  | cons e es ih =>
    simpa [run, List.foldl_cons] using ih (step c s e) (jobInvariant_step c s e hs)

/-- A standalone job never enters a forge-merge phase, records a merged ticket,
or requests a merge, for any finite normalized event sequence. -/
theorem standaloneJob_never_merges (c : Config) (events : List Event)
    (hm : c.mode = .standaloneJob) :
    (run c (initial c) events).phase ≠ .merging ∧
    (run c (initial c) events).phase ≠ .done ∧
    (run c (initial c) events).mergeRequests = 0 := by
  have hj := jobInvariant_run c (initial c) events (initial_jobInvariant c hm)
  simp only [JobInvariant] at hj
  rcases hj with ⟨hp, _, _, _, _, _, _, _, _, hmerge⟩
  refine ⟨?_, ?_, hmerge⟩
  · intro h
    simp [JobPhase, h] at hp
  · intro h
    simp [JobPhase, h] at hp

end Runner
