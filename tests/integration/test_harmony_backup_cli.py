"""Offline end-to-end acceptance through the existing forensic CLI.

Run with --analyzer /path/to/forensic_analyzer. Optional --source/--output
accept external decrypted evidence; no evidence or personal data is committed.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tarfile
import tempfile


def create_fixture(root: Path) -> None:
    package = "com.huawei.hmos.calendardata"
    app = root / "files" / "BASIC" / package
    app.mkdir(parents=True)
    (root / ".info.json").write_text(json.dumps({
        "BackupFileHeaderInfo": {"deviceModel": "synthetic", "backupTime": 1700000000000},
        "BackupFileVersionInfo": {"versionName": "test"},
        "BackupFileModuleInfo": [{"moduleName": package, "appName": "Calendar", "appIndex": 0}],
    }), encoding="utf-8")
    with tempfile.TemporaryDirectory() as temporary:
        database = Path(temporary) / "calendar.db"
        con = sqlite3.connect(database)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("CREATE TABLE Events(_id INTEGER PRIMARY KEY,title TEXT,dtstart INTEGER)")
        con.executemany("INSERT INTO Events VALUES(?,?,?)", [(1, "alpha", 1700000000000), (2, "beta", 1700000001000)])
        con.commit()
        primary = database.read_bytes()
        wal = Path(str(database) + "-wal").read_bytes()
        con.close()
    original = "/data/storage/el2/database/entry/rdb/calendardata.db"
    archive = app / "part.0.tarx"
    with tarfile.open(archive, "w", format=tarfile.GNU_FORMAT) as tar:
        directory = tarfile.TarInfo("/data/storage/el2/database")
        directory.type = tarfile.DIRTYPE
        directory.size = 3440  # observed Harmony directory header; no data payload
        tar.addfile(directory)
        for name, data in [(original, primary), ("/data/storage/el2/base/files/" + "long-" * 35 + ".txt", b"payload")]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.mtime = 1700000000
            tar.addfile(member, io.BytesIO(data))
    (app / "wal_blobx").write_bytes(wal)
    (app / "manage.jsonx").write_text(json.dumps([
        {"fileName": "part.0.tar", "isBigFile": False,
         "information": {"path": "/data/storage/el2/base/.backup/part.0.tar", "stat": {"st_size": archive.stat().st_size}}},
        {"fileName": "wal_blob", "isBigFile": True,
         "information": {"path": original + "-wal", "stat": {"st_size": len(wal)}}},
    ]), encoding="utf-8")


def analyze(binary: Path, source: Path, output: Path, mode="harmony-backup") -> dict:
    output.mkdir(parents=True, exist_ok=True)
    command = [str(binary), str(source), "--android-analyze", "--android-source", mode,
               "--no-ai", "--db-dir", str(output)]
    with (output / "analysis.log").open("w", encoding="utf-8") as log:
        result = subprocess.run(command, cwd=Path(__file__).resolve().parents[2], stdout=log, stderr=subprocess.STDOUT, timeout=1200)
    assert result.returncode == 0, (output / "analysis.log").read_text(errors="replace")[-5000:]
    prefix = source.stem
    counts = {}
    with sqlite3.connect(output / f"{prefix}_files.db") as con:
        counts["classified_files"] = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        counts["artifacts"] = dict(con.execute("SELECT kind,COUNT(*) FROM mobile_artifacts GROUP BY kind"))
        assert con.execute("SELECT COUNT(*) FROM harmony_source_files").fetchone()[0] > 0
    with sqlite3.connect(output / f"{prefix}_raw.db") as con:
        counts["indexed_files"] = con.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    with sqlite3.connect(output / f"{prefix}_events.db") as con:
        counts["mobile_events"] = con.execute("SELECT COUNT(*) FROM events WHERE event_source='HARMONY_BACKUP'").fetchone()[0]
    assert counts["classified_files"] and counts["indexed_files"]
    (output / "acceptance_counts.json").write_text(json.dumps(counts, ensure_ascii=False, indent=2), encoding="utf-8")
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    binary = args.analyzer.resolve()
    if args.source:
        if not args.output:
            parser.error("external evidence requires an explicit separate --output directory")
        source, output = args.source.resolve(), args.output.resolve()
        if output == source or source in output.parents:
            parser.error("output must be outside evidence")
        print(json.dumps(analyze(binary, source, output), ensure_ascii=False))
        return
    with tempfile.TemporaryDirectory(prefix="harmony-cli-") as temporary:
        root = Path(temporary)
        source = root / "backup"
        create_fixture(source)
        before = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in source.rglob("*") if p.is_file()}
        for mode in ("harmony-backup", "dir"):
            output = root / mode
            counts = analyze(binary, source, output, mode)
            assert counts["artifacts"] == {"calendar": 2}, counts
            assert counts["mobile_events"] == 2, counts
            extracted = output / "extracted"
            run = subprocess.run([str(binary), str(source), "--database", str(output / "backup_raw.db"),
                                  "--extract-file", "calendardata.db", "--output-dir", str(extracted)],
                                 cwd=output, capture_output=True, text=True, timeout=60)
            assert run.returncode == 0, run.stdout + run.stderr
            assert any(extracted.rglob("calendardata.db")), run.stdout
        after = {str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in source.rglob("*") if p.is_file()}
        assert before == after, "evidence content changed"
        invalid = subprocess.run([str(binary), str(source), "--android-source", "harmony-backup", "--no-ai",
                                  "--db-dir", str(source / "analysis")], capture_output=True, text=True, timeout=30)
        assert invalid.returncode != 0 and not (source / "analysis").exists()
        print("PASS: standard classification, timeline, extraction, WAL, auto-detection and evidence preservation")


if __name__ == "__main__":
    main()
