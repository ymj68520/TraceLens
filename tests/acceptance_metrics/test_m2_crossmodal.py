"""指标 2 跨模态证据挖掘：文本/图像/视频信息提取、事件转化、重复证据去重。

对应验收申请指标：
  (1) 能提取文本、图像、视频文字信息，支持事件转化功能
  (2) 提供重复证据去重功能

文本提取走 MarkItDown 确定性转换（无 LLM 依赖）；图像/视频走 /api/llm/analyze
的自动路由（图像→视觉模型、视频→分段抽帧视觉分析），依赖已配置的 LLM。
事件转化为任务链路内的确定性功能（文件系统/系统事件提取）。
"""

from __future__ import annotations

from pathlib import Path

from conftest import CPP_BASE, PY_BASE, FIXTURE_DIR, db_scalar, fixture_path, \
    llm_analyze_content, overview, run_analysis_task


def _analysis_text(body: dict) -> str:
    analysis = body.get("analysis") or {}
    return (analysis.get("description") or analysis.get("summary")
            or body.get("description") or body.get("summary") or "")


def test_m2_1a_text_extraction_markitdown(api):
    """文本信息提取：html 经 MarkItDown 转出含关键内容的 Markdown。"""
    src = fixture_path("_md_in/_text_sample.html")
    in_root = FIXTURE_DIR / "_md_in"
    out_root = FIXTURE_DIR / "_md_out"
    out_root.mkdir(exist_ok=True)
    status, body = api.post(PY_BASE, "/api/markitdown/convert-one", json={
        "workspace_root": str(FIXTURE_DIR),
        "input_root": str(in_root),
        "input_file": str(src),
        "output_root": str(out_root),
    })
    assert status == 200, f"convert-one 失败({status}): {body}"
    output = body.get("output_path")
    assert output and Path(output).exists(), f"转换产物缺失: {body}"
    text = Path(output).read_text(encoding="utf-8", errors="replace")
    assert "设备采购合同" in text and "386,000" in text, "文本转换丢失关键内容"


def test_m2_1b_image_text_extraction(api, llm_ready):
    """图像文字信息提取：视觉模型读出夹具图上绘制的编号文字。"""
    png = fixture_path("sample.png")
    body = llm_analyze_content(api, str(png), llm_ready=llm_ready,
                               prompt="逐字读出图像中的全部可见文字")
    desc = _analysis_text(body)
    assert desc.strip(), "视觉模型返回空描述"
    assert "ACCT-2026-777" in desc, \
        f"图像中的编号文字未被提取。模型输出: {desc[:200]}"


def test_m2_1c_video_text_extraction(api, llm_ready):
    """视频信息提取：分段抽帧视觉分析产出内容描述。"""
    mp4 = fixture_path("sample.mp4")
    body = llm_analyze_content(api, str(mp4), llm_ready=llm_ready,
                               prompt="概述视频内容")
    desc = _analysis_text(body)
    assert desc.strip(), "视频分析返回空描述"
    method = str(body.get("extraction_method", ""))
    print(f"\n[视频] method={method} tokens={body.get('tokens_used')}")


def test_m2_1d_event_conversion(api):
    """事件转化：任务链路把文件/工件证据转为结构化事件（events 库+时间线端点）。"""
    task = run_analysis_task(api, fixture_path("raw_basic.img"),
                             scenarios=["linux"], platform_analyze=False,
                             cache_key="raw-acc")
    stats = overview(api, task["id"])
    events = stats["events_database_stats"]
    assert events["total_events"] > 0, "events 库为空：证据未转化为事件"
    status, timeline = api.get(
        CPP_BASE, f"/api/forensics/timeline/full?task_id={task['id']}")
    assert status == 200
    rows = (timeline.get("timeline") if isinstance(timeline, dict) else None) \
        or (timeline if isinstance(timeline, list) else [])
    assert rows, "时间线端点无事件"
    sample = rows[0]
    assert sample.get("timestamp") and sample.get("event_type"), \
        f"事件缺少结构化字段（timestamp/event_type）: {sorted(sample.keys())[:10]}"


def test_m2_2_duplicate_evidence_dedup(api):
    """重复证据去重：/api/forensics/files/duplicates 按 MD5 聚出植入的重复对。

    已知缺口（2026-10-14 核查）：摄入/分类链路不计算内容 MD5（files.db md5 列
    全空），本用例当前失败属产品缺陷信号——需在提取或分类阶段补内容哈希。
    """
    task = run_analysis_task(api, fixture_path("raw_basic.img"),
                             scenarios=["linux"], platform_analyze=False,
                             cache_key="raw-acc")
    status, body = api.get(
        CPP_BASE, f"/api/forensics/files/duplicates?task_id={task['id']}")
    assert status == 200, f"duplicates 端点失败({status})"
    assert isinstance(body.get("duplicates"), list), "响应缺 duplicates 数组"
    dups = body["duplicates"]
    hit = [d for d in dups
           if "dup_a.csv" in str(d.get("file_paths", ""))
           and "dup_b.csv" in str(d.get("file_paths", ""))]
    assert hit, (
        "植入的重复文件对未被聚出。当前 duplicates="
        f"{[(d.get('duplicate_count'), str(d.get('file_paths'))[:80]) for d in dups[:5]]}。"
        "根因：files.db 的 md5 列未在摄入链路填充。")
    assert hit[0]["duplicate_count"] >= 2
    files_db = task_db(task["id"], "files")
    assert db_scalar(files_db, "SELECT COUNT(*) FROM files WHERE md5 = ?",
                     (hit[0]["md5"],)) >= 2
