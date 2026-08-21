#!/usr/bin/env python3
"""Shell-first Vikunja dispatch gate (hermes cron --no-agent script).

Judge path: yaml labels.judge_ready / judge_escalate → fire-and-forget hermes -p judge cron run …
Worker dispatch moved to the 01:00 job vikunja-worker-supervisor (script vikunja_worker_supervisor.py);
this preflight no longer dispatches workers — it keeps judge dispatch, mention
scans, and stale-claim reaping.

Caps come from ~/.hermes/vikunja.yaml. Empty stdout on
idle ticks = zero LLM cost; every tick still appends one heartbeat line.
"""
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

CLAIM_MARKERS = ("claiming this task", "starting this task", "claiming task")
REAPER_PREFIX = "vikunja reaper:"
MENTION_PROCESS_PATTERN = "hermes_review.py mention"
# CLI `hermes cron run` has no agent session, so hermes executes the job
# synchronously in-process. Preflight must not wait for that agent run.
TRIGGER_ACCEPT_SECONDS = 2.0
RESUME_TIMEOUT_SECONDS = 30.0
CRON_RUN_SKIP_MARKERS = (
    "paused/disabled",
    "resume it before running",
)

import httpx

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import hermes_machine_comments as hmc  # noqa: E402
from vikunja_config import load as load_vikunja_config  # noqa: E402

CFG = load_vikunja_config()
L = CFG.labels
HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
JUDGE_STATE_FILE = HERMES_HOME / "state" / "vikunja_judge_dispatch.json"
JUDGE_DAILY_CAP = CFG.caps["judge_per_day"]
CLAIM_STALE_AFTER = timedelta(hours=CFG.claim_stale_after_hours)
# Process patterns must match the real invocation form:
#   python -m hermes_cli.main -p <profile> cron run <job>
# A pattern like "hermes_cli.main cron run <job>" never matches it (the
# "-p <profile>" segment intervenes), which left the reaper blind to live
# workers. "cron run vikunja-worker" also prefix-matches
# "cron run vikunja-worker-escalate"; the overlap is harmless (any worker
# being alive blocks reaping either way).
WORKER_PROCESS_PATTERN = f"cron run {CFG.job('worker')}"
WORKER_ESCALATE_PROCESS_PATTERN = f"cron run {CFG.job('worker_escalate')}"
# The daily orchestrator (vikunja_worker_orchestrator.py) and the host
# supervisor (vikunja_worker_supervisor.py) run the worker loop synchronously
# in their own processes — no hermes_cli.main subprocess is spawned per task,
# so the two "cron run" patterns above are blind to them. Detect both script
# names so stale-claim reaping does not fire mid-run.
WORKER_ORCHESTRATOR_PROCESS_PATTERN = "vikunja_worker_orchestrator.py"
WORKER_SUPERVISOR_PROCESS_PATTERN = "vikunja_worker_supervisor.py"
JUDGE_PROCESS_PATTERN = f"cron run {CFG.job('judge')}"
JUDGE_ESCALATE_PROCESS_PATTERN = f"cron run {CFG.job('judge_escalate')}"
VENV_PY = HERMES_HOME / "hermes-agent" / "venv" / "bin" / "python"
JUDGE_TRIGGER_LOG = HERMES_HOME / "logs" / "vikunja_judge_trigger.log"
MENTION_TRIGGER_LOG = HERMES_HOME / "logs" / "vikunja_mention_trigger.log"
PREFLIGHT_LOG = HERMES_HOME / "logs" / "vikunja_preflight.log"
REVIEW_PY = Path.home() / "projects" / "hermes-review" / "hermes_review.py"


def load_env() -> None:
    env_file = HERMES_HOME / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text().splitlines():
        if not raw or raw.lstrip().startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        if key in {"VIKUNJA_API_TOKEN", "VIKUNJA_URL"} and key not in os.environ:
            os.environ[key] = value.strip().strip('"').strip("'")


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _process_running(pattern: str) -> bool:
    result = subprocess.run(
        ["pgrep", "-f", pattern],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return result.returncode == 0


def worker_running() -> bool:
    """True when a worker cron job, the daily orchestrator, or the host
    supervisor is running."""
    return (
        _process_running(WORKER_PROCESS_PATTERN)
        or _process_running(WORKER_ESCALATE_PROCESS_PATTERN)
        or _process_running(WORKER_ORCHESTRATOR_PROCESS_PATTERN)
        or _process_running(WORKER_SUPERVISOR_PROCESS_PATTERN)
    )


def judge_running() -> bool:
    return _process_running(JUDGE_PROCESS_PATTERN) or _process_running(
        JUDGE_ESCALATE_PROCESS_PATTERN
    )


def mention_running() -> bool:
    return _process_running(MENTION_PROCESS_PATTERN)


def reap_stale_claims(client: httpx.Client, now: datetime | None = None) -> list[int]:
    """Return stale claim IDs after clearing abandoned in-progress labels.

    Claims are timestamped by the worker's claim comment. When a task holds
    in-progress with no claim comment (e.g. an interactive session left the
    label on), the fallback staleness clock is the task's last activity:
    newest comment or, failing that, the task's updated timestamp. We only
    reap when no worker process is alive; this avoids turning a slow, valid
    run into a second dispatch.

    Claim-marked tasks are returned to worker:ready ONLY when no executor
    label remains (a worker:escalate task must not gain worker:ready and be
    mis-routed). Claim-less tasks are never given an executor label —
    they were never released for dispatch; Julian re-routes.
    """
    if worker_running():
        return []
    now = now or datetime.now(timezone.utc)
    response = client.get("/tasks", params={"filter": "done = false", "per_page": 100})
    response.raise_for_status()
    labels_response = client.get("/labels")
    labels_response.raise_for_status()
    label_ids = {
        label.get("title"): label.get("id") for label in labels_response.json() or []
    }
    in_progress_id = label_ids.get(L["in_progress"])
    ready_id = label_ids.get(L["worker_ready"])
    if in_progress_id is None or ready_id is None:
        raise RuntimeError(
            f"Vikunja label vocabulary lacks {L['in_progress']!r} or {L['worker_ready']!r}"
        )
    executor_titles = {L["worker_ready"], L["worker_escalate"]}
    stale: list[int] = []
    for task in response.json() or []:
        labels = {label.get("title") for label in (task.get("labels") or [])}
        if L["in_progress"] not in labels:
            continue
        comments_response = client.get(f"/tasks/{task['id']}/comments")
        comments_response.raise_for_status()
        comments = comments_response.json() or []
        claim_times = []
        other_times = []
        for comment in comments:
            text = (comment.get("comment") or "").strip().lower()
            created = comment.get("created")
            if not created:
                continue
            if text.startswith(REAPER_PREFIX):
                continue
            if any(marker in text for marker in CLAIM_MARKERS):
                claim_times.append(_parse_timestamp(created))
            else:
                other_times.append(_parse_timestamp(created))
        if claim_times:
            last_activity = max(claim_times)
        else:
            fallbacks = other_times
            if task.get("updated"):
                fallbacks = fallbacks + [_parse_timestamp(task["updated"])]
            last_activity = max(fallbacks) if fallbacks else None
        if last_activity is None or now - last_activity < CLAIM_STALE_AFTER:
            continue
        task_id = task["id"]
        client.delete(f"/tasks/{task_id}/labels/{in_progress_id}").raise_for_status()
        requeued = False
        if claim_times and not labels & executor_titles:
            client.put(
                f"/tasks/{task_id}/labels",
                json={"label_id": ready_id},
            ).raise_for_status()
            requeued = True
        if requeued:
            note = (
                f"{REAPER_PREFIX} cleared stale in-progress claim after "
                f"{CLAIM_STALE_AFTER}; no worker process was alive. "
                f"Task returned to {L['worker_ready']} for dispatch."
            )
        elif claim_times:
            note = (
                f"{REAPER_PREFIX} cleared stale in-progress claim after "
                f"{CLAIM_STALE_AFTER}; no worker process was alive. Executor "
                f"label intact ({', '.join(sorted(labels & executor_titles))}); "
                f"not re-queued as {L['worker_ready']}."
            )
        else:
            note = (
                f"{REAPER_PREFIX} cleared abandoned in-progress after "
                f"{CLAIM_STALE_AFTER} with no claim comment and no worker "
                f"process alive. No executor label re-applied — this task was "
                f"never released for dispatch; re-route manually if needed."
            )
        client.put(
            f"/tasks/{task_id}/comments",
            json={"comment": note},
        ).raise_for_status()
        stale.append(task_id)
    return stale


def _snoozed(client: httpx.Client, task_id: int) -> bool:
    try:
        data = hmc.list_machine(client, task_id)
    except Exception:
        return False
    return hmc.is_snoozed(data.get("control"))


def eligible_worker_tasks(client: httpx.Client) -> list[dict]:
    response = client.get("/tasks", params={"filter": "done = false", "per_page": 100})
    response.raise_for_status()
    out = []
    for task in response.json() or []:
        labels = {label.get("title") for label in (task.get("labels") or [])}
        if (
            L["worker_ready"] in labels or L["worker_escalate"] in labels
        ) and not labels & {
            L["in_progress"],
            L["blocked"],
            L["human_only"],
            L["needs_review"],
            L["judge_ready"],
            L["judge_escalate"],
        }:
            if _snoozed(client, task["id"]):
                continue
            out.append(task)
    return out


def eligible_judge_tasks(client: httpx.Client) -> list[dict]:
    """yaml judge_ready or judge_escalate (escalate is enough on its own)."""
    response = client.get("/tasks", params={"filter": "done = false", "per_page": 100})
    response.raise_for_status()
    out = []
    for task in response.json() or []:
        labels = {label.get("title") for label in (task.get("labels") or [])}
        if not (L["judge_ready"] in labels or L["judge_escalate"] in labels):
            continue
        if labels & {L["blocked"], L["human_only"], L["in_progress"]}:
            continue
        if _snoozed(client, task["id"]):
            continue
        out.append(task)
    return out


def pick_worker_job(tasks: list[dict]) -> str:
    """Route to escalate worker when any ready task carries worker_escalate."""
    for task in tasks:
        labels = {label.get("title") for label in (task.get("labels") or [])}
        if L["worker_escalate"] in labels:
            return CFG.job("worker_escalate")
    return CFG.job("worker")


def pick_judge_job(tasks: list[dict]) -> str:
    for task in tasks:
        labels = {label.get("title") for label in (task.get("labels") or [])}
        if L["judge_escalate"] in labels:
            return CFG.job("judge_escalate")
    return CFG.job("judge")


def heartbeat(
    *, eligible: int, reaped: int, action: str, judge_eligible: int = 0
) -> None:
    """One line per tick so silence ≠ failure (risks R4)."""
    PREFLIGHT_LOG.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().astimezone().isoformat(timespec="seconds")
    line = (
        f"{ts} eligible={eligible} judge_eligible={judge_eligible} "
        f"reaped={reaped} action={action}\n"
    )
    with PREFLIGHT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(line)


def _profile_jobs_file(profile: str) -> Path:
    if profile == "default":
        return HERMES_HOME / "cron" / "jobs.json"
    return HERMES_HOME / "profiles" / profile / "cron" / "jobs.json"


def _job_record(profile: str, job_name: str) -> dict | None:
    try:
        payload = json.loads(_profile_jobs_file(profile).read_text())
    except (OSError, ValueError):
        return None
    for job in payload.get("jobs", []):
        if job.get("id") == job_name or job.get("name") == job_name:
            return job
    return None


def _resume_auto_completed_job(
    profile: str, job_name: str, log_path: Path
) -> tuple[bool, str]:
    """Re-arm an on-demand job after Hermes marked its previous run complete.

    A deliberate pause is preserved. Only the terminal state produced by an
    on-demand run (``completed`` with no ``paused_at``) is resumed.
    """
    job = _job_record(profile, job_name)
    if job is None:
        return False, f"{profile} job {job_name!r} not found"
    if job.get("state") == "paused" or job.get("paused_at"):
        return False, f"{profile} job {job_name} is deliberately paused"
    if job.get("enabled") and job.get("state") != "completed":
        return True, ""
    if job.get("state") != "completed":
        return False, (
            f"{profile} job {job_name} is disabled in unexpected state "
            f"{job.get('state')!r}"
        )

    cmd = [
        str(VENV_PY),
        "-m",
        "hermes_cli.main",
        "-p",
        profile,
        "cron",
        "resume",
        job_name,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=RESUME_TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"resume failed: {exc}"
    blob = (proc.stdout or "") + (proc.stderr or "")
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as fh:
            fh.write(blob.encode())
            if blob and not blob.endswith("\n"):
                fh.write(b"\n")
    except OSError as exc:
        return False, f"cannot write trigger log: {exc}"
    if proc.returncode != 0:
        return False, f"resume exited {proc.returncode}: {blob.strip()[-500:]}"
    return True, ""


def _trigger_profile(profile: str, job_name: str, log_path: Path) -> tuple[bool, str]:
    ok, err = _resume_auto_completed_job(profile, job_name, log_path)
    if not ok:
        return False, err
    cmd = [
        str(VENV_PY),
        "-m",
        "hermes_cli.main",
        "-p",
        profile,
        "cron",
        "run",
        job_name,
    ]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    offset = log_path.stat().st_size if log_path.exists() else 0
    try:
        log_f = open(log_path, "ab", buffering=0)
    except OSError as exc:
        return False, f"cannot open trigger log: {exc}"
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        log_f.close()
        return False, str(exc)
    log_f.close()

    deadline = time.monotonic() + TRIGGER_ACCEPT_SECONDS
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            if rc != 0:
                return False, (
                    f"{profile} trigger exited {rc} within accept window "
                    f"(see {log_path})"
                )
            try:
                output = log_path.read_bytes()[offset:].decode(
                    "utf-8", errors="replace"
                )
            except OSError:
                output = ""
            if any(marker in output.lower() for marker in CRON_RUN_SKIP_MARKERS):
                return False, (
                    f"{profile} job skipped as paused/disabled after resume "
                    f"(see {log_path})"
                )
            return True, ""
        time.sleep(0.05)
    return True, ""


def trigger_judge(job_name: str | None = None) -> tuple[bool, str]:
    return _trigger_profile("judge", job_name or CFG.job("judge"), JUDGE_TRIGGER_LOG)


def trigger_mentions() -> tuple[bool, str]:
    if mention_running():
        return True, "busy"
    if not REVIEW_PY.is_file():
        return False, f"missing {REVIEW_PY}"
    cmd = [str(VENV_PY), str(REVIEW_PY), "mention"]
    MENTION_TRIGGER_LOG.parent.mkdir(parents=True, exist_ok=True)
    try:
        log_f = open(MENTION_TRIGGER_LOG, "ab", buffering=0)
    except OSError as exc:
        return False, f"cannot open mention log: {exc}"
    try:
        subprocess.Popen(
            cmd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    except OSError as exc:
        log_f.close()
        return False, str(exc)
    log_f.close()
    return True, ""


def _cap_state(state_file: Path) -> dict:
    today = date.today().isoformat()
    if state_file.exists():
        try:
            saved = json.loads(state_file.read_text())
            if saved.get("date") == today:
                return saved
        except (ValueError, OSError):
            pass
    return {"date": today, "count": 0}


def under_cap(state_file: Path, daily_cap: int) -> bool:
    """Check the daily cap without consuming it.

    The count is recorded only after the subprocess accepts the dispatch. A
    rejected fire must not spend a worker or judge run.
    """
    return _cap_state(state_file)["count"] < daily_cap


def record_dispatch(state_file: Path) -> None:
    state = _cap_state(state_file)
    state["count"] += 1
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state))


def main() -> int:
    load_env()
    base = (
        os.environ.get("VIKUNJA_URL", "http://localhost:8788").rstrip("/") + "/api/v1"
    )
    headers = {"Authorization": f"Bearer {os.environ['VIKUNJA_API_TOKEN']}"}
    actions: list[str] = []
    try:
        with httpx.Client(base_url=base, headers=headers, timeout=20.0) as client:
            reaped = reap_stale_claims(client)
            worker_tasks = eligible_worker_tasks(client)
            judge_tasks = eligible_judge_tasks(client)
    except Exception as exc:  # a broken tracker must be loud, not silent
        print(f"vikunja preflight FAILED: {exc}")
        return 1

    # Worker dispatch is owned by the 01:00 vikunja-worker-supervisor job.
    actions.append("worker_orchestrated")

    # --- judge dispatch (independent of worker; skip if judge already running) ---
    if judge_tasks:
        if judge_running():
            actions.append("judge_busy")
        elif not under_cap(JUDGE_STATE_FILE, JUDGE_DAILY_CAP):
            actions.append("judge_cap")
        else:
            job = pick_judge_job(judge_tasks)
            ok, err = trigger_judge(job)
            if not ok:
                actions.append(f"fail:{job}")
                heartbeat(
                    eligible=len(worker_tasks),
                    judge_eligible=len(judge_tasks),
                    reaped=len(reaped),
                    action=",".join(actions),
                )
                print(f"vikunja preflight: failed to trigger judge: {err[:300]}")
                return 1
            record_dispatch(JUDGE_STATE_FILE)
            actions.append(f"dispatch:{job}")
            ids = ", ".join(f"#{t['id']}" for t in judge_tasks[:5])
            print(
                f"vikunja judge dispatch: {len(judge_tasks)} task(s) ({ids}) — {job} triggered"
            )
    else:
        actions.append("judge_idle")

    # --- mention replies (independent; skip if a mention run is already live) ---
    ok, err = trigger_mentions()
    if err == "busy":
        actions.append("mention_busy")
    elif not ok:
        actions.append("mention_fail")
        print(f"vikunja preflight: failed to trigger mentions: {err[:300]}")
    else:
        actions.append("mention_scan")

    heartbeat(
        eligible=len(worker_tasks),
        judge_eligible=len(judge_tasks),
        reaped=len(reaped),
        action=",".join(actions),
    )
    if reaped and not worker_tasks:
        print(
            f"vikunja reaper: cleared {len(reaped)} stale in-progress claim(s); "
            f"executor labels re-applied only where a dispatch claim existed"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
