import Runner.Model

namespace Runner

set_option maxHeartbeats 2000000
-- These lists are shared across exhaustive constructor branches.
set_option linter.unusedSimpArgs false
set_option maxRecDepth 4096

/-- §5.1 terminal rows and all `S` cleanup rows preserve the terminal phase. -/
theorem terminalPhase_rowStep (c : Config) (s : State) (e : Event)
    (ht : terminal s.phase = true) : (rowStep c s e).phase = s.phase := by
  have ne (q : Phase) (hq : terminal q = false) : s.phase ≠ q := by
    intro he
    rw [he, hq] at ht
    contradiction
  have h_queued := ne .queued rfl
  have h_building := ne .building rfl
  have h_gating := ne .gating rfl
  have h_reviewing := ne .reviewing rfl
  have h_awaitingAcceptance := ne .awaitingAcceptance rfl
  have h_approving := ne .approving rfl
  have h_merging := ne .merging rfl
  have h_jobAuthorizing := ne .jobAuthorizing rfl
  have h_jobRunning := ne .jobRunning rfl
  have h_jobVerifying := ne .jobVerifying rfl
  have h_jobRollingBack := ne .jobRollingBack rfl
  have h_closerRunning := ne .closerRunning rfl
  have h_quiescing := ne .quiescing rfl
  have h_finishedAwaitingHuman := ne .finishedAwaitingHuman rfl
  have h_needsDecision := ne .needsDecision rfl
  have h_dependencyBlocked := ne .dependencyBlocked rfl
  have h_paused := ne .paused rfl
  have h_awaitingMerge := ne .awaitingMerge rfl
  have h_schedulerRecovering := ne .schedulerRecovering rfl
  have h_schedulerWatching := ne .schedulerWatching rfl
  have h_schedulerStopping := ne .schedulerStopping rfl
  have h_workflow : workflow s.phase = false := by
    cases hp : s.phase <;> simp_all [terminal, workflow]
  have h_running : running s.phase = false := by
    cases hp : s.phase <;> simp_all [terminal, running]
  have h_buildReviewCloser : buildReviewCloser s.phase = false := by
    cases hp : s.phase <;> simp_all [terminal, buildReviewCloser]
  have h_serviceJob : serviceJob s.phase = false := by
    cases hp : s.phase <;> simp_all [terminal, serviceJob]
  have h_identityPhase : identityPhase s.phase = false := by
    cases hp : s.phase <;> simp_all [terminal, identityPhase]
  have h_blockerHold : blockerHold s.phase = false := by
    cases hp : s.phase <;> simp_all [terminal, blockerHold]
  have h_scheduler : scheduler s.phase = false := by
    cases hp : s.phase <;> simp_all [terminal, scheduler]
  cases e with
  | mk kind facts =>
    cases kind <;> simp_all [rowStep, Id.run, pure, withPhase, launchAt,
      saveDecisionHold, invalidate, quiesce, rollBack, control]
    all_goals split <;> simp_all

theorem terminalPhase_absorbing (c : Config) (s : State) (e : Event)
    (ht : terminal s.phase = true) : (step c s e).phase = s.phase := by
  unfold step
  split
  · rfl
  · exact terminalPhase_rowStep c s e ht

/-- Absorption holds for arbitrary finite event sequences, including cleanup. -/
theorem terminalPhase_trace (c : Config) (s : State) (es : List Event)
    (ht : terminal s.phase = true) : (run c s es).phase = s.phase := by
  induction es generalizing s with
  | nil => rfl
  | cons e es ih =>
    have hp := terminalPhase_absorbing c s e ht
    simpa [run, List.foldl_cons, hp] using ih (step c s e) (by simpa [hp] using ht)

/-- Valid counters and a reserved next round whenever a worker attempt has not
started. Positive round caps make this true at initialization. -/
def WithinLimits (c : Config) (s : State) : Prop :=
  s.rounds ≤ c.maxRounds ∧
  (s.workerStarted = false → s.rounds < c.maxRounds) ∧
  s.nudges ≤ c.finishNudges ∧ s.launchRetries ≤ c.launchRetries ∧ s.retries ≤ c.runRetries

theorem initial_withinLimits (c : Config) (hc : 0 < c.maxRounds) :
    WithinLimits c (initial c) := by
  simp [WithinLimits, initial, hc]

attribute [local irreducible] WithinLimits

/-- §5.1 round, nudge, absent-child launch-retry and safe run-retry guards. -/

theorem budgets_rowStep (c : Config) (s : State) (e : Event)
    (hs : WithinLimits c s) : WithinLimits c (rowStep c s e) := by
  have hfull := hs
  unfold WithinLimits at hs
  rcases hs with ⟨hr, hw, hn, hl, hf⟩
  rcases e with ⟨kind, facts⟩
  cases kind <;> simp only [rowStep, Id.run, pure]
  repeat (any_goals (split <;> try simp_all only [Id.run, pure]))
  all_goals simp_all [WithinLimits, withPhase, launchAt, saveDecisionHold,
    invalidate, quiesce, rollBack, control]
  all_goals omega

/-- Invalid schema, stale run/effect identity and duplicate receipt events stutter. -/
theorem invalid_event_unchanged (c : Config) (s : State) (e : Event)
    (h : e.facts.schemaValid = false ∨ e.facts.current = false ∨ e.facts.duplicate = true) :
    step c s e = s := by
  rcases h with h | h | h <;> simp [step, h]

theorem budgets_preserved (c : Config) (s : State) (e : Event)
    (hs : WithinLimits c s) : WithinLimits c (step c s e) := by
  unfold step
  split
  · exact hs
  · exact budgets_rowStep c s e hs

theorem budgets_trace (c : Config) (s : State) (es : List Event)
    (hs : WithinLimits c s) : WithinLimits c (run c s es) := by
  induction es generalizing s with
  | nil => exact hs
  | cons e es ih =>
    simpa [run, List.foldl_cons] using ih (step c s e) (budgets_preserved c s e hs)

/-- All finite traces from initialization respect a positive configured cap,
and the per-attempt/per-stage nudge and retry budgets. -/
theorem initial_trace_budgets (c : Config) (es : List Event) (hc : 0 < c.maxRounds) :
    (run c (initial c) es).rounds ≤ c.maxRounds ∧
    (run c (initial c) es).nudges ≤ c.finishNudges ∧
    (run c (initial c) es).launchRetries ≤ c.launchRetries ∧
    (run c (initial c) es).retries ≤ c.runRetries := by
  have hb := budgets_trace c (initial c) es (initial_withinLimits c hc)
  unfold WithinLimits at hb
  exact ⟨hb.1, hb.2.2⟩

/-- New confirmed worker attempts consume a strictly decreasing round measure.
This bounds attempts; pause/resume process launches have a separate counter. -/
def remainingRounds (c : Config) (s : State) : Nat := c.maxRounds - s.rounds

theorem workerRound_measure (c : Config) (s : State) (e : Event)
    (hs : WithinLimits c s) (hnew : (step c s e).rounds = s.rounds + 1) :
    remainingRounds c (step c s e) < remainingRounds c s := by
  have hb := budgets_preserved c s e hs
  unfold WithinLimits at hb
  have hcap := hb.1
  simp only [remainingRounds]
  omega

/-- A malformed normalized verdict fails closed and remains terminal under
any later event sequence; the adapter's raw-text parser is outside the model. -/
theorem malformed_never_merges (c : Config) (s : State) (es : List Event)
    (hp : s.phase = .reviewing) :
    (run c (step c s { kind := .reviewVerdict, facts := { verdict := .malformed } }) es).phase = .failed := by
  have hf : (step c s { kind := .reviewVerdict, facts := { verdict := .malformed } }).phase = .failed := by
    simp [step, rowStep, Id.run, pure, hp]
  have ht : terminal (step c s { kind := .reviewVerdict, facts := { verdict := .malformed } }).phase = true := by
    simp [hf, terminal]
  exact (terminalPhase_trace c _ es ht).trans hf

end Runner
