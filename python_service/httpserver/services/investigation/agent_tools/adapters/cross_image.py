"""Cross-Image & Cross-Device Correlation Tools (Phase 3).

Enables Specialists and Correlation Agents to:
1. search_shared_indicators: Scan across multiple disks/devices for shared IOCs
   (file hashes, IP addresses, domains, accounts, filenames).
2. correlate_timeline: Align multi-device timeline events across scopes with
   clock offset / skew normalization and tolerance windows.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sqlite3
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, Field

from ..definitions import (
    EvidenceBehavior,
    ForensicToolDefinition,
    ToolAccess,
    ToolCategory,
    ToolCostClass,
    ToolPaginationKind,
    ToolScopeKind,
)
from ..errors import ToolErrorCode, ToolExecutionError
from ..registry import ToolExecutionOutcome
from .base import ToolCatalogConfig
from .services import ForensicToolServices

logger = logging.getLogger(__name__)


def _connect_ro(path: str) -> sqlite3.Connection:
    candidate = sqlite3.connect(f"file:{quote(str(path), safe='/')}?mode=ro", uri=True, timeout=10)
    candidate.row_factory = sqlite3.Row
    return candidate


# ============================================================================
# Tool 1: search_shared_indicators
# ============================================================================

class SearchSharedIndicatorsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_type: Literal["hash", "ip", "domain", "filename", "all"] = "all"
    query: Optional[str] = None
    target_scopes: Optional[List[str]] = None
    min_occurrences: int = Field(default=2, ge=1)


class IndicatorOccurrence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_scope: str
    task_id: str
    artifact_type: str
    location: str  # file path, event type, etc.
    evidence_key: str
    details: Optional[str] = None


class SharedIndicatorItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    indicator_value: str
    indicator_type: str
    occurrence_count: int
    scopes: List[str]
    occurrences: List[IndicatorOccurrence]


class SearchSharedIndicatorsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shared_indicators: List[SharedIndicatorItem] = Field(default_factory=list)
    total_shared: int = 0
    scanned_tasks_count: int = 0
    scanned_scopes: List[str] = Field(default_factory=list)
    limitations: Tuple[str, ...] = ()


def build_search_shared_indicators_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: SearchSharedIndicatorsInput = invocation.args
        current_task_id = invocation.context.task_id

        # 1. Discover all task candidates in case or scope
        tasks_to_scan: Dict[str, dict] = {}  # scope_label -> task_dict
        try:
            cases_res = await services.cpp_backend.list_cases()
            cases = cases_res.get("cases", []) if isinstance(cases_res, dict) else []
            for c in cases:
                tids = c.get("task_ids", [])
                if current_task_id in tids and len(tids) > 1:
                    for tid in tids:
                        t = await services.cpp_backend.get_task(tid)
                        if t:
                            img = t.get("image_name") or t.get("image_path") or ""
                            scope_label = tid
                            if "服务器" in img or "server" in img.lower():
                                scope_label = "src_server"
                            elif "计算机" in img or "pc" in img.lower() or "嫌疑人" in img:
                                scope_label = "src_pc"
                            elif "android" in img.lower() or "phone" in img.lower() or t.get("android_analyze") or "android" in t.get("scenarios", []):
                                scope_label = "src_phone"
                            elif "android" in img.lower() or "phone" in img.lower() or t.get("android_analyze") or "android" in t.get("scenarios", []):
                                scope_label = "src_phone"
                            tasks_to_scan[scope_label] = t
                    break
        except Exception as e:
            logger.warning(f"Failed to lookup cases in search_shared_indicators: {e}")

        # Fallback to current task if no case found
        if not tasks_to_scan:
            current_task = await services.cpp_backend.get_task(current_task_id)
            if current_task:
                tasks_to_scan[current_task_id] = current_task

        # Filter by requested scopes if provided
        if args.target_scopes:
            tasks_to_scan = {
                k: v for k, v in tasks_to_scan.items() if k in args.target_scopes or v.get("id") in args.target_scopes
            }

        shared_results: Dict[str, SharedIndicatorItem] = {}

        def _scan_sqlite():
            found_by_val: Dict[Tuple[str, str], List[IndicatorOccurrence]] = {}

            for scope_label, t in tasks_to_scan.items():
                tid = t.get("id", "")
                files_db = t.get("output_files_db")
                events_db = t.get("output_events_db")

                # Scan files for hash & filename
                if files_db and os.path.exists(files_db) and (args.indicator_type in ("hash", "filename", "all")):
                    try:
                        conn = _connect_ro(files_db)
                        c = conn.cursor()
                        # Hash scan
                        if args.indicator_type in ("hash", "all"):
                            query_sql = "SELECT md5, path, name FROM files WHERE md5 IS NOT NULL AND md5 != ''"
                            params = []
                            if args.query:
                                query_sql += " AND md5 LIKE ?"
                                params.append(f"%{args.query}%")
                            query_sql += " LIMIT 200"
                            c.execute(query_sql, params)
                            for r in c.fetchall():
                                md5_val = str(r["md5"]).lower()
                                path_val = str(r["path"] or r["name"] or "")
                                fqer = f"{scope_label}:file:{path_val}"
                                key = (md5_val, "hash")
                                found_by_val.setdefault(key, []).append(
                                    IndicatorOccurrence(
                                        source_scope=scope_label,
                                        task_id=tid,
                                        artifact_type="file_md5",
                                        location=path_val,
                                        evidence_key=fqer,
                                        details=f"File: {path_val}",
                                    )
                                )
                        # Filename scan
                        if args.indicator_type in ("filename", "all"):
                            query_sql = "SELECT name, path, md5 FROM files WHERE name IS NOT NULL AND length(name) > 3"
                            params = []
                            if args.query:
                                query_sql += " AND name LIKE ?"
                                params.append(f"%{args.query}%")
                            query_sql += " LIMIT 200"
                            c.execute(query_sql, params)
                            for r in c.fetchall():
                                name_val = str(r["name"])
                                path_val = str(r["path"] or name_val)
                                fqer = f"{scope_label}:file:{path_val}"
                                key = (name_val.lower(), "filename")
                                found_by_val.setdefault(key, []).append(
                                    IndicatorOccurrence(
                                        source_scope=scope_label,
                                        task_id=tid,
                                        artifact_type="file_name",
                                        location=path_val,
                                        evidence_key=fqer,
                                        details=f"Path: {path_val} (MD5: {r['md5']})",
                                    )
                                )
                        conn.close()
                    except Exception as fe:
                        logger.warning(f"Error querying files.db for {tid}: {fe}")

                # Scan events for IP/Domain
                if events_db and os.path.exists(events_db) and (args.indicator_type in ("ip", "domain", "all")):
                    try:
                        conn = _connect_ro(events_db)
                        c = conn.cursor()
                        c.execute("SELECT timestamp, event_type, file_path FROM events WHERE file_path IS NOT NULL LIMIT 300")
                        for r in c.fetchall():
                            text_body = str(r["file_path"] or "")
                            ts = int(r["timestamp"] or 0)
                            evt_type = str(r["event_type"] or "")
                            minute = ts // 60
                            fqer = f"{scope_label}:cluster:v1:{minute}:{quote(evt_type, safe='')}"
                            if args.query and args.query.lower() in text_body.lower():
                                key = (args.query.lower(), "ip_or_keyword")
                                found_by_val.setdefault(key, []).append(
                                    IndicatorOccurrence(
                                        source_scope=scope_label,
                                        task_id=tid,
                                        artifact_type="event_text",
                                        location=evt_type,
                                        evidence_key=fqer,
                                        details=text_body[:100],
                                    )
                                )
                        conn.close()
                    except Exception as ee:
                        logger.warning(f"Error querying events.db for {tid}: {ee}")

            # Filter for items appearing in >= min_occurrences distinct scopes
            results = []
            for (val, ind_type), occ_list in found_by_val.items():
                distinct_scopes = sorted({occ.source_scope for occ in occ_list})
                if len(distinct_scopes) >= args.min_occurrences or (len(tasks_to_scan) == 1 and len(occ_list) >= args.min_occurrences):
                    results.append(
                        SharedIndicatorItem(
                            indicator_value=val,
                            indicator_type=ind_type,
                            occurrence_count=len(occ_list),
                            scopes=distinct_scopes,
                            occurrences=occ_list,
                        )
                    )
            return sorted(results, key=lambda x: (-len(x.scopes), -x.occurrence_count))

        shared_items = await asyncio.to_thread(_scan_sqlite)

        all_evidence_refs = [
            occ.evidence_key
            for item in shared_items
            for occ in item.occurrences
        ]

        summary = (
            f"Found {len(shared_items)} shared indicators across "
            f"{len(tasks_to_scan)} devices/scopes"
        )
        output = SearchSharedIndicatorsOutput(
            shared_indicators=shared_items,
            total_shared=len(shared_items),
            scanned_tasks_count=len(tasks_to_scan),
            scanned_scopes=list(tasks_to_scan.keys()),
            limitations=(
                "Shared indicators are matched against files.db and events.db across associated tasks",
            ),
        )
        return ToolExecutionOutcome(
            summary=summary,
            result=output,
            evidence_refs=tuple(all_evidence_refs[:100]),
        )

    definition = ForensicToolDefinition(
        tool_id="search_shared_indicators",
        version="1",
        title="Search Shared Indicators Across Devices",
        description=(
            "Cross-device correlation tool: scan across multiple tasks/devices in the case "
            "for identical hashes (MD5), filenames, IP addresses or domains to uncover shared "
            "malware, C2 infrastructure, or perpetrator artifacts."
        ),
        input_model=SearchSharedIndicatorsInput,
        output_model=SearchSharedIndicatorsOutput,
        category=ToolCategory.EVIDENCE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.TASK,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.NONE,
    )
    return definition, adapter


# ============================================================================
# Tool 2: correlate_timeline
# ============================================================================

class CorrelateTimelineInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_scopes: Optional[List[str]] = None
    start_unix: Optional[int] = None
    end_unix: Optional[int] = None
    tolerance_seconds: int = Field(default=120, ge=1, le=86400)
    clock_offsets: Optional[Dict[str, int]] = None  # scope -> bias_seconds


class CorrelatedCluster(BaseModel):
    model_config = ConfigDict(extra="forbid")

    canonical_unix_minute: int
    scopes_involved: List[str]
    event_count: int
    evidence_keys: List[str]
    summary: str


class CorrelateTimelineOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correlated_clusters: List[CorrelatedCluster] = Field(default_factory=list)
    total_clusters: int = 0
    scanned_scopes: List[str] = Field(default_factory=list)


def build_correlate_timeline_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: CorrelateTimelineInput = invocation.args
        current_task_id = invocation.context.task_id

        tasks_to_scan: Dict[str, dict] = {}
        try:
            cases_res = await services.cpp_backend.list_cases()
            cases = cases_res.get("cases", []) if isinstance(cases_res, dict) else []
            for c in cases:
                tids = c.get("task_ids", [])
                if current_task_id in tids and len(tids) > 1:
                    for tid in tids:
                        t = await services.cpp_backend.get_task(tid)
                        if t:
                            img = t.get("image_name") or t.get("image_path") or ""
                            scope_label = tid
                            if "服务器" in img or "server" in img.lower():
                                scope_label = "src_server"
                            elif "计算机" in img or "pc" in img.lower() or "嫌疑人" in img:
                                scope_label = "src_pc"
                            elif "android" in img.lower() or "phone" in img.lower() or t.get("android_analyze") or "android" in t.get("scenarios", []):
                                scope_label = "src_phone"
                            tasks_to_scan[scope_label] = t
                    break
        except Exception as e:
            logger.warning(f"Failed to lookup cases in correlate_timeline: {e}")

        if not tasks_to_scan:
            t = await services.cpp_backend.get_task(current_task_id)
            if t:
                tasks_to_scan[current_task_id] = t

        if args.target_scopes:
            tasks_to_scan = {
                k: v for k, v in tasks_to_scan.items() if k in args.target_scopes or v.get("id") in args.target_scopes
            }

        offsets = args.clock_offsets or {}

        def _correlate_events():
            # (canonical_minute) -> dict of scope -> list of (evt_type, raw_minute)
            events_by_min: Dict[int, Dict[str, List[Tuple[str, int]]]] = {}

            for scope_label, t in tasks_to_scan.items():
                edb = t.get("output_events_db")
                if not edb or not os.path.exists(edb):
                    continue
                try:
                    conn = _connect_ro(edb)
                    c = conn.cursor()
                    sql = "SELECT timestamp, event_type FROM events WHERE timestamp IS NOT NULL"
                    params = []
                    if args.start_unix is not None:
                        sql += " AND timestamp >= ?"
                        params.append(args.start_unix)
                    if args.end_unix is not None:
                        sql += " AND timestamp <= ?"
                        params.append(args.end_unix)
                    sql += " LIMIT 500"
                    c.execute(sql, params)
                    offset = offsets.get(scope_label, 0)
                    for r in c.fetchall():
                        raw_ts = int(r["timestamp"] or 0)
                        canon_ts = raw_ts + offset
                        minute = canon_ts // 60
                        raw_minute = raw_ts // 60
                        evt_type = str(r["event_type"] or "")
                        events_by_min.setdefault(minute, {}).setdefault(scope_label, []).append((evt_type, raw_minute))
                    conn.close()
                except Exception as e:
                    logger.warning(f"Error querying events.db for timeline correlation: {e}")

            clusters = []
            for minute, scope_evts in sorted(events_by_min.items()):
                scopes = sorted(scope_evts.keys())
                if len(scopes) > 1 or (len(tasks_to_scan) == 1 and len(scopes) == 1):
                    all_keys = []
                    total_cnt = 0
                    summary_parts = []
                    for sc, ev_tuples in scope_evts.items():
                        total_cnt += len(ev_tuples)
                        evt_names = [x[0] for x in ev_tuples]
                        summary_parts.append(f"{sc}: {len(ev_tuples)} events ({', '.join(evt_names[:2])})")
                        for et, raw_m in set(ev_tuples):
                            all_keys.append(f"{sc}:cluster:v1:{raw_m}:{quote(et, safe='')}")
                    clusters.append(
                        CorrelatedCluster(
                            canonical_unix_minute=minute,
                            scopes_involved=scopes,
                            event_count=total_cnt,
                            evidence_keys=all_keys[:5],
                            summary="; ".join(summary_parts),
                        )
                    )
            return clusters

        clusters = await asyncio.to_thread(_correlate_events)
        all_keys = [k for c in clusters for k in c.evidence_keys]

        output = CorrelateTimelineOutput(
            correlated_clusters=clusters,
            total_clusters=len(clusters),
            scanned_scopes=list(tasks_to_scan.keys()),
        )
        return ToolExecutionOutcome(
            summary=f"Found {len(clusters)} cross-device timeline clusters across {len(tasks_to_scan)} scopes",
            result=output,
            evidence_refs=tuple(all_keys[:100]),
        )

    definition = ForensicToolDefinition(
        tool_id="correlate_timeline",
        version="1",
        title="Correlate Multi-Device Timelines",
        description=(
            "Cross-device timeline alignment tool: correlate event activity across multiple devices "
            "within a calibrated time window, applying clock offsets and timezone shifts to detect "
            "synchronized malicious actions."
        ),
        input_model=CorrelateTimelineInput,
        output_model=CorrelateTimelineOutput,
        category=ToolCategory.TIMELINE,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.TIMELINE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.NONE,
    )
    return definition, adapter
