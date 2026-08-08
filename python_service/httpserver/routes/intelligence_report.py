"""Evidence intelligence report reader routes.

Serves the /case-intelligence reader view. It is intentionally separate from
the versioned forensic-report snapshot API (/api/reports) and from the legacy
case-analysis generator (/api/llm/case-analysis). This view only READS:

  - task metadata (from the C++ backend)
  - files evidence table (from the task _files.db)
  - timeline events (from the task _events.db)
  - the five-chapter LLM intelligence report (from case_analysis.case_report)

It never mutates the source databases and never reads case_analysis /
file_descriptions as if they were raw forensic evidence.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)
router = APIRouter()


# ── response models ───────────────────────────────────────────────────────────


class DirectoryNodeStats(BaseModel):
    total: int = 0
    deleted: int = 0
    relevant: int = 0


class DirectoryNode(BaseModel):
    id: str
    title: str
    kind: str  # overview | case | files | timeline | chapter
    stats: DirectoryNodeStats | None = None


class IntelligenceReportMetadata(BaseModel):
    task_id: str
    title: str
    image_path: str | None = None
    files_db: str | None = None
    events_db: str | None = None
    generated_at: str | None = None
    platforms: list[str] = []


class IntelligenceReportResponse(BaseModel):
    scope_type: str = "task"
    scope_id: str
    metadata: IntelligenceReportMetadata
    directory: list[DirectoryNode]


class RecordPage(BaseModel):
    category: str
    page: int
    page_size: int
    total: int
    total_pages: int
    records: list[dict[str, Any]]


class SearchHit(BaseModel):
    category: str
    page: int
    record_id: str
    title: str


class SearchResponse(BaseModel):
    total: int
    offset: int
    limit: int
    hits: list[SearchHit]


# ── DB helpers ────────────────────────────────────────────────────────────────

_FILE_FIELDS = (
    "name", "path", "size", "extension", "category", "type", "mtime", "ctime",
    "is_deleted", "md5", "scene_type", "scene_priority", "scene_relevant",
)
_EVENT_FIELDS = (
    "timestamp", "event_type", "file_path", "description", "file_size",
    "file_type", "severity", "event_source", "event_category", "normalized_type",
    "llm_summary", "llm_is_relevant",
)

# ── report metadata (case info + evidence info) ──────────────────────────────
# Editable, task-scoped forensic metadata that has no home in the C++ task
# object. Mirrors the reference report's 案件信息 (~20 fields) and 证据信息
# (~21 fields). Stored in _files.db alongside case_analysis; never touched by
# the C++ analyzer.

_METADATA_CREATE = """\
CREATE TABLE IF NOT EXISTS report_metadata (
    task_id TEXT PRIMARY KEY,
    -- 案件信息
    case_name TEXT, case_number TEXT, case_type TEXT,
    law_case_number TEXT, law_case_category TEXT, law_case_name TEXT,
    collector_name TEXT, collector_id TEXT, collector_id_card TEXT,
    collector_unit TEXT,
    submitter1_name TEXT, submitter1_id TEXT,
    submitter2_name TEXT, submitter2_id TEXT, submitter_unit TEXT,
    inspection_number TEXT, alarm_id TEXT, alarm_code TEXT, remarks TEXT,
    -- 证据信息
    evidence_name TEXT, evidence_number TEXT,
    phone1 TEXT, phone2 TEXT,
    holder TEXT, holder_id TEXT, holder_type TEXT,
    id_type TEXT, id_number TEXT,
    extract_start TEXT, extract_end TEXT, evidence_remarks TEXT,
    holder_gender TEXT, holder_ethnicity TEXT, birth_date TEXT,
    current_address TEXT, registered_address TEXT,
    id_issue_authority TEXT, id_valid_from TEXT, id_valid_to TEXT,
    updated_at INTEGER
)
"""

# Whitelist of user-editable columns (task_id/updated_at are managed by us).
_METADATA_FIELDS = (
    "case_name", "case_number", "case_type",
    "law_case_number", "law_case_category", "law_case_name",
    "collector_name", "collector_id", "collector_id_card", "collector_unit",
    "submitter1_name", "submitter1_id",
    "submitter2_name", "submitter2_id", "submitter_unit",
    "inspection_number", "alarm_id", "alarm_code", "remarks",
    "evidence_name", "evidence_number",
    "phone1", "phone2",
    "holder", "holder_id", "holder_type",
    "id_type", "id_number",
    "extract_start", "extract_end", "evidence_remarks",
    "holder_gender", "holder_ethnicity", "birth_date",
    "current_address", "registered_address",
    "id_issue_authority", "id_valid_from", "id_valid_to",
)

# ── device basic info: the 39 reference-report items, in order ───────────────
# Each item: (display_label, lookup_keys...) — lookup_keys are tried in order
# against build-property / device-identifier / OS values to populate the row.
_DEVICE_INFO_ITEMS = (
    ("设备名称", "ro.product.name", "ProductName"),
    ("系统版本", "ro.build.version.release", "OSVersion"),
    ("设备型号", "ro.product.model", "ProductModel"),
    ("颜色", "ro.boot.color"),
    ("设备品牌", "ro.product.brand", "Manufacturer"),
    ("ICCID（SIM卡1）", "iccid_sim1"),
    ("ICCID（SIM卡2）", "iccid_sim2"),
    ("CPU ABI", "ro.product.cpu.abi"),
    ("购买日期", "purchase_date"),
    ("过保日期", "warranty_date"),
    ("电话号码1", "phone_number_1", "line1_number1"),
    ("电话号码2", "phone_number_2", "line1_number2"),
    ("内核版本", "kernel_version"),
    ("设备标识", "ro.serialno", "DeviceId"),
    ("序列号", "serial_number"),
    ("GSM基带版本", "gsm.version.baseband", "ro.baseband.version"),
    ("CDMA基带版本", "cdma_baseband_version"),
    ("时区", "persist.sys.timezone"),
    ("时区名", "timezone_name"),
    ("Wi-Fi地址", "wifi_mac", "ro.boot.wifimacaddr"),
    ("蓝牙地址", "bluetooth_mac", "ro.boot.btmacaddr"),
    ("IMEI", "imei1", "imei"),
    ("IMEI2", "imei2"),
    ("MEID", "meid"),
    ("IMSI（SIM卡1）", "imsi_sim1"),
    ("IMSI（SIM卡2）", "imsi_sim2"),
    ("运营商（SIM卡1）", "carrier_sim1", "gsm.operator.alpha"),
    ("运营商（SIM卡2）", "carrier_sim2"),
    ("IP地址", "ip_address"),
    ("Hardware Name", "ro.hardware"),
    ("Board Name", "ro.product.board"),
    ("ANDROID ID", "android_id"),
    ("内置SD卡信息", "internal_sd"),
    ("外置SD卡信息", "external_sd"),
    ("用户总空间大小", "user_total_space"),
    ("用户可用空间大小(动态变化)", "user_available_space"),
    ("默认存储总空间大小", "default_storage_total"),
    ("默认存储可用空间大小(动态变化)", "default_storage_available"),
    ("是否root", "is_rooted", "ro.boot.verifiedbootstate"),
)


def _connect_ro(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=ro"
    return sqlite3.connect(uri, uri=True, timeout=10)


def _connect_rw(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()), safe='/')}?mode=rwc"
    return sqlite3.connect(uri, uri=True, timeout=10)


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone() is not None


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _row_to_record(row: sqlite3.Row, columns: list[str]) -> dict[str, Any]:
    return {columns[i]: row[i] for i in range(len(columns))}


def _select_columns(conn: sqlite3.Connection, table: str, wanted: tuple[str, ...]) -> list[str]:
    """Return the subset of `wanted` columns actually present on `table`."""
    present = _table_columns(conn, table)
    return [c for c in wanted if c in present]


def _fetch_rows(
    conn: sqlite3.Connection, table: str, wanted: tuple[str, ...],
    order_by: str | None, page: int, page_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """Select `wanted` columns from `table` with optional ORDER BY + pagination."""
    cols = _select_columns(conn, table, wanted)
    if not cols:
        return [], 0
    total = _count(conn, table)
    page, page_size, total_pages = _paginated(total, page, page_size)
    col_sql = ", ".join(f'"{c}"' for c in cols)
    offset = (page - 1) * page_size
    order_sql = f' ORDER BY "{order_by}"' if (order_by and order_by in cols) else ""
    rows = conn.execute(
        f'SELECT {col_sql} FROM "{table}"{order_sql} LIMIT ? OFFSET ?',
        (page_size, offset),
    ).fetchall()
    return [_row_to_record(r, cols) for r in rows], total


def _empty_metadata() -> dict[str, Any]:
    """Full metadata dict with every field present (empty string)."""
    return {field: "" for field in _METADATA_FIELDS}


def _json_or_raw(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed
        except (TypeError, ValueError, json.JSONDecodeError):
            return value
    return value


# ── report metadata persistence ──────────────────────────────────────────────


def _ensure_metadata_table(files_db: str) -> None:
    """Create report_metadata table (idempotent) in _files.db."""
    if not files_db or not Path(files_db).is_file():
        return
    try:
        with _connect_rw(Path(files_db)) as conn:
            conn.executescript(_METADATA_CREATE)
            conn.commit()
    except sqlite3.Error as exc:
        logger.warning("ensure report_metadata failed: %s", exc)


def _load_metadata(files_db: str | None, task_id: str) -> dict[str, Any]:
    """Return the metadata row as a dict (all fields, empty if absent)."""
    base = _empty_metadata()
    if not files_db or not Path(files_db).is_file():
        return base
    try:
        with _connect_ro(Path(files_db)) as conn:
            if not _table_exists(conn, "report_metadata"):
                return base
            cols = [c for c in _METADATA_FIELDS if c in _table_columns(conn, "report_metadata")]
            if not cols:
                return base
            col_sql = ", ".join(f'"{c}"' for c in cols)
            row = conn.execute(
                f'SELECT {col_sql} FROM "report_metadata" WHERE task_id = ?', (task_id,)
            ).fetchone()
            if row:
                for i, c in enumerate(cols):
                    base[c] = row[i] if row[i] is not None else ""
    except sqlite3.Error as exc:
        logger.warning("load report_metadata failed: %s", exc)
    return base


def _save_metadata(files_db: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Upsert metadata (whitelisted fields only). Returns the stored row."""
    _ensure_metadata_table(files_db)
    now = int(datetime.now(tz=timezone.utc).timestamp())
    values = {k: payload.get(k) for k in _METADATA_FIELDS}
    # Never persist raw None — normalize to empty string for display parity.
    clean = {k: ("" if v is None else str(v)) for k, v in values.items()}
    try:
        with _connect_rw(Path(files_db)) as conn:
            col_sql = ", ".join(f'"{c}"' for c in _METADATA_FIELDS)
            placeholders = ", ".join("?" for _ in _METADATA_FIELDS)
            update_assigns = ", ".join(f'"{c}" = excluded."{c}"' for c in _METADATA_FIELDS)
            conn.execute(
                f'INSERT INTO "report_metadata" (task_id, {col_sql}, updated_at) '
                f'VALUES (?, {placeholders}, ?) '
                f'ON CONFLICT(task_id) DO UPDATE SET {update_assigns}, updated_at = excluded.updated_at',
                (task_id, *clean.values(), now),
            )
            conn.commit()
    except sqlite3.Error as exc:
        logger.warning("save report_metadata failed: %s", exc)
        raise HTTPException(status_code=503, detail="could not persist report metadata")
    stored = _load_metadata(files_db, task_id)
    stored["updated_at"] = now
    return stored


# ── platform detection ──────────────────────────────────────────────────────


def _detect_platforms(files_db: str | None) -> list[str]:
    """Detect which platform artifact tables exist in _files.db."""
    platforms: list[str] = []
    if not files_db or not Path(files_db).is_file():
        return platforms
    android_markers = ("contacts", "sms_messages", "call_logs", "installed_packages",
                       "system_build_properties", "device_identifiers")
    windows_markers = ("windows_services", "registry_values", "user_accounts",
                       "mft_entries", "amcache_entries", "scheduled_tasks")
    linux_markers = ("linux_users", "linux_packages", "linux_login_records",
                     "linux_shell_history", "linux_systemd_services")
    try:
        with _connect_ro(Path(files_db)) as conn:
            tables = {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()}
            if any(t in tables for t in android_markers):
                platforms.append("android")
            if any(t in tables for t in windows_markers):
                platforms.append("windows")
            if any(t in tables for t in linux_markers):
                platforms.append("linux")
    except sqlite3.Error as exc:
        logger.warning("platform detect failed: %s", exc)
    return platforms


# ── per-category data readers (table-presence-aware, never 404) ──────────────


def _device_info_records(files_db: str | None) -> list[dict[str, Any]]:
    """Read device basic info from build properties / identifiers / OS tables.

    Returns ONE synthesized record: the 39 reference-report items, each value
    resolved (first hit wins) from available property/identifier sources. Missing
    values stay empty to preserve display parity.
    """
    if not files_db or not Path(files_db).is_file():
        return []
    props: dict[str, str] = {}
    try:
        with _connect_ro(Path(files_db)) as conn:
            # Android: system_build_properties (key/value) + device_identifiers
            if _table_exists(conn, "system_build_properties"):
                for key, value in conn.execute(
                    'SELECT property_key, property_value FROM "system_build_properties"'
                ).fetchall():
                    if value is not None and key not in props:
                        props[key] = str(value)
            if _table_exists(conn, "device_identifiers"):
                for itype, value in conn.execute(
                    'SELECT identifier_type, value FROM "device_identifiers"'
                ).fetchall():
                    if value is not None:
                        props.setdefault(str(itype), str(value))
            # Windows: registry_values holds OS build info under known value names.
            if _table_exists(conn, "registry_values"):
                for row in conn.execute(
                    'SELECT value_name, data FROM "registry_values" '
                    'WHERE value_name IN ("ProductName","OSVersion","ProductModel",'
                    '"Manufacturer","DeviceId","BuildLab")'
                ).fetchall():
                    name, data = row[0], row[1]
                    if data is not None:
                        props.setdefault(str(name), str(data))
            # Linux: os_config_files may carry version lines; best-effort.
            if _table_exists(conn, "os_config_files") and "file_path" in _table_columns(conn, "os_config_files"):
                pass  # no structured OS fields; left to build props if present
    except sqlite3.Error as exc:
        logger.warning("device_info read failed: %s", exc)
        return []
    record: dict[str, Any] = {}
    for label, *keys in _DEVICE_INFO_ITEMS:
        value = ""
        for k in keys:
            if k in props and props[k]:
                value = props[k]
                break
        record[label] = value
    # Always emit a record (even all-empty) so the section renders placeholders.
    return [record]


def _generic_table_records(
    files_db: str | None, table: str, fields: tuple[str, ...],
    order_by: str | None, page: int, page_size: int, category: str,
) -> RecordPage:
    """Read a platform artifact table; return empty page if table absent."""
    if not files_db or not Path(files_db).is_file() or not table:
        return RecordPage(category=category, page=1, page_size=page_size,
                          total=0, total_pages=1, records=[])
    try:
        with _connect_ro(Path(files_db)) as conn:
            if not _table_exists(conn, table):
                return RecordPage(category=category, page=1, page_size=page_size,
                                  total=0, total_pages=1, records=[])
            rows, total = _fetch_rows(conn, table, fields, order_by, page, page_size)
            page, page_size, total_pages = _paginated(total, page, page_size)
            records = [{**r, "_category": category} for r in rows]
            return RecordPage(category=category, page=page, page_size=page_size,
                              total=total, total_pages=total_pages, records=records)
    except sqlite3.Error as exc:
        logger.warning("%s read failed: %s", category, exc)
        return RecordPage(category=category, page=1, page_size=page_size,
                          total=0, total_pages=1, records=[])


def _category_total(files_db: str | None, table: str) -> int:
    """Row count of an artifact table (0 if absent/unreadable)."""
    if not files_db or not Path(files_db).is_file() or not table:
        return 0
    try:
        with _connect_ro(Path(files_db)) as conn:
            if not _table_exists(conn, table):
                return 0
            return _count(conn, table)
    except sqlite3.Error:
        return 0


def _resolve_apps_table(files_db: str | None) -> str:
    if not files_db or not Path(files_db).is_file():
        return ""
    try:
        with _connect_ro(Path(files_db)) as conn:
            for t in ("installed_packages", "system_apps"):
                if _table_exists(conn, t):
                    return t
    except sqlite3.Error:
        pass
    return ""


def _resolve_locations_table(files_db: str | None) -> str:
    """Resolve a real GPS-bearing locations table, if any.

    NOTE: the generic `images` table is intentionally NOT used — it is a file
    classifier table (name/path/size/md5) with no latitude/longitude columns.
    The reference report's 位置信息 comes from photo EXIF GPS, which TraceLens
    does not currently extract into a dedicated table. When none exists, the
    section renders a placeholder (total 0) rather than mislabeling plain
    image file rows as location data.
    """
    if not files_db or not Path(files_db).is_file():
        return ""
    try:
        with _connect_ro(Path(files_db)) as conn:
            for t in ("image_locations", "locations", "geo_locations",
                      "exif_locations", "wifi_networks"):
                if _table_exists(conn, t):
                    # verify it actually carries coordinate columns
                    cols = _table_columns(conn, t)
                    if {"latitude", "longitude"} & cols or t == "wifi_networks":
                        return t
    except sqlite3.Error:
        pass
    return ""


# ── platform section registry ───────────────────────────────────────────────
# Each entry: (platform, section_id, title, source_table, fields, order_by).
# The directory builder only emits sections whose platform is detected; within
# a detected platform, every section is shown (total 0 → placeholder), mirroring
# the reference report's "full schema always visible" semantics.
#
# `fields` is the ordered tuple of columns to select; missing columns are
# dropped at read time by _select_columns, so a partial table still renders.
# `source_table` may be a callable (files_db) -> table for fallback resolution.

_PlatformSection = tuple  # (platform, section_id, title, source_table, fields, order_by)

_PLATFORM_SECTIONS: list[_PlatformSection] = [
    # ── Android (mobile) ──
    ("android", "contacts", "通讯录", "contacts",
     ("display_name", "phone_number", "email", "account_type", "account_name"),
     "display_name"),
    ("android", "sms", "短信息", "sms_messages",
     ("thread_id", "address", "person", "date", "date_sent", "type", "body",
      "status", "service_center"),
     "date"),
    ("android", "call_logs", "通话记录", "call_logs",
     ("number", "date", "duration", "type", "name", "geocoded_location"),
     "date"),
    ("android", "locations", "位置信息", _resolve_locations_table,
     ("file_name", "file_path", "latitude", "longitude", "ssid",
      "created_time", "modified_time", "file_size"),
     "file_name"),
    ("android", "apps", "程序列表", _resolve_apps_table,
     ("package_name", "display_name", "name", "code_path", "apk_path", "version",
      "version_name", "installer", "is_system_app",
      "first_install_time", "last_update_time", "native_library_path"),
     "package_name"),

    # ── Windows (computer) ──
    ("windows", "win_users", "用户账户", "user_accounts",
     ("username", "full_name", "rid", "is_admin", "last_login",
      "password_last_set", "account_flags", "home_directory", "comment"),
     "username"),
    ("windows", "win_usb", "USB设备", "usb_devices",
     ("device_description", "friendly_name", "vendor_id", "product_id",
      "serial_number", "first_connected", "last_connected", "last_drive_letter"),
     "last_connected"),
    ("windows", "win_browser", "浏览器历史", "browser_history",
     ("browser_name", "profile_name", "url", "title", "visit_time",
      "visit_count", "visit_type", "referrer"),
     "visit_time"),
    ("windows", "win_downloads", "浏览器下载", "browser_downloads",
     ("browser_name", "url", "target_path", "file_name", "file_size",
      "start_time", "end_time", "state", "received_bytes"),
     "start_time"),
    ("windows", "win_bookmarks", "浏览器书签", "browser_bookmarks",
     ("browser_name", "title", "url", "folder_path", "date_added", "date_modified"),
     "date_added"),
    ("windows", "win_services", "系统服务", "windows_services",
     ("service_name", "display_name", "image_path", "start_type",
      "service_type", "account_name", "is_running", "description"),
     "service_name"),
    ("windows", "win_scheduled_tasks", "计划任务", "scheduled_tasks",
     ("task_name", "task_path", "author", "action_type", "action_path",
      "arguments", "trigger_type", "last_run_time", "next_run_time", "status", "run_as"),
     "task_name"),
    ("windows", "win_prefetch", "预读取文件", "prefetch_files",
     ("executable_name", "executable_path", "run_count", "last_run_time",
      "creation_time", "prefetch_hash"),
     "last_run_time"),
    ("windows", "win_event_logs", "事件日志", "event_logs",
     ("event_id", "level", "log_source", "timestamp", "source",
      "computer_name", "user_sid", "channel", "message"),
     "timestamp"),
    ("windows", "win_recycle_bin", "回收站", "recycle_bin",
     ("file_name", "original_path", "recycle_file_path", "deletion_time",
      "original_size", "user_sid"),
     "deletion_time"),
    ("windows", "win_rdp", "RDP连接", "rdp_connections",
     ("server_address", "username_hint", "last_connection_time", "entry_type"),
     "last_connection_time"),
    ("windows", "win_installed_apps", "已安装程序", "amcache_entries",
     ("file_name", "product_name", "product_version", "company_name",
      "file_description", "file_path", "file_hash", "file_size", "link_time"),
     "file_name"),
    ("windows", "win_userassist", "用户活动(UserAssist)", "user_assist_entries",
     ("user_sid", "decoded_path", "rot13_path", "run_count", "focus_time",
      "last_run_time"),
     "last_run_time"),
    ("windows", "win_logins", "浏览器保存密码", "browser_logins",
     ("browser_name", "url", "username", "times_used", "date_created", "date_last_used"),
     "date_last_used"),

    # ── Linux (server) ──
    ("linux", "linux_users", "用户账户", "linux_users",
     ("username", "uid", "gid", "full_name", "home_directory", "shell",
      "is_locked", "last_password_change", "account_expires"),
     "username"),
    ("linux", "linux_login", "登录记录", "linux_login_records",
     ("username", "terminal", "remote_host", "login_time", "logout_time",
      "login_type", "is_success", "pid"),
     "login_time"),
    ("linux", "linux_shell", "Shell历史", "linux_shell_history",
     ("username", "shell_type", "command", "timestamp", "line_number", "history_file"),
     "timestamp"),
    ("linux", "linux_services", "系统服务", "linux_systemd_services",
     ("service_name", "description", "load_state", "active_state", "sub_state",
      "is_enabled", "exec_start", "user", "unit_file"),
     "service_name"),
    ("linux", "linux_network", "网络连接", "linux_network_connections",
     ("protocol", "local_address", "local_port", "remote_address", "remote_port",
      "state", "uid", "process", "pid"),
     "state"),
    ("linux", "linux_cron", "计划任务(Cron)", "linux_cron_jobs",
     ("username", "minute", "hour", "day_of_month", "month", "day_of_week",
      "command", "cron_file", "cron_type"),
     "username"),
    ("linux", "linux_audit", "审计事件", "linux_audit_events",
     ("timestamp", "event_id", "syscall_name", "success", "exit_code",
      "uid", "auid", "pid", "ppid"),
     "timestamp"),
    ("linux", "linux_packages", "已安装包", "linux_packages",
     ("name", "version", "architecture", "package_manager", "status",
      "install_time", "description", "maintainer"),
     "name"),
    ("linux", "linux_anomalies", "安全异常", "linux_anomalies",
     ("anomaly_type", "anomaly_subtype", "severity", "confidence", "description",
      "mitigation", "detected_at"),
     "detected_at"),
    ("linux", "linux_ssh_keys", "SSH密钥", "linux_ssh_keys",
     ("key_type", "fingerprint", "comment", "key_path", "bit_length"),
     "key_path"),
    ("linux", "linux_firewall", "防火墙规则", "linux_firewall_rules",
     ("chain", "target", "protocol", "source", "destination", "port", "interface"),
     "chain"),
]


def _section_table(section: _PlatformSection, files_db: str | None) -> str:
    """Resolve the source table for a section (handles callable fallbacks)."""
    table = section[3]
    if callable(table):
        return table(files_db)
    return table


def _platform_sections_for(platforms: list[str], files_db: str | None) -> list[_PlatformSection]:
    """Sections to show for the detected platforms (deduped by section_id)."""
    seen: set[str] = set()
    out: list[_PlatformSection] = []
    for sec in _PLATFORM_SECTIONS:
        if sec[0] not in platforms:
            continue
        if sec[1] in seen:
            continue
        seen.add(sec[1])
        out.append(sec)
    return out


def _section_total(section: _PlatformSection, files_db: str | None) -> int:
    return _category_total(files_db, _section_table(section, files_db))


# ── device info per platform (synthesized records) ──────────────────────────


def _win_device_info_records(files_db: str | None) -> list[dict[str, Any]]:
    """Windows 设备/系统信息: OS build info from registry + machine account."""
    if not files_db or not Path(files_db).is_file():
        return [{}]
    props: dict[str, str] = {}
    try:
        with _connect_ro(Path(files_db)) as conn:
            if _table_exists(conn, "registry_values"):
                # Pull the canonical OS identification values.
                names = ("ProductName", "OSVersion", "CurrentBuild", "ReleaseId",
                         "InstallDate", "RegisteredOrganization",
                         "RegisteredOwner", "ComputerName", "DigitalProductId")
                placeholders = ",".join("?" for _ in names)
                for row in conn.execute(
                    f'SELECT value_name, value_data FROM "registry_values" '
                    f'WHERE value_name IN ({placeholders})', names,
                ).fetchall():
                    name, data = row[0], row[1]
                    if data is not None:
                        props.setdefault(str(name), str(data))
            if _table_exists(conn, "user_accounts"):
                cnt = _count(conn, "user_accounts")
                if cnt:
                    props.setdefault("用户账户数", str(cnt))
    except sqlite3.Error as exc:
        logger.warning("win_device_info read failed: %s", exc)
    labels = [
        ("操作系统", "ProductName"),
        ("系统版本", "OSVersion"),
        ("内部版本号", "CurrentBuild"),
        ("版本号", "ReleaseId"),
        ("安装时间", "InstallDate"),
        ("注册组织", "RegisteredOrganization"),
        ("注册所有者", "RegisteredOwner"),
        ("计算机名", "ComputerName"),
        ("用户账户数", "用户账户数"),
    ]
    return [{label: props.get(key, "") for label, key in labels}]


def _linux_device_info_records(files_db: str | None) -> list[dict[str, Any]]:
    """Linux 系统/主机信息: best-effort from os_config_files + user count."""
    if not files_db or not Path(files_db).is_file():
        return [{}]
    props: dict[str, str] = {}
    try:
        with _connect_ro(Path(files_db)) as conn:
            # os_config_files: file_path/file_content-style rows; look for release files.
            if _table_exists(conn, "os_config_files"):
                cols = _table_columns(conn, "os_config_files")
                # Different schemas name columns differently; try common ones.
                path_col = "file_path" if "file_path" in cols else (
                    "name" if "name" in cols else None)
                content_col = "content" if "content" in cols else (
                    "value" if "value" in cols else None)
                if path_col and content_col:
                    for p, c in conn.execute(
                        f'SELECT "{path_col}", "{content_col}" FROM "os_config_files" '
                        f'WHERE "{path_col}" LIKE "%release%" OR '
                        f'"{path_col}" LIKE "%os-release%" OR '
                        f'"{path_col}" LIKE "%issue%" LIMIT 20',
                    ).fetchall():
                        if c:
                            props.setdefault(str(Path(str(p)).name), str(c))
            if _table_exists(conn, "linux_users"):
                cnt = _count(conn, "linux_users")
                if cnt:
                    props.setdefault("用户账户数", str(cnt))
    except sqlite3.Error as exc:
        logger.warning("linux_device_info read failed: %s", exc)
    record = {
        "主机名": props.get("hostname", ""),
        "发行版": props.get("os-release", props.get("release", "")),
        "系统版本": props.get("issue", ""),
        "用户账户数": props.get("用户账户数", ""),
    }
    # Fold any extra release files into the record too.
    for k, v in props.items():
        if k not in record:
            record[k] = v
    return [record]


# ── service resolution ───────────────────────────────────────────────────────


async def _resolve_task(task_id: str) -> tuple[dict[str, Any], str | None, str | None]:
    from ..services import get_service_manager

    service_manager = get_service_manager()
    task = await service_manager.cpp_backend.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")

    files_db = task.get("output_files_db") or None
    events_db = task.get("output_events_db") or None
    return task, files_db, events_db


def _title(task: dict[str, Any], task_id: str) -> str:
    image = task.get("image_path") or task_id
    return f"{Path(image).name} 证据研判报告"


# ── files stats ──────────────────────────────────────────────────────────────


def _files_stats(files_db: str | None) -> DirectoryNodeStats:
    if not files_db or not Path(files_db).is_file():
        return DirectoryNodeStats()
    try:
        with _connect_ro(Path(files_db)) as conn:
            if not _table_exists(conn, "files"):
                return DirectoryNodeStats()
            total = _count(conn, "files")
            deleted = int(conn.execute(
                'SELECT COUNT(*) FROM "files" WHERE COALESCE(is_deleted, 0) = 1'
            ).fetchone()[0])
            relevant = int(conn.execute(
                'SELECT COUNT(*) FROM "files" WHERE COALESCE(scene_relevant, 0) = 1 '
                'OR COALESCE(scene_priority, 0) > 0'
            ).fetchone()[0])
            return DirectoryNodeStats(total=total, deleted=deleted, relevant=relevant)
    except sqlite3.Error as exc:
        logger.warning("intelligence-report files stats failed: %s", exc)
        return DirectoryNodeStats()


def _events_stats(events_db: str | None) -> DirectoryNodeStats:
    if not events_db or not Path(events_db).is_file():
        return DirectoryNodeStats()
    try:
        with _connect_ro(Path(events_db)) as conn:
            if not _table_exists(conn, "events"):
                return DirectoryNodeStats()
            total = _count(conn, "events")
            relevant = int(conn.execute(
                'SELECT COUNT(*) FROM "events" WHERE COALESCE(llm_is_relevant, 0) = 1'
            ).fetchone()[0])
            return DirectoryNodeStats(total=total, relevant=relevant)
    except sqlite3.Error as exc:
        logger.warning("intelligence-report events stats failed: %s", exc)
        return DirectoryNodeStats()


# ── five-chapter intelligence report ─────────────────────────────────────────

_CHAPTERS = (
    ("analysis.overview", "案件概述", "案件概述"),
    ("analysis.timeline", "时间线梳理", "时间线梳理"),
    ("analysis.evidence", "证据分析", "证据分析"),
    ("analysis.findings", "关键发现", "关键发现"),
    ("analysis.conclusion", "结论与建议", "结论与建议"),
)


def _load_chapter_markdown(files_db: str | None) -> dict[str, str]:
    """Split the legacy case_analysis.case_report by the known chapter headings."""
    result: dict[str, str] = {}
    if not files_db or not Path(files_db).is_file():
        return result
    try:
        with _connect_ro(Path(files_db)) as conn:
            if not _table_exists(conn, "case_analysis"):
                return result
            row = conn.execute(
                'SELECT case_report FROM "case_analysis" ORDER BY updated_at DESC LIMIT 1'
            ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("intelligence-report chapter load failed: %s", exc)
        return result
    if not row or not row[0]:
        return result

    markdown = row[0]
    splits: list[tuple[str, str]] = []
    positions = []
    lower = markdown.lower()
    cursor = 0
    for key, _, heading in _CHAPTERS:
        # match either '# heading' or '## heading' (case-insensitive)
        needle_lower = f"# {heading.lower()}"
        idx = lower.find(needle_lower, cursor)
        if idx == -1:
            idx = lower.find(heading.lower(), cursor)
        if idx == -1:
            continue
        positions.append((key, idx))
        cursor = idx + len(heading)
    if not positions:
        # no headings found: keep whole text under first chapter
        result[_CHAPTERS[0][0]] = markdown
        return result

    for i, (key, start) in enumerate(positions):
        end = positions[i + 1][1] if i + 1 < len(positions) else len(markdown)
        result[key] = markdown[start:end].strip()
    # text before the first detected heading goes into overview as preamble
    preamble = markdown[: positions[0][1]].strip()
    if preamble:
        result.setdefault(_CHAPTERS[0][0], "")
        result[_CHAPTERS[0][0]] = (preamble + "\n\n" + result[_CHAPTERS[0][0]]).strip()
    return result


def _analysis_directory(chapters: dict[str, str]) -> list[DirectoryNode]:
    return [
        DirectoryNode(id=key, title=title, kind="chapter")
        for key, title, _heading in _CHAPTERS
        if key in chapters
    ]


def _generated_at(files_db: str | None) -> str | None:
    if not files_db or not Path(files_db).is_file():
        return None
    try:
        with _connect_ro(Path(files_db)) as conn:
            if not _table_exists(conn, "case_analysis"):
                return None
            row = conn.execute(
                'SELECT updated_at FROM "case_analysis" ORDER BY updated_at DESC LIMIT 1'
            ).fetchone()
    except sqlite3.Error:
        return None
    if not row or row[0] is None:
        return None
    try:
        return datetime.fromtimestamp(int(row[0]), tz=timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return str(row[0])


# ── routes ───────────────────────────────────────────────────────────────────


@router.get(
    "/intelligence-report/{task_id}",
    response_model=IntelligenceReportResponse,
)
async def get_intelligence_report(task_id: str) -> IntelligenceReportResponse:
    task, files_db, events_db = await _resolve_task(task_id)
    chapters = _load_chapter_markdown(files_db)
    platforms = _detect_platforms(files_db)

    directory: list[DirectoryNode] = [
        DirectoryNode(id="overview", title="报告概览", kind="overview"),
        DirectoryNode(id="case", title="案件信息", kind="case"),
        DirectoryNode(id="evidence_info", title="证据信息", kind="evidence_info"),
    ]

    # Device/system info section — platform-specific id, always present for the
    # detected platform(s) so placeholders render even when data is empty.
    if "android" in platforms:
        directory.append(DirectoryNode(id="device_info", title="设备基本信息", kind="device_info"))
    if "windows" in platforms:
        directory.append(DirectoryNode(id="win_device_info", title="系统信息", kind="device_info"))
    if "linux" in platforms:
        directory.append(DirectoryNode(id="linux_device_info", title="系统信息", kind="device_info"))
    # If no platform detected, still show a generic device info placeholder.
    if not {"android", "windows", "linux"} & set(platforms):
        directory.append(DirectoryNode(id="device_info", title="设备基本信息", kind="device_info"))

    # Platform-specific artifact sections (only the detected platform's set).
    for sec in _platform_sections_for(platforms, files_db):
        _, section_id, title, _table, _fields, _order = sec
        directory.append(DirectoryNode(
            id=section_id, title=title, kind="records",
            stats=DirectoryNodeStats(total=_section_total(sec, files_db)),
        ))

    directory.extend([
        DirectoryNode(id="evidence.files", title="文件证据", kind="records",
                      stats=_files_stats(files_db)),
        DirectoryNode(id="timeline", title="时间线", kind="records",
                      stats=_events_stats(events_db)),
        *_analysis_directory(chapters),
    ])

    return IntelligenceReportResponse(
        scope_type="task",
        scope_id=task_id,
        metadata=IntelligenceReportMetadata(
            task_id=task_id,
            title=_title(task, task_id),
            image_path=task.get("image_path"),
            files_db=files_db,
            events_db=events_db,
            generated_at=_generated_at(files_db),
            platforms=platforms,
        ),
        directory=directory,
    )


def _paginated(
    total: int, page: int, page_size: int
) -> tuple[int, int, int]:
    page = max(1, page)
    page_size = max(1, min(page_size, 200))
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(page, total_pages)
    return page, page_size, total_pages


@router.get(
    "/intelligence-report/{task_id}/records",
    response_model=RecordPage,
)
async def get_intelligence_records(
    task_id: str,
    category: str = Query(
        ..., description="evidence.files | timeline | analysis.* | device_info | "
                         "win_device_info | linux_device_info | <platform section id>"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> RecordPage:
    _task, files_db, events_db = await _resolve_task(task_id)

    if category == "evidence.files":
        return await _files_records(files_db, page, page_size)
    if category == "timeline":
        return await _event_records(events_db, page, page_size)
    if category.startswith("analysis."):
        return await _chapter_records(files_db, category, page, page_size)

    # ── synthesized device/system info sections (one synthesized record) ──
    if category == "device_info":
        return RecordPage(category="device_info", page=1, page_size=page_size,
                          total=1, total_pages=1,
                          records=_device_info_records(files_db))
    if category == "win_device_info":
        return RecordPage(category="win_device_info", page=1, page_size=page_size,
                          total=1, total_pages=1,
                          records=_win_device_info_records(files_db))
    if category == "linux_device_info":
        return RecordPage(category="linux_device_info", page=1, page_size=page_size,
                          total=1, total_pages=1,
                          records=_linux_device_info_records(files_db))

    # ── SMS keeps its specialized thread view ──
    if category == "sms":
        return _generic_table_records(
            files_db, "sms_messages",
            ("thread_id", "address", "person", "date", "date_sent",
             "type", "body", "status", "service_center"),
            "date", page, page_size, "sms")

    # ── generic platform artifact sections via the registry ──
    for sec in _PLATFORM_SECTIONS:
        if sec[1] == category:
            _platform, section_id, title, table, fields, order_by = sec
            resolved = _section_table(sec, files_db)
            return _generic_table_records(
                files_db, resolved, fields, order_by, page, page_size, section_id)

    raise HTTPException(status_code=404, detail=f"unknown category: {category}")


async def _files_records(
    files_db: str | None, page: int, page_size: int
) -> RecordPage:
    if not files_db or not Path(files_db).is_file():
        return RecordPage(category="evidence.files", page=1, page_size=page_size,
                          total=0, total_pages=1, records=[])
    try:
        with _connect_ro(Path(files_db)) as conn:
            if not _table_exists(conn, "files"):
                return RecordPage(category="evidence.files", page=1, page_size=page_size,
                                  total=0, total_pages=1, records=[])
            total = _count(conn, "files")
            page, page_size, total_pages = _paginated(total, page, page_size)
            columns = [c for c in _FILE_FIELDS if c in _table_columns(conn, "files")]
            col_sql = ", ".join(f'"{c}"' for c in columns)
            offset = (page - 1) * page_size
            rows = conn.execute(
                f'SELECT {col_sql} FROM "files" ORDER BY id LIMIT ? OFFSET ?',
                (page_size, offset),
            ).fetchall()
            records = [
                {**_row_to_record(row, columns), "_category": "evidence.files"}
                for row in rows
            ]
            return RecordPage(
                category="evidence.files", page=page, page_size=page_size,
                total=total, total_pages=total_pages, records=records,
            )
    except sqlite3.Error as exc:
        logger.warning("intelligence-report files page failed: %s", exc)
        raise HTTPException(status_code=503, detail="evidence database unavailable")


async def _event_records(
    events_db: str | None, page: int, page_size: int
) -> RecordPage:
    if not events_db or not Path(events_db).is_file():
        return RecordPage(category="timeline", page=1, page_size=page_size,
                          total=0, total_pages=1, records=[])
    try:
        with _connect_ro(Path(events_db)) as conn:
            if not _table_exists(conn, "events"):
                return RecordPage(category="timeline", page=1, page_size=page_size,
                                  total=0, total_pages=1, records=[])
            total = _count(conn, "events")
            page, page_size, total_pages = _paginated(total, page, page_size)
            columns = [c for c in _EVENT_FIELDS if c in _table_columns(conn, "events")]
            col_sql = ", ".join(f'"{c}"' for c in columns)
            offset = (page - 1) * page_size
            rows = conn.execute(
                f'SELECT {col_sql} FROM "events" ORDER BY timestamp DESC LIMIT ? OFFSET ?',
                (page_size, offset),
            ).fetchall()
            records = [
                {**_row_to_record(row, columns), "_category": "timeline"}
                for row in rows
            ]
            return RecordPage(
                category="timeline", page=page, page_size=page_size,
                total=total, total_pages=total_pages, records=records,
            )
    except sqlite3.Error as exc:
        logger.warning("intelligence-report events page failed: %s", exc)
        raise HTTPException(status_code=503, detail="timeline database unavailable")


async def _chapter_records(
    files_db: str | None, category: str, page: int, page_size: int
) -> RecordPage:
    chapters = _load_chapter_markdown(files_db)
    markdown = chapters.get(category, "")
    if not markdown:
        return RecordPage(category=category, page=1, page_size=page_size,
                          total=0, total_pages=1, records=[])
    # Chapters are single-record "pages"; pagination collapses to one page.
    return RecordPage(
        category=category, page=1, page_size=page_size,
        total=1, total_pages=1,
        records=[{"_category": category, "markdown": markdown, "title": _chapter_title(category)}],
    )


def _chapter_title(category: str) -> str:
    for key, title, _ in _CHAPTERS:
        if key == category:
            return title
    return category


@router.get(
    "/intelligence-report/{task_id}/search",
    response_model=SearchResponse,
)
async def search_intelligence_report(
    task_id: str,
    q: str = Query(..., min_length=1),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> SearchResponse:
    _task, files_db, events_db = await _resolve_task(task_id)
    hits: list[SearchHit] = []
    pattern = f"%{q}%"

    if files_db and Path(files_db).is_file():
        try:
            with _connect_ro(Path(files_db)) as conn:
                if _table_exists(conn, "files"):
                    cols = _table_columns(conn, "files")
                    searchable = [c for c in ("name", "path", "category", "md5") if c in cols]
                    if searchable:
                        where = " OR ".join(f'"{c}" LIKE ?' for c in searchable)
                        rows = conn.execute(
                            f'SELECT id, path, name FROM "files" WHERE {where} LIMIT ? OFFSET ?',
                            (*[pattern] * len(searchable), limit, offset),
                        ).fetchall()
                        for rid, path, name in rows:
                            hits.append(SearchHit(
                                category="evidence.files",
                                page=1,
                                record_id=str(rid),
                                title=path or name or str(rid),
                            ))
        except sqlite3.Error as exc:
            logger.warning("intelligence-report search files failed: %s", exc)

    if events_db and Path(events_db).is_file():
        try:
            with _connect_ro(Path(events_db)) as conn:
                if _table_exists(conn, "events"):
                    cols = _table_columns(conn, "events")
                    searchable = [c for c in ("file_path", "description", "event_type") if c in cols]
                    if searchable:
                        where = " OR ".join(f'"{c}" LIKE ?' for c in searchable)
                        rows = conn.execute(
                            f'SELECT id, file_path FROM "events" WHERE {where} LIMIT ? OFFSET ?',
                            (*[pattern] * len(searchable), limit, offset),
                        ).fetchall()
                        for rid, path in rows:
                            hits.append(SearchHit(
                                category="timeline",
                                page=1,
                                record_id=str(rid),
                                title=path or str(rid),
                            ))
        except sqlite3.Error as exc:
            logger.warning("intelligence-report search events failed: %s", exc)

    return SearchResponse(total=len(hits), offset=offset, limit=limit, hits=hits)


# ── report metadata (case info + evidence info) ──────────────────────────────


class ReportMetadataResponse(BaseModel):
    task_id: str
    metadata: dict[str, Any]
    updated_at: int | None = None


class ReportMetadataUpdate(BaseModel):
    """Editable forensic metadata. All fields optional; unknown keys ignored."""
    case_name: str | None = None
    case_number: str | None = None
    case_type: str | None = None
    law_case_number: str | None = None
    law_case_category: str | None = None
    law_case_name: str | None = None
    collector_name: str | None = None
    collector_id: str | None = None
    collector_id_card: str | None = None
    collector_unit: str | None = None
    submitter1_name: str | None = None
    submitter1_id: str | None = None
    submitter2_name: str | None = None
    submitter2_id: str | None = None
    submitter_unit: str | None = None
    inspection_number: str | None = None
    alarm_id: str | None = None
    alarm_code: str | None = None
    remarks: str | None = None
    evidence_name: str | None = None
    evidence_number: str | None = None
    phone1: str | None = None
    phone2: str | None = None
    holder: str | None = None
    holder_id: str | None = None
    holder_type: str | None = None
    id_type: str | None = None
    id_number: str | None = None
    extract_start: str | None = None
    extract_end: str | None = None
    evidence_remarks: str | None = None
    holder_gender: str | None = None
    holder_ethnicity: str | None = None
    birth_date: str | None = None
    current_address: str | None = None
    registered_address: str | None = None
    id_issue_authority: str | None = None
    id_valid_from: str | None = None
    id_valid_to: str | None = None


@router.get(
    "/intelligence-report/{task_id}/metadata",
    response_model=ReportMetadataResponse,
)
async def get_report_metadata(task_id: str) -> ReportMetadataResponse:
    """Return case-info + evidence-info metadata (all fields, empty if unset)."""
    _task, files_db, _events_db = await _resolve_task(task_id)
    metadata = _load_metadata(files_db, task_id)
    return ReportMetadataResponse(task_id=task_id, metadata=metadata)


@router.put(
    "/intelligence-report/{task_id}/metadata",
    response_model=ReportMetadataResponse,
)
async def update_report_metadata(
    task_id: str, payload: ReportMetadataUpdate
) -> ReportMetadataResponse:
    """Upsert editable forensic metadata. Returns the stored row."""
    _task, files_db, _events_db = await _resolve_task(task_id)
    if not files_db or not Path(files_db).is_file():
        raise HTTPException(status_code=503, detail="task files database unavailable")
    stored = _save_metadata(files_db, task_id, payload.model_dump(exclude_unset=True))
    updated_at = stored.pop("updated_at", None)
    return ReportMetadataResponse(task_id=task_id, metadata=stored, updated_at=updated_at)
