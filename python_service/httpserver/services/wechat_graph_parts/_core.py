"""Part of WeChatGraphService (split for maintainability).

This mixin contributes a group of methods to the WeChatGraphService class. It is
mixed into WeChatGraphService in services/wechat_graph_service.py and relies on
the instance attributes defined there (self._cache, ...).
"""

import asyncio
import logging
import os
import sqlite3
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class WeChatGraphCoreMixin:
    """Auto-extracted method group; see module docstring."""

    def __init__(self):
        """Initialize the WeChat Graph Service."""
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_ttl = CACHE_TTL

    def _get_cache_key(self, task_id: str, db_path: str) -> str:
        """
        Generate a cache key incorporating task_id and db file modification time.

        Args:
            task_id: The task identifier.
            db_path: Path to the _android.db file.

        Returns:
            A string cache key.
        """
        try:
            mtime = os.path.getmtime(db_path)
        except OSError:
            mtime = 0
        return f"{task_id}:{mtime}"

    def _is_cache_valid(self, cache_key: str) -> bool:
        """
        Check if a cached entry is still valid (not expired).

        Args:
            cache_key: The cache key to check.

        Returns:
            True if cache entry exists and has not expired.
        """
        if cache_key not in self._cache:
            return False
        entry = self._cache[cache_key]
        return (time.time() - entry.get("timestamp", 0)) < self._cache_ttl

    def invalidate_cache(self, task_id: str) -> None:
        """
        Clear all cached data for a given task_id.

        Args:
            task_id: The task identifier whose cache should be cleared.
        """
        keys_to_remove = [k for k in self._cache if k.startswith(f"{task_id}:")]
        for key in keys_to_remove:
            del self._cache[key]
        logger.info(f"Cache invalidated for task {task_id}")

    async def get_full_graph(
        self,
        task_id: str,
        db_path: str,
        include_metrics: bool = True,
    ) -> Dict[str, Any]:
        """
        Main entry point: get the full WeChat graph with analytics.

        Checks cache first, builds graph if needed, computes metrics,
        caches the result, and returns it.

        Args:
            task_id: The task identifier.
            db_path: Path to the _android.db file.
            include_metrics: Whether to compute PageRank, betweenness, communities.

        Returns:
            Dictionary with nodes, edges, communities, and metadata.
        """
        cache_key = self._get_cache_key(task_id, db_path)

        if self._is_cache_valid(cache_key):
            logger.info(f"Returning cached graph for task {task_id}")
            return self._cache[cache_key]["data"]

        logger.info(f"Building graph for task {task_id} from {db_path}")

        # Build graph in a thread to avoid blocking the event loop
        result = await asyncio.to_thread(
            self._build_and_analyze, task_id, db_path, include_metrics
        )

        # Cache the result
        self._cache[cache_key] = {
            "data": result,
            "timestamp": time.time(),
        }

        return result

    def _build_and_analyze(
        self, task_id: str, db_path: str, include_metrics: bool
    ) -> Dict[str, Any]:
        """
        Synchronous graph building and analysis pipeline.

        Args:
            task_id: The task identifier.
            db_path: Path to the _android.db file.
            include_metrics: Whether to compute analytics.

        Returns:
            Complete graph analysis result dictionary.
        """
        try:
            import networkx as nx
        except ImportError:
            logger.error("networkx is not installed. Install with: pip install networkx")
            return {
                "error": "networkx is not installed",
                "nodes": [],
                "edges": [],
                "communities": [],
                "metadata": {},
            }

        if not os.path.exists(db_path):
            logger.error(f"Database not found: {db_path}")
            return {
                "error": f"Database not found: {db_path}",
                "nodes": [],
                "edges": [],
                "communities": [],
                "metadata": {},
            }

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            G = self._build_graph(conn)
            result = self._compute_metrics(G) if include_metrics else self._graph_to_basic(G)
            result["metadata"] = {
                "task_id": task_id,
                "db_path": db_path,
                "node_count": G.number_of_nodes(),
                "edge_count": G.number_of_edges(),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            return result
        finally:
            conn.close()

    def _build_graph(self, conn: sqlite3.Connection):
        """
        Build a NetworkX DiGraph from the WeChat tables in _android.db.

        Nodes represent contacts (including the owner).
        Edges represent message flows (private) or co-activity (group).

        Args:
            conn: SQLite connection to the _android.db.

        Returns:
            A NetworkX DiGraph.
        """
        import networkx as nx

        G = nx.DiGraph()

        # 1. Get owner info
        owner = self._get_owner_from_conn(conn)
        owner_username = owner.get("username", "") if owner else ""

        # 2. Add owner as a node
        if owner_username:
            G.add_node(
                owner_username,
                label=owner.get("nickname", owner_username),
                is_owner=True,
                message_count=0,
            )

        # 3. Load contacts and add as nodes
        contacts = self._load_contacts(conn)
        contact_map = {}  # username -> {nickname, remark, ...}
        for c in contacts:
            username = c["username"]
            label = c.get("remark") or c.get("nickname") or username
            contact_map[username] = {
                "nickname": c.get("nickname", ""),
                "remark": c.get("remark", ""),
            }
            if not G.has_node(username):
                G.add_node(
                    username,
                    label=label,
                    is_owner=False,
                    message_count=0,
                )

        # 4. Process private messages -> directed edges
        self._add_private_message_edges(G, conn, owner_username, contact_map)

        # 5. Process group messages -> co-activity edges
        self._add_group_coactivity_edges(G, conn, owner_username, contact_map)

        return G

    def _get_owner_from_conn(self, conn: sqlite3.Connection) -> Optional[Dict[str, Any]]:
        """Fetch the WeChat owner info from the database."""
        try:
            cursor = conn.execute(
                "SELECT username, nickname, uin, imei FROM wechat_owner_info LIMIT 1"
            )
            row = cursor.fetchone()
            if row:
                return {
                    "username": row["username"] or "",
                    "nickname": row["nickname"] or "",
                    "uin": row["uin"],
                    "imei": row["imei"] or "",
                }
        except sqlite3.OperationalError as e:
            logger.warning(f"wechat_owner_info table not found or error: {e}")
        return None

    def _load_contacts(self, conn: sqlite3.Connection) -> List[Dict[str, Any]]:
        """Load all WeChat contacts from the database."""
        contacts = []
        try:
            cursor = conn.execute(
                "SELECT username, nickname, remark, avatar_path, type, chatroom_flag "
                "FROM wechat_contacts"
            )
            for row in cursor.fetchall():
                contacts.append({
                    "username": row["username"] or "",
                    "nickname": row["nickname"] or "",
                    "remark": row["remark"] or "",
                    "avatar_path": row["avatar_path"] or "",
                    "type": row["type"],
                    "chatroom_flag": row["chatroom_flag"],
                })
        except sqlite3.OperationalError as e:
            logger.warning(f"wechat_contacts table not found or error: {e}")
        return contacts

    def _add_private_message_edges(
        self,
        G,
        conn: sqlite3.Connection,
        owner_username: str,
        contact_map: Dict,
    ) -> None:
        """
        Aggregate private (non-group) messages into directed weighted edges.

        For each sender->receiver pair outside of chatrooms, creates/updates an edge
        with weight (message count), total_chars, first_time, last_time,
        sent_count, received_count.
        """
        try:
            cursor = conn.execute(
                """
                SELECT
                    sender,
                    receiver,
                    COUNT(*) as msg_count,
                    SUM(LENGTH(COALESCE(content, ''))) as total_chars,
                    MIN(timestamp) as first_time,
                    MAX(timestamp) as last_time
                FROM wechat_messages
                WHERE (chatroom_name IS NULL OR chatroom_name = '')
                  AND sender IS NOT NULL
                  AND receiver IS NOT NULL
                  AND sender != ''
                  AND receiver != ''
                GROUP BY sender, receiver
                """
            )

            for row in cursor.fetchall():
                sender = row["sender"]
                receiver = row["receiver"]
                msg_count = row["msg_count"]
                total_chars = row["total_chars"] or 0
                first_time = row["first_time"]
                last_time = row["last_time"]

                # Ensure nodes exist
                if not G.has_node(sender):
                    label = contact_map.get(sender, {}).get("remark") or \
                            contact_map.get(sender, {}).get("nickname") or sender
                    G.add_node(sender, label=label, is_owner=False, message_count=0)
                if not G.has_node(receiver):
                    label = contact_map.get(receiver, {}).get("remark") or \
                            contact_map.get(receiver, {}).get("nickname") or receiver
                    G.add_node(receiver, label=label, is_owner=False, message_count=0)

                # Update node message counts
                G.nodes[sender]["message_count"] = (
                    G.nodes[sender].get("message_count", 0) + msg_count
                )

                # Determine sent/received from owner's perspective
                is_owner_sender = (sender == owner_username)
                sent_count = msg_count if is_owner_sender else 0
                received_count = msg_count if not is_owner_sender else 0

                # If edge already exists, merge
                if G.has_edge(sender, receiver):
                    edge_data = G[sender][receiver]
                    edge_data["weight"] = edge_data.get("weight", 0) + msg_count
                    edge_data["total_chars"] = edge_data.get("total_chars", 0) + total_chars
                    edge_data["sent_count"] = edge_data.get("sent_count", 0) + sent_count
                    edge_data["received_count"] = edge_data.get("received_count", 0) + received_count
                    if first_time and (not edge_data.get("first_time") or first_time < edge_data["first_time"]):
                        edge_data["first_time"] = first_time
                    if last_time and (not edge_data.get("last_time") or last_time > edge_data["last_time"]):
                        edge_data["last_time"] = last_time
                else:
                    G.add_edge(
                        sender,
                        receiver,
                        weight=msg_count,
                        total_chars=total_chars,
                        first_time=first_time,
                        last_time=last_time,
                        sent_count=sent_count,
                        received_count=received_count,
                        edge_type="private",
                    )

        except sqlite3.OperationalError as e:
            logger.warning(f"Error reading wechat_messages for private edges: {e}")

    def _add_group_coactivity_edges(
        self,
        G,
        conn: sqlite3.Connection,
        owner_username: str,
        contact_map: Dict,
    ) -> None:
        """
        Add co-activity edges for users who are active in the same group
        within a 1-hour window.

        For each chatroom, fetch messages ordered by timestamp, then for
        each pair of users active within a 1-hour window, add/extend a
        co-activity edge.
        """
        ONE_HOUR_MS = 3600 * 1000  # 1 hour in milliseconds (timestamps are in ms)

        try:
            # Get distinct chatrooms with messages
            cursor = conn.execute(
                """
                SELECT DISTINCT chatroom_name
                FROM wechat_messages
                WHERE chatroom_name IS NOT NULL AND chatroom_name != ''
                """
            )
            chatrooms = [row["chatroom_name"] for row in cursor.fetchall()]

            for chatroom_name in chatrooms:
                # Fetch messages in this chatroom ordered by timestamp
                msg_cursor = conn.execute(
                    """
                    SELECT sender, timestamp
                    FROM wechat_messages
                    WHERE chatroom_name = ?
                      AND sender IS NOT NULL
                      AND sender != ''
                      AND timestamp IS NOT NULL
                    ORDER BY timestamp ASC
                    """,
                    (chatroom_name,),
                )
                messages = msg_cursor.fetchall()

                if len(messages) < 2:
                    continue

                # Sliding window: for each message, find other users active
                # within the 1-hour window
                seen_pairs = set()
                for i, msg_i in enumerate(messages):
                    sender_i = msg_i["sender"]
                    ts_i = msg_i["timestamp"]

                    for j in range(i + 1, len(messages)):
                        msg_j = messages[j]
                        ts_j = msg_j["timestamp"]

                        # Since messages are sorted, break if beyond window
                        if ts_j - ts_i > ONE_HOUR_MS:
                            break

                        sender_j = msg_j["sender"]
                        if sender_i == sender_j:
                            continue

                        # Create a canonical pair key
                        pair = (min(sender_i, sender_j), max(sender_i, sender_j))
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)

                        u, v = pair
                        # Ensure nodes exist
                        if not G.has_node(u):
                            label = contact_map.get(u, {}).get("remark") or \
                                    contact_map.get(u, {}).get("nickname") or u
                            G.add_node(u, label=label, is_owner=False, message_count=0)
                        if not G.has_node(v):
                            label = contact_map.get(v, {}).get("remark") or \
                                    contact_map.get(v, {}).get("nickname") or v
                            G.add_node(v, label=label, is_owner=False, message_count=0)

                        # Add bidirectional co-activity edges
                        for src, dst in [(u, v), (v, u)]:
                            if G.has_edge(src, dst):
                                edge_data = G[src][dst]
                                if edge_data.get("edge_type") == "group":
                                    edge_data["weight"] = edge_data.get("weight", 0) + 1
                            else:
                                G.add_edge(
                                    src,
                                    dst,
                                    weight=1,
                                    edge_type="group",
                                    chatroom=chatroom_name,
                                    total_chars=0,
                                    first_time=ts_i,
                                    last_time=ts_j,
                                    sent_count=0,
                                    received_count=0,
                                )

        except sqlite3.OperationalError as e:
            logger.warning(f"Error reading wechat_messages for group edges: {e}")

