"""Routes package for the HTTP server."""

from importlib import import_module

__all__ = [
    "health",
    "graphiti",
    "llm",
    "database",
    "office",
    "case_analysis",
    "system",
    "system_logs",
    "markitdown",
    "wechat_graph",
    "forensic_reports",
]

_ROUTE_MODULES = frozenset(
    {
        *__all__,
        "associations",
        "oss_analysis",
        "multi_analysis",
        "dll",
    }
)


def __getattr__(name: str):
    if name not in _ROUTE_MODULES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return import_module(f"{__name__}.{name}")
