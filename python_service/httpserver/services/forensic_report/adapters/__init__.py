"""Built-in adapters for structured forensic report snapshots."""

from .sqlite_task import SqliteTaskReportAdapter, build_default_adapters

__all__ = ["SqliteTaskReportAdapter", "build_default_adapters"]
