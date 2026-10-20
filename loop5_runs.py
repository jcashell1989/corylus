"""Read-only, allowlisted loop5 observations; source text never crosses the API boundary.

A run is an explicit start event, not a ticket or an inferred attempt. Terminal
messages without starts are retained with unknown start time. Current ticket
metadata supplies current points only; it never retroactively supplies a model.
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import stat
import threading
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

TICKET = r"td-[a-f0-9]{4,16}"
IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\Z")
MODEL = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,39}(?:/[a-zA-Z0-9][a-zA-Z0-9_.-]{0,39})?\Z")
SECRET = re.compile(
    r"(?:sk-|gh[pousr]_|github_pat_|xox[baprs]-|AKIA|Bearer|password|token|secret|api.?key)", re.I
)
STAMP = re.compile(r"^(\S+)\s+(.*)$")
ONEOFF = re.compile(rf"^({TICKET}) ([A-Za-z0-9_.-]+) (start|FINISHED|FAILED)(?:\s|$)")
ROUND_START = re.compile(
    rf"^({TICKET}) round (\d+): (?:review-only )?(implementer start|implementer done; reviewer start|reviewer start)"
)
ROUND_VERDICT = re.compile(
    rf"^({TICKET}) round (\d+): (?:review-only )?VERDICT: (APPROVE|REJECT|NEEDS-DECISION)(?:\s|$)"
)
MAX_FILE = 8 * 1024 * 1024
MAX_STATUS = 32 * 1024 * 1024
STALE_AFTER_SECONDS = 3600


def _identifier(value: object, *, model: bool = False) -> str:
    if not isinstance(value, str) or SECRET.search(value):
        return "unknown"
    if re.search(r"[A-Za-z0-9]{28,}", value):
        return "unknown"
    return value if (MODEL if model else IDENT).fullmatch(value) else "unknown"


def _time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.astimezone(UTC) if result.tzinfo else None
    except (ValueError, OverflowError):
        return None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _points(value: object) -> float | int | None:
    if value is None or isinstance(value, bool) or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result) or result < 0:
        return None
    return int(result) if result.is_integer() else result


class _Reader:
    """Open each path component relative to an already-open root without symlinks."""

    def __init__(self, directory: Path, warnings: set[str]):
        self.fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        self.warnings = warnings

    def close(self) -> None:
        os.close(self.fd)

    def read(self, relative: str, limit: int = MAX_FILE) -> tuple[str, datetime | None]:
        parts = relative.split("/")
        if any(p in ("", ".", "..") for p in parts):
            return "", None
        opened = []
        try:
            parent = self.fd
            for component in parts[:-1]:
                parent = os.open(
                    component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent
                )
                opened.append(parent)
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
            opened.append(fd)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                return "", None
            if info.st_size > limit:
                name = parts[-1]
                safe_name = (
                    name
                    if name in ("status.txt", "state.json")
                    or (
                        re.fullmatch(rf"{TICKET}\.[A-Za-z0-9_.-]+\.(?:log|out|md)", name)
                        and _identifier(
                            name.removesuffix(".log")
                            .removesuffix(".out")
                            .removesuffix(".md")
                            .split(".", 1)[1]
                        )
                        != "unknown"
                    )
                    else "source"
                )
                impact = (
                    "event history is unavailable"
                    if relative == "status.txt"
                    else "only its beginning and end are read; middle observations may be missing"
                )
                self.warnings.add(f"{safe_name} exceeds the read limit; {impact}.")
                if relative == "status.txt":
                    return "", None
                # Both ends retain provider metadata and terminal errors, without unbounded reads.
                head = os.read(fd, limit // 2)
                os.lseek(fd, -limit // 2, os.SEEK_END)
                raw = head + b"\n" + os.read(fd, limit // 2)
            else:
                raw = os.read(fd, limit + 1)
            return raw.decode("utf-8", errors="replace"), datetime.fromtimestamp(info.st_mtime, UTC)
        except OSError:
            return "", None
        finally:
            for fd in reversed(opened):
                os.close(fd)

    def names(self, relative: str = "") -> list[str]:
        fd = None
        try:
            fd = (
                os.open(relative, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                if relative
                else os.dup(self.fd)
            )
            names = sorted(os.listdir(fd))
            if len(names) > 20000:
                self.warnings.add("Too many source files; observations may be incomplete.")
            return names[:20000]
        except OSError:
            return []
        finally:
            if fd is not None:
                os.close(fd)

    def latest_activity(self, relative: str, depth: int = 2) -> datetime | None:
        """Read only file metadata in the known session directory, never transcripts."""
        opened = []
        try:
            parent = self.fd
            for part in relative.split("/"):
                if not IDENT.fullmatch(part):
                    return None
                parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                opened.append(parent)

            def scan(fd: int, remaining: int) -> float:
                latest = 0.0
                names = os.listdir(fd)
                if len(names) > 1000:
                    self.warnings.add(
                        "A session has too many entries; activity observations may be incomplete."
                    )
                for name in names[:1000]:
                    try:
                        info = os.stat(name, dir_fd=fd, follow_symlinks=False)
                        if stat.S_ISREG(info.st_mode):
                            latest = max(latest, info.st_mtime)
                        elif remaining and stat.S_ISDIR(info.st_mode):
                            child = os.open(
                                name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd
                            )
                            try:
                                latest = max(latest, scan(child, remaining - 1))
                            finally:
                                os.close(child)
                    except OSError:
                        continue
                return latest

            timestamp = scan(parent, depth)
            return datetime.fromtimestamp(timestamp, UTC) if timestamp else None
        except OSError:
            return None
        finally:
            for fd in reversed(opened):
                os.close(fd)


class RunsStore:
    def __init__(
        self, directory: str | Path | None, points_provider: Callable[[], dict] | None = None
    ):
        self.directory = Path(directory) if directory else None
        self.points_provider = points_provider
        self._cache: dict | None = None
        self._cached_at = 0.0
        self._lock = threading.Lock()

    def get(self) -> dict:
        # Concurrent browser tabs share a bounded read rather than scanning logs in parallel.
        with self._lock:
            if self._cache is None or time.monotonic() - self._cached_at >= 5:
                self._cache = self._get()
                self._cached_at = time.monotonic()
            return self._cache

    def _get(self) -> dict:
        now = datetime.now(UTC)
        snapshot = {
            "available": False,
            "message": "Loop5 state directory is not configured.",
            "refreshed_at": _iso(now),
            "runs": [],
            "lanes": [],
            "queue": [],
            "warnings": [],
            "cost": "not reported",
            "points_note": "Uses the ticket's current points; points may change after a run.",
            "stale_after_seconds": STALE_AFTER_SECONDS,
            "freshness_note": "Running observations without activity for one hour are stale; their outcome is unknown.",
        }
        if self.directory is None:
            return snapshot
        warnings: set[str] = set()
        try:
            reader = _Reader(self.directory, warnings)
        except OSError:
            snapshot["message"] = "Loop5 state directory is missing or unreadable."
            return snapshot
        try:
            return self._snapshot(reader, snapshot, now, warnings)
        finally:
            reader.close()

    def _snapshot(self, reader: _Reader, snapshot: dict, now: datetime, warnings: set[str]) -> dict:
        status_text, status_mtime = reader.read("status.txt", MAX_STATUS)
        state_text, _ = reader.read("state.json")
        if not status_text:
            warnings.add(
                "Loop5 event history is missing, empty, unreadable, or oversized; run counts are unavailable."
            )
        if not state_text:
            warnings.add(
                "Loop5 state is missing, empty, or unreadable; queue and fallback points are unavailable."
            )
        if not status_text and not state_text:
            snapshot["message"] = (
                "Loop5 status and state files are missing, unreadable, or exceed the read limit."
            )
            snapshot["warnings"] = sorted(warnings)
            return snapshot
        try:
            state = json.loads(state_text) if state_text else {}
        except (ValueError, TypeError):
            state = {}
            warnings.add("Loop5 state JSON is invalid; queue and fallback points are unavailable.")
        if not isinstance(state, dict):
            state = {}
        tickets = state.get("tickets", []) if state.get("schema_version") == 2 else []
        if state and state.get("schema_version") != 2:
            warnings.add("Unsupported state schema; queue and fallback points are unavailable.")
        if not isinstance(tickets, list):
            tickets = []
        current = {
            t["id"]: t
            for t in tickets
            if isinstance(t, dict) and re.fullmatch(TICKET, str(t.get("id", "")))
        }
        td_points: dict = {}
        if self.points_provider:
            try:
                result = self.points_provider()
                if isinstance(result, dict):
                    td_points = result
                    if result.get("_incomplete"):
                        warnings.add(
                            "Some current td points are unavailable; state points are used where recorded."
                        )
            except Exception:  # noqa: BLE001 - a failed optional td provider must not break the viewer
                warnings.add(
                    "Current td points are unavailable; state points are used where recorded."
                )

        def ticket_points(ticket: str) -> tuple[float | int | None, str]:
            value = _points(td_points.get(ticket))
            if value is not None:
                return value, "td"
            value = _points(current.get(ticket, {}).get("points"))
            return value, "state" if value is not None else "unpointed"

        events = []
        for number, line in enumerate(status_text.splitlines(), 1):
            match = STAMP.match(line.split("\t", 1)[0])
            if match and (at := _time(match[1])):
                events.append((at, number, match[2]))
        runs: list[dict] = []
        pending: dict[tuple[str, str], dict] = {}
        lane_events: dict[str, list] = defaultdict(list)
        round_builds: dict[tuple[str, str], dict] = {}
        unsupported_events = False

        def create(
            ticket: str,
            label: str,
            at: datetime | None,
            number: int,
            kind="unknown",
            source="oneoff",
        ) -> dict:
            points, point_source = ticket_points(ticket)
            run = {
                "id": f"event-{number}-{len(runs)}",
                "ticket": ticket,
                "label": _identifier(label),
                "kind": kind,
                "model": "unknown",
                "builder_model": "unknown",
                "start_time": _iso(at),
                "end_time": None,
                "last_activity": _iso(at),
                "state": "running" if at else "unknown",
                "next_retry": None,
                "verdict": None,
                "points": points,
                "points_source": point_source,
                "lane": None,
                "duration_seconds": None,
                "source": source,
                "event_line": number,
            }
            runs.append(run)
            pending[(ticket, label)] = run
            return run

        def finish(run: dict, at: datetime, outcome: str) -> None:
            run.update(state=outcome, end_time=_iso(at), last_activity=_iso(at))
            start = _time(run["start_time"])
            if start and at >= start:
                run["duration_seconds"] = (at - start).total_seconds()

        for at, number, message in events:
            serial = re.match(r"^serial(?: (lane\d+))? (.*)$", message)
            if serial:
                lane = serial[1] or "serial"
                lane_events[lane].append((at, number, serial[2]))
                job = re.match(rf"^({TICKET}) ([A-Za-z0-9_.-]+) (.*)$", serial[2])
                if job:
                    ticket, label, detail = job.groups()
                    run = pending.get((ticket, label))
                    if "skipped:" in detail:
                        run = create(ticket, label, None, number, "judge", "serial")
                        finish(run, at, "skipped")
                    if run:
                        run["lane"] = lane
                        if "hit gateway budget" in detail:
                            finish(run, at, "waiting_budget")
                            wait = re.search(r"waiting (\d+)m before retry", detail)
                            if wait:
                                run["next_retry"] = _iso(at + timedelta(minutes=int(wait[1])))
                        elif "FAILED" in detail or detail.startswith("failed"):
                            finish(run, at, "failed")
                continue
            if match := ROUND_START.match(message):
                ticket, round_number, action = match.groups()
                if "implementer done" in action:
                    build = pending.get((ticket, f"impl.r{round_number}"))
                    if build:
                        finish(build, at, "finished")
                    run = create(ticket, f"review.r{round_number}", at, number, "judge", "queue")
                    if build:
                        run["builder_run_id"] = build["id"]
                elif action == "implementer start":
                    run = create(ticket, f"impl.r{round_number}", at, number, "build", "queue")
                    round_builds[(ticket, round_number)] = run
                else:
                    run = create(ticket, f"review.r{round_number}", at, number, "judge", "queue")
                run["round"] = int(round_number)
                continue
            if match := ROUND_VERDICT.match(message):
                ticket, round_number, verdict = match.groups()
                run = pending.get((ticket, f"review.r{round_number}"))
                if run:
                    run["verdict"] = verdict if verdict in ("APPROVE", "REJECT") else None
                    finish(run, at, "finished" if run["verdict"] else "unknown")
                continue
            if match := ONEOFF.match(message):
                ticket, label, outcome = match.groups()
                if outcome == "start":
                    # Starts, including repeated labels, remain separate recorded attempts.
                    run = create(ticket, label, at, number)
                else:
                    run = pending.get((ticket, label)) or create(ticket, label, None, number)
                    exit_match = re.search(r"\(exit (\d+)", message)
                    outcome = "finished" if outcome == "FINISHED" else "failed"
                    if exit_match and int(exit_match[1]) != 0:
                        outcome = "failed"
                    finish(run, at, outcome)
                continue
            if match := re.match(rf"^({TICKET}) DIED: ([A-Za-z0-9_.-]+) FINISHED(?:\s|$)", message):
                ticket, label = match.groups()
                run = pending.get((ticket, label)) or create(ticket, label, None, number)
                finish(run, at, "failed")
                continue
            if match := re.match(rf"^({TICKET}) (DIED:|NEEDS-DECISION(?:[: ]|$))", message):
                ticket = match[1]
                for (run_ticket, _), run in pending.items():
                    if (
                        run_ticket == ticket
                        and run["source"] == "queue"
                        and run["state"] == "running"
                    ):
                        finish(
                            run,
                            at,
                            "failed" if message.startswith(ticket + " DIED:") else "unknown",
                        )
            elif re.search(r"\bstart(?:$| \()|\b(?:FINISHED|FAILED) \(exit \d+\)", message):
                unsupported_events = True

        if unsupported_events:
            warnings.add(
                "Some older event formats cannot be classified; only recognized recorded runs are counted."
            )

        # Files are consulted only for explicit facts (provider model/error/verdict), never returned.
        file_cache: dict[str, tuple[str, datetime | None]] = {}

        def read(relative: str) -> tuple[str, datetime | None]:
            if relative not in file_cache:
                file_cache[relative] = reader.read(relative)
            return file_cache[relative]

        def fresh(run: dict, mtime: datetime | None) -> bool:
            start = _time(run["start_time"])
            # roles can be written just before the timestamped start event.
            return bool(mtime and (not start or mtime >= start - timedelta(seconds=2)))

        latest = {(r["ticket"], r["label"]): r for r in runs}
        latest_queue = {r["ticket"]: r for r in runs if r["source"] == "queue"}
        for run in runs:
            ticket, label = run["ticket"], run["label"]
            if label == "unknown":
                continue
            # Reused label files contain the latest attempt only. Do not attribute their
            # model, errors, or verdict backwards to older attempts with that label.
            if latest[(ticket, label)] is not run:
                warnings.add("Repeated job labels have only their latest file evidence attributed.")
                continue
            log_files = [
                f"{ticket}.{label}.out.log",
                f"{ticket}.{label}.log",
                f"{ticket}.{label}.md.log",
            ]
            roles_path = (
                f"sessions/{ticket}/roles.yml"
                if run["source"] == "queue" and run["kind"] == "build"
                else f"sessions/omp-{ticket}-{label}/roles.yml"
            )
            roles, roles_mtime = read(roles_path)
            role = re.search(r"(?m)^\s{1,8}default:\s*([^\s#]+)", roles)
            end = _time(run["end_time"])
            role_in_attempt = (
                run["source"] != "queue"
                or bool(roles_mtime and end and roles_mtime <= end + timedelta(seconds=2))
                or (not end and latest_queue.get(ticket) is run)
            )
            if role and fresh(run, roles_mtime) and role_in_attempt:
                run["model"] = _identifier(role[1], model=True)
            verdict_texts = []
            diagnostic_texts = []
            activity = _time(run["last_activity"])
            for filename in log_files:
                text, mtime = read(filename)
                if text and fresh(run, mtime):
                    diagnostic_texts.append("\n".join(text.rstrip().splitlines()[-3:]))
                    if mtime and (not activity or mtime > activity):
                        activity = min(mtime, now)
                    cli = re.search(r"(?m)^OpenAI Codex [^\n]*\n", text[:1024])
                    if cli:
                        header = re.split(
                            r"(?m)^user(?::|$)", text[cli.start() : 8000], maxsplit=1
                        )[0]
                        model = re.search(r"(?m)^model:\s*([a-zA-Z0-9_./-]+)\s*$", header)
                        if model:
                            run["model"] = _identifier(model[1], model=True)
            for filename in [f"{ticket}.{label}.out", f"{ticket}.{label}.md"]:
                text, mtime = read(filename)
                if text and fresh(run, mtime):
                    verdict_texts.append(text)
                    if mtime and (not activity or mtime > activity):
                        activity = min(mtime, now)
            # Provider diagnostics must be terminal error records, not quoted prompt text.
            diagnostics = "\n".join(diagnostic_texts)
            budget = bool(
                re.search(
                    r"(?m)^(?:(?:[A-Za-z_][A-Za-z0-9_.]*\.)?ExceededBudget(?::|$)|(?:Error: )?Budget has been exceeded(?:[!.]|$)|Error: ExceededBudget(?:[: ]|$))",
                    diagnostics,
                )
            )
            deadline = bool(re.search(r"(?mi)^(?:Error: )?Deadline exceeded[.!]?\s*$", diagnostics))
            if run["state"] in ("failed", "unknown", "running"):
                if budget:
                    run["state"] = "waiting_budget"
                elif deadline:
                    run["state"] = "timed_out"
            if run["state"] == "running":
                session_path = (
                    f"sessions/{ticket}"
                    if run["source"] == "queue"
                    else f"sessions/omp-{ticket}-{label}"
                )
                session_activity = (
                    reader.latest_activity(session_path)
                    if run["source"] != "queue" or latest_queue.get(ticket) is run
                    else None
                )
                if session_activity and (not activity or session_activity > activity):
                    activity = min(session_activity, now)
                if activity:
                    run["last_activity"] = _iso(activity)
            verdicts = re.findall(
                # Final outputs can append a head SHA or reason of any length.
                # Read only the enum and check its boundary without consuming or
                # exposing the suffix. Source-file reads are already bounded.
                r"(?m)^[ \t]*VERDICT:[ \t]*(APPROVE|REJECT)(?=[ \t]|\r?$)",
                "\n".join(verdict_texts),
            )
            if run["kind"] == "unknown":
                # Labels are identity, not evidence of purpose. Only explicit conventional
                # labels that name the job kind are classified.
                if re.fullmatch(r"(?:build|impl)(?:[-.0-9].*)?", label):
                    run["kind"] = "build"
                elif re.fullmatch(r"(?:review|judge)(?:[-.0-9].*)?", label):
                    run["kind"] = "judge"
            if verdicts and run["kind"] == "judge" and run["end_time"]:
                run["verdict"] = verdicts[-1]

        def is_stale(activity: str | None) -> bool:
            at = _time(activity)
            return not at or (now - at).total_seconds() > STALE_AFTER_SECONDS

        for run in runs:
            if run["state"] == "running" and is_stale(run["last_activity"]):
                run["state"] = "stale"
            run["live_state"] = run["state"]
            retry = _time(run["next_retry"])
            if (
                run["state"] == "waiting_budget"
                and is_stale(run["last_activity"])
                and (not retry or retry <= now)
            ):
                # Preserve the recorded budget outcome for analytics while
                # declining to present an ancient pause as currently active.
                run["live_state"] = "stale"

        # JOBS may have any basename. Attribute it using recorded serial events,
        # not a filename suffix; canonical copies collapse by parsed job identity.
        files = {}
        for filename in reader.names("serial"):
            if not filename.endswith(".txt") or _identifier(filename) == "unknown":
                continue
            jobs_text, mtime = reader.read(f"serial/{filename}")
            lines = []
            for line in jobs_text.splitlines():
                if not line.strip() or line.lstrip().startswith("#"):
                    continue
                try:
                    fields = shlex.split(line)
                except ValueError:
                    continue
                if (
                    len(fields) >= 3
                    and fields[0] in ("build", "review", "codex", "wait")
                    and re.fullmatch(TICKET, fields[1])
                ):
                    lines.append(fields)
            if not lines:
                continue
            # Paths are used only for identity comparisons; never returned.
            key = tuple(tuple(fields) for fields in lines)
            if key in files:
                files[key]["names"].append(filename)
                if mtime and (not files[key]["mtime"] or mtime < files[key]["mtime"]):
                    files[key]["mtime"] = mtime
                continue
            files[key] = {"names": [filename], "lines": lines, "mtime": mtime}
        lane_sources = {}
        unattributed = []
        for source in files.values():
            evidence = []
            for fields in source["lines"]:
                kind, ticket, label = fields[:3]
                label = "review" if kind == "review" else label
                for lane, observations in lane_events.items():
                    for at, _, message in observations:
                        if re.match(
                            rf"^{re.escape(ticket)} {re.escape(label)}(?:-s\d+)?(?: |$)", message
                        ):
                            evidence.append((at, lane))
            possible = {lane for _, lane in evidence}
            if len(possible) == 1:
                lane = possible.pop()
                rank = max(at for at, _ in evidence)
            elif not possible:
                canonical = {
                    name[:-4] if name != "jobs.txt" else "serial"
                    for name in source["names"]
                    if re.fullmatch(r"(?:lane\d+|jobs)\.txt", name)
                }
                if len(canonical) == 1:
                    lane = canonical.pop()
                    rank = datetime.min.replace(tzinfo=UTC)
                else:
                    unattributed.append(source)
                    continue
            else:
                warnings.add(
                    "A serial job list matches multiple lanes; its lane attribution is ambiguous."
                )
                unattributed.append(source)
                continue
            if lane in lane_sources:
                warnings.add(
                    "Multiple serial job lists match one lane; configuration is selected only by newer recorded job evidence."
                )
            if lane not in lane_sources or rank > lane_sources[lane][0]:
                lane_sources[lane] = (rank, source)
            elif rank == lane_sources[lane][0]:
                lane_sources[lane][1]["ambiguous"] = True
                warnings.add(
                    "Serial job lists have equal lane evidence but conflicting configuration; next job and configured models are unknown."
                )
        for index, source in enumerate(unattributed, 1):
            lane_sources[f"unassigned-{index}"] = (None, source)
            warnings.add(
                "A serial job list has no unique recorded lane; it is shown as unassigned, not live."
            )
        lanes = []
        for lane, (_, source) in sorted(lane_sources.items()):
            jobs = []
            for fields in source["lines"]:
                kind, ticket, label = fields[:3]
                if kind == "review":
                    label = "review"
                job = {
                    "ticket": ticket,
                    "label": _identifier(label),
                    "kind": "build"
                    if kind == "build"
                    or (kind == "codex" and re.match(r"build(?:[-.0-9]|$)", label))
                    else "judge"
                    if kind == "review"
                    or (kind == "codex" and re.match(r"(?:judge|review)(?:[-.0-9]|$)", label))
                    else "unknown",
                    "model": _identifier(fields[3], model=True)
                    if kind == "codex" and len(fields) > 3
                    else _identifier(fields[5], model=True)
                    if kind == "build" and len(fields) > 5
                    else _identifier(fields[4], model=True)
                    if kind == "review" and len(fields) > 4
                    else "unknown",
                }
                candidates = [
                    r
                    for r in runs
                    if r["ticket"] == ticket
                    and (r["lane"] is None or r["lane"] == lane)
                    and (
                        r["label"] == label
                        or (
                            kind in ("build", "review")
                            and re.fullmatch(re.escape(label) + r"-s\d+", r["label"])
                        )
                    )
                ]
                if lane.startswith("unassigned-"):
                    candidates = []
                job["run_ids"] = [r["id"] for r in candidates]
                for run in candidates:
                    if run["lane"] and run["lane"] != lane:
                        continue
                    run["lane"] = lane
                    # A mutable job list supplies a missing model only when its
                    # configuration predates this latest observed label attempt.
                    start = _time(run["start_time"])
                    predates_start = bool(start and source["mtime"] and source["mtime"] <= start)
                    if (
                        predates_start
                        and not source.get("ambiguous")
                        and run["model"] == "unknown"
                        and latest[(ticket, run["label"])] is run
                    ):
                        run["model"] = job["model"]
                    if job["kind"] != "unknown":
                        run["kind"] = job["kind"]
                # A judge directly following a build in the lane records its association.
                if (
                    job["kind"] == "judge"
                    and jobs
                    and jobs[-1]["kind"] == "build"
                    and jobs[-1]["ticket"] == ticket
                ):
                    for run in candidates:
                        builders = [
                            r
                            for r in runs
                            if r["id"] in jobs[-1]["run_ids"]
                            and (
                                not run["start_time"]
                                or (r["start_time"] and r["start_time"] <= run["start_time"])
                            )
                        ]
                        if builders:
                            run["builder_run_id"] = builders[-1]["id"]
                jobs.append(job)
            observations = lane_events.get(lane, [])
            # A lane's old completion cannot complete a replacement job list.
            # Each selected job needs attempt evidence within that invocation.
            invocation = next(
                (at for at, _, message in reversed(observations) if message.startswith("start (")),
                None,
            )
            completion = (
                observations[-1][0]
                if observations and observations[-1][2] == "all jobs done"
                else None
            )
            finished = bool(
                completion
                and not source.get("ambiguous")
                and all(
                    any(
                        r["id"] in job["run_ids"]
                        and r["lane"] == lane
                        and (end := _time(r["end_time"]))
                        and end <= completion
                        and (not invocation or end >= invocation)
                        for r in runs
                    )
                    for job in jobs
                )
            )
            current_run = None
            next_job = None
            for index, job in enumerate(jobs):
                candidates = [r for r in runs if r["id"] in job["run_ids"]]
                last = candidates[-1] if candidates else None
                if last and last["state"] in ("running", "waiting_budget", "stale"):
                    # A later attempt/job is stronger evidence than a stale budget pause.
                    later_started = any(j["run_ids"] for j in jobs[index + 1 :])
                    if not later_started and not finished:
                        current_run = last
                        next_job = jobs[index + 1] if index + 1 < len(jobs) else None
                        break
                if not last and not finished:
                    next_job = job
                    break
            if current_run is None:
                configured_ids = {run_id for job in jobs for run_id in job["run_ids"]}
                observed = [r for r in runs if r["lane"] == lane and r["id"] in configured_ids]
                current_run = observed[-1] if observed else None
            if source.get("ambiguous"):
                next_job = None
            # Completed failed attempts remain budget outcomes in analytics even once retried.
            lanes.append(
                {
                    "id": lane,
                    "current_run_id": current_run["id"] if current_run else None,
                    "next_job": {k: v for k, v in next_job.items() if k != "run_ids"}
                    if next_job
                    else None,
                    "finished": finished,
                    "job_count": None if source.get("ambiguous") else len(jobs),
                    "configuration_ambiguous": bool(source.get("ambiguous")),
                    "state": "unknown"
                    if lane.startswith("unassigned-")
                    else "finished"
                    if finished
                    else current_run["live_state"]
                    if current_run
                    else "unknown",
                }
            )

        by_id = {r["id"]: r for r in runs}
        for run in runs:
            builder = by_id.get(run.get("builder_run_id"))
            if builder:
                run["builder_model"] = builder["model"]
        queue = []
        for ticket, record in current.items():
            column = record.get("column")
            if column in ("merged", "stopped", "finished", "failed"):
                continue
            points, point_source = ticket_points(ticket)
            ticket_runs = [r for r in runs if r["ticket"] == ticket]
            expected_kind = (
                "build" if column == "building" else "judge" if column == "reviewing" else "unknown"
            )
            # Columns describe ticket workflow and can still say building during
            # a one-off judge. Explicit latest job evidence supplies its identity
            # and timing, including a terminal job before state catches up.
            start = _time(record.get("start_time"))
            activity = _time(record.get("last_event_time"))
            pending_queue = column in ("queued", "held")
            # A new chain's recorded start bounds its attempt evidence. Queued
            # tickets are a future invocation even if an older run exists.
            eligible = [
                r
                for r in ticket_runs
                if not start
                or (_time(r["start_time"]) or datetime.min.replace(tzinfo=UTC)) >= start
            ]
            active = eligible[-1] if eligible and not pending_queue else None
            kind = active["kind"] if active else expected_kind
            row_state = (
                active["live_state"]
                if active
                else column
                if pending_queue
                else "running"
                if record.get("running")
                else "unknown"
            )
            if (
                not pending_queue
                and not active
                and (is_stale(_iso(activity)) or not record.get("running"))
            ):
                row_state = "stale"
            if pending_queue:
                start = activity = None
            queue.append(
                {
                    "ticket": ticket,
                    "label": active["label"] if active else _identifier(record.get("phase")),
                    "model": active["model"]
                    if active and active["model"] != "unknown"
                    else _identifier(record.get("model"), model=True)
                    if pending_queue
                    or (kind == "build" and (not active or active["source"] == "queue"))
                    else "unknown",
                    "kind": kind,
                    "state": row_state,
                    "end_time": active["end_time"] if active else None,
                    "duration_seconds": active["duration_seconds"] if active else None,
                    "start_time": active["start_time"] if active else _iso(start),
                    "last_activity": active["last_activity"] if active else _iso(activity),
                    "next_retry": active["next_retry"] if active else None,
                    "current_run_id": active["id"] if active else None,
                    "column": _identifier(column),
                    "points": points,
                    "points_source": point_source,
                }
            )
        snapshot.update(
            available=True,
            message="",
            runs=runs,
            lanes=lanes,
            queue=queue,
            warnings=sorted(warnings),
            source_updated_at=_iso(status_mtime),
        )
        return snapshot
