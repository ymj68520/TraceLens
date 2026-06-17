"""WeChatGraphService implementation, split across mixins for maintainability.

The public WeChatGraphService class lives in ../wechat_graph_service.py and
aggregates these mixins via multiple inheritance.
"""

from ._core import WeChatGraphCoreMixin
from ._analysis import WeChatGraphAnalysisMixin
from ._timeline import WeChatGraphTimelineMixin
from ._queries import WeChatGraphQueriesMixin

__all__ = [
    "WeChatGraphCoreMixin",
    "WeChatGraphAnalysisMixin",
    "WeChatGraphTimelineMixin",
    "WeChatGraphQueriesMixin",
]
