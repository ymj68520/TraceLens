#!/usr/bin/env python3
"""OPPO (ThunderForensic 雷电手机快取) backup CLI end-to-end tests.

Builds a synthetic ThunderForensic tar mirroring the real extraction layout —
ThunderForensic.json manifest, PhoneData/*.json artifacts, LogData payloads —
including the obsolescent base-64 gid header quirk the real writer emits, then
asserts the analyzer parses the artifacts into the vendor-neutral mobile
backup tables for both the tar and the project-directory source forms.
"""

import argparse
import json
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path


def create_thunderforensic_tar(target: Path) -> Path:
    manifest = {
        "Software": {"Name": "ThunderForensic", "DisplayName": "雷电手机快取",
                     "Version": "4.9.3.32581", "ExtractType": ""},
        "Device": {"Name": "OPPO", "Os": "Android", "OsVersion": "10", "Manufactor": "OPPO",
                   "Brand": "OPPO", "Model": "PBEM00", "Imei": "865040046649992",
                   "VenderVersion": "V7.1"},
        "TaskInfo": {"TaskName": "androidmobileextra", "DisplayName": "数据提取",
                     "CreateAt": "2026-10-25T10:33:23.434691+08:00",
                     "CompleteAt": "2026-10-25T10:46:06.2548576+08:00"},
    }
    members = [
        ("PhoneData/deviceinfo.json", [
            {"Key": "name", "Name": "名称", "Value": "OPPO R17"},
            {"Key": "osversion", "Name": "操作系统版本", "Value": "10"},
            {"Key": "androidid", "Name": "AndroidId", "Value": "7d683cc1a6a9ee42"},
            {"Key": "imei1", "Name": "IMEI1", "Value": "865040046649992"},
        ]),
        ("PhoneData/imei.json", [
            {"Key": "imei1", "Name": "IMEI1", "Value": "865040046649992"},
            {"Key": "imei2", "Name": "IMEI2", "Value": "865040046649984"},
        ]),
        ("PhoneData/application.json", [
            {"AllowBackup": 1, "ApkPath": "/data/app/foo.apk", "ApkSize": 4096,
             "AppName": "测试应用", "Delete": 1, "InstallTime": "2022-11-01T12:06:22.000Z",
             "LastUseTime": "2025-03-24T02:41:25.000Z", "PackageName": "com.example.app",
             "SystemFlag": 1, "VersionCode": "12", "VersionName": "1.2"},
        ]),
        ("PhoneData/app_traffic.json", [
            {"PackageName": "com.example.app", "MobileTrafficAll": "10",
             "WiFiTrafficAll": "1727129"},
        ]),
        ("PhoneData/appusagedetail.json", {"eventResultList": [
            {"appName": "测试应用", "packageName": "com.example.app",
             "startTime": "2025-09-19T12:16:08.584Z", "endTime": "2025-09-19T12:16:10.157Z",
             "useDuration": "1"},
        ]}),
        ("PhoneData/wifi.json", [
            {"Ssid": "\"Pixel_9577bn\"", "KeyType": "WPA_PSK",
             "LastConnected": "04-08 15:02:05.182"},
        ]),
        ("PhoneData/image_extractor.json", [
            {"BucketName": "Camera", "CreateTime": "2025-03-26T01:52:55.000Z",
             "MediaType": "image", "MobilePath": "/storage/emulated/0/DCIM/Camera/IMG.jpg",
             "Name": "IMG.jpg", "Size": 3069933},
        ]),
        ("PhoneData/contacts.json", []),
        ("PhoneData/smss.json", []),
        # ThunderForensic writes extractor error strings into .json members.
        ("PhoneData/siminfo.json", None, b"java.lang.SecurityException: No phone privilege permission"),
        ("LogData/usagestats.log", None, b"usage-events"),
        ("sdcard/DCIM/Camera/IMG.jpg", None, b"\xff\xd8fakejpeg"),
        ("ThunderForensic.json", None,
         json.dumps(manifest, ensure_ascii=False).encode("utf-8")),
    ]

    raw = BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for entry in members:
            name = entry[0]
            if entry[1] is not None:
                payload = (json.dumps(entry[1], ensure_ascii=False).encode("utf-8")
                           if not isinstance(entry[1], bytes) else entry[1])
            else:
                payload = entry[2]
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            archive.addfile(info, BytesIO(payload))
    data = bytearray(raw.getvalue())

    # Mirror the real writer's obsolescent gid field ("-6667000", non-octal)
    # on later members, fixing the header checksum afterwards, so the
    # extractor is exercised against the quirk that breaks strict readers.
    offset = 0
    count = 0
    while offset + 512 <= len(data):
        header = data[offset:offset + 512]
        if header == b"\0" * 512:
            break
        size_field = bytes(header[124:136]).rstrip(b"\0 ")
        if not size_field or any(c not in b"01234567" for c in size_field):
            break
        size = int(size_field, 8)
        count += 1
        if count > 1:
            data[offset + 116:offset + 124] = b"-6667000"
            checksum = sum(data[offset:offset + 148]) + 32 * 8 + sum(data[offset + 156:offset + 512])
            data[offset + 148:offset + 156] = f"{checksum:06o}\0 ".encode("ascii")
        offset += 512 + ((size + 511) // 512) * 512
    target.write_bytes(bytes(data))
    return target


def create_project_dir(root: Path) -> Path:
    project = root / "20261025OPPO"
    tar_dir = project / "filesystem" / "1" / "tar"
    tar_dir.mkdir(parents=True)
    create_thunderforensic_tar(tar_dir / "20261025103239YGBYRC-1792895603.tar")
    return project


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*command, "--no-ai"], capture_output=True, text=True,
                          check=False, timeout=120)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_artifacts(database: Path, context: str) -> None:
    assert_true(database.exists(), f"{context}: artifact database was not created")
    with sqlite3.connect(database) as connection:
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert_true("mobile_backup_manifest" in tables, f"{context}: manifest table missing")
        manifest = connection.execute(
            "SELECT platform, device, backup_version, module_count, adapter_version "
            "FROM mobile_backup_manifest").fetchone()
        assert_true(manifest == ("Android", "OPPO PBEM00", "4.9.3.32581", 10,
                                 "oppo-thunderforensic-v1"),
                    f"{context}: unexpected manifest row: {manifest}")
        kinds = dict(connection.execute(
            "SELECT kind, COUNT(*) FROM mobile_artifacts GROUP BY kind"))
        assert_true(kinds.get("application") == 1, f"{context}: application rows: {kinds}")
        assert_true(kinds.get("wifi") == 1, f"{context}: wifi rows: {kinds}")
        assert_true(kinds.get("media") == 1, f"{context}: media rows: {kinds}")
        assert_true(kinds.get("app_usage_session") == 1,
                    f"{context}: usage rows: {kinds}")
        assert_true(kinds.get("device_log") == 1, f"{context}: log rows: {kinds}")
        installed = connection.execute(
            "SELECT package_name, display_name FROM installed_apps "
            "WHERE package_name = 'com.example.app'").fetchone()
        assert_true(installed == ("com.example.app", "测试应用"),
                    f"{context}: missing installed app: {installed}")
        wifi = connection.execute("SELECT ssid FROM wifi_networks").fetchall()
        assert_true(wifi == [("Pixel_9577bn",)], f"{context}: wifi rows: {wifi}")
        identifiers = dict(connection.execute(
            "SELECT identifier_type, value FROM device_identifiers"))
        assert_true(identifiers.get("androidid") == "7d683cc1a6a9ee42",
                    f"{context}: android id missing: {identifiers}")
        assert_true(identifiers.get("imei1") == "865040046649992",
                    f"{context}: imei missing: {identifiers}")
        coverage = {row[0]: (row[1], row[2]) for row in connection.execute(
            "SELECT source_path, status, detail FROM android_source_coverage "
            "WHERE source_path LIKE 'PhoneData/%'")}
        assert_true(coverage.get("PhoneData/application.json", ("", ""))[0] == "parsed",
                    f"{context}: application coverage: {coverage}")
        assert_true(coverage.get("PhoneData/contacts.json", ("", ""))[0] == "empty",
                    f"{context}: empty-member coverage: {coverage}")
        assert_true("SecurityException" in coverage.get("PhoneData/siminfo.json", ("", ""))[1],
                    f"{context}: extractor error not surfaced: {coverage}")
        session = connection.execute(
            "SELECT timestamp_seconds FROM mobile_artifacts "
            "WHERE kind = 'app_usage_session'").fetchone()
        assert_true(session is not None and session[0] == 1758284168,
                    f"{context}: usage session timestamp: {session}")


def verify_tar_route(analyzer: Path, root: Path) -> None:
    tar_path = create_thunderforensic_tar(root / "20261025OPPO.tar")
    output = root / "out-tar"
    result = run([
        str(analyzer), str(tar_path), "--android-analyze",
        "--android-source", "oppo-backup", "--db-dir", str(output),
    ])
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"tar analysis failed: {combined}")
    assert_true("Using The Sleuth Kit" not in combined, "OPPO source entered the TSK pipeline")
    verify_artifacts(output / "20261025OPPO_files.db", "tar")


def verify_dir_route_and_promotion(analyzer: Path, root: Path) -> None:
    project = create_project_dir(root)
    output = root / "out-dir"
    result = run([
        str(analyzer), str(project), "--android-analyze",
        "--android-source", "dir", "--db-dir", str(output),
    ])
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"dir analysis failed: {combined}")
    assert_true("auto-selecting oppo-backup mode" in combined,
                f"dir source was not promoted: {combined}")
    verify_artifacts(output / "20261025OPPO_files.db", "dir")


def verify_invalid_source_rejected(analyzer: Path, root: Path) -> None:
    not_oppo = root / "not-oppo"
    not_oppo.mkdir()
    result = run([
        str(analyzer), str(not_oppo), "--android-analyze",
        "--android-source", "oppo-backup", "--db-dir", str(root / "out-bad"),
    ])
    combined = result.stdout + result.stderr
    assert_true(result.returncode != 0, f"non-OPPO source accepted: {combined}")
    assert_true("INVALID_OPPO_BACKUP" in combined, f"wrong failure code: {combined}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", required=True)
    args = parser.parse_args()
    analyzer = Path(args.analyzer).resolve()

    with tempfile.TemporaryDirectory(prefix="oppo-cli-") as temp:
        root = Path(temp)
        verify_tar_route(analyzer, root)
        verify_dir_route_and_promotion(analyzer, root)
        verify_invalid_source_rejected(analyzer, root)
    print("OPPO backup CLI end-to-end tests passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        sys.exit(1)
