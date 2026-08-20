#!/home/julian/.hermes/hermes-agent/venv/bin/python
"""Hermes Review — Catkin dashboard on :8789.

Vikunja's API token stays on the box. The browser talks only to this process.

Write routes require a per-start secret (X-Hermes-Review-Token) injected into
the HTML. Host must match HERMES_REVIEW_HOST (the tailnet bind), not localhost.
That blocks CSRF and DNS rebinding. A tailnet peer who loads the page can still
scrape the token; that is the remaining threat.
"""
from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
SCRIPTS = HERMES_HOME / "scripts"
sys.path.insert(0, str(SCRIPTS))
import hermes_machine_comments as hmc  # noqa: E402
from vikunja_config import load as load_vikunja_config  # noqa: E402
import vikunja_preflight as vpre  # noqa: E402
import monitor  # noqa: E402

CFG = load_vikunja_config()
L = CFG.labels

BASE_DIR = Path(__file__).resolve().parent
STATIC = BASE_DIR / "static"
TZ = ZoneInfo("America/Los_Angeles")
HOST = os.environ.get("HERMES_REVIEW_HOST", "localhost")
PORT = int(os.environ.get("HERMES_REVIEW_PORT", "8789"))
WRITE_TOKEN = secrets.token_urlsafe(32)
UNDO_TOKENS: dict[str, dict] = {}
TOKEN_HEADER = "X-Hermes-Review-Token"
INDEX_TOKEN_PLACEHOLDER = "{{HERMES_REVIEW_TOKEN}}"
PREFLIGHT_LOG = HERMES_HOME / "logs" / "vikunja_preflight.log"
WEBUI_BASE = os.environ.get("HERMES_WEBUI_URL", "http://127.0.0.1:8787")
WEBUI_ENV = Path("/home/julian/projects/hermes-webui/.env")
REVIEW_MODEL = str(CFG.discuss["model"])
REVIEW_TOOLSETS = list(CFG.discuss.get("toolsets") or [])
REVIEW_TOOLSETS_WITHOUT_REPO = list(CFG.discuss.get("toolsets_without_repo") or [])
WORKSPACE_WITHOUT_REPO = str(CFG.discuss.get("workspace_without_repo") or "")
CTX_OPEN = "[[review-context]]"
CTX_CLOSE = "[[/review-context]]"
TAILNET = ipaddress.ip_network((0x64400000, 10))  # RFC 6598 CGNAT base /10
DISPOSITION_PREFIX = "Hermes Review:"
MACHINE_MARKERS = (
    "<!-- hermes:",
    "<<<hermes:",
)
BOT_USER_ID = int(CFG.mention["user_id"])
BOT_USERNAME = str(CFG.mention["username"])
MENTION_RE = re.compile(
    rf"@{re.escape(BOT_USERNAME)}\b|data-mention[^>]*\b(?:user[-_]?id|id)\s*=\s*[\"']?{BOT_USER_ID}\b",
    re.I,
)
MENTION_CAP = 3
MENTION_WAIT_SECONDS = 180

PRIORITY_LABEL = {
    0: "unset",
    1: "low",
    2: "medium",
    3: "high",
    4: "urgent",
    5: "DO NOW",
}


def mentions_bot(text: str) -> bool:
    return bool(MENTION_RE.search(text or ""))


def _plain_comment(text: str) -> str:
    stripped = re.sub(r"<[^>]+>", " ", text or "")
    return html.unescape(stripped).strip()


def load_env() -> None:
    hmc.load_env()


def _now() -> datetime:
    return datetime.now(TZ)


def vikunja_ui(host_header: str | None) -> str:
    base = os.environ.get("VIKUNJA_URL") or CFG.vikunja_ui or "http://localhost:8788"
    if not host_header:
        return CFG.vikunja_ui or "http://localhost:8788"
    host = host_header.rsplit(":", 1)[0].strip("[]")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return base
    if ip in TAILNET:
        return f"http://{host}:8788"
    return base


def _client() -> httpx.Client:
    return hmc._client()


def _labels(client: httpx.Client) -> dict[str, int]:
    r = client.get("/labels")
    r.raise_for_status()
    return {l.get("title"): l.get("id") for l in r.json() or []}


def _add_label(
    client: httpx.Client, task_id: int, title: str, ids: dict[str, int]
) -> None:
    lid = ids.get(title)
    if lid is None:
        raise RuntimeError(f"missing Vikunja label {title!r}")
    client.put(f"/tasks/{task_id}/labels", json={"label_id": lid}).raise_for_status()


def _remove_label(
    client: httpx.Client,
    task_id: int,
    title: str,
    ids: dict[str, int],
    attached: set[str] | None = None,
) -> None:
    if attached is not None and title not in attached:
        return
    lid = ids.get(title)
    if lid is None:
        return
    r = client.delete(f"/tasks/{task_id}/labels/{lid}")
    # Vikunja returns 403 (not 404) when the label is not on the task.
    if r.status_code not in {200, 204, 404, 403}:
        r.raise_for_status()


def _comment(client: httpx.Client, task_id: int, text: str) -> None:
    client.put(f"/tasks/{task_id}/comments", json={"comment": text}).raise_for_status()


def _webui_password() -> str:
    if WEBUI_ENV.exists():
        for raw in WEBUI_ENV.read_text().splitlines():
            if raw.startswith("HERMES_WEBUI_PASSWORD="):
                return raw.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("HERMES_WEBUI_PASSWORD", "")


class WebuiClient:
    """Loopback client for hermes-webui. Never forwards Origin/Referer."""

    def __init__(self) -> None:
        self._http = httpx.Client(base_url=WEBUI_BASE, timeout=30.0)
        self._authed = False

    def login(self) -> None:
        password = _webui_password()
        if not password:
            raise RuntimeError("HERMES_WEBUI_PASSWORD missing")
        r = self._http.post("/api/auth/login", json={"password": password})
        r.raise_for_status()
        self._authed = True

    def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self._authed:
            self.login()
        r = self._http.request(method, path, **kwargs)
        if r.status_code == 401:
            self._authed = False
            self.login()
            r = self._http.request(method, path, **kwargs)
        return r


_webui = WebuiClient()


def _msg_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        bits = []
        for part in content:
            if isinstance(part, str):
                bits.append(part)
            elif isinstance(part, dict):
                bits.append(str(part.get("text") or part.get("content") or ""))
        return "".join(bits)
    return str(content or "")


def _strip_envelope(text: str) -> str:
    start = text.find(CTX_OPEN)
    end = text.find(CTX_CLOSE)
    if start < 0 or end < 0 or end < start:
        return text.strip()
    return (text[:start] + text[end + len(CTX_CLOSE) :]).strip()


def _session_messages(session: dict) -> list[dict]:
    out = []
    for m in session.get("messages") or []:
        role = m.get("role") or ""
        if role not in {"user", "assistant"}:
            continue
        text = _strip_envelope(_msg_text(m.get("content")))
        if not text:
            continue
        out.append(
            {
                "who": "me" if role == "user" else "hermes",
                "text": text,
                "at": str(m.get("timestamp") or ""),
            }
        )
    return out


def _webui_session(session_id: str) -> dict:
    r = _webui.request(
        "GET", "/api/session", params={"session_id": session_id, "messages": 1}
    )
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    data = r.json() or {}
    if isinstance(data.get("session"), dict):
        return data["session"]
    return data if isinstance(data, dict) else {}


def _pending_notice(session_id: str) -> str | None:
    appr = _webui.request(
        "GET", "/api/approval/pending", params={"session_id": session_id}
    )
    if appr.status_code == 200 and (appr.json() or {}).get("pending"):
        return "Hermes is waiting for approval in webui"
    clar = _webui.request(
        "GET", "/api/clarify/pending", params={"session_id": session_id}
    )
    if clar.status_code == 200 and (clar.json() or {}).get("pending"):
        return "Hermes is waiting for a clarify answer in webui"
    return None


def _ensure_session(vik: httpx.Client, task: dict, machine: dict) -> str:
    existing = (machine.get("session") or {}).get("webui_session_id") or ""
    if existing:
        sess = _webui_session(existing)
        if sess:
            return existing
    attempts = machine.get("attempts") or []
    git = (attempts[-1].get("git") if attempts else {}) or {}
    repo = git.get("repo") or ""
    workspace = repo if repo and Path(repo).is_dir() else WORKSPACE_WITHOUT_REPO
    toolsets = (
        REVIEW_TOOLSETS
        if repo and Path(repo).is_dir()
        else (REVIEW_TOOLSETS_WITHOUT_REPO or REVIEW_TOOLSETS)
    )
    if not workspace or not Path(workspace).is_dir():
        raise RuntimeError("no workspace for discuss session")
    r = _webui.request(
        "POST",
        "/api/session/new",
        json={
            "worktree": False,
            "profile": "default",
            "model": REVIEW_MODEL,
            "workspace": workspace,
            "enabled_toolsets": toolsets,
        },
    )
    r.raise_for_status()
    body = r.json() or {}
    sess = body.get("session") or body
    sid = sess.get("session_id") or sess.get("id")
    if not sid:
        raise RuntimeError("webui session/new returned no session_id")
    ident = f"#{task['id']}"
    _webui.request(
        "POST",
        "/api/session/rename",
        json={"session_id": sid, "title": f"review · {ident}"},
    ).raise_for_status()
    hmc.upsert_session(vik, int(task["id"]), webui_session_id=sid)
    return sid


def _context_envelope(task: dict, machine: dict, artifacts: list) -> str:
    ident = f"#{task['id']}"
    title = task.get("title") or ident
    attempts = machine.get("attempts") or []
    judges = machine.get("judges") or []
    latest_a = attempts[-1] if attempts else {}
    latest_j = judge_for_attempt(judges, latest_a.get("n"))
    summary = latest_a.get("summary") or []
    lines = [
        CTX_OPEN,
        f"Ticket {ident}: {title}",
        f"Judge: {latest_j.get('verdict') or '—'} ({latest_j.get('model') or '—'})",
        f"Attempt {latest_a.get('n') or 0} summary:",
    ]
    if summary:
        lines.extend(f"- {s}" for s in summary[:8])
    else:
        lines.append("- (none)")
    diff = ""
    for art in artifacts:
        if art.get("kind") == "diff" and art.get("diff"):
            diff = art["diff"]
            break
    if diff:
        if len(diff) > 12000:
            diff = diff[:12000] + "\n… truncated …\n"
        lines.append("Diff (truncated):")
        lines.append(diff)
    lines.append(
        "Do not change Vikunja labels or mark tasks done. Julian dispositions with the buttons."
    )
    lines.append(CTX_CLOSE)
    return "\n".join(lines)


def discuss_status(task_id: int) -> dict:
    load_env()
    with _client() as vik:
        machine = hmc.list_machine(vik, task_id)
        sid = (machine.get("session") or {}).get("webui_session_id") or ""
        if not sid:
            return {
                "messages": [],
                "status": "idle",
                "session_id": None,
                "notice": None,
            }
        sess = _webui_session(sid)
        if not sess:
            return {
                "messages": [],
                "status": "missing",
                "session_id": sid,
                "notice": "session gone in webui — send to start a new one",
            }
        notice = _pending_notice(sid)
        streaming = bool(sess.get("active_stream_id"))
        status = "paused" if notice else ("streaming" if streaming else "idle")
        return {
            "messages": _session_messages(sess),
            "status": status,
            "session_id": sid,
            "notice": notice,
            "model": sess.get("model"),
            "enabled_toolsets": sess.get("enabled_toolsets"),
        }


def discuss_send(task_id: int, user_text: str) -> dict:
    text = (user_text or "").strip()
    if not text:
        raise RuntimeError("empty")
    load_env()
    with _client() as vik:
        task_r = vik.get(f"/tasks/{task_id}")
        task_r.raise_for_status()
        task = task_r.json()
        machine = hmc.list_machine(vik, task_id)
        assembled = _assemble_ticket(vik, task, "http://localhost:8788")
        sid = _ensure_session(vik, task, machine)
        sess = _webui_session(sid)
        first = not _session_messages(sess)
        payload = (
            _context_envelope(task, machine, assembled.get("artifacts") or [])
            + "\n\n"
            + text
            if first
            else text
        )
        r = _webui.request(
            "POST",
            "/api/chat/start",
            json={
                "session_id": sid,
                "message": payload,
                "model": REVIEW_MODEL,
                "profile": "default",
            },
        )
        if r.status_code == 409:
            return {
                "ok": False,
                "status": "busy",
                "session_id": sid,
                "notice": "Hermes is busy (webui or another send)",
                "messages": _session_messages(sess),
            }
        r.raise_for_status()
        started = r.json() or {}
        return {
            "ok": True,
            "status": "streaming",
            "session_id": sid,
            "stream_id": started.get("stream_id"),
            "notice": None,
            "messages": _session_messages(_webui_session(sid)),
        }


def _heartbeat() -> dict[str, str]:
    last = ""
    if PREFLIGHT_LOG.exists():
        lines = PREFLIGHT_LOG.read_text(encoding="utf-8").splitlines()
        if lines:
            last = lines[-1][:80]
    nxt = (_now() + timedelta(minutes=30)).strftime("%H:%M")
    return {"last": last or "no preflight log yet", "next": f"~{nxt} Pacific"}


def _split_paras(text: str) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text).strip()
    if not text:
        return []
    parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    return parts or [text]


def _human_comments(raw: list[dict]) -> list[dict]:
    out = []
    for c in raw or []:
        raw_text = (c.get("comment") or "").strip()
        if not raw_text or any(m in raw_text for m in MACHINE_MARKERS):
            continue
        author = c.get("author") or {}
        uid = author.get("id")
        uname = (author.get("username") or "").lower()
        who = "hermes" if uid == BOT_USER_ID or uname == BOT_USERNAME else "me"
        text = _plain_comment(raw_text)
        if not text:
            continue
        out.append({"who": who, "text": text, "at": c.get("created") or ""})
    return out


def _parse_disposition(comments: list[dict]) -> dict | None:
    for c in reversed(comments):
        text = (c.get("text") or "").strip()
        if not text.startswith(DISPOSITION_PREFIX):
            continue
        rest = text[len(DISPOSITION_PREFIX) :].strip()
        kind = rest.split(" ", 1)[0].rstrip(":")
        note = rest[len(kind) :].strip(" :—-")
        return {"kind": kind, "note": note, "at": c.get("at") or ""}
    return None


def _machine_marker_ids(machine: dict) -> list[int]:
    ids = []
    for bucket in ("attempts", "judges"):
        for row in machine.get(bucket) or []:
            cid = row.get("_comment_id")
            if cid is not None:
                ids.append(int(cid))
    for key in ("control_comment_id", "session_comment_id", "organizer_comment_id"):
        cid = machine.get(key)
        if cid is not None:
            ids.append(int(cid))
    return sorted(set(ids))


def _handoff_comment(comments: list[dict], machine: dict, attempt: dict) -> dict | None:
    """Latest human-readable comment posted after this attempt's machine
    marker and before the next one — the worker's handoff note (td-4952a9).

    Non-Git attempts (host-operations tasks) have no git pointers, so this
    is the only execution evidence available for the run-log section.
    """
    a_id = attempt.get("_comment_id")
    if a_id is None:
        return None
    a_id = int(a_id)
    markers = _machine_marker_ids(machine)
    upper = next((m for m in markers if m > a_id), None)
    best = None
    for c in comments or []:
        cid = c.get("id")
        if cid is None:
            continue
        cid = int(cid)
        if cid <= a_id or (upper is not None and cid >= upper):
            continue
        raw_text = (c.get("comment") or "").strip()
        if not raw_text or any(m in raw_text for m in MACHINE_MARKERS):
            continue
        author = c.get("author") or {}
        uid = author.get("id")
        uname = (author.get("username") or "").lower()
        if not (uid == BOT_USER_ID or uname == BOT_USERNAME):
            continue
        if best is None or cid > int(best.get("id") or 0):
            best = c
    return best


def _handoff_log_lines(
    comments: list[dict], machine: dict, attempt: dict
) -> list[dict]:
    handoff = _handoff_comment(comments, machine, attempt)
    if not handoff:
        return []
    at = handoff.get("created") or ""
    paras = _split_paras(handoff.get("comment") or "")
    return [{"at": at, "level": "handoff", "msg": p} for p in paras]


def _board_bucket(labels: set[str]) -> str | None:
    """Which Review list a task belongs on. One lane wins; blocked is last."""
    if L["human_only"] in labels:
        return "human"
    if L["needs_review"] in labels:
        return "review"
    if L["blocked"] in labels:
        return "blocked"
    if labels & {
        L["worker_ready"],
        L["worker_escalate"],
        L["judge_ready"],
        L["judge_escalate"],
    }:
        return "queue"
    return None


def _classify(labels: set[str]) -> str:
    if L["human_only"] in labels:
        return L["human_only"]
    if L["needs_review"] in labels:
        return L["needs_review"]
    if L["judge_escalate"] in labels:
        return L["judge_escalate"]
    if L["judge_ready"] in labels:
        return "judge-ready"
    if L["worker_escalate"] in labels:
        return L["worker_escalate"]
    if L["worker_ready"] in labels:
        return "worker-ready"
    if L["blocked"] in labels:
        return L["blocked"]
    return "unclassified"


def judge_for_attempt(judges: list | None, attempt_n) -> dict:
    """Judge comment for this attempt, not judges[-1] (td-b2b873)."""
    n = int(attempt_n or 0)
    if n <= 0:
        return {}
    for j in reversed(list(judges or [])):
        if int(j.get("attempt") or 0) == n:
            return j
    return {}


def serialize_judge(judge: dict | None) -> dict:
    """Pane payload for one hermes:judge comment.

    An empty judges list (or a comment with no verdict) must not invent
    verdict thin or confidence 0.00 — that is a fake judge (td-b4f126).
    """
    judge = judge or {}
    verdict = judge.get("verdict")
    if not verdict:
        return {
            "model": None,
            "verdict": None,
            "confidence": None,
            "notes": [],
            "checks": [],
        }
    return {
        "model": judge.get("model") or "—",
        "verdict": verdict,
        "confidence": float(judge.get("confidence") or 0),
        "notes": judge.get("notes") or [],
        "checks": judge.get("checks") or [],
        "finished_at": judge.get("finished_at")
        or judge.get("at")
        or judge.get("created")
        or "",
    }


def _assemble_ticket(client: httpx.Client, task: dict, ui: str) -> dict:
    tid = task["id"]
    labels = [l.get("title") for l in (task.get("labels") or []) if l.get("title")]
    labelset = set(labels)
    machine = hmc.list_machine(client, tid)
    comments_r = client.get(f"/tasks/{tid}/comments")
    comments_r.raise_for_status()
    comments = comments_r.json() or []
    monitor.stamp_comment_times(machine, comments)
    chat = _human_comments(comments)
    attempts = machine.get("attempts") or []
    judges = machine.get("judges") or []
    latest_a = attempts[-1] if attempts else {}
    latest_j = judge_for_attempt(judges, latest_a.get("n"))
    git = latest_a.get("git") or {}
    git_pointers = bool(git.get("repo") and git.get("base") and git.get("tip"))
    artifacts = []
    log_lines = []
    if git_pointers:
        gr = hmc.git_range(git["repo"], git["base"], git["tip"])
        diff_ok = bool(gr.get("ok"))
        if diff_ok:
            stat_lines = (gr.get("diff_stat") or "").strip().splitlines()
            detail = (
                stat_lines[-1]
                if stat_lines
                else f"{git.get('base', '')[:7]}..{git.get('tip', '')[:7]}"
            )
        else:
            err_lines = (
                (gr.get("stderr") or gr.get("error") or "git diff failed")
                .strip()
                .splitlines()
            )
            detail = err_lines[0] if err_lines else "git diff failed"
        artifacts.append(
            {
                "kind": "diff",
                "name": git.get("branch") or Path(git["repo"]).name,
                "ok": diff_ok,
                "detail": detail,
                "diff": gr.get("diff") or "",
            }
        )
        for line in (gr.get("log") or "").splitlines():
            log_lines.append({"at": "", "level": "ok", "msg": line})
    elif latest_a:
        # Non-Git (host-operations) attempt: no git object to diff or log.
        # Surface the worker's handoff comment instead (td-4952a9).
        log_lines = _handoff_log_lines(comments, machine, latest_a)
    history = []
    for a in attempts[:-1] if len(attempts) > 1 else []:
        matched = judge_for_attempt(judges, a.get("n"))
        history.append(
            {
                "at": a.get("finished_at") or "",
                "head": f"attempt {a.get('n')} · {a.get('finished_at') or ''} · {matched.get('verdict') or 'unjudged'}",
                "note": " ".join(a.get("summary") or []) or "(no summary)",
                "thenText": " ".join(a.get("summary") or []),
                "nowText": " ".join(latest_a.get("summary") or []),
                "comparable": True,
            }
        )
    project = (
        (task.get("project") or {}) if isinstance(task.get("project"), dict) else {}
    )
    project_title = project.get("title") or str(task.get("project_id") or "")
    identifier = f"#{tid}"
    snoozed = hmc.is_snoozed(machine.get("control"))
    disp = _parse_disposition(chat)
    pending = (
        L["needs_review"] in labelset
        and not task.get("done")
        and not snoozed
        and not (disp and disp.get("kind") in {"approve", "noAction", "discard"})
    )
    n = int(latest_a.get("n") or 0)
    return {
        "id": tid,
        "identifier": identifier,
        "title": task.get("title") or identifier,
        "description": _split_paras(task.get("description") or ""),
        "project": project_title,
        "project_id": task.get("project_id"),
        "labels": labels,
        "priority": int(task.get("priority") or 0),
        "priority_label": PRIORITY_LABEL.get(int(task.get("priority") or 0), "unset"),
        "href": f"{ui}/tasks/{tid}",
        "edit_href": f"{ui}/tasks/{tid}/edit",
        "classification": _classify(labelset),
        "created": task.get("created") or "",
        "updated": task.get("updated") or "",
        "due_date": task.get("due_date") or "",
        "done": bool(task.get("done")),
        "percent_done": task.get("percent_done") or 0,
        "assignees": [
            a.get("username") or a.get("name") or str(a.get("id"))
            for a in (task.get("assignees") or [])
        ],
        "attempt": {
            "n": n,
            "of": max(n, len(attempts)),
            "finished_at": latest_a.get("finished_at") or "",
            "summary": latest_a.get("summary") or [],
            "stats": (
                f"git {git.get('branch') or '—'} · {(git.get('tip') or '')[:7]}"
                if git
                else "no git pointers"
            ),
            "git": git,
            "git_pointers": git_pointers,
        },
        "judge": serialize_judge(latest_j),
        "judges": [
            {
                "verdict": j.get("verdict"),
                "model": j.get("model"),
                "attempt": j.get("attempt"),
                "n": j.get("attempt"),
                "finished_at": j.get("finished_at") or j.get("at") or "",
            }
            for j in judges
            if j.get("verdict")
        ],
        "history": history,
        "artifacts": artifacts,
        "log": log_lines,
        "chat": chat,
        "session_id": (machine.get("session") or {}).get("webui_session_id"),
        "drafts": [],
        "control": machine.get("control"),
        "snoozed": snoozed,
        "pending": pending,
        "disposition": disp,
        "age": task.get("updated") or task.get("created") or "",
    }


def _unit_active(name: str) -> bool | None:
    env = os.environ.copy()
    env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    try:
        r = subprocess.run(
            ["systemctl", "--user", "is-active", name],
            capture_output=True,
            text=True,
            env=env,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    status = (r.stdout or "").strip()
    if status == "active":
        return True
    if status in {"inactive", "failed", "deactivating", "activating", "dead"}:
        return False
    return None


def _recently_done(client: httpx.Client) -> tuple[list[dict], bool]:
    try:
        r = client.get(
            "/tasks",
            params={
                "filter": "done = true",
                "per_page": 15,
                "sort_by": "updated",
                "order_by": "desc",
            },
        )
        r.raise_for_status()
    except Exception:
        return [], False
    tasks = r.json() or []
    return tasks, len(tasks) >= 15


def _done_blocked(client: httpx.Client) -> tuple[list[dict], bool]:
    """Load completed blocked tasks so the blocked list can reopen them."""
    try:
        r = client.get(
            "/tasks",
            params={
                "filter": "done = true",
                "per_page": 100,
                "sort_by": "updated",
                "order_by": "desc",
            },
        )
        r.raise_for_status()
    except Exception:
        return [], False
    tasks = r.json() or []
    blocked = [
        task
        for task in tasks
        if L["blocked"] in {
            label.get("title") for label in (task.get("labels") or [])
        }
    ]
    return blocked, len(tasks) >= 100


def _dispatch_today(path: Path) -> int:
    return monitor.dispatch_count(path, _now().strftime("%Y-%m-%d"))


def build_board(host_header: str | None) -> dict:
    ui = vikunja_ui(host_header)
    load_env()
    with _client() as client:
        r = client.get("/tasks", params={"filter": "done = false", "per_page": 100})
        r.raise_for_status()
        tasks = r.json() or []
        tickets = []
        human_only = []
        queue = []
        blocked = []
        for task in tasks:
            labels = {l.get("title") for l in (task.get("labels") or [])}
            bucket = _board_bucket(labels)
            if bucket == "human":
                human_only.append(_assemble_ticket(client, task, ui))
            elif bucket == "review":
                tickets.append(_assemble_ticket(client, task, ui))
            elif bucket == "queue":
                queue.append(_assemble_ticket(client, task, ui))
            elif bucket == "blocked":
                blocked.append(_assemble_ticket(client, task, ui))
        claim_sources = []
        for task in tasks:
            titles = [
                l.get("title") for l in (task.get("labels") or []) if l.get("title")
            ]
            if L["in_progress"] in titles:
                claim_sources.append(
                    {
                        "id": task["id"],
                        "identifier": f"#{task['id']}",
                        "title": task.get("title") or f"#{task['id']}",
                        "labels": titles,
                    }
                )
        truncated = []
        if len(tasks) >= 100:
            truncated.append("open task list hit per_page 100")
        extra_events = []
        done_tasks, done_capped = _recently_done(client)
        if done_capped:
            truncated.append("recently-done machine comments capped at 15")
        done_blocked, done_blocked_capped = _done_blocked(client)
        if done_blocked_capped:
            truncated.append("completed blocked list capped at 100")
        seen = {t["id"] for t in tickets + queue + human_only + blocked}
        for task in done_blocked:
            if task["id"] in seen:
                continue
            if _board_bucket(
                {l.get("title") for l in (task.get("labels") or [])}
            ) == "blocked":
                blocked.append(_assemble_ticket(client, task, ui))
                seen.add(task["id"])
        for task in done_tasks:
            if task.get("id") in seen:
                continue
            try:
                comments_r = client.get(f"/tasks/{task['id']}/comments")
                comments_r.raise_for_status()
                machine = hmc.list_machine(client, task["id"])
                monitor.stamp_comment_times(machine, comments_r.json() or [])
                extra_events.extend(monitor.events_from_machine(task, machine))
            except Exception:
                continue
        worker_live = vpre.worker_running()
        judge_live = vpre.judge_running()
        claims = monitor.claim_rows(
            claim_sources, L["in_progress"], worker_live, judge_live
        )
        units = {name: _unit_active(name) for name in monitor.UNITS}
        preflight_path = HERMES_HOME / "logs" / "vikunja_preflight.log"
        preflight_text = monitor.read_text_capped(preflight_path)
        ticks = monitor.parse_preflight_log(preflight_text)
        preflight_missing = not preflight_path.is_file()
        preflight_age_s = None
        if ticks and ticks[-1].get("ts"):
            preflight_age_s = (_now() - ticks[-1]["ts"]).total_seconds()
        log_dir = HERMES_HOME / "logs"
        calls = monitor.parse_api_calls(
            monitor.read_text_capped(log_dir / "agent.log.1")
            + monitor.read_text_capped(log_dir / "agent.log")
        )
        prices = monitor.load_prices(
            HERMES_HOME / "cache" / "openrouter_model_metadata.json"
        )
        worker_used = _dispatch_today(HERMES_HOME / "state" / "vikunja_dispatch.json")
        judge_used = _dispatch_today(
            HERMES_HOME / "state" / "vikunja_judge_dispatch.json"
        )
        depths = {
            "worker": sum(
                1
                for t in queue
                if t.get("classification") in {"worker-ready", "worker:escalate"}
            ),
            "judge": sum(
                1
                for t in queue
                if t.get("classification") in {"judge-ready", "judge:escalate"}
            ),
            "review": 0,
        }
        assembled = tickets + queue + human_only + blocked
        mon = monitor.build_monitor(
            assembled=assembled,
            extra_events=extra_events,
            ticks=ticks,
            calls=calls,
            prices=prices,
            claims=claims,
            depths=depths,
            units=units,
            worker_live=worker_live,
            judge_live=judge_live,
            preflight_missing=preflight_missing,
            preflight_age_s=preflight_age_s,
            worker_used=worker_used,
            worker_cap=int(CFG.caps.get("worker_per_day") or 0),
            judge_used=judge_used,
            judge_cap=int(CFG.caps.get("judge_per_day") or 0),
            truncated=truncated,
            now=_now(),
        )
    tickets.sort(key=lambda t: (-t["priority"], t["id"]))
    human_only.sort(key=lambda t: (-t["priority"], t["id"]))
    blocked.sort(key=lambda t: (-t["priority"], t["id"]))
    queue.sort(key=lambda t: (-t["priority"], t["id"]))
    pending = [t for t in tickets if t["pending"]]
    for w in monitor.WINDOWS:
        mon["metrics"][w]["queue_depth_review"] = len(pending)
    verdicts = [
        t["judge"]["verdict"] for t in tickets if (t.get("judge") or {}).get("verdict")
    ]
    n_approve = sum(1 for v in verdicts if v == "approve")
    n_rem = sum(1 for v in verdicts if v == "remediate")
    n_human = sum(1 for v in verdicts if v == "human")
    n_thin = sum(1 for v in verdicts if v == "thin")
    decided_human = [t for t in tickets if t.get("disposition")]
    agree = 0
    compared = 0
    for t in decided_human:
        kind = (t["disposition"] or {}).get("kind")
        jv = t["judge"]["verdict"]
        if kind in {"approve", "remediate", "human"}:
            compared += 1
            if (
                (kind == "approve" and jv == "approve")
                or (kind == "remediate" and jv == "remediate")
                or (kind == "human" and jv == "human")
            ):
                agree += 1
    hb = _heartbeat()
    return {
        "generated_at": _now().isoformat(timespec="seconds"),
        "date_stamp": _now().strftime("%Y-%m-%d %H:%M Pacific"),
        "heartbeat": hb,
        "vikunja_ui": ui,
        "vocab": {"labels": dict(L), "cron": dict(CFG.cron), "caps": dict(CFG.caps)},
        "tickets": tickets,
        "pending_ids": [t["id"] for t in pending],
        "queue": queue,
        "queue_ids": [t["id"] for t in queue],
        "human_only": human_only,
        "blocked": blocked,
        "activity": mon.get("home_events") or [],
        "metrics": {
            "judge_approve": n_approve,
            "judge_remediate": n_rem,
            "judge_human": n_human,
            "judge_thin": n_thin,
            "open_judged": len(tickets),
            "pending": len(pending),
            "ready": len(queue),
            "blocked": len(blocked),
            "agreement": f"{agree}/{compared}" if compared else "—",
            "first_attempt": "—",
        },
        "monitor": mon,
    }


def stash_undo(task_id: int, kind: str, snapshot: dict) -> str:
    token = secrets.token_urlsafe(16)
    UNDO_TOKENS[token] = {"id": task_id, "kind": kind, "snapshot": snapshot}
    return token


def label_restore_ops(
    current: set[str], wanted: set[str]
) -> tuple[list[str], list[str]]:
    """Titles to add, titles to remove, to make current match wanted."""
    return sorted(wanted - current), sorted(current - wanted)


def _undo_still_valid(
    kind: str, task: dict, attached: set[str], control: dict | None
) -> None:
    if kind in {"approve", "noAction", "discard"}:
        if not task.get("done"):
            raise RuntimeError("task is no longer done — undo is stale")
    elif kind == "human":
        if L["human_only"] not in attached:
            raise RuntimeError("human-only is already gone — undo is stale")
    elif kind == "remediate":
        if L["worker_ready"] not in attached:
            raise RuntimeError("worker:ready is already gone — undo is stale")
    elif kind == "snooze":
        if not hmc.is_snoozed(control):
            raise RuntimeError("snooze is already gone — undo is stale")


def restore_snapshot(
    client: httpx.Client, task_id: int, kind: str, snapshot: dict
) -> None:
    ids = _labels(client)
    t = client.get(f"/tasks/{task_id}")
    t.raise_for_status()
    task = t.json()
    attached = {l.get("title") for l in (task.get("labels") or []) if l.get("title")}
    machine = hmc.list_machine(client, task_id)
    _undo_still_valid(kind, task, attached, machine.get("control"))
    wanted = {x for x in (snapshot.get("labels") or []) if x}
    add, remove = label_restore_ops(attached, wanted)
    for title in add:
        if title in ids:
            _add_label(client, task_id, title, ids)
    for title in remove:
        _remove_label(client, task_id, title, ids, attached)
    body: dict = {}
    if "done" in snapshot:
        body["done"] = bool(snapshot["done"])
    if "percent_done" in snapshot:
        body["percent_done"] = snapshot["percent_done"]
    if body:
        client.post(f"/tasks/{task_id}", json=body).raise_for_status()
    if kind == "snooze" or (snapshot.get("control") or {}).get("not_before"):
        hmc.upsert_control(
            client,
            task_id,
            not_before=(snapshot.get("control") or {}).get("not_before"),
        )
    _comment(
        client, task_id, f"{DISPOSITION_PREFIX} revert — undid last Review disposition"
    )


def apply_undo(token: str) -> dict:
    record = UNDO_TOKENS.get(token)
    if record is None:
        raise RuntimeError("undo is no longer available")
    load_env()
    with _client() as client:
        restore_snapshot(client, record["id"], record["kind"], record["snapshot"])
    UNDO_TOKENS.pop(token, None)
    return {"ok": True, "id": record["id"], "kind": record["kind"]}


def apply_decision(
    task_id: int, kind: str, note: str = "", not_before: str | None = None
) -> dict:
    load_env()
    kind = kind.strip()
    with _client() as client:
        ids = _labels(client)
        t = client.get(f"/tasks/{task_id}")
        t.raise_for_status()
        task = t.json()
        machine = hmc.list_machine(client, task_id)
        snapshot = {
            "done": task.get("done"),
            "percent_done": task.get("percent_done"),
            "labels": [l.get("title") for l in (task.get("labels") or [])],
            "control": machine.get("control") or {},
        }
        attached = {
            l.get("title") for l in (task.get("labels") or []) if l.get("title")
        }
        text = f"{DISPOSITION_PREFIX} {kind}"
        if note:
            text += f" — {note}"
        if kind == "approve":
            _remove_label(client, task_id, L["needs_review"], ids, attached)
            _remove_label(client, task_id, L["in_progress"], ids, attached)
            _remove_label(client, task_id, L["worker_ready"], ids, attached)
            _remove_label(client, task_id, L["worker_escalate"], ids, attached)
            _remove_label(client, task_id, L["judge_ready"], ids, attached)
            _remove_label(client, task_id, L["judge_escalate"], ids, attached)
            client.post(
                f"/tasks/{task_id}",
                json={"done": True, "percent_done": 100},
            ).raise_for_status()
        elif kind == "remediate":
            _comment(client, task_id, text)
            _remove_label(client, task_id, L["judged"], ids, attached)
            _remove_label(client, task_id, L["needs_review"], ids, attached)
            _remove_label(client, task_id, L["judge_ready"], ids, attached)
            _remove_label(client, task_id, L["judge_escalate"], ids, attached)
            _remove_label(client, task_id, L["in_progress"], ids, attached)
            _add_label(client, task_id, L["worker_ready"], ids)
            text = ""  # already commented
        elif kind in {"noAction", "discard"}:
            _remove_label(client, task_id, L["needs_review"], ids, attached)
            _remove_label(client, task_id, L["in_progress"], ids, attached)
            _remove_label(client, task_id, L["worker_ready"], ids, attached)
            _remove_label(client, task_id, L["worker_escalate"], ids, attached)
            _remove_label(client, task_id, L["judge_ready"], ids, attached)
            _remove_label(client, task_id, L["judge_escalate"], ids, attached)
            client.post(
                f"/tasks/{task_id}",
                json={"done": True},
            ).raise_for_status()
        elif kind == "human":
            _add_label(client, task_id, L["human_only"], ids)
            _remove_label(client, task_id, L["worker_ready"], ids, attached)
            _remove_label(client, task_id, L["worker_escalate"], ids, attached)
            _remove_label(client, task_id, L["judge_ready"], ids, attached)
            _remove_label(client, task_id, L["judge_escalate"], ids, attached)
            _remove_label(client, task_id, L["needs_review"], ids, attached)
            _remove_label(client, task_id, L["in_progress"], ids, attached)
        elif kind == "snooze":
            if not not_before:
                raise RuntimeError("snooze requires not_before")
            hmc.upsert_control(client, task_id, not_before=not_before)
        else:
            raise RuntimeError(f"unknown decision {kind!r}")
        if text and kind != "remediate":
            _comment(client, task_id, text)
        token = stash_undo(task_id, kind, snapshot)
        return {"ok": True, "snapshot": snapshot, "kind": kind, "undo": token}


def human_action(task_id: int, action: str, note: str = "") -> dict:
    load_env()
    with _client() as client:
        ids = _labels(client)
        if action == "note":
            if note:
                _comment(client, task_id, note)
        elif action == "done":
            client.post(
                f"/tasks/{task_id}", json={"done": True, "percent_done": 100}
            ).raise_for_status()
        elif action == "reopen":
            client.post(f"/tasks/{task_id}", json={"done": False}).raise_for_status()
        elif action == "hand":
            _remove_label(client, task_id, L["human_only"], ids)
            _add_label(client, task_id, L["worker_ready"], ids)
            _comment(
                client, task_id, "Handed to hermes — pick up on the next heartbeat."
            )
        else:
            raise RuntimeError(f"unknown human action {action!r}")
        return {"ok": True}


def blocked_action(task_id: int, action: str, note: str = "") -> dict:
    load_env()
    with _client() as client:
        ids = _labels(client)
        if action == "note":
            if note:
                _comment(client, task_id, note)
        elif action == "done":
            client.post(
                f"/tasks/{task_id}", json={"done": True, "percent_done": 100}
            ).raise_for_status()
        elif action == "reopen":
            client.post(f"/tasks/{task_id}", json={"done": False}).raise_for_status()
        elif action == "ready":
            t = client.get(f"/tasks/{task_id}")
            t.raise_for_status()
            attached = {
                l.get("title") for l in (t.json().get("labels") or []) if l.get("title")
            }
            _remove_label(client, task_id, L["blocked"], ids, attached)
            _remove_label(client, task_id, L["worker_escalate"], ids, attached)
            if L["worker_ready"] not in attached:
                _add_label(client, task_id, L["worker_ready"], ids)
            _comment(
                client,
                task_id,
                "Unblocked — worker:ready for the next supervisor run.",
            )
        else:
            raise RuntimeError(f"unknown blocked action {action!r}")
        return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj) -> None:
        self._send(
            code, json.dumps(obj).encode("utf-8"), "application/json; charset=utf-8"
        )

    def _read_json(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            return {}
        raw = self.rfile.read(n)
        return json.loads(raw.decode("utf-8") or "{}")

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip()
        if "]" in host:
            name = host.split("]")[0] + "]"
            name = name.strip("[]")
        else:
            name = host.rsplit(":", 1)[0] if host else ""
        return name == HOST

    def _write_ok(self) -> bool:
        got = self.headers.get(TOKEN_HEADER) or ""
        return secrets.compare_digest(got, WRITE_TOKEN)

    def _refuse(self, message: str) -> None:
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n > 0:
            self.rfile.read(n)
        self._json(403, {"error": message})

    def do_HEAD(self) -> None:
        self.do_GET()

    def do_GET(self) -> None:
        if not self._host_ok():
            self._json(403, {"error": "Host header refused"})
            return
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/index.html"}:
            page = (STATIC / "index.html").read_text(encoding="utf-8")
            page = page.replace(INDEX_TOKEN_PLACEHOLDER, WRITE_TOKEN)
            self._send(200, page.encode("utf-8"), "text/html; charset=utf-8")
            return
        if path.startswith("/static/"):
            rel = path[len("/static/") :]
            fp = (STATIC / rel).resolve()
            if STATIC not in fp.parents and fp != STATIC:
                self._json(403, {"error": "forbidden"})
                return
            if not fp.is_file():
                self._json(404, {"error": "missing"})
                return
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".js": "text/javascript; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".svg": "image/svg+xml",
                ".woff2": "font/woff2",
            }.get(fp.suffix, "application/octet-stream")
            self._send(200, fp.read_bytes(), ctype)
            return
        if path == "/api/board":
            try:
                self._json(200, build_board(self.headers.get("Host")))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._host_ok():
            self._refuse("Host header refused")
            return
        if not self._write_ok():
            self._refuse(f"missing or bad {TOKEN_HEADER}")
            return
        parsed = urlparse(self.path)
        path = parsed.path
        try:
            payload = self._read_json()
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"})
            return
        m = re.fullmatch(r"/api/tasks/(\d+)/decide", path)
        if m:
            try:
                result = apply_decision(
                    int(m.group(1)),
                    str(payload.get("kind") or ""),
                    str(payload.get("note") or ""),
                    payload.get("not_before"),
                )
                self._json(200, result)
            except Exception as exc:
                self._json(400, {"error": str(exc)})
            return
        m = re.fullmatch(r"/api/tasks/(\d+)/comment", path)
        if m:
            text = str(payload.get("text") or "").strip()
            if not text:
                self._json(400, {"error": "empty"})
                return
            try:
                load_env()
                tid = int(m.group(1))
                with _client() as client:
                    _comment(client, tid, text)
                    cr = client.get(f"/tasks/{tid}/comments")
                    cr.raise_for_status()
                    chat = _human_comments(cr.json() or [])
                self._json(200, {"ok": True, "chat": chat})
            except Exception as exc:
                self._json(400, {"error": str(exc)})
            return
        m = re.fullmatch(r"/api/tasks/(\d+)/human", path)
        if m:
            try:
                self._json(
                    200,
                    human_action(
                        int(m.group(1)),
                        str(payload.get("action") or ""),
                        str(payload.get("note") or ""),
                    ),
                )
            except Exception as exc:
                self._json(400, {"error": str(exc)})
            return
        m = re.fullmatch(r"/api/tasks/(\d+)/blocked", path)
        if m:
            try:
                self._json(
                    200,
                    blocked_action(
                        int(m.group(1)),
                        str(payload.get("action") or ""),
                        str(payload.get("note") or ""),
                    ),
                )
            except Exception as exc:
                self._json(400, {"error": str(exc)})
            return
        if path == "/api/undo":
            try:
                token = str(payload.get("token") or "")
                self._json(200, apply_undo(token))
            except Exception as exc:
                self._json(400, {"error": str(exc)})
            return
        self._json(404, {"error": "not found"})


def _iter_unreplied_mentions(vik: httpx.Client):
    r = vik.get("/tasks", params={"filter": "done = false", "per_page": 100})
    r.raise_for_status()
    for task in r.json() or []:
        tid = int(task["id"])
        cr = vik.get(f"/tasks/{tid}/comments")
        cr.raise_for_status()
        comments = cr.json() or []
        machine = hmc.list_machine(vik, tid)
        last = int((machine.get("session") or {}).get("last_mention_comment_id") or 0)
        for c in comments:
            cid = int(c.get("id") or 0)
            if cid <= last:
                continue
            author = c.get("author") or {}
            uid = author.get("id")
            uname = (author.get("username") or "").lower()
            if uid == BOT_USER_ID or uname == BOT_USERNAME:
                continue
            text = c.get("comment") or ""
            if any(m in text for m in MACHINE_MARKERS):
                continue
            if mentions_bot(text):
                yield tid, cid, text


def reply_mention(task_id: int, comment_id: int, raw_text: str) -> None:
    user_text = _plain_comment(raw_text)
    if not user_text:
        raise RuntimeError("empty mention text")
    before = discuss_status(task_id)
    before_n = len(before.get("messages") or [])
    result = discuss_send(task_id, user_text)
    if result.get("status") == "busy":
        raise RuntimeError(result.get("notice") or "webui busy")
    deadline = time.time() + MENTION_WAIT_SECONDS
    last = result
    while time.time() < deadline:
        last = discuss_status(task_id)
        status = last.get("status")
        if status == "streaming":
            time.sleep(2)
            continue
        if status == "paused":
            raise RuntimeError(last.get("notice") or "webui paused")
        break
    else:
        raise RuntimeError("mention reply timed out")
    new = (last.get("messages") or [])[before_n:]
    reply = "\n\n".join(
        m["text"] for m in new if m.get("who") == "hermes" and m.get("text")
    ).strip()
    if not reply:
        raise RuntimeError("empty hermes reply")
    load_env()
    with _client() as vik:
        _comment(vik, task_id, reply)
        machine = hmc.list_machine(vik, task_id)
        sid = (machine.get("session") or {}).get("webui_session_id") or ""
        if not sid:
            raise RuntimeError("missing webui_session_id after mention reply")
        hmc.upsert_session(
            vik,
            task_id,
            webui_session_id=sid,
            extra={"last_mention_comment_id": comment_id},
        )


def run_mentions(*, scan_only: bool = False) -> int:
    load_env()
    found: list[tuple[int, int, str]] = []
    with _client() as vik:
        for item in _iter_unreplied_mentions(vik):
            found.append(item)
            if len(found) >= MENTION_CAP:
                break
    if not found:
        print("mention: none")
        return 0
    for tid, cid, text in found:
        print(f"mention: #{tid} comment {cid}")
        if scan_only:
            continue
        try:
            reply_mention(tid, cid, text)
            print(f"mention: #{tid} replied")
        except Exception as exc:
            print(f"mention: #{tid} failed: {exc}", file=sys.stderr)
            return 1
    return 0


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "mention":
        scan_only = "--scan-only" in sys.argv[2:]
        return run_mentions(scan_only=scan_only)
    load_env()
    if not os.environ.get("VIKUNJA_API_TOKEN"):
        print("VIKUNJA_API_TOKEN missing", file=sys.stderr)
        return 1
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"hermes-review http://{HOST}:{PORT}", flush=True)
    httpd.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
