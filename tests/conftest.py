"""Keep pytest collection and execution on synthetic config, never live credentials."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    # conftest's directory is on pytest's import path. Enter before collecting
    # legacy test modules that load Hermes configuration at import time.
    from run_python_tests import fixture_environment

    environment = fixture_environment()
    environment.__enter__()
    config._corylus_fixture_environment = environment


def pytest_unconfigure(config):
    environment = getattr(config, "_corylus_fixture_environment", None)
    if environment is not None:
        environment.__exit__(None, None, None)
        del config._corylus_fixture_environment
