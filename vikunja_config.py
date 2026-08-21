#!/usr/bin/env python3
"""Load ~/.hermes/vikunja.yaml. Fail loud if a required key is missing."""
from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:  # pyyaml may live only in the Hermes venv
    yaml = None

HERMES_HOME = Path.home() / ".hermes"
CONFIG_PATH = HERMES_HOME / "vikunja.yaml"

REQUIRED_LABELS = (
    "worker_ready",
    "worker_escalate",
    "judge_ready",
    "judge_escalate",
    "judged",
    "needs_review",
    "in_progress",
    "blocked",
    "human_only",
)
REQUIRED_CAPS = ("worker_per_day", "judge_per_day")
REQUIRED_CRON = ("worker", "worker_escalate", "judge", "judge_escalate")
DEFAULT_WORKER_SINGLE_RUN_SPEND_LIMIT_USD = 1.50


class VikunjaConfigError(RuntimeError):
    pass


def _need(mapping: Any, keys: tuple[str, ...], section: str) -> dict:
    if not isinstance(mapping, dict):
        raise VikunjaConfigError(f"{CONFIG_PATH}: missing section {section!r}")
    missing = [k for k in keys if k not in mapping or mapping[k] in (None, "")]
    if missing:
        raise VikunjaConfigError(
            f"{CONFIG_PATH}: {section} missing required key(s): {', '.join(missing)}"
        )
    return mapping


@dataclass(frozen=True)
class VikunjaConfig:
    labels: dict[str, str]
    caps: dict[str, int]
    cron: dict[str, str]
    discuss: dict[str, Any]
    mention: dict[str, Any]
    vikunja_ui: str
    claim_stale_after_hours: int
    organizer: dict[str, Any]
    worker_single_run_spend_limit_usd: float
    path: Path

    def label(self, key: str) -> str:
        return self.labels[key]

    def job(self, key: str) -> str:
        return self.cron[key]


def load(path: Path | None = None) -> VikunjaConfig:
    cfg_path = path or CONFIG_PATH
    if yaml is None:
        raise VikunjaConfigError(
            "PyYAML is not installed (need yaml in the Hermes venv)"
        )
    if not cfg_path.is_file():
        raise VikunjaConfigError(f"missing config {cfg_path}")
    data = yaml.safe_load(cfg_path.read_text()) or {}
    if not isinstance(data, dict):
        raise VikunjaConfigError(f"{cfg_path}: root must be a mapping")
    labels = _need(data.get("labels"), REQUIRED_LABELS, "labels")
    caps = _need(data.get("caps"), REQUIRED_CAPS, "caps")
    cron = _need(data.get("cron"), REQUIRED_CRON, "cron")
    for key in REQUIRED_CAPS:
        if not isinstance(caps[key], int) or caps[key] < 1:
            raise VikunjaConfigError(f"{cfg_path}: caps.{key} must be a positive int")
    discuss = data.get("discuss") or {}
    mention = data.get("mention") or {}
    organizer = data.get("organizer") or {}
    if organizer and not isinstance(organizer, dict):
        raise VikunjaConfigError(f"{cfg_path}: organizer must be a mapping")
    if not isinstance(organizer, dict):
        organizer = {}
    ui = data.get("vikunja_ui") or ""
    hours = data.get("claim_stale_after_hours")
    if hours is None:
        hours = 6
    if not isinstance(hours, int) or hours < 1:
        raise VikunjaConfigError(
            f"{cfg_path}: claim_stale_after_hours must be a positive int"
        )
    spend_limit = data.get("worker_single_run_spend_limit_usd")
    if spend_limit is None:
        spend_limit = DEFAULT_WORKER_SINGLE_RUN_SPEND_LIMIT_USD
    if (
        isinstance(spend_limit, bool)
        or not isinstance(spend_limit, (int, float))
        or not math.isfinite(spend_limit)
        or spend_limit < 0
    ):
        raise VikunjaConfigError(
            f"{cfg_path}: worker_single_run_spend_limit_usd must be a finite "
            "non-negative number"
        )
    return VikunjaConfig(
        labels={k: str(labels[k]) for k in REQUIRED_LABELS},
        caps={k: int(caps[k]) for k in REQUIRED_CAPS},
        cron={k: str(cron[k]) for k in REQUIRED_CRON},
        discuss=discuss if isinstance(discuss, dict) else {},
        mention=mention if isinstance(mention, dict) else {},
        vikunja_ui=str(ui),
        claim_stale_after_hours=hours,
        organizer=organizer,
        worker_single_run_spend_limit_usd=float(spend_limit),
        path=cfg_path,
    )


def check_labels(client, cfg: VikunjaConfig | None = None) -> list[str]:
    """Return yaml label titles that do not exist in Vikunja. Empty = ok."""
    cfg = cfg or load()
    response = client.get("/labels")
    response.raise_for_status()
    have = {item.get("title") for item in (response.json() or [])}
    return [title for title in cfg.labels.values() if title not in have]


def main() -> int:
    cfg = load()
    print(f"loaded {cfg.path}")
    print("labels", cfg.labels)
    print("caps", cfg.caps)
    print("cron", cfg.cron)
    if len(sys.argv) > 1 and sys.argv[1] == "check":
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import hermes_machine_comments as hmc  # noqa: E402

        hmc.load_env()
        with hmc._client() as client:
            missing = check_labels(client, cfg)
        if missing:
            print("missing Vikunja labels:", ", ".join(missing), file=sys.stderr)
            return 1
        print("all yaml labels exist in Vikunja")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
