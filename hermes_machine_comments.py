#!/usr/bin/env python3
"""Hermes machine-comment helper — attempt/judge (append-only) + control/session (upsert).

Markers (preferred):
  <!-- hermes:attempt v1 -->
  <!-- hermes:judge v1 -->
  <!-- hermes:control v1 -->
  <!-- hermes:session v1 -->

Fallback if HTML comments are stripped by Vikunja:
  <<<hermes:attempt v1>>>
  <<<hermes:judge v1>>>
  <<<hermes:control v1>>>
  <<<hermes:session v1>>>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
HTML_ATTEMPT = "<!-- hermes:attempt v1 -->"
HTML_JUDGE = "<!-- hermes:judge v1 -->"
HTML_CONTROL = "<!-- hermes:control v1 -->"
HTML_SESSION = "<!-- hermes:session v1 -->"
HTML_ORGANIZER = "<!-- hermes:organizer v1 -->"
FENCE_ATTEMPT = "<<<hermes:attempt v1>>>"
FENCE_JUDGE = "<<<hermes:judge v1>>>"
FENCE_CONTROL = "<<<hermes:control v1>>>"
FENCE_SESSION = "<<<hermes:session v1>>>"
FENCE_ORGANIZER = "<<<hermes:organizer v1>>>"
ORGANIZER_CONDITIONS = frozenset({"empty_title", "empty_description", "wrong_project"})

VERDICTS = frozenset({"approve", "remediate", "split", "human", "thin"})
# Judge verdicts that earn the worker:escalate retry tier (td-164539).
# approve / split / human go to Julian (needs-review), not another worker.
JUDGE_RETRY_VERDICTS = frozenset({"remediate", "thin"})


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


def _client() -> httpx.Client:
    load_env()
    base = (
        os.environ.get("VIKUNJA_URL", "http://localhost:8788").rstrip("/") + "/api/v1"
    )
    token = os.environ.get("VIKUNJA_API_TOKEN")
    if not token:
        raise SystemExit("VIKUNJA_API_TOKEN missing")
    return httpx.Client(
        base_url=base,
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )


def _now_iso() -> str:
    try:
        return datetime.now(ZoneInfo("America/Los_Angeles")).isoformat(
            timespec="seconds"
        )
    except Exception:
        return datetime.now().astimezone().isoformat(timespec="seconds")


def _extract_blocks(text: str, kind: str) -> list[dict[str, Any]]:
    """Return parsed JSON payloads for attempt|judge|control|session blocks."""
    if kind == "attempt":
        markers = [HTML_ATTEMPT, FENCE_ATTEMPT]
    elif kind == "judge":
        markers = [HTML_JUDGE, FENCE_JUDGE]
    elif kind == "control":
        markers = [HTML_CONTROL, FENCE_CONTROL]
    elif kind == "session":
        markers = [HTML_SESSION, FENCE_SESSION]
    elif kind == "organizer":
        markers = [HTML_ORGANIZER, FENCE_ORGANIZER]
    else:
        raise ValueError(kind)

    out: list[dict[str, Any]] = []
    for marker in markers:
        start = 0
        while True:
            idx = text.find(marker, start)
            if idx < 0:
                break
            after = text[idx + len(marker) :]
            m = re.search(r"\{", after)
            if not m:
                start = idx + len(marker)
                continue
            blob = after[m.start() :]
            try:
                payload, _ = json.JSONDecoder().raw_decode(blob)
            except json.JSONDecodeError:
                start = idx + len(marker)
                continue
            if isinstance(payload, dict):
                out.append(payload)
            start = idx + len(marker)
    return out


def list_machine(client: httpx.Client, task_id: int) -> dict[str, Any]:
    r = client.get(f"/tasks/{task_id}/comments")
    r.raise_for_status()
    attempts: list[dict[str, Any]] = []
    judges: list[dict[str, Any]] = []
    control: dict[str, Any] | None = None
    control_comment_id: int | None = None
    session: dict[str, Any] | None = None
    session_comment_id: int | None = None
    organizer: dict[str, Any] | None = None
    organizer_comment_id: int | None = None
    for comment in r.json() or []:
        text = comment.get("comment") or ""
        cid = comment.get("id")
        for a in _extract_blocks(text, "attempt"):
            a["_comment_id"] = cid
            attempts.append(a)
        for j in _extract_blocks(text, "judge"):
            j["_comment_id"] = cid
            judges.append(j)
        for c in _extract_blocks(text, "control"):
            c["_comment_id"] = cid
            control = c
            control_comment_id = cid
        for s in _extract_blocks(text, "session"):
            s["_comment_id"] = cid
            session = s
            session_comment_id = cid
        for o in _extract_blocks(text, "organizer"):
            o["_comment_id"] = cid
            organizer = o
            organizer_comment_id = cid
    attempts.sort(key=lambda x: int(x.get("n") or 0))
    judges.sort(key=lambda x: int(x.get("attempt") or 0))
    return {
        "attempts": attempts,
        "judges": judges,
        "control": control,
        "control_comment_id": control_comment_id,
        "session": session,
        "session_comment_id": session_comment_id,
        "organizer": organizer,
        "organizer_comment_id": organizer_comment_id,
    }


def _format_block(marker: str, payload: dict[str, Any]) -> str:
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return f"{marker}\n{body}\n"


def _post_comment(client: httpx.Client, task_id: int, comment: str) -> dict[str, Any]:
    r = client.put(f"/tasks/{task_id}/comments", json={"comment": comment})
    r.raise_for_status()
    return r.json() if r.content else {}


def _update_comment(
    client: httpx.Client, task_id: int, comment_id: int, comment: str
) -> dict[str, Any]:
    r = client.post(
        f"/tasks/{task_id}/comments/{comment_id}", json={"comment": comment}
    )
    r.raise_for_status()
    return r.json() if r.content else {}


def next_attempt_n(client: httpx.Client, task_id: int) -> int:
    existing = list_machine(client, task_id)["attempts"]
    if not existing:
        return 1
    return max(int(a.get("n") or 0) for a in existing) + 1


def post_attempt(
    client: httpx.Client,
    task_id: int,
    *,
    summary: list[str],
    git: dict[str, Any] | None = None,
    finished_at: str | None = None,
    use_fence: bool = False,
) -> dict[str, Any]:
    n = next_attempt_n(client, task_id)
    payload: dict[str, Any] = {
        "n": n,
        "finished_at": finished_at or _now_iso(),
        "summary": summary,
    }
    if git:
        payload["git"] = git
    marker = FENCE_ATTEMPT if use_fence else HTML_ATTEMPT
    comment = _format_block(marker, payload)
    posted = _post_comment(client, task_id, comment)
    return {"ok": True, "n": n, "marker": marker, "posted": posted, "payload": payload}


def post_judge(
    client: httpx.Client,
    task_id: int,
    *,
    attempt: int,
    model: str,
    verdict: str,
    confidence: float,
    notes: list[str],
    checks: list[dict[str, Any]] | None = None,
    use_fence: bool = False,
) -> dict[str, Any]:
    if verdict not in VERDICTS:
        raise SystemExit(
            f"invalid verdict {verdict!r}; expected one of {sorted(VERDICTS)}"
        )
    payload: dict[str, Any] = {
        "attempt": attempt,
        "model": model,
        "verdict": verdict,
        "confidence": confidence,
        "notes": notes,
        "checks": checks or [],
    }
    marker = FENCE_JUDGE if use_fence else HTML_JUDGE
    comment = _format_block(marker, payload)
    posted = _post_comment(client, task_id, comment)
    labels = apply_judge_finish_labels(client, task_id, verdict)
    return {
        "ok": True,
        "attempt": attempt,
        "marker": marker,
        "posted": posted,
        "payload": payload,
        "labels": labels,
    }


def judge_finish_label_plan(verdict: str) -> tuple[set[str], set[str]]:
    """Return (add_keys, remove_keys) using vikunja.yaml label keys.

    Always stamp judged and drop judge lanes. remediate/thin earn
    worker:escalate and must not keep needs-review (preflight will not
    dispatch a worker while that label is present). Other verdicts go
    to Julian via needs-review.
    """
    if verdict not in VERDICTS:
        raise ValueError(f"invalid verdict {verdict!r}")
    add = {"judged"}
    remove = {"judge_ready", "judge_escalate"}
    if verdict in JUDGE_RETRY_VERDICTS:
        add.add("worker_escalate")
        remove.update({"worker_ready", "needs_review"})
    else:
        add.add("needs_review")
    return add, remove


def apply_judge_finish_labels(
    client: httpx.Client,
    task_id: int,
    verdict: str,
    titles: dict[str, str] | None = None,
) -> dict[str, list[str]]:
    """Idempotently apply post-judge labels. Does not trust the LLM."""
    if titles is None:
        from vikunja_config import load

        titles = load().labels
    add_keys, remove_keys = judge_finish_label_plan(verdict)
    labels_resp = client.get("/labels")
    labels_resp.raise_for_status()
    ids = {lb.get("title"): lb.get("id") for lb in labels_resp.json() or []}
    task_resp = client.get(f"/tasks/{task_id}")
    task_resp.raise_for_status()
    attached = {x.get("title") for x in (task_resp.json().get("labels") or [])}
    added: list[str] = []
    removed: list[str] = []
    for key in sorted(remove_keys):
        title = titles[key]
        lid = ids.get(title)
        if not lid or title not in attached:
            continue
        resp = client.delete(f"/tasks/{task_id}/labels/{lid}")
        code = getattr(resp, "status_code", 200)
        if code not in {200, 204, 403, 404}:
            resp.raise_for_status()
        removed.append(title)
        attached.discard(title)
    for key in sorted(add_keys):
        title = titles[key]
        lid = ids.get(title)
        if lid is None:
            raise RuntimeError(f"Vikunja label vocabulary lacks {title!r}")
        if title in attached:
            continue
        client.put(
            f"/tasks/{task_id}/labels", json={"label_id": lid}
        ).raise_for_status()
        added.append(title)
        attached.add(title)
    return {"added": added, "removed": removed}


def parse_not_before(control: dict[str, Any] | None) -> datetime | None:
    if not control:
        return None
    raw = control.get("not_before")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("America/Los_Angeles"))
    return dt


def is_snoozed(control: dict[str, Any] | None, now: datetime | None = None) -> bool:
    until = parse_not_before(control)
    if until is None:
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return until > now.astimezone(until.tzinfo)


def upsert_control(
    client: httpx.Client,
    task_id: int,
    *,
    not_before: str | None,
    use_fence: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if not_before:
        payload["not_before"] = not_before
    marker = FENCE_CONTROL if use_fence else HTML_CONTROL
    comment = _format_block(marker, payload)
    existing = list_machine(client, task_id)
    cid = existing.get("control_comment_id")
    if cid:
        posted = _update_comment(client, task_id, int(cid), comment)
        action = "updated"
    else:
        posted = _post_comment(client, task_id, comment)
        action = "created"
    return {
        "ok": True,
        "action": action,
        "marker": marker,
        "posted": posted,
        "payload": payload,
    }


def upsert_session(
    client: httpx.Client,
    task_id: int,
    *,
    webui_session_id: str,
    extra: dict[str, Any] | None = None,
    use_fence: bool = False,
) -> dict[str, Any]:
    existing = list_machine(client, task_id)
    payload: dict[str, Any] = dict(existing.get("session") or {})
    payload.pop("_comment_id", None)
    payload["webui_session_id"] = webui_session_id
    if extra:
        payload.update(extra)
    marker = FENCE_SESSION if use_fence else HTML_SESSION
    comment = _format_block(marker, payload)
    cid = existing.get("session_comment_id")
    if cid:
        posted = _update_comment(client, task_id, int(cid), comment)
        action = "updated"
    else:
        posted = _post_comment(client, task_id, comment)
        action = "created"
    return {
        "ok": True,
        "action": action,
        "marker": marker,
        "posted": posted,
        "payload": payload,
    }


def _task_fingerprint(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": (task.get("title") or "").strip(),
        "description": (task.get("description") or "").strip(),
        "project_id": task.get("project_id"),
    }


def upsert_organizer(
    client: httpx.Client,
    task_id: int,
    *,
    conditions: list[str],
    use_fence: bool = False,
) -> dict[str, Any]:
    cleaned = []
    for raw in conditions:
        c = str(raw).strip()
        if c not in ORGANIZER_CONDITIONS:
            raise ValueError(f"unknown organizer condition {c!r}")
        if c not in cleaned:
            cleaned.append(c)
    if not cleaned:
        raise ValueError("post-organizer requires at least one --condition")
    task_r = client.get(f"/tasks/{task_id}")
    task_r.raise_for_status()
    fp = _task_fingerprint(task_r.json() or {})
    existing = list_machine(client, task_id)
    prev = dict(existing.get("organizer") or {})
    prev.pop("_comment_id", None)
    if prev.get("fp") == fp:
        merged = list(prev.get("conditions") or [])
        for c in cleaned:
            if c not in merged:
                merged.append(c)
        cleaned = merged
    payload = {"conditions": cleaned, "fp": fp, "at": _now_iso()}
    marker = FENCE_ORGANIZER if use_fence else HTML_ORGANIZER
    comment = _format_block(marker, payload)
    cid = existing.get("organizer_comment_id")
    if cid:
        posted = _update_comment(client, task_id, int(cid), comment)
        action = "updated"
    else:
        posted = _post_comment(client, task_id, comment)
        action = "created"
    return {
        "ok": True,
        "action": action,
        "marker": marker,
        "posted": posted,
        "payload": payload,
    }


def cmd_post_organizer(args: argparse.Namespace) -> int:
    with _client() as client:
        result = upsert_organizer(
            client,
            args.task_id,
            conditions=list(args.condition or []),
            use_fence=args.fence,
        )
    print(json.dumps({k: result[k] for k in ("ok", "action", "payload")}, indent=2))
    return 0


def git_range(repo: str, base: str, tip: str) -> dict[str, Any]:
    path = Path(repo)
    if not path.is_dir():
        return {"ok": False, "error": f"repo missing: {repo}"}
    log = subprocess.run(
        ["git", "log", "--oneline", f"{base}..{tip}"],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    diff_stat = subprocess.run(
        ["git", "diff", "--stat", f"{base}..{tip}"],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    diff = subprocess.run(
        ["git", "diff", f"{base}..{tip}"],
        cwd=path,
        text=True,
        capture_output=True,
        check=False,
    )
    diff_text = diff.stdout or ""
    if len(diff_text) > 200_000:
        diff_text = diff_text[:200_000] + "\n… truncated …\n"
    return {
        "ok": log.returncode == 0
        and diff_stat.returncode == 0
        and diff.returncode == 0,
        "repo": repo,
        "base": base,
        "tip": tip,
        "log": log.stdout,
        "diff_stat": diff_stat.stdout,
        "diff": diff_text,
        "stderr": (log.stderr or "") + (diff_stat.stderr or "") + (diff.stderr or ""),
    }


def cmd_list(args: argparse.Namespace) -> int:
    with _client() as client:
        data = list_machine(client, args.task_id)
    for a in data["attempts"]:
        a.pop("_comment_id", None)
    for j in data["judges"]:
        j.pop("_comment_id", None)
    if data.get("control"):
        data["control"].pop("_comment_id", None)
    data.pop("control_comment_id", None)
    if data.get("session"):
        data["session"].pop("_comment_id", None)
    data.pop("session_comment_id", None)
    if data.get("organizer"):
        data["organizer"].pop("_comment_id", None)
    data.pop("organizer_comment_id", None)
    print(json.dumps(data, indent=2))
    return 0


def cmd_post_attempt(args: argparse.Namespace) -> int:
    git = None
    if args.repo:
        git = {
            "repo": args.repo,
            "branch": args.branch or "",
            "base": args.base or "",
            "tip": args.tip or "",
            "commits": args.commits or [],
        }
    with _client() as client:
        result = post_attempt(
            client,
            args.task_id,
            summary=args.summary or [],
            git=git,
            use_fence=args.fence,
        )
    print(json.dumps(result, indent=2))
    return 0


def cmd_post_judge(args: argparse.Namespace) -> int:
    checks = []
    if args.check:
        for raw in args.check:
            parts = raw.split("|", 2)
            label = parts[0]
            passed = (
                parts[1].lower() in {"1", "true", "pass", "yes"}
                if len(parts) > 1
                else False
            )
            note = parts[2] if len(parts) > 2 else ""
            checks.append({"label": label, "pass": passed, "note": note})
    with _client() as client:
        result = post_judge(
            client,
            args.task_id,
            attempt=args.attempt,
            model=args.model,
            verdict=args.verdict,
            confidence=args.confidence,
            notes=args.note or [],
            checks=checks,
            use_fence=args.fence,
        )
    print(json.dumps(result, indent=2))
    return 0


def cmd_git_range(args: argparse.Namespace) -> int:
    print(json.dumps(git_range(args.repo, args.base, args.tip), indent=2))
    return 0


def cmd_post_control(args: argparse.Namespace) -> int:
    with _client() as client:
        result = upsert_control(
            client,
            args.task_id,
            not_before=args.not_before,
            use_fence=args.fence,
        )
    print(json.dumps(result, indent=2))
    return 0


def cmd_post_session(args: argparse.Namespace) -> int:
    with _client() as client:
        result = upsert_session(
            client,
            args.task_id,
            webui_session_id=args.webui_session_id,
            use_fence=args.fence,
        )
    print(json.dumps(result, indent=2))
    return 0


def cmd_roundtrip(args: argparse.Namespace) -> int:
    """Write attempt marker, read back, report whether HTML survived."""
    with _client() as client:
        posted = post_attempt(
            client,
            args.task_id,
            summary=["phase3-roundtrip-probe"],
            use_fence=False,
        )
        n = posted["n"]
        data = list_machine(client, args.task_id)
        found = [a for a in data["attempts"] if int(a.get("n") or 0) == n]
        mode = "html" if found else None
        if not found:
            posted = post_attempt(
                client,
                args.task_id,
                summary=["phase3-roundtrip-probe-fence"],
                use_fence=True,
            )
            n = posted["n"]
            data = list_machine(client, args.task_id)
            found = [a for a in data["attempts"] if int(a.get("n") or 0) == n]
            mode = "fence" if found else None
        first_n = (
            min(int(a.get("n") or 0) for a in data["attempts"])
            if data["attempts"]
            else n
        )
        post_attempt(
            client,
            args.task_id,
            summary=["phase3-prior-attempt-probe"],
            use_fence=(mode == "fence"),
        )
        data2 = list_machine(client, args.task_id)
        ns = {int(a.get("n") or 0) for a in data2["attempts"]}
        history_ok = first_n in ns and max(ns) > first_n
        out = {
            "ok": bool(found) and history_ok,
            "marker_mode": mode or "FAILED",
            "html_survived": mode == "html",
            "history_ok": history_ok,
            "attempt_ns": sorted(ns),
        }
        print(json.dumps(out, indent=2))
        return 0 if out["ok"] else 1


def main() -> int:
    p = argparse.ArgumentParser(description="Hermes Vikunja machine-comment helper")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="List parsed attempt/judge machine comments")
    sp.add_argument("task_id", type=int)

    sp = sub.add_parser("post-attempt", help="Append hermes:attempt comment")
    sp.add_argument("task_id", type=int)
    sp.add_argument("--summary", action="append", default=[])
    sp.add_argument("--repo")
    sp.add_argument("--branch")
    sp.add_argument("--base")
    sp.add_argument("--tip")
    sp.add_argument("--commits", action="append", default=[])
    sp.add_argument(
        "--fence", action="store_true", help="Use fenced marker instead of HTML"
    )

    sp = sub.add_parser("post-judge", help="Append hermes:judge comment")
    sp.add_argument("task_id", type=int)
    sp.add_argument("--attempt", type=int, required=True)
    sp.add_argument("--model", required=True)
    sp.add_argument("--verdict", required=True)
    sp.add_argument("--confidence", type=float, default=0.5)
    sp.add_argument("--note", action="append", default=[])
    sp.add_argument("--check", action="append", default=[], help="label|pass|note")
    sp.add_argument("--fence", action="store_true")

    sp = sub.add_parser("git-range", help="Show git log/diff-stat for base..tip")
    sp.add_argument("repo")
    sp.add_argument("base")
    sp.add_argument("tip")

    sp = sub.add_parser(
        "post-control", help="Upsert hermes:control (snooze / not_before)"
    )
    sp.add_argument("task_id", type=int)
    sp.add_argument("--not-before", dest="not_before", required=True)
    sp.add_argument("--fence", action="store_true")

    sp = sub.add_parser("post-session", help="Upsert hermes:session (webui session id)")
    sp.add_argument("task_id", type=int)
    sp.add_argument("--webui-session-id", dest="webui_session_id", required=True)
    sp.add_argument("--fence", action="store_true")

    sp = sub.add_parser(
        "post-organizer",
        help="Upsert hermes:organizer ping skip marker",
    )
    sp.add_argument("task_id", type=int)
    sp.add_argument(
        "--condition",
        action="append",
        default=[],
        help="empty_title | empty_description | wrong_project (repeatable)",
    )
    sp.add_argument("--fence", action="store_true")

    sp = sub.add_parser(
        "roundtrip", help="Smoke: write→read marker + prior-attempt history"
    )
    sp.add_argument("task_id", type=int)

    args = p.parse_args()
    if args.cmd == "list":
        return cmd_list(args)
    if args.cmd == "post-attempt":
        return cmd_post_attempt(args)
    if args.cmd == "post-judge":
        return cmd_post_judge(args)
    if args.cmd == "git-range":
        return cmd_git_range(args)
    if args.cmd == "post-control":
        return cmd_post_control(args)
    if args.cmd == "post-session":
        return cmd_post_session(args)
    if args.cmd == "post-organizer":
        return cmd_post_organizer(args)
    if args.cmd == "roundtrip":
        return cmd_roundtrip(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
