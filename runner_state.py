"""Bounded, read-only public projection of runner state schema version 1.

The source file is configured locally with CORYLUS_RUNNER_STATE_FILE. No local
file locations are included in snapshots or error messages. Unknown fields are
ignored; schema 1 does not supply titles, accounting, or a full event timeline.
"""

from __future__ import annotations

import json
import os
import re
import stat
from datetime import datetime, time
from urllib.parse import urlsplit

MAX_BYTES = 2 * 1024 * 1024
MAX_TICKETS = 2000
MAX_MERGES = 10000
MAX_TEXT = 2048
MAX_BLOCKERS = 100
COLUMNS = {
    "queued",
    "held",
    "building",
    "reviewing",
    "needs_decision",
    "merged",
    "stopped",
}
_TICKET = re.compile(r"td-[a-zA-Z0-9]{1,32}\Z")
_HEAD = re.compile(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})?\Z")
_PATH = re.compile(r"(?<![\w/])(?:[A-Za-z]:[\\/]|~?/|\\\\)[^\s<>\"'`),;]+")
_URL = re.compile(r"https?://[^\s<>\"'`),;]+", re.IGNORECASE)
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PUBLIC_TICKET_FIELDS = {
    "id",
    "repo",
    "pr_url",
    "column",
    "round",
    "engine",
    "model",
    "start_time",
    "last_event_time",
    "reviewed_head",
    "hold_reason",
    "blockers",
    "running",
    "phase",
    "name",
}


class InvalidRunnerState(ValueError):
    """The snapshot cannot be safely interpreted as schema version 1."""


def _text(value: object, *, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise InvalidRunnerState("Invalid text field")
    # The digest's blocker summaries and latest messages may mention local
    # paths. Preserve their useful prose, without exposing filesystem details.
    value = _URL.sub("[link]", value)
    value = _PATH.sub("[path]", value)
    value = _IP.sub("[address]", value)
    return " ".join(value.split())


def _timestamp(
    value: object, *, nullable: bool = False, dated: bool = False
) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or len(value) > 64:
        raise InvalidRunnerState("Invalid timestamp")
    try:
        if not dated and re.fullmatch(r"\d{2}:\d{2}:\d{2}", value):
            time.fromisoformat(value)
        else:
            if not re.match(r"\d{4}-\d{2}-\d{2}T", value):
                raise ValueError
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.utcoffset() is None:
                raise ValueError
    except ValueError as exc:
        raise InvalidRunnerState("Invalid timestamp") from exc
    return value


def _ticket_id(value: object) -> str:
    if not isinstance(value, str) or not _TICKET.fullmatch(value):
        raise InvalidRunnerState("Invalid ticket ID")
    return value


def _pr_url(value: object) -> str:
    if not isinstance(value, str) or len(value) > MAX_TEXT:
        raise InvalidRunnerState("Invalid PR URL")
    if not value:
        return ""
    try:
        parsed = urlsplit(value)
        if (
            parsed.scheme == "https"
            and parsed.netloc == "github.com"
            and re.fullmatch(r"/[\w.-]+/[\w.-]+/pull/[1-9]\d*", parsed.path)
            and not parsed.query
            and not parsed.fragment
        ):
            return value
    except ValueError:
        pass
    return ""


def _repo_label(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > MAX_TEXT:
        raise InvalidRunnerState("Invalid repository")
    label = value.replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", label):
        raise InvalidRunnerState("Invalid repository label")
    return label


def normalize_state(state: object) -> dict:
    """Validate a schema-1 snapshot and return its public, path-free fields.

    Schema 1 has no queue ordering field. An optional explicit queue_position
    extension is accepted only as a positive integer; absent values stay null.
    Array order never establishes dispatch priority. Legacy time-only events
    remain time-only: their date is unknown.
    """
    if not isinstance(state, dict) or type(state.get("schema_version")) is not int:
        raise InvalidRunnerState("Invalid schema version")
    if state["schema_version"] != 1:
        raise InvalidRunnerState("Unsupported schema version")
    tickets = state.get("tickets")
    merges = state.get("merges")
    if not isinstance(tickets, list) or len(tickets) > MAX_TICKETS:
        raise InvalidRunnerState("Invalid ticket list")
    if not isinstance(merges, list) or len(merges) > MAX_MERGES:
        raise InvalidRunnerState("Invalid merge list")
    result = {
        "available": True,
        "schema_version": 1,
        "generated_at": _timestamp(state.get("generated_at"), dated=True),
        "tickets": [],
        "merges": [],
    }
    seen = set()
    for ticket in tickets:
        if not isinstance(ticket, dict):
            raise InvalidRunnerState("Invalid ticket record")
        if not _PUBLIC_TICKET_FIELDS.issubset(ticket):
            raise InvalidRunnerState("Missing ticket fields")
        ticket_id = _ticket_id(ticket.get("id"))
        column = ticket.get("column")
        if not isinstance(column, str) or column not in COLUMNS or ticket_id in seen:
            raise InvalidRunnerState("Invalid ticket column or duplicate ID")
        seen.add(ticket_id)
        round_number = ticket.get("round")
        if type(round_number) is not int or not 0 <= round_number <= 100000:
            raise InvalidRunnerState("Invalid round")
        if type(ticket.get("running")) is not bool:
            raise InvalidRunnerState("Invalid running flag")
        blockers = ticket.get("blockers")
        if not isinstance(blockers, list) or len(blockers) > MAX_BLOCKERS:
            raise InvalidRunnerState("Invalid blockers")
        head = ticket.get("reviewed_head")
        if not isinstance(head, str) or not _HEAD.fullmatch(head):
            raise InvalidRunnerState("Invalid reviewed head")
        queue_position = ticket.get("queue_position")
        if queue_position is not None and (
            type(queue_position) is not int or queue_position <= 0
        ):
            raise InvalidRunnerState("Invalid queue position")
        result["tickets"].append(
            {
                "id": ticket_id,
                "repo": _repo_label(ticket.get("repo")),
                "pr_url": _pr_url(ticket.get("pr_url")),
                "column": column,
                "round": round_number,
                "engine": _text(ticket.get("engine")),
                "model": _text(ticket.get("model")),
                "start_time": _timestamp(ticket.get("start_time"), nullable=True),
                "last_event_time": _timestamp(
                    ticket.get("last_event_time"), nullable=True
                ),
                "reviewed_head": head,
                "hold_reason": _text(ticket.get("hold_reason"), nullable=True),
                "blockers": [_text(blocker) for blocker in blockers],
                "running": ticket["running"],
                "phase": _text(ticket.get("phase")),
                "name": _text(ticket.get("name")),
                "queue_position": queue_position if column == "queued" else None,
            }
        )
    for merge in merges:
        if not isinstance(merge, dict):
            raise InvalidRunnerState("Invalid merge record")
        result["merges"].append(
            {
                "ticket": _ticket_id(merge.get("ticket")),
                "merged_at": _timestamp(merge.get("merged_at")),
                "message": _text(merge.get("message")),
            }
        )
    return result


def snapshot_from_environment() -> dict:
    """Read one complete snapshot using only locally configured file location."""
    source = os.environ.get("CORYLUS_RUNNER_STATE_FILE")
    if not source:
        return {"available": False, "error": "Runner state is not configured"}
    try:
        # NONBLOCK prevents a malicious/mistaken FIFO from hanging the server.
        descriptor = os.open(source, os.O_RDONLY | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise InvalidRunnerState("Invalid state file")
            data = handle.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise InvalidRunnerState("State file too large")
        return normalize_state(json.loads(data))
    except (OSError, ValueError, RecursionError):
        return {"available": False, "error": "Runner state is unavailable or invalid"}
