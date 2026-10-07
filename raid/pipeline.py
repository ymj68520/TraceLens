# SPDX-License-Identifier: AGPL-3.0-or-later
"""Optional existing C++ analysis on a private derived image, never a live Task."""
from __future__ import annotations

from pathlib import Path
import sqlite3
import subprocess

from .core import RaidError
from .export import verify_package, write_json
from .results import _file_hash


def analyze_package(package: Path, analyzer: Path, *, allow_partial=False, timeout=300):
    verified = verify_package(package, allow_partial=allow_partial)
    analyzer = analyzer.resolve(strict=True)
    work = package / "native-analysis"
    work.mkdir(mode=0o700)
    # Own config wins over workspace/production .env; no service or AI startup.
    (work / ".env").write_text(f"PROJECT_ROOT={work}\nDATA_DIR={work / 'data'}\n"
                               "TRACELENS_FIELD_AUTH=enabled\nFIELD_OUTBOUND_POLICY=disabled\nLLM_BASE_URL=\n")
    with (work / "stdout.private.log").open("x") as stdout, (work / "stderr.private.log").open("x") as stderr:
        result = subprocess.run([str(analyzer), str(package / "logical.img"), "--no-ai", "--report",
                                 "--db-dir", str(work / "databases")], cwd=work,
                                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, timeout=timeout)
    if result.returncode:
        write_json(work / "failure.json", {"status": "FAILED", "code": "NATIVE_ANALYSIS_FAILED"})
        raise RaidError("NATIVE_ANALYSIS_FAILED")
    files_db = work / "databases" / "logical_files.db"
    if not files_db.is_file(): raise RaidError("NATIVE_FILE_DATABASE_MISSING")
    with sqlite3.connect(f"file:{files_db}?mode=ro", uri=True) as db:
        file_count = db.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        categories = dict(db.execute("SELECT category,COUNT(*) FROM files GROUP BY category"))
        keyword_count = db.execute("SELECT COUNT(*) FROM files WHERE lower(name) LIKE ?", ("%.txt",)).fetchone()[0]
    reports = list((work / "databases").glob("*.md"))
    output = {"schema_version": 1, "status": "COMPLETE", "input_business_status": verified["business_status"],
              "file_count": file_count, "categories": categories, "txt_query_count": keyword_count,
              "analyzer_sha256": _file_hash(analyzer), "files_db_sha256": _file_hash(files_db),
              "readable_reports": [{"file": p.name, "sha256": _file_hash(p)} for p in reports],
              "ai": "DISABLED_FOR_THIS_ISOLATED_RUN", "production_task_created": False,
              "warnings": verified["warnings"]}
    write_json(work / "analysis_manifest.json", output)
    return output
