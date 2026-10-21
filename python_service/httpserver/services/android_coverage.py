"""Read-only, task-owned Android artifact coverage presentation."""

from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from urllib.parse import quote

_TABLES = (
    "sms_messages", "contacts", "call_logs", "wechat_messages",
    "whatsapp_messages", "telegram_messages", "installed_apps",
    "wechat_artifact_inventory", "qqnt_artifact_inventory", "wifi_networks",
    "installed_packages",
    "mobile_artifacts",
)


def android_db_candidates(task: dict) -> list[Path]:
    metadata = task.get("metadata") or {}
    trusted_parents = {
        Path(task[key]).resolve(strict=False).parent
        for key in ("output_files_db", "output_raw_db") if task.get(key)
    }
    candidates = []
    if isinstance(metadata, dict) and metadata.get("android_db"):
        candidates.append(Path(metadata["android_db"]))
    files_db = task.get("output_files_db")
    if files_db and task.get("android_source") in {"dir", "zip", "miui-backup", "harmony-backup"}:
        candidates.append(Path(files_db))
    if files_db:
        candidates.append(Path(files_db).with_name("android.db"))
    if task.get("output_raw_db"):
        raw = Path(task["output_raw_db"])
        candidates.append(raw.with_name("android.db"))
        stem = raw.stem[:-4] if raw.stem.endswith("_raw") else raw.stem
        candidates.append(raw.with_name(stem + "_android.db"))

    result = []
    for candidate in candidates:
        path = candidate.resolve(strict=False)
        if path.parent not in trusted_parents or not path.is_file():
            continue
        if path not in result:
            result.append(path)
    return result


def resolve_android_db(task: dict) -> Path | None:
    for path in android_db_candidates(task):
        try:
            uri = f"file:{quote(str(path), safe='/')}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as con:
                con.execute("PRAGMA query_only=ON")
                tables = {row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                if "android_source_coverage" not in tables and not tables.intersection(_TABLES):
                    continue
                return path
        except sqlite3.DatabaseError:
            continue
    return None


def read_coverage(task: dict) -> dict:
    metadata = task.get("metadata") or {}
    path = resolve_android_db(task)
    if path is not None:
        try:
            uri = f"file:{quote(str(path), safe='/')}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=5) as con:
                con.execute("PRAGMA query_only=ON")
                tables = {row[0] for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )}
                counts = {name: con.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
                          for name in _TABLES if name in tables}
                rows = []
                if "android_source_coverage" in tables:
                    rows = [dict(zip(("artifact_kind", "source_path", "status", "detail"), row))
                            for row in con.execute(
                                "SELECT artifact_kind, source_path, status, detail "
                                "FROM android_source_coverage ORDER BY artifact_kind, source_path LIMIT 1000"
                            )]
                warnings = []
                manifest = None
                normalization_manifest = None
                manifest_path = path.parent / "android_coverage_manifest.json"
                if manifest_path.is_file() and not manifest_path.is_symlink():
                    try:
                        if manifest_path.stat().st_size <= 2 * 1024 * 1024:
                            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                    except (OSError, UnicodeError, ValueError):
                        warnings.append("覆盖清单无效，不能用于完整性判断")
                normalization_path = path.parent / "android_normalization_manifest.json"
                if normalization_path.is_file() and not normalization_path.is_symlink():
                    try:
                        if normalization_path.stat().st_size <= 8 * 1024 * 1024:
                            normalization_manifest = json.loads(normalization_path.read_text(encoding="utf-8"))
                    except (OSError, UnicodeError, ValueError):
                        warnings.append("Android 规范化清单无效，来源链不可用")
                if not rows:
                    warnings.append("旧版任务未记录来源覆盖；已解析条数不能证明取证完整")
                if any(row["status"] != "parsed" for row in rows):
                    warnings.append("部分来源缺失、加密、失败或仅完成提取，尚未确认全部解析")
                if metadata.get("android_coverage_status") == "COMPLETED_WITH_LOCKED_USERDATA":
                    warnings.append("userdata 已识别，但用户加密内容不可读取，Android 工件覆盖不完整")
                return {
                    "task_id": task["id"], "source_mode": task.get("android_source"),
                    "available": True, "coverage_recorded": bool(rows),
                    "artifact_counts": counts, "sources": rows, "warnings": warnings,
                    "manifest": manifest, "normalization_manifest": normalization_manifest,
                }
        except sqlite3.DatabaseError:
            pass
    return {
        "task_id": task["id"], "source_mode": task.get("android_source"),
        "available": False, "coverage_recorded": False, "artifact_counts": {},
        "sources": [], "warnings": ["该任务没有可读取的安卓分析数据库"],
    }
