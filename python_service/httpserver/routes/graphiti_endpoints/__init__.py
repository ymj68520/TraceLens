"""Graphiti routes split into per-domain endpoint modules.

The parent graphiti.py mounts each sub-router under /api/graphiti. The split
keeps domains discoverable without changing any URL or response shape.
"""

from . import _ingest, _jobs, _migrate, _query, _admin

__all__ = ["_ingest", "_jobs", "_migrate", "_query", "_admin"]
