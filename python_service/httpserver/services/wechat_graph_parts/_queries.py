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


class WeChatGraphQueriesMixin:
    """Auto-extracted method group; see module docstring."""

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
                       media_url, media_type, msg_type, is_send,
                       chatroom_name, sender_nickname, talker
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
            logger.warning(f"Error fetching chat history: {e}")
            return {"error": "database query failed", "messages": [], "total": 0}
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
            return {"error": "database query failed", "messages": [], "total": 0}
        finally:
            conn.close()

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
            return {"error": "database query failed", "contacts": [], "total": 0}
        finally:
            conn.close()

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
            return {"error": "database query failed", "chatrooms": [], "total": 0}
        finally:
            conn.close()

