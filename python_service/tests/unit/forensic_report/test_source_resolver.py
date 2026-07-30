from hashlib import sha256
from pathlib import Path
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

    adapter = Mock()
    adapter.load_task.return_value = {
        "markdown": "",
        "generated_at": None,
        "filtered_files": [],
    }
    resolved = await SourceResolver(backend, analysis_adapter=adapter).resolve_task("task-1")

    assert resolved.scope_type is ScopeType.TASK
    assert resolved.evidence[0].db_paths["android"] == str(android_db)
    assert resolved.evidence[0].source_fingerprints["android"].size == 7
    assert resolved.evidence[0].source_fingerprints["android"].sha256 == sha256(b"android").hexdigest()
    assert resolved.contexts[0].evidence_id == "task-1"
    assert resolved.case_description == "fraud"


def test_fingerprint_file_returns_nonexistent_source_without_reading(tmp_path: Path):
    missing = tmp_path / "missing.db"

    fingerprint = fingerprint_file(str(missing))

    assert fingerprint.path == str(missing)
    assert fingerprint.exists is False
    assert fingerprint.size is None
    assert fingerprint.mtime_ns is None
    assert fingerprint.sha256 is None
