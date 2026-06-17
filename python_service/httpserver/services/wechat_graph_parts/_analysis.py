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


class WeChatGraphAnalysisMixin:
    """Auto-extracted method group; see module docstring."""

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

