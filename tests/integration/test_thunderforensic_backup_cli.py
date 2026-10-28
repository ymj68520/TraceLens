#!/usr/bin/env python3
"""Generic ThunderForensic (雷电手机快取) CLI end-to-end tests.

Builds three synthetic vendor extractions that reproduce the layouts observed
in the real OPPO / OnePlus / vivo samples:

  * plain ustar with a non-octal gid ("-6667000") on every member, including
    the first one (vivo), which libarchive rejects outright;
  * GNU long-name members for app-data paths;
  * PhoneData/*.json artifacts, LogData logs, sdcard payloads;
  * per-package data trees (<package>.tar/, <package>.ab/);
  * vivo root envelopes: chunk-framed wifi.xml, chunk-framed encrypted
    note.zip / encryptNote.zip, .backup marker, empty encrypted contacts/SMS;
  * duplicate member names (vivo) and the manifest placed last.

The analyzer must parse all three through one generic adapter, preserve the
legacy oppo-backup source alias, auto-promote a project directory selected as
"dir", and report coverage/provenance truthfully.
"""

import argparse
import html
import io
import json
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

USAGE_TIME = "2025-09-19T12:16:08.584Z"
USAGE_EPOCH = 1758284168


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def _frame_blob(payload: bytes, chunk_size: int = 40960) -> bytes:
    """ThunderForensic's [uint32_be length][payload] envelope + zero terminator."""
    out = bytearray()
    for offset in range(0, len(payload), chunk_size):
        chunk = payload[offset:offset + chunk_size]
        out += len(chunk).to_bytes(4, "big")
        out += chunk
    out += (0).to_bytes(4, "big")
    return bytes(out)


def _encrypted_zip(entries: dict[str, bytes]) -> bytes:
    """A stored ZIP whose entries carry the strong-encryption flag (0x800)."""
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w", zipfile.ZIP_STORED) as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    data = bytearray(raw.getvalue())
    position = 0
    while True:
        position = data.find(b"PK\x01\x02", position)
        if position == -1:
            break
        flags = int.from_bytes(data[position + 8:position + 10], "little")
        data[position + 8:position + 10] = (flags | 0x0800).to_bytes(2, "little")
        position += 4
    position = 0
    while True:
        position = data.find(b"PK\x03\x04", position)
        if position == -1:
            break
        flags = int.from_bytes(data[position + 6:position + 8], "little")
        data[position + 6:position + 8] = (flags | 0x0800).to_bytes(2, "little")
        position += 4
    return bytes(data)


def _wifi_xml(networks: list[dict]) -> bytes:
    payload = html.escape(json.dumps(networks, ensure_ascii=False), quote=True)
    return (
        "<?xml version='1.0' encoding='utf-8' standalone='yes' ?>\n"
        "<map>\n"
        f'    <string name="wifi_saved_network">{payload}</string>\n'
        "    <int name=\"wifi_scan_always_enabled\" value=\"1\" />\n"
        "</map>\n"
    ).encode("utf-8")


VENDOR = {
    "OPPO": {
        "brand": "OPPO", "model": "PBEM00", "vendor": "V7.1", "android": "10",
        "contact": {"Name": "张三", "Phone": "13800000001"},
        "call": {"Number": "13800000002", "Date": "2025-09-19T12:00:00.000Z",
                 "Duration": 12, "Type": "outgoing"},
        "sms": {"Address": "13800000003", "Body": "hello-oppo",
                "Date": "2025-09-19T12:01:00.000Z", "Type": "inbox"},
        "wifi": [{"Ssid": "\"TestNet\"", "KeyType": "WPA_PSK",
                  "LastConnected": "04-08 15:02:05.182"}],
        "siminfo": b"java.lang.SecurityException: No phone privilege permission",
        "app_container": None,
        "root_envelopes": False,
    },
    "OnePlus": {
        "brand": "OnePlus", "model": "GM1910", "vendor": "", "android": "10",
        "contact": {"Name": "李四", "PhoneNumber": "13900000001"},
        "call": {"PhoneNumber": "13900000002", "Time": "2025-09-19T12:00:00.000Z",
                 "Duration": 7, "Type": "incoming"},
        "sms": {"Address": "13900000003", "Body": "hello-oneplus",
                "Date": "2025-09-19T12:01:00.000Z", "Type": "inbox"},
        "wifi": [{"Ssid": "\"OnePlusNet\"", "KeyType": "WPA_PSK",
                  "LastConnected": ""}],
        "siminfo": b"java.lang.SecurityException: No phone privilege permission",
        "app_container": "com.example.oneplus.tar",
        "root_envelopes": False,
    },
    "VIVO": {
        "brand": "vivo", "model": "V1824BA", "vendor": "OriginOS 1.0", "android": "11",
        "contact": {"Name": "王五", "PhoneNumber": "+8613700000001"},
        "call": {"PhoneNumber": "13700000002", "Time": "2025-09-19T12:00:00.000Z",
                 "Duration": 3, "Type": "outgoing"},
        "sms": {"Address": "13700000003", "Body": "hello-vivo",
                "Date": "2025-09-19T12:01:00.000Z", "Type": "inbox"},
        "wifi": None,
        "siminfo": [{"Iccid": "898600100120f0005391", "Imsi": "460001234567890",
                     "PhoneNumber": "+8613700000001", "CarrierName": "中国移动"}],
        "app_container": "com.example.vivo.ab",
        "root_envelopes": True,
    },
}


def _phone_data(vendor: str) -> list[tuple[str, bytes]]:
    info = VENDOR[vendor]
    device = [
        {"Key": "name", "Name": "名称", "Value": f"{info['brand']} test"},
        {"Key": "os", "Name": "操作系统", "Value": "android"},
        {"Key": "osversion", "Name": "操作系统版本", "Value": info["android"]},
        {"Key": "manufactor", "Name": "厂商", "Value": info["brand"]},
        {"Key": "brand", "Name": "品牌", "Value": info["brand"]},
        {"Key": "model", "Name": "型号", "Value": info["model"]},
        {"Key": "androidid", "Name": "AndroidId", "Value": "deadbeefcafebabe"},
    ]
    imei = [
        {"Key": "imei1", "Name": "IMEI1", "Value": "860000000000001"},
        {"Key": "imei2", "Name": "IMEI2", "Value": "860000000000002"},
        {"Key": "macaddress", "Name": "WiFi地址", "Value": "AA:BB:CC:DD:EE:FF"},
    ]
    applications = [
        {"AllowBackup": 1, "ApkPath": "/data/app/foo.apk", "ApkSize": 4096,
         "AppName": "测试应用", "Delete": 1, "InstallTime": "2022-11-01T12:06:22.000Z",
         "LastUseTime": "2025-03-24T02:41:25.000Z", "PackageName": "com.example.app",
         "SystemFlag": 1, "VersionCode": "12", "VersionName": "1.2"},
        {"AllowBackup": 0, "ApkSize": 1024, "AppName": "第二个应用", "Delete": 1,
         "InstallTime": "2023-01-01T00:00:00.000Z", "PackageName": "com.example.two",
         "SystemFlag": 0, "VersionCode": "2", "VersionName": "2.0"},
    ]
    documents = {
        "PhoneData/deviceinfo.json": _json_bytes(device),
        "PhoneData/imei.json": _json_bytes(imei),
        "PhoneData/application.json": _json_bytes(applications),
        "PhoneData/contacts.json": _json_bytes([info["contact"]]),
        "PhoneData/calllogs.json": _json_bytes([info["call"]]),
        "PhoneData/smss.json": _json_bytes([info["sms"]]),
        "PhoneData/mmss.json": b"[]",
        "PhoneData/siminfo.json": (info["siminfo"] if isinstance(info["siminfo"], bytes)
                                   else _json_bytes(info["siminfo"])),
        "PhoneData/simstate.json": b"[]",
        "PhoneData/calendar.json": b"[]",
        "PhoneData/bluetooth.json": _json_bytes(
            [{"Mac": "C4:E3:9F:DF:4F:F6", "Name": "peer", "State": "paired"}]),
        "PhoneData/image_extractor.json": _json_bytes([
            {"BucketName": "Camera", "CreateTime": "2025-03-26T01:52:55.000Z",
             "MediaType": "image",
             "MobilePath": "/storage/emulated/0/DCIM/Camera/IMG.jpg",
             "Name": "IMG.jpg", "Size": 3069933}]),
        "PhoneData/video_extractor.json": b"[]",
        "PhoneData/audio_extractor.json": b"[]",
        "PhoneData/doc_extractor.json": b"[]",
        "PhoneData/uninstalllist.json": _json_bytes([
            {"PackageName": "com.example.gone", "Delete": 0, "ApkSize": 0}]),
        "PhoneData/app_traffic.json": _json_bytes([
            {"PackageName": "com.example.app", "MobileTrafficAll": "10",
             "WiFiTrafficAll": "1727129"}]),
        "PhoneData/appusagedetail.json": _json_bytes({"eventResultList": [
            {"appName": "测试应用", "packageName": "com.example.app",
             "startTime": USAGE_TIME, "endTime": "2025-09-19T12:16:10.157Z",
             "useDuration": "1"}]}),
    }
    if info["wifi"] is not None:
        documents["PhoneData/wifi.json"] = _json_bytes(info["wifi"])
    return list(documents.items())


def create_thunderforensic_tar(target: Path, vendor: str = "OPPO") -> Path:
    info = VENDOR[vendor]
    manifest = {
        "Software": {"Name": "ThunderForensic", "DisplayName": "雷电手机快取",
                     "Version": "4.9.3.32581", "ExtractType": ""},
        "Device": {"Name": info["brand"], "Os": "Android", "OsVersion": info["android"],
                   "Manufactor": info["brand"], "Brand": info["brand"],
                   "Model": info["model"], "Imei": "860000000000001",
                   "VenderVersion": info["vendor"]},
        "TaskInfo": {"TaskName": "androidmobileextra", "DisplayName": "数据提取",
                     "CreateAt": "2026-10-25T10:33:23.434691+08:00",
                     "CompleteAt": "2026-10-25T10:46:06.2548576+08:00"},
    }

    members: list[tuple[str, bytes]] = []
    # Root envelopes / app data come first; PhoneData and the manifest last,
    # matching the vivo sample where the manifest is the final member.
    if info["root_envelopes"]:
        members.append((".backup", _json_bytes({"model": "vivo",
                                                "from": "thunderforensic"})))
        members.append(("wifi.xml", _frame_blob(_wifi_xml([
            {"SSID": "\"VivoNet\"", "preSharedKey": "\"vivo-pass\"",
             "allowedKeyManagement": [0, 1]},
            {"SSID": "\"VivoNet5G\"", "preSharedKey": "\"vivo-pass-5g\"",
             "allowedKeyManagement": [0, 1]},
        ]))))
        members.append(("note.zip", _frame_blob(_encrypted_zip({
            "/data/user/0/com.android.notes/files/easy_transfer_db_record.json": b"{}",
            "/data/user/0/com.android.notes/files/easy_transfer_sp.json": b"{}",
        }))))
        members.append(("encryptNote.zip", _frame_blob(_encrypted_zip({
            "/data/user/0/com.android.notes/files/easy_transfer_db_folder.json": b"{}",
        }))))
        members.append(("encryptContact.vcf", b""))
        members.append(("encryptSms.xml", b""))

    if info["app_container"]:
        container = info["app_container"]
        package = container.rsplit(".", 1)[0]
        prefix = f"{container}/{package}"
        members.append((f"{prefix}/data/user/0/{package}/databases/example.db",
                        b"SQLite format 3\x00fake"))
        members.append((f"{prefix}/data/user/0/{package}/shared_prefs/prefs.xml",
                        b"<map/>"))
        members.append((f"{prefix}/data/user/0/{package}/files/note.txt",
                        b"app-data"))
        # A long path forces a GNU long-name header in the outer container.
        long_path = (f"{prefix}/data/user/0/{package}/cache/"
                     "a-very-long-directory-name-to-exercise-gnu-longname/"
                     "another-long-directory-name/state.bin")
        members.append((long_path, b"long-name"))
        if vendor == "VIVO":
            # The real vivo writer emits the same path more than once; the
            # index keeps the first and accounts for the duplicate.
            members.append((f"{prefix}/data/user/0/{package}/files/note.txt",
                            b"duplicate-should-be-ignored"))

    members.extend(_phone_data(vendor))
    members.append(("LogData/usagestats.log", b"usage-events\n"))
    members.append(("LogData/wifi.log", b"wifi-events\n"))
    members.append(("sdcard/DCIM/Camera/IMG.jpg", b"\xff\xd8fakejpeg"))
    members.append(("sdcard/Download/sample.pdf", b"%PDF-1.4"))
    members.append(("ThunderForensic.json", _json_bytes(manifest)))

    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for name, payload in members:
            record = tarfile.TarInfo(name)
            record.size = len(payload)
            record.mtime = 1758284168
            archive.addfile(record, io.BytesIO(payload))
    data = bytearray(raw.getvalue())

    # Mirror the real writer: every header carries the non-octal gid
    # "-6667000", with a recomputed checksum. This is the quirk that makes
    # libarchive reject the vivo container at open time.
    offset = 0
    while offset + 512 <= len(data):
        header = data[offset:offset + 512]
        if header == b"\0" * 512:
            break
        size_field = bytes(header[124:136]).rstrip(b"\0 ")
        if not size_field or any(c not in b"01234567" for c in size_field):
            break
        size = int(size_field, 8)
        data[offset + 116:offset + 124] = b"-6667000"
        checksum = (sum(data[offset:offset + 148]) + 32 * 8 +
                    sum(data[offset + 156:offset + 512]))
        data[offset + 148:offset + 156] = f"{checksum:06o}\0 ".encode("ascii")
        offset += 512 + ((size + 511) // 512) * 512
    target.write_bytes(bytes(data))
    return target


def _case_database(project: Path, evidence_id: int, kind: str,
                   columns: list[str], rows: list[dict]) -> None:
    """Write one data/evidence_<id>_<kind> case database as ThunderForensic does."""
    data = project / "data"
    data.mkdir(parents=True, exist_ok=True)
    path = data / f"evidence_{evidence_id}_{kind}"
    with sqlite3.connect(path) as connection:
        table = f"evidence_{evidence_id}_{kind}"
        connection.execute(
            f'CREATE TABLE "{table}" (' + ", ".join(f'"{c}" TEXT' for c in columns) + ")")
        for row in rows:
            connection.execute(
                f'INSERT INTO "{table}" (' +
                ", ".join(f'"{c}"' for c in columns) + ") VALUES (" +
                ", ".join("?" for _ in columns) + ")",
                [row.get(column) for column in columns])


def create_case_databases(project: Path, vendor: str) -> None:
    """Mirror the tool's own case databases, including a row the tar lacks.

    The vivo sample ships no PhoneData/smss.json at all while
    data/evidence_1_sms holds the SMS rows, so the fixture reproduces that:
    SMS comes only from the case database, while contacts/calls exist in both
    layers and must not be double-counted.
    """
    archive = f"20261025{vendor}.tar"
    _case_database(project, 1, "sms",
                   ["id", "delete", "name", "phone_number", "content", "time",
                    "type", "is_read", "src_file_path"],
                   [{"id": "1", "delete": "0", "name": "", "phone_number": "13800000009",
                     "content": "case-only-sms", "time": "2025-09-19 12:02:00",
                     "type": "inbox", "is_read": "1",
                     "src_file_path": f"{archive}/com.android.mms.ab/com.android.mms.ab/"
                                      "apps/com.android.mms/db/mmssms.db"}])
    _case_database(project, 1, "contact",
                   ["id", "delete", "name", "phone_number", "src_file_path"],
                   [{"id": "1", "delete": "0", "name": "重复联系人",
                     "phone_number": "13800000001",
                     "src_file_path": f"{archive}/PhoneData/contacts.json"},
                    {"id": "2", "delete": "0", "name": "无来源联系人",
                     "phone_number": "13800000010", "src_file_path": ""}])
    _case_database(project, 1, "calllog",
                   ["id", "delete", "name", "phone_number", "duration", "time",
                    "type", "src_file_path"],
                   [{"id": "1", "delete": "0", "name": "", "phone_number": "13800000011",
                     "duration": "9", "time": "2025-09-19 12:03:00", "type": "missed",
                     "src_file_path": f"{archive}/com.yx.ab/com.yx.ab/apps/com.yx/db/yx.db"}])
    _case_database(project, 1, "wifi",
                   ["id", "delete", "ssid", "password", "key_type", "last_joined",
                    "src_file_path"],
                   [{"id": "1", "delete": "0", "ssid": "AppWifi",
                     "password": "app-pass", "key_type": "WPA_PSK",
                     "last_joined": "2025-09-01 10:00:00",
                     "src_file_path": f"{archive}/com.yx.ab/com.yx.ab/apps/com.yx/db/hmdb"}])
    _case_database(project, 1, "file",
                   ["id", "delete", "name", "full_path", "size", "mtime",
                    "src_full_path"],
                   [{"id": "1", "delete": "0", "name": "main.db",
                     "full_path": f"{archive}/com.yx.ab/com.yx.ab/apps/com.yx/db/main.db",
                     "size": "4096", "mtime": "2025-09-02 11:00:00",
                     "src_full_path": "/data/data/com.yx/db/main.db"}])
    _case_database(project, 1, "webhistory",
                   ["id", "delete", "title", "url", "visit_count",
                    "last_visit_time", "from_app", "src_file_path"],
                   [{"id": "1", "delete": "0", "title": "Example",
                     "url": "https://example.com/", "visit_count": "2",
                     "last_visit_time": "2025-09-03 12:00:00", "from_app": "com.example",
                     "src_file_path": f"{archive}/com.example.ab/com.example.ab/"
                                      "apps/com.example/db/history"}])
    _case_database(project, 1, "immsginfo",
                   ["id", "delete", "send_user_id", "send_nick_name", "receive_user_id",
                    "time", "content", "is_send", "msg_type", "from_app",
                    "src_file_path"],
                   [{"id": "1", "delete": "0", "send_user_id": "u1",
                     "send_nick_name": "甲", "receive_user_id": "u2",
                     "time": "2025-09-04 13:00:00", "content": "case-im-message",
                     "is_send": "2", "msg_type": "text", "from_app": "com.example",
                     "src_file_path": f"{archive}/com.example.ab/com.example.ab/"
                                      "apps/com.example/db/messages"}])
    # An unsupported family still lands in mobile_artifacts under its own kind.
    _case_database(project, 1, "location",
                   ["id", "delete", "name", "address", "longitude", "latitude", "time",
                    "src_file_path"],
                   [{"id": "1", "delete": "0", "name": "家", "address": "某地",
                     "longitude": "116.4", "latitude": "39.9",
                     "time": "2025-09-05 14:00:00", "src_file_path": ""}])


def create_project_dir(root: Path, vendor: str = "OPPO") -> Path:
    project = root / f"20261025{vendor}"
    tar_dir = project / "filesystem" / "1" / "tar"
    tar_dir.mkdir(parents=True)
    create_thunderforensic_tar(tar_dir / f"20261025{vendor}.tar", vendor)
    create_case_databases(project, vendor)
    return project


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([*command, "--no-ai"], capture_output=True, text=True,
                          check=False, timeout=600)


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_extraction(database: Path, vendor: str, context: str,
                      expect_case_databases: bool = True) -> None:
    assert_true(database.exists(), f"{context}: artifact database was not created")
    info = VENDOR[vendor]
    with sqlite3.connect(database) as connection:
        connection.row_factory = sqlite3.Row
        tables = {row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("mobile_backup_manifest", "mobile_artifacts",
                      "installed_apps", "contacts", "call_logs", "sms_messages",
                      "wifi_networks", "device_identifiers",
                      "android_source_coverage", "android_source_provenance"):
            assert_true(table in tables, f"{context}: table missing: {table}")

        manifest = connection.execute(
            "SELECT platform, device, backup_version, module_count, adapter_version, "
            "backup_time_ms FROM mobile_backup_manifest").fetchone()
        expected_device = f"{info['brand']} {info['model']}"
        assert_true(manifest["platform"] == "Android", f"{context}: {dict(manifest)}")
        assert_true(manifest["device"] == expected_device, f"{context}: {dict(manifest)}")
        assert_true(manifest["backup_version"] == "4.9.3.32581",
                    f"{context}: {dict(manifest)}")
        # deviceinfo, imei, application, contacts, calllogs, smss, mmss, siminfo,
        # simstate, calendar, bluetooth, image, video, audio, doc, uninstall,
        # app_traffic, appusagedetail (+ wifi for OPPO/OnePlus)
        expected_modules = 19 if info["wifi"] is not None else 18
        assert_true(manifest["module_count"] == expected_modules,
                    f"{context}: module_count {manifest['module_count']} != {expected_modules}")
        assert_true(manifest["adapter_version"] == "thunderforensic-v2",
                    f"{context}: {dict(manifest)}")
        assert_true(manifest["backup_time_ms"] > 0, f"{context}: {dict(manifest)}")

        kinds = dict(connection.execute(
            "SELECT kind, COUNT(*) FROM mobile_artifacts GROUP BY kind"))
        for kind in ("application", "contact", "call_log", "sms", "wifi", "media",
                     "app_usage_session", "device_info", "device_identifier",
                     "device_log"):
            assert_true(kinds.get(kind, 0) >= 1, f"{context}: kind {kind}: {kinds}")
        # Container (tar) layer counts, isolated from any case-database rows.
        container_kinds = dict(connection.execute(
            "SELECT kind, COUNT(*) FROM mobile_artifacts "
            "WHERE source_path NOT LIKE 'evidence_%' GROUP BY kind"))
        assert_true(container_kinds.get("application") == 2,
                    f"{context}: container kinds: {container_kinds}")
        assert_true(container_kinds.get("contact") == 1,
                    f"{context}: container kinds: {container_kinds}")
        assert_true(container_kinds.get("call_log") == 1,
                    f"{context}: container kinds: {container_kinds}")
        assert_true(container_kinds.get("sms") == 1,
                    f"{context}: container kinds: {container_kinds}")
        assert_true(container_kinds.get("media") == 1,
                    f"{context}: container kinds: {container_kinds}")
        expected_container_wifi = 1 if info["wifi"] is not None else 2
        assert_true(container_kinds.get("wifi") == expected_container_wifi,
                    f"{context}: container kinds: {container_kinds}")
        if info["app_container"]:
            assert_true(kinds.get("app_data_container", 0) >= 1,
                        f"{context}: app containers: {kinds}")
            assert_true(kinds.get("app_database", 0) >= 1,
                        f"{context}: app databases: {kinds}")
        if info["root_envelopes"]:
            assert_true(kinds.get("note_archive") == 2, f"{context}: {kinds}")
            assert_true(kinds.get("device_marker") == 1, f"{context}: {kinds}")
            assert_true(kinds.get("encrypted_artifact") == 2, f"{context}: {kinds}")

        installed = connection.execute(
            "SELECT display_name FROM installed_apps WHERE package_name='com.example.app'"
        ).fetchone()
        assert_true(installed is not None and installed["display_name"] == "测试应用",
                    f"{context}: installed app: {installed}")

        contact = connection.execute(
            "SELECT display_name, phone_number FROM contacts "
            "ORDER BY id LIMIT 1").fetchone()
        assert_true(contact["display_name"] == info["contact"].get(
            "Name", info["contact"].get("NickName")), f"{context}: contact: {contact}")
        expected_phone = info["contact"].get("Phone") or info["contact"].get("PhoneNumber")
        assert_true(contact["phone_number"] == expected_phone, f"{context}: contact: {contact}")

        call = connection.execute(
            "SELECT number, date, duration, type FROM call_logs "
            "ORDER BY id LIMIT 1").fetchone()
        expected_number = info["call"].get("PhoneNumber") or info["call"].get("Number")
        assert_true(call["number"] == expected_number,
                    f"{context}: call: {dict(call)}")
        assert_true(call["duration"] == info["call"]["Duration"],
                    f"{context}: call: {dict(call)}")
        expected_call_type = {"outgoing": 2, "incoming": 1}[info["call"]["Type"]]
        assert_true(call["type"] == expected_call_type,
                    f"{context}: call type: {dict(call)}")
        assert_true(call["date"] == 1758283200,
                    f"{context}: call date: {dict(call)}")

        sms = connection.execute(
            "SELECT address, body, date, type FROM sms_messages "
            "ORDER BY id LIMIT 1").fetchone()
        assert_true(sms["address"] == info["sms"]["Address"] and
                    sms["body"] == info["sms"]["Body"], f"{context}: sms: {dict(sms)}")
        assert_true(sms["type"] == 1, f"{context}: sms type: {dict(sms)}")
        assert_true(sms["date"] == 1758283260, f"{context}: sms date: {dict(sms)}")

        networks = {row["ssid"]: row for row in connection.execute(
            "SELECT ssid, pre_shared_key, key_mgmt FROM wifi_networks")}
        if info["wifi"] is not None:
            ssid = info["wifi"][0]["Ssid"].strip('"')
            assert_true(ssid in networks, f"{context}: wifi: {networks}")
        else:
            assert_true(networks.get("VivoNet", {})["pre_shared_key"] == "vivo-pass",
                        f"{context}: wifi: {networks}")
            assert_true(networks.get("VivoNet5G", {})["pre_shared_key"] == "vivo-pass-5g",
                        f"{context}: wifi: {networks}")
            assert_true(networks.get("VivoNet", {})["key_mgmt"] == "NONE|WPA_PSK",
                        f"{context}: wifi key mgmt: {networks}")

        identifiers = {row["identifier_type"]: row["value"] for row in
                       connection.execute("SELECT identifier_type, value FROM device_identifiers")}
        assert_true(identifiers.get("androidid") == "deadbeefcafebabe",
                    f"{context}: identifiers: {identifiers}")
        assert_true(identifiers.get("imei1") == "860000000000001",
                    f"{context}: identifiers: {identifiers}")
        if vendor == "VIVO":
            assert_true(identifiers.get("iccid") == "898600100120f0005391",
                        f"{context}: identifiers: {identifiers}")

        coverage = {row["source_path"]: (row["status"], row["detail"]) for row in
                    connection.execute("SELECT source_path, status, detail "
                                       "FROM android_source_coverage")}
        assert_true(coverage["PhoneData/application.json"][0] == "parsed",
                    f"{context}: coverage: {coverage}")
        assert_true(coverage["PhoneData/contacts.json"][0] == "parsed",
                    f"{context}: coverage: {coverage}")
        if vendor == "VIVO":
            assert_true(coverage["PhoneData/siminfo.json"][0] == "parsed",
                        f"{context}: coverage: {coverage}")
            assert_true(coverage["wifi.xml"][0] == "parsed",
                        f"{context}: coverage: {coverage}")
            assert_true(coverage["note.zip"][0] == "LOCKED",
                        f"{context}: coverage: {coverage}")
            assert_true(coverage["encryptNote.zip"][0] == "LOCKED",
                        f"{context}: coverage: {coverage}")
            assert_true(coverage[".backup"][0] == "parsed",
                        f"{context}: coverage: {coverage}")
            assert_true(coverage["encryptContact.vcf"][0] == "empty",
                        f"{context}: coverage: {coverage}")
            assert_true(coverage["<containers>"][0] == "indexed",
                        f"{context}: coverage: {coverage}")
        else:
            assert_true("SecurityException" in coverage["PhoneData/siminfo.json"][1],
                        f"{context}: extractor error not surfaced: {coverage}")
            assert_true(coverage["wifi.xml"][0] == "not_found",
                        f"{context}: coverage: {coverage}")
            expected_app_data = "indexed" if info["app_container"] else "empty"
            assert_true(coverage["<containers>"][0] == expected_app_data,
                        f"{context}: coverage: {coverage}")

        # ---- case database layer (data/evidence_<n>_<kind>) ----
        # A bare tar has no project folder, so there is nothing to read.
        if not expect_case_databases:
            assert_true("<data>" not in coverage,
                        f"{context}: tar-only source reported case databases: {coverage}")
            assert_true(not any(path.startswith("evidence_")
                                for path in coverage),
                        f"{context}: tar-only source imported case rows: {coverage}")
            case_kinds = dict(connection.execute(
                "SELECT kind, COUNT(*) FROM mobile_artifacts "
                "WHERE source_path LIKE 'evidence_%' GROUP BY kind"))
            assert_true(not case_kinds,
                        f"{context}: tar-only source imported case rows: {case_kinds}")
        else:
            verify_case_databases(connection, coverage, context)

        session = connection.execute(
            "SELECT timestamp_seconds FROM mobile_artifacts "
            "WHERE kind='app_usage_session'").fetchone()
        assert_true(session is not None and session["timestamp_seconds"] == USAGE_EPOCH,
                    f"{context}: usage session timestamp: {session}")

        verify_source_keys_and_media(connection, context)
        verify_container(connection, vendor, context)
        verify_provenance(connection, context)
        verify_app_container(connection, vendor, context)


def verify_case_databases(connection, coverage, context: str) -> None:
    assert_true(coverage["<data>"][0] == "parsed",
                f"{context}: case aggregate: {coverage['<data>']}")
    assert_true("databases=8" in coverage["<data>"][1],
                f"{context}: case aggregate: {coverage['<data>']}")
    assert_true("skipped_duplicate_rows=2" in coverage["<data>"][1],
                f"{context}: case aggregate: {coverage['<data>']}")
    assert_true(coverage["evidence_1_sms"][0] == "parsed",
                f"{context}: case sms: {coverage['evidence_1_sms']}")
    assert_true("standard_table_rows=1" in coverage["evidence_1_sms"][1],
                f"{context}: case sms: {coverage['evidence_1_sms']}")
    # The case contact rows duplicate the tar's contacts.json family (one names
    # it explicitly, the other is the same provider table without provenance),
    # so both are skipped rather than double-counted.
    assert_true(coverage["evidence_1_contact"][0] == "empty",
                f"{context}: case contact dedupe: {coverage['evidence_1_contact']}")
    assert_true(coverage["evidence_1_calllog"][0] == "parsed",
                f"{context}: case calllog: {coverage['evidence_1_calllog']}")
    assert_true(coverage["evidence_1_wifi"][0] == "parsed",
                f"{context}: case wifi: {coverage['evidence_1_wifi']}")
    assert_true(coverage["evidence_1_file"][0] == "parsed",
                f"{context}: case file: {coverage['evidence_1_file']}")
    assert_true(coverage["evidence_1_location"][0] == "parsed",
                f"{context}: case location: {coverage['evidence_1_location']}")

    case_kinds = dict(connection.execute(
        "SELECT kind, COUNT(*) FROM mobile_artifacts "
        "WHERE source_path LIKE 'evidence_%' GROUP BY kind"))
    for kind in ("sms", "call_log", "wifi", "file_inventory", "im_message",
                 "web_history", "case_location"):
        assert_true(case_kinds.get(kind) == 1,
                    f"{context}: case kind {kind}: {case_kinds}")
    assert_true("contact" not in case_kinds,
                f"{context}: case contacts must be deduped: {case_kinds}")

    case_sms = connection.execute(
        "SELECT body, address FROM sms_messages WHERE body='case-only-sms'").fetchone()
    assert_true(case_sms is not None and case_sms["address"] == "13800000009",
                f"{context}: case sms row: {case_sms}")
    case_im = connection.execute(
        "SELECT record_json, timestamp_raw FROM mobile_artifacts "
        "WHERE kind='im_message'").fetchone()
    assert_true("case-im-message" in case_im["record_json"],
                f"{context}: case im: {dict(case_im)}")
    # ThunderForensic writes local-time strings with no zone; the adapter must
    # keep the raw value instead of inventing a UTC instant.
    assert_true(case_im["timestamp_raw"] == "2025-09-04 13:00:00",
                f"{context}: case im: {dict(case_im)}")
    case_wifi = connection.execute(
        "SELECT ssid, pre_shared_key FROM wifi_networks WHERE ssid='AppWifi'"
    ).fetchone()
    assert_true(case_wifi is not None and case_wifi["pre_shared_key"] == "app-pass",
                f"{context}: case wifi row: {case_wifi}")
    assert_true(connection.execute(
        "SELECT COUNT(*) FROM mobile_artifacts WHERE kind='contact'").fetchone()[0] == 1,
        f"{context}: contact rows must stay at the tar count")
    # Case databases are their own provenance entries (parsed derivative).
    case_provenance = connection.execute(
        "SELECT COUNT(*) FROM android_source_provenance "
        "WHERE source_member_path LIKE 'evidence_%'").fetchone()[0]
    assert_true(case_provenance == 8,
                f"{context}: case provenance rows: {case_provenance}")


def verify_source_keys_and_media(connection, context: str) -> None:
    # The mobile artifact reader (android_artifact_reader.artifact_detail)
    # json.loads(source_key) for every row: a bare string breaks the
    # investigation/report seeding path.
    for row in connection.execute("SELECT kind, source_key FROM mobile_artifacts"):
        try:
            key = json.loads(row["source_key"])
        except json.JSONDecodeError as error:
            raise AssertionError(
                f"{context}: non-JSON source_key for {row['kind']}: "
                f"{row['source_key']!r} ({error})") from error
        assert_true(isinstance(key, dict),
                    f"{context}: source_key is not an object: {row['source_key']}")

    media = connection.execute(
        "SELECT related_path, related_status FROM mobile_artifacts "
        "WHERE kind='media' AND source_path='PhoneData/image_extractor.json'").fetchone()
    assert_true(media["related_status"] == "present_in_container",
                f"{context}: media related link: {dict(media)}")
    assert_true(media["related_path"] == "sdcard/DCIM/Camera/IMG.jpg",
                f"{context}: media related link: {dict(media)}")


def verify_container(connection, vendor: str, context: str) -> None:
    container = connection.execute(
        "SELECT status, reason FROM android_container_coverage").fetchone()
    assert_true(container is not None, f"{context}: container coverage missing")
    assert_true("container_sha256_status=sha256" in container["reason"],
                f"{context}: {container['reason']}")
    expected_duplicates = 1 if vendor == "VIVO" else 0
    assert_true(f"duplicate_members={expected_duplicates}" in container["reason"],
                f"{context}: {container['reason']}")


def verify_provenance(connection, context: str) -> None:
    provenance = connection.execute(
        "SELECT COUNT(*), MIN(adapter_type), MIN(LENGTH(member_sha256)) "
        "FROM android_source_provenance WHERE source_member_path NOT LIKE 'evidence_%'"
    ).fetchone()
    assert_true(provenance[0] > 0, f"{context}: provenance empty")
    assert_true(provenance[1] == "thunder-backup", f"{context}: provenance: {provenance}")
    assert_true(provenance[2] == 64, f"{context}: provenance: {provenance}")


def verify_app_container(connection, vendor: str, context: str) -> None:
    info = VENDOR[vendor]
    if not info["app_container"]:
        assert_true(connection.execute(
            "SELECT COUNT(*) FROM mobile_artifacts "
            "WHERE kind='app_data_container'").fetchone()[0] == 0,
            f"{context}: unexpected app container rows")
        return
    app = connection.execute(
        "SELECT package_name, record_json FROM mobile_artifacts "
        "WHERE kind='app_data_container'").fetchone()
    record = json.loads(app["record_json"])
    assert_true(record["files"] >= 4, f"{context}: app container: {record}")
    assert_true(record["databases"] >= 1, f"{context}: app container: {record}")
    db = connection.execute(
        "SELECT source_path, related_status FROM mobile_artifacts "
        "WHERE kind='app_database'").fetchone()
    assert_true(db["related_status"] == "present_in_container",
                f"{context}: app db: {db}")
    if vendor == "VIVO":
        duplicate = connection.execute(
            "SELECT COUNT(*) FROM mobile_artifacts WHERE source_path LIKE "
            "'%com.example.vivo.ab%files/note.txt'").fetchone()[0]
        assert_true(duplicate == 0,
                    f"{context}: duplicate file unexpectedly indexed: {duplicate}")


def verify_tar_route(analyzer: Path, root: Path, vendor: str) -> None:
    tar_path = create_thunderforensic_tar(root / f"20261025{vendor}.tar", vendor)
    output = root / f"out-tar-{vendor}"
    source = "oppo-backup" if vendor == "OPPO" else "thunder-backup"
    result = run([
        str(analyzer), str(tar_path), "--android-analyze",
        "--android-source", source, "--db-dir", str(output),
    ])
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"{vendor} tar analysis failed: {combined}")
    assert_true("Using The Sleuth Kit" not in combined, "source entered the TSK pipeline")
    # A bare tar carries no project folder, so only the container layer applies.
    verify_extraction(output / f"20261025{vendor}_files.db", vendor, f"{vendor} tar",
                      expect_case_databases=False)


def verify_dir_route_and_promotion(analyzer: Path, root: Path, vendor: str) -> None:
    project = create_project_dir(root, vendor)
    output = root / f"out-dir-{vendor}"
    result = run([
        str(analyzer), str(project), "--android-analyze",
        "--android-source", "dir", "--db-dir", str(output),
    ])
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"{vendor} dir analysis failed: {combined}")
    assert_true("auto-selecting thunder-backup mode" in combined,
                f"{vendor} dir source was not promoted: {combined}")
    assert_true("ThunderForensic case databases:" in combined,
                f"{vendor} dir source skipped case databases: {combined}")
    verify_extraction(output / f"20261025{vendor}_files.db", vendor, f"{vendor} dir")


def verify_root_tar_in_directory(analyzer: Path, root: Path, vendor: str) -> None:
    directory = root / f"flat-{vendor}"
    directory.mkdir()
    create_thunderforensic_tar(directory / f"20261025{vendor}.tar", vendor)
    output = root / f"out-flat-{vendor}"
    result = run([
        str(analyzer), str(directory), "--android-analyze",
        "--android-source", "dir", "--db-dir", str(output),
    ])
    combined = result.stdout + result.stderr
    assert_true(result.returncode == 0, f"{vendor} flat dir failed: {combined}")
    # No data/evidence_* beside the tar, so no case database layer.
    assert_true("ThunderForensic case databases:" not in combined,
                f"{vendor} flat dir invented case databases: {combined}")
    database = output / f"20261025{vendor}_files.db"
    if not database.exists():
        candidates = list(output.glob("*_files.db"))
        assert_true(len(candidates) == 1,
                    f"{vendor} flat dir DB not found: {list(output.iterdir())}")
        database = candidates[0]
    verify_extraction(database, vendor, f"{vendor} flat dir",
                      expect_case_databases=False)


def verify_invalid_source_rejected(analyzer: Path, root: Path) -> None:
    not_thunder = root / "not-thunder"
    not_thunder.mkdir()
    (not_thunder / "readme.txt").write_text("not a container")
    result = run([
        str(analyzer), str(not_thunder), "--android-analyze",
        "--android-source", "thunder-backup", "--db-dir", str(root / "out-bad"),
    ])
    combined = result.stdout + result.stderr
    assert_true(result.returncode != 0, f"non-ThunderForensic source accepted: {combined}")
    assert_true("INVALID_THUNDERFORENSIC_BACKUP" in combined,
                f"wrong failure code: {combined}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--analyzer", required=True)
    args = parser.parse_args()
    analyzer = Path(args.analyzer).resolve()

    with tempfile.TemporaryDirectory(prefix="thunder-cli-") as temp:
        root = Path(temp)
        for vendor in ("OPPO", "OnePlus", "VIVO"):
            verify_tar_route(analyzer, root, vendor)
            verify_dir_route_and_promotion(analyzer, root, vendor)
        verify_root_tar_in_directory(analyzer, root, "VIVO")
        verify_invalid_source_rejected(analyzer, root)
    print("ThunderForensic generic CLI end-to-end tests passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as error:
        print(f"FAILED: {error}", file=sys.stderr)
        sys.exit(1)
