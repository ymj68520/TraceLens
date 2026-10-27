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
CACHE_TTL = 1800


# ---------------------------------------------------------------------------
# Human-readable helpers (node/edge labels readable by investigators)
# ---------------------------------------------------------------------------

_SYSTEM_ACCOUNT_LABELS = {
    "weixin": "微信团队", "filehelper": "文件传输助手", "newsapp": "腾讯新闻",
    "fmessage": "朋友推荐消息", "tmessage": "腾讯消息", "qmessage": "QQ消息",
    "qqmail": "QQ邮箱提醒", "floatbottle": "漂流瓶", "shakeapp": "摇一摇",
    "lbsapp": "附近的人", "medianote": "语音记事本", "qqsync": "通讯录同步助手",
    "masssendapp": "群发助手", "feedsapp": "朋友圈", "weibo": "微博",
    "officialaccounts": "订阅号", "notifymessage": "服务通知", "voipapp": "视频通话",
    "voiceinputapp": "语音输入", "voicevoipapp": "语音通话", "linkedinplugin": "领英",
    "facebookapp": "Facebook", "qqfriend": "查看QQ好友", "downloaderapp": "微信游戏下载",
    "appbrandcustomerservicemsg": "小程序客服消息", "opencustomerservicemsg": "开放客服消息",
    "brandsessionholder": "品牌会话", "schedule_message": "日程消息", "exmessage": "外部消息",
}


def _node_type(node_id, is_owner=False, chatroom_ids=()):
    """Classify a node: 本人 / 联系人 / 公众号 / 群聊 / 系统/功能账号."""
    if is_owner:
        return "本人"
    if not isinstance(node_id, str):
        return "联系人"
    if node_id in chatroom_ids or node_id.endswith("@chatroom"):
        return "群聊"
    if node_id.startswith("gh_"):
        return "公众号"
    if node_id in _SYSTEM_ACCOUNT_LABELS or node_id.endswith(
            ("@fakeuser", "@weclaw", "@stranger")):
        return "系统/功能账号"
    return "联系人"


def _chatroom_label(name):
    return ("QQ群 " if isinstance(name, str) and name.isdigit() else "微信群 ") \
        + str(name).replace("@chatroom", "")


def _human_label(node_id, contact_map, chatrooms):
    info = contact_map.get(node_id) or {}
    label = info.get("remark") or info.get("nickname")
    if label:
        return label
    if node_id in _SYSTEM_ACCOUNT_LABELS:
        return _SYSTEM_ACCOUNT_LABELS[node_id]
    if node_id in chatrooms:
        return _chatroom_label(node_id)
    return node_id


def _ensure_node(G, node_id, contact_map, chatroom_ids, chatrooms):
    if not node_id or G.has_node(node_id):
        return
    G.add_node(
        node_id,
        label=_human_label(node_id, contact_map, chatrooms),
        is_owner=False,
        node_type=_node_type(node_id, False, chatroom_ids),
        message_count=0,
    )


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
            tables = {
                row[0] for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            if "wechat_messages" not in tables:
                return {
                    "error": "Invalid WeChat database: wechat_messages table is missing",
                    "nodes": [], "edges": [], "communities": [],
                    "metadata": {"task_id": task_id, "db_path": db_path},
                }
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

        # 2. Group chat rooms (hub nodes + readable Chinese labels)
        chatrooms = self._load_chatrooms(conn)
        chatroom_ids = set(chatrooms)

        # 3. Add owner as a node
        if owner_username:
            G.add_node(
                owner_username,
                label=owner.get("nickname", owner_username),
                is_owner=True,
                node_type="本人",
                message_count=0,
            )

        # 4. Load contacts and add as nodes
        contacts = self._load_contacts(conn)
        contact_map = {}  # username -> {nickname, remark, ...}
        for c in contacts:
            username = c["username"]
            contact_map[username] = {
                "nickname": c.get("nickname", ""),
                "remark": c.get("remark", ""),
            }
            _ensure_node(G, username, contact_map, chatroom_ids, chatrooms)

        # 5. Group hub nodes so every group is visible and labelled
        group_msg_counts = {}
        try:
            for name, cnt in conn.execute(
                "SELECT chatroom_name, COUNT(*) FROM wechat_messages "
                "WHERE chatroom_name IS NOT NULL AND chatroom_name != '' "
                "GROUP BY chatroom_name"
            ):
                group_msg_counts[name] = cnt
        except sqlite3.OperationalError:
            pass
        for name, info in chatrooms.items():
            if G.has_node(name):
                G.nodes[name]["node_type"] = "群聊"
                G.nodes[name]["label"] = _chatroom_label(name)
                G.nodes[name]["member_count"] = info.get("member_count") or 0
                continue
            G.add_node(
                name,
                label=_chatroom_label(name),
                is_owner=False,
                node_type="群聊",
                member_count=info.get("member_count") or 0,
                message_count=group_msg_counts.get(name, 0),
            )

        # 6. Process private messages -> directed edges
        self._add_private_message_edges(G, conn, owner_username, contact_map, chatrooms)

        # 7. Process group messages -> co-activity + speaker->hub edges
        self._add_group_coactivity_edges(G, conn, owner_username, contact_map, chatrooms)

        return G

    def _load_chatrooms(self, conn: sqlite3.Connection) -> Dict[str, Dict[str, Any]]:
        """Load group chat rooms for hub nodes and Chinese labels."""
        out: Dict[str, Dict[str, Any]] = {}
        try:
            cur = conn.execute(
                "SELECT chatroom_name, owner, member_list, member_count FROM wechat_chatrooms"
            )
            for name, owner, member_list, member_count in cur.fetchall():
                if not name:
                    continue
                out[name] = {
                    "owner": owner or "",
                    "member_list": member_list or "",
                    "member_count": member_count or 0,
                }
        except sqlite3.OperationalError as e:
            logger.warning(f"wechat_chatrooms table not found or error: {e}")
        return out

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
        chatrooms: Dict,
    ) -> None:
        """
        Aggregate private (non-group) messages into directed weighted edges.

        For each sender->receiver pair outside of chatrooms, creates/updates an edge
        with weight (message count), total_chars, first_time, last_time,
        sent_count, received_count.
        """
        chatroom_ids = set(chatrooms)
        previews: Dict[tuple, str] = {}
        try:
            # last non-empty message per pair, oldest-first so later rows win
            for s_, r_, c_ in conn.execute(
                """
                SELECT sender, receiver, content FROM wechat_messages
                WHERE (chatroom_name IS NULL OR chatroom_name = '')
                  AND content IS NOT NULL AND content != ''
                ORDER BY timestamp ASC
                """
            ):
                previews[(s_, r_)] = c_
        except sqlite3.OperationalError:
            pass
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

                _ensure_node(G, sender, contact_map, chatroom_ids, chatrooms)
                _ensure_node(G, receiver, contact_map, chatroom_ids, chatrooms)

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
                        edge_label="私聊",
                        preview=(previews.get((sender, receiver), "") or "")[:120],
                    )

        except sqlite3.OperationalError as e:
            logger.warning(f"Error reading wechat_messages for private edges: {e}")

    def _add_group_coactivity_edges(
        self,
        G,
        conn: sqlite3.Connection,
        owner_username: str,
        contact_map: Dict,
        chatrooms: Dict,
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
            chatroom_names = [row["chatroom_name"] for row in cursor.fetchall()]
            chatroom_ids = set(chatrooms)

            for chatroom_name in chatroom_names:
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

                hub = chatroom_name
                hub_label = _chatroom_label(hub)
                per_member: Dict[str, int] = {}
                for m_ in messages:
                    s_ = m_["sender"]
                    if s_ and s_ != hub:
                        per_member[s_] = per_member.get(s_, 0) + 1

                # Sliding window: for each message, find other users active
                # within the 1-hour window
                seen_pairs = set()
                for i, msg_i in enumerate(messages):
                    sender_i = msg_i["sender"]
                    ts_i = msg_i["timestamp"]
                    if not sender_i or sender_i == hub:
                        continue

                    for j in range(i + 1, len(messages)):
                        msg_j = messages[j]
                        ts_j = msg_j["timestamp"]

                        # Since messages are sorted, break if beyond window
                        if ts_j - ts_i > ONE_HOUR_MS:
                            break

                        sender_j = msg_j["sender"]
                        if not sender_j or sender_j == hub:
                            continue
                        if sender_i == sender_j:
                            continue

                        # Create a canonical pair key
                        pair = (min(sender_i, sender_j), max(sender_i, sender_j))
                        if pair in seen_pairs:
                            continue
                        seen_pairs.add(pair)

                        u, v = pair
                        _ensure_node(G, u, contact_map, chatroom_ids, chatrooms)
                        _ensure_node(G, v, contact_map, chatroom_ids, chatrooms)

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
                                    edge_label="同群互动",
                                    chatroom=chatroom_name,
                                    chatroom_label=hub_label,
                                    total_chars=0,
                                    first_time=ts_i,
                                    last_time=ts_j,
                                    sent_count=0,
                                    received_count=0,
                                )

                # Speaker -> group hub edges so every group is a readable hub
                for sender, cnt in per_member.items():
                    _ensure_node(G, sender, contact_map, chatroom_ids, chatrooms)
                    if G.has_edge(sender, hub):
                        ed = G[sender][hub]
                        ed["weight"] = ed.get("weight", 0) + cnt
                    else:
                        G.add_edge(
                            sender,
                            hub,
                            weight=cnt,
                            edge_type="group",
                            edge_label="群聊发言",
                            chatroom=hub,
                            chatroom_label=hub_label,
                            total_chars=0,
                            first_time=None,
                            last_time=None,
                            sent_count=0,
                            received_count=0,
                        )

        except sqlite3.OperationalError as e:
            logger.warning(f"Error reading wechat_messages for group edges: {e}")

