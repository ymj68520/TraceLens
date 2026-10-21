"""Read-only tool adapters (P3 §20).

Every adapter calls trusted internal facades (CppBackendService,
InvestigationService read methods, InvestigationReadService,
InvestigationEventService, SecondaryAnalysisExecutor). No HTTP self-calls,
no raw SQLite, no filesystem scans, no Graphiti.

Identity rules:
    task_id always comes from the trusted ForensicToolContext;
    evidence keys are parsed/validated before any facade call;
    paths returned to the model are forensic (image-relative) paths only —
    the adapters never expose server filesystem layout.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ....investigation_evidence import make_cluster_key


class ToolCatalogConfig(BaseModel):
    """Configurable pagination / bounds for the read-only catalog.

    Provisional defaults; P8 benchmark calibration may override them via
    explicit config, the values are not architecture constants.
    """

    model_config = ConfigDict(frozen=True)

    default_page_size: int = Field(default=30, ge=1, le=200)
    max_page_size: int = Field(default=100, ge=1, le=500)
    max_preview_chars: int = Field(default=64000, ge=200, le=2000000)
    max_temporal_window_seconds: int = Field(default=7 * 86400, ge=60)
    default_temporal_window_seconds: int = Field(default=600, ge=1)
    max_related_items: int = Field(default=20, ge=1, le=100)


def bounded_page_size(requested: int | None, config: ToolCatalogConfig) -> int:
    if requested is None:
        return config.default_page_size
    return max(1, min(int(requested), config.max_page_size))


def cluster_key_for_event(timestamp: Any, event_type: Any) -> str | None:
    """Derive the backend-owned cluster Evidence key for one raw event.

    The model can never construct cluster:v1 keys itself; tools hand them out
    in canonical form so get_evidence can hydrate them.
    """
    if timestamp is None or not event_type:
        return None
    try:
        minute = int(timestamp) // 60
    except (TypeError, ValueError):
        return None
    try:
        return make_cluster_key(minute, str(event_type))
    except Exception:  # noqa: BLE001 - never fail a read on key derivation
        return None
