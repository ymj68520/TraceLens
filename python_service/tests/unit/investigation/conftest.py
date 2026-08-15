"""Shared opt-in fixtures for Investigation tests."""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

import pytest

from httpserver.services.investigation import InvestigationRepository, SUPPORTED_SCHEMA_VERSION


@pytest.fixture(scope="session")
def investigation_v7_baseline(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create and validate an immutable, empty current-schema DB once."""
    root = tmp_path_factory.mktemp("investigation-baseline")
    path = root / "investigation.db"
    InvestigationRepository(path, "baseline")

    assert not Path(f"{path}-wal").exists()
    assert not Path(f"{path}-shm").exists()
    with sqlite3.connect(path) as conn:
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SUPPORTED_SCHEMA_VERSION == 7
    return path

def _copy_investigation_v7_baseline(
    investigation_v7_baseline: Path, tmp_path: Path
) -> Path:
    destination = tmp_path / "investigation.db"
    shutil.copy2(investigation_v7_baseline, destination)
    return destination


@pytest.fixture
def copy_investigation_v7_baseline(investigation_v7_baseline):
    """Return an explicit copier for tests that require a valid v7 store."""
    return lambda tmp_path: _copy_investigation_v7_baseline(
        investigation_v7_baseline, tmp_path
    )
