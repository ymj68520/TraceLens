"""GraphitiService implementation, split across mixins for maintainability.

The public GraphitiService class lives in ../graphiti_service.py and aggregates
these mixins via multiple inheritance:

    GraphitiService(GraphitiCoreMixin, GraphitiJobsMixin, GraphitiQueryMixin,
                    GraphitiStatusMixin, GraphitiIngestMixin)

Each mixin owns a cohesive group of methods and shares the instance state
initialised by GraphitiService.__init__.
"""

from ._core import GraphitiCoreMixin
from ._jobs import GraphitiJobsMixin
from ._query import GraphitiQueryMixin
from ._status import GraphitiStatusMixin
from ._ingest import GraphitiIngestMixin

__all__ = [
    "GraphitiCoreMixin",
    "GraphitiJobsMixin",
    "GraphitiQueryMixin",
    "GraphitiStatusMixin",
    "GraphitiIngestMixin",
]
