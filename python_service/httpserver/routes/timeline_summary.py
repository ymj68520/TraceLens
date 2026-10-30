"""Additive read surfaces mounted by the existing association/IM routers."""
from __future__ import annotations

import asyncio
import logging
import json
import re
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import ValidationError

from ..config import get_data_root
from ..services.timeline_sources import TimelineSource, SourceChanged, SourceUnavailable
from ..services.timeline_summary import RecordSelection, SummaryFilters, summarize

logger = logging.getLogger(__name__)
task_router = APIRouter()
wechat_router = APIRouter()
qq_router = APIRouter()
_SELECTORS = set(RecordSelection.model_fields) - {"direction"}


async def task_source(task_id: str, kind: str):
    if not task_id or len(task_id) > 256 or kind not in ("events", "wechat"):
        raise ValueError("任务或来源类型无效")
    imported = re.fullmatch(r"(wx|qq)_([0-9a-f]{12})", task_id)
    if kind == "wechat" and imported:
        return import_source("wechat" if imported[1] == "wx" else "qq", imported[2])
    from ..services import get_service_manager
    task = await get_service_manager().cpp_backend.get_task(task_id)
    if not task or task.get("id") != task_id:
        raise SourceUnavailable("任务不存在")
    if kind == "events":
        value = task.get("output_events_db")
        path = Path(value) if value else None
    else:
        from ..services.android_coverage import resolve_android_db
        path = await asyncio.to_thread(resolve_android_db, task)
    if path is None:
        raise SourceUnavailable("该任务没有对应来源数据库")
    return TimelineSource(path, "events" if kind == "events" else "wechat_task", task_id)


def import_source(platform: str, import_id: str):
    if not re.fullmatch(r"[0-9a-f]{12}", import_id):
        raise ValueError("导入标识无效")
    root = get_data_root() / f"{platform}_imports" / import_id
    if root.is_symlink():
        raise SourceUnavailable("导入目录不可用")
    if platform == "qq":
        # 老版QQ（pre-NTQQ）导入没有 nt_msg.db：时间规律直接读归一化
        # graph.db 的 wechat_messages 投影（与微信任务库同形状）。
        meta_path = root / "meta.json"
        try:
            legacy = json.loads(meta_path.read_text(encoding="utf-8")).get("format") == "legacy_qq4"
        except (OSError, ValueError):
            legacy = False
        if legacy:
            return TimelineSource(root / "graph.db", "qq_legacy", import_id)
        return TimelineSource(root / "nt_msg.db", "qq_import", import_id)
    return TimelineSource(root / "EnMicroMsg.db", f"{platform}_import", import_id)


async def read_summary(request: Request, *, platform=None, import_id=None, records=False):
    try:
        params = dict(request.query_params)
        allowed = set(SummaryFilters.model_fields)
        if not platform:
            allowed |= {"task_id", "source"}
        if records:
            allowed |= _SELECTORS | {"source_version", "summary_id", "record_direction"}
        if set(params) - allowed or len(params) != len(request.query_params.multi_items()):
            raise ValueError("存在未知或重复的筛选参数")
        filters = SummaryFilters.model_validate({k: v for k, v in params.items() if k in SummaryFilters.model_fields})
        source = (import_source(platform, import_id) if platform else
                  await task_source(params.get("task_id", ""), params.get("source", "events")))
        options = {}
        if records:
            for key in ("source_version", "summary_id"):
                if not re.fullmatch(r"[0-9a-f]{64}", params.get(key, "")):
                    raise ValueError("来源回查必须携带原统计的来源版本和统计标识")
            selection = {k: v for k, v in params.items() if k in _SELECTORS}
            if "record_direction" in params:
                selection["direction"] = params["record_direction"]
            options = {"selection": RecordSelection.model_validate(selection),
                       "expected_version": params["source_version"], "expected_summary": params["summary_id"]}
        result = await asyncio.to_thread(summarize, source, filters, **options)
        return {"success": True, **result}
    except SourceChanged as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (SourceUnavailable, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="对应来源不可用或未完成解析") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail="筛选条件无效：请检查时区、日期范围及分页参数") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (sqlite3.Error, OSError) as exc:
        logger.warning("Timeline summary source read failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="来源暂不可读取，请稍后重试") from exc


@task_router.get("/timeline-summary")
async def task_summary(request: Request):
    return await read_summary(request)


@task_router.get("/timeline-summary/records")
async def task_summary_records(request: Request):
    return await read_summary(request, records=True)


@wechat_router.get("/forensics/imports/{import_id}/timeline-summary")
async def wechat_summary(import_id: str, request: Request):
    return await read_summary(request, platform="wechat", import_id=import_id)


@wechat_router.get("/forensics/imports/{import_id}/timeline-summary/records")
async def wechat_summary_records(import_id: str, request: Request):
    return await read_summary(request, platform="wechat", import_id=import_id, records=True)


@qq_router.get("/forensics/imports/{import_id}/timeline-summary")
async def qq_summary(import_id: str, request: Request):
    return await read_summary(request, platform="qq", import_id=import_id)


@qq_router.get("/forensics/imports/{import_id}/timeline-summary/records")
async def qq_summary_records(import_id: str, request: Request):
    return await read_summary(request, platform="qq", import_id=import_id, records=True)
