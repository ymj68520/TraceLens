#!/usr/bin/env python3
"""Prepare a current v9 COPY of one operator-selected v7 Task store.

The historical command name remains compatible; the manifest states the
actual prepared schema version. The source v7 store is never changed.

The source investigation.db is opened read-only and never migrated or
replaced. Run only after stopping writes; verify the resulting copy and keep
the old file for rollback. This tool does not perform a production cutover.
"""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_service"))
from httpserver.services.android_field_package import _snapshot
from httpserver.services.investigation.paths import investigation_db_path_for_task
from httpserver.services.investigation.repository import InvestigationRepository


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def prepare(task_record: Path, output_copy: Path) -> dict:
    if task_record.is_symlink() or not task_record.is_file():
        raise ValueError("task record must be a regular local file")
    task = json.loads(task_record.read_text(encoding="utf-8"))
    task_id = task.get("id")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,128}", task_id):
        raise ValueError("invalid task ID in record")
    source = investigation_db_path_for_task(task)
    output_copy = output_copy.absolute()
    if (source.is_symlink() or not source.is_file() or output_copy.exists()
            or output_copy.parent.is_symlink() or not output_copy.parent.is_dir()
            or output_copy.resolve(strict=False) == source.resolve()):
        raise ValueError("source or output copy is unsafe")
    with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as con:
        con.execute("PRAGMA query_only=ON")
        if con.execute("PRAGMA user_version").fetchone()[0] != 7:
            raise ValueError("source is not a v7 investigation store")
    # A live writer can still race the backup. Maintenance must stop writers;
    # the manifest below records the source bundle's before/after digests.
    bundle = [source, Path(str(source) + "-wal"), Path(str(source) + "-journal")]
    def bundle_digests():
        if any(part.is_symlink() for part in bundle):
            raise ValueError("source database bundle contains a symlink")
        return {part.name: sha256(part) for part in bundle if part.is_file()}
    before = bundle_digests()
    stage = Path(tempfile.mkdtemp(prefix=".investigation-v8-incomplete-", dir=output_copy.parent))
    candidate = stage / "investigation.db"
    try:
        _snapshot(source, candidate)
        if before != bundle_digests():
            raise ValueError("source database bundle changed during backup")
        InvestigationRepository(candidate, task_id, allow_v7_upgrade=True)
        with sqlite3.connect(candidate) as con:
            if con.execute("PRAGMA user_version").fetchone()[0] != 9:
                raise ValueError("prepared copy has wrong schema")
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("prepared copy failed integrity check")
            if con.execute("PRAGMA foreign_key_check").fetchone():
                raise ValueError("prepared copy failed foreign key check")
        result = {"task_id": task_id, "source_schema": 7, "prepared_schema": 9,
                  "source_bundle_sha256": before, "prepared_copy_sha256": sha256(candidate),
                  "cutover_performed": False}
        os.link(candidate, output_copy)  # atomic no-overwrite publication
        candidate.unlink()
        backup=candidate.with_name(candidate.name+".before-v9.sqlite")
        if backup.exists():backup.unlink()
        stage.rmdir()
        return result
    except Exception:
        (stage / "INCOMPLETE").write_text("Do not use as a migrated database\n", encoding="utf-8")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task-record", type=Path, required=True)
    parser.add_argument("--output-copy", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.task_record, args.output_copy), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
