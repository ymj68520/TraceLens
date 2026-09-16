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
from typing import Any, NamedTuple
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
#
# Fields are seeded ONCE from the analysis itself (see _derive_metadata): a
# value the analyst has not touched is reported back in auto_fields and shown
# with an [自动] badge. User edits always win and are never auto-overwritten.

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
    -- auto-seed bookkeeping
    auto_seeded_at INTEGER,
    auto_fields TEXT,
    updated_at INTEGER
)
"""

# Columns that are not user-editable metadata but are managed by the seed logic.
_METADATA_BOOKKEEPING: tuple[tuple[str, str], ...] = (
    ("auto_seeded_at", "INTEGER"),
    ("auto_fields", "TEXT"),
)

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
# Android-only. Each item: (display_label, lookup_keys...) — lookup_keys are
# tried in order against build properties / device identifiers / MIUI manifest
# values to populate the row. Windows and Linux have their own label sets in
# _WIN_REGISTRY_FIELDS and _LINUX_DEVICE_COUNTS.
_DEVICE_INFO_ITEMS = (
    ("设备名称", "ro.product.name"),
    ("系统版本", "ro.build.version.release"),
    ("设备型号", "ro.product.model"),
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

# Fields a MIUI / Android *backup* can actually supply. Chosen so the section
# shows only real values instead of the full image-oriented schema above.
_ANDROID_BACKUP_ITEMS = (
    ("设备型号", "ro.product.model"),
    ("系统版本", "ro.build.version.release"),
    ("备份日期", "备份日期"),
    ("数据总量", "数据总量"),
    ("应用数", "应用数"),
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
    """Create report_metadata (idempotent) and add any missing columns.

    CREATE TABLE IF NOT EXISTS leaves a table from an earlier build untouched,
    and SQLite has no ADD COLUMN IF NOT EXISTS — so reconcile every expected
    column explicitly. Adding a column is safe and lossless; an existing row
    keeps its values and simply gets NULL for the new ones.
    """
    if not files_db or not Path(files_db).is_file():
        return
    expected = [(field, "TEXT") for field in _METADATA_FIELDS]
    expected.extend(_METADATA_BOOKKEEPING)
    expected.append(("updated_at", "INTEGER"))
    try:
        with _connect_rw(Path(files_db)) as conn:
            conn.executescript(_METADATA_CREATE)
            existing = _table_columns(conn, "report_metadata")
            for column, column_type in expected:
                if column not in existing:
                    conn.execute(
                        f'ALTER TABLE "report_metadata" ADD COLUMN "{column}" {column_type}'
                    )
            conn.commit()
    except sqlite3.Error as exc:
        logger.warning("ensure report_metadata failed: %s", exc)


def _decode_auto_fields(raw: Any) -> list[str]:
    """Auto-filled field names from the stored JSON array (never raises)."""
    if not raw:
        return []
    if isinstance(raw, list):
        decoded = raw
    else:
        try:
            decoded = json.loads(str(raw))
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
    if not isinstance(decoded, list):
        return []
    return [str(f) for f in decoded if str(f) in _METADATA_FIELDS]


def _load_metadata_state(
    files_db: str | None, task_id: str
) -> tuple[dict[str, Any], int | None, list[str]]:
    """Metadata row plus its auto-seed bookkeeping.

    Returns (fields, auto_seeded_at, auto_fields). All-empty when no row exists.
    """
    metadata = _empty_metadata()
    if not files_db or not Path(files_db).is_file():
        return metadata, None, []
    try:
        with _connect_ro(Path(files_db)) as conn:
            if not _table_exists(conn, "report_metadata"):
                return metadata, None, []
            table_cols = _table_columns(conn, "report_metadata")
            cols = [c for c in _METADATA_FIELDS if c in table_cols]
            if not cols:
                return metadata, None, []
            col_sql = ", ".join(f'"{c}"' for c in cols)
            bookkeeping = [c for c in ("auto_seeded_at", "auto_fields") if c in table_cols]
            extra_sql = "".join(f', "{c}"' for c in bookkeeping)
            row = conn.execute(
                f'SELECT {col_sql}{extra_sql} FROM "report_metadata" WHERE task_id = ?',
                (task_id,),
            ).fetchone()
    except sqlite3.Error as exc:
        logger.warning("load report_metadata failed: %s", exc)
        return metadata, None, []
    if not row:
        return metadata, None, []

    for i, c in enumerate(cols):
        metadata[c] = row[i] if row[i] is not None else ""
    values = dict(zip(bookkeeping, row[len(cols):]))
    seeded_at = values.get("auto_seeded_at")
    return (
        metadata,
        int(seeded_at) if seeded_at is not None else None,
        _decode_auto_fields(values.get("auto_fields")),
    )


def _load_metadata(files_db: str | None, task_id: str) -> dict[str, Any]:
    """Return the metadata row as a dict (all fields, empty if absent)."""
    return _load_metadata_state(files_db, task_id)[0]


def _write_metadata(
    files_db: str,
    task_id: str,
    values: dict[str, str],
    *,
    auto_seeded_at: int | None = None,
    auto_fields: list[str] | None = None,
) -> None:
    """Upsert the whitelisted metadata fields plus the seed bookkeeping."""
    _ensure_metadata_table(files_db)
    now = int(datetime.now(tz=timezone.utc).timestamp())
    clean = {k: ("" if values.get(k) is None else str(values.get(k))) for k in _METADATA_FIELDS}
    columns = (*_METADATA_FIELDS, "auto_fields")
    params: list[Any] = [task_id, *clean.values(), json.dumps(auto_fields or [], ensure_ascii=False)]
    update_assigns = [f'"{c}" = excluded."{c}"' for c in columns]
    update_assigns.append("updated_at = excluded.updated_at")
    if auto_seeded_at is not None:
        columns = (*columns, "auto_seeded_at")
        params.append(auto_seeded_at)
        update_assigns.append("auto_seeded_at = excluded.auto_seeded_at")
    params.append(now)
    col_sql = ", ".join(f'"{c}"' for c in columns)
    placeholders = ", ".join("?" for _ in columns)
    try:
        with _connect_rw(Path(files_db)) as conn:
            conn.execute(
                f'INSERT INTO "report_metadata" (task_id, {col_sql}, updated_at) '
                f'VALUES (?, {placeholders}, ?) '
                f'ON CONFLICT(task_id) DO UPDATE SET {", ".join(update_assigns)}',
                params,
            )
            conn.commit()
    except sqlite3.Error as exc:
        logger.warning("save report_metadata failed: %s", exc)
        raise HTTPException(status_code=503, detail="could not persist report metadata")


def _save_metadata(
    files_db: str, task_id: str, payload: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Upsert metadata (whitelisted fields only).

    Returns (stored row, auto_fields). The editor submits the WHOLE field set,
    so a field the analyst left alone arrives with the value it already had.
    Comparing against the stored row is therefore the only way to tell an
    untouched auto value from a deliberate edit — a provided-but-unchanged field
    keeps its [自动] badge.
    """
    _ensure_metadata_table(files_db)
    previous, auto_seeded_at, previous_auto = _load_metadata_state(files_db, task_id)
    now = int(datetime.now(tz=timezone.utc).timestamp())
    # Never persist raw None — normalize to empty string for display parity.
    clean = {k: ("" if payload.get(k) is None else str(payload.get(k)))
             for k in _METADATA_FIELDS}
    still_auto = sorted(
        field for field in previous_auto
        if field in clean and clean[field] == previous.get(field)
    )
    _write_metadata(
        files_db, task_id, clean,
        auto_seeded_at=auto_seeded_at, auto_fields=still_auto,
    )
    stored = _load_metadata(files_db, task_id)
    stored["updated_at"] = now
    return stored, still_auto


# ── metadata auto-derivation (seed once) ────────────────────────────────────


def _primary_phone(ctx: "_ReportContext") -> str:
    """Most frequent phone number in the Android call/SMS artifacts."""
    db = ctx.platform_db("android")
    if not db or not Path(db).is_file():
        return ""
    try:
        with _connect_ro(Path(db)) as conn:
            for table, column in (("call_logs", "number"), ("sms_messages", "address")):
                if not _table_exists(conn, table):
                    continue
                if column not in _table_columns(conn, table):
                    continue
                row = conn.execute(
                    f'SELECT "{column}", COUNT(*) AS occurrences FROM "{table}" '
                    f'WHERE "{column}" IS NOT NULL AND "{column}" != "" '
                    f'GROUP BY "{column}" ORDER BY occurrences DESC LIMIT 1'
                ).fetchone()
                if row and row[0]:
                    return str(row[0])
    except sqlite3.Error as exc:
        logger.warning("phone derivation failed: %s", exc)
    return ""


def _task_timestamp(task: dict[str, Any], key: str) -> Any:
    """A task timestamp by name.

    The C++ task API nests them as ``timestamps: {created, started, completed}``
    in MILLISECONDS, while the persisted form uses top-level ``<key>_time`` in
    seconds; accept either.
    """
    timestamps = task.get("timestamps")
    if isinstance(timestamps, dict) and timestamps.get(key) is not None:
        return timestamps[key]
    return task.get(f"{key}_time")


def _derive_metadata(ctx: "_ReportContext") -> dict[str, str]:
    """Values derivable from the analysis itself, with no human input.

    Only what the artifacts actually support. 采集人 / 送检人 / 持有人 / 证件号
    and friends have no source here and are deliberately absent so they keep
    rendering as "—" for the analyst to fill in.
    """
    task = ctx.task
    image_path = str(task.get("image_path") or "")
    platform_names = "、".join(PLATFORM_LABELS.get(p, p) for p in ctx.platforms)
    case_description = str(task.get("case_description") or "").strip()

    # created_time is when the task was queued; started_time is when the
    # extraction actually began. Prefer the latter for 开始提取时间 when present.
    extract_start = _task_timestamp(task, "started") or _task_timestamp(task, "created")

    remarks_parts: list[str] = []
    if case_description:
        remarks_parts.append(case_description)
    if image_path:
        remarks_parts.append(f"镜像：{image_path}")
    if platform_names:
        remarks_parts.append(f"检测平台：{platform_names}")
    remarks = "；".join(remarks_parts)

    derived = {
        "evidence_name": Path(image_path).name if image_path else "",
        "evidence_number": str(task.get("id") or ""),
        "extract_start": _format_epoch(extract_start),
        "extract_end": _format_epoch(_task_timestamp(task, "completed")),
        "case_name": case_description,
        "remarks": remarks,
        "evidence_remarks": remarks,
        "phone1": _primary_phone(ctx),
    }
    return {key: value for key, value in derived.items() if value}


def _metadata_db(ctx: "_ReportContext") -> str | None:
    """Writable database that holds report_metadata.

    _files.db is the canonical home, but Android *logical* analyses produce no
    files.db at all — their result database IS android.db, which already carries
    case_analysis. Fall back through the other artifacts so the metadata section
    (and the editor) still work for those tasks.
    """
    candidates = (
        ctx.files_db,
        ctx.platform_db("android"),
        ctx.platform_db("windows"),
        ctx.platform_db("linux"),
        ctx.raw_db,
        ctx.events_db,
    )
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def _seed_metadata(ctx: "_ReportContext") -> tuple[dict[str, Any], list[str]]:
    """Fill still-empty metadata fields from the analysis — exactly once.

    Returns (metadata, auto_fields). The row is stamped only for a COMPLETED
    task: seeding a running task would freeze a half-populated result, so an
    in-progress task gets the derived values as a non-persisted preview and
    keeps its one write for when the analysis finishes.
    """
    task_id = str(ctx.task.get("id") or "")
    files_db = _metadata_db(ctx)
    current, auto_seeded_at, previous_auto = _load_metadata_state(files_db, task_id)
    if not files_db:
        return current, previous_auto
    if auto_seeded_at is not None:
        return current, previous_auto

    derived = _derive_metadata(ctx)
    filled = {k: v for k, v in derived.items() if not current.get(k)}
    if str(ctx.task.get("status") or "").upper() != "COMPLETED":
        return {**current, **filled}, sorted(set(previous_auto) | set(filled))

    merged = {**current, **filled}
    auto_fields = sorted(set(previous_auto) | set(filled))
    now = int(datetime.now(tz=timezone.utc).timestamp())
    try:
        _write_metadata(files_db, task_id, merged, auto_seeded_at=now, auto_fields=auto_fields)
    except HTTPException as exc:
        # A read path must not 500 because the metadata row could not be
        # written; the derived values are still returned for display.
        logger.warning("metadata seed for %s not persisted: %s", task_id, exc.detail)
    return merged, auto_fields


# ── platform database resolution ─────────────────────────────────────────────
# Platform artifact tables do NOT live in _files.db. PathManager::getTaskDbPaths()
# (src/core/PathManager/PathManager.cpp:102-115) lays each platform's database out
# as a SIBLING file in the task directory — <task>/android.db, windows.db,
# linux.db, oss.db — and the task pipeline writes them separately
# (TaskManagerAnalysis.cpp:481,497,513,529). Only the CLI path merges every
# platform into one _files.db (AnalysisOrchestrator.cpp:314,330,346), which is
# why reading _files.db alone used to look like it worked.

_PLATFORM_MARKER_TABLES: dict[str, tuple[str, ...]] = {
    "android": (
        "system_build_properties", "device_identifiers", "miui_backup_manifest",
        "installed_apps", "installed_packages", "system_apps", "app_db_inventory",
        "sms_messages", "contacts", "call_logs", "wifi_networks",
        "wechat_messages", "qqnt_kv_records",
    ),
    "windows": (
        "registry_values", "user_accounts", "windows_services", "event_logs",
        "mft_entries", "amcache_entries", "scheduled_tasks", "usb_devices",
        "browser_history",
    ),
    "linux": (
        "linux_users", "linux_groups", "linux_packages", "linux_login_records",
        "linux_shell_history", "linux_systemd_services", "linux_log_entries",
        "linux_kernel_modules", "linux_audit_events",
    ),
}

# Display labels for the 检测平台 line.
PLATFORM_LABELS = {"android": "Android", "windows": "Windows", "linux": "Linux"}

# Marker table -> section id/title for the per-platform directory nodes.
_DEVICE_INFO_SECTIONS = {
    "android": ("device_info", "设备基本信息（Android）"),
    "windows": ("win_device_info", "设备基本信息（Windows）"),
    "linux": ("linux_device_info", "设备基本信息（Linux）"),
}


def _db_tables(path: str | None) -> set[str]:
    """Table names in a SQLite file (empty when absent or unreadable)."""
    if not path or not Path(path).is_file():
        return set()
    try:
        with _connect_ro(Path(path)) as conn:
            return {row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()}
    except sqlite3.Error as exc:
        logger.warning("table listing failed for %s: %s", path, exc)
        return set()


def _platform_db_candidates(
    name: str, files_db: str | None, raw_db: str | None, task: dict[str, Any]
) -> list[str]:
    """Candidate paths for one platform DB, most specific first.

    Mirrors the resolution order of RouteHelpers::get_database_path
    (src/network/HTTPServer/routes/RouteHelpers.cpp:48-66): an explicitly
    declared task-metadata path, then the sibling of the known artifact DBs,
    then the legacy ``<image>_android.db`` layout.
    """
    candidates: list[str] = []

    # Most authoritative: the path the C++ backend recorded for that scenario.
    scenario_databases = task.get("scenario_databases")
    if isinstance(scenario_databases, dict):
        for scenario in (name, "server_cloud" if name == "linux" else name):
            declared = scenario_databases.get(scenario)
            if isinstance(declared, str) and declared:
                candidates.append(declared)

    metadata = task.get("metadata")
    if isinstance(metadata, dict):
        declared = metadata.get(f"{name}_db")
        if isinstance(declared, str) and declared:
            candidates.append(declared)

    for anchor in (files_db, raw_db):
        if not anchor:
            continue
        stem = str(Path(anchor).with_suffix(""))
        candidates.append(str(Path(anchor).parent / f"{name}.db"))
        candidates.append(f"{stem}_{name}.db")

    if files_db and "_files.db" in files_db:
        candidates.append(files_db.replace("_files.db", f"_{name}.db"))

    unique: list[str] = []
    for candidate in candidates:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def _resolve_platform_db(
    name: str, files_db: str | None, raw_db: str | None, task: dict[str, Any]
) -> str | None:
    """First candidate that exists AND actually carries this platform's tables.

    The table check matters: a files.db mistaken for a platform DB would
    otherwise be reported as every platform at once.
    """
    markers = set(_PLATFORM_MARKER_TABLES[name])
    for candidate in _platform_db_candidates(name, files_db, raw_db, task):
        if _db_tables(candidate) & markers:
            return candidate
    return None


def _resolve_platform_dbs(
    files_db: str | None, raw_db: str | None, task: dict[str, Any]
) -> dict[str, str | None]:
    """Locate the sibling platform databases for a task."""
    return {
        name: _resolve_platform_db(name, files_db, raw_db, task)
        for name in _PLATFORM_MARKER_TABLES
    }


def _platforms_from_partitions(raw_db: str | None) -> list[str]:
    """Infer platforms from _raw.db partition filesystem types.

    Last-resort fallback for tasks recorded before scenarios were persisted.
    Android logical backups carry no partition table at all, so this never
    fires for them.
    """
    if not raw_db or not Path(raw_db).is_file():
        return []
    try:
        with _connect_ro(Path(raw_db)) as conn:
            if not _table_exists(conn, "partitions"):
                return []
            rows = conn.execute('SELECT description, fs_type FROM "partitions"').fetchall()
    except sqlite3.Error as exc:
        logger.warning("partition platform probe failed: %s", exc)
        return []

    found: list[str] = []
    for description, fs_type in rows:
        haystack = f"{description or ''} {fs_type or ''}".lower()
        if "android" in haystack:
            name = "android"
        elif "ntfs" in haystack or "windows" in haystack:
            name = "windows"
        elif "linux" in haystack or any(
            fs in haystack for fs in ("ext2", "ext3", "ext4", "xfs", "btrfs")
        ):
            name = "linux"
        else:
            continue
        if name not in found:
            found.append(name)
    return found


def _detect_platforms(
    task: dict[str, Any],
    platform_dbs: dict[str, str | None],
    raw_db: str | None,
    files_db: str | None = None,
) -> list[str]:
    """Which platforms this task carries evidence for.

    Priority: the scenarios the C++ backend recorded > a dedicated platform
    database holding that platform's tables > the same tables inside a merged
    database > partition filesystem types.

    The merged-database case is not hypothetical: the CLI pipeline writes every
    platform's artifacts into one _files.db (AnalysisOrchestrator.cpp:314,330,346),
    unlike the task pipeline's per-platform files.
    """
    platforms: list[str] = []

    scenarios = task.get("scenarios")
    if isinstance(scenarios, list):
        for scenario in scenarios:
            name = str(scenario).lower()
            # Server/cloud artifacts are produced by the Linux analyzer, into
            # oss.db; report them as Linux.
            if name == "server_cloud":
                name = "linux"
            if name in _PLATFORM_MARKER_TABLES and name not in platforms:
                platforms.append(name)

    for name, path in platform_dbs.items():
        if path and name not in platforms:
            platforms.append(name)

    merged_tables = _db_tables(files_db)
    if merged_tables:
        for name, markers in _PLATFORM_MARKER_TABLES.items():
            if name not in platforms and merged_tables & set(markers):
                platforms.append(name)

    if not platforms:
        platforms.extend(_platforms_from_partitions(raw_db))
    return platforms


# ── per-category data readers (table-presence-aware, never 404) ──────────────


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
    """Applications table, preferring whichever candidate actually has rows.

    A full Android image populates installed_packages / system_apps, but MIUI and
    Android *backup* sources populate installed_apps instead. A fixed order would
    therefore report zero apps for exactly the sources that do carry them.
    """
    if not files_db or not Path(files_db).is_file():
        return ""
    try:
        with _connect_ro(Path(files_db)) as conn:
            present = [t for t in ("installed_packages", "system_apps", "installed_apps")
                       if _table_exists(conn, t)]
            for table in present:
                if _count(conn, table):
                    return table
            return present[0] if present else ""
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
      "version_name", "version_code", "installer", "is_system_app",
      "first_install_time", "last_update_time", "native_library_path",
      # MIUI / Android-backup sources (installed_apps) carry these instead.
      "data_size", "sd_size", "bak_type", "manifest_summary"),
     "package_name"),
    # ── Android backup-source inventories ──
    # MIUI / Android backup evidence carries no live app databases, but it does
    # carry a full inventory of what was backed up. These tables hold thousands
    # of rows and previously had no section at all.
    ("android", "app_db_inventory", "应用数据库清单", "app_db_inventory",
     ("package_name", "db_path", "table_name", "row_count", "open_status"),
     "package_name"),
    ("android", "qqnt_artifacts", "QQ工件清单", "qqnt_artifact_inventory",
     ("package_name", "source_path", "bak_file", "artifact_category", "format",
      "size", "modified_time", "parse_status", "summary"),
     "source_path"),
    ("android", "qqnt_kv", "QQ键值记录", "qqnt_kv_records",
     ("namespace", "key", "value_type", "value_text", "is_sensitive",
      "parse_status", "source_path"),
     "namespace"),
    ("android", "wechat_artifacts", "微信工件清单", "wechat_artifact_inventory",
     ("package_name", "source_path", "bak_file", "artifact_category", "format",
      "size", "modified_time", "parse_status", "summary"),
     "source_path"),
    ("android", "wechat_kv", "微信键值记录", "wechat_kv_records",
     ("namespace", "key", "value_type", "value_text", "is_sensitive",
      "parse_status", "source_path"),
     "namespace"),

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


def _section_db(
    section: _PlatformSection,
    files_db: str | None,
    platform_dbs: dict[str, str | None],
) -> str | None:
    """Database holding this section's table.

    Every section belongs to exactly one platform, and that platform's artifacts
    live in its own database (see _resolve_platform_dbs). The CLI pipeline merges
    everything into _files.db, so fall back to it when no platform DB was found.
    """
    return platform_dbs.get(section[0]) or files_db


def _section_table(section: _PlatformSection, db: str | None) -> str:
    """Resolve the source table for a section (handles callable fallbacks)."""
    table = section[3]
    if callable(table):
        return table(db)
    return table


def _platform_sections_for(
    platforms: list[str],
    files_db: str | None,
    platform_dbs: dict[str, str | None],
) -> list[_PlatformSection]:
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


def _section_total(
    section: _PlatformSection,
    files_db: str | None,
    platform_dbs: dict[str, str | None],
) -> int:
    db = _section_db(section, files_db, platform_dbs)
    return _category_total(db, _section_table(section, db))


# ── device info per platform (synthesized records) ──────────────────────────


def _format_epoch(value: Any) -> str:
    """Render an epoch timestamp (seconds or milliseconds) as a UTC string.

    Empty for a missing value — the caller must not turn a null timestamp into
    the literal string "None" and present it as evidence data.

    Uses UTC for parity with _generated_at; the frontend does its own local
    formatting for the columns it owns.
    """
    if value is None or value == "":
        return ""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return str(value)
    if number <= 0:
        return ""
    seconds = number / 1000 if number > 100_000_000_000 else number
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except (OverflowError, OSError, ValueError):
        return str(value)


def _format_bytes(value: Any) -> str:
    """Render a byte count as a human-readable size."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number < 0:
        return ""
    for unit in ("B", "KB", "MB", "GB"):
        if number < 1024:
            return f"{number:.0f} {unit}" if unit == "B" else f"{number:.2f} {unit}"
        number /= 1024
    return f"{number:.2f} TB"


def _android_device_info_records(android_db: str | None) -> list[dict[str, Any]]:
    """Android 设备基本信息.

    The label set follows the SOURCE, not a fixed schema. A complete image
    populates system/build.prop, so the full 39-item reference-report schema
    applies. A MIUI / Android *backup* carries only a handful of identity
    fields — rendering the full schema there produced ~37 permanent em-dashes,
    which reads as "the report is broken" rather than "this evidence cannot
    supply these fields". So a backup source reports only what it can hold.
    """
    props: dict[str, str] = {}
    is_backup_source = False
    if android_db and Path(android_db).is_file():
        try:
            with _connect_ro(Path(android_db)) as conn:
                if _table_exists(conn, "system_build_properties"):
                    for key, value in conn.execute(
                        'SELECT property_key, property_value FROM "system_build_properties"'
                    ).fetchall():
                        if value is not None and str(key) not in props:
                            props[str(key)] = str(value)
                if _table_exists(conn, "device_identifiers"):
                    for itype, value in conn.execute(
                        'SELECT identifier_type, value FROM "device_identifiers"'
                    ).fetchall():
                        if value is not None:
                            props.setdefault(str(itype), str(value))
                if _table_exists(conn, "miui_backup_manifest"):
                    cols = _select_columns(
                        conn, "miui_backup_manifest",
                        ("device", "miui_version", "backup_date",
                         "total_size", "package_count"),
                    )
                    if cols:
                        col_sql = ", ".join(f'"{c}"' for c in cols)
                        row = conn.execute(
                            f'SELECT {col_sql} FROM "miui_backup_manifest" '
                            f'ORDER BY id DESC LIMIT 1'
                        ).fetchone()
                        if row:
                            manifest = _row_to_record(row, cols)
                            # A backup manifest with no build properties means the
                            # evidence IS the backup, not a full image.
                            is_backup_source = not props
                            # `device` is MIUI's device codename (e.g. "cepheus");
                            # it is the only model identifier a backup carries.
                            device = manifest.get("device")
                            if device:
                                props["ro.product.model"] = str(device)
                            version = manifest.get("miui_version")
                            if version:
                                props["ro.build.version.release"] = str(version)
                            if manifest.get("backup_date") is not None:
                                props["备份日期"] = _format_epoch(manifest["backup_date"])
                            if manifest.get("total_size") is not None:
                                props["数据总量"] = _format_bytes(manifest["total_size"])
                            if manifest.get("package_count") is not None:
                                props["应用数"] = str(manifest["package_count"])
                if _table_exists(conn, "installed_apps"):
                    count = _count(conn, "installed_apps")
                    if count:
                        props.setdefault("应用数", str(count))
        except sqlite3.Error as exc:
            logger.warning("android device_info read failed: %s", exc)

    items = _ANDROID_BACKUP_ITEMS if is_backup_source else _DEVICE_INFO_ITEMS
    record: dict[str, Any] = {}
    for label, *keys in items:
        value = ""
        for key in keys:
            if props.get(key):
                value = props[key]
                break
        record[label] = value
    # A manifest can accompany a full image too (and the fields are worth
    # reporting when it does), so surface any backup-only value that the chosen
    # label set did not already cover. Always emit a record, even all-empty, so
    # the section renders placeholders.
    for label, *keys in _ANDROID_BACKUP_ITEMS:
        if label in record:
            continue
        if any(props.get(key) for key in keys):
            record[label] = props[keys[0]]
    return [record]


# Registry values carrying Windows host identity, each located by its value_name
# AND the key it must live under.
#
# Matching on value_name alone is NOT safe. A real Software hive held 29
# ProductName values, only 2 of which described the OS — the rest were
# application names under Installer\Products and Uninstall, so the report showed
# 操作系统 = "InstallShield*". InstallDate, DisplayVersion and OSVersion are
# polluted the same way. hive_type alone does not separate them either (the OS
# row and the app rows are all SOFTWARE); the key_path is what discriminates.
#
# The C++ walk (WindowsRegistryParser.cpp) stores key_path relative to the hive
# root, so these are matched as SUFFIXES rather than exact literals.
_WIN_HOST_VALUE = "Microsoft\\Windows NT\\CurrentVersion"
_WIN_REGISTRY_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("操作系统", "ProductName", _WIN_HOST_VALUE),
    ("系统版本", "CurrentVersion", _WIN_HOST_VALUE),
    ("Service Pack", "CSDVersion", _WIN_HOST_VALUE),
    ("版次", "EditionID", _WIN_HOST_VALUE),
    ("内部版本号", "CurrentBuild", _WIN_HOST_VALUE),
    ("版本号", "ReleaseId", _WIN_HOST_VALUE),
    ("安装时间", "InstallDate", _WIN_HOST_VALUE),
    ("注册所有者", "RegisteredOwner", _WIN_HOST_VALUE),
    ("注册组织", "RegisteredOrganization", _WIN_HOST_VALUE),
    ("产品ID", "ProductId", _WIN_HOST_VALUE),
    ("计算机名", "ComputerName", "Control\\ComputerName\\ComputerName"),
    ("处理器架构", "PROCESSOR_ARCHITECTURE", "Session Manager\\Environment"),
    ("时区", "TimeZoneKeyName", "Control\\TimeZoneInformation"),
    ("机器标识", "MachineId", "Microsoft\\SQMClient"),
)

# Values rendered as a timestamp rather than verbatim (InstallDate is an epoch).
_WIN_EPOCH_FIELDS = frozenset({"安装时间"})

# The 32-bit registry view duplicates many keys. Its rows can disagree with the
# native ones (InstallDate: native 1521447805 vs Wow6432Node 0;
# RegisteredOwner: native "CaiXX" vs Wow6432Node "Microsoft"), so it never wins.
_WIN_WOW_NODE = "Wow6432Node"


def _win_registry_identity(conn: sqlite3.Connection) -> dict[str, str]:
    """Resolve each Windows host-identity value from its authoritative key.

    Rows are ranked so the native (non-Wow6432Node) view wins, then a usable
    value over an empty or zero one.
    """
    clauses: list[str] = []
    params: list[str] = []
    for _label, value_name, suffix in _WIN_REGISTRY_FIELDS:
        clauses.append("(value_name = ? AND key_path LIKE ?)")
        params.extend([value_name, f"%{suffix}"])

    rows = conn.execute(
        f'SELECT value_name, value_data, key_path FROM "registry_values" '
        f'WHERE {" OR ".join(clauses)}',
        params,
    ).fetchall()

    # (label) -> (rank, value); rank is compared, never the raw row order.
    best: dict[str, tuple[tuple[int, int, int], str]] = {}
    for value_name, value_data, key_path in rows:
        name = str(value_name or "")
        path = str(key_path or "")
        raw = "" if value_data is None else str(value_data).strip()
        is_wow = _WIN_WOW_NODE in path
        rank = (
            0 if is_wow else 1,                     # native view first
            1 if raw not in ("", "0") else 0,       # a usable value first
            1 if raw else 0,
        )
        for label, expected_name, suffix in _WIN_REGISTRY_FIELDS:
            if expected_name != name or not path.endswith(suffix):
                continue
            if label not in best or rank > best[label][0]:
                best[label] = (rank, raw)
    return {label: value for label, (_rank, value) in best.items()}


def _win_device_info_records(windows_db: str | None) -> list[dict[str, Any]]:
    """Windows 设备基本信息: host identity from the registry + host counts.

    All of it already lives in `registry_values` — the analyzer dumps every value
    of the SYSTEM / SOFTWARE / SAM / NTUSER hives. This only has to pick the
    right rows (see _WIN_REGISTRY_FIELDS).

    Windows exposes no CPU / RAM / machine-model artifact: the key that would
    carry them (HARDWARE\\DESCRIPTION\\System\\BIOS) is a volatile in-memory hive
    the kernel builds at boot, so it has no file on disk to walk. No such fields
    are offered rather than being shown permanently empty.
    """
    props: dict[str, str] = {}
    if windows_db and Path(windows_db).is_file():
        try:
            with _connect_ro(Path(windows_db)) as conn:
                if _table_exists(conn, "registry_values"):
                    props.update(_win_registry_identity(conn))
                if not props.get("计算机名") and _table_exists(conn, "event_logs"):
                    if "computer_name" in _table_columns(conn, "event_logs"):
                        # libevtx defaults to the literal "UNKNOWN" when absent.
                        row = conn.execute(
                            'SELECT computer_name FROM "event_logs" '
                            'WHERE computer_name IS NOT NULL AND computer_name != "" '
                            'AND UPPER(computer_name) != "UNKNOWN" LIMIT 1'
                        ).fetchone()
                        if row and row[0]:
                            props["计算机名"] = str(row[0])
                if _table_exists(conn, "user_accounts"):
                    count = _count(conn, "user_accounts")
                    if count:
                        props["用户账户数"] = str(count)
                if _table_exists(conn, "windows_services"):
                    count = _count(conn, "windows_services")
                    if count:
                        props["系统服务数"] = str(count)
        except sqlite3.Error as exc:
            logger.warning("win_device_info read failed: %s", exc)

    labels = [label for label, _name, _suffix in _WIN_REGISTRY_FIELDS]
    labels += ["用户账户数", "系统服务数"]
    record: dict[str, Any] = {}
    for label in labels:
        value = props.get(label, "")
        if label in _WIN_EPOCH_FIELDS and value:
            value = _format_epoch(value) or value
        record[label] = value
    return [record]


# host identity, in report order: (label, linux_host_info column)
_LINUX_HOST_FIELDS: tuple[tuple[str, str], ...] = (
    ("主机名", "hostname"),
    ("发行版", "distro"),
    ("发行版版本", "distro_version"),
    ("内核版本", "kernel_version"),
    ("系统架构", "architecture"),
    ("时区", "timezone"),
    ("机器标识", "machine_id"),
)

# Linux tables whose row counts are reported as host规模 indicators.
_LINUX_DEVICE_COUNTS: tuple[tuple[str, str], ...] = (
    ("用户账户数", "linux_users"),
    ("用户组数", "linux_groups"),
    ("已安装包数", "linux_packages"),
    ("系统服务数", "linux_systemd_services"),
    ("内核模块数", "linux_kernel_modules"),
)


def _linux_device_info_records(linux_db: str | None) -> list[dict[str, Any]]:
    """Linux 设备基本信息.

    Preferred source is the analyzer's own `linux_host_info` row, written by
    LinuxFilesAnalyzer::analyzeHostInformation() from the guest's /etc/hostname,
    /etc/os-release, /etc/machine-id and the kernel banner in dmesg.

    The older fallbacks are kept so databases produced before that table existed
    (and the CLI layout, which merges everything into _files.db) still work:
    hostname from linux_log_entries.hostname (its mode) or /etc/hostname content,
    distro from /etc/os-release content.

    内核模块数 is the count of modules INSTALLED on disk, not loaded — a disk
    image has no /proc/modules. It falls back to the linux_kernel_modules row
    count, which is only populated when the image itself carried that artifact.
    """
    record: dict[str, Any] = {label: "" for label, _column in _LINUX_HOST_FIELDS}
    for label, _table in _LINUX_DEVICE_COUNTS:
        record[label] = ""
    if not linux_db or not Path(linux_db).is_file():
        return [record]
    try:
        with _connect_ro(Path(linux_db)) as conn:
            if _table_exists(conn, "linux_host_info"):
                wanted = tuple(column for _label, column in _LINUX_HOST_FIELDS)
                wanted += ("kernel_modules_installed",)
                cols = _select_columns(conn, "linux_host_info", wanted)
                if cols:
                    col_sql = ", ".join(f'"{c}"' for c in cols)
                    row = conn.execute(
                        f'SELECT {col_sql} FROM "linux_host_info" ORDER BY id DESC LIMIT 1'
                    ).fetchone()
                    if row:
                        host = _row_to_record(row, cols)
                        for label, column in _LINUX_HOST_FIELDS:
                            if host.get(column) not in (None, ""):
                                record[label] = str(host[column])
                        installed = host.get("kernel_modules_installed")
                        if installed:                     # 0 means "not counted"
                            record["内核模块数"] = str(installed)

            if not record["主机名"] and _table_exists(conn, "linux_log_entries"):
                row = conn.execute(
                    'SELECT hostname, COUNT(*) AS occurrences FROM "linux_log_entries" '
                    'WHERE hostname IS NOT NULL AND hostname != "" '
                    'GROUP BY hostname ORDER BY occurrences DESC LIMIT 1'
                ).fetchone()
                if row and row[0]:
                    record["主机名"] = str(row[0])
            if _table_exists(conn, "os_config_files"):
                cols = _table_columns(conn, "os_config_files")
                path_col = "file_path" if "file_path" in cols else (
                    "path" if "path" in cols else None)
                content_col = "content" if "content" in cols else (
                    "value" if "value" in cols else None)
                if path_col and content_col:
                    for row in conn.execute(
                        f'SELECT "{path_col}", "{content_col}" FROM "os_config_files" '
                        f'WHERE "{path_col}" IS NOT NULL LIMIT 200'
                    ).fetchall():
                        name = str(Path(str(row[0])).name).lower()
                        content = str(row[1] or "").strip()
                        if not content:
                            continue
                        if name == "hostname" and not record["主机名"]:
                            record["主机名"] = content
                        elif name == "os-release" and not record["发行版"]:
                            record["发行版"] = _os_release_name(content)
            for label, table in _LINUX_DEVICE_COUNTS:
                if record[label]:                         # already from linux_host_info
                    continue
                if _table_exists(conn, table):
                    count = _count(conn, table)
                    if count:
                        record[label] = str(count)
    except sqlite3.Error as exc:
        logger.warning("linux device_info read failed: %s", exc)
    return [record]


def _os_release_name(content: str) -> str:
    """Human-readable name from /etc/os-release, verbatim if not key=value form."""
    def _unquote(value: str) -> str:
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            return value[1:-1]
        return value

    for key in ("PRETTY_NAME", "NAME"):
        for line in content.splitlines():
            if line.startswith(f"{key}="):
                name = _unquote(line.split("=", 1)[1])
                if name:
                    return name
    return content.strip()


# ── service resolution ───────────────────────────────────────────────────────


class _ReportContext(NamedTuple):
    """Everything the reader needs about one task's artifacts."""
    task: dict[str, Any]
    files_db: str | None
    events_db: str | None
    raw_db: str | None
    platform_dbs: dict[str, str | None]
    platforms: list[str]

    def platform_db(self, name: str) -> str | None:
        return self.platform_dbs.get(name)


async def _resolve_task(task_id: str) -> "_ReportContext":
    from ..services import get_service_manager

    service_manager = get_service_manager()
    task = await service_manager.cpp_backend.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"task not found: {task_id}")

    files_db = task.get("output_files_db") or None
    events_db = task.get("output_events_db") or None
    raw_db = task.get("output_raw_db") or None
    platform_dbs = _resolve_platform_dbs(files_db, raw_db, task)
    return _ReportContext(
        task=task,
        files_db=files_db,
        events_db=events_db,
        raw_db=raw_db,
        platform_dbs=platform_dbs,
        platforms=_detect_platforms(task, platform_dbs, raw_db, files_db),
    )


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
    ctx = await _resolve_task(task_id)
    task, files_db, events_db = ctx.task, ctx.files_db, ctx.events_db
    chapters = _load_chapter_markdown(files_db)
    platforms = ctx.platforms

    directory: list[DirectoryNode] = [
        DirectoryNode(id="overview", title="报告概览", kind="overview"),
        DirectoryNode(id="case", title="案件信息", kind="case"),
        DirectoryNode(id="evidence_info", title="证据信息", kind="evidence_info"),
    ]

    # Device/system info section — one node per detected platform, each titled
    # with its platform so the three are distinguishable. Always present for a
    # detected platform so placeholders render even when data is empty.
    for platform in platforms:
        section = _DEVICE_INFO_SECTIONS.get(platform)
        if section:
            directory.append(DirectoryNode(id=section[0], title=section[1], kind="device_info"))
    # If no platform detected, still show a generic device info placeholder.
    # Uses its own id so the reader never labels an unknown platform "Android".
    if not platforms:
        directory.append(
            DirectoryNode(id="device_info_generic", title="设备基本信息", kind="device_info"))

    # Platform-specific artifact sections (only the detected platform's set).
    for sec in _platform_sections_for(platforms, files_db, ctx.platform_dbs):
        _, section_id, title, _table, _fields, _order = sec
        directory.append(DirectoryNode(
            id=section_id, title=title, kind="records",
            stats=DirectoryNodeStats(total=_section_total(sec, files_db, ctx.platform_dbs)),
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
            # Raw platform ids ("android"), not display labels: this field is an
            # existing API contract. The display names live in the directory
            # node titles and in the frontend's own label map.
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
                         "device_info_generic | win_device_info | linux_device_info | "
                         "<platform section id>"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> RecordPage:
    ctx = await _resolve_task(task_id)
    files_db, events_db = ctx.files_db, ctx.events_db

    if category == "evidence.files":
        return await _files_records(files_db, page, page_size)
    if category == "timeline":
        return await _event_records(events_db, page, page_size)
    if category.startswith("analysis."):
        return await _chapter_records(files_db, category, page, page_size)

    # ── synthesized device/system info sections (one synthesized record) ──
    # Each reads its own platform database; _files.db is only the CLI-merged
    # fallback (see _resolve_platform_dbs).
    if category == "device_info":
        db = ctx.platform_db("android") or files_db
        return RecordPage(category="device_info", page=1, page_size=page_size,
                          total=1, total_pages=1,
                          records=_android_device_info_records(db))
    if category == "device_info_generic":
        # No platform was detected, so there is no platform database to read;
        # show the Android label set as empty placeholders rather than guessing.
        return RecordPage(category="device_info_generic", page=1, page_size=page_size,
                          total=1, total_pages=1, records=[{}])
    if category == "win_device_info":
        db = ctx.platform_db("windows") or files_db
        return RecordPage(category="win_device_info", page=1, page_size=page_size,
                          total=1, total_pages=1,
                          records=_win_device_info_records(db))
    if category == "linux_device_info":
        db = ctx.platform_db("linux") or files_db
        return RecordPage(category="linux_device_info", page=1, page_size=page_size,
                          total=1, total_pages=1,
                          records=_linux_device_info_records(db))

    # ── SMS keeps its specialized thread view ──
    if category == "sms":
        return _generic_table_records(
            ctx.platform_db("android") or files_db, "sms_messages",
            ("thread_id", "address", "person", "date", "date_sent",
             "type", "body", "status", "service_center"),
            "date", page, page_size, "sms")

    # ── generic platform artifact sections via the registry ──
    for sec in _PLATFORM_SECTIONS:
        if sec[1] == category:
            _platform, section_id, _title, _table, fields, order_by = sec
            db = _section_db(sec, files_db, ctx.platform_dbs)
            resolved = _section_table(sec, db)
            return _generic_table_records(
                db, resolved, fields, order_by, page, page_size, section_id)

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
    _ctx = await _resolve_task(task_id)
    files_db, events_db = _ctx.files_db, _ctx.events_db
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
    # Fields currently holding an auto-derived value the analyst has not edited.
    auto_fields: list[str] = []
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
    """Return case-info + evidence-info metadata.

    Seeds the derived values on first read (the fallback path for tasks that
    finished before the completion hook existed), then reports which fields are
    still auto-derived via auto_fields.
    """
    ctx = await _resolve_task(task_id)
    metadata, auto_fields = _seed_metadata(ctx)
    return ReportMetadataResponse(task_id=task_id, metadata=metadata, auto_fields=auto_fields)


@router.post(
    "/intelligence-report/{task_id}/metadata/seed",
    response_model=ReportMetadataResponse,
)
async def seed_report_metadata(task_id: str) -> ReportMetadataResponse:
    """Derive case-info + evidence-info values once, from the analysis itself.

    Called by the C++ pipeline when a task completes. Idempotent: a task that
    has already been seeded (by this call or by a first read) is left alone, and
    fields the analyst has filled in are never overwritten.
    """
    ctx = await _resolve_task(task_id)
    metadata, auto_fields = _seed_metadata(ctx)
    return ReportMetadataResponse(task_id=task_id, metadata=metadata, auto_fields=auto_fields)


@router.put(
    "/intelligence-report/{task_id}/metadata",
    response_model=ReportMetadataResponse,
)
async def update_report_metadata(
    task_id: str, payload: ReportMetadataUpdate
) -> ReportMetadataResponse:
    """Upsert editable forensic metadata. Returns the stored row."""
    ctx = await _resolve_task(task_id)
    files_db = _metadata_db(ctx)
    if not files_db:
        raise HTTPException(status_code=503, detail="task files database unavailable")
    stored, auto_fields = _save_metadata(files_db, task_id, payload.model_dump(exclude_unset=True))
    updated_at = stored.pop("updated_at", None)
    return ReportMetadataResponse(
        task_id=task_id, metadata=stored, auto_fields=auto_fields, updated_at=updated_at
    )
