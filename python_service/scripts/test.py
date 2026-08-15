#!/usr/bin/env python3
"""Run stable Python test profiles from any working directory."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[1]

INVESTIGATION_PATHS = [
    "tests/unit/investigation",
    "tests/unit/test_investigation_event_routes.py",
    "tests/unit/test_investigation_graph_routes.py",
    "tests/unit/test_investigation_read_routes.py",
    "tests/unit/test_investigation_refresh_routes.py",
    "tests/unit/test_investigation_review_routes.py",
    "tests/unit/test_service_manager_investigation.py",
    "tests/unit/test_service_manager_report_lifecycle.py",
]
FAST_EXPRESSION = "not slow and not concurrency and not migration_matrix"


def _run(arguments: list[str]) -> int:
    environment = os.environ.copy()
    site_package_candidates = (
        PYTHON_SERVICE_ROOT
        / ".venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages",
        PYTHON_SERVICE_ROOT / ".venv" / "lib" / "python3.12" / "site-packages",
    )
    site_packages = next(
        (path for path in site_package_candidates if path.is_dir()),
        None,
    )
    if site_packages is not None:
        existing = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(site_packages), existing) if part
        )
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", *arguments],
        cwd=PYTHON_SERVICE_ROOT,
        env=environment,
    )
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="profile", required=True)
    focused = subparsers.add_parser("focused", help="run explicit pytest paths/options")
    focused.add_argument("pytest_args", nargs=argparse.REMAINDER)
    subparsers.add_parser("investigation", help="run Investigation fast regression")
    subparsers.add_parser("fast", help="run fast unit regression")
    subparsers.add_parser("full", help="run the complete unit suite")
    args = parser.parse_args(argv)

    if args.profile == "focused":
        return _run(args.pytest_args)
    if args.profile == "investigation":
        return _run([*INVESTIGATION_PATHS, "-m", FAST_EXPRESSION])
    if args.profile == "fast":
        return _run(["tests/unit", "-m", FAST_EXPRESSION])
    return _run(["tests/unit", "-q"])


if __name__ == "__main__":
    raise SystemExit(main())
