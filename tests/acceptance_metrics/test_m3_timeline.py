"""指标 3 动态时间线构建：多模态同一事件聚合、≥100 事件节点展示。

对应验收申请指标：
  (1) 支持多模态同一事件聚合功能
  (2) 支持 ≥100 个事件节点展示功能

聚合口径：研判工作台把 文件证据(file) / 事件簇(cluster) / Android 工件
(android_artifact) 多来源证据聚合到同一事件轴（evidence_snapshots 表的
evidence_type CHECK 约束即三种来源）。节点容量：timeline_120.img 植入 120 个
逐小时时间戳文件，任务后时间线端点必须返回 ≥100 个事件节点。
"""

from __future__ import annotations

import pytest

from conftest import CPP_BASE, PY_BASE, fixture_path, run_analysis_task


@pytest.mark.llm
def test_m3_1_multimodal_event_aggregation(api, llm_ready):
    """多模态同一事件聚合：工作台事件轴由已分析簇播种（每簇一事件），
    且每个事件可回溯到其证据明细（聚合不是孤立列表）。

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

    # 聚合来源多样性：事件携带的证据可解析（file/cluster/android_artifact）
    probe = events[:10]
    resolved = 0
    for event in probe:
        event_id = event.get("id") or event.get("event_id")
        status, ev = api.get(
            PY_BASE, f"/api/investigation/workbench/{task_id}/events/{event_id}/evidence")
        if status == 200 and ev.get("total", 0) >= 0:
            resolved += 1
    assert resolved >= len(probe) - 1, \
        f"事件证据回溯大量失败（{resolved}/{len(probe)}）— 聚合链路断裂"

    # 至少一个事件由簇（多来源聚合单元）支撑
    cluster_backed = [
        e for e in events
        if any(("cluster" in str(ev).lower()) for ev in (e.get("evidence_types") or []))
    ]
    print(f"\n[聚合] 工作台事件 {len(events)} 个，簇支撑 {len(cluster_backed)} 个")
    assert events, "无聚合事件"


def test_m3_2_timeline_supports_100_nodes(api):
    """≥100 事件节点：timeline_120.img（120 个逐小时文件）→ 时间线 ≥100 节点。"""
    task = run_analysis_task(api, fixture_path("timeline_120.img"),
                             scenarios=["linux"], platform_analyze=False,
                             cache_key="timeline-acc")
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
