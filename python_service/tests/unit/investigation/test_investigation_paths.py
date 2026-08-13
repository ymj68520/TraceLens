"""Tests for investigation_db_path_for_task (fail-closed task-scoped path)."""

import pytest

from httpserver.services.evidence import EvidenceStoreError
from httpserver.services.investigation import investigation_db_path_for_task


def test_files_and_events_same_dir(tmp_path):
    d = tmp_path / "A"
    d.mkdir()
    p = investigation_db_path_for_task({
        "output_files_db": str(d / "files.db"),
        "output_events_db": str(d / "events.db"),
    })
    assert p == (d / "investigation.db").resolve(strict=False)


def test_only_files_db(tmp_path):
    d = tmp_path / "A"
    d.mkdir()
    p = investigation_db_path_for_task({"output_files_db": str(d / "files.db")})
    assert p == (d / "investigation.db").resolve(strict=False)


def test_only_events_db(tmp_path):
    d = tmp_path / "A"
    d.mkdir()
    p = investigation_db_path_for_task({"output_events_db": str(d / "events.db")})
    assert p == (d / "investigation.db").resolve(strict=False)


def test_both_empty_raises(tmp_path):
    with pytest.raises(EvidenceStoreError):
        investigation_db_path_for_task({})


def test_inconsistent_dirs_raise(tmp_path):
    a = tmp_path / "A"; a.mkdir()
    b = tmp_path / "B"; b.mkdir()
    with pytest.raises(EvidenceStoreError):
        investigation_db_path_for_task({
            "output_files_db": str(a / "files.db"),
            "output_events_db": str(b / "events.db"),
        })


def test_dot_slash_syntax_normalized(tmp_path):
    d = tmp_path / "A"
    d.mkdir()
    p = investigation_db_path_for_task({
        "output_files_db": str(d / "files.db"),
        "output_events_db": str(d / "." / "events.db"),
    })
    assert p == (d / "investigation.db").resolve(strict=False)
