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


class WeChatGraphTimelineMixin:
    """Auto-extracted method group; see module docstring."""

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
            return {"error": "database query failed", "intervals": []}
        finally:
            conn.close()

