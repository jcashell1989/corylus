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

-- §5.1 R016–R020: identity refusal handles each process/service safety branch.
def observedChild (child : Child) : Event :=
  { kind := .effectObserved, facts := { observedChild := some child } }
def unknownService : Event :=
  { kind := .effectObserved, facts := { observedService := some .unknown } }
def identityAbsent : List Event := [event .admissionChecked, event .identityRefused]
example : outcome auto identityAbsent = .needsDecision := by decide
example : (run auto (initial auto) identityAbsent).workerLaunches = 0 := by decide
#eval showTrace "identity_absent_no_launch" auto identityAbsent

def identityLive : List Event := worker ++ [event .identityRefused, event .cancelVerified]
example : phases auto identityLive =
    [.queued, .building, .building, .quiescing, .needsDecision] := by decide
example : (run auto (initial auto) identityLive).child = .absent := by decide
#eval showTrace "identity_verified_child_cancelled" auto identityLive

def identityUnknown : List Event := worker ++ [observedChild .unknown, event .identityRefused]
example : outcome auto identityUnknown = .needsDecision := by decide
example : (run auto (initial auto) identityUnknown).child = .unknown := by decide
example : (run auto (initial auto) identityUnknown).leased = true := by decide
#eval showTrace "identity_unknown_child_retains_lease" auto identityUnknown

def identityUnknownService : List Event := worker ++ [unknownService, event .identityRefused]
example : outcome auto identityUnknownService = .needsDecision := by decide
example : (run auto (initial auto) identityUnknownService).service = .unknown := by decide
#eval showTrace "identity_unknown_service_hold" auto identityUnknownService

def identityServiceRestored : List Event := jobStart ++
  [changedService true, event .identityRefused, event .rollbackVerified]
example : phases job identityServiceRestored = [.queued, .jobAuthorizing, .jobRunning,
    .jobRunning, .jobRunning, .jobRollingBack, .needsDecision] := by decide
example : (run job (initial job) identityServiceRestored).service = .unchanged := by decide
#eval showTrace "identity_service_restored_before_hold" job identityServiceRestored

def identityServiceNoBackup : List Event := jobStart ++
  [changedService false, event .identityRefused]
example : outcome job identityServiceNoBackup = .jobRollbackFailed := by decide
#eval showTrace "identity_service_backup_unavailable" job identityServiceNoBackup

-- §5.1 R021–R023: retry allowance is consumed before absent-child launch exhaustion.
def launchExhausted : List Event := [event .admissionChecked,
  event .runLaunchFailed, event .runLaunchFailed]
example : outcome auto launchExhausted = .failed := by decide
example : (run auto (initial auto) launchExhausted).launchRetries = auto.launchRetries := by decide
example : (run auto (initial auto) launchExhausted).rounds = 0 := by decide
#eval showTrace "worker_launch_retry_exhausted" auto launchExhausted

def jobLaunchExhausted : List Event := [event .admissionChecked,
  event .authorizationChecked, event .runLaunchFailed, event .runLaunchFailed]
example : outcome job jobLaunchExhausted = .jobFailed := by decide
#eval showTrace "job_launch_retry_exhausted" job jobLaunchExhausted

-- §5.1 R026/R028/R033: handoff, round and repairable-gate failure alternatives.
def missingWorkerHandoff : List Event := worker ++
  [{ kind := .runFinished, facts := { resultAvailable := false } }]
example : outcome auto missingWorkerHandoff = .failed := by decide
#eval showTrace "missing_worker_handoff" auto missingWorkerHandoff

def safeWorkerFailure : Event := { kind := .runFailed, facts := { safeRetry := true } }
example : outcome { auto with maxRounds := 1 } (worker ++ [safeWorkerFailure]) =
    .roundExhausted := by decide
#eval showTrace "worker_retry_without_round_capacity" { auto with maxRounds := 1 }
  (worker ++ [safeWorkerFailure])

def retryExhausted : List Event := worker ++
  [safeWorkerFailure, event .runStarted, safeWorkerFailure]
example : outcome auto retryExhausted = .failed := by decide
example : (run auto (initial auto) retryExhausted).retries = auto.runRetries := by decide
#eval showTrace "worker_run_retry_exhausted" auto retryExhausted

def repairableGateFailure : List Event := worker ++ [event .runFinished,
  { kind := .gateFailed, facts := { repairable := true } }]
example : outcome { auto with finishNudges := 0 } repairableGateFailure = .failed := by decide
#eval showTrace "repairable_gate_nudge_exhausted" { auto with finishNudges := 0 }
  repairableGateFailure

-- §5.1 R011: invalid continuation evidence cannot authorize a launch.
def invalidAdmission : List Event :=
  [{ kind := .admissionChecked, facts := { continuationValid := false } }]
example : outcome auto invalidAdmission = .needsDecision := by decide
#eval showTrace "invalid_continuation_admission" auto invalidAdmission

-- §5.1 R013/R024/R036/R038–R042: attention holds and cancellation precede inspection.
example : outcome auto (worker ++ [event .workspaceUncertain]) = .needsDecision := by decide
#eval showTrace "workspace_uncertain" auto (worker ++ [event .workspaceUncertain])
example : outcome auto (worker ++ [event .effectUncertain]) = .needsDecision := by decide
example : (run auto (initial auto) (worker ++ [event .effectUncertain])).effectUnresolved =
    true := by decide
#eval showTrace "effect_uncertain" auto (worker ++ [event .effectUncertain])
example : outcome auto (worker ++ [event .runFinished, event .checksAbsent]) =
    .needsDecision := by decide
#eval showTrace "required_checks_absent" auto (worker ++ [event .runFinished, event .checksAbsent])

def requiredJudgment : Event :=
  { kind := .judgmentUnavailable, facts := { judgmentRequired := true } }
def judgmentAbsent : List Event := worker ++ [event .runFinished, requiredJudgment]
def judgmentLive : List Event := worker ++ [requiredJudgment, event .cancelVerified]
example : outcome auto judgmentAbsent = .needsDecision := by decide
example : phases auto judgmentLive =
    [.queued, .building, .building, .quiescing, .needsDecision] := by decide
#eval showTrace "required_judgment_unavailable_absent" auto judgmentAbsent
#eval showTrace "required_judgment_unavailable_live_cancelled" auto judgmentLive

def judgmentFlag (judgment : Judgment) : Event :=
  { kind := .judgmentResult, facts := { judgment } }
def flaggedAbsent (judgment : Judgment) : List Event :=
  worker ++ [event .runFinished, judgmentFlag judgment]
def flaggedLive (judgment : Judgment) : List Event :=
  worker ++ [judgmentFlag judgment, event .cancelVerified]
example : outcome auto (flaggedAbsent .flagLoop) = .needsDecision := by decide
example : outcome auto (flaggedAbsent .flagReviewGap) = .needsDecision := by decide
example : outcome auto (flaggedAbsent .needsDecision) = .needsDecision := by decide
example : phases auto (flaggedLive .flagLoop) =
    [.queued, .building, .building, .quiescing, .needsDecision] := by decide
example : phases auto (flaggedLive .flagReviewGap) =
    [.queued, .building, .building, .quiescing, .needsDecision] := by decide
example : phases auto (flaggedLive .needsDecision) =
    [.queued, .building, .building, .quiescing, .needsDecision] := by decide
#eval showTrace "judgment_flag_loop_absent" auto (flaggedAbsent .flagLoop)
#eval showTrace "judgment_flag_review_gap_absent" auto (flaggedAbsent .flagReviewGap)
#eval showTrace "judgment_needs_decision_absent" auto (flaggedAbsent .needsDecision)
#eval showTrace "judgment_flag_loop_live_cancelled" auto (flaggedLive .flagLoop)
#eval showTrace "judgment_flag_review_gap_live_cancelled" auto (flaggedLive .flagReviewGap)
#eval showTrace "judgment_needs_decision_live_cancelled" auto (flaggedLive .needsDecision)

-- §5.1 R049–R050/R070/R078: changed heads discard prior authority.
def staleHeadAbsent : List Event := approved ++ [eventAtSha .headChanged 2,
  event .trackerApproved, event .mergeRequested, event .prMerged]
def staleHeadLive : List Event := gated ++ [event .runStarted,
  eventAtSha .headChanged 2, event .cancelVerified]
example : outcome auto staleHeadAbsent = .needsDecision := by decide
example : (run auto (initial auto) staleHeadAbsent).approved = false := by decide
example : (run auto (initial auto) staleHeadAbsent).reviewedSha = none := by decide
example : (run auto (initial auto) staleHeadAbsent).headSha = 2 := by decide
example : (run auto (initial auto) staleHeadAbsent).mergeRequests = 0 := by decide
example : phases auto staleHeadLive = [.queued, .building, .building, .gating,
    .reviewing, .reviewing, .quiescing, .needsDecision] := by decide
#eval showTrace "stale_head_invalidates_approval_blocks_merge" auto staleHeadAbsent
#eval showTrace "stale_head_live_reviewer_cancelled" auto staleHeadLive

def staleResume : Event := { kind := .resumeRequested, facts := { headCurrent := false } }
example : outcome manual (approved ++ [staleResume]) = .needsDecision := by decide
#eval showTrace "manual_stale_head_resume_refused" manual (approved ++ [staleResume])
def pausedStaleMerge : List Event := mergeHold ++
  [event .pauseRequested, event .cancelVerified, staleResume]
example : outcome auto pausedStaleMerge = .needsDecision := by decide
example : (run auto (initial auto) pausedStaleMerge).approved = false := by decide
#eval showTrace "paused_merge_stale_head_resume_refused" auto pausedStaleMerge

-- §5.1 R081/R084/R090: job policy and success evidence remain required.
def unauthorizedJob : List Event := [event .admissionChecked,
  { kind := .authorizationChecked, facts := { authorizationSatisfied := false } }]
example : outcome job unauthorizedJob = .needsDecision := by decide
#eval showTrace "job_authorization_missing" job unauthorizedJob
example : outcome job (jobStart ++
    [{ kind := .jobFinished, facts := { successReceiptsValid := false } }]) = .jobFailed := by decide
#eval showTrace "job_success_receipt_missing" job (jobStart ++
  [{ kind := .jobFinished, facts := { successReceiptsValid := false } }])
def serviceVerifyCrash : List Event := jobStart ++
  [{ kind := .jobFinished, facts := { serviceRunbook := true } }, event .runFailed]
example : outcome job serviceVerifyCrash = .jobFailed := by decide
#eval showTrace "job_verification_run_failed_without_changes" job serviceVerifyCrash

-- §5.1 R088–R089/R102–R103: both normalized failure/control events restore first.
example : outcome job (jobStart ++ [changedService true, event .runFailed,
    event .rollbackVerified]) = .jobRolledBack := by decide
#eval showTrace "service_run_failed_restored" job
  (jobStart ++ [changedService true, event .runFailed, event .rollbackVerified])
example : outcome job (jobStart ++ [changedService false, event .runFailed]) =
    .jobRollbackFailed := by decide
#eval showTrace "service_run_failed_backup_unavailable" job
  (jobStart ++ [changedService false, event .runFailed])
example : outcome job (jobStart ++ [changedService false, event .pauseRequested]) =
    .jobRollbackFailed := by decide
#eval showTrace "service_pause_backup_unavailable" job
  (jobStart ++ [changedService false, event .pauseRequested])

-- §5.1 R098/R100/R103/R106–R108/R115/R129: unsafe effects never become success.
def cancelFailure : List Event := worker ++ [event .stopRequested, event .cancelFailed]
example : outcome auto cancelFailure = .needsDecision := by decide
example : (run auto (initial auto) cancelFailure).leased = true := by decide
example : (run auto (initial auto) cancelFailure).child = .liveVerified := by decide
#eval showTrace "cancel_failed_retains_lease" auto cancelFailure
example : outcome auto (worker ++ [unknownService, event .stopRequested]) =
    .needsDecision := by decide
#eval showTrace "stop_unknown_service_safety" auto (worker ++ [unknownService, event .stopRequested])
example : outcome job (jobStart ++ [changedService false, event .stopRequested]) =
    .jobRollbackFailed := by decide
#eval showTrace "service_stop_backup_unavailable" job
  (jobStart ++ [changedService false, event .stopRequested])

def deadline : Event :=
  { kind := .ticketDeadline, facts := { deadlineEnabled := true, deadlineExpired := true } }
example : outcome auto (worker ++ [unknownService, deadline]) = .needsDecision := by decide
#eval showTrace "deadline_unknown_service_safety" auto (worker ++ [unknownService, deadline])
example : outcome job (jobStart ++ [changedService true, deadline, event .rollbackVerified]) =
    .stopped := by decide
#eval showTrace "service_deadline_restores_before_stopped" job
  (jobStart ++ [changedService true, deadline, event .rollbackVerified])
example : outcome job (jobStart ++ [changedService false, deadline]) = .jobRollbackFailed := by decide
#eval showTrace "service_deadline_backup_unavailable" job (jobStart ++ [changedService false, deadline])

def unsafeResult : List Event := worker ++ [event .resultUnsafe,
  event .trackerApproved, event .mergeRequested, event .prMerged]
example : outcome auto unsafeResult = .needsDecision := by decide
example : (run auto (initial auto) unsafeResult).effectUnresolved = true := by decide
example : (run auto (initial auto) unsafeResult).leased = true := by decide
example : (run auto (initial auto) unsafeResult).mergeRequests = 0 := by decide
#eval showTrace "unsafe_result_hold_blocks_merge" auto unsafeResult
example : outcome auto (worker ++ [event .storageFailed]) = .failed := by decide
#eval showTrace "workflow_storage_failed" auto (worker ++ [event .storageFailed])

-- §5.1 R058–R059: an independent closer's concrete receipt must match this head.
def closerStarted : List Event := decisionHold ++
  [waiver, event .admissionChecked, event .runStarted]
def missingCloserReceipt : List Event := closerStarted ++
  [{ kind := .jobFinished, facts := { approvalReceiptValid := false } }]
example : outcome auto missingCloserReceipt = .failed := by decide
example : (run auto (initial auto) missingCloserReceipt).approved = false := by decide
#eval showTrace "closer_approval_receipt_missing" auto missingCloserReceipt

def refusedCloserActor : List Event := closerStarted ++
  [{ kind := .jobFinished, facts := { actorValid := false } }]
example : outcome auto refusedCloserActor = .failed := by decide
example : (run auto (initial auto) refusedCloserActor).approved = false := by decide
#eval showTrace "closer_approval_actor_refused" auto refusedCloserActor

example : outcome { auto with closerEligible := false }
    (closerStarted ++ [event .jobFinished]) = .failed := by decide
#eval showTrace "closer_ineligible_receipt_refused" { auto with closerEligible := false }
  (closerStarted ++ [event .jobFinished])

def staleCloserHead : List Event := closerStarted ++
  [eventAtSha .headChanged 2, event .cancelVerified]
example : outcome auto staleCloserHead = .needsDecision := by decide
example : (run auto (initial auto) staleCloserHead).waiverAccepted = false := by decide
example : (run auto (initial auto) staleCloserHead).waiverSha = none := by decide
#eval showTrace "stale_closer_head_invalidates_waiver" auto staleCloserHead

def matchingCloserReceipt : List Event := closerStarted ++ [eventAtSha .jobFinished 1]
example : outcome auto matchingCloserReceipt = .approving := by decide
example : (run auto (initial auto) matchingCloserReceipt).approved = true := by decide
example : (run auto (initial auto) matchingCloserReceipt).reviewedSha = some 1 := by decide
#eval showTrace "closer_matching_receipt_sha" auto matchingCloserReceipt

def mismatchedCloserReceipt : List Event := closerStarted ++ [eventAtSha .jobFinished 99,
  event .trackerApproved, event .mergeRequested, event .prMerged]
example : outcome auto mismatchedCloserReceipt = .failed := by decide
example : (run auto (initial auto) mismatchedCloserReceipt).approved = false := by decide
example : (run auto (initial auto) mismatchedCloserReceipt).mergeRequests = 0 := by decide
#eval showTrace "closer_mismatched_receipt_sha_blocks_merge" auto mismatchedCloserReceipt

def newHeadCloserReceipt : List Event := newHeadGated ++
  [{ kind := .reviewVerdict, facts := { sha := 2, verdict := .needsDecision } },
   waiver, event .admissionChecked, event .runStarted, eventAtSha .jobFinished 2,
   eventAtSha .trackerApproved 2, eventAtSha .mergeRequested 2, eventAtSha .prMerged 2]
example : outcome auto newHeadCloserReceipt = .done := by decide
example : (run auto (initial auto) newHeadCloserReceipt).headSha = 2 := by decide
example : (run auto (initial auto) newHeadCloserReceipt).reviewedSha = some 2 := by decide
#eval showTrace "closer_new_head_matching_receipt_merges" auto newHeadCloserReceipt

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

-- §5.1 R130/R120/R072/R010/R014: a provider/budget blocker needs explicit
-- resolution before a same-attempt continuation. Provider policy and actual
-- harness session/input handling remain adapter facts, not modeled effects.
def infrastructureFailure : Event :=
  { kind := .runFailed, facts := { infrastructureFailure := true } }
def infrastructureHold : List Event := worker ++ [infrastructureFailure]
example : phases auto infrastructureHold =
    [.queued, .building, .building, .needsDecision] := by decide
example : (run auto (initial auto) infrastructureHold).continuation = .savedPhase := by decide
example : (run auto (initial auto) infrastructureHold).returnState = .building := by decide
example : (run auto (initial auto) infrastructureHold).child = .absent := by decide
example : (run auto (initial auto) infrastructureHold).rounds = 1 := by decide
example : (run auto (initial auto) infrastructureHold).nudges = 0 := by decide
example : (run auto (initial auto) infrastructureHold).retries = 0 := by decide
#eval showTrace "infrastructure_failure_same_attempt_hold" auto infrastructureHold

def infrastructureResolved : List Event := infrastructureHold ++
  [event .decisionRecorded, event .resumeRequested, event .admissionChecked, event .runStarted]
example : phases auto infrastructureResolved = [.queued, .building, .building,
    .needsDecision, .needsDecision, .queued, .building, .building] := by decide
example : (run auto (initial auto) infrastructureResolved).rounds = 1 := by decide
example : (run auto (initial auto) infrastructureResolved).nudges = 0 := by decide
example : (run auto (initial auto) infrastructureResolved).retries = 0 := by decide
example : (run auto (initial auto) infrastructureResolved).launchRetries = 0 := by decide
example : (run auto (initial auto) infrastructureResolved).workerLaunches = 2 := by decide
example : outcome { auto with maxRounds := 1, runRetries := 0 } infrastructureResolved =
    .building := by decide
example : outcome { auto with maxRounds := 2, runRetries := 0 } infrastructureResolved =
    .building := by decide
example : outcome auto (infrastructureHold ++ [event .resumeRequested]) =
    .needsDecision := by decide
#eval showTrace "infrastructure_failure_resolved_same_attempt_resume" auto infrastructureResolved
#eval showTrace "infrastructure_failure_resume_before_resolution_refused" auto
  (infrastructureHold ++ [event .resumeRequested])
def infrastructureRepeatedUnresolved : List Event := infrastructureResolved ++
  [infrastructureFailure, event .resumeRequested]
example : outcome auto infrastructureRepeatedUnresolved = .needsDecision := by decide
example : (run auto (initial auto) infrastructureRepeatedUnresolved).blockerResolved =
    false := by decide
example : (run auto (initial auto) infrastructureRepeatedUnresolved).rounds = 1 := by decide
example : (run auto (initial auto) infrastructureRepeatedUnresolved).retries = 0 := by decide
#eval showTrace "infrastructure_failure_repeated_blocker_needs_new_resolution" auto
  infrastructureRepeatedUnresolved

-- Even safeRetry cannot convert uncertain infrastructure evidence to a work retry.
def unsafeInfrastructureFailure : Event :=
  { kind := .runFailed, facts := {
      infrastructureFailure := true, safeRetry := true, childExited := false } }
def infrastructureUnknownChild : List Event := worker ++
  [observedChild .unknown, unsafeInfrastructureFailure]
example : run auto (initial auto) infrastructureUnknownChild =
    run auto (initial auto) (worker ++ [observedChild .unknown]) := by decide
example : (run auto (initial auto) infrastructureUnknownChild).leased = true := by decide
#eval showTrace "infrastructure_failure_unknown_child_refused" auto infrastructureUnknownChild
example : run auto (initial auto) (worker ++ [unsafeInfrastructureFailure]) =
    run auto (initial auto) worker := by decide
#eval showTrace "infrastructure_failure_live_child_unreconciled_refused" auto
  (worker ++ [unsafeInfrastructureFailure])
example : run auto (initial auto) (worker ++ [unknownService, infrastructureFailure]) =
    run auto (initial auto) (worker ++ [unknownService]) := by decide
#eval showTrace "infrastructure_failure_unknown_service_refused" auto
  (worker ++ [unknownService, infrastructureFailure])

/-- Focused guard assertion for an unsafe abstract running state. Normal
reachable traces do not introduce unresolved effects without entering a hold. -/
example (c : Config) (s : State) (hp : s.phase = .building)
    (he : s.effectUnresolved = true) :
    step c s unsafeInfrastructureFailure = s := by
  simp [step, rowStep, Id.run, pure, unsafeInfrastructureFailure, hp, he,
    running, buildReviewCloser]

def infrastructureJobResume : List Event := jobStart ++ [infrastructureFailure,
  event .decisionRecorded, event .resumeRequested, event .admissionChecked, event .runStarted]
example : outcome job infrastructureJobResume = .jobRunning := by decide
example : (run job (initial job) infrastructureJobResume).retries = 0 := by decide
example : (run job (initial job) infrastructureJobResume).mergeRequests = 0 := by decide
#eval showTrace "infrastructure_failure_job_same_attempt_resume" job infrastructureJobResume
def infrastructureVerificationFailure : List Event := jobStart ++
  [{ kind := .jobFinished, facts := { serviceRunbook := true } }, infrastructureFailure]
example : outcome job infrastructureVerificationFailure = .jobFailed := by decide
#eval showTrace "infrastructure_failure_verification_without_changes_job_failed" job
  infrastructureVerificationFailure
def infrastructureServiceRollback : List Event := jobStart ++
  [changedService true, infrastructureFailure, event .rollbackVerified]
example : outcome job infrastructureServiceRollback = .jobRolledBack := by decide
#eval showTrace "infrastructure_failure_changed_service_restored" job infrastructureServiceRollback
example : outcome job (jobStart ++ [changedService false, infrastructureFailure]) =
    .jobRollbackFailed := by decide
#eval showTrace "infrastructure_failure_changed_service_backup_unavailable" job
  (jobStart ++ [changedService false, infrastructureFailure])

-- §5.1 R076: abstract new-input control uses the existing pause/resume path.
-- The reviewer actor remains identical; input version/delivery and harness
-- resumption capability are not represented and require adapter verification.
def newInputPauseResume : List Event := gated ++ [event .runStarted,
  event .pauseRequested, event .cancelVerified, event .resumeRequested,
  event .admissionChecked, event .runStarted]
example : outcome auto newInputPauseResume = .reviewing := by decide
example : (run auto (initial auto) newInputPauseResume).actorSession =
    (run auto (initial auto) (gated ++ [event .runStarted])).actorSession := by decide
example : (run auto (initial auto) newInputPauseResume).actorSession = auto.reviewerSession := by decide
example : (run auto (initial auto) newInputPauseResume).rounds = 1 := by decide
example : (run auto (initial auto) newInputPauseResume).nudges = 0 := by decide
example : (run auto (initial auto) newInputPauseResume).retries = 0 := by decide
#eval showTrace "new_input_pause_resume_same_reviewer_identity_abstract" auto newInputPauseResume

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
