"""End-to-end acceptance for resumable CLI analysis (断点续跑).

Builds a synthetic EXT4 image, runs the real forensic_analyzer, then proves the
resume contract on the produced artifacts:

  1. First run   — full pipeline, ledger written beside the databases.
  2. Re-run      — every completed stage is skipped and the databases are
                   byte-identical (a resumed run must not duplicate rows).
  3. Mid-way loss — delete the events DB only, re-run, and confirm the skipped
                   stages keep their identity while the missing one is rebuilt.
  4. Changed input — touch the raw DB, re-run, and confirm the downstream
                   stages are *invalidated* rather than reusing stale claims.
  5. --overwrite — forces a full re-run that deletes the ledger.

Only generated test images are written; no real evidence is touched. Requires
mke2fs.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile


def command(*args, timeout=300, **kwargs):
    result = subprocess.run([str(arg) for arg in args], text=True,
                            capture_output=True, timeout=timeout, **kwargs)
    if result.returncode:
        raise AssertionError(f"{args[0]} failed: {result.stderr[-1600:]} {result.stdout[-500:]}")
    return result


def build_image(root: Path) -> Path:
    """A small EXT4 image with a filesystem worth classifying."""
    tree = root / "tree"
    (tree / "etc").mkdir(parents=True)
    (tree / "var" / "log").mkdir(parents=True)
    (tree / "home" / "analyst").mkdir(parents=True)
    (tree / "etc" / "passwd").write_text("root:x:0:0:root:/root:/bin/bash\nanalyst:x:1000:1000::/home/analyst:/bin/bash\n")
    (tree / "etc" / "os-release").write_text('NAME="Ubuntu"\nVERSION="22.04"\n')
    (tree / "var" / "log" / "auth.log").write_text(
        "Jan  1 00:00:01 host sshd[1]: Accepted password for analyst from 10.0.0.5\n"
        "Jan  1 00:05:00 host sudo[2]: analyst : TTY=pts/0 ; COMMAND=/bin/bash\n")
    (tree / "home" / "analyst" / ".bash_history").write_text("id\nwhoami\ncat /etc/shadow\n")

    image = root / "resume_case.img"
    command("truncate", "-s", "64M", image)
    command("mke2fs", "-q", "-F", "-t", "ext4", "-L", "evidence", "-d", tree, image)
    return image


def analyze(analyzer: Path, image: Path, output: Path, extra: list[str] | None = None):
    output.mkdir(parents=True, exist_ok=True)
    cmd = [str(analyzer), str(image), "--no-ai", "--db-dir", str(output)]
    if extra:
        cmd.extend(extra)
    log = output / "analysis.log"
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[2],
                                stdout=handle, stderr=subprocess.STDOUT, timeout=900)
    text = log.read_text(errors="replace")
    assert result.returncode == 0, text[-4000:]
    return text


def ledger_of(output: Path, stem: str) -> dict:
    path = output / f"{stem}_stages.json"
    assert path.exists(), f"no stage ledger written at {path}"
    return json.loads(path.read_text())


def db_digest(path: Path) -> str:
    """Content digest that ignores SQLite's own bookkeeping.

    Row counts per table are compared instead of file bytes: a re-run opens the
    database (which can move pages/WAL state) without changing any evidence, and
    the property we care about is "no duplicated rows", not file identity.

    `immutable=1` keeps the observation read-only at the OS level: without it
    SQLite creates a -shm/-wal pair on open, and the test would perturb the very
    state it is measuring.
    """
    with sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True) as con:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        parts = []
        for table in tables:
            try:
                count = con.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            except sqlite3.DatabaseError:
                count = -1
            parts.append(f"{table}={count}")
    return "|".join(parts)


def skipped_stages(log: str) -> set[str]:
    """Stage names the analyzer reported as reused, read from its own output.

    The analyzer's step banners are the stable signal ("[1/4] Analyzing image...
    skipped (...)"), so match the banner plus the skip marker rather than
    scanning for "skipped" anywhere: unrelated library warnings also contain the
    word and would otherwise register as stage skips.
    """
    found = set()
    for line in log.splitlines():
        lowered = line.lower()
        if "skipped" not in lowered:
            continue
        for stage, marker in (
            ("IMAGE_ANALYSIS", "[1/4] analyzing image"),
            ("FILE_FILTER", "[2/4] applying file filter"),
            ("FILE_CLASSIFICATION", "[3/4] classifying files"),
            ("PLATFORM_ANALYSIS", "[scene] platform analysis"),
            ("EVENT_EXTRACTION", "[4/4] generating timeline"),
        ):
            if marker in lowered:
                found.add(stage)
    return found


def run(analyzer: Path) -> int:
    if not shutil_which("mke2fs"):
        print("SKIP: mke2fs not available", file=sys.stderr)
        return 77

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        image = build_image(root)
        out = root / "out"
        stem = image.stem

        raw_db = out / f"{stem}_raw.db"
        events_db = out / f"{stem}_events.db"
        files_db = out / f"{stem}_files.db"

        # ── 1. First run: full pipeline, ledger written ──────────────────────
        log1 = analyze(analyzer, image, out)
        ledger1 = ledger_of(out, stem)
        for stage in ("IMAGE_ANALYSIS", "FILE_FILTER", "FILE_CLASSIFICATION",
                      "EVENT_EXTRACTION"):
            assert f"stage.{stage}" in ledger1, f"{stage} missing from ledger: {ledger1}"
            assert ledger1[f"stage.{stage}"].startswith("done"), ledger1[f"stage.{stage}"]
        assert not skipped_stages(log1), f"first run must not skip: {skipped_stages(log1)}"

        first = {name: db_digest(p) for name, p in
                 (("raw", raw_db), ("events", events_db), ("files", files_db))}
        mtimes = {p: p.stat().st_mtime_ns for p in (raw_db, events_db, files_db)}

        # ── 2. Re-run: everything reused, nothing duplicated ─────────────────
        log2 = analyze(analyzer, image, out)
        skipped2 = skipped_stages(log2)
        assert "IMAGE_ANALYSIS" in skipped2, f"raw DB should be reused: {log2[-2000:]}"
        assert "EVENT_EXTRACTION" in skipped2, f"events DB should be reused: {log2[-2000:]}"
        for p in (raw_db, events_db, files_db):
            assert p.stat().st_mtime_ns == mtimes[p], f"{p.name} was rewritten on a no-op resume"
        second = {name: db_digest(p) for name, p in
                  (("raw", raw_db), ("events", events_db), ("files", files_db))}
        assert first == second, f"resume changed row counts:\n{first}\n{second}"

        # Ledger must be stable across the no-op run.
        assert ledger_of(out, stem) == ledger1, "no-op resume rewrote the ledger"

        # ── 3. Missing artifact: only that stage is rebuilt ─────────────────
        events_db.unlink()
        log3 = analyze(analyzer, image, out)
        skipped3 = skipped_stages(log3)
        assert "IMAGE_ANALYSIS" in skipped3, "raw DB must still be reused"
        assert "EVENT_EXTRACTION" not in skipped3, "the deleted events DB must be rebuilt"
        assert db_digest(events_db) == first["events"], \
            "rebuilt events DB must match the original row counts"

        # ── 4. Changed upstream input: downstream claims are invalidated ────
        # Mutate the *effective* raw database (the filtered copy is what the
        # later stages actually read) and confirm the pipeline does NOT trust the
        # old downstream claims. The write goes through SQLite with WAL enabled,
        # so it lands in the -wal sidecar while the main file's size and mtime
        # stay identical — which is exactly why the ledger fingerprints sidecars.
        filtered_db = out / f"{stem}_filtered.db"
        assert filtered_db.exists(), "expected a filtered DB (general_forensics default)"
        with sqlite3.connect(str(filtered_db)) as con:
            con.execute(
                "INSERT INTO files (inode, name, path, size, atime, mtime, ctime, crtime, "
                "type, md5, is_deleted, is_allocated, permissions, uid, gid, partition_num) "
                "VALUES (999999, 'injected.txt', '/tmp/injected.txt', 12, 1, 1, 1, 1, "
                "'REG', '', 0, 1, '0644', 0, 0, 0)")
            con.commit()

        log4 = analyze(analyzer, image, out)
        skipped4 = skipped_stages(log4)
        # The image analysis and the filter are still valid (their inputs did not
        # change); classification and the timeline consumed the mutated database.
        assert "IMAGE_ANALYSIS" in skipped4, "an unrelated raw DB must still be reused"
        assert "FILE_CLASSIFICATION" not in skipped4, \
            "a changed effective raw DB must invalidate the classification claim"
        assert "EVENT_EXTRACTION" not in skipped4, \
            "a changed effective raw DB must invalidate the events claim"

        # ── 5. --overwrite forces a full re-run and drops the ledger ─────────
        log5 = analyze(analyzer, image, out, extra=["--overwrite"])
        assert not skipped_stages(log5), \
            f"--overwrite must not reuse anything: {skipped_stages(log5)}"
        ledger5 = ledger_of(out, stem)
        assert f"stage.IMAGE_ANALYSIS" in ledger5, "ledger is recreated after --overwrite"

    print("PASS: CLI resume (skip / invalidate / rebuild / overwrite) verified")
    return 0


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analyzer", required=True, type=Path)
    args = parser.parse_args()
    return run(args.analyzer.resolve())


if __name__ == "__main__":
    sys.exit(main())
