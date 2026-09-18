"""Tests for the evidence-report reader's auto-acquisition of 案件信息 / 证据信息 /
设备基本信息.

The reader used to open only _files.db, where none of the platform artifact
tables live — the task pipeline writes each platform to a SIBLING database
(<task>/android.db, windows.db, linux.db; PathManager::getTaskDbPaths). These
tests pin the resolution, the per-platform device fields, and the write-once
seeding semantics against synthetic fixtures.
"""

import sqlite3
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from httpserver.routes import intelligence_report


# ── fixture databases ────────────────────────────────────────────────────────


def _connect(path):
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE report_metadata_placeholder (x INTEGER);
        DROP TABLE report_metadata_placeholder;
    """)
    return conn


def _make_files_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE files (
            id INTEGER PRIMARY KEY, name TEXT, path TEXT, size INTEGER,
            category TEXT, is_deleted INTEGER, scene_relevant INTEGER, scene_priority INTEGER
        )""")
        conn.execute(
            "INSERT INTO files (name, path, size, category, is_deleted, scene_relevant, scene_priority) "
            "VALUES ('report.pdf', '/docs/report.pdf', 1024, 'documents', 0, 1, 0)"
        )
        conn.execute("""CREATE TABLE case_analysis (
            task_id TEXT PRIMARY KEY, case_description TEXT, case_report TEXT,
            created_at INTEGER, updated_at INTEGER
        )""")


def _make_android_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE miui_backup_manifest (
            id INTEGER PRIMARY KEY, device TEXT, miui_version TEXT, backup_date INTEGER,
            total_size INTEGER, package_count INTEGER, source_folder TEXT
        )""")
        conn.execute(
            "INSERT INTO miui_backup_manifest (device, miui_version, backup_date, total_size, package_count) "
            "VALUES ('cepheus', 'V12.5.6.0.RFACNXM', 1786252337573, 10178179271, 57)"
        )
        # A MIUI backup populates installed_apps, never installed_packages.
        conn.execute("""CREATE TABLE installed_apps (
            id INTEGER PRIMARY KEY, package_name TEXT, display_name TEXT, data_size INTEGER
        )""")
        conn.execute(
            "INSERT INTO installed_apps (package_name, data_size) VALUES ('com.android.contacts', 6)"
        )
        conn.execute("""CREATE TABLE app_db_inventory (
            id INTEGER PRIMARY KEY, package_name TEXT, db_path TEXT, table_name TEXT,
            row_count INTEGER, open_status TEXT
        )""")
        conn.execute(
            "INSERT INTO app_db_inventory (package_name, db_path, table_name, row_count, open_status) "
            "VALUES ('com.android.browser', 'apps/browser/db/analytics.db', 'analytics', 3, 'decrypted')"
        )
        conn.execute("""CREATE TABLE qqnt_kv_records (
            id INTEGER PRIMARY KEY, source_path TEXT, namespace TEXT, key TEXT,
            value_type TEXT, value_text TEXT, is_sensitive INTEGER, parse_status TEXT
        )""")
        conn.execute(
            "INSERT INTO qqnt_kv_records (namespace, key, value_type, value_text) "
            "VALUES ('move_to_de_records', 'push_client_self_info', 'boolean', 'true')"
        )
        conn.execute("""CREATE TABLE call_logs (
            id INTEGER PRIMARY KEY, number TEXT, date INTEGER, type INTEGER
        )""")
        conn.executemany(
            "INSERT INTO call_logs (number, date, type) VALUES (?, 1600000000, 1)",
            [("13800000001",), ("13800000001",), ("13900000002",)],
        )
        conn.execute("""CREATE TABLE system_build_properties (
            id INTEGER PRIMARY KEY, property_key TEXT, property_value TEXT
        )""")
        conn.execute("INSERT INTO system_build_properties (property_key, property_value) "
                     "VALUES ('ro.product.brand', 'Xiaomi')")


def _make_windows_db(path):
    """A windows.db shaped like a REAL one.

    A real Software hive carries dozens of decoy rows whose value_name collides
    with the OS identity values (application names under Installer\\Products /
    Uninstall), plus a Wow6432Node duplicate of CurrentVersion whose values can
    disagree. Both are reproduced here — they are what broke the original
    value_name-only lookup.
    """
    host_key = r"Microsoft\Windows NT\CurrentVersion"
    wow_key = r"Wow6432Node\Microsoft\Windows NT\CurrentVersion"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE registry_values (
            id INTEGER PRIMARY KEY, hive_path TEXT, hive_type TEXT, key_path TEXT,
            value_name TEXT, value_type TEXT, value_data TEXT
        )""")
        conn.executemany(
            "INSERT INTO registry_values (hive_type, key_path, value_name, value_data) VALUES (?, ?, ?, ?)",
            [
                # --- the genuine OS identity, under CurrentVersion ---
                ("SOFTWARE", host_key, "ProductName", "Windows 7 Ultimate"),
                ("SOFTWARE", host_key, "CurrentVersion", "6.1"),
                ("SOFTWARE", host_key, "CSDVersion", "Service Pack 1"),
                ("SOFTWARE", host_key, "EditionID", "Ultimate"),
                ("SOFTWARE", host_key, "CurrentBuild", "7601"),
                ("SOFTWARE", host_key, "InstallDate", "1521447805"),
                ("SOFTWARE", host_key, "RegisteredOwner", "CaiXX"),
                ("SOFTWARE", host_key, "ProductId", "00426-292-0000007-85354"),
                # ...and the 32-bit view, which disagrees and must never win.
                ("SOFTWARE", wow_key, "ProductName", "Windows 7 Ultimate"),
                ("SOFTWARE", wow_key, "InstallDate", "0"),
                ("SOFTWARE", wow_key, "RegisteredOwner", "Microsoft"),
                # --- decoys: same value_names, application keys ---
                ("SOFTWARE", r"Microsoft\Windows\CurrentVersion\Uninstall\WinRAR", "ProductName", "WinRAR archiver"),
                ("SOFTWARE", r"Installer\Products\0B85F5C26FB13DB46A561C5B02B6CD71", "ProductName", "Xshell 7"),
                ("SOFTWARE", r"Installer\Products\0B85F5C26FB13DB46A561C5B02B6CD71", "InstallDate", "20220608"),
                ("SOFTWARE", r"Installer\Products\0B85F5C26FB13DB46A561C5B02B6CD71", "DisplayVersion", "7.0.0109"),
                ("SOFTWARE", r"Microsoft\Internet Explorer\AdvancedOptions\CRYPTO\TLS1.2", "OSVersion", "3.6.1.0.0"),
                # --- other System-hive identity keys ---
                ("SYSTEM", r"ControlSet001\Control\ComputerName\ComputerName", "ComputerName", "COMPUTER-DV"),
                ("SYSTEM", r"ControlSet001\Control\Session Manager\Environment", "PROCESSOR_ARCHITECTURE", "AMD64"),
                ("SYSTEM", r"ControlSet001\Control\TimeZoneInformation", "TimeZoneKeyName", "China Standard Time"),
                ("SOFTWARE", r"Microsoft\SQMClient", "MachineId", "{83F10809-763F-4412-B54C-6FA27D85B871}"),
                # a ComputerName decoy from an unrelated key must not win
                ("NTUSER", r"Software\Microsoft\Windows Media\WMSDK\General", "ComputerName", "WRONG-HOST"),
            ],
        )
        conn.execute("CREATE TABLE user_accounts (id INTEGER PRIMARY KEY, username TEXT, rid INTEGER, is_admin INTEGER)")
        conn.executemany("INSERT INTO user_accounts (username, rid) VALUES (?, ?)",
                         [("Administrator", 500), ("alice", 1001)])
        conn.execute("CREATE TABLE windows_services (id INTEGER PRIMARY KEY, service_name TEXT)")
        conn.executemany("INSERT INTO windows_services (service_name) VALUES (?)", [("Spooler",), ("W32Time",)])
        conn.execute("""CREATE TABLE event_logs (
            id INTEGER PRIMARY KEY, computer_name TEXT, event_id INTEGER
        )""")
        conn.execute("INSERT INTO event_logs (computer_name, event_id) VALUES ('DESKTOP-7QK2L9', 4624)")


def _make_linux_db(path):
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE linux_log_entries (
            id INTEGER PRIMARY KEY, log_file TEXT, hostname TEXT, process TEXT, message TEXT
        )""")
        conn.executemany(
            "INSERT INTO linux_log_entries (log_file, hostname, message) VALUES ('/var/log/messages', ?, 'x')",
            [("srv-prod-01",)] * 3 + [("other-host",)],
        )
        conn.execute("CREATE TABLE linux_users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.executemany("INSERT INTO linux_users (username) VALUES (?)", [("root",), ("deploy",)])
        conn.execute("CREATE TABLE linux_packages (id INTEGER PRIMARY KEY, name TEXT, package_manager TEXT)")
        conn.executemany("INSERT INTO linux_packages (name, package_manager) VALUES (?, 'rpm')",
                         [("bash",), ("openssl",), ("nginx",)])
        conn.execute("CREATE TABLE linux_systemd_services (id INTEGER PRIMARY KEY, service_name TEXT)")
        conn.execute("INSERT INTO linux_systemd_services (service_name) VALUES ('sshd')")


def _make_raw_db(path, fs_types):
    if path.exists():
        path.unlink()
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE partitions (
            id INTEGER PRIMARY KEY, partition_num INTEGER, start_offset INTEGER,
            length INTEGER, description TEXT, fs_type TEXT
        )""")
        conn.executemany(
            "INSERT INTO partitions (partition_num, description, fs_type) VALUES (?, ?, ?)",
            [(i + 1, description, fs_type) for i, (description, fs_type) in enumerate(fs_types)],
        )


@pytest.fixture
def task_dir(tmp_path):
    """A task directory laid out exactly like PathManager::getTaskDbPaths."""
    _make_files_db(tmp_path / "files.db")
    _make_android_db(tmp_path / "android.db")
    _make_windows_db(tmp_path / "windows.db")
    _make_linux_db(tmp_path / "linux.db")
    _make_raw_db(tmp_path / "raw.db", [("Linux (0x83)", "ext4"), ("NTFS", "ntfs")])
    return tmp_path


def _task(task_dir, **overrides):
    task = {
        "id": "task-abc",
        "image_path": "/evidence/服务器镜像.E01",
        "status": "COMPLETED",
        "case_description": "电信诈骗案",
        "created_time": 1786252330,
        "completed_time": 1786253726,
        "scenarios": [],
        "output_files_db": str(task_dir / "files.db"),
        "output_raw_db": str(task_dir / "raw.db"),
        "metadata": {},
    }
    task.update(overrides)
    return task


@pytest.fixture
def client_factory(monkeypatch):
    """Build a TestClient whose C++ backend returns the supplied task dict."""
    def _build(task):
        service_manager = MagicMock()
        service_manager.cpp_backend.get_task = AsyncMock(return_value=task)
        monkeypatch.setattr(
            "httpserver.services.get_service_manager", lambda: service_manager, raising=False
        )
        app = FastAPI()
        app.include_router(intelligence_report.router, prefix="/api/llm")
        return TestClient(app)
    return _build


# ── platform database resolution ─────────────────────────────────────────────


def test_resolves_platform_dbs_as_siblings_of_files_db(task_dir):
    task = _task(task_dir)
    dbs = intelligence_report._resolve_platform_dbs(
        task["output_files_db"], task["output_raw_db"], task
    )
    assert dbs["android"] == str(task_dir / "android.db")
    assert dbs["windows"] == str(task_dir / "windows.db")
    assert dbs["linux"] == str(task_dir / "linux.db")


def test_platform_db_candidate_is_rejected_without_its_tables(tmp_path):
    """A stray android.db without Android tables must not be claimed as Android."""
    (tmp_path / "files.db").touch()
    _make_linux_db(tmp_path / "android.db")  # wrong tables for the name
    dbs = intelligence_report._resolve_platform_dbs(str(tmp_path / "files.db"), None, {})
    assert dbs["android"] is None
    # ...but the same file is legitimately the Linux database? No — it is named
    # android.db, and candidates are derived by name, so linux stays unfound too.
    assert dbs["linux"] is None


def test_declared_task_metadata_path_wins(tmp_path):
    (tmp_path / "elsewhere").mkdir()
    _make_android_db(tmp_path / "elsewhere" / "custom.db")
    (tmp_path / "files.db").touch()
    task = {"metadata": {"android_db": str(tmp_path / "elsewhere" / "custom.db")}}
    dbs = intelligence_report._resolve_platform_dbs(str(tmp_path / "files.db"), None, task)
    assert dbs["android"] == str(tmp_path / "elsewhere" / "custom.db")


def test_scenario_databases_beat_every_other_candidate(task_dir):
    """The path C++ recorded for the scenario is the authority."""
    (task_dir / "elsewhere").mkdir()
    _make_android_db(task_dir / "elsewhere" / "declared.db")
    task = {"scenario_databases": {"android": str(task_dir / "elsewhere" / "declared.db")}}
    dbs = intelligence_report._resolve_platform_dbs(
        str(task_dir / "files.db"), str(task_dir / "raw.db"), task
    )
    assert dbs["android"] == str(task_dir / "elsewhere" / "declared.db")


# ── timestamps ───────────────────────────────────────────────────────────────


def test_format_epoch_never_stringifies_a_missing_value():
    # A null timestamp must stay empty, not become the literal "None".
    assert intelligence_report._format_epoch(None) == ""
    assert intelligence_report._format_epoch("") == ""
    assert intelligence_report._format_epoch(0) == ""
    assert intelligence_report._format_epoch(-1) == ""


def test_format_epoch_accepts_seconds_and_milliseconds():
    assert intelligence_report._format_epoch(1787404958).startswith("2026-")
    # The C++ task API reports milliseconds; both must land on the same instant.
    assert intelligence_report._format_epoch(1787404958000) == \
        intelligence_report._format_epoch(1787404958)


def test_derives_extract_times_from_the_nested_timestamps_object(task_dir, client_factory):
    task = _task(
        task_dir,
        timestamps={"created": 1787404958000, "started": 1787404960000,
                    "completed": 1787405078000, "execution_time_seconds": 118},
    )
    task.pop("created_time")
    task.pop("completed_time")
    body = client_factory(task).get("/api/llm/intelligence-report/task-abc/metadata").json()
    assert body["metadata"]["extract_start"] == \
        intelligence_report._format_epoch(1787404960000)
    assert body["metadata"]["extract_end"] == \
        intelligence_report._format_epoch(1787405078000)


def test_missing_timestamps_leave_the_fields_empty(task_dir, client_factory):
    task = _task(task_dir)
    task.pop("created_time")
    task.pop("completed_time")
    body = client_factory(task).get("/api/llm/intelligence-report/task-abc/metadata").json()
    assert body["metadata"]["extract_start"] == ""
    assert body["metadata"]["extract_end"] == ""
    assert "extract_start" not in body["auto_fields"]


# ── platform detection ───────────────────────────────────────────────────────


def test_detects_every_platform_from_its_database(task_dir):
    task = _task(task_dir)
    dbs = intelligence_report._resolve_platform_dbs(
        task["output_files_db"], task["output_raw_db"], task
    )
    assert intelligence_report._detect_platforms(task, dbs, task["output_raw_db"]) == [
        "android", "windows", "linux",
    ]


def test_scenarios_take_priority_over_databases(task_dir):
    task = _task(task_dir, scenarios=["windows"])
    dbs = intelligence_report._resolve_platform_dbs(
        task["output_files_db"], task["output_raw_db"], task
    )
    platforms = intelligence_report._detect_platforms(task, dbs, task["output_raw_db"])
    # windows is declared first, the rest still follow from their databases
    assert platforms[0] == "windows"


def test_server_cloud_scenario_reports_as_linux():
    task = {"scenarios": ["server_cloud"]}
    assert intelligence_report._detect_platforms(task, {}, None) == ["linux"]


def test_falls_back_to_partition_filesystem_types(tmp_path):
    raw_db = tmp_path / "raw.db"
    _make_raw_db(raw_db, [("Linux (0x83)", "ext4")])
    # No scenarios and no platform databases: only the partition table to go on.
    assert intelligence_report._detect_platforms({}, {}, str(raw_db)) == ["linux"]

    _make_raw_db(raw_db, [("NTFS", "ntfs")])
    assert intelligence_report._detect_platforms({}, {}, str(raw_db)) == ["windows"]


# ── device basic info per platform ───────────────────────────────────────────


def test_android_device_info_from_miui_manifest(task_dir):
    record = intelligence_report._android_device_info_records(str(task_dir / "android.db"))[0]
    assert record["设备型号"] == "cepheus"
    assert record["系统版本"] == "V12.5.6.0.RFACNXM"
    assert record["设备品牌"] == "Xiaomi"          # from system_build_properties
    assert record["应用数"] == "57"
    assert record["数据总量"] == "9.48 GB"
    # 39 reference items are always present, empty ones included.
    assert len([k for k in record if k not in ("备份日期", "数据总量", "应用数")]) >= 39


def test_backup_source_reports_only_the_fields_it_can_hold(tmp_path):
    """A MIUI backup has no build.prop, so the image schema would be ~37 dashes."""
    import sqlite3 as _sqlite3
    db = tmp_path / "android.db"
    with _sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE miui_backup_manifest (
            id INTEGER PRIMARY KEY, device TEXT, miui_version TEXT, backup_date INTEGER,
            total_size INTEGER, package_count INTEGER, source_folder TEXT
        )""")
        conn.execute(
            "INSERT INTO miui_backup_manifest (device, miui_version, backup_date, total_size, package_count) "
            "VALUES ('cepheus', 'V12.5.6.0.RFACNXM', 1786252337573, 10178179271, 57)"
        )
        # No system_build_properties / device_identifiers at all.

    record = intelligence_report._android_device_info_records(str(db))[0]
    assert set(record) == {"设备型号", "系统版本", "备份日期", "数据总量", "应用数"}
    # Every reported field carries a real value — no permanent em-dashes.
    assert all(record.values()), record
    assert record["设备型号"] == "cepheus"


def test_windows_device_info_picks_the_os_rows_not_the_app_rows(task_dir):
    """value_name alone collides with Installer/Uninstall rows; key_path decides."""
    record = intelligence_report._win_device_info_records(str(task_dir / "windows.db"))[0]
    # The decoys ("WinRAR archiver", "Xshell 7") must be ignored.
    assert record["操作系统"] == "Windows 7 Ultimate"
    assert record["安装时间"] == \
        intelligence_report._format_epoch(1521447805)     # not "20220608"
    assert record["系统版本"] == "6.1"                      # not the IE "3.6.1.0.0"
    assert record["版次"] == "Ultimate"
    assert record["内部版本号"] == "7601"
    assert record["Service Pack"] == "Service Pack 1"
    assert record["产品ID"] == "00426-292-0000007-85354"


def test_windows_device_info_prefers_the_native_registry_view(task_dir):
    """Wow6432Node duplicates can disagree (InstallDate 0, owner "Microsoft")."""
    record = intelligence_report._win_device_info_records(str(task_dir / "windows.db"))[0]
    assert record["注册所有者"] == "CaiXX"                  # not "Microsoft"
    assert record["安装时间"] != intelligence_report._format_epoch(0)


def test_windows_device_info_reads_the_system_hive_identity(task_dir):
    record = intelligence_report._win_device_info_records(str(task_dir / "windows.db"))[0]
    assert record["计算机名"] == "COMPUTER-DV"              # not the NTUSER decoy
    assert record["处理器架构"] == "AMD64"
    assert record["时区"] == "China Standard Time"
    assert record["机器标识"] == "{83F10809-763F-4412-B54C-6FA27D85B871}"
    assert record["用户账户数"] == "2"
    assert record["系统服务数"] == "2"


def test_windows_computer_name_falls_back_to_event_logs(tmp_path):
    """With no ComputerName registry row, libevtx's event field supplies it."""
    db = tmp_path / "windows.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE registry_values (
            id INTEGER PRIMARY KEY, hive_path TEXT, hive_type TEXT, key_path TEXT,
            value_name TEXT, value_type TEXT, value_data TEXT
        )""")
        conn.execute("""CREATE TABLE event_logs (
            id INTEGER PRIMARY KEY, computer_name TEXT, event_id INTEGER
        )""")
        conn.execute("INSERT INTO event_logs (computer_name, event_id) VALUES ('FALLBACK-PC', 4624)")
    record = intelligence_report._win_device_info_records(str(db))[0]
    assert record["计算机名"] == "FALLBACK-PC"


def test_windows_device_info_missing_db_is_all_empty():
    record = intelligence_report._win_device_info_records(None)[0]
    assert record and all(v == "" for v in record.values())


def test_linux_device_info_hostname_and_counts(task_dir):
    record = intelligence_report._linux_device_info_records(str(task_dir / "linux.db"))[0]
    assert record["主机名"] == "srv-prod-01"         # mode, not the stray 'other-host'
    assert record["用户账户数"] == "2"
    assert record["已安装包数"] == "3"
    assert record["系统服务数"] == "1"
    # No source exists for the distro/kernel in this fixture, so it stays empty
    # rather than being invented.
    assert record["发行版"] == ""


def test_linux_device_info_prefers_the_analyzers_host_info_row(tmp_path):
    """linux_host_info (written by the analyzer) outranks the log-derived guess."""
    import sqlite3 as _sqlite3
    db = tmp_path / "linux.db"
    with _sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE linux_host_info (
            id INTEGER PRIMARY KEY, hostname TEXT, distro TEXT, distro_version TEXT,
            kernel_version TEXT, architecture TEXT, timezone TEXT, machine_id TEXT,
            kernel_modules_installed INTEGER, collected_at INTEGER
        )""")
        conn.execute(
            "INSERT INTO linux_host_info (hostname, distro, distro_version, kernel_version,"
            " architecture, timezone, machine_id, kernel_modules_installed, collected_at)"
            " VALUES ('happy-bliss-7', 'CentOS Linux 7 (Core)', '7',"
            " '4.10.4-1.el7.elrepo.x86_64', 'x86_64', 'Asia/Shanghai', 'abc123', 1523, 1)"
        )
        # A log-derived hostname that must NOT win.
        conn.execute("CREATE TABLE linux_log_entries (id INTEGER PRIMARY KEY, hostname TEXT)")
        conn.execute("INSERT INTO linux_log_entries (hostname) VALUES ('stale-from-logs')")
        conn.execute("CREATE TABLE linux_users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.executemany("INSERT INTO linux_users (username) VALUES (?)", [("root",), ("web",)])

    record = intelligence_report._linux_device_info_records(str(db))[0]
    assert record["主机名"] == "happy-bliss-7"          # not "stale-from-logs"
    assert record["发行版"] == "CentOS Linux 7 (Core)"
    assert record["发行版版本"] == "7"
    assert record["内核版本"] == "4.10.4-1.el7.elrepo.x86_64"
    assert record["系统架构"] == "x86_64"
    assert record["时区"] == "Asia/Shanghai"
    assert record["机器标识"] == "abc123"
    assert record["内核模块数"] == "1523"
    assert record["用户账户数"] == "2"                   # still counted from its table


def test_linux_device_info_reads_os_release_when_a_content_table_exists(tmp_path):
    import sqlite3 as _sqlite3
    db = tmp_path / "linux.db"
    os_release = 'PRETTY_NAME="Ubuntu 22.04 LTS"\nNAME=Ubuntu\nID=ubuntu'
    with _sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE linux_users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.execute("""CREATE TABLE os_config_files (
            id INTEGER PRIMARY KEY, file_path TEXT, content TEXT
        )""")
        conn.execute(
            "INSERT INTO os_config_files (file_path, content) VALUES (?, ?)",
            ("/etc/os-release", os_release),
        )
        conn.execute(
            "INSERT INTO os_config_files (file_path, content) VALUES (?, ?)",
            ("/etc/hostname", "srv01"),
        )

    record = intelligence_report._linux_device_info_records(str(db))[0]
    assert record["发行版"] == "Ubuntu 22.04 LTS"    # PRETTY_NAME wins over NAME
    assert record["主机名"] == "srv01"


# ── report directory ─────────────────────────────────────────────────────────


def test_directory_labels_each_detected_platform(task_dir, client_factory):
    client = client_factory(_task(task_dir))
    body = client.get("/api/llm/intelligence-report/task-abc").json()
    titles = {n["id"]: n["title"] for n in body["directory"]}
    assert titles["device_info"] == "设备基本信息（Android）"
    assert titles["win_device_info"] == "设备基本信息（Windows）"
    assert titles["linux_device_info"] == "设备基本信息（Linux）"
    # metadata.platforms keeps the raw ids — it is an existing API contract.
    assert body["metadata"]["platforms"] == ["android", "windows", "linux"]


def test_directory_uses_a_distinct_id_when_no_platform_is_known(tmp_path, client_factory):
    _make_files_db(tmp_path / "files.db")
    task = _task(tmp_path, scenarios=[], output_raw_db="")
    client = client_factory(task)
    titles = {n["id"]: n["title"] for n in
              client.get("/api/llm/intelligence-report/task-abc").json()["directory"]}
    assert titles["device_info_generic"] == "设备基本信息"
    assert "device_info" not in titles


def test_records_endpoint_reads_from_the_platform_database(task_dir, client_factory):
    client = client_factory(_task(task_dir))
    windows = client.get(
        "/api/llm/intelligence-report/task-abc/records",
        params={"category": "win_device_info"},
    ).json()
    assert windows["records"][0]["操作系统"] == "Windows 7 Ultimate"

    linux = client.get(
        "/api/llm/intelligence-report/task-abc/records",
        params={"category": "linux_device_info"},
    ).json()
    assert linux["records"][0]["主机名"] == "srv-prod-01"


# ── Android artifact sections ────────────────────────────────────────────────


def test_apps_section_falls_back_to_the_backup_table(task_dir):
    """A MIUI backup populates installed_apps, not installed_packages."""
    db = str(task_dir / "android.db")
    assert intelligence_report._resolve_apps_table(db) == "installed_apps"


def test_apps_section_prefers_a_populated_table(tmp_path):
    import sqlite3 as _sqlite3
    db = tmp_path / "android.db"
    with _sqlite3.connect(db) as conn:
        # installed_packages exists but is empty; installed_apps has the data.
        conn.execute("CREATE TABLE installed_packages (id INTEGER PRIMARY KEY, package_name TEXT)")
        conn.execute("CREATE TABLE installed_apps (id INTEGER PRIMARY KEY, package_name TEXT)")
        conn.execute("INSERT INTO installed_apps (package_name) VALUES ('com.tencent.mm')")
    assert intelligence_report._resolve_apps_table(str(db)) == "installed_apps"


def test_backup_inventory_sections_are_registered_and_populated(task_dir, client_factory):
    """The backup inventories carry thousands of rows and used to have no section."""
    client = client_factory(_task(task_dir))
    directory = client.get("/api/llm/intelligence-report/task-abc").json()["directory"]
    totals = {n["id"]: (n.get("stats") or {}).get("total")
              for n in directory if n["kind"] == "records"}
    assert totals["apps"] == 1
    assert totals["app_db_inventory"] == 1
    assert totals["qqnt_kv"] == 1

    page = client.get(
        "/api/llm/intelligence-report/task-abc/records",
        params={"category": "app_db_inventory"},
    ).json()
    assert page["total"] == 1
    assert page["records"][0]["package_name"] == "com.android.browser"


# ── metadata derivation + write-once seeding ─────────────────────────────────


def test_metadata_seeds_derived_values_on_first_read(task_dir, client_factory):
    client = client_factory(_task(task_dir))
    body = client.get("/api/llm/intelligence-report/task-abc/metadata").json()
    md = body["metadata"]
    assert md["evidence_name"] == "服务器镜像.E01"
    assert md["evidence_number"] == "task-abc"
    assert md["case_name"] == "电信诈骗案"
    assert md["extract_start"].startswith("2026-")
    assert "检测平台" in md["remarks"]
    assert md["phone1"] == "13800000001"          # most frequent call_logs number
    assert set(body["auto_fields"]) >= {"evidence_name", "evidence_number", "case_name"}
    # Fields with no source stay empty for the analyst to fill in.
    assert md["collector_name"] == ""
    assert md["holder"] == ""


def test_edited_field_loses_its_auto_badge_and_survives_re_seeding(task_dir, client_factory):
    client = client_factory(_task(task_dir))
    seeded = client.get("/api/llm/intelligence-report/task-abc/metadata").json()

    payload = dict(seeded["metadata"])
    payload["holder"] = "张三"
    payload["case_name"] = "改名后的案件"
    saved = client.put("/api/llm/intelligence-report/task-abc/metadata", json=payload).json()
    assert "case_name" not in saved["auto_fields"]
    assert "evidence_name" in saved["auto_fields"]     # untouched, still auto

    # Re-reading must not clobber the analyst's edit nor re-badge it.
    again = client.get("/api/llm/intelligence-report/task-abc/metadata").json()
    assert again["metadata"]["case_name"] == "改名后的案件"
    assert again["metadata"]["holder"] == "张三"
    assert "case_name" not in again["auto_fields"]


def test_seed_endpoint_is_idempotent(task_dir, client_factory):
    client = client_factory(_task(task_dir))
    payload = dict(client.get("/api/llm/intelligence-report/task-abc/metadata").json()["metadata"])
    payload["case_name"] = "人工案件名"
    client.put("/api/llm/intelligence-report/task-abc/metadata", json=payload)

    seeded = client.post("/api/llm/intelligence-report/task-abc/metadata/seed").json()
    assert seeded["metadata"]["case_name"] == "人工案件名"


def test_seeding_is_deferred_while_the_task_is_still_running(task_dir, client_factory):
    client = client_factory(_task(task_dir, status="RUNNING"))
    body = client.get("/api/llm/intelligence-report/task-abc/metadata").json()
    # Derived values are shown as a preview...
    assert body["metadata"]["evidence_name"] == "服务器镜像.E01"
    # ...but nothing is stamped, so the one write is kept for completion.
    with sqlite3.connect(task_dir / "files.db") as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_metadata'"
        ).fetchone()
        stamped = None
        if exists:
            row = conn.execute(
                "SELECT auto_seeded_at FROM report_metadata WHERE task_id = 'task-abc'"
            ).fetchone()
            stamped = row[0] if row else None
    assert stamped is None


def test_migrates_a_pre_existing_metadata_table_without_losing_rows(task_dir, client_factory):
    """A files.db written by the previous build has the 39 fields, no seed columns."""
    db = task_dir / "files.db"
    field_sql = ", ".join(f'"{f}" TEXT' for f in intelligence_report._METADATA_FIELDS)
    with sqlite3.connect(db) as conn:
        conn.execute(
            f'CREATE TABLE report_metadata (task_id TEXT PRIMARY KEY, {field_sql}, updated_at INTEGER)'
        )
        conn.execute(
            "INSERT INTO report_metadata (task_id, case_name, holder) "
            "VALUES ('task-abc', '既有案件', '李四')"
        )

    client = client_factory(_task(task_dir))
    body = client.get("/api/llm/intelligence-report/task-abc/metadata").json()
    assert body["metadata"]["case_name"] == "既有案件"     # preserved, never overwritten
    assert body["metadata"]["holder"] == "李四"
    assert body["metadata"]["evidence_number"] == "task-abc"   # still-empty fields seeded
    assert "case_name" not in body["auto_fields"]
    assert "evidence_number" in body["auto_fields"]

    # The new bookkeeping columns now exist and the row is stamped.
    with sqlite3.connect(db) as conn:
        row = conn.execute(
            "SELECT auto_seeded_at FROM report_metadata WHERE task_id = 'task-abc'"
        ).fetchone()
    assert row[0] is not None


def test_migration_backfills_columns_missing_from_a_partial_table(task_dir, client_factory):
    """Reconciliation is per-column, not just for the seed bookkeeping."""
    db = task_dir / "files.db"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE TABLE report_metadata (task_id TEXT PRIMARY KEY, case_name TEXT, updated_at INTEGER)"
        )
        conn.execute("INSERT INTO report_metadata (task_id, case_name) VALUES ('task-abc', '既有案件')")

    client = client_factory(_task(task_dir))
    body = client.get("/api/llm/intelligence-report/task-abc/metadata").json()
    assert body["metadata"]["case_name"] == "既有案件"
    assert body["metadata"]["evidence_name"] == "服务器镜像.E01"
    # A write must now succeed against the reconciled table.
    saved = client.put(
        "/api/llm/intelligence-report/task-abc/metadata",
        json={**body["metadata"], "holder": "王五"},
    )
    assert saved.status_code == 200
    assert saved.json()["metadata"]["holder"] == "王五"
