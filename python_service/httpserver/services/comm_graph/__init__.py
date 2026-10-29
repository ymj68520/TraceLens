"""Unified communication graph over every mobile data source of a case.

The three existing pipelines never meet: a task writes ``android.db``, a WeChat
import and a QQ import each write their own ``graph.db``. This package reads all
of them through one projection and answers "who communicated with whom" over the
union, without merging the source databases.

Design boundaries:

* Read-only. Nothing here writes to a source database.
* Identity merging is restricted to strong keys (normalized phone number, wxid,
  QQ uin). Names only produce candidate links; a same-name pair is never merged
  automatically.
* Every edge keeps the dataset it came from and a record reference, so an
  analyst can go back to the original row.
"""

from .models import Dataset, DatasetRef, GraphFilters, UnifiedGraph
from .service import CommGraphService, resolve_datasets

__all__ = [
    "CommGraphService",
    "Dataset",
    "DatasetRef",
    "GraphFilters",
    "UnifiedGraph",
    "resolve_datasets",
]
