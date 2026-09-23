"""Read-only tool catalog assembly (P3 §20)."""

from typing import Any, Callable

from ..registry import ForensicToolRegistry
from .base import ToolCatalogConfig
from .services import ForensicToolServices
from . import evidence, files, investigation_reads, task_context, timeline

ToolBuildFunc = Callable[[ForensicToolServices, ToolCatalogConfig], tuple]


def read_only_catalog_builders() -> list[ToolBuildFunc]:
    return [
        task_context.build_task_context_tool,
        evidence.build_search_evidence_tool,
        evidence.build_get_evidence_tool,
        evidence.build_find_related_evidence_tool,
        files.build_search_files_tool,
        timeline.build_search_timeline_tool,
        timeline.build_find_temporal_neighbors_tool,
        investigation_reads.build_get_existing_analyses_tool,
        investigation_reads.build_get_existing_claims_tool,
    ]


def build_read_only_registry(
    services: ForensicToolServices,
    *,
    config: ToolCatalogConfig | None = None,
    observation_sink: Any = None,
    evidence_ref_validator=None,
    builders: list[ToolBuildFunc] | None = None,
) -> ForensicToolRegistry:
    """Assemble the P3 read-only registry over trusted service facades."""
    config = config or ToolCatalogConfig()
    registry = ForensicToolRegistry(
        observation_sink=observation_sink,
        evidence_ref_validator=evidence_ref_validator,
    )
    for builder in builders or read_only_catalog_builders():
        definition, adapter = builder(services, config)
        registry.register(definition, adapter)
    return registry


__all__ = ["build_read_only_registry", "read_only_catalog_builders"]
