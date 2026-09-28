"""Only synthetic AndroidAnalyzer outputs; no real Task or image is opened."""

import sqlite3

import pytest

from httpserver.services.android_artifact_reader import ArtifactChanged, artifact_detail
from httpserver.services.android_result_sets import freeze_selected_result, read_frozen_artifact, read_result_set


@pytest.fixture
def task(tmp_path):
    db = tmp_path / "android.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE sms_messages(id INTEGER PRIMARY KEY, address TEXT, body TEXT, date INTEGER, type INTEGER)")
        con.execute("INSERT INTO sms_messages VALUES(1,'10086','same body',1700000000000,1)")
        con.execute("INSERT INTO sms_messages VALUES(2,'10086','same body',1700000000000,1)")
        con.execute("CREATE TABLE android_source_coverage(artifact_kind TEXT, source_path TEXT, status TEXT, detail TEXT)")
        con.execute("INSERT INTO android_source_coverage VALUES('sms','data/data/telephony/mmssms.db','staged_for_parser','bundle read')")
    return {"id": "synthetic-task", "output_files_db": str(db), "android_source": "dir"}


def test_freeze_once_and_keep_duplicate_rows_distinct(task, tmp_path):
    assert not (tmp_path / "android_result_sets").exists()
    with pytest.raises(FileNotFoundError):
        read_result_set(task, "a" * 64)
    assert not (tmp_path / "android_result_sets").exists()  # GET is read-only
    first = artifact_detail(task, "sms", 1)
    second = artifact_detail(task, "sms", 2)
    assert first["record_hash"] != second["record_hash"]  # id is part of the exact row
    manifest = freeze_selected_result(task, "sms", 1,
        expected_row_hash=first["record_hash"], expected_source_revision=first["source_revision"])
    again = freeze_selected_result(task, "sms", 2,
        expected_row_hash=second["record_hash"], expected_source_revision=second["source_revision"])
    assert again["result_set_id"] == manifest["result_set_id"]
    assert len(list((tmp_path / "android_result_sets").glob("*/android.db"))) == 1
    frozen = read_frozen_artifact(task, manifest["result_set_id"], "sms", 1)
    assert frozen["record"]["body"] == "same body"
    assert frozen["source"]["original_primary_key"] is None


def test_changed_source_conflicts_but_old_result_stays_frozen(task, tmp_path):
    detail = artifact_detail(task, "sms", 1)
    old = freeze_selected_result(task, "sms", 1,
        expected_row_hash=detail["record_hash"], expected_source_revision=detail["source_revision"])
    with sqlite3.connect(tmp_path / "android.db") as con:
        con.execute("UPDATE sms_messages SET body='new body' WHERE id=1")
    with pytest.raises(ArtifactChanged):
        freeze_selected_result(task, "sms", 1,
            expected_row_hash=detail["record_hash"], expected_source_revision=detail["source_revision"])
    latest = artifact_detail(task, "sms", 1)
    new = freeze_selected_result(task, "sms", 1,
        expected_row_hash=latest["record_hash"], expected_source_revision=latest["source_revision"])
    assert new["result_set_id"] != old["result_set_id"]
    assert read_frozen_artifact(task, old["result_set_id"], "sms", 1)["record"]["body"] == "same body"
    assert read_frozen_artifact(task, new["result_set_id"], "sms", 1)["record"]["body"] == "new body"
    with pytest.raises(ValueError):
        read_result_set(task, "../../etc/passwd")
    foreign = {**task, "id": "other-task"}
    with pytest.raises(ValueError):
        read_result_set(foreign, old["result_set_id"])


def test_snapshot_tamper_is_rejected(task, tmp_path):
    detail = artifact_detail(task, "sms", 1)
    result = freeze_selected_result(task, "sms", 1,
        expected_row_hash=detail["record_hash"], expected_source_revision=detail["source_revision"])
    frozen_db = tmp_path / "android_result_sets" / result["result_set_id"] / "android.db"
    with sqlite3.connect(frozen_db) as con:
        con.execute("UPDATE sms_messages SET body='tampered' WHERE id=1")
    with pytest.raises(ValueError):
        read_result_set(task, result["result_set_id"])


def test_result_set_symlink_escape_is_rejected(task, tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside")
    outside.mkdir()
    (tmp_path / "android_result_sets").symlink_to(outside, target_is_directory=True)
    detail = artifact_detail(task, "sms", 1)
    with pytest.raises(ValueError):
        freeze_selected_result(task, "sms", 1,
            expected_row_hash=detail["record_hash"], expected_source_revision=detail["source_revision"])
    assert list(outside.iterdir()) == []
