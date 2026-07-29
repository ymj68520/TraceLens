#!/usr/bin/env python3

import argparse
import os
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import zlib
from io import BytesIO
from pathlib import Path


def create_backup(root: Path, compressed: bool = False) -> Path:
    backup = root / "backup"
    backup.mkdir(parents=True)

    payload = BytesIO()
    with tarfile.open(fileobj=payload, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        data = b"not-a-sqlite-db"
        info = tarfile.TarInfo("apps/com.foo/db/x.db")
        info.size = len(data)
        archive.addfile(info, BytesIO(data))

    tar_bytes = payload.getvalue()
    compression = b"1" if compressed else b"0"
    body = zlib.compress(tar_bytes) if compressed else tar_bytes
    (backup / "Foo(com.foo).bak").write_bytes(
        b"ANDROID BACKUP\n5\n" + compression + b"\nnone\n" + body
    )
    (backup / "descript.xml").write_text(
        '<?xml version="1.0"?><MIUI-backup>'
        '<device>task8-device</device><miuiVersion>V12</miuiVersion>'
        '<date>1</date><size>1</size><packages><package>'
        '<packageName>com.foo</packageName><bakFile>Foo(com.foo).bak</bakFile>'
        '<bakType>1</bakType><pkgSize>1</pkgSize><sdSize>0</sdSize>'
        '<state>1</state><error>0</error></package></packages></MIUI-backup>',
        encoding="utf-8",
    )
    return backup


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_miui_route(analyzer: Path, root: Path) -> None:
    backup = create_backup(root)
    output = root / "out"
    secret = "TASK8_E2E_SECRET_SENTINEL"
    result = run([
        str(analyzer), str(backup), "--android-analyze",
        "--android-source", "miui-backup",
        "--backup-password", secret,
        "--db-dir", str(output),
    ])

    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"MIUI analysis failed ({result.returncode}): {combined}")
    assert_true(secret not in combined, "backup password appeared in captured output")
    assert_true("Using The Sleuth Kit" not in combined, "MIUI source entered the TSK pipeline")

    database = output / "backup_files.db"
    assert_true(database.exists(), "MIUI artifact database was not created")
    with sqlite3.connect(database) as connection:
        manifest = connection.execute(
            "SELECT device, miui_version FROM miui_backup_manifest"
        ).fetchone()
        installed = connection.execute(
            "SELECT package_name FROM installed_apps WHERE package_name = 'com.foo'"
        ).fetchone()
        inventory = connection.execute(
            "SELECT package_name, db_path, open_status FROM app_db_inventory "
            "WHERE package_name = 'com.foo'"
        ).fetchone()

    assert_true(manifest == ("task8-device", "V12"), f"unexpected manifest row: {manifest}")
    assert_true(installed == ("com.foo",), f"missing installed-app row: {installed}")
    assert_true(
        inventory == ("com.foo", "apps/com.foo/db/x.db", "parse_error"),
        f"unexpected inventory row: {inventory}",
    )


def verify_malformed_input(analyzer: Path) -> None:
    secret = "TASK8_MALFORMED_SECRET"
    result = run([
        str(analyzer), "/evidence/miui", "--android-analyze",
        "--android-source", "--backup-password", secret,
    ])
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 2, f"malformed CLI returned {result.returncode}: {combined}")
    assert_true("Missing value for --android-source" in result.stderr,
                f"missing parser error: {result.stderr}")
    assert_true(secret not in combined, "malformed CLI leaked the following secret argument")
    assert_true("Forensic Image Analyzer" not in result.stdout,
                "malformed CLI reached analysis before rejection")

    unknown = run([
        str(analyzer), "/evidence/miui", "--android-analyze",
        "--android-source", "vendor-backup",
    ])
    assert_true(unknown.returncode == 2, f"unknown source returned {unknown.returncode}")
    assert_true("Invalid --android-source" in unknown.stderr,
                f"unknown source was not rejected by parser: {unknown.stderr}")


def verify_secure_password_input(analyzer: Path, root: Path) -> None:
    backup = create_backup(root / "secure")
    output = root / "secure-out"
    secret = "MIUI_SECURE_INPUT_SENTINEL"
    result = subprocess.run([
        str(analyzer), str(backup), "--android-analyze",
        "--android-source", "miui-backup",
        "--backup-password-stdin", "--db-dir", str(output),
    ], input=secret + "\n", capture_output=True, text=True, check=False)
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"secure password input failed: {combined}")
    assert_true(secret not in combined, "secure backup password appeared in output")
    assert_true((output / "backup_files.db").exists(), "secure input run produced no database")


def verify_tmpdir_isolation(analyzer: Path, root: Path) -> None:
    backup = create_backup(root / "tmpdir", compressed=True)
    hostile_tmp = backup / "hostile-tmp"
    hostile_tmp.mkdir()
    output = root / "tmpdir-out"
    environment = os.environ.copy()
    environment["TMPDIR"] = str(hostile_tmp)
    result = subprocess.run([
        str(analyzer), str(backup), "--android-analyze",
        "--android-source", "miui-backup", "--db-dir", str(output),
    ], capture_output=True, text=True, check=False, env=environment)
    assert_true(result.returncode == 0, f"TMPDIR isolation run failed: {result.stdout}{result.stderr}")
    assert_true(not any(hostile_tmp.iterdir()), "analyzer created internal temporary files under evidence")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", required=True, type=Path)
    args = parser.parse_args()

    analyzer = args.analyzer.resolve()
    assert_true(analyzer.is_file(), f"analyzer binary not found: {analyzer}")
    with tempfile.TemporaryDirectory(prefix="tracelens_miui_cli_") as temp:
        root = Path(temp)
        verify_miui_route(analyzer, root)
        verify_secure_password_input(analyzer, root)
        verify_tmpdir_isolation(analyzer, root)
        verify_malformed_input(analyzer)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AssertionError as error:
        print(f"FAIL: {error}", file=sys.stderr)
        sys.exit(1)
