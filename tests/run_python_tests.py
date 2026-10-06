"""Run the Python regression suite with fixture configuration, never live credentials."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    # The legacy module imports Hermes config at module load. Give it a known,
    # non-secret config and an empty temporary home, keeping production intact.
    import vikunja_config

    config = vikunja_config.VikunjaConfig(
        labels={key: key.replace("_", ":") for key in vikunja_config.REQUIRED_LABELS},
        caps={"worker_per_day": 1, "judge_per_day": 1},
        cron={key: f"fixture-{key}" for key in vikunja_config.REQUIRED_CRON},
        discuss={
            "model": "fixture-model", "toolsets": [],
            "toolsets_without_repo": [], "workspace_without_repo": "",
        },
        mention={"user_id": 1, "username": "fixture-bot"},
        vikunja_ui="http://localhost:8788", claim_stale_after_hours=6,
        organizer={}, worker_single_run_spend_limit_usd=1.5,
        path=Path("fixture-vikunja.yaml"),
    )
    with tempfile.TemporaryDirectory(prefix="corylus-config-") as temporary:
        with (
            patch.dict(os.environ, {"HERMES_HOME": temporary}),
            patch.object(vikunja_config, "load", return_value=config),
        ):
            suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
            result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
