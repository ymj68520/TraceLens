import asyncio
import os
from hashlib import sha256
from pathlib import Path
from threading import Event
from unittest.mock import AsyncMock, Mock

import pytest

from httpserver.services.forensic_report.models import ScopeType
from httpserver.services.forensic_report.source_resolver import (
    SourceResolver,
    fingerprint_file,
)


@pytest.mark.asyncio
async def test_task_resolution_uses_backend_paths_and_freezes_fingerprints(tmp_path: Path):
    files_db = tmp_path / "files.db"
    android_db = tmp_path / "android.db"
    files_db.write_bytes(b"files")
    android_db.write_bytes(b"android")
    backend = AsyncMock()
    backend.get_task.return_value = {
        "id": "task-1",
        "image_path": "/evidence/phone.E01",
        "case_description": "fraud",
        "output_files_db": str(files_db),
    }
    backend.get_task_databases.return_value = [
        {"type": "files", "path": str(files_db)},
        {"type": "android", "path": str(android_db)},
    ]

    resolved = await SourceResolver(backend).resolve_task("task-1")

    assert resolved.scope_type is ScopeType.TASK
    assert resolved.evidence[0].db_paths["android"] == str(android_db)
    assert resolved.evidence[0].source_fingerprints["android"].size == 7
    assert resolved.evidence[0].source_fingerprints["android"].sha256 == sha256(b"android").hexdigest()
    assert resolved.contexts[0].evidence_id == "task-1"
    assert not hasattr(resolved, "case_description")


def test_fingerprint_file_returns_nonexistent_source_without_reading(tmp_path: Path):
    missing = tmp_path / "missing.db"

    fingerprint = fingerprint_file(str(missing))

    assert fingerprint.path == str(missing)
    assert fingerprint.exists is False
    assert fingerprint.size is None
    assert fingerprint.mtime_ns is None
    assert fingerprint.sha256 is None


def test_fingerprint_file_rejects_a_source_changed_while_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "changing.db"
    source.write_bytes(b"a" * (2 * 1024 * 1024))
    original_fstat = os.fstat
    calls = 0

    def changing_fstat(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            source.write_bytes(b"b" * (2 * 1024 * 1024 + 1))
        return original_fstat(fd)

    monkeypatch.setattr(os, "fstat", changing_fstat)

    with pytest.raises(RuntimeError, match="changed while fingerprinting"):
        fingerprint_file(str(source))


def test_fingerprint_file_rejects_a_source_replaced_while_hashing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    source = tmp_path / "replaced.db"
    replacement = tmp_path / "replacement.db"
    source.write_bytes(b"original")
    replacement.write_bytes(b"replacement")
    original_fstat = os.fstat
    calls = 0

    def replacing_fstat(fd):
        nonlocal calls
        calls += 1
        if calls == 2:
            os.replace(replacement, source)
        return original_fstat(fd)

    monkeypatch.setattr(os, "fstat", replacing_fstat)

    with pytest.raises(RuntimeError, match="changed while fingerprinting"):
        fingerprint_file(str(source))


@pytest.mark.asyncio
async def test_task_resolution_moves_source_freeze_off_the_event_loop(tmp_path: Path):
    source = tmp_path / "files.db"
    source.write_bytes(b"files")
    backend = AsyncMock()
    backend.get_task.return_value = {
        "id": "task-1",
        "image_path": "/evidence/phone.E01",
        "output_files_db": str(source),
    }
    backend.get_task_databases.return_value = [{"type": "files", "path": str(source)}]
    entered = Event()
    release = Event()

    def blocking_fingerprint(path: str):
        entered.set()
        assert release.wait(timeout=1)
        return fingerprint_file(path)

    resolver = SourceResolver(backend)
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(
            "httpserver.services.forensic_report.source_resolver.fingerprint_file",
            blocking_fingerprint,
        )
        resolution = asyncio.create_task(resolver.resolve_task("task-1"))
        asyncio.get_running_loop().call_later(0.01, release.set)
        await asyncio.wait_for(resolution, timeout=0.5)
    assert entered.is_set()
