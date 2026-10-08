import Runner.Model

namespace Runner

set_option maxHeartbeats 2000000

/-- Independent reviewer eligibility checks both configured tracker identities. -/
theorem reviewer_identity_distinct (c : Config) (h : reviewerIndependent c = true) :
    c.reviewerSession ≠ c.workerSession ∧ c.reviewerSession ≠ c.creatorSession := by
  simp [reviewerIndependent, independent] at h
  exact h.2

/-- The same eligibility boundary applies to an independent waiver closer. -/
theorem closer_identity_distinct (c : Config) (h : closerIndependent c = true) :
    c.closerSession ≠ c.workerSession ∧ c.closerSession ≠ c.creatorSession := by
  simp [closerIndependent, independent] at h
  exact h.2

/-- R060–R061: a new tracker approval receipt uses an independent actor.
The premise distinguishes a newly acquired receipt from previously stored data. -/
theorem tracker_approval_identity (c : Config) (s : State) (f : Facts)
    (hnew : (step c s { kind := .trackerApproved, facts := f }).approvalSession ≠ s.approvalSession) :
    s.actorSession ≠ c.workerSession ∧ s.actorSession ≠ c.creatorSession := by
  simp only [step] at hnew
  split at hnew
  · exact False.elim (hnew rfl)
  · simp [rowStep] at hnew
    split at hnew
    · rename_i h
      simp_all [independent]
    · exact False.elim (hnew rfl)

/-- R058: an acquired closer approval receipt uses an independent closer. -/
theorem closer_approval_identity (c : Config) (s : State) (f : Facts)
    (hp : s.phase = .closerRunning)
    (hnew : (step c s { kind := .jobFinished, facts := f }).approvalSession ≠ s.approvalSession) :
    c.closerSession ≠ c.workerSession ∧ c.closerSession ≠ c.creatorSession := by
  simp only [step] at hnew
  split at hnew
  · exact False.elim (hnew rfl)
  · simp [rowStep, hp] at hnew
    split at hnew
    · exact False.elim (hnew rfl)
    · split at hnew
      · rename_i h
        have hi : closerIndependent c = true := by
          simp_all
        exact closer_identity_distinct c hi
      · exact False.elim (hnew rfl)

/-- R065: actual merge intent requires approval for the exact current head. -/
theorem merge_ready_guard (c : Config) (s : State) (f : Facts)
    (hnew : s.mergeRequests < (step c s { kind := .prReady, facts := f }).mergeRequests) :
    s.phase = .merging ∧ s.approved = true ∧ s.reviewedSha = some s.headSha ∧
    f.headCurrent = true ∧ f.checksValid = true ∧ f.draftReady = true := by
  simp only [step] at hnew
  split at hnew
  · exact False.elim (Nat.lt_irrefl _ hnew)
  · simp [rowStep] at hnew
    split at hnew
    · simp_all [acceptedHead, exactHead]
    · exact False.elim (Nat.lt_irrefl _ hnew)

/-- R066: an already-ready merge has the same independent acceptance/SHA gates. -/
theorem merge_requested_guard (c : Config) (s : State) (f : Facts)
    (hnew : s.mergeRequests < (step c s { kind := .mergeRequested, facts := f }).mergeRequests) :
    s.phase = .merging ∧ s.approved = true ∧ s.reviewedSha = some s.headSha ∧
    f.headCurrent = true ∧ f.checksValid = true ∧ f.draftReady = true := by
  simp only [step] at hnew
  split at hnew
  · exact False.elim (Nat.lt_irrefl _ hnew)
  · simp [rowStep] at hnew
    split at hnew
    · simp_all [acceptedHead, exactHead]
    · exact False.elim (Nat.lt_irrefl _ hnew)

/-- R067: a newly observed merged outcome has approval for its exact receipt SHA. -/
theorem merged_receipt_guard (c : Config) (s : State) (f : Facts)
    (hp : s.phase ≠ .done)
    (hd : (step c s { kind := .prMerged, facts := f }).phase = .done) :
    (s.phase = .merging ∨ s.phase = .awaitingMerge) ∧ s.approved = true ∧
    s.reviewedSha = some s.headSha ∧ f.sha = s.headSha ∧ f.verifiedReceipt = true := by
  simp only [step] at hd
  split at hd
  · exact False.elim (hp hd)
  · simp [rowStep, withPhase] at hd
    split at hd
    · simp_all [acceptedHead, exactHead]
    · exact False.elim (hp hd)

/-- R047–R048: reaching approval or human acceptance from review requires
an APPROVE verdict from a distinct, eligible reviewer session. -/
theorem reviewer_approval_identity (c : Config) (s : State) (f : Facts)
    (hp : s.phase = .reviewing)
    (ha : (step c s { kind := .reviewVerdict, facts := f }).phase = .approving ∨
      (step c s { kind := .reviewVerdict, facts := f }).phase = .awaitingAcceptance) :
    f.verdict = .approve ∧ c.reviewerSession ≠ c.workerSession ∧
      c.reviewerSession ≠ c.creatorSession := by
  simp only [step] at ha
  split at ha
  · simp_all
  · cases hv : f.verdict <;>
      simp [rowStep, hp, hv, saveDecisionHold, invalidate] at ha
    all_goals split at ha <;> simp_all [reviewerIndependent, independent]
    all_goals split at ha <;> simp_all
    all_goals split at ha <;> simp_all
    all_goals split at ha <;> simp_all [reviewerIndependent, independent]

/-- R060–R061: newly acquiring approval requires an independent actor even
when the stored session ID happens to match an earlier receipt. -/
theorem tracker_approval_acquisition (c : Config) (s : State) (f : Facts)
    (hbefore : s.approved = false)
    (hafter : (step c s { kind := .trackerApproved, facts := f }).approved = true) :
    s.actorSession ≠ c.workerSession ∧ s.actorSession ≠ c.creatorSession := by
  simp only [step] at hafter
  split at hafter
  · simp_all
  · simp [rowStep] at hafter
    split at hafter
    · simp_all [independent]
    · simp_all

/-- R058: newly acquiring a waiver-closer approval obeys the same boundary. -/
theorem closer_approval_acquisition (c : Config) (s : State) (f : Facts)
    (hp : s.phase = .closerRunning) (hbefore : s.approved = false)
    (hafter : (step c s { kind := .jobFinished, facts := f }).approved = true) :
    c.closerSession ≠ c.workerSession ∧ c.closerSession ≠ c.creatorSession := by
  simp only [step] at hafter
  split at hafter
  · simp_all
  · simp [rowStep, hp] at hafter
    split at hafter
    · simp_all
    · split at hafter
      · simp_all [closerIndependent, independent]
      · simp_all

/-- Approval is a verified independent tracker receipt tied to the current head.
This invariant permits the explicitly documented independent waiver closer;
it does not assert that every approval came from an APPROVE verdict. -/
def ApprovalInvariant (c : Config) (s : State) : Prop :=
  s.approved = true → ∃ actor, s.approvalSession = some actor ∧
    actor ≠ c.workerSession ∧ actor ≠ c.creatorSession ∧
    s.reviewedSha = some s.headSha

theorem initial_approvalInvariant (c : Config) : ApprovalInvariant c (initial c) := by
  simp [ApprovalInvariant, initial]

attribute [local irreducible] ApprovalInvariant

/-- Every source-table row preserves independent, exact-head approval evidence. -/

theorem approvalInvariant_rowStep (c : Config) (s : State) (e : Event)
    (hs : ApprovalInvariant c s) : ApprovalInvariant c (rowStep c s e) := by
  cases e with
  | mk kind facts =>
    cases kind <;> simp only [rowStep, Id.run, pure]
    all_goals repeat (any_goals (split <;> try simp_all only))
    all_goals
      by_cases ha : s.approved = true
      · have hx := hs
        unfold ApprovalInvariant at hx
        rcases (hx ha) with ⟨actor, hsession, hworker, hcreator, hsha⟩
        simp_all [ApprovalInvariant, withPhase, launchAt, saveDecisionHold,
          invalidate, quiesce, rollBack, control, independent, reviewerIndependent,
          closerIndependent, exactHead]
      · simp_all [ApprovalInvariant, withPhase, launchAt, saveDecisionHold,
          invalidate, quiesce, rollBack, control, independent, reviewerIndependent,
          closerIndependent, exactHead]

/-- Schema failures and duplicate observations preserve approval evidence too. -/
theorem approvalInvariant_step (c : Config) (s : State) (e : Event)
    (hs : ApprovalInvariant c s) : ApprovalInvariant c (step c s e) := by
  unfold step
  split
  · exact hs
  · exact approvalInvariant_rowStep c s e hs

/-- Independent exact-head approval is preserved by any finite event sequence. -/
theorem approvalInvariant_run (c : Config) (s : State) (events : List Event)
    (hs : ApprovalInvariant c s) : ApprovalInvariant c (run c s events) := by
  induction events generalizing s with
  | nil => exact hs
  | cons e es ih =>
    simpa [run, List.foldl_cons] using
      ih (step c s e) (approvalInvariant_step c s e hs)

/-- Every reachable approved state has a recorded actor distinct from worker
and creator, and approval for precisely its current head. -/
theorem reachable_approval_independent_exact (c : Config) (events : List Event)
    (ha : (run c (initial c) events).approved = true) :
    ∃ actor, (run c (initial c) events).approvalSession = some actor ∧
      actor ≠ c.workerSession ∧ actor ≠ c.creatorSession ∧
      (run c (initial c) events).reviewedSha = some (run c (initial c) events).headSha := by
  have hi := approvalInvariant_run c (initial c) events (initial_approvalInvariant c)
  unfold ApprovalInvariant at hi
  exact hi ha

end Runner
