"""
WeChat Graph Service - Social network analysis for WeChat forensic data.

This service reads from _android.db, builds a NetworkX directed graph,
computes social network analytics (PageRank, betweenness centrality,
community detection), and provides caching for performance.

Typical usage:
    service = WeChatGraphService()
    result = await service.get_full_graph(task_id, db_path)
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

# Cache TTL in seconds (30 minutes)
CACHE_TTL = 1800


class WeChatGraphService:
    """
    Service for WeChat social network graph analysis.

    Reads from _android.db (wechat_owner_info, wechat_contacts,
    wechat_messages, wechat_chatrooms), builds a NetworkX DiGraph,
    and computes analytics including PageRank, betweenness centrality,
    and Louvain community detection.
    """

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

    # -------------------------------------------------------------------------
    # Graph Construction
    # -------------------------------------------------------------------------

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

    # -------------------------------------------------------------------------
    # Graph Algorithms / Metrics
    # -------------------------------------------------------------------------

    def _compute_metrics(self, G) -> Dict[str, Any]:
        """
        Compute graph analytics: PageRank, betweenness centrality,
        and Louvain community detection.

        Args:
            G: NetworkX DiGraph.

        Returns:
            Dictionary with nodes (with metrics), edges, and communities.
        """
        import networkx as nx

        if G.number_of_nodes() == 0:
            return {"nodes": [], "edges": [], "communities": []}

        # PageRank
        try:
            pagerank = nx.pagerank(G, weight="weight")
        except Exception as e:
            logger.warning(f"PageRank computation failed: {e}")
            pagerank = {n: 0.0 for n in G.nodes()}

        # Betweenness centrality
        try:
            betweenness = nx.betweenness_centrality(G, weight="weight")
        except Exception as e:
            logger.warning(f"Betweenness centrality computation failed: {e}")
            betweenness = {n: 0.0 for n in G.nodes()}

        # Community detection (Louvain on undirected projection)
        communities = self._detect_communities(G)

        # Build node -> community mapping
        node_community = {}
        for idx, community in enumerate(communities):
            for node in community:
                node_community[node] = idx

        # Assemble node list with metrics
        nodes = []
        for node in G.nodes():
            node_data = G.nodes[node]
            nodes.append({
                "id": node,
                "label": node_data.get("label", node),
                "is_owner": node_data.get("is_owner", False),
                "message_count": node_data.get("message_count", 0),
                "pagerank": round(pagerank.get(node, 0.0), 6),
                "betweenness": round(betweenness.get(node, 0.0), 6),
                "cluster": node_community.get(node, -1),
            })

        # Assemble edge list
        edges = []
        for u, v, data in G.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "weight": data.get("weight", 1),
                "edge_type": data.get("edge_type", "private"),
                "total_chars": data.get("total_chars", 0),
                "first_time": data.get("first_time"),
                "last_time": data.get("last_time"),
                "sent_count": data.get("sent_count", 0),
                "received_count": data.get("received_count", 0),
            })

        # Format communities as list of lists of node IDs
        communities_list = [list(c) for c in communities]

        return {
            "nodes": nodes,
            "edges": edges,
            "communities": communities_list,
        }

    def _detect_communities(self, G) -> List[List[str]]:
        """
        Detect communities using the Louvain algorithm.

        Falls back to connected components if python-louvain is not available.

        Args:
            G: NetworkX DiGraph.

        Returns:
            List of communities (each community is a list of node IDs).
        """
        import networkx as nx

        # Convert to undirected for community detection
        G_undirected = G.to_undirected()

        try:
            import community as community_louvain
            partition = community_louvain.best_partition(G_undirected, weight="weight")
            # Group nodes by community ID
            communities = defaultdict(list)
            for node, comm_id in partition.items():
                communities[comm_id].append(node)
            return list(communities.values())
        except ImportError:
            logger.warning(
                "python-louvain not installed. Falling back to connected components. "
                "Install with: pip install python-louvain"
            )
        except Exception as e:
            logger.warning(f"Louvain community detection failed: {e}. Falling back to connected components.")

        # Fallback: use connected components
        try:
            components = nx.connected_components(G_undirected)
            return [list(c) for c in components]
        except Exception as e:
            logger.warning(f"Connected components fallback also failed: {e}")
            # Last resort: all nodes in one community
            return [list(G.nodes())]

    def _graph_to_basic(self, G) -> Dict[str, Any]:
        """
        Convert graph to basic node/edge lists without computing analytics.

        Args:
            G: NetworkX DiGraph.

        Returns:
            Dictionary with nodes and edges (no metrics).
        """
        nodes = []
        for node in G.nodes():
            node_data = G.nodes[node]
            nodes.append({
                "id": node,
                "label": node_data.get("label", node),
                "is_owner": node_data.get("is_owner", False),
                "message_count": node_data.get("message_count", 0),
                "pagerank": 0.0,
                "betweenness": 0.0,
                "cluster": -1,
            })

        edges = []
        for u, v, data in G.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "weight": data.get("weight", 1),
                "edge_type": data.get("edge_type", "private"),
                "total_chars": data.get("total_chars", 0),
                "first_time": data.get("first_time"),
                "last_time": data.get("last_time"),
                "sent_count": data.get("sent_count", 0),
                "received_count": data.get("received_count", 0),
            })

        return {
            "nodes": nodes,
            "edges": edges,
            "communities": [],
        }

    # -------------------------------------------------------------------------
    # Timeline Analysis
    # -------------------------------------------------------------------------

    async def compute_timeline(
        self,
        task_id: str,
        db_path: str,
        granularity: str = "month",
    ) -> Dict[str, Any]:
        """
        Compute message timeline aggregated by month or week.

        Args:
            task_id: The task identifier.
            db_path: Path to the _android.db file.
            granularity: 'month' or 'week'.

        Returns:
            Dictionary with timeline intervals.
        """
        return await asyncio.to_thread(
            self._compute_timeline_sync, db_path, granularity
        )

    def _compute_timeline_sync(
        self, db_path: str, granularity: str
    ) -> Dict[str, Any]:
        """
        Synchronous timeline computation.

        Args:
            db_path: Path to the _android.db file.
            granularity: 'month' or 'week'.

        Returns:
            Timeline result dictionary.
        """
        if not os.path.exists(db_path):
            return {"error": f"Database not found: {db_path}", "intervals": []}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT sender, receiver, timestamp
                FROM wechat_messages
                WHERE timestamp IS NOT NULL AND timestamp > 0
                """
            )
            messages = cursor.fetchall()

            if not messages:
                return {"intervals": [], "granularity": granularity}

            # Group by period
            period_data = defaultdict(lambda: {
                "total_messages": 0,
                "active_edges": set(),
                "top_contacts": defaultdict(int),
            })

            for msg in messages:
                ts = msg["timestamp"]
                sender = msg["sender"] or ""
                receiver = msg["receiver"] or ""

                # Convert timestamp (ms) to datetime
                try:
                    dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                except (OSError, ValueError):
                    continue

                if granularity == "week":
                    # ISO week: YYYY-Www
                    period_key = f"{dt.isocalendar()[0]}-W{dt.isocalendar()[1]:02d}"
                else:
                    # Month: YYYY-MM
                    period_key = f"{dt.year}-{dt.month:02d}"

                period_data[period_key]["total_messages"] += 1
                if sender and receiver:
                    edge_key = tuple(sorted([sender, receiver]))
                    period_data[period_key]["active_edges"].add(edge_key)
                if sender:
                    period_data[period_key]["top_contacts"][sender] += 1
                if receiver:
                    period_data[period_key]["top_contacts"][receiver] += 1

            # Format output
            intervals = []
            for period_key in sorted(period_data.keys()):
                data = period_data[period_key]
                top_contacts = sorted(
                    data["top_contacts"].items(),
                    key=lambda x: x[1],
                    reverse=True,
                )[:10]
                intervals.append({
                    "period": period_key,
                    "total_messages": data["total_messages"],
                    "active_edges": len(data["active_edges"]),
                    "top_contacts": [
                        {"username": username, "message_count": count}
                        for username, count in top_contacts
                    ],
                })

            return {
                "granularity": granularity,
                "intervals": intervals,
            }

        except sqlite3.OperationalError as e:
            logger.warning(f"Error computing timeline: {e}")
            return {"error": str(e), "intervals": []}
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Chat History
    # -------------------------------------------------------------------------

    async def get_chat_history(
        self,
        db_path: str,
        contact_username: str,
        owner_username: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """
        Get paginated private chat history between the owner and a contact.

        Args:
            db_path: Path to the _android.db file.
            contact_username: The contact's username.
            owner_username: The owner's username (optional, auto-detected if empty).
            page: Page number (1-based).
            page_size: Number of messages per page.

        Returns:
            Dictionary with messages, pagination info.
        """
        return await asyncio.to_thread(
            self._get_chat_history_sync,
            db_path, contact_username, owner_username, page, page_size,
        )

    def _get_chat_history_sync(
        self,
        db_path: str,
        contact_username: str,
        owner_username: str,
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        """
        Synchronous private chat history retrieval.
        """
        if not os.path.exists(db_path):
            return {"error": f"Database not found: {db_path}", "messages": [], "total": 0}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Auto-detect owner if not provided
            if not owner_username:
                owner_info = self._get_owner_from_conn(conn)
                owner_username = owner_info.get("username", "") if owner_info else ""

            # Count total messages
            count_cursor = conn.execute(
                """
                SELECT COUNT(*) as total
                FROM wechat_messages
                WHERE (chatroom_name IS NULL OR chatroom_name = '')
                  AND (
                    (sender = ? AND receiver = ?)
                    OR (sender = ? AND receiver = ?)
                  )
                """,
                (owner_username, contact_username, contact_username, owner_username),
            )
            total = count_cursor.fetchone()["total"]

            # Fetch page
            offset = (page - 1) * page_size
            cursor = conn.execute(
                """
                SELECT id, sender, receiver, content, timestamp,
                       media_url, media_type, msg_type, is_send
                FROM wechat_messages
                WHERE (chatroom_name IS NULL OR chatroom_name = '')
                  AND (
                    (sender = ? AND receiver = ?)
                    OR (sender = ? AND receiver = ?)
                  )
                ORDER BY timestamp ASC
                LIMIT ? OFFSET ?
                """,
                (owner_username, contact_username,
                 contact_username, owner_username,
                 page_size, offset),
            )

            messages = []
            for row in cursor.fetchall():
                messages.append({
                    "id": row["id"],
                    "sender": row["sender"],
                    "receiver": row["receiver"],
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                    "media_url": row["media_url"],
                    "media_type": row["media_type"],
                    "msg_type": row["msg_type"],
                    "is_send": row["is_send"],
                })

            return {
                "messages": messages,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
            }

        except sqlite3.OperationalError as e:
            logger.warning(f"Error fetching chat history: {e}")
            return {"error": str(e), "messages": [], "total": 0}
        finally:
            conn.close()

    async def get_group_chat_history(
        self,
        db_path: str,
        chatroom_name: str,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """
        Get paginated group chat history for a chatroom.

        Args:
            db_path: Path to the _android.db file.
            chatroom_name: The chatroom name/ID.
            page: Page number (1-based).
            page_size: Number of messages per page.

        Returns:
            Dictionary with messages, pagination info.
        """
        return await asyncio.to_thread(
            self._get_group_chat_history_sync,
            db_path, chatroom_name, page, page_size,
        )

    def _get_group_chat_history_sync(
        self,
        db_path: str,
        chatroom_name: str,
        page: int,
        page_size: int,
    ) -> Dict[str, Any]:
        """
        Synchronous group chat history retrieval.
        """
        if not os.path.exists(db_path):
            return {"error": f"Database not found: {db_path}", "messages": [], "total": 0}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # Count total messages
            count_cursor = conn.execute(
                """
                SELECT COUNT(*) as total
                FROM wechat_messages
                WHERE chatroom_name = ?
                """,
                (chatroom_name,),
            )
            total = count_cursor.fetchone()["total"]

            # Fetch page
            offset = (page - 1) * page_size
            cursor = conn.execute(
                """
                SELECT id, sender, receiver, content, timestamp,
                       media_url, media_type, msg_type, is_send,
                       chatroom_name, sender_nickname, talker
                FROM wechat_messages
                WHERE chatroom_name = ?
                ORDER BY timestamp ASC
                LIMIT ? OFFSET ?
                """,
                (chatroom_name, page_size, offset),
            )

            messages = []
            for row in cursor.fetchall():
                messages.append({
                    "id": row["id"],
                    "sender": row["sender"],
                    "receiver": row["receiver"],
                    "content": row["content"],
                    "timestamp": row["timestamp"],
                    "media_url": row["media_url"],
                    "media_type": row["media_type"],
                    "msg_type": row["msg_type"],
                    "is_send": row["is_send"],
                    "chatroom_name": row["chatroom_name"],
                    "sender_nickname": row["sender_nickname"],
                    "talker": row["talker"],
                })

            return {
                "messages": messages,
                "total": total,
                "page": page,
                "page_size": page_size,
                "total_pages": (total + page_size - 1) // page_size if page_size > 0 else 0,
            }

        except sqlite3.OperationalError as e:
            logger.warning(f"Error fetching group chat history: {e}")
            return {"error": str(e), "messages": [], "total": 0}
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Owner / Contacts
    # -------------------------------------------------------------------------

    async def get_owner_info(self, db_path: str) -> Dict[str, Any]:
        """
        Get WeChat owner information.

        Args:
            db_path: Path to the _android.db file.

        Returns:
            Owner info dictionary or error.
        """
        return await asyncio.to_thread(self._get_owner_info_sync, db_path)

    def _get_owner_info_sync(self, db_path: str) -> Dict[str, Any]:
        """Synchronous owner info retrieval."""
        if not os.path.exists(db_path):
            return {"error": f"Database not found: {db_path}"}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            owner = self._get_owner_from_conn(conn)
            if owner:
                return {"owner": owner}
            return {"owner": None, "message": "No owner info found in database"}
        finally:
            conn.close()

    async def get_contacts_list(
        self,
        db_path: str,
        include_chatrooms: bool = False,
    ) -> Dict[str, Any]:
        """
        Get WeChat contacts list.

        Args:
            db_path: Path to the _android.db file.
            include_chatrooms: Whether to include chatroom contacts.

        Returns:
            Dictionary with contacts list.
        """
        return await asyncio.to_thread(
            self._get_contacts_list_sync, db_path, include_chatrooms
        )

    def _get_contacts_list_sync(
        self, db_path: str, include_chatrooms: bool
    ) -> Dict[str, Any]:
        """Synchronous contacts list retrieval."""
        if not os.path.exists(db_path):
            return {"error": f"Database not found: {db_path}", "contacts": []}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            if include_chatrooms:
                cursor = conn.execute(
                    """
                    SELECT username, nickname, remark, avatar_path, type, chatroom_flag
                    FROM wechat_contacts
                    ORDER BY chatroom_flag DESC, username ASC
                    """
                )
            else:
                cursor = conn.execute(
                    """
                    SELECT username, nickname, remark, avatar_path, type, chatroom_flag
                    FROM wechat_contacts
                    WHERE chatroom_flag = 0
                    ORDER BY username ASC
                    """
                )

            contacts = []
            for row in cursor.fetchall():
                contacts.append({
                    "username": row["username"] or "",
                    "nickname": row["nickname"] or "",
                    "remark": row["remark"] or "",
                    "avatar_path": row["avatar_path"] or "",
                    "type": row["type"],
                    "chatroom_flag": row["chatroom_flag"],
                })

            return {
                "contacts": contacts,
                "total": len(contacts),
            }

        except sqlite3.OperationalError as e:
            logger.warning(f"Error fetching contacts: {e}")
            return {"error": str(e), "contacts": [], "total": 0}
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Chatrooms
    # -------------------------------------------------------------------------

    async def get_chatrooms_list(self, db_path: str) -> Dict[str, Any]:
        """
        Get WeChat chatrooms list.

        Args:
            db_path: Path to the _android.db file.

        Returns:
            Dictionary with chatrooms list.
        """
        return await asyncio.to_thread(self._get_chatrooms_list_sync, db_path)

    def _get_chatrooms_list_sync(self, db_path: str) -> Dict[str, Any]:
        """Synchronous chatrooms list retrieval."""
        if not os.path.exists(db_path):
            return {"error": f"Database not found: {db_path}", "chatrooms": []}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            cursor = conn.execute(
                """
                SELECT chatroom_name, owner, member_list, member_count, create_time
                FROM wechat_chatrooms
                ORDER BY member_count DESC
                """
            )

            chatrooms = []
            for row in cursor.fetchall():
                chatrooms.append({
                    "chatroom_name": row["chatroom_name"] or "",
                    "owner": row["owner"] or "",
                    "member_list": row["member_list"] or "",
                    "member_count": row["member_count"] or 0,
                    "create_time": row["create_time"],
                })

            return {
                "chatrooms": chatrooms,
                "total": len(chatrooms),
            }

        except sqlite3.OperationalError as e:
            logger.warning(f"Error fetching chatrooms: {e}")
            return {"error": str(e), "chatrooms": [], "total": 0}
        finally:
            conn.close()
