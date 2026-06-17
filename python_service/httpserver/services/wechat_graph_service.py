"""
WeChat Graph Service - Social network analysis for WeChat forensic data.

This service reads from _android.db, builds a NetworkX directed graph,
computes social network analytics (PageRank, betweenness centrality,
community detection), and provides caching for performance.

NOTE: The method implementations are split into mixins under the
``wechat_graph_parts`` subpackage for maintainability:
  - WeChatGraphCoreMixin    : cache + get_full_graph + graph construction
  - WeChatGraphAnalysisMixin: metrics + community detection + serialization
  - WeChatGraphTimelineMixin: activity timeline
  - WeChatGraphQueriesMixin : chat-history / contacts / chatrooms queries
The public surface (class name, all method signatures) is unchanged.
"""

import logging

from .wechat_graph_parts import (
    WeChatGraphCoreMixin,
    WeChatGraphAnalysisMixin,
    WeChatGraphTimelineMixin,
    WeChatGraphQueriesMixin,
)

logger = logging.getLogger(__name__)


class WeChatGraphService(
    WeChatGraphCoreMixin,
    WeChatGraphAnalysisMixin,
    WeChatGraphTimelineMixin,
    WeChatGraphQueriesMixin,
):
    """Service for WeChat social-network forensic analysis (split into mixins)."""
