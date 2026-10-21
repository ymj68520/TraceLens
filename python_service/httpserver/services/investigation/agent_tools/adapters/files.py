"""File search tool (P3 §20) — reuses the paginated Files facade."""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from ....investigation_evidence import make_file_evidence_key
from ..errors import ToolErrorCode, ToolExecutionError
from ..registry import ToolExecutionOutcome
from .base import ToolCatalogConfig, bounded_page_size
from .services import ForensicToolServices


class SearchFilesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: Optional[str] = None
    path_prefix: Optional[str] = None
    file_type: Optional[str] = None
    extension: Optional[str] = None
    deleted_only: bool = False
    page_size: Optional[int] = None
    page_token: Optional[int] = None  # 1-based page number


class FileDigest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    evidence_key: str
    path: str
    name: str | None = None
    extension: str | None = None
    size: int | None = None
    md5: str | None = None
    is_deleted: bool = False
    has_llm_summary: bool = False
    modified_time: int | None = None


class SearchFilesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: tuple[FileDigest, ...] = ()
    result_count: int = 0
    total_count: int = 0
    truncated: bool = False
    continuation: str | None = None


def build_search_files_tool(
    services: ForensicToolServices, config: ToolCatalogConfig
):
    async def adapter(invocation) -> ToolExecutionOutcome:
        args: SearchFilesInput = invocation.args
        task_id = invocation.context.task_id
        page = int(args.page_token or 1)
        if page < 1:
            raise ToolExecutionError(
                ToolErrorCode.TOOL_INPUT_INVALID,
                "page_token must be >= 1",
            )
        result = await services.cpp_backend.get_task_files_paginated(
            task_id,
            query=args.query,
            path_prefix=args.path_prefix,
            file_type=args.file_type,
            extension=args.extension,
            deleted_only=args.deleted_only,
            include_llm=True,
            page=page,
            page_size=bounded_page_size(args.page_size, config),
        )
        files = list(result.get("files") or [])
        total = int(result.get("total_count") or 0)
        digests: list[FileDigest] = []
        for row in files:
            path = str(row.get("path") or row.get("name") or "")
            if not path:
                continue
            try:
                evidence_key = make_file_evidence_key(path)
            except Exception:  # noqa: BLE001 - never fail a page on one row
                continue
            digests.append(
                FileDigest(
                    evidence_key=evidence_key,
                    path=path,
                    name=row.get("name"),
                    extension=row.get("extension"),
                    size=row.get("size"),
                    md5=row.get("md5"),
                    is_deleted=bool(row.get("is_deleted")),
                    has_llm_summary=bool(row.get("llm_description")),
                    modified_time=row.get("modified_time"),
                )
            )
        total_pages = max(1, -(-total // max(1, len(files) or 1)))
        continuation = str(page + 1) if page * bounded_page_size(args.page_size, config) < total else None
        return ToolExecutionOutcome(
            summary=f"{len(digests)} files on page {page} (total {total})",
            result=SearchFilesOutput(
                items=tuple(digests),
                result_count=len(digests),
                total_count=total,
                truncated=continuation is not None,
                continuation=continuation,
            ),
            evidence_refs=tuple(item.evidence_key for item in digests),
            limitations=(f"result pages cover {total_pages}+ pages; refine with filters",),
        )

    from ..definitions import (
        EvidenceBehavior,
        ForensicToolDefinition,
        ToolAccess,
        ToolCategory,
        ToolCostClass,
        ToolPaginationKind,
        ToolScopeKind,
    )

    definition = ForensicToolDefinition(
        tool_id="search_files",
        version="1",
        title="Search files",
        description=(
            "Lists files of this task with type/extension/deleted filters. "
            "Each item carries its file: evidence key for get_evidence. "
            "Deterministic page ordering, bounded page size, page continuation."
        ),
        input_model=SearchFilesInput,
        output_model=SearchFilesOutput,
        category=ToolCategory.FILES,
        access=ToolAccess.READ,
        scope_kind=ToolScopeKind.FILE,
        evidence_behavior=EvidenceBehavior.EVIDENCE_PRODUCING,
        cost_class=ToolCostClass.CHEAP,
        pagination_kind=ToolPaginationKind.PAGE_TOKEN,
    )
    return definition, adapter
