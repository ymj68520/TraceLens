"""Dataset resolution: which communication sources belong to this request.

A request is either a plain task id (its ``android.db``) or a case id (every
task of the case plus the WeChat/QQ imports attached to those tasks). Imports
are not linked to tasks yet, so the optional ``import_id`` list is explicit:
the caller names the imports it wants merged. Guessing would risk pulling in an
unrelated account.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..android_coverage import resolve_android_db
from .models import DatasetRef

_IMPORT_ID = re.compile(r"^[0-9a-f]{12}$")


class DatasetResolutionError(ValueError):
    """Raised when the requested scope cannot be resolved."""


def _import_root(kind: str) -> Path:
    from ...config import get_data_root

    return get_data_root() / ("wechat_imports" if kind == "wechat_import" else "qq_imports")


def _import_ref(kind: str, import_id: str) -> DatasetRef | None:
    if not _IMPORT_ID.fullmatch(import_id):
        raise DatasetResolutionError("导入标识无效")
    if kind == "wechat_import":
        from ..wechat_import_service import get_wechat_import_service

        try:
            path = get_wechat_import_service().ensure_graph_db(import_id)
        except (ValueError, OSError):
            path = ""
        label = "微信导入"
    else:
        from ..qq_import_service import get_qq_import_service

        try:
            path = get_qq_import_service().ensure_graph_db(import_id)
        except (ValueError, OSError):
            path = ""
        label = "QQ 导入"
    if not path or not Path(path).is_file():
        root = _import_root(kind) / import_id
        if root.is_symlink():
            raise DatasetResolutionError("导入目录不可用")
        return None
    return DatasetRef(kind=kind, id=import_id, path=path, label=f"{label} {import_id[:8]}")


def _task_ref(task: dict[str, Any]) -> DatasetRef | None:
    path = resolve_android_db(task)
    if path is None:
        return None
    name = Path(str(task.get("image_path") or task["id"])).name
    return DatasetRef(kind="task", id=str(task["id"]), path=str(path),
                      label=f"手机检材 {name}")


def resolve_datasets(task: dict[str, Any], *, wechat_imports=(), qq_imports=()):
    """Resolve every readable source for a task.

    Returns ``(refs, unavailable)``. ``unavailable`` carries human-readable
    reasons for sources the caller named but that could not be opened, so the
    graph payload can disclose them instead of quietly showing fewer datasets.
    """
    refs: list[DatasetRef] = []
    unavailable: list[dict[str, str]] = []

    task_ref = _task_ref(task)
    if task_ref is not None:
        refs.append(task_ref)

    for kind, ids in (("wechat_import", wechat_imports), ("qq_import", qq_imports)):
        for import_id in ids:
            ref = _import_ref(kind, import_id)
            if ref is None:
                unavailable.append({"kind": kind, "id": import_id,
                                    "reason": "not_found_or_unreadable"})
                continue
            refs.append(ref)

    # A task whose android.db exists but carries only file evidence (TSK
    # sources) is still a valid, if communication-empty, dataset. It stays in
    # the list so coverage can say "no communication tables".
    return refs, unavailable


__all__ = ["DatasetResolutionError", "resolve_datasets"]
