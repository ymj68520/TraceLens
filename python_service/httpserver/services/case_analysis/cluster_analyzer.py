"""
Cluster Analyzer Module — Event cluster analysis and Graphiti integration.

This module handles the complete event cluster data flow:
1. Fetch event clusters from database
2. LLM analysis for each cluster
3. Persist to database
4. Ingest to Graphiti knowledge graph
"""

import asyncio
import bisect
import json
import logging
import sqlite3
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ...config import Settings
from ...path_utils import normalize_evidence_path
from ..investigation_evidence import (
    PARENT_DIRECTORY_SQL,
    TIMELINE_MAX_BUCKET_SECONDS,
    parent_directory_of,
)
from .adaptive import choose_bucket, estimate_bucket_ladder
from .file_schema import latest_analysis, latest_analyses_batch
from .schema import (
    create_analysis_run,
    ensure_cluster_analysis_schema,
    finalize_analysis_run,
    find_latest_analysis,
    mark_analysis_ingested,
    members_fingerprint,
)

logger = logging.getLogger(__name__)


def _connect_events(events_db: str) -> sqlite3.Connection:
    """Open the events db tolerating non-UTF-8 bytes stored by the pipeline.

    Disk images routinely contain filenames in legacy encodings; sqlite3's
    default strict UTF-8 decode turns any GROUP_CONCAT over such paths into a
    fetch-wide failure, so undecodable bytes are replaced instead.
    """
    conn = sqlite3.connect(events_db, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.text_factory = lambda b: b.decode("utf-8", "replace")
    return conn

# Initial-analysis clustering window. Phase C replaces this constant with the
# budget-driven adaptive selection (SPEC §5); until then the pipeline keeps the
# historical 60-second behavior.
PIPELINE_BUCKET_SECONDS = 60

# Map-reduce input bounds (SPEC §6): a chunk is bounded by BOTH the configured
# event count and a character budget, so no chunk can trip the LLM layer's
# own context guard (which would silently drop evidence lines).
CLUSTER_CHUNK_MAX_CHARS = 6000

MAP_CHUNK_PROMPT = (
    "以下是同一个事件簇的一份分片事件清单。请提炼本片的关键行为特征、"
    "值得注意的文件路径与时间规律，输出简洁的要点列表（纯文本，不要 Markdown）。"
)


def lines_from_paths_descs(paths: List[str], descs: List[str]) -> List[str]:
    """Evidence lines for pipeline clusters (paths/descs come from GROUP_CONCAT)."""
    return [f"- {path}: {desc}" for path, desc in zip(paths, descs)]


def lines_from_members(members: List[Dict[str, Any]]) -> List[str]:
    """Evidence lines for descriptor-resolved member rows (route path)."""
    return [
        f"- {member.get('timestamp')}: {member.get('event_type')} | "
        f"{member.get('file_path') or ''} | {member.get('description') or ''}"
        for member in members
    ]


def chunk_member_lines(
    lines: List[str],
    chunk_size: int,
    max_chars: int = CLUSTER_CHUNK_MAX_CHARS,
) -> List[str]:
    """Split evidence lines into chunks bounded by line count and char budget.

    Every line enters exactly one chunk — no sampling. A single line longer
    than ``max_chars`` gets a dedicated chunk rather than being cut.
    """
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0
    for line in lines:
        line_len = len(line) + 1
        if current and (len(current) >= chunk_size or current_len + line_len > max_chars):
            chunks.append("\n".join(current))
            current, current_len = [], 0
        current.append(line)
        current_len += line_len
    if current:
        chunks.append("\n".join(current))
    return chunks


async def analyze_cluster_members(
    llm_service,
    *,
    event_type: str,
    time_window: int,
    member_lines: List[str],
    chunk_size: int,
    prompt: Optional[str] = None,
    concurrency: int = 3,
) -> Dict[str, Any]:
    """Analyze every member line of a cluster (map-reduce, no sampling).

    Single chunk → one direct call. Multiple chunks → concurrent per-chunk
    point extraction (map), then one merge call producing the final four-part
    conclusion (reduce). A failed chunk fails the whole analysis: silently
    skipping evidence is never acceptable.
    """
    total = len(member_lines)
    chunks = chunk_member_lines(member_lines, chunk_size)

    if len(chunks) == 1:
        content = f"### 事件清单（共 {total} 条）\n{chunks[0]}"
        return await llm_service.analyze_event_cluster(
            event_data={
                "event_type": event_type,
                "description": content,
                "time_window": time_window,
            },
            prompt=prompt,
        )

    sem = asyncio.Semaphore(max(1, concurrency))

    async def map_chunk(index: int, chunk: str) -> str:
        async with sem:
            content = (
                f"### 事件清单（全簇共 {total} 条，本片为第 {index}/{len(chunks)} 片）\n{chunk}"
            )
            result = await llm_service.analyze_event_cluster(
                event_data={
                    "event_type": event_type,
                    "description": content,
                    "time_window": time_window,
                },
                prompt=MAP_CHUNK_PROMPT,
            )
            analysis = result.get("analysis", {})
            return analysis.get("description") or analysis.get("summary") or ""

    points = await asyncio.gather(
        *(map_chunk(i + 1, chunk) for i, chunk in enumerate(chunks))
    )
    usable_points = [point.strip() for point in points if point and point.strip()]
    joined = "\n".join(f"- {point}" for point in usable_points)
    content = (
        f"### 全簇概况\n共 {total} 条事件，已分 {len(chunks)} 片逐片分析，"
        f"以下为各片要点：\n{joined}"
    )
    result = await llm_service.analyze_event_cluster(
        event_data={
            "event_type": event_type,
            "description": content,
            "time_window": time_window,
        },
        prompt=prompt,
    )
    result["map_calls"] = len(chunks)
    result["reduce_calls"] = 1
    return result


class ClusterAnalyzer:
    """
    Handles event cluster analysis operations with Graphiti integration.

    Data Flow:
    - fetch_event_clusters() → Get clusters from _events.db
    - analyze_cluster() → LLM analysis
    - persist_cluster() → Save to _events.db
    - ingest_clusters_to_graphiti() → Send to Graphiti
    """

    def __init__(self, settings: Settings, llm_service, graphiti_service):
        """
        Initialize ClusterAnalyzer.

        Args:
            settings: Application settings
            llm_service: LLM service for analysis
            graphiti_service: Knowledge graph service (optional)
        """
        self.settings = settings
        self._llm_service = llm_service
        self._graphiti_service = graphiti_service

    async def analyze_and_ingest_clusters(
        self,
        events_db: str,
        case_description: str,
        task_id: str,
        progress_callback=None,
    ) -> List[Dict[str, Any]]:
        """
        Complete pipeline: select window, fetch, analyze, persist, and ingest.

        The clustering window is chosen by the budget-driven adaptive
        algorithm (SPEC §5); the run is recorded in ``cluster_analysis_runs``.
        The D9 skip filter (``llm_analyzed_at IS NULL``) is preserved — failed
        clusters stay re-runnable on the next pass.

        Args:
            events_db: Path to _events.db database
            case_description: Case description for LLM context
            task_id: Task identifier
            progress_callback: Optional progress callback

        Returns:
            List of cluster analysis results.
        """
        if not Path(events_db).exists():
            logger.warning(f"Events database not found: {events_db}")
            return []

        # Append-only analysis tables must exist before the first persist (SPEC §3.2).
        ensure_cluster_analysis_schema(events_db)

        # Step 0: adaptive window selection + run bookkeeping (SPEC §5).
        budget = getattr(self.settings, "llm_max_event_clusters", 200)
        scan = estimate_bucket_ladder(events_db, include_analyzed=False)
        choice = choose_bucket(scan["estimates"], budget)
        bucket_seconds = choice["recommended_bucket_seconds"]
        if choice["warning"]:
            logger.warning(f"Task {task_id}: adaptive bucket budget overshoot - {choice['warning']}")
        run_id = create_analysis_run(
            events_db, task_id, "pipeline", bucket_seconds, scan["bucket_epoch_offset"], budget
        )

        # Step 1: Fetch event clusters
        clusters = await self.fetch_event_clusters(events_db, bucket_seconds=bucket_seconds)
        if not clusters:
            logger.info(f"Task {task_id}: No event clusters to analyze")
            finalize_analysis_run(events_db, run_id, "completed", 0, 0, 0, 0)
            return []

        if progress_callback:
            await progress_callback("fetching_clusters", f"获取到 {len(clusters)} 个事件簇")

        # Step 2: Analyze each cluster (with concurrency control)
        results = await self._analyze_clusters_concurrent(
            clusters, case_description, events_db, progress_callback, task_id
        )

        # Step 3: Ingest to Graphiti
        if self._graphiti_service and results:
            if progress_callback:
                await progress_callback("ingesting_clusters", "正在将事件簇摄入知识图谱...")
            await self.ingest_clusters_to_graphiti(
                task_id, case_description, results, events_db=events_db
            )

        self._finalize_run_from_results(events_db, run_id, len(clusters), results)
        return results

    async def run_analysis(
        self,
        task_id: str,
        events_db: str,
        case_description: str = "",
        bucket_seconds: Optional[int] = None,
        progress_callback=None,
    ) -> Dict[str, Any]:
        """
        Task-level cluster analysis entry (SPEC §8.1 ``run`` endpoint backend).

        Covers every cluster at the chosen window: already-fresh coordinates
        (same member fingerprint) are skipped idempotently, stale or missing
        ones are analyzed. Records the run and returns a summary.
        """
        if not Path(events_db).exists():
            raise FileNotFoundError(f"Events database not found: {events_db}")

        ensure_cluster_analysis_schema(events_db)

        budget = getattr(self.settings, "llm_max_event_clusters", 200)
        scan = estimate_bucket_ladder(events_db, include_analyzed=True)
        warning = None
        if bucket_seconds:
            chosen = int(bucket_seconds)
            if chosen < 1 or chosen > TIMELINE_MAX_BUCKET_SECONDS:
                raise ValueError(f"bucket_seconds out of range: {chosen}")
        else:
            choice = choose_bucket(scan["estimates"], budget)
            chosen = choice["recommended_bucket_seconds"]
            warning = choice["warning"]
            if warning:
                logger.warning(f"Task {task_id}: adaptive bucket budget overshoot - {warning}")

        offset = scan["bucket_epoch_offset"]
        run_id = create_analysis_run(events_db, task_id, "task_run", chosen, offset, budget)

        clusters = await self.fetch_event_clusters(
            events_db, bucket_seconds=chosen, include_analyzed=True
        )

        pending: List[Dict[str, Any]] = []
        skipped_fresh = 0
        for cluster in clusters:
            latest = find_latest_analysis(
                events_db,
                cluster["bucket_epoch_offset"],
                cluster["bucket_seconds"],
                cluster["time_window"],
                cluster["event_type"],
                cluster["parent_directory"],
            )
            fresh = (
                latest is not None
                and latest["member_count"] == cluster["cluster_count"]
                and latest["member_min_id"] == cluster["first_event_id"]
                and latest["member_max_id"] == cluster["last_event_id"]
            )
            if fresh:
                skipped_fresh += 1
            else:
                pending.append(cluster)

        # The adaptive window only steers bucket choice; a timeline that
        # overshoots the budget at every candidate window would otherwise send
        # tens of thousands of clusters to the LLM. Enforce the budget by
        # keeping the most active clusters deterministically.
        skipped_over_budget = 0
        if len(pending) > budget:
            pending.sort(
                key=lambda c: (
                    -c["cluster_count"],
                    c["time_window"],
                    c["event_type"],
                    c["parent_directory"] or "",
                )
            )
            skipped_over_budget = len(pending) - budget
            pending = pending[:budget]
            logger.warning(
                f"Task {task_id}: cluster budget {budget} enforced, "
                f"{skipped_over_budget} clusters skipped (kept the most active ones)"
            )
            warning = warning or (
                f"cluster count exceeds the budget ({budget}); "
                f"analyzed only the {budget} most active clusters"
            )

        results = await self._analyze_clusters_concurrent(
            pending, case_description, events_db, progress_callback, task_id,
            trigger_source="task_run",
        )

        if self._graphiti_service and any(r.get("analysis_id") for r in results):
            await self.ingest_clusters_to_graphiti(
                task_id, case_description, results, events_db=events_db
            )

        self._finalize_run_from_results(events_db, run_id, len(clusters), results)
        return {
            "run_id": run_id,
            "task_id": task_id,
            "bucket_seconds": chosen,
            "bucket_epoch_offset": offset,
            "cluster_total": len(clusters),
            "analyzed": len(pending),
            "skipped_fresh": skipped_fresh,
            "skipped_over_budget": skipped_over_budget,
            "failed": sum(1 for r in results if not r.get("success")),
            "warning": warning,
            "results": results,
        }

    def _finalize_run_from_results(
        self, events_db: str, run_id: int, cluster_total: int, results: List[Dict[str, Any]]
    ) -> None:
        """Fold per-cluster results into the run row's final statistics."""
        successes = [r for r in results if r.get("success")]
        failed = len(results) - len(successes)
        map_calls = sum(r.get("map_calls", 1) for r in successes)
        reduce_calls = sum(r.get("reduce_calls", 1) for r in successes)
        model = next((r.get("model", "") for r in successes if r.get("model")), "")
        failures = [
            {"event_type": r.get("event_type"), "time_window": r.get("time_window"), "error": r.get("error")}
            for r in results
            if not r.get("success")
        ]
        detail = json.dumps({"failures": failures}, ensure_ascii=False)
        try:
            finalize_analysis_run(
                events_db, run_id, "completed", cluster_total, failed,
                map_calls, reduce_calls, model, detail,
            )
        except sqlite3.Error as e:
            logger.error(f"Failed to finalize analysis run #{run_id}: {e}")

    async def fetch_event_clusters(
        self,
        events_db: str,
        limit: Optional[int] = None,
        bucket_seconds: Optional[int] = None,
        include_analyzed: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Fetch event clusters from the events database.

        Clusters are grouped by (time_window, event_type, parent_directory)
        using the canonical bucket expression with the task's window-alignment
        offset (SPEC §4).

        Args:
            events_db: Path to _events.db database
            limit: Maximum number of clusters to fetch (None = no limit)
            bucket_seconds: Window width; defaults to the historical 60 s
            include_analyzed: False (pipeline, D9) keeps the
                ``llm_analyzed_at IS NULL`` skip filter; True groups every
                event — the task-level run uses this for full coverage

        Returns:
            List of cluster dictionaries.
        """
        window = int(bucket_seconds or PIPELINE_BUCKET_SECONDS)
        try:
            from .schema import read_bucket_epoch_offset

            offset = read_bucket_epoch_offset(events_db)
            with _connect_events(events_db) as conn:

                # Build SQL query
                limit_clause = f"LIMIT {limit}" if limit else ""
                analyzed_filter = "" if include_analyzed else "WHERE llm_analyzed_at IS NULL"
                sql = f"""
                    SELECT
                        ((timestamp - ?) / {window}) as time_window,
                        event_type,
                        COUNT(*) as cluster_count,
                        MIN(timestamp) as cluster_start,
                        MAX(timestamp) as cluster_end,
                        MIN(id) as first_event_id,
                        MAX(id) as last_event_id,
                        {PARENT_DIRECTORY_SQL} as parent_directory,
                        GROUP_CONCAT(COALESCE(description, ''), '\n') as group_desc,
                        GROUP_CONCAT(COALESCE(file_path, ''), '\n') as group_paths,
                        GROUP_CONCAT(id) as member_ids
                    FROM events
                    {analyzed_filter}
                    GROUP BY time_window, event_type, parent_directory
                    ORDER BY cluster_count DESC
                    {limit_clause}
                """

                cur = conn.execute(sql, (offset,))
                rows = cur.fetchall()
                clusters = []
                for row in rows:
                    cluster = dict(row)
                    # Coordinates carried through to the analysis record.
                    cluster["bucket_seconds"] = window
                    cluster["bucket_epoch_offset"] = offset
                    clusters.append(cluster)

                logger.info(
                    f"Fetched {len(clusters)} event clusters (bucket={window}s, "
                    f"include_analyzed={include_analyzed}) from {events_db}"
                )
                return clusters

        except sqlite3.Error as e:
            logger.error(f"Failed to fetch event clusters: {e}")
            return []

    async def _analyze_clusters_concurrent(
        self,
        clusters: List[Dict[str, Any]],
        case_description: str,
        events_db: str,
        progress_callback=None,
        task_id: str = "",
        trigger_source: str = "pipeline",
    ) -> List[Dict[str, Any]]:
        """
        Analyze clusters concurrently with semaphore control.

        Args:
            clusters: List of cluster dictionaries
            case_description: Case description for LLM context
            events_db: Path to _events.db for persistence
            progress_callback: Optional progress callback
            task_id: Task identifier recorded on each analysis row
            trigger_source: Recorded on each analysis row

        Returns:
            List of analysis results.
        """
        total = len(clusters)
        processed = 0

        # Concurrency control
        sem = asyncio.Semaphore(self.settings.llm_max_concurrency)

        async def analyze_one(cluster: Dict[str, Any]) -> Dict[str, Any]:
            nonlocal processed
            async with sem:
                try:
                    result = await self.analyze_cluster(cluster, case_description)
                    # Persist result (append analysis record + dual-write events)
                    result["analysis_id"] = self.persist_cluster_analysis(
                        events_db, cluster, result, task_id=task_id,
                        trigger_source=trigger_source,
                    )
                    processed += 1
                    if progress_callback:
                        await progress_callback(
                            processed, total,
                            f"分析事件簇: {cluster['event_type']} @ {cluster['time_window']}"
                        )

                    return result
                except Exception as e:
                    logger.warning(f"Failed to analyze cluster {cluster['time_window']}: {e}")
                    processed += 1
                    return {
                        "event_type": cluster.get("event_type", "UNKNOWN"),
                        "time_window": cluster.get("time_window", 0),
                        "success": False,
                        "error": str(e),
                    }

        tasks = [analyze_one(c) for c in clusters]
        return await asyncio.gather(*tasks)

    async def analyze_cluster(
        self,
        cluster: Dict[str, Any],
        case_description: str,
    ) -> Dict[str, Any]:
        """
        Analyze a single event cluster using LLM.

        Args:
            cluster: Cluster dictionary with event_type, time_window, etc.
            case_description: Case description for context

        Returns:
            Analysis result dictionary.
        """
        if not self._llm_service:
            raise RuntimeError("LLM service not initialized")

        # Full member list — no sampling (SPEC §6). The evidence lines flow to
        # the LLM via event_data.description, chunked map-reduce when needed.
        lines = lines_from_paths_descs(
            cluster['group_paths'].split('\n'),
            cluster['group_desc'].split('\n'),
        )
        prompt = f"""案情背景：{case_description}

请针对以上案情背景，分析这个事件簇在取证上的意义，并给出研判结论。

### 事件簇信息
- 类型: {cluster['event_type']}
- 时间窗口: {cluster['time_window']} (timestamp / {cluster.get('bucket_seconds', 60)})
- 事件数量: {cluster['cluster_count']}
- 目录: {cluster['parent_directory'] or '/'}
- 时间范围: {cluster['cluster_start']} ~ {cluster['cluster_end']}

请提供：
1. 简要总结（1-2句话概括事件簇的核心特征）
2. 详细分析（包括行为模式、时间特征、文件路径特征、行为意图研判）
3. 关键词（3-5个，用逗号分隔）
4. 取证价值评估（高/中/低，并说明理由）"""

        # Call LLM
        try:
            result = await analyze_cluster_members(
                self._llm_service,
                event_type=cluster['event_type'],
                time_window=cluster['time_window'],
                member_lines=lines,
                chunk_size=getattr(self.settings, "cluster_analysis_chunk_size", 200),
                prompt=prompt,
                concurrency=getattr(self.settings, "llm_max_concurrency", 3),
            )

            # Enhance result with cluster metadata
            result["event_type"] = cluster['event_type']
            result["time_window"] = cluster['time_window']
            result["cluster_count"] = cluster['cluster_count']
            result["parent_directory"] = cluster['parent_directory']
            result["success"] = True

            return result

        except Exception as e:
            logger.error(f"LLM analysis failed for cluster {cluster['time_window']}: {e}")
            return {
                "event_type": cluster['event_type'],
                "time_window": cluster['time_window'],
                "success": False,
                "error": str(e),
            }

    def persist_cluster_analysis(
        self,
        events_db: str,
        cluster: Dict[str, Any],
        analysis_result: Dict[str, Any],
        task_id: str = "",
        trigger_source: str = "pipeline",
    ):
        """
        Persist cluster analysis atomically (SPEC §3.2).

        Appends one row to ``event_cluster_analyses`` (the truth source) and
        dual-writes the denormalized ``llm_*`` cache onto every member event
        row, inside a single transaction: the member-rowcount check raising
        rolls back the analysis record too, so the two stores can never
        disagree.

        Args:
            events_db: Path to _events.db
            cluster: Original cluster data (needs member_ids and coordinates)
            analysis_result: LLM analysis result
            task_id: Task identifier recorded on the analysis row
            trigger_source: pipeline / timeline_auto / timeline_manual / task_run / migrated

        Returns:
            The new analysis record id. Raises on failure — callers treat the
            cluster as failed (SPEC D9: failed clusters stay re-runnable).
        """
        try:
            analysis = analysis_result.get("analysis", {})
            description = analysis.get("description", "")
            summary = analysis.get("summary", "") or description[:200]
            keywords = analysis.get("keywords", [])
            keywords_str = ", ".join(keywords) if isinstance(keywords, list) else str(keywords)
            model_used = analysis_result.get("model", "unknown")
            member_ids = [int(value) for value in str(cluster.get("member_ids") or "").split(",") if value]
            if not member_ids:
                raise sqlite3.DatabaseError("cluster has no trusted member IDs")

            fingerprint = members_fingerprint(member_ids)
            bucket_seconds = int(cluster.get("bucket_seconds") or PIPELINE_BUCKET_SECONDS)
            bucket_offset = int(cluster.get("bucket_epoch_offset") or 0)
            bucket_index = int(cluster.get("time_window") or 0)
            event_type = cluster.get("event_type") or "UNKNOWN"
            parent_directory = cluster.get("parent_directory") or ""
            is_relevant = 1 if bool(analysis.get("is_relevant", True)) else 0

            ensure_cluster_analysis_schema(events_db)

            with _connect_events(events_db) as conn:
                cur = conn.execute(
                    """
                    INSERT INTO event_cluster_analyses (
                        task_id, bucket_epoch_offset, bucket_seconds, bucket_index,
                        event_type, parent_directory, member_count, member_min_id,
                        member_max_id, members_hash, summary, description, keywords,
                        model, trigger_source, analysis_id_upstream, created_at, ingested_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, NULL)
                    """,
                    (
                        task_id,
                        bucket_offset,
                        bucket_seconds,
                        bucket_index,
                        event_type,
                        parent_directory,
                        fingerprint["member_count"],
                        fingerprint["member_min_id"],
                        fingerprint["member_max_id"],
                        fingerprint["members_hash"],
                        summary,
                        description,
                        keywords_str,
                        model_used,
                        trigger_source,
                        int(time.time()),
                    ),
                )
                analysis_id = cur.lastrowid

                placeholders = ", ".join("?" for _ in member_ids)
                sql = f"""
                    UPDATE events
                    SET llm_summary = ?,
                        llm_description = ?,
                        llm_keywords = ?,
                        llm_is_relevant = ?,
                        llm_analyzed_at = ?,
                        llm_model_used = ?
                    WHERE id IN ({placeholders})
                """
                now = int(time.time())
                cur_events = conn.execute(sql, (
                    summary, description, keywords_str, is_relevant, now, model_used, *member_ids
                ))
                if cur_events.rowcount != len(member_ids):
                    raise sqlite3.DatabaseError(
                        f"cluster member update incomplete: expected {len(member_ids)}, got {cur_events.rowcount}"
                    )
                conn.commit()

            logger.debug(
                f"Persisted cluster analysis #{analysis_id}: {event_type} @ {bucket_index}"
            )
            return analysis_id

        except sqlite3.Error as e:
            logger.error(f"Failed to persist cluster analysis: {e}")
            raise

    @staticmethod
    def _chunk_text(text: str, max_chars: Optional[int] = None) -> List[str]:
        """Split text into chunks (shared episode budget by default, D11)."""
        return chunk_text(text, max_chars)

    async def ingest_clusters_to_graphiti(
        self,
        task_id: str,
        case_description: str,
        cluster_results: List[Dict[str, Any]],
        events_db: str = "",
    ) -> bool:
        """
        Ingest cluster analysis results into the Graphiti knowledge graph.

        Marks the corresponding analysis rows as ingested only when every
        episode of a record made it (partial batches stay NULL for retry).
        """
        if not self._graphiti_service:
            logger.info("Graphiti service not available, skipping cluster ingestion")
            return False

        try:
            from graphiti_integration.toon_transformer import EpisodeData

            await self._graphiti_service.initialize()

            graph_entry = await self._graphiti_service._get_task_graph(task_id)
            if not graph_entry or not isinstance(graph_entry, dict):
                logger.warning(f"Could not get task graph for {task_id}")
                return False

            ingestor = graph_entry.get("ingestor")
            if not ingestor:
                logger.warning(f"No ingestor available for task {task_id}")
                return False

            episodes = []
            ingested_ids: List[int] = []

            # Only ingest successful analyses that carry a persisted record id.
            for cluster in [c for c in cluster_results if c.get("success")]:
                analysis_id = cluster.get("analysis_id")
                if not analysis_id:
                    continue
                record_episodes = build_analysis_episodes({
                    "id": analysis_id,
                    "event_type": cluster.get("event_type", "UNKNOWN"),
                    "bucket_seconds": cluster.get("bucket_seconds", PIPELINE_BUCKET_SECONDS),
                    "time_window": cluster.get("time_window", 0),
                    "parent_directory": cluster.get("parent_directory", ""),
                    "cluster_count": cluster.get("cluster_count", 0),
                    "description": (cluster.get("analysis") or {}).get("description", ""),
                })
                if record_episodes:
                    episodes.extend(record_episodes)
                    ingested_ids.append(analysis_id)

            if not episodes:
                logger.info("No cluster episodes to ingest")
                return True

            logger.info(f"Ingesting {len(episodes)} cluster episodes into Graphiti for task {task_id}")
            # §B1 (kg-ingestion-hardening): serialize with every other writer
            # on this group (file-episode dispatch, worker gap-fill, route path).
            async with self._graphiti_service.lock_for_group(task_id):
                result = await ingestor.batch_ingest(
                    episodes=episodes,
                    group_id=task_id,
                )
            successful = getattr(result, 'successful', 0)
            total = getattr(result, 'total_episodes', len(episodes))
            logger.info(f"Cluster Graphiti ingestion complete: {successful}/{total} successful")

            fully_ingested = total and successful == total
            if fully_ingested and events_db and ingested_ids:
                mark_analysis_ingested(events_db, ingested_ids)
            return successful > 0

        except ImportError:
            logger.warning("graphiti_integration not available, skipping cluster ingestion")
            return False
        except Exception as e:
            logger.error(f"Cluster Graphiti ingestion failed: {e}", exc_info=True)
            return False


def chunk_text(text: str, max_chars: Optional[int] = None) -> List[str]:
    """Split text into chunks, breaking at paragraph boundaries.

    ``max_chars`` defaults to the shared episode budget (SPEC file-analysis
    D11): floor(effective GRAPHITI_MAX_EPISODE_TOKENS × 3).
    """
    if max_chars is None:
        from ..graphiti_parts.episode_budget import episode_chunk_chars
        max_chars = episode_chunk_chars()
    if len(text) <= max_chars:
        return [text]

    chunks = []
    paragraphs = text.split("\n\n")
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            current = para
        else:
            current = current + "\n\n" + para if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


def build_analysis_episodes(
    analysis: Dict[str, Any],
    extra_body: Optional[Dict[str, Any]] = None,
) -> List[Any]:
    """Build Graphiti episodes for one persisted analysis record (SPEC §9).

    The episode name embeds the full cluster coordinate and the record id so
    re-analyses produce distinct, citable episodes instead of overwriting.
    ``extra_body`` merges caller context (e.g. case-level source_image /
    task_id tags) into the episode body.
    """
    from graphiti_integration.toon_transformer import EpisodeData

    description = analysis.get("description") or ""
    if not description:
        return []

    analysis_id = analysis["id"]
    event_type = analysis.get("event_type", "UNKNOWN")
    bucket_seconds = analysis.get("bucket_seconds", PIPELINE_BUCKET_SECONDS)
    bucket_index = analysis.get("time_window", analysis.get("bucket_index", 0))
    bucket_offset = int(analysis.get("bucket_epoch_offset") or 0)
    parent_directory = analysis.get("parent_directory", "")
    cluster_count = analysis.get("cluster_count", 0)

    # D12: the episode carries the cluster's forensic time — the window
    # start under the task's local alignment — not the ingestion instant.
    try:
        reference_time = datetime.fromtimestamp(bucket_index * bucket_seconds + bucket_offset)
    except (OverflowError, OSError, ValueError):
        reference_time = datetime.now()

    chunks = chunk_text(description)
    episodes = []
    for j, chunk in enumerate(chunks):
        ep_name = (
            f"事件簇分析: {event_type} @ {bucket_seconds}s/{bucket_index}"
            f" @ {parent_directory} #a{analysis_id}"
        )
        if len(chunks) > 1:
            ep_name += f" (第{j + 1}部分)"
        episodes.append(EpisodeData(
            name=ep_name,
            episode_body=json.dumps({
                "event_type": event_type,
                "bucket_epoch_seconds": bucket_seconds,
                "bucket_index": bucket_index,
                "parent_directory": parent_directory,
                "cluster_count": cluster_count,
                "analysis_id": analysis_id,
                "analysis": chunk,
                **(extra_body or {}),
            }, ensure_ascii=False),
            source_description=f"事件簇LLM分析 - {event_type} (count={cluster_count})",
            reference_time=reference_time,
            file_path="",
            file_id=0,
            category="event_cluster_description",
        ))
    return episodes


def related_file_summaries(
    events_db: str,
    files_db: str,
    *,
    bucket_epoch_offset: int,
    bucket_seconds: int,
    bucket_index: int,
    event_type: str,
    parent_directory: str,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """C3-v0 (SPEC file-analysis D9): distinct member files of one cluster
    with their latest AI summaries.

    Computed live from the current analysis state — nothing is denormalized
    into the events db (L1 auto-fresh). Ordered by member-event count,
    capped at ``limit``, summary-only to bound payload size. Files without
    an analysis record are skipped.
    """
    import sqlite3

    if not events_db or not Path(events_db).exists():
        return []
    start = int(bucket_index) * int(bucket_seconds) + int(bucket_epoch_offset or 0)
    end = start + int(bucket_seconds)
    try:
        with _connect_events(events_db) as conn:
            rows = conn.execute(
                f"SELECT file_path, COUNT(*) AS c FROM events "
                f"WHERE timestamp >= ? AND timestamp < ? AND event_type = ? "
                f"AND ({PARENT_DIRECTORY_SQL}) = ? "
                f"AND file_path IS NOT NULL AND file_path != '' "
                f"GROUP BY file_path ORDER BY c DESC LIMIT ?",
                (start, end, event_type, parent_directory, limit),
            ).fetchall()
    except sqlite3.Error:
        return []

    summaries: List[Dict[str, Any]] = []
    for file_path, _count in rows:
        record = latest_analysis(files_db, file_path) if files_db else None
        if not record or not (record.get("summary") or record.get("description")):
            continue
        summaries.append({
            "file_path": file_path,
            "summary": record.get("summary") or (record.get("description") or "")[:200],
            "model": record.get("model") or "",
            "analyzed_at": record.get("created_at"),
        })
    return summaries


def related_file_summaries_batch(
    events_db: str,
    files_db: str,
    records: List[Dict[str, Any]],
    *,
    limit: int = 20,
) -> List[List[Dict[str, Any]]]:
    """Batched :func:`related_file_summaries` — one result per input record.

    Per-record output is identical to calling ``related_file_summaries()``
    on that record; the difference is purely mechanical. Records on one page
    share heavily-overlapping time windows, so per-record GROUP BY scans made
    a 200-record page take >40s (plus one files-db connection per member
    file) and the evidence workspace rendered as an empty page while the
    request was in flight. Here: ONE events scan bucketed in memory by
    (event_type, parent) with bisected time windows, and ONE files-db
    connection for all latest-analysis lookups. Very large events tables
    fall back to per-record SQL under one connection.
    """
    empty: List[List[Dict[str, Any]]] = [[] for _ in records]
    if not records or not events_db or not Path(events_db).exists():
        return empty

    try:
        member_paths = _cluster_member_paths_batched(events_db, records, limit=limit)
    except sqlite3.Error:
        return empty

    # Newest analysis per member file (single files-db connection).
    wanted: set = set()
    for paths in member_paths:
        wanted.update(
            normalized for normalized in (
                normalize_evidence_path(p) for p in paths
            ) if normalized
        )
    latest = latest_analyses_batch(files_db, sorted(wanted))

    # Assemble per record, same fields/semantics as the single variant.
    all_summaries: List[List[Dict[str, Any]]] = []
    for paths in member_paths:
        summaries: List[Dict[str, Any]] = []
        for file_path in paths:
            record = latest.get(normalize_evidence_path(file_path))
            if not record or not (record.get("summary") or record.get("description")):
                continue
            summaries.append({
                "file_path": file_path,
                "summary": record.get("summary") or (record.get("description") or "")[:200],
                "model": record.get("model") or "",
                "analyzed_at": record.get("created_at"),
            })
        all_summaries.append(summaries)
    return all_summaries


# Events tables above this row count fall back to per-record SQL instead of
# materializing every (timestamp, event_type, file_path) row in memory.
_MEMBER_SCAN_MAX_EVENTS = 1_000_000


def _cluster_member_paths_batched(
    events_db: str,
    records: List[Dict[str, Any]],
    *,
    limit: int,
) -> List[List[str]]:
    """Distinct member files (count-ordered, capped at ``limit``) per record."""
    with _connect_events(events_db) as conn:
        total = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        if total > _MEMBER_SCAN_MAX_EVENTS:
            return _cluster_member_paths_per_record(conn, records, limit=limit)

        # One scan, grouped by the cluster coordinate; windows on a page
        # overlap heavily, so this replaces N index-range scans.
        groups: Dict[Any, List] = {}
        for ts, event_type, file_path in conn.execute(
            "SELECT timestamp, event_type, file_path FROM events "
            "WHERE file_path IS NOT NULL AND file_path != ''"
        ):
            groups.setdefault(
                (event_type or "", parent_directory_of(file_path)), []
            ).append((ts, file_path))

        member_paths: List[List[str]] = []
        for record in records:
            bucket_seconds = int(record.get("bucket_seconds") or 60)
            start = (
                int(record.get("bucket_index") or 0) * bucket_seconds
                + int(record.get("bucket_epoch_offset") or 0)
            )
            end = start + bucket_seconds
            times_paths = groups.get(
                (record.get("event_type") or "",
                 record.get("parent_directory") or ""),
                [],
            )
            if not times_paths:
                member_paths.append([])
                continue
            times_paths.sort(key=lambda item: item[0])
            times = [ts for ts, _ in times_paths]
            lo = bisect.bisect_left(times, start)
            hi = bisect.bisect_left(times, end)
            counts: Dict[str, int] = {}
            for _, file_path in times_paths[lo:hi]:
                counts[file_path] = counts.get(file_path, 0) + 1
            member_paths.append([
                file_path
                for file_path, _count in sorted(
                    counts.items(), key=lambda kv: (-kv[1], kv[0])
                )[:limit]
            ])
        return member_paths


def _cluster_member_paths_per_record(
    conn: sqlite3.Connection,
    records: List[Dict[str, Any]],
    *,
    limit: int,
) -> List[List[str]]:
    """Per-record member query (oversized events tables), one shared connection."""
    member_paths: List[List[str]] = []
    for record in records:
        bucket_seconds = int(record.get("bucket_seconds") or 60)
        start = (
            int(record.get("bucket_index") or 0) * bucket_seconds
            + int(record.get("bucket_epoch_offset") or 0)
        )
        end = start + bucket_seconds
        rows = conn.execute(
            f"SELECT file_path, COUNT(*) AS c FROM events "
            f"WHERE timestamp >= ? AND timestamp < ? AND event_type = ? "
            f"AND ({PARENT_DIRECTORY_SQL}) = ? "
            f"AND file_path IS NOT NULL AND file_path != '' "
            f"GROUP BY file_path ORDER BY c DESC LIMIT ?",
            (
                start,
                end,
                record.get("event_type") or "",
                record.get("parent_directory") or "",
                limit,
            ),
        ).fetchall()
        member_paths.append([row[0] for row in rows])
    return member_paths


async def ingest_analysis_record_to_graphiti(
    graphiti_service,
    task_id: str,
    analysis: Dict[str, Any],
    events_db: str = "",
) -> bool:
    """Ingest one persisted analysis record (route path, SPEC §7/D10).

    Failure is non-fatal by contract: the analysis is already persisted and
    only ``ingested_at`` stays NULL for a later retry.
    """
    if not graphiti_service:
        logger.info("Graphiti service not available, skipping cluster ingestion")
        return False
    try:
        await graphiti_service.initialize()
        graph_entry = await graphiti_service._get_task_graph(task_id)
        if not graph_entry or not isinstance(graph_entry, dict):
            logger.warning(f"Could not get task graph for {task_id}")
            return False
        ingestor = graph_entry.get("ingestor")
        if not ingestor:
            logger.warning(f"No ingestor available for task {task_id}")
            return False

        episodes = build_analysis_episodes(analysis)
        if not episodes:
            return True

        logger.info(f"Ingesting {len(episodes)} episode(s) for analysis #{analysis.get('id')}")
        # §B1 (kg-ingestion-hardening): every writer on one group — including
        # this SPEC ingestor — must hold the single-flight group lock, or
        # concurrent pipeline/gap-fill ingests interleave Graphiti writes.
        async with graphiti_service.lock_for_group(task_id):
            result = await ingestor.batch_ingest(episodes=episodes, group_id=task_id)
        total = getattr(result, "total_episodes", len(episodes))
        successful = getattr(result, "successful", 0)
        if total and successful == total and events_db:
            mark_analysis_ingested(events_db, [analysis["id"]])
        return successful > 0
    except ImportError:
        logger.warning("graphiti_integration not available, skipping cluster ingestion")
        return False
    except Exception as e:
        logger.error(f"Cluster Graphiti ingestion failed: {e}", exc_info=True)
        return False
