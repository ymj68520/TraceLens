"""指标 3 动态时间线构建：多模态同一事件聚合、≥100 事件节点展示。

对应验收申请指标：
  (1) 支持多模态同一事件聚合功能
  (2) 支持 ≥100 个事件节点展示功能

聚合口径：研判工作台按时间窗把同一分钟内的多模态文件证据挂到同一个
事件上。raw_llm.img 里 内部沟通记录.txt 与 转账凭证.png 共享 2026-03-02
10:14 这一分钟，播种后必须存在一个事件同时挂着文本文件和图像文件。
节点容量：timeline_120.img 植入 120 个逐小时时间戳文件，任务后时间线端点
必须返回 ≥100 个事件节点。
"""

from __future__ import annotations

import pytest

from conftest import CPP_BASE, PY_BASE, fixture_path, run_analysis_task


@pytest.mark.llm
_TEXT_EXT = (".txt", ".html", ".csv", ".md")
_IMAGE_EXT = (".png", ".jpg", ".jpeg")


def _evidence_kinds(items: list) -> set[str]:
    """Classify one event's linked evidence into text / image by file suffix."""
    kinds: set[str] = set()
    for item in items:
        key = str(item.get("evidence_key") or item.get("title") or "").lower()
        if key.endswith(_TEXT_EXT):
            kinds.add("text")
        elif key.endswith(_IMAGE_EXT):
            kinds.add("image")
    return kinds


def test_m3_1_multimodal_event_aggregation(api, llm_ready):
    """多模态同一事件聚合：同一分钟内的文本与图像必须挂在同一个事件上。

    raw_llm.img 把 内部沟通记录.txt 与 转账凭证.png 都落在 2026-03-02 10:14。
    簇播种按时间窗把两者链到同一事件；只证明事件轴非空不再算通过。
    播入来源 = 带簇分析的任务（cluster_seed 模式），故本用例依赖 LLM。
    """
    if not llm_ready:
        pytest.skip("LLM 未配置：工作台事件轴播种自已分析的簇，需要 llm_analyze 任务")
    task = run_analysis_task(api, fixture_path("raw_llm.img"),
                             scenarios=["linux"], llm_analyze=True, llm_event_analyze=True,
                             platform_analyze=False, cache_key="raw-llm-acc")
    task_id = task["id"]

    status, overview_body = api.post(
        PY_BASE, f"/api/investigation/workbench/{task_id}/bootstrap",
        json={"mode": "cluster_seed", "generate_llm_summaries": False})
    assert status in (200, 202), f"工作台 bootstrap 失败({status})"

    status, body = api.get(PY_BASE, f"/api/investigation/workbench/{task_id}/events")
    assert status == 200, f"工作台事件轴拉取失败({status})"
    events = body.get("events", [])
    assert body.get("total", len(events)) >= 1, "工作台事件轴为空"

    aggregated = []
    for event in events:
        event_id = event.get("id") or event.get("event_id")
        status, ev = api.get(
            PY_BASE, f"/api/investigation/workbench/{task_id}/events/{event_id}/evidence")
        assert status == 200, f"事件 {event_id} 证据回溯失败({status})"
        items = ev.get("evidence") or []
        kinds = _evidence_kinds(items)
        if {"text", "image"} <= kinds:
            aggregated.append((event_id, [i.get("evidence_key") for i in items]))
    print(f"\n[聚合] 工作台事件 {len(events)} 个，同时含文本与图像的 {len(aggregated)} 个")
    assert aggregated, (
        "没有任何一个事件同时挂着文本文件和图像文件。"
        "夹具要求 内部沟通记录.txt 与 转账凭证.png 落在同一分钟并被簇播种链到同一事件。")


def test_m3_2_timeline_supports_100_nodes(api):
    """≥100 事件节点：timeline_120.img（120 个逐小时文件）→ 时间线 ≥100 节点。"""
    task = run_analysis_task(api, fixture_path("timeline_120.img"),
                             scenarios=["linux"], platform_analyze=False,
                             filtering_only=True, cache_key="timeline-acc")
    task_id = task["id"]
    from conftest import overview
    total = overview(api, task_id)["events_database_stats"]["total_events"]
    assert total >= 100, f"事件库仅 {total} 条 < 100"

    status, timeline = api.get(CPP_BASE, f"/api/forensics/timeline/full?task_id={task_id}")
    assert status == 200
    rows = (timeline.get("timeline") if isinstance(timeline, dict) else None) \
        or (timeline if isinstance(timeline, list) else [])
    assert len(rows) >= 100, f"时间线端点仅返回 {len(rows)} 个节点 < 100"
    stamps = sorted(r["timestamp"] for r in rows if r.get("timestamp"))
    assert stamps, "时间线节点缺时间戳"
    print(f"\n[节点数] events 库 {total}，端点返回 {len(rows)}")
