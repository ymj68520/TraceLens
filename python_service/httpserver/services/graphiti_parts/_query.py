"""Part of GraphitiService (split for maintainability).

This mixin contributes a group of methods to the GraphitiService class. It is
mixed into GraphitiService in services/graphiti_service.py and relies on the
instance attributes defined there (self.settings, self._initialized,
self._task_graphs, self._jobs, ...).
"""

import asyncio
import logging
import uuid
import os
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class GraphitiQueryMixin:
    """Auto-extracted method group; see module docstring."""

    async def search(
        self,
        query: str,
        task_id: str,
        entity_types: Optional[List[str]] = None,
        limit: int = 100,
        include_relationships: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Search the knowledge graph for a specific task.

        Uses COMBINED_HYBRID_SEARCH_RRF to retrieve edges (facts), nodes (entity summaries),
        and episodes (raw content), then formats them with meaningful text for report generation.

        Each result's ``properties`` dict contains a ``body`` key with the primary text:
          - Edges   → ``fact`` (LLM-extracted relationship text)
          - Nodes   → ``summary`` (entity region summary) or ``name``
          - Episodes → ``content`` (raw episode data)
        """
        if not self._initialized:
            # Fallback: Neo4j full-text search
            return await self._neo4j_text_search(query, task_id, limit)

        try:
            graph_entry = self._task_graphs.get(task_id)
            if graph_entry and isinstance(graph_entry, dict):
                ingestor = graph_entry.get("ingestor")
                if ingestor and ingestor._client:
                    # Use combined hybrid search to get edges + nodes + episodes
                    # (search() only returns edges; search_() returns all layers)
                    from graphiti_core.search.search_config_recipes import COMBINED_HYBRID_SEARCH_RRF
                    from graphiti_core.search.search_filters import SearchFilters

                    config = COMBINED_HYBRID_SEARCH_RRF.model_copy(update={'limit': limit})
                    search_results = await ingestor._client.search_(
                        query=query,
                        config=config,
                        group_ids=[task_id],
                        search_filter=SearchFilters(),
                    )

                    formatted: List[Dict[str, Any]] = []

                    # --- Edges: LLM-extracted facts (relationships) ---
                    edge_scores = getattr(search_results, 'edge_reranker_scores', []) or []
                    for i, edge in enumerate(search_results.edges or []):
                        fact = getattr(edge, 'fact', '') or ''
                        if not fact:
                            continue
                        score = edge_scores[i] if i < len(edge_scores) else 0.5
                        formatted.append({
                            "id": str(getattr(edge, 'uuid', '') or ''),
                            "name": getattr(edge, 'name', '') or '',
                            "type": "relationship",
                            "properties": {
                                "body": fact,
                                "fact": fact,
                                "source": getattr(edge, 'source_node_uuid', ''),
                                "target": getattr(edge, 'target_node_uuid', ''),
                            },
                            "score": score,
                        })

                    # --- Nodes: entity summaries ---
                    node_scores = getattr(search_results, 'node_reranker_scores', []) or []
                    for i, node in enumerate(search_results.nodes or []):
                        summary = getattr(node, 'summary', '') or ''
                        name = getattr(node, 'name', '') or ''
                        text = summary or name
                        if not text:
                            continue
                        score = node_scores[i] if i < len(node_scores) else 0.5
                        formatted.append({
                            "id": str(getattr(node, 'uuid', '') or ''),
                            "name": name,
                            "type": "entity",
                            "properties": {
                                "body": text,
                                "summary": summary,
                                "labels": getattr(node, 'labels', []) or [],
                            },
                            "score": score,
                        })

                    # --- Episodes: raw content ---
                    ep_scores = getattr(search_results, 'episode_reranker_scores', []) or []
                    for i, episode in enumerate(search_results.episodes or []):
                        content = getattr(episode, 'content', '') or ''
                        if not content:
                            continue
                        score = ep_scores[i] if i < len(ep_scores) else 0.5
                        formatted.append({
                            "id": str(getattr(episode, 'uuid', '') or ''),
                            "name": getattr(episode, 'name', '') or '',
                            "type": "episode",
                            "properties": {
                                "body": content,
                                "content": content,
                                "source_description": getattr(episode, 'source_description', ''),
                            },
                            "score": score,
                        })

                    # Sort by score descending, then limit
                    formatted.sort(key=lambda x: x.get('score', 0), reverse=True)
                    return formatted[:limit]

            # Fallback to Neo4j text search
            return await self._neo4j_text_search(query, task_id, limit)
        except Exception as e:
            logger.error(f"Graphiti search failed for task {task_id}: {e}")
            return await self._neo4j_text_search(query, task_id, limit)

    async def _neo4j_text_search(
        self, query: str, task_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Fallback text search using Neo4j CONTAINS through Episodic nodes."""
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    result = await session.run(
                        "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                        "WHERE toLower(n.name) CONTAINS toLower($q) "
                        "   OR toLower(coalesce(n.summary, '')) CONTAINS toLower($q) "
                        "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n)[0] AS type "
                        "LIMIT $lim",
                        gid=task_id, q=query, lim=limit,
                    )
                    rows = [dict(r) async for r in result]
                return [
                    {
                        "id": r.get("id", ""),
                        "name": r.get("name", ""),
                        "type": r.get("type", "unknown"),
                        "properties": {},
                        "score": 0.8,
                    }
                    for r in rows
                ]
            finally:
                await driver.close()
        except Exception as e:
            logger.error(f"Neo4j text search failed: {e}")
            return []

    async def list_entities(
        self,
        task_id: str,
        entity_type: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List entities in the knowledge graph for a specific task.
        """
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    skip = (page - 1) * page_size
                    if entity_type:
                        count_res = await session.run(
                            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) WHERE $et IN labels(n) "
                            "RETURN count(DISTINCT n) AS cnt",
                            gid=task_id, et=entity_type,
                        )
                        data_res = await session.run(
                            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) WHERE $et IN labels(n) "
                            "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n) AS type "
                            "SKIP $skip LIMIT $lim",
                            gid=task_id, et=entity_type, skip=skip, lim=page_size,
                        )
                    else:
                        count_res = await session.run(
                            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                            "RETURN count(DISTINCT n) AS cnt",
                            gid=task_id,
                        )
                        data_res = await session.run(
                            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                            "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n) AS type "
                            "SKIP $skip LIMIT $lim",
                            gid=task_id, skip=skip, lim=page_size,
                        )
                    count_row = await count_res.single()
                    total = count_row["cnt"] if count_row else 0
                    entities = [dict(record) async for record in data_res]
                return entities, total
            finally:
                await driver.close()
        except Exception as e:
            logger.error(f"List entities failed for task {task_id}: {e}")
            return [], 0

    async def list_relationships(
        self,
        task_id: str,
        relationship_type: Optional[str] = None,
        source_id: Optional[str] = None,
        target_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """
        List relationships in the knowledge graph for a specific task.
        In Graphiti, relationships are between entities mentioned in episodes of the task.
        """
        try:
            from neo4j import AsyncGraphDatabase
            driver = AsyncGraphDatabase.driver(
                self.settings.neo4j_uri,
                auth=(self.settings.neo4j_user, self.settings.neo4j_password),
            )
            try:
                async with driver.session() as session:
                    skip = (page - 1) * page_size

                    # Build match clause - relationships between entities mentioned in task's episodes
                    match_clause = "MATCH (e:Episodic {group_id: $gid})-[m1:MENTIONS]->(s:Entity)-[r:RELATES_TO]->(t:Entity)"

                    # Build where conditions - ensure target entity is also mentioned in task's episodes
                    where_clauses = ["(e)-[:MENTIONS]->(t)"]

                    params = {"gid": task_id, "skip": skip, "lim": page_size}

                    if relationship_type:
                        where_clauses.append("r.name = $rt")
                        params["rt"] = relationship_type
                    if source_id:
                        where_clauses.append("s.uuid = $sid")
                        params["sid"] = source_id
                    if target_id:
                        where_clauses.append("t.uuid = $tid")
                        params["tid"] = target_id

                    where_str = " WHERE " + " AND ".join(where_clauses)

                    # Count query
                    count_res = await session.run(
                        f"{match_clause} {where_str} RETURN count(DISTINCT r) AS cnt",
                        **params
                    )

                    # Data query
                    data_res = await session.run(
                        f"{match_clause} {where_str} "
                        "RETURN DISTINCT s.uuid AS source_id, s.name AS source_name, "
                        "       t.uuid AS target_id, t.name AS target_name, r.name AS type, "
                        "       r.uuid AS id "
                        "SKIP $skip LIMIT $lim",
                        **params
                    )

                    count_row = await count_res.single()
                    total = count_row["cnt"] if count_row else 0
                    rels = [dict(record) async for record in data_res]
                return rels, total
            finally:
                await driver.close()
        except Exception as e:
            logger.error(f"List relationships failed for task {task_id}: {e}")
            return [], 0

    async def get_graph_data(
        self,
        task_id: str,
        max_nodes: int = 200,
    ) -> tuple:
        """
        Get graph data for visualization filtered by task_id.
        """
        from neo4j import AsyncGraphDatabase
        driver = AsyncGraphDatabase.driver(
            self.settings.neo4j_uri,
            auth=(self.settings.neo4j_user, self.settings.neo4j_password),
        )
        try:
            async with driver.session() as session:
                # Fetch entities linked to episodes of this task
                node_result = await session.run(
                    "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                    "RETURN DISTINCT n.uuid AS id, n.name AS name, "
                    "       labels(n) AS labels, n.summary AS summary "
                    "LIMIT $lim",
                    gid=task_id, lim=max_nodes,
                )
                node_rows = [dict(r) async for r in node_result]

                node_ids = {r["id"] for r in node_rows}

                # Fetch relationships between those nodes
                rel_result = await session.run(
                    "MATCH (s:Entity)-[r:RELATES_TO]->(t:Entity) "
                    "WHERE s.uuid IN $ids AND t.uuid IN $ids "
                    "RETURN s.uuid AS source, t.uuid AS target, "
                    "       r.name AS label "
                    "LIMIT $lim",
                    ids=list(node_ids), lim=max_nodes * 3,
                )
                rel_rows = [dict(r) async for r in rel_result]

            nodes = [
                {
                    "id": r["id"],
                    "name": r["name"] or r["id"],
                    "label": (r["labels"][0] if isinstance(r.get("labels"), list) and r["labels"] else "Entity"),
                    "summary": r.get("summary") or "",
                }
                for r in node_rows
                if r.get("id")
            ]

            links = [
                {
                    "source": r["source"],
                    "target": r["target"],
                    "label": r.get("label", "RELATES_TO"),
                }
                for r in rel_rows
                if r.get("source") and r.get("target")
            ]

            return nodes, links
        finally:
            await driver.close()

