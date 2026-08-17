"""Phase D2b: task-owned store/path resolution helper contracts.

Covers validate_legacy_db_path exact-match semantics, component-aware
workspace containment (sibling prefix, traversal, symlink escape), record
fail-closed behaviour, and exact files.path membership.
"""

from __future__ import annotations

import sqlite3

import pytest

from httpserver.services import task_store


# --------------------------------------------------------------- legacy path


def test_legacy_path_absent_passes():
    task_store.validate_legacy_db_path(None, "/data/tasks/t1/x_files.db")
    task_store.validate_legacy_db_path("", "/data/tasks/t1/x_files.db")
    task_store.validate_legacy_db_path("   ", "/data/tasks/t1/x_files.db")


def test_legacy_path_exact_match_passes(tmp_path):
    trusted = tmp_path / "x_files.db"
    task_store.validate_legacy_db_path(str(trusted), trusted)


def test_legacy_path_resolve_equivalent_match_passes(tmp_path):
    trusted = tmp_path / "x_files.db"
    supplied = str(tmp_path / "." / ".." / tmp_path.name / "x_files.db")
    task_store.validate_legacy_db_path(supplied, trusted)


@pytest.mark.parametrize(
    "supplied",
    [
        "x_files.db",  # basename only — forbidden
        "x_files.db.bak",  # suffix match — forbidden
    ],
)
def test_legacy_path_basename_and_suffix_rejected(supplied, tmp_path):
    trusted = tmp_path / "x_files.db"
    with pytest.raises(task_store.TaskStoreError) as excinfo:
        task_store.validate_legacy_db_path(supplied, trusted)
    assert excinfo.value.code == task_store.PATH_MISMATCH


def test_legacy_path_other_task_db_rejected(tmp_path):
    trusted = tmp_path / "a_files.db"
    supplied = tmp_path / "b_files.db"
    with pytest.raises(task_store.TaskStoreError) as excinfo:
        task_store.validate_legacy_db_path(str(supplied), trusted)
    assert excinfo.value.code == task_store.PATH_MISMATCH


# ----------------------------------------------------------- containment


def test_containment_child_passes(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    child = root / "sub" / "file.txt"
    assert task_store.resolved_within(root, child) == child.resolve(strict=False)


def test_containment_root_itself_passes(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    assert task_store.resolved_within(root, root) == root.resolve()


def test_containment_sibling_prefix_rejected(tmp_path, tmp_path_factory):
    root = tmp_path / "taskA"
    root.mkdir()
    sibling = tmp_path / "taskABC"
    sibling.mkdir()
    with pytest.raises(task_store.TaskStoreError) as excinfo:
        task_store.resolved_within(root, sibling)
    assert excinfo.value.code == task_store.PATH_OUTSIDE_WORKSPACE


def test_containment_parent_escape_rejected(tmp_path):
    root = tmp_path / "task"
    root.mkdir()
    with pytest.raises(task_store.TaskStoreError):
        task_store.resolved_within(root, root / ".." / "outside.txt")


def test_containment_absolute_outside_rejected(tmp_path, tmp_path_factory):
    root = tmp_path / "task"
    root.mkdir()
    outside = tmp_path_factory.mktemp("outside")
    with pytest.raises(task_store.TaskStoreError):
        task_store.resolved_within(root, outside / "file.txt")


def test_containment_symlink_escape_rejected(tmp_path, tmp_path_factory):
    root = tmp_path / "task"
    root.mkdir()
    outside = tmp_path_factory.mktemp("outside-target")
    target = outside / "secret.txt"
    target.write_text("x")
    link = root / "linked.txt"
    link.symlink_to(target)
    with pytest.raises(task_store.TaskStoreError):
        task_store.resolved_within(root, link)


def test_containment_existing_prefix_symlink_directory_rejected(
    tmp_path, tmp_path_factory
):
    root = tmp_path / "task"
    root.mkdir()
    outside = tmp_path_factory.mktemp("outside-dir")
    link_dir = root / "linkeddir"
    link_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(task_store.TaskStoreError):
        task_store.resolved_within(root, link_dir / "file.txt")


# ------------------------------------------------------------- records


@pytest.mark.asyncio
async def test_resolve_task_files_db_requires_existing_task(monkeypatch):
    class FakeCppBackend:
        async def get_task(self, task_id):
            return None

    class FakeServiceManager:
        cpp_backend = FakeCppBackend()

    monkeypatch.setattr(
        "httpserver.services.get_service_manager",
        lambda: FakeServiceManager(),
    )
    with pytest.raises(task_store.TaskStoreError) as excinfo:
        await task_store.resolve_task_files_db("missing")
    assert excinfo.value.code == task_store.TASK_NOT_FOUND


@pytest.mark.asyncio
async def test_resolve_task_files_db_and_workspace(monkeypatch, tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()

    class FakeCppBackend:
        async def get_task(self, task_id):
            return {
                "id": task_id,
                "output_files_db": str(ws / "x_files.db"),
                "output_events_db": str(ws / "x_events.db"),
            }

    class FakeServiceManager:
        cpp_backend = FakeCppBackend()

    monkeypatch.setattr(
        "httpserver.services.get_service_manager",
        lambda: FakeServiceManager(),
    )
    assert await task_store.resolve_task_files_db("t1") == ws / "x_files.db"
    assert await task_store.resolve_task_workspace("t1") == ws.resolve()


def test_record_without_db_paths_fails_closed():
    with pytest.raises(task_store.TaskStoreError) as excinfo:
        task_store.workspace_from_record({"id": "t1"})
    assert excinfo.value.code == task_store.TASK_STORE_UNAVAILABLE
    with pytest.raises(task_store.TaskStoreError):
        task_store.files_db_from_record({"id": "t1"})


def test_record_with_inconsistent_db_dirs_fails_closed(tmp_path):
    record = {
        "output_files_db": str(tmp_path / "a" / "x_files.db"),
        "output_events_db": str(tmp_path / "b" / "x_events.db"),
    }
    with pytest.raises(task_store.TaskStoreError):
        task_store.workspace_from_record(record)


# ------------------------------------------------------------- membership


def _make_files_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE files (path TEXT)")
    conn.executemany("INSERT INTO files VALUES (?)", [(r,) for r in rows])
    conn.commit()
    conn.close()


def test_membership_exact_row_passes(tmp_path):
    db = tmp_path / "x_files.db"
    _make_files_db(db, ["/evidence/a/doc.txt"])
    assert task_store.file_known_to_task(db, "/evidence/a/doc.txt")
    assert not task_store.file_known_to_task(db, "/evidence/a/other.txt")
    # exact semantics only — no normalization of separators
    assert not task_store.file_known_to_task(db, "\\evidence\\a\\doc.txt")


def test_membership_missing_db_fails_closed(tmp_path):
    with pytest.raises(task_store.TaskStoreError) as excinfo:
        task_store.file_known_to_task(tmp_path / "missing.db", "/x")
    assert excinfo.value.code == task_store.TASK_STORE_UNAVAILABLE


def test_membership_db_without_files_table_fails_closed(tmp_path):
    db = tmp_path / "x_files.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE other (x TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(task_store.TaskStoreError):
        task_store.file_known_to_task(db, "/x")
