"""
WeChat relationship graph routes — aggregator.

Single entry point used by main.py:
    app.include_router(wechat_graph.router, prefix="/api/wechat", tags=["WeChat Analysis"])

Endpoints split by domain under ``wechat_graph_endpoints/``:
  - _graph.py  graph, graph/timeline, graph/community, graph/person/{username}
  - _data.py   chat, chat/group, owner, contacts, graph/invalidate

Pydantic models live in ``wechat_graph_models.py``. Public surface unchanged.
"""

import logging
from fastapi import APIRouter

from .wechat_graph_endpoints import _graph, _data
from .wechat_graph_models import (  # noqa: F401
    GraphResponse,
    TimelineResponse,
    CommunityResponse,
    PersonEgoResponse,
    ChatMessage,
    ChatResponse,
    OwnerResponse,
    ContactItem,
    ContactsResponse,
    CacheInvalidateResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter()
router.include_router(_graph.router)
router.include_router(_data.router)
