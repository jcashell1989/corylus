import Runner.Model

namespace Runner.Examples

set_option maxRecDepth 10000
set_option maxHeartbeats 1000000

/-- Every printed phase comes from applying `step`, including the initial phase. -/
def phases (c : Config) (events : List Event) : List Phase :=
  (trace c (initial c) events).map (·.phase)

def outcome (c : Config) (events : List Event) : Phase :=
  (run c (initial c) events).phase

def showTrace (name : String) (c : Config) (events : List Event) : String :=
  name ++ ": " ++ String.intercalate " -> "
    ((phases c events).map fun p => (reprStr p).replace "Runner.Phase." "")

def auto : Config := {}
def manual : Config := { mergePolicy := .manual }
def accepting : Config := { humanAcceptanceRequired := true }
def job : Config := { mode := .standaloneJob }
def schedulerConfig : Config := { mode := .scheduler }

def event (kind : EventKind) : Event := { kind }
def approve : Event := { kind := .reviewVerdict }
def reject : Event := { kind := .reviewVerdict, facts := { verdict := .reject } }
def malformed : Event := { kind := .reviewVerdict, facts := { verdict := .malformed } }
def needsDecision : Event := { kind := .reviewVerdict, facts := { verdict := .needsDecision } }
def waiver : Event := { kind := .decisionRecorded, facts := { decision := .acceptWaiver } }

def worker : List Event := [event .admissionChecked, event .runStarted]
def gated : List Event := worker ++ [event .runFinished, event .gatePassed]
def reviewed : List Event := gated ++ [event .runStarted, approve]
def approved : List Event := reviewed ++ [event .trackerApproved]
def jobStart : List Event := [event .admissionChecked, event .authorizationChecked,
  event .runStarted]

-- §5.1 happy automatic lane, manual completion and explicit later authorization.
def happyAuto : List Event := approved ++ [event .prReady, event .mergeRequested,
  event .prMerged]
example : outcome auto happyAuto = .done := by decide
#eval showTrace "happy_auto" auto happyAuto

/-- §5.1 R113/R114 permit terminal cleanup data to change while the outcome
phase is absorbing. This refutes full-State equality as the interpretation
of terminal absorption; it does not restart completed work. -/
def terminalCleanup : List Event := happyAuto ++ [event .effectObserved]
theorem terminal_cleanup_phase : outcome auto terminalCleanup = .done := by decide
theorem terminal_cleanup_data_counterexample :
    run auto (initial auto) terminalCleanup ≠ run auto (initial auto) happyAuto := by
  intro h
  have receipts := congrArg State.receiptCount h
  have completedCount : (run auto (initial auto) happyAuto).receiptCount = 0 := by decide
  have cleanupCount : (run auto (initial auto) terminalCleanup).receiptCount = 1 := by decide
  have impossible : (1 : Nat) = 0 := cleanupCount.symm.trans (receipts.trans completedCount)
  exact Nat.noConfusion impossible
theorem terminal_cleanup_receipt :
    (run auto (initial auto) terminalCleanup).receiptCount = 1 := by decide
#eval showTrace "terminal_cleanup_keeps_done_but_changes_receipt_data" auto terminalCleanup

-- §5.1 R025/R031/R047–R048/R060–R061/R067: workers may produce a new
-- head. Gates, independent review, tracker approval and merge receipt must
-- then refer to that new head, rather than the initial workspace SHA.
def eventAtSha (kind : EventKind) (sha : Nat) : Event :=
  { kind, facts := { sha } }
def newHeadGated : List Event := worker ++
  [eventAtSha .runFinished 2, event .gatePassed, event .runStarted]
def newHeadReviewed : List Event := newHeadGated ++ [eventAtSha .reviewVerdict 2]
def newHeadApproved : List Event := newHeadReviewed ++ [eventAtSha .trackerApproved 2]
def newHeadMerged : List Event := newHeadApproved ++
  [eventAtSha .mergeRequested 2, eventAtSha .prMerged 2]
theorem worker_new_sha_merge : outcome auto newHeadMerged = .done := by decide
theorem worker_new_sha_head : (run auto (initial auto) newHeadMerged).headSha = 2 := by decide
theorem worker_new_sha_review :
    (run auto (initial auto) newHeadMerged).reviewedSha = some 2 := by decide
theorem worker_new_sha_approval :
    (run auto (initial auto) newHeadMerged).approved = true := by decide
#eval showTrace "worker_new_sha_gated_reviewed_approved_merged" auto newHeadMerged

theorem stale_review_sha_refused :
    outcome auto (newHeadGated ++ [eventAtSha .reviewVerdict 1]) = .reviewing := by decide
theorem stale_tracker_sha_refused :
    outcome auto (newHeadReviewed ++ [eventAtSha .trackerApproved 1]) = .approving := by decide
theorem stale_merge_receipt_sha_refused :
    outcome auto (newHeadApproved ++ [eventAtSha .prMerged 1]) = .merging := by decide
#eval showTrace "stale_review_sha_refused" auto (newHeadGated ++ [eventAtSha .reviewVerdict 1])
#eval showTrace "stale_tracker_sha_refused" auto (newHeadReviewed ++ [eventAtSha .trackerApproved 1])
#eval showTrace "stale_merge_receipt_sha_refused" auto (newHeadApproved ++ [eventAtSha .prMerged 1])

example : outcome manual approved = .finishedAwaitingHuman := by decide
#eval showTrace "manual_hold" manual approved

/-- §5.1 manual resume records authorization; a resume note alone grants none. -/
def authorizedManualMerge : List Event := approved ++
  [{ kind := .resumeRequested, facts := { manualMergeAuthorized := true } },
   event .admissionChecked, event .mergeRequested, event .prMerged]
theorem manual_merge_counterexample : outcome manual authorizedManualMerge = .done := by decide
theorem manual_merge_request_counterexample :
    (run manual (initial manual) authorizedManualMerge).mergeRequests = 1 := by decide
example : outcome manual (approved ++ [event .resumeRequested]) = .finishedAwaitingHuman := by decide
#eval showTrace "manual_authorized_merge_counterexample_to_auto_only" manual authorizedManualMerge
#eval showTrace "manual_resume_without_authority" manual (approved ++ [event .resumeRequested])

-- §5.1 acceptance hold, saved acceptance/free-slot retry, and declined acceptance.
example : outcome accepting reviewed = .awaitingAcceptance := by decide
#eval showTrace "awaiting_acceptance" accepting reviewed
def acceptanceThenMerge : List Event := reviewed ++
  [{ kind := .decisionRecorded, facts := { decision := .acceptance, slotFree := false } },
   event .acceptanceReady, event .trackerApproved, event .prMerged]
example : outcome accepting acceptanceThenMerge = .done := by decide
#eval showTrace "acceptance_slot_retry_then_merge" accepting acceptanceThenMerge
def declined : List Event := reviewed ++
  [{ kind := .decisionRecorded, facts := { decision := .declineAcceptance } }]
example : outcome accepting declined = .acceptanceDeclined := by decide
#eval showTrace "acceptance_declined" accepting declined

-- §5.1 each resumable hold has a reachable trace from the documented initial state.
def blocked : List Event :=
  [{ kind := .admissionChecked, facts := { dependenciesSatisfied := false } }]
example : outcome auto blocked = .dependencyBlocked := by decide
#eval showTrace "dependency_blocked" auto blocked
def decisionHold : List Event := gated ++ [event .runStarted, needsDecision]
example : outcome auto decisionHold = .needsDecision := by decide
#eval showTrace "needs_decision" auto decisionHold
def pausedRun : List Event := worker ++ [event .pauseRequested, event .cancelVerified]
example : outcome auto pausedRun = .paused := by decide
#eval showTrace "paused" auto pausedRun
def mergeHold : List Event := approved ++ [event .mergeBlocked]
example : outcome auto mergeHold = .awaitingMerge := by decide
#eval showTrace "awaiting_merge" auto mergeHold
example : outcome auto (mergeHold ++ [event .prMerged]) = .done := by decide
#eval showTrace "lost_merge_response_then_readback" auto (mergeHold ++ [event .prMerged])

-- §5.1 terminal failures; each concrete trace checks its final outcome in the kernel.
def buildFailure : List Event := worker ++ [event .runFailed]
example : outcome auto buildFailure = .failed := by decide
#eval showTrace "build_run_failed" auto buildFailure
example : outcome auto [event .admissionChecked, event .workspaceFailed] = .failed := by decide
#eval showTrace "workspace_failed" auto [event .admissionChecked, event .workspaceFailed]
example : outcome auto (worker ++ [event .runFinished, event .gateError]) = .failed := by decide
#eval showTrace "gate_error" auto (worker ++ [event .runFinished, event .gateError])
example : outcome auto (worker ++ [event .runFinished, event .gateFailed]) = .failed := by decide
#eval showTrace "gate_failed" auto (worker ++ [event .runFinished, event .gateFailed])
example : outcome auto (reviewed ++ [event .trackerFailed]) = .failed := by decide
#eval showTrace "tracker_failed" auto (reviewed ++ [event .trackerFailed])
example : outcome auto (approved ++ [event .mergeUnsupported]) = .failed := by decide
#eval showTrace "merge_unsupported" auto (approved ++ [event .mergeUnsupported])
def malformedFailure : List Event := gated ++ [event .runStarted, malformed,
  event .trackerApproved, event .prMerged]
theorem malformed_verdict_failure_example : outcome auto malformedFailure = .failed := by decide
#eval showTrace "malformed_verdict_blocks_merge" auto malformedFailure
def rejectedAtCap : List Event := gated ++ [event .runStarted, reject]
example : outcome { auto with maxRounds := 1 } rejectedAtCap = .roundExhausted := by decide
#eval showTrace "reject_at_round_cap" { auto with maxRounds := 1 } rejectedAtCap
example : outcome { auto with maxRounds := 0 } [event .admissionChecked] = .roundExhausted := by decide
#eval showTrace "admission_round_exhausted" { auto with maxRounds := 0 } [event .admissionChecked]
def stoppedRun : List Event := worker ++ [event .stopRequested, event .cancelVerified]
example : outcome auto stoppedRun = .stopped := by decide
#eval showTrace "stopped" auto stoppedRun
def expiredRun : List Event := worker ++
  [{ kind := .ticketDeadline, facts := { deadlineEnabled := true, deadlineExpired := true } },
   event .cancelVerified]
example : outcome auto expiredRun = .stopped := by decide
#eval showTrace "ticket_deadline" auto expiredRun

-- §5.1 standalone job states: no worker/reviewer/forge path is used.
def jobSuccess : List Event := jobStart ++ [event .jobFinished]
example : outcome job jobSuccess = .jobSucceeded := by decide
#eval showTrace "job_succeeded" job jobSuccess
def serviceSuccess : List Event := jobStart ++
  [{ kind := .jobFinished, facts := { serviceRunbook := true } }, event .jobVerified]
example : outcome job serviceSuccess = .jobSucceeded := by decide
#eval showTrace "service_job_verified" job serviceSuccess
def jobFailure : List Event := jobStart ++ [event .jobFailed]
example : outcome job jobFailure = .jobFailed := by decide
#eval showTrace "job_failed" job jobFailure
example : outcome job (jobStart ++ [event .runFailed]) = .jobFailed := by decide
#eval showTrace "job_run_failed" job (jobStart ++ [event .runFailed])

def changedService (backup : Bool) : Event :=
  { kind := .effectObserved, facts := { observedService := some .changed, backupReceipt := backup } }
def serviceFailure : List Event := jobStart ++ [changedService true, event .jobFailed]
def restoredService : List Event := serviceFailure ++ [event .rollbackVerified]
example : outcome job restoredService = .jobRolledBack := by decide
#eval showTrace "job_rolled_back" job restoredService
example : outcome job (serviceFailure ++ [event .rollbackFailed]) = .jobRollbackFailed := by decide
#eval showTrace "job_rollback_failed" job (serviceFailure ++ [event .rollbackFailed])
example : outcome job (jobStart ++ [changedService false, event .jobFailed]) = .jobRollbackFailed := by decide
#eval showTrace "job_backup_unavailable" job (jobStart ++ [changedService false, event .jobFailed])
def servicePaused : List Event := jobStart ++ [changedService true,
  event .pauseRequested, event .rollbackVerified]
example : outcome job servicePaused = .paused := by decide
#eval showTrace "service_pause_restores_before_hold" job servicePaused
def serviceStopped : List Event := jobStart ++ [changedService true,
  event .stopRequested, event .rollbackVerified]
example : outcome job serviceStopped = .stopped := by decide
#eval showTrace "service_stop_restores_before_terminal" job serviceStopped

-- §5.1 accepted waiver and independently verified closer approval are an
-- alternate lane. The doc permits this even after a REJECT, without APPROVE.
def rejectThenWaiver : List Event :=
  gated ++ [event .runStarted, reject] ++
  gated ++ [event .runStarted, needsDecision, waiver,
    event .admissionChecked, event .runStarted, event .jobFinished,
    event .trackerApproved, event .mergeRequested, event .prMerged]
theorem reject_waiver_counterexample : outcome auto rejectThenWaiver = .done := by decide
theorem reject_waiver_no_approve : (rejectThenWaiver.all fun e =>
  e.kind != .reviewVerdict || e.facts.verdict != .approve) = true := by decide
theorem reject_waiver_has_reject : (rejectThenWaiver.any fun e =>
  e.kind == .reviewVerdict && e.facts.verdict == .reject) = true := by decide
theorem reject_waiver_closer_approval :
    (run auto (initial auto) rejectThenWaiver).approvalSession = some auto.closerSession := by decide
#eval showTrace "reject_then_waiver_closer_counterexample_to_approve_necessity" auto rejectThenWaiver

-- §5.1 launches caused by same-attempt pause/resume consume no new rounds.
def pauseResumeCycle : List Event := [event .pauseRequested, event .cancelVerified,
  event .resumeRequested, event .admissionChecked, event .runStarted]
def repeatedPauseResumes : Nat → List Event
  | 0 => worker
  | n + 1 => repeatedPauseResumes n ++ pauseResumeCycle
example : outcome auto (repeatedPauseResumes 2) = .building := by decide
example : (run auto (initial auto) (repeatedPauseResumes 2)).rounds = 1 := by decide
example : (run auto (initial auto) (repeatedPauseResumes 2)).workerLaunches = 3 := by decide
#eval showTrace "same_round_three_worker_launches" auto (repeatedPauseResumes 2)

private theorem run_append (c : Config) (s : State) (xs ys : List Event) :
    run c s (xs ++ ys) = run c (run c s xs) ys := by
  simp [run, List.foldl_append]

/-- Canonical state after one or more completed pause/resume cycles. Its data
comes from a real trace; only the symbolic launch count varies with `n`. -/
def resumedWorker (n : Nat) : State :=
  { (run auto (initial auto) (repeatedPauseResumes 1)) with workerLaunches := n + 2 }

private theorem pause_cycle (n : Nat) :
    run auto (resumedWorker n) pauseResumeCycle = resumedWorker (n + 1) := by
  cbv

theorem pause_resume_normal_form (n : Nat) :
    run auto (initial auto) (repeatedPauseResumes (n + 1)) = resumedWorker n := by
  induction n with
  | zero => decide
  | succ n ih =>
    change run auto (initial auto) (repeatedPauseResumes (n + 1) ++ pauseResumeCycle) = _
    rw [run_append, ih, pause_cycle]

/-- Counterexample to any finite bound on total launches from configured
round/nudge/retry budgets: a reachable state can exceed any chosen bound.
The optional ticket deadline is disabled in `auto`, as the doc permits. -/
theorem worker_launches_unbounded (bound : Nat) :
    ∃ events : List Event,
      (run auto (initial auto) events).rounds = 1 ∧
      (run auto (initial auto) events).nudges = 0 ∧
      (run auto (initial auto) events).retries = 0 ∧
      bound < (run auto (initial auto) events).workerLaunches := by
  have normal := pause_resume_normal_form bound
  have rounds : (resumedWorker bound).rounds = 1 := by cbv
  have nudges : (resumedWorker bound).nudges = 0 := by cbv
  have retries : (resumedWorker bound).retries = 0 := by cbv
  have launches : (resumedWorker bound).workerLaunches = bound + 2 := by rfl
  have count := (congrArg State.workerLaunches normal).trans launches
  have greater : bound < bound + 2 := by omega
  exact ⟨repeatedPauseResumes (bound + 1),
    (congrArg State.rounds normal).trans rounds,
    (congrArg State.nudges normal).trans nudges,
    (congrArg State.retries normal).trans retries,
    count.symm ▸ greater⟩

-- §5.1/§6 persistent scheduler: empty ticks do not stop; explicit shutdown drains.
def watching : List Event := [event .recoveryComplete, event .schedulerTick, event .queueAdded]
example : outcome schedulerConfig watching = .schedulerWatching := by decide
#eval showTrace "scheduler_empty_queue_waits" schedulerConfig watching
def schedulerStop : List Event := watching ++ [event .shutdownRequested,
  { kind := .schedulerTick, facts := { activeWorkflows := true } }, event .schedulerTick]
example : outcome schedulerConfig schedulerStop = .schedulerStopped := by decide
#eval showTrace "scheduler_shutdown_drains" schedulerConfig schedulerStop
example : outcome schedulerConfig [event .recoveryFailed] = .schedulerFailed := by decide
#eval showTrace "scheduler_recovery_failed" schedulerConfig [event .recoveryFailed]
example : outcome schedulerConfig (watching ++ [event .storageFailed]) = .schedulerFailed := by decide
#eval showTrace "scheduler_storage_failed" schedulerConfig (watching ++ [event .storageFailed])

end Runner.Examples
