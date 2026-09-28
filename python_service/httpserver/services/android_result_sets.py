"""Immutable task-owned AndroidAnalyzer result versions (derived DB only).

Only POST capture creates a result set. Every read resolves a version from the
trusted task workspace and verifies the frozen database SHA-256. The original
image, third-party records.db and existing Task databases are never changed.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .android_artifact_reader import (
    ArtifactChanged, ArtifactUnavailable, artifact_detail_from_database,
    raw_row_hash, read_raw_row, source_revision,
)
from .android_coverage import read_coverage, resolve_android_db
from .android_field_package import _hash, _snapshot
from .task_store import workspace_from_record

RESULT_SET_ID = re.compile(r"[0-9a-f]{64}\Z")
MAX_RESULT_SETS_PER_TASK = 1000


def _root(task: dict, *, create: bool = False) -> Path:
    workspace = workspace_from_record(task)
    root = workspace / "android_result_sets"
    if root.is_symlink() or root.resolve(strict=False).parent != workspace:
        raise ArtifactUnavailable("result-set root escapes the task workspace")
    if create:
        root.mkdir(mode=0o700, exist_ok=True)
    return root


def _result_id(task_id: str, revision: str, snapshot_sha256: str) -> str:
    return hashlib.sha256(f"{task_id}|{revision}|{snapshot_sha256}".encode()).hexdigest()


def _load(task: dict, result_set_id: str) -> tuple[dict, Path]:
    if not RESULT_SET_ID.fullmatch(result_set_id):
        raise ValueError("invalid Android result-set ID")
    directory = _root(task) / result_set_id
    manifest_path = directory / "manifest.json"
    digest_path = directory / "manifest.sha256"
    db = directory / "android.db"
    if (directory.is_symlink() or manifest_path.is_symlink() or digest_path.is_symlink() or db.is_symlink()
            or not manifest_path.is_file() or not digest_path.is_file() or not db.is_file()):
        raise FileNotFoundError("Android result set not found")
    if digest_path.read_text(encoding="ascii").strip() != _hash(manifest_path):
        raise ArtifactUnavailable("Android result-set manifest changed after capture")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise ArtifactUnavailable("Android result-set manifest is invalid") from exc
    if (manifest.get("task_id") != task["id"] or manifest.get("result_set_id") != result_set_id
            or manifest.get("source_type") != "android_analyzer"
            or not RESULT_SET_ID.fullmatch(str(manifest.get("snapshot_sha256", "")))
            or not RESULT_SET_ID.fullmatch(str(manifest.get("source_revision", "")))
            or _result_id(task["id"], manifest["source_revision"], manifest["snapshot_sha256"]) != result_set_id):
        raise ArtifactUnavailable("Android result-set identity is invalid")
    if _hash(db) != manifest["snapshot_sha256"]:
        raise ArtifactUnavailable("Android result-set database changed after capture")
    return manifest, db


def read_result_set(task: dict, result_set_id: str) -> tuple[dict, Path]:
    """Strict read-only lookup; never creates directories, databases or schema."""
    return _load(task, result_set_id)


def read_frozen_artifact(task: dict, result_set_id: str, kind: str, row_id: int) -> dict:
    manifest, db = _load(task, result_set_id)
    detail = artifact_detail_from_database(db, task["id"], kind, row_id)
    return {**detail, "result_set_id": result_set_id, "result_manifest": manifest}


def freeze_selected_result(task: dict, kind: str, row_id: int, *,
                           expected_row_hash: str, expected_source_revision: str) -> dict:
    """Freeze the selected row's exact current derived result version once.

    The row digest and bundle revision are from the prior GET; a changed row,
    bundle, or snapshot-under-copy raises conflict. The caller never supplies a
    database path/table. A reused revision shares one already frozen snapshot.
    """
    if not RESULT_SET_ID.fullmatch(expected_row_hash or "") or not RESULT_SET_ID.fullmatch(expected_source_revision or ""):
        raise ValueError("capture requires the selected row hash and source revision")
    root = _root(task, create=True)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(root / ".capture.lock", flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        source = resolve_android_db(task)
        if source is None:
            raise ArtifactUnavailable("task has no AndroidAnalyzer database")
        if source_revision(task) != expected_source_revision:
            raise ArtifactChanged("Android result changed; refresh the selected record")
        try:
            selected = read_raw_row(source, kind, row_id)
        except FileNotFoundError as exc:
            raise ArtifactChanged("selected Android record disappeared") from exc
        if raw_row_hash(selected) != expected_row_hash:
            raise ArtifactChanged("selected Android record changed; refresh before capture")
        candidates = [path for path in root.iterdir() if path.is_dir()]
        for candidate in candidates:
            if not RESULT_SET_ID.fullmatch(candidate.name):
                continue
            manifest, db = _load(task, candidate.name)
            if manifest["source_revision"] == expected_source_revision:
                if raw_row_hash(read_raw_row(db, kind, row_id)) != expected_row_hash:
                    raise ArtifactChanged("existing frozen result does not match selection")
                return manifest
        if len(candidates) >= MAX_RESULT_SETS_PER_TASK:
            raise ArtifactUnavailable("task result-set limit reached")
        stage = Path(tempfile.mkdtemp(prefix=".capture-", dir=root))
        try:
            target = stage / "android.db"
            _snapshot(source, target)
            if source_revision(task) != expected_source_revision:
                raise ArtifactChanged("Android result changed while freezing")
            if raw_row_hash(read_raw_row(target, kind, row_id)) != expected_row_hash:
                raise ArtifactChanged("selected row changed while freezing")
            snapshot_sha = _hash(target)
            result_set_id = _result_id(task["id"], expected_source_revision, snapshot_sha)
            coverage = read_coverage(task)
            manifest = {
                "schema_version": 1, "source_type": "android_analyzer",
                "task_id": task["id"], "result_set_id": result_set_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "source_revision": expected_source_revision,
                "snapshot_sha256": snapshot_sha, "coverage": coverage,
                "warnings": coverage.get("warnings", []),
                "parser_name": "AndroidAnalyzer",
                "parser_version": (task.get("metadata") or {}).get("android_parser_version"),
                "source_identity_granularity": "derived_database_version",
            }
            manifest_file = stage / "manifest.json"
            manifest_file.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            (stage / "manifest.sha256").write_text(_hash(manifest_file) + "\n", encoding="ascii")
            published = root / result_set_id
            if published.exists():
                existing, _ = _load(task, result_set_id)
                return existing
            stage.rename(published)
            stage = None
            return manifest
        finally:
            if stage is not None and stage.exists():
                shutil.rmtree(stage)
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
