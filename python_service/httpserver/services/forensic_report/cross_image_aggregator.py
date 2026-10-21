"""Cross-Image Multi-Device Evidence Aggregator (Phase 1).

Aggregates evidence across multiple image tasks belonging to a case:
1. Resolves case member tasks and infers/reads device scopes (src_pc, src_server, src_phone).
2. Collects evidence snapshots and bound analyses from each task's investigation.db.
3. Upgrades local evidence keys to Fully Qualified Evidence References (FQER: scope:type:path).
4. Produces a deterministic, immutable ReportGenerationEnvelopeV4.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from ..investigation.paths import investigation_db_path_for_task
from ..investigation.repository import READABLE_SCHEMA_VERSIONS
from ..investigation.models import ReportEvidenceStatus
from .models import (
    CASE_DESCRIPTION_MAX_CHARS,
    DeviceScopeSummary,
    EnvelopeEvidenceItemV3,
    EnvelopeSnapshotV3,
    ReportGenerationEnvelopeV4,
)
from .generation import ReportGenerationInputError, REPORT_GENERATION_PROMPT_VERSION

logger = logging.getLogger(__name__)

CROSS_CASE_REPORT_PROMPT_VERSION = "cross-case-report:v1"


class CrossImageEvidenceAggregator:
    """Read-only aggregator for assembling cross-image forensic evidence envelopes."""

    def __init__(self, cpp_backend: Any):
        self._cpp_backend = cpp_backend

    async def assemble_case_envelope(
        self,
        case_id: str,
        *,
        prompt_version: str = CROSS_CASE_REPORT_PROMPT_VERSION,
        override_description: Optional[str] = None,
    ) -> ReportGenerationEnvelopeV4:
        """Fetch case and sub-tasks, aggregate evidence across devices, and return EnvelopeV4."""
        case_info = await self._cpp_backend.get_case(case_id)
        if not case_info or not isinstance(case_info, dict):
            raise ReportGenerationInputError(
                "case_not_found", f"Case {case_id} not found in backend"
            )

        case_name = case_info.get("name") or f"Case-{case_id[:8]}"
        case_desc = override_description or case_info.get("description") or ""

        task_ids = case_info.get("task_ids") or []
        if not task_ids:
            raise ReportGenerationInputError(
                "no_tasks_in_case", f"Case {case_id} has no member tasks"
            )

        # 1. Fetch metadata for all member tasks
        tasks_meta: List[Dict[str, Any]] = []
        for tid in task_ids:
            try:
                t = await self._cpp_backend.get_task(tid)
                if t and isinstance(t, dict):
                    tasks_meta.append(t)
            except Exception as e:
                logger.warning("Failed to fetch task %s for case %s: %s", tid, case_id, e)

        if not tasks_meta:
            raise ReportGenerationInputError(
                "tasks_unavailable", f"Could not load member tasks for case {case_id}"
            )

        # 2. Determine device scopes and build DeviceScopeSummary list
        devices: List[DeviceScopeSummary] = []
        main_items: List[EnvelopeEvidenceItemV3] = []
        appendix_items: List[EnvelopeEvidenceItemV3] = []

        seen_scopes: Dict[str, int] = {}
        for t in tasks_meta:
            tid = t.get("id") or ""
            img_path = t.get("image_path") or ""
            img_name = Path(img_path).name if img_path else tid[:8]
            img_lower = img_name.lower()

            scope = t.get("metadata", {}).get("device_scope")
            if not scope:
                if any(k in img_lower for k in ("服务器", "server", "linux", "centos", "ubuntu")):
                    scope = "src_server"
                elif any(k in img_lower for k in ("phone", "android", "miui", "ios")):
                    scope = "src_phone"
                else:
                    scope = "src_pc"

            # Avoid scope collisions if multiple tasks share the same role
            count = seen_scopes.get(scope, 0)
            seen_scopes[scope] = count + 1
            effective_scope = scope if count == 0 else f"{scope}_{count+1}"

            role_desc = (
                "涉案服务器 (Web/后端/日志)" if "server" in effective_scope
                else "涉案移动终端 (手机/聊天/通讯)" if "phone" in effective_scope
                else "嫌疑人计算机 (工作站/操作端)"
            )

            devices.append(
                DeviceScopeSummary(
                    scope=effective_scope,
                    role_description=f"{role_desc} [{img_name}]",
                    task_id=tid,
                    image_name=img_name,
                    clock_skew_seconds=t.get("metadata", {}).get("clock_skew_seconds", 0),
                    timezone=t.get("metadata", {}).get("timezone", "UTC+8"),
                )
            )

            # 3. Harvest evidence from this task's investigation.db
            db_path = investigation_db_path_for_task(t)
            if not db_path.exists():
                logger.info("Task %s has no investigation.db at %s; skipping evidence", tid, db_path)
                continue

            task_main, task_app = self._harvest_task_evidence(db_path, tid, effective_scope)
            main_items.extend(task_main)
            appendix_items.extend(task_app)

        # Deduplicate & sort items by evidence_key
        def _dedup_sort(items: List[EnvelopeEvidenceItemV3]) -> Tuple[EnvelopeEvidenceItemV3, ...]:
            by_key: Dict[str, EnvelopeEvidenceItemV3] = {}
            for item in items:
                by_key[item.evidence_key] = item
            return tuple(by_key[k] for k in sorted(by_key.keys()))

        sorted_main = _dedup_sort(main_items)
        sorted_app = _dedup_sort(appendix_items)

        # Disallow empty evidence envelope
        if not sorted_main and not sorted_app:
            raise ReportGenerationInputError(
                "no_report_evidence",
                f"Case {case_id} has no report evidence in any member task",
            )

        all_keys = tuple(sorted({i.evidence_key for i in (*sorted_main, *sorted_app)}))

        envelope = ReportGenerationEnvelopeV4(
            prompt_version=prompt_version,
            case_id=case_id,
            case_name=case_name,
            case_description=case_desc[:CASE_DESCRIPTION_MAX_CHARS],
            devices=tuple(sorted(devices, key=lambda d: d.scope)),
            main_evidence=sorted_main,
            appendix_evidence=sorted_app,
            allowed_report_evidence_ids=all_keys,
        )

        return envelope

    def _harvest_task_evidence(
        self, db_path: Path, task_id: str, scope: str
    ) -> Tuple[List[EnvelopeEvidenceItemV3], List[EnvelopeEvidenceItemV3]]:
        """Harvest and FQER-prefix evidence from one task's investigation.db."""
        uri = f"file:{quote(str(db_path))}?mode=ro"
        main_list: List[EnvelopeEvidenceItemV3] = []
        app_list: List[EnvelopeEvidenceItemV3] = []

        try:
            with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=15)) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON")

                # Check if report_evidence table exists
                tbl = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='report_evidence'"
                ).fetchone()
                if not tbl:
                    return [], []

                rows = conn.execute(
                    "SELECT evidence_key, report_status, analysis_id FROM report_evidence WHERE task_id = ?",
                    (task_id,),
                ).fetchall()

                for r in rows:
                    raw_key = r["evidence_key"]
                    status = ReportEvidenceStatus(r["report_status"])
                    if status is ReportEvidenceStatus.excluded or raw_key.startswith("cluster:"):
                        continue

                    # Ensure key is fully qualified with device scope
                    fqer_key = (
                        raw_key if raw_key.startswith(f"{scope}:")
                        else f"{scope}:{raw_key}"
                    )

                    # Retrieve snapshot row
                    snap_row = conn.execute(
                        "SELECT * FROM evidence_snapshots WHERE task_id = ? AND evidence_key = ?",
                        (task_id, raw_key),
                    ).fetchone()
                    if not snap_row:
                        continue

                    try:
                        snap_payload = json.loads(snap_row["snapshot_json"])
                    except Exception:
                        snap_payload = {}

                    ev_type = snap_row["evidence_type"] or "file"
                    if ev_type not in ("file", "cluster", "android_artifact"):
                        ev_type = "file"

                    snapshot = EnvelopeSnapshotV3(
                        task_id=task_id,
                        evidence_key=fqer_key,
                        evidence_type=ev_type,
                        captured_at=snap_row["captured_at"],
                        payload=snap_payload,
                    )

                    item = EnvelopeEvidenceItemV3(
                        evidence_key=fqer_key,
                        report_status=status,
                        snapshot=snapshot,
                        bound_analysis=None,
                    )

                    if status is ReportEvidenceStatus.main:
                        main_list.append(item)
                    else:
                        app_list.append(item)

        except Exception as exc:
            logger.warning("Error reading evidence from %s: %s", db_path, exc)

        return main_list, app_list


__all__ = ["CrossImageEvidenceAggregator", "CROSS_CASE_REPORT_PROMPT_VERSION"]
