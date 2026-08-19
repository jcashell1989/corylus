"""Pipeline monitor aggregations for Hermes Review Activity/Metrics (td-8f0fa2).

Pure functions. The HTTP process passes in logs, tasks, process flags, and
unit status. This module never reads secrets or returns log text.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TZ = ZoneInfo("America/Los_Angeles")
WINDOWS = ("24h", "7d", "all")
DEFAULT_WINDOW = "7d"
PREFLIGHT_STALE_AFTER = timedelta(minutes=45)
REAPER_PREFIX = "vikunja reaper:"
DISPOSITION_PREFIX = "Hermes Review:"

API_CALL_RE = re.compile(
    r"API call #(?P<n>\d+):\s*"
    r"model=(?P<model>\S+)\s+"
    r"provider=(?P<provider>\S+)\s+"
    r"in=(?P<inn>\d+)\s+"
    r"out=(?P<out>\d+)\s+"
    r"total=(?P<total>\d+)\s+"
    r"latency=(?P<lat>[\d.]+)s"
)
LOG_TS_RE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
PREFLIGHT_RE = re.compile(
    r"^(?P<ts>\S+)\s+eligible=(?P<eligible>\d+)"
    r"(?:\s+judge_eligible=(?P<judge_eligible>\d+))?"
    r"\s+reaped=(?P<reaped>\d+)\s+action=(?P<action>.*)\s*$"
)
UNITS = (
    "hermes-gateway",
    "hermes-dashboard",
    "hermes-webui",
    "vikunja",
    "hermes-review",
)


def now_pacific() -> datetime:
    return datetime.now(TZ)


def parse_ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace(" ", "T", 1))
    except ValueError:
        try:
            dt = datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def first_at(*vals: Any) -> str:
    for v in vals:
        if v is None:
            continue
        text = str(v).strip()
        if text:
            return text
    return ""


def stamp_comment_times(machine: dict[str, Any], comments: list[Any]) -> dict[str, Any]:
    """Copy Vikunja comment created onto attempts/judges missing finished_at."""
    by_id: dict[Any, str] = {}
    for c in comments or []:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if cid is None:
            continue
        by_id[cid] = first_at(c.get("created"), c.get("updated"))
    for bucket in ("attempts", "judges"):
        for row in machine.get(bucket) or []:
            if not isinstance(row, dict):
                continue
            if first_at(row.get("finished_at"), row.get("at")):
                continue
            row["finished_at"] = by_id.get(row.get("_comment_id")) or ""
    return machine


def window_start(window: str, now: datetime) -> datetime | None:
    if window == "24h":
        return now - timedelta(hours=24)
    if window == "7d":
        return now - timedelta(days=7)
    return None


def in_window(ts: datetime | None, window: str, now: datetime) -> bool:
    """Untimed records are included only in window=all."""
    start = window_start(window, now)
    if start is None:
        return True
    if ts is None:
        return False
    return start <= ts <= now


def parse_preflight_log(text: str) -> list[dict[str, Any]]:
    out = []
    for line in (text or "").splitlines():
        m = PREFLIGHT_RE.match(line.strip())
        if not m:
            continue
        ts = parse_ts(m.group("ts"))
        action = (m.group("action") or "").strip()
        lane = "all"
        if "worker" in action and "judge" not in action.split(",")[0]:
            lane = "worker"
        if "judge" in action:
            lane = "judge" if lane == "all" else lane
        if "vikunja-worker-escalate" in action or "worker-escalate" in action:
            lane = "worker-escalate"
        if "vikunja-judge-escalate" in action or "judge-escalate" in action:
            lane = "judge-escalate"
        out.append(
            {
                "at": m.group("ts"),
                "ts": ts,
                "kind": "preflight",
                "eligible": int(m.group("eligible")),
                "judge_eligible": int(m.group("judge_eligible") or 0),
                "reaped": int(m.group("reaped")),
                "action": action,
                "lane": lane,
                "id": None,
                "ref": None,
                "text": action,
                "model": None,
            }
        )
    return out


def parse_api_calls(text: str) -> list[dict[str, Any]]:
    """Only conversation_loop API call lines. Never keep msg= content."""
    out = []
    for line in (text or "").splitlines():
        if "msg=" in line and "API call #" not in line:
            continue
        m = API_CALL_RE.search(line)
        if not m:
            continue
        ts_m = LOG_TS_RE.match(line)
        at = ts_m.group(1) if ts_m else ""
        out.append(
            {
                "at": at,
                "ts": parse_ts(at),
                "kind": "call",
                "n": int(m.group("n")),
                "model": m.group("model"),
                "provider": m.group("provider"),
                "inn": int(m.group("inn")),
                "out": int(m.group("out")),
                "total": int(m.group("total")),
                "latency_s": float(m.group("lat")),
                "id": None,
                "ref": None,
                "lane": lane_for_model(m.group("model")),
                "text": f"{m.group('model')} · {m.group('lat')}s · {m.group('inn')}+{m.group('out')} tok",
            }
        )
    return out


def lane_for_model(model: str) -> str:
    m = (model or "").lower()
    if "luna-pro" in m:
        return "worker-escalate"
    if "luna" in m:
        return "worker"
    if "glm" in m or "claude" in m or "opus" in m:
        return "judge"
    return "all"


def load_prices(path: Path) -> dict[str, dict[str, float]]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    out: dict[str, dict[str, float]] = {}
    if not isinstance(raw, dict):
        return {}
    for key, val in raw.items():
        pricing = (val or {}).get("pricing") if isinstance(val, dict) else None
        if not isinstance(pricing, dict):
            continue
        try:
            out[str(key)] = {
                "prompt": float(pricing.get("prompt") or 0),
                "completion": float(pricing.get("completion") or 0),
            }
        except (TypeError, ValueError):
            continue
    return out


def estimate_spend(
    calls: list[dict[str, Any]], prices: dict[str, dict[str, float]]
) -> dict[str, Any]:
    usd = 0.0
    known = 0
    unknown = 0
    for c in calls:
        p = prices.get(c.get("model") or "")
        if not p:
            unknown += 1
            continue
        usd += c["inn"] * p["prompt"] + c["out"] * p["completion"]
        known += 1
    return {
        "usd": round(usd, 4) if known else None,
        "known": known,
        "unknown": unknown,
        "label": "estimated USD from OpenRouter list prices, not billed",
    }


def median(nums: list[float]) -> float | None:
    if not nums:
        return None
    s = sorted(nums)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


def claim_rows(
    tasks: list[dict[str, Any]],
    in_progress_label: str,
    worker_live: bool,
    judge_live: bool,
) -> list[dict[str, Any]]:
    idle = (not worker_live) and (not judge_live)
    out = []
    for t in tasks:
        labels = set(t.get("labels") or [])
        if in_progress_label not in labels:
            continue
        ident = t.get("identifier") or f"#{t.get('id')}"
        out.append(
            {
                "id": t.get("id"),
                "title": t.get("title") or ident,
                "ref": ident,
                "stranded": idle,
                "status": "stranded" if idle else "claimed",
            }
        )
    return out


def lane_from_labels(labels: list[str] | set[str]) -> str:
    s = set(labels or [])
    if "worker:escalate" in s:
        return "worker-escalate"
    if "judge:escalate" in s:
        return "judge-escalate"
    if "judge:ready" in s or "needs-review" in s or "judged" in s:
        return "judge"
    if "worker:ready" in s or "in-progress" in s:
        return "worker"
    return "all"


def events_from_ticket(t: dict[str, Any]) -> list[dict[str, Any]]:
    tid = t.get("id")
    ident = t.get("identifier") or f"#{tid}"
    lane = lane_from_labels(t.get("labels") or [])
    events: list[dict[str, Any]] = []
    attempt = t.get("attempt") or {}
    if attempt.get("n"):
        at = attempt.get("finished_at") or ""
        summary = " ".join(attempt.get("summary") or [])[:160]
        events.append(
            {
                "at": at,
                "ts": parse_ts(at),
                "kind": "attempt",
                "id": tid,
                "ref": ident,
                "lane": lane,
                "model": None,
                "n": attempt.get("n"),
                "text": f"attempt {attempt.get('n')} · {summary or 'no summary'}",
            }
        )
    for h in t.get("history") or []:
        head = h.get("head") or ""
        at = first_at(h.get("at"), h.get("finished_at"))
        events.append(
            {
                "at": at,
                "ts": parse_ts(at),
                "kind": "attempt",
                "id": tid,
                "ref": ident,
                "lane": lane,
                "model": None,
                "text": head or (h.get("note") or "prior attempt"),
            }
        )
    judges_list = [j for j in (t.get("judges") or []) if j.get("verdict")]
    if judges_list:
        for j in judges_list:
            at = first_at(j.get("finished_at"), j.get("at"), j.get("created"))
            n = j.get("attempt") if j.get("attempt") is not None else j.get("n")
            events.append(
                {
                    "at": at,
                    "ts": parse_ts(at),
                    "kind": "judge",
                    "id": tid,
                    "ref": ident,
                    "lane": "judge",
                    "model": j.get("model"),
                    "verdict": j.get("verdict"),
                    "n": n,
                    "text": f"judge {j.get('verdict')} · {j.get('model') or '—'} · attempt {n}",
                }
            )
    else:
        judge = t.get("judge") or {}
        if judge.get("verdict"):
            at = first_at(
                judge.get("finished_at"), judge.get("at"), judge.get("created")
            )
            events.append(
                {
                    "at": at,
                    "ts": parse_ts(at),
                    "kind": "judge",
                    "id": tid,
                    "ref": ident,
                    "lane": "judge",
                    "model": judge.get("model"),
                    "verdict": judge.get("verdict"),
                    "n": judge.get("attempt") or judge.get("n"),
                    "text": f"judge {judge.get('verdict')} · {judge.get('model') or '—'}",
                }
            )
    disp = t.get("disposition") or {}
    if disp.get("kind"):
        at = first_at(disp.get("at"), disp.get("finished_at"))
        events.append(
            {
                "at": at,
                "ts": parse_ts(at),
                "kind": "disposition",
                "id": tid,
                "ref": ident,
                "lane": lane,
                "model": None,
                "text": f"{DISPOSITION_PREFIX} {disp.get('kind')}",
            }
        )
    for msg in t.get("chat") or []:
        text = (msg.get("text") or "").strip()
        if text.lower().startswith(REAPER_PREFIX):
            events.append(
                {
                    "at": msg.get("at") or "",
                    "ts": parse_ts(msg.get("at")),
                    "kind": "reaper",
                    "id": tid,
                    "ref": ident,
                    "lane": lane,
                    "model": None,
                    "text": text[:180],
                }
            )
    return events


def events_from_machine(
    task: dict[str, Any], machine: dict[str, Any]
) -> list[dict[str, Any]]:
    t = {
        "id": task.get("id"),
        "identifier": f"#{task.get('id')}",
        "title": task.get("title"),
        "labels": [
            l.get("title") if isinstance(l, dict) else l
            for l in (task.get("labels") or [])
        ],
        "attempt": {},
        "history": [],
        "judge": {},
        "judges": machine.get("judges") or [],
        "disposition": None,
        "chat": [],
    }
    attempts = machine.get("attempts") or []
    if attempts:
        latest = attempts[-1]
        t["attempt"] = {
            "n": latest.get("n"),
            "finished_at": latest.get("finished_at") or "",
            "summary": latest.get("summary") or [],
        }
        for a in attempts[:-1]:
            at = first_at(a.get("finished_at"), a.get("at"))
            t["history"].append(
                {
                    "at": at,
                    "finished_at": at,
                    "head": (
                        f"attempt {a.get('n')} · {at} · "
                        f"{' '.join(a.get('summary') or [])}"
                    ),
                }
            )
    return events_from_ticket(t)


def latency_pairs(events: list[dict[str, Any]]) -> list[float]:
    attempts = {}
    for e in events:
        if e.get("kind") == "attempt" and e.get("id") and e.get("n") and e.get("ts"):
            attempts[(e["id"], int(e["n"]))] = e["ts"]
    out = []
    for e in events:
        if (
            e.get("kind") != "judge"
            or not e.get("id")
            or e.get("n") is None
            or not e.get("ts")
        ):
            continue
        start = attempts.get((e["id"], int(e["n"])))
        if start is None:
            continue
        delta = (e["ts"] - start).total_seconds()
        if delta >= 0:
            out.append(delta)
    return out


def metrics_for_window(
    *,
    events: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    ticks: list[dict[str, Any]],
    window: str,
    now: datetime,
    prices: dict[str, dict[str, float]],
    claims: list[dict[str, Any]],
    depths: dict[str, int],
    problems_n: int,
) -> dict[str, Any]:
    ev = [e for e in events if in_window(e.get("ts"), window, now)]
    cl = [c for c in calls if in_window(c.get("ts"), window, now)]
    tk = [t for t in ticks if in_window(t.get("ts"), window, now)]
    attempts = [e for e in ev if e.get("kind") == "attempt"]
    judges = [e for e in ev if e.get("kind") == "judge" and e.get("verdict")]
    outcomes: dict[str, int] = {}
    for j in judges:
        v = j["verdict"]
        outcomes[v] = outcomes.get(v, 0) + 1
    spend = estimate_spend(cl, prices)
    lats = [c["latency_s"] for c in cl if c.get("latency_s") is not None]
    pair_lats = latency_pairs(ev)
    spark = [{"at": t["at"], "eligible": t["eligible"]} for t in tk[-48:]]
    return {
        "window": window,
        "throughput_attempts": len(attempts),
        "throughput_judges": len(judges),
        "queue_depth_worker": depths.get("worker", 0),
        "queue_depth_judge": depths.get("judge", 0),
        "queue_depth_review": depths.get("review", 0),
        "latency_attempt_to_judge_s": median(pair_lats),
        "errors": problems_n,
        "spend": spend,
        "model_calls": len(cl),
        "call_latency_s": median(lats),
        "judge_outcomes": outcomes,
        "stranded": sum(1 for c in claims if c.get("stranded")),
        "claimed": len(claims),
        "preflight_spark": spark,
        "preflight_samples": len(tk),
    }


def problems(
    *,
    units: dict[str, bool | None],
    claims: list[dict[str, Any]],
    preflight_missing: bool,
    preflight_age_s: float | None,
    worker_used: int,
    worker_cap: int,
    judge_used: int,
    judge_cap: int,
    truncated: list[str],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for name, active in units.items():
        if active is False:
            out.append({"kind": "unit down", "text": name, "id": None})
        elif active is None:
            out.append({"kind": "unit status unreadable", "text": name, "id": None})
    if preflight_missing:
        out.append(
            {
                "kind": "preflight missing",
                "text": "vikunja_preflight.log is missing",
                "id": None,
            }
        )
    elif (
        preflight_age_s is not None
        and preflight_age_s > PREFLIGHT_STALE_AFTER.total_seconds()
    ):
        mins = int(preflight_age_s // 60)
        out.append(
            {
                "kind": "preflight stale",
                "text": f"last tick {mins}m ago",
                "id": None,
            }
        )
    for c in claims:
        if c.get("stranded"):
            out.append(
                {
                    "kind": "stranded",
                    "text": f"{c['ref']} in-progress · worker idle",
                    "id": c.get("id"),
                }
            )
    if worker_cap and worker_used >= worker_cap:
        out.append(
            {
                "kind": "dispatch cap",
                "text": f"worker {worker_used}/{worker_cap} today",
                "id": None,
            }
        )
    if judge_cap and judge_used >= judge_cap:
        out.append(
            {
                "kind": "dispatch cap",
                "text": f"judge {judge_used}/{judge_cap} today",
                "id": None,
            }
        )
    for note in truncated:
        out.append({"kind": "truncated read", "text": note, "id": None})
    return out


def ticket_bearing(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [e for e in events if e.get("id")]


def serialize_event(e: dict[str, Any]) -> dict[str, Any]:
    return {
        "at": e.get("at") or "",
        "kind": e.get("kind"),
        "id": e.get("id"),
        "ref": e.get("ref"),
        "lane": e.get("lane") or "all",
        "model": e.get("model"),
        "text": e.get("text") or "",
        "verdict": e.get("verdict"),
    }


def build_monitor(
    *,
    assembled: list[dict[str, Any]],
    extra_events: list[dict[str, Any]],
    ticks: list[dict[str, Any]],
    calls: list[dict[str, Any]],
    prices: dict[str, dict[str, float]],
    claims: list[dict[str, Any]],
    depths: dict[str, int],
    units: dict[str, bool | None],
    worker_live: bool,
    judge_live: bool,
    preflight_missing: bool,
    preflight_age_s: float | None,
    worker_used: int,
    worker_cap: int,
    judge_used: int,
    judge_cap: int,
    truncated: list[str],
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or now_pacific()
    events = []
    for t in assembled:
        events.extend(events_from_ticket(t))
    events.extend(extra_events)
    events.extend(ticks)
    events.sort(key=lambda e: (e.get("ts") is None, e.get("ts") or now), reverse=True)
    calls_sorted = sorted(
        calls,
        key=lambda c: (c.get("ts") is None, c.get("ts") or now),
        reverse=True,
    )
    probs = problems(
        units=units,
        claims=claims,
        preflight_missing=preflight_missing,
        preflight_age_s=preflight_age_s,
        worker_used=worker_used,
        worker_cap=worker_cap,
        judge_used=judge_used,
        judge_cap=judge_cap,
        truncated=truncated,
    )
    unit_bits = []
    for name in UNITS:
        st = units.get(name)
        label = name.replace("hermes-", "")
        if st is True:
            unit_bits.append(f"{label} up")
        elif st is False:
            unit_bits.append(f"{label} down")
        else:
            unit_bits.append(f"{label} ?")
    health = {
        "units": unit_bits,
        "worker": "live" if worker_live else "idle",
        "judge": "live" if judge_live else "idle",
        "worker_cap": f"{worker_used}/{worker_cap}" if worker_cap else str(worker_used),
        "judge_cap": f"{judge_used}/{judge_cap}" if judge_cap else str(judge_used),
        "preflight_age_s": preflight_age_s,
        "generated_at": now.isoformat(timespec="seconds"),
    }
    metrics = {
        w: metrics_for_window(
            events=events,
            calls=calls,
            ticks=ticks,
            window=w,
            now=now,
            prices=prices,
            claims=claims,
            depths=depths,
            problems_n=len(probs),
        )
        for w in WINDOWS
    }
    partial = [
        "open tasks plus a capped recently-done read; older done work is not in this view",
        "spend is estimated from agent.log tokens × list prices, not billed",
        "agent.log is current file plus agent.log.1; older rotations are gone",
    ]
    if truncated:
        partial.extend(truncated)
    if not ticks:
        partial.append("collecting · no preflight samples yet")
    return {
        "health": health,
        "problems": probs,
        "claims": claims,
        "events": [serialize_event(e) for e in events[:400]],
        "calls": [serialize_event(c) for c in calls_sorted[:100]],
        "home_events": [serialize_event(e) for e in ticket_bearing(events)[:40]],
        "metrics": metrics,
        "partial": partial,
        "models": sorted({c["model"] for c in calls if c.get("model")}),
    }


def read_text_capped(path: Path, max_bytes: int = 6_000_000) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


def dispatch_count(path: Path, today: str) -> int:
    if not path.is_file():
        return 0
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if str(raw.get("date") or "") != today:
        return 0
    try:
        return int(raw.get("count") or 0)
    except (TypeError, ValueError):
        return 0
