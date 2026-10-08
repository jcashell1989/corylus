import Std

namespace Runner

/-- §5.1 state table. Camel-case spelling maps one-to-one to snake_case. -/
inductive Phase where
  | queued | building | gating | reviewing | awaitingAcceptance | approving | merging
  | jobAuthorizing | jobRunning | jobVerifying | jobRollingBack | closerRunning | quiescing
  | done | jobSucceeded | finishedAwaitingHuman | needsDecision | dependencyBlocked | paused
  | awaitingMerge | failed | stopped | roundExhausted | acceptanceDeclined | jobFailed
  | jobRolledBack | jobRollbackFailed | schedulerRecovering | schedulerWatching
  | schedulerStopping | schedulerStopped | schedulerFailed
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq

/-- §5.1 transition event vocabulary; camel case removes dots and underscores. -/
inductive EventKind where
  | admissionChecked | dependencySatisfied | workspaceFailed | workspaceUncertain
  | runStarted | identityRefused | runLaunchFailed | effectUncertain | runFinished | runFailed
  | gatePassed | gateFailed | gateError | checksAbsent | judgmentUnavailable | judgmentResult
  | reviewVerdict | headChanged | decisionRecorded | acceptanceReady | jobFinished
  | trackerApproved | trackerFailed | mergeBlocked | mergeUnsupported | prReady | mergeRequested
  | prMerged | resumeRequested | authorizationChecked | jobFailed | jobVerified
  | rollbackVerified | rollbackFailed | stopRequested | pauseRequested | cancelVerified
  | cancelFailed | ticketDeadline | recoveryObserved | effectObserved | leaseReleaseRequested
  | resultUnsafe | commandInvalid | decisionInvalid | eventDuplicate | observationRecorded
  | recoveryComplete | recoveryFailed | schedulerTick | queueAdded | shutdownRequested | storageFailed
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq

inductive Continuation where
  | build | review | merge | closer | job | savedPhase
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq
inductive MergePolicy where
  | automatic | manual
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq
inductive Mode where
  | workflow | standaloneJob | closerJob | scheduler
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq
inductive Child where
  | absent | liveVerified | unknown
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq
inductive Service where
  | unchanged | changed | unknown
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq
inductive Verdict where
  | approve | reject | needsDecision | malformed
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq
inductive Decision where
  | acceptance | declineAcceptance | acceptWaiver | resolveBlocker | declineWaiver
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq
inductive Judgment where
  | continueRun | flagLoop | flagReviewGap | needsDecision
  deriving DecidableEq, Repr, BEq, ReflBEq, LawfulBEq

structure Config where
  maxRounds : Nat := 3
  finishNudges : Nat := 1
  launchRetries : Nat := 1
  runRetries : Nat := 1
  maxWallSeconds : Nat := 5400
  idleTimeoutSeconds : Nat := 1200
  launchTimeoutSeconds : Nat := 30
  cancelGraceSeconds : Nat := 15
  rollbackTimeoutSeconds : Nat := 300
  ticketDeadlineSeconds : Nat := 0
  mergePolicy : MergePolicy := .automatic
  humanAcceptanceRequired : Bool := false
  workerSession : Nat := 1
  creatorSession : Nat := 2
  reviewerSession : Nat := 3
  closerSession : Nat := 4
  reviewerEligible : Bool := true
  closerEligible : Bool := true
  initialHeadSha : Nat := 1
  mode : Mode := .workflow
  deriving Repr

structure State where
  phase : Phase := .queued
  rounds : Nat := 0
  nudges : Nat := 0
  launchRetries : Nat := 0
  retries : Nat := 0
  mergeRequests : Nat := 0
  workerLaunches : Nat := 0
  workerStarted : Bool := false
  launchPending : Bool := false
  launchDeadlineFailurePending : Bool := false
  continuation : Continuation := .build
  returnState : Phase := .building
  pauseReturnState : Phase := .queued
  controlTarget : Option Phase := none
  headSha : Nat := 1
  reviewedSha : Option Nat := none
  waiverSha : Option Nat := none
  approved : Bool := false
  accepted : Bool := false
  waiverAccepted : Bool := false
  blockerResolved : Bool := false
  manualMergeAuthorized : Bool := false
  actorSession : Nat := 3
  approvalSession : Option Nat := none
  child : Child := .absent
  service : Service := .unchanged
  backupAvailable : Bool := false
  serviceSuccessValid : Bool := false
  effectUnresolved : Bool := false
  leased : Bool := false
  receiptCount : Nat := 0
  deriving Repr, DecidableEq

/-- Adapter-normalized evidence, never credentials or raw harness text.
Each Boolean denotes the correspondingly named table guard. Schema/current
checks cover event/run/effect identities; actual identities and SHA equality
are checked separately, rather than hidden inside an 'everything valid' flag. -/
structure Facts where
  schemaValid : Bool := true
  current : Bool := true
  duplicate : Bool := false
  dependenciesSatisfied : Bool := true
  slotFree : Bool := true
  continuationValid : Bool := true
  workGatesValid : Bool := true
  authorized : Bool := true
  headCurrent : Bool := true
  identitiesValid : Bool := true
  cwdValid : Bool := true
  claimedEffect : Bool := true
  firstReceipt : Bool := true
  beforeLaunchDeadline : Bool := true
  safeRetry : Bool := false
  resultAvailable : Bool := true
  exitZero : Bool := true
  moreGates : Bool := false
  allGatesValid : Bool := true
  repairable : Bool := false
  judgmentRequired : Bool := false
  judgmentValid : Bool := true
  judgment : Judgment := .continueRun
  verdict : Verdict := .approve
  verdictValid : Bool := true
  decision : Decision := .resolveBlocker
  scopeReviewValid : Bool := true
  deadlineNotExpired : Bool := true
  reconciledAbsent : Bool := true
  blockerResolutionValid : Bool := true
  approvalReceiptValid : Bool := true
  actorValid : Bool := true
  serviceRunbook : Bool := false
  successReceiptsValid : Bool := true
  probePassed : Bool := true
  rollbackPassed : Bool := true
  cancelReceiptValid : Bool := true
  deadlineExpired : Bool := false
  deadlineEnabled : Bool := false
  recoveryKnown : Bool := true
  deadWithoutReceipt : Bool := false
  matchingEffect : Bool := true
  verifiedReceipt : Bool := true
  releaseReceiptsValid : Bool := true
  ownerValid : Bool := true
  activeWorkflows : Bool := false
  receiptsDurable : Bool := true
  oneShotOwner : Bool := true
  authorizationSatisfied : Bool := true
  manualMergeAuthorized : Bool := false
  observedChild : Option Child := none
  observedService : Option Service := none
  backupReceipt : Bool := false
  childExited : Bool := true
  checksValid : Bool := true
  draftReady : Bool := true
  sha : Nat := 1
  deriving Repr
structure Event where
  kind : EventKind
  facts : Facts := {}
  deriving Repr

def terminal : Phase → Bool
  | .done | .jobSucceeded | .failed | .stopped | .roundExhausted | .acceptanceDeclined
  | .jobFailed | .jobRolledBack | .jobRollbackFailed | .schedulerStopped | .schedulerFailed => true
  | _ => false

def workflow (p : Phase) : Bool := [Phase.queued, .building, .gating, .reviewing,
  .awaitingAcceptance, .approving, .merging, .jobAuthorizing, .jobRunning, .jobVerifying,
  .jobRollingBack, .closerRunning, .quiescing, .finishedAwaitingHuman, .needsDecision,
  .dependencyBlocked, .paused, .awaitingMerge].contains p
def running (p : Phase) : Bool := [Phase.building, .reviewing, .jobRunning, .closerRunning].contains p
def buildReviewCloser (p : Phase) : Bool := [Phase.building, .reviewing, .closerRunning].contains p
def serviceJob (p : Phase) : Bool := [Phase.jobRunning, .jobVerifying].contains p
def identityPhase (p : Phase) : Bool := [Phase.building, .reviewing, .approving,
  .jobAuthorizing, .jobRunning, .jobVerifying, .closerRunning].contains p
def active (p : Phase) : Bool := [Phase.building, .gating, .reviewing, .approving,
  .merging, .jobAuthorizing, .jobRunning, .jobVerifying, .closerRunning].contains p
def hold (p : Phase) : Bool := [Phase.awaitingAcceptance, .finishedAwaitingHuman,
  .needsDecision, .dependencyBlocked, .awaitingMerge].contains p
def blockerHold (p : Phase) : Bool := [Phase.needsDecision, .dependencyBlocked].contains p
def scheduler (p : Phase) : Bool := [Phase.schedulerRecovering, .schedulerWatching,
  .schedulerStopping].contains p
def pauseOriginValid (p : Phase) : Bool := p == .queued || active p || hold p

def independent (c : Config) (actor : Nat) : Bool :=
  actor != c.workerSession && actor != c.creatorSession

def reviewerIndependent (c : Config) : Bool := c.reviewerEligible && independent c c.reviewerSession
def closerIndependent (c : Config) : Bool := c.closerEligible && independent c c.closerSession

def exactHead (s : State) : Bool := s.reviewedSha == some s.headSha

def acceptedHead (s : State) : Bool := exactHead s && s.approved

def safe (s : State) : Bool := s.child == .absent && !s.effectUnresolved && s.service == .unchanged

def acceptanceSatisfied (c : Config) (s : State) : Bool := !c.humanAcceptanceRequired || s.accepted

def initial (c : Config) : State :=
  { headSha := c.initialHeadSha, actorSession := c.reviewerSession,
    returnState := if c.mode == .standaloneJob then .jobAuthorizing else .building,
    phase := if c.mode == .scheduler then .schedulerRecovering else .queued,
    continuation := if c.mode == .standaloneJob then .job else if c.mode == .closerJob then .closer else .build }

def withPhase (s : State) (p : Phase) : State := { s with
    phase := p }
def launchAt (s : State) (p : Phase) : State := { s with
    phase := p, launchPending := true, leased := true }
def saveDecisionHold (s : State) : State :=
  { s with
    phase := .needsDecision,
    continuation := if active s.phase then .savedPhase else s.continuation,
    returnState := if active s.phase then s.phase else s.returnState }
def invalidate (s : State) : State :=
  { s with
    reviewedSha := none, approved := false, accepted := false, waiverAccepted := false,
    waiverSha := none, approvalSession := none }
def quiesce (s : State) (target : Phase) : State :=
  { s with
    phase := .quiescing, controlTarget := some target,
    continuation := if target == .needsDecision && active s.phase then .savedPhase else s.continuation,
    returnState := if active s.phase then s.phase else s.returnState }
def rollBack (s : State) (target : Option Phase) : State :=
  { s with
    phase := .jobRollingBack, controlTarget := target,
    returnState := .jobAuthorizing, serviceSuccessValid := false }
def control (s : State) (target : Phase) : State :=
  { s with
    controlTarget := some target,
    pauseReturnState := if target == .paused then
      (if s.phase == .jobRollingBack || serviceJob s.phase && s.service == .changed then .jobAuthorizing
       else if s.phase == .quiescing then
         (if s.controlTarget == some .needsDecision then .needsDecision else s.pauseReturnState)
       else s.phase) else if pauseOriginValid s.phase then s.phase else s.pauseReturnState }

/-- Total transition relation, §5.1. Dispatch groups the source rows by event;
comments preserve all R001–R129 identifiers. Guard precedence follows the
disjoint table guards. Finite aliases are literal enumerations above and their
individual source-row expansions are recorded in rows.tsv. -/
def rowStep (c : Config) (s : State) (e : Event) : State := Id.run do
  let f := e.facts
  let p := s.phase
  match e.kind with
  | .admissionChecked =>
    if p != .queued then return s
    -- §5.1 row R001: unmet dependencies.
    if !f.dependenciesSatisfied then return withPhase s .dependencyBlocked
    -- §5.1 row R003: no slot.
    if !f.slotFree then return s
    -- §5.1 row R011: invalid continuation evidence, complement of admission rows.
    if !f.continuationValid then return saveDecisionHold s
    match s.continuation with
    | .build =>
      -- §5.1 rows R004–R005: new build admitted only below round cap.
      if s.rounds < c.maxRounds then return launchAt s .building
      else return withPhase s .roundExhausted
    | .review =>
      -- §5.1 row R006: valid work/head/gates.
      if f.workGatesValid && f.headCurrent then return launchAt { s with
    actorSession := c.reviewerSession, launchRetries := 0, retries := 0 } .reviewing
      else return saveDecisionHold s
    | .merge =>
      -- §5.1 row R007: authorized exact head (manual authorization is supported).
      if f.authorized && acceptedHead s && f.headCurrent then return { s with
    phase := .merging, leased := true }
      else return saveDecisionHold s
    | .closer =>
      -- §5.1 row R008: accepted scoped waiver.
      if s.waiverAccepted && s.waiverSha == some s.headSha && f.scopeReviewValid then
        return launchAt { s with
    actorSession := c.closerSession, launchRetries := 0, retries := 0 } .closerRunning
      else return saveDecisionHold s
    | .job =>
      -- §5.1 row R009: job policy evaluated in next phase.
      return { s with
    phase := .jobAuthorizing, leased := true }
    | .savedPhase =>
      -- §5.1 row R010: validated active origin/reconciled effects; budgets retained.
      if active s.returnState && f.reconciledAbsent then
        return { s with
    phase := s.returnState, leased := true,
          launchPending := running s.returnState && s.child == .absent }
      else return saveDecisionHold s
  | .dependencySatisfied =>
    -- §5.1 row R002.
    if p == .dependencyBlocked && f.dependenciesSatisfied then return withPhase s .queued else return s
  | .workspaceFailed =>
    -- §5.1 row R012: building/reviewing.
    if p == .building || p == .reviewing then return withPhase s .failed else return s
  | .workspaceUncertain =>
    -- §5.1 row R013.
    if p == .building || p == .reviewing then return saveDecisionHold s else return s
  | .runStarted =>
    -- §5.1 rows R014–R015: first receipt for the claimed launch; late start queues failure.
    if running p && s.launchPending && f.claimedEffect && f.identitiesValid && f.cwdValid && f.firstReceipt then
      return { s with
    child := .liveVerified, launchPending := false,
        rounds := if p == .building && !s.workerStarted then s.rounds + 1 else s.rounds,
        workerStarted := s.workerStarted || p == .building,
        workerLaunches := if p == .building then s.workerLaunches + 1 else s.workerLaunches,
        launchDeadlineFailurePending := !f.beforeLaunchDeadline }
    else return s
  | .identityRefused =>
    if !identityPhase p then return s
    -- §5.1 rows R019–R020: service restoration precedes identity hold.
    if serviceJob p && s.service == .changed && s.child != .unknown then
      if s.backupAvailable then return rollBack s (some .needsDecision)
      else return withPhase s .jobRollbackFailed
    -- §5.1 row R018: unknown process/effect safety; retain lease.
    if s.child == .unknown || s.service == .unknown then return saveDecisionHold s
    -- §5.1 rows R016–R017: absent child vs verified live child.
    if s.service == .unchanged then
      if s.child == .absent then return saveDecisionHold s
      else return quiesce s .needsDecision
    return s
  | .runLaunchFailed =>
    if !running p || s.child != .absent then return s
    -- §5.1 row R021: launch retry does not consume a round.
    if s.launchRetries < c.launchRetries then return { s with
    launchRetries := s.launchRetries + 1, launchPending := true }
    -- §5.1 rows R022–R023.
    else if buildReviewCloser p then return withPhase s .failed else return withPhase s .jobFailed
  | .effectUncertain =>
    -- §5.1 row R024.
    if workflow p then return { (saveDecisionHold s) with effectUnresolved := true } else return s
  | .runFinished =>
    -- §5.1 rows R025–R026: nonzero normalized to run.failed by adapter.
    if p == .building && f.exitZero then
      if f.resultAvailable then
        -- The sanitized handoff observes the worker's new commit head (§3.3);
        -- changed code invalidates prior acceptance before SHA-bound gating.
        let observed := if f.sha == s.headSha then s else invalidate { s with headSha := f.sha }
        return { observed with phase := .gating, child := .absent }
      else return { s with
    phase := .failed, child := .absent }
    return s
  | .runFailed =>
    if buildReviewCloser p then
      -- §5.1 rows R027–R029: only safe retry, no extra round for reviewer/closer.
      if f.safeRetry && s.retries < c.runRetries then
        if p == .building && !(s.rounds < c.maxRounds) then return { s with
    phase := .roundExhausted, child := .absent }
        else return { s with
    retries := s.retries + 1, launchPending := true, child := .absent,
          workerStarted := if p == .building then false else s.workerStarted,
          nudges := if p == .building then 0 else s.nudges,
          launchRetries := if p == .building then 0 else s.launchRetries,
          launchDeadlineFailurePending := false }
      else return { s with
    phase := .failed, child := .absent }
    if serviceJob p then
      -- §5.1 rows R088–R089 (run.failed alternative).
      if s.service == .changed then
        if s.backupAvailable then return rollBack ({ s with child := .absent }) none
        else return { s with
    phase := .jobRollbackFailed, child := .absent }
      -- §5.1 rows R086–R087 and R090.
      if p == .jobRunning && s.service == .unchanged && f.safeRetry && s.retries < c.runRetries then
        return { s with
    retries := s.retries + 1, launchPending := true, child := .absent }
      if s.service == .unchanged then return { s with
    phase := .jobFailed, child := .absent }
    return s
  | .gatePassed =>
    if p != .gating then return s
    -- §5.1 row R030.
    if f.moreGates then return s
    -- §5.1 row R031.
    if f.allGatesValid then return launchAt { s with
    reviewedSha := some s.headSha,
      actorSession := c.reviewerSession, launchRetries := 0, retries := 0 } .reviewing
    return s
  | .gateFailed =>
    if p != .gating then return s
    -- §5.1 rows R032–R034: shared same-attempt nudge budget.
    if f.repairable && s.nudges < c.finishNudges then
      return launchAt { s with
    nudges := s.nudges + 1 } .building
    else return withPhase s .failed
  | .gateError =>
    -- §5.1 row R035.
    if p == .gating then return withPhase s .failed else return s
  | .checksAbsent =>
    -- §5.1 row R036.
    if p == .gating then return saveDecisionHold s else return s
  | .judgmentUnavailable =>
    if !(p == .gating || buildReviewCloser p) then return s
    -- §5.1 rows R037–R039.
    if !f.judgmentRequired then return s
    if s.child == .absent then return saveDecisionHold s
    if buildReviewCloser p && s.child == .liveVerified then return quiesce s .needsDecision
    return s
  | .judgmentResult =>
    if !(p == .gating || buildReviewCloser p) || !f.judgmentValid then return s
    -- §5.1 rows R040–R042.
    if f.judgment == .continueRun then return s
    if s.child == .absent then return saveDecisionHold s
    if buildReviewCloser p && s.child == .liveVerified then return quiesce s .needsDecision
    return s
  | .reviewVerdict =>
    if p != .reviewing || !f.exitZero then return s
    -- §5.1 row R043: malformed output is failure, not rejection or approval.
    if !f.verdictValid || f.verdict == .malformed then return { s with
    phase := .failed, child := .absent }
    match f.verdict with
    | .reject =>
      -- §5.1 rows R044–R045.
      if s.rounds < c.maxRounds then return { (invalidate s) with
        phase := .queued,
        continuation := .build, child := .absent, workerStarted := false, nudges := 0,
        retries := 0, launchRetries := 0 }
      else return { s with
    phase := .roundExhausted, child := .absent }
    | .needsDecision =>
      -- §5.1 row R046.
      return { (saveDecisionHold s) with child := .absent, reviewedSha := some s.headSha }
    | .approve =>
      -- §5.1 rows R047–R048: independent current reviewer; receipt is not tracker approval.
      if f.headCurrent && f.sha == s.headSha && f.identitiesValid && reviewerIndependent c then
        return { s with
    phase := if c.humanAcceptanceRequired then .awaitingAcceptance else .approving,
          reviewedSha := some s.headSha, actorSession := c.reviewerSession, child := .absent }
      else return s
    | .malformed => return s
  | .headChanged =>
    -- §5.1 rows R049–R050: effect data retain continuation, invalidate all acceptance.
    if [Phase.reviewing, .awaitingAcceptance, .approving, .merging, .closerRunning].contains p then
      let t := { (invalidate { s with headSha := f.sha }) with
        returnState := .gating, continuation := .savedPhase }
      if s.child == .absent then return { (saveDecisionHold t) with returnState := .gating, continuation := .savedPhase }
      if (p == .reviewing || p == .closerRunning) && s.child == .liveVerified then return { (quiesce t .needsDecision) with returnState := .gating, continuation := .savedPhase }
    return s
  | .decisionRecorded =>
    if !f.authorized then return s
    if p == .awaitingAcceptance then
      -- §5.1 row R055.
      if f.decision == .declineAcceptance then return withPhase s .acceptanceDeclined
      if f.decision == .acceptance && f.headCurrent && exactHead s then
        -- §5.1 row R054: closer continuation still requires admission.
        if s.continuation == .closer && s.waiverAccepted && s.waiverSha == some s.headSha then
          return { s with
    phase := .queued, accepted := true }
        -- §5.1 rows R051–R052: normal reviewer continuation, free-slot split.
        if s.continuation != .closer then
          return { s with
    phase := if f.slotFree then .approving else .awaitingAcceptance,
            accepted := true, leased := f.slotFree }
      return s
    if p == .needsDecision then
      if f.decision == .acceptWaiver && f.scopeReviewValid && f.headCurrent && exactHead s && safe s && f.deadlineNotExpired then
        -- §5.1 rows R056–R057.
        return { s with
    phase := if acceptanceSatisfied c s then .queued else .awaitingAcceptance,
          waiverAccepted := true, waiverSha := some s.headSha, continuation := .closer }
      -- §5.1 rows R120–R121: resolution requires a separate resume; declined waiver grants nothing.
      if f.decision == .resolveBlocker && f.blockerResolutionValid then return { s with
    blockerResolved := true }
      return s
    -- §5.1 row R074: resolution while paused preserves both continuations.
    if p == .paused && s.pauseReturnState == .needsDecision && f.decision == .resolveBlocker && f.blockerResolutionValid then
      return { s with
    blockerResolved := true }
    return s
  | .acceptanceReady =>
    -- §5.1 row R053.
    if p == .awaitingAcceptance && s.accepted && s.continuation != .closer && exactHead s && f.headCurrent && f.slotFree then
      return { s with
    phase := .approving, leased := true }
    return s
  | .jobFinished =>
    if !f.exitZero then return s
    if p == .closerRunning then
      -- §5.1 rows R058–R059: closer approval receipt intentionally substitutes for APPROVE verdict.
      if closerIndependent c && f.identitiesValid && acceptanceSatisfied c s && f.approvalReceiptValid && f.actorValid && f.headCurrent && s.waiverSha == some s.headSha then
        return { s with
    phase := .approving, child := .absent, approved := true,
          reviewedSha := some s.headSha, approvalSession := some c.closerSession, actorSession := c.closerSession }
      else return { s with
    phase := .failed, child := .absent }
    if p == .jobRunning then
      -- §5.1 row R083.
      if f.serviceRunbook then return { s with
    phase := .jobVerifying, child := .absent }
      -- §5.1 rows R082 and R084.
      if f.successReceiptsValid then return { s with
    phase := .jobSucceeded, child := .absent }
      else return { s with
    phase := .jobFailed, child := .absent }
    return s
  | .trackerApproved =>
    -- §5.1 rows R060–R061.
    if p == .approving && f.approvalReceiptValid && f.actorValid && independent c s.actorSession &&
        ((s.actorSession == c.reviewerSession && c.reviewerEligible) || (s.actorSession == c.closerSession && c.closerEligible)) &&
        exactHead s && f.headCurrent && f.sha == s.headSha && acceptanceSatisfied c s then
      return { s with
    phase := if c.mergePolicy == .manual then .finishedAwaitingHuman else .merging,
        approved := true, approvalSession := some s.actorSession }
    return s
  | .trackerFailed =>
    -- §5.1 row R062.
    if p == .approving then return withPhase s .failed else return s
  | .mergeBlocked =>
    -- §5.1 row R063.
    if p == .merging then return withPhase s .awaitingMerge else return s
  | .mergeUnsupported =>
    -- §5.1 row R064.
    if p == .merging then return withPhase s .failed else return s
  | .prReady =>
    -- §5.1 row R065: action intent, no new phase; receipt follows.
    if p == .merging && acceptedHead s && f.headCurrent && f.checksValid && f.draftReady then return { s with mergeRequests := s.mergeRequests + 1 } else return s
  | .mergeRequested =>
    -- §5.1 row R066: same phase, atomically SHA-guarded action abstracted.
    if p == .merging && acceptedHead s && f.headCurrent && f.checksValid && f.draftReady then return { s with mergeRequests := s.mergeRequests + 1 } else return s
  | .prMerged =>
    -- §5.1 row R067: reconciled receipt proves the approved expected head.
    if (p == .merging || p == .awaitingMerge) && f.verifiedReceipt && acceptedHead s && f.sha == s.headSha then
      return withPhase s .done
    return s
  | .resumeRequested =>
    if p == .awaitingMerge || p == .finishedAwaitingHuman then
      -- §5.1 row R070: stale accepted head invalidates acceptance.
      if !acceptedHead s || !f.headCurrent then return { (saveDecisionHold (invalidate s)) with returnState := .gating, continuation := .savedPhase }
      -- §5.1 rows R068–R069 and R071: authority/reconciliation/deadline split.
      if f.authorized && f.deadlineNotExpired && (if p == .awaitingMerge then f.reconciledAbsent else f.manualMergeAuthorized) then
        return { s with
    phase := .queued, continuation := .merge }
      return s
    if blockerHold p then
      -- §5.1 rows R072–R073.
      if s.blockerResolved && f.blockerResolutionValid && f.continuationValid && safe s && f.deadlineNotExpired then
        return withPhase s .queued
      return s
    if p == .paused then
      if f.authorized && safe s && f.deadlineNotExpired then
        -- §5.1 row R078: restoring a stale pinned acceptance/merge hold requires new review.
        if (s.pauseReturnState == .awaitingAcceptance || s.pauseReturnState == .finishedAwaitingHuman || s.pauseReturnState == .awaitingMerge) &&
            (!f.headCurrent || !exactHead s) then return { (saveDecisionHold (invalidate s)) with returnState := .gating, continuation := .savedPhase }
        -- §5.1 row R075: queued origin preserves queue continuation.
        if s.pauseReturnState == .queued && f.continuationValid then return withPhase s .queued
        -- §5.1 row R076: active origin enters queue with saved_phase, same attempt.
        if active s.pauseReturnState && f.continuationValid then return { s with
    phase := .queued,
          continuation := .savedPhase, returnState := s.pauseReturnState }
        -- §5.1 row R077: original hold restored without granting authority.
        if hold s.pauseReturnState then return withPhase s s.pauseReturnState
      -- §5.1 row R079: reject unmatched pause resume.
      return s
    -- §5.1 row R119: terminal resume rejected (also all unlisted origins).
    return s
  | .authorizationChecked =>
    if p != .jobAuthorizing then return s
    -- §5.1 rows R080–R081.
    if f.authorizationSatisfied then return launchAt s .jobRunning else return saveDecisionHold s
  | .jobFailed =>
    if !serviceJob p then return s
    -- §5.1 row R085: no changed service state.
    if s.service == .unchanged then return { s with
    phase := .jobFailed, child := .absent }
    -- §5.1 rows R088–R089 (job.failed alternative).
    if s.service == .changed then
      if s.backupAvailable then return rollBack ({ s with child := .absent }) none
      else return { s with
    phase := .jobRollbackFailed, child := .absent }
    return s
  | .jobVerified =>
    -- §5.1 row R091.
    if p == .jobVerifying && f.successReceiptsValid && f.probePassed then
      return { s with
    phase := .jobSucceeded, serviceSuccessValid := true }
    return s
  | .rollbackVerified =>
    if p != .jobRollingBack || !f.rollbackPassed then return s
    -- §5.1 rows R092–R093: target is constrained by saved-target vocabulary.
    let t := { s with
    service := .unchanged, child := .absent, serviceSuccessValid := false }
    match s.controlTarget with
    | none => return withPhase t .jobRolledBack
    | some target =>
      if [Phase.paused, .stopped, .needsDecision].contains target then return withPhase t target else return s
  | .rollbackFailed =>
    -- §5.1 row R094.
    if p == .jobRollingBack then return withPhase s .jobRollbackFailed else return s
  | .stopRequested | .pauseRequested =>
    let target := if e.kind == .stopRequested then Phase.stopped else .paused
    if !workflow p then return s
    -- §5.1 row R096: already-paused pause preserves origin.
    if p == .paused && target == .paused then return s
    -- §5.1 rows R101 and R104: controls never abandon cancellation/restoration.
    if p == .quiescing then return control s target
    if p == .jobRollingBack then return control s target
    -- §5.1 rows R102–R103: service restoration first.
    if serviceJob p && s.service == .changed then
      if s.backupAvailable then return rollBack (control s target) (some target)
      else return withPhase s .jobRollbackFailed
    -- §5.1 row R098: unknown service safety outside J/rollback.
    if !serviceJob p && s.service == .unknown then return saveDecisionHold s
    -- §5.1 row R097: paused stop only with child/effects safe.
    if p == .paused then
      if safe s then return quiesce (control s target) target else return s
    -- §5.1 row R095: unchanged service, normal control begins quiescing.
    if s.service == .unchanged then return quiesce (control s target) target
    return s
  | .cancelVerified =>
    -- §5.1 row R099: no child remains; target is stopped/paused/needs_decision.
    if p == .quiescing && f.cancelReceiptValid && f.childExited then
      match s.controlTarget with
      | some target =>
        if [Phase.paused, .stopped, .needsDecision].contains target then return { s with phase := target, leased := false, child := .absent }
        else return s
      | none => return s
    return s
  | .cancelFailed =>
    -- §5.1 row R100: unknown/live child retains lease.
    if p == .quiescing then return saveDecisionHold s else return s
  | .ticketDeadline =>
    if !workflow p || !f.deadlineExpired || !f.deadlineEnabled then return s
    -- §5.1 rows R109–R110: bounded cancellation/restoration continues.
    if p == .jobRollingBack || p == .quiescing then return { s with
    controlTarget := some .stopped }
    -- §5.1 rows R107–R108.
    if serviceJob p && s.service == .changed then
      if s.backupAvailable then return rollBack s (some .stopped)
      else return withPhase s .jobRollbackFailed
    -- §5.1 row R106.
    if !serviceJob p && s.service == .unknown then return saveDecisionHold s
    -- §5.1 row R105.
    if s.service == .unchanged then return quiesce s .stopped
    return s
  | .recoveryObserved =>
    -- §5.1 rows R111–R112: receipt replay/emit run.failed is a separate event.
    if workflow p && f.recoveryKnown then return s
    if running p && f.deadWithoutReceipt && !s.effectUnresolved then return s
    return s
  | .effectObserved =>
    -- §5.1 row R113, all S including terminal outcomes: cleanup may update data.
    if f.matchingEffect && f.verifiedReceipt then return { s with
      receiptCount := s.receiptCount + 1, effectUnresolved := false,
      child := f.observedChild.getD s.child,
      service := f.observedService.getD s.service,
      backupAvailable := s.backupAvailable || f.backupReceipt }
    return s
  | .leaseReleaseRequested =>
    -- §5.1 row R114, all S: phase is unchanged even after terminal outcomes.
    if (terminal p || hold p || p == .paused) && s.leased && s.child == .absent && f.releaseReceiptsValid then
      return { s with
    leased := false }
    return s
  | .resultUnsafe =>
    -- §5.1 row R115: sanitized diagnostic only, retain slot until safe.
    if workflow p then return { (saveDecisionHold s) with effectUnresolved := true } else return s
  | .commandInvalid | .decisionInvalid =>
    -- §5.1 row R116, all S.
    return s
  | .eventDuplicate =>
    -- §5.1 row R117, all S.
    return s
  | .observationRecorded =>
    -- §5.1 row R118, all S: abstract observations do not grant authority.
    return s
  | .recoveryComplete =>
    -- §5.1 row R122.
    if p == .schedulerRecovering && f.ownerValid && f.recoveryKnown then return withPhase s .schedulerWatching else return s
  | .recoveryFailed =>
    -- §5.1 row R123.
    if p == .schedulerRecovering then return withPhase s .schedulerFailed else return s
  | .schedulerTick | .queueAdded =>
    -- §5.1 row R124: persistent scheduler, including empty queue.
    if p == .schedulerWatching && f.ownerValid then return s
    if p == .schedulerStopping && e.kind == .schedulerTick then
      -- §5.1 rows R126–R127: shutdown waits for workflows/children and durable receipts.
      if f.activeWorkflows then return s
      if s.child == .absent && f.receiptsDurable then return withPhase s .schedulerStopped
    return s
  | .shutdownRequested =>
    -- §5.1 row R125.
    if p == .schedulerWatching then return withPhase s .schedulerStopping else return s
  | .storageFailed =>
    -- §5.1 rows R128–R129: no new external effects; may be nondurable.
    if scheduler p then return withPhase s .schedulerFailed
    if workflow p && f.oneShotOwner then return withPhase s .failed
    return s

/-- Schema/current checks precede table dispatch; duplicate IDs never repeat effects.
Terminal phases still accept the S cleanup rows, so phase absorption does not
claim immutability of cleanup data. -/
def step (c : Config) (s : State) (e : Event) : State :=
  if !e.facts.schemaValid || !e.facts.current || e.facts.duplicate then s
  else rowStep c s e

def run (c : Config) (s : State) (events : List Event) : State := events.foldl (step c) s

def trace (c : Config) (s : State) : List Event → List State
  | [] => [s]
  | e :: es => s :: trace c (step c s e) es

end Runner
