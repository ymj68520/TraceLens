"""Workbench side-table store boundary tests.

The side tables must only ever augment an existing investigation store:
opening a missing file would materialize an empty user_version=0 store
that wedges the next bootstrap on "schema 0 requires manual migration"
(the workbench rendered an error for such tasks).
"""

from httpserver.services.investigation import workbench_state
import pytest


def test_read_on_missing_store_raises_instead_of_creating(tmp_path):
    db = tmp_path / "investigation.db"
    with pytest.raises(FileNotFoundError):
        workbench_state.event_review_statuses_sync(db, "T1")
    assert not db.exists()


def test_write_on_missing_store_raises_instead_of_creating(tmp_path):
    db = tmp_path / "investigation.db"
    with pytest.raises(FileNotFoundError):
        workbench_state.set_event_review_status_sync(db, "T1", "ev-1", "confirmed")
    assert not db.exists()


def test_side_tables_roundtrip_on_existing_store(tmp_path):
    db = tmp_path / "investigation.db"
    db.touch()
    workbench_state.set_event_review_status_sync(db, "T1", "ev-1", "confirmed")
    assert workbench_state.event_review_statuses_sync(db, "T1") == {
        "ev-1": "confirmed"
    }
    workbench_state.upsert_note_sync(db, "T1", "evidence", "k", "调查上下文笔记")
    assert (
        workbench_state.get_note_sync(db, "T1", "evidence", "k")["content"]
        == "调查上下文笔记"
    )
