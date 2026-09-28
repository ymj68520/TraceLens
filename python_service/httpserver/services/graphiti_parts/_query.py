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
            rows = await self._run_read_query(
                "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                "WHERE toLower(n.name) CONTAINS toLower($q) "
                "   OR toLower(coalesce(n.summary, '')) CONTAINS toLower($q) "
                "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n)[0] AS type "
                "LIMIT $lim",
                {"gid": task_id, "q": query, "lim": limit},
            )
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
            skip = (page - 1) * page_size
            if entity_type:
                count_rows = await self._run_read_query(
                    "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) WHERE $et IN labels(n) "
                    "RETURN count(DISTINCT n) AS cnt",
                    {"gid": task_id, "et": entity_type},
                )
                entities = await self._run_read_query(
                    "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) WHERE $et IN labels(n) "
                    "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n) AS type "
                    "SKIP $skip LIMIT $lim",
                    {"gid": task_id, "et": entity_type, "skip": skip, "lim": page_size},
                )
            else:
                count_rows = await self._run_read_query(
                    "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                    "RETURN count(DISTINCT n) AS cnt",
                    {"gid": task_id},
                )
                entities = await self._run_read_query(
                    "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
                    "RETURN DISTINCT n.uuid AS id, n.name AS name, labels(n) AS type "
                    "SKIP $skip LIMIT $lim",
                    {"gid": task_id, "skip": skip, "lim": page_size},
                )
            total = count_rows[0]["cnt"] if count_rows else 0
            return entities, total
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
            skip = (page - 1) * page_size

            # Build match clause - relationships between entities mentioned in task's episodes
            match_clause = "MATCH (e:Episodic {group_id: $gid})-[m1:MENTIONS]->(s:Entity)-[r:RELATES_TO]->(t:Entity)"

            # Build where conditions - ensure target entity is also mentioned in task's episodes
            where_clauses = ["(e)-[:MENTIONS]->(t)", "r.group_id = $gid"]

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
            count_rows = await self._run_read_query(
                f"{match_clause} {where_str} RETURN count(DISTINCT r) AS cnt",
                params,
            )

            # Data query
            rels = await self._run_read_query(
                f"{match_clause} {where_str} "
                "RETURN DISTINCT s.uuid AS source_id, s.name AS source_name, "
                "       t.uuid AS target_id, t.name AS target_name, r.name AS type, "
                "       r.uuid AS id "
                "SKIP $skip LIMIT $lim",
                params,
            )

            total = count_rows[0]["cnt"] if count_rows else 0
            return rels, total
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
        node_rows = await self._run_read_query(
            "MATCH (e:Episodic {group_id: $gid})-[m:MENTIONS]->(n:Entity) "
            "RETURN DISTINCT n.uuid AS id, n.name AS name, "
            "       labels(n) AS labels, n.summary AS summary "
            "LIMIT $lim",
            {"gid": task_id, "lim": max_nodes},
        )

        node_ids = {r["id"] for r in node_rows}

        # Fetch relationships between those nodes
        rel_rows = await self._run_read_query(
            "MATCH (s:Entity)-[r:RELATES_TO]->(t:Entity) "
            "WHERE r.group_id = $gid AND s.uuid IN $ids AND t.uuid IN $ids "
            "RETURN r.uuid AS id, s.uuid AS source, t.uuid AS target, "
            "       r.name AS label "
            "LIMIT $lim",
            {"gid": task_id, "ids": list(node_ids), "lim": max_nodes * 3},
        )

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
                "id": r.get("id"),
                "source": r["source"],
                "target": r["target"],
                "label": r.get("label", "RELATES_TO"),
            }
            for r in rel_rows
            if r.get("source") and r.get("target")
        ]

        return nodes, links

    async def get_relationship_trace(
        self, task_id: str, relationship_id: str, *, max_episodes: int = 10
    ) -> dict | None:
        """Read one task-owned extracted fact and its exact source episodes."""
        rows = await self._run_read_query(
            "MATCH (s:Entity)-[r:RELATES_TO {uuid: $rid}]->(t:Entity) "
            "WHERE r.group_id = $gid "
            "RETURN r.uuid AS id, r.name AS label, r.fact AS fact, "
            "r.episodes AS episode_ids, r.created_at AS created_at, "
            "s.uuid AS source_id, s.name AS source_name, "
            "t.uuid AS target_id, t.name AS target_name LIMIT 1",
            {"gid": task_id, "rid": relationship_id},
        )
        if not rows:
            return None
        edge = rows[0]
        episode_ids = list(dict.fromkeys(
            item for item in (edge.get("episode_ids") or []) if isinstance(item, str)
        ))
        selected_ids = episode_ids[:max_episodes]
        episode_rows = await self._run_read_query(
            "MATCH (e:Episodic {group_id: $gid}) "
            "WHERE e.uuid IN $ids "
            "RETURN e.uuid AS id, e.name AS name, e.content AS content, "
            "e.source_description AS source_description",
            {"gid": task_id, "ids": selected_ids},
        ) if selected_ids else []
        episodes_by_id = {row["id"]: row for row in episode_rows}
        episodes = []
        for episode_id in selected_ids:
            row = episodes_by_id.get(episode_id)
            if row is None:
                continue
            content = row.get("content") or ""
            episodes.append({
                "id": episode_id,
                "name": row.get("name") or "",
                "source_description": row.get("source_description") or "",
                "content": content[:12_000],
                "content_truncated": len(content) > 12_000,
            })
        return {
            "id": edge["id"],
            "label": edge.get("label") or "RELATES_TO",
            "fact": edge.get("fact") or "",
            "source": {"id": edge["source_id"], "name": edge.get("source_name") or ""},
            "target": {"id": edge["target_id"], "name": edge.get("target_name") or ""},
            "created_at": str(edge.get("created_at") or ""),
            "episode_count": len(episode_ids),
            "episodes": episodes,
        }

    async def get_local_graph_data(
        self, task_id: str, evidence_path: str, max_nodes: int = 50
    ) -> tuple[list[dict], list[dict]]:
        """Exact file-path entity and its task-scoped one-hop KG neighbours.

        An arbitrary first page of the task graph is not a local evidence
        graph. Never fall back to a basename: duplicate filenames may refer
        to different evidence in the same image.
        """
        seed_rows = await self._run_read_query(
            "MATCH (:Episodic {group_id: $gid})-[:MENTIONS]->"
            "(seed:Entity {name: $path}) "
            "RETURN DISTINCT seed.uuid AS id, seed.name AS name, "
            "labels(seed) AS labels, seed.summary AS summary LIMIT 1",
            {"gid": task_id, "path": evidence_path},
        )
        if not seed_rows:
            return [], []

        seed = seed_rows[0]
        nodes = [{
            "id": seed["id"], "name": seed["name"],
            "label": (seed["labels"] or ["Entity"])[0],
            "summary": seed.get("summary") or "",
        }]
        links: list[dict] = []
        if max_nodes <= 1:
            return nodes, links

        rows = await self._run_read_query(
            "MATCH (seed:Entity {uuid: $seed_id})-[r:RELATES_TO]-"
            "(neighbor:Entity) "
            "WHERE r.group_id = $gid AND EXISTS { "
            "MATCH (:Episodic {group_id: $gid})-"
            "[:MENTIONS]->(neighbor) } "
            "RETURN DISTINCT neighbor.uuid AS id, neighbor.name AS name, "
            "labels(neighbor) AS labels, neighbor.summary AS summary, "
            "startNode(r).uuid AS source, endNode(r).uuid AS target, "
            "r.name AS relation LIMIT $lim",
            {"gid": task_id, "seed_id": seed["id"], "lim": max_nodes * 3},
        )
        seen = {seed["id"]}
        for row in rows:
            node_id = row.get("id")
            if not node_id:
                continue
            if node_id not in seen:
                if len(nodes) >= max_nodes:
                    continue
                seen.add(node_id)
                nodes.append({
                    "id": node_id, "name": row.get("name") or node_id,
                    "label": (row.get("labels") or ["Entity"])[0],
                    "summary": row.get("summary") or "",
                })
            source, target = row.get("source"), row.get("target")
            if source in seen and target in seen:
                links.append({
                    "source": source, "target": target,
                    "label": row.get("relation") or "RELATES_TO",
                })
        return nodes, links
