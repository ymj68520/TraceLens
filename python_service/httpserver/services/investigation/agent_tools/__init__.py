"""Agent tool substrate (Phase 3): read-only forensic tool surface.

Contracts:
    definitions.ForensicToolDefinition  TraceLens domain tool contract
    context.ForensicToolContext         trusted per-run execution context
    registry.ForensicToolRegistry       permission/scope authority (P3-2)
    pydantic_bridge.ForensicToolset     PydanticAI toolset adapter
    visibility.reconstruct_allowed_evidence_ids  auditable Evidence visibility

P3 tools are read-only; the registry refuses non-read registrations.
"""
