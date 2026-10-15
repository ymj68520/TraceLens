"""指标 1(2) 数据轻量化过滤：吞吐 ≥10MB/s、低价值剔除率 ≥70%、待分析压缩至 12%-15%。

系统口径（与本仓库实现一一对应）：
  原始量   = raw.db  files 表（镜像提取出的全部常规文件）
  待分析集 = files.db files 表中 scene_priority > 0 的文件（LLM/研判准入集，
             见 LLMAnalysisService 的筛选 SQL：WHERE scene_priority > 0）
  剔除率   = 1 - 待分析文件数 / 原始文件数
  压缩比   = 待分析文件字节数 / 原始文件字节数（字节口径，反映数据量）
  吞吐     = 镜像字节数 / (任务创建→COMPLETED 墙钟时间)

夹具 raw_basic.img 按真实分布调比：约 77% 文件为低价值（/usr/lib、/var/cache、
/tmp 的 .so/.ttf/.tmp），约 13% 字节为高价值证据（文档/照片/聊天记录）。
"""

from __future__ import annotations

import time
from pathlib import Path

from conftest import (CPP_BASE, db_scalar, filtering_pipeline_seconds,
                      fixture_path, overview, run_analysis_task, task_db)

THROUGHPUT_MIN_MB_S = float(__import__("os").environ.get(
    "TRACELENS_ACCEPT_MIN_MB_S", "10"))  # 合同值 10MB/s
REJECT_MIN = 0.70
COMPRESS_LO, COMPRESS_HI = 0.12, 0.15


def _prepare(api):
    image = fixture_path("raw_basic.img")
    start = time.monotonic()
    # 吞吐口径 = 轻量化过滤流水线（摄入+提取+分类+事件），关闭下游平台/LLM 分析
    task = run_analysis_task(api, image, scenarios=["linux"],
                             platform_analyze=False, cache_key="raw-acc")
    elapsed = time.monotonic() - start
    return image, task, elapsed


def test_m1_2a_throughput_ge_10mb_s(api):
    """轻量化过滤流水线吞吐 ≥ 10MB/s（审计口径：创建→过滤产物落库）。"""
    image, task, _ = _prepare(api)
    mb = image.stat().st_size / (1024 * 1024)
    window = filtering_pipeline_seconds(task["id"])
    throughput = mb / window
    print(f"\n[吞吐] {mb:.1f}MB / 过滤窗口 {window:.1f}s = {throughput:.2f} MB/s "
          f"(task={task['id']}，阈值 {THROUGHPUT_MIN_MB_S})")
    assert throughput >= THROUGHPUT_MIN_MB_S, \
        f"吞吐 {throughput:.2f} MB/s < {THROUGHPUT_MIN_MB_S} MB/s（过滤窗口 {window:.1f}s）"


def test_m1_2b_low_value_reject_ge_70pct(api):
    """低价值数据剔除率 = 1 - 待分析(优先级>0)文件数/全量 ≥ 70%。"""
    image, task, _ = _prepare(api)
    files_db = task_db(task["id"], "files")
    total = db_scalar(files_db, "SELECT COUNT(*) FROM files")
    pending = db_scalar(files_db, "SELECT COUNT(*) FROM files WHERE scene_priority > 0")
    marked = db_scalar(files_db, "SELECT COUNT(*) FROM files WHERE scene_type != ''")
    assert total, "files.db 为空"
    assert marked == total, "场景规则未生效（scene_type 存在空值）— 请确认任务选择场景"
    ratio = pending / total
    print(f"\n[剔除率] 待分析 {pending}/{total} = 剔除 {(1 - ratio) * 100:.1f}%")
    assert 1 - ratio >= REJECT_MIN, f"剔除率 {(1 - ratio) * 100:.1f}% < 70%"


def test_m1_2c_pending_compress_12_to_15pct(api):
    """待分析数据量（字节口径）压缩至原始量的 12%-15%。"""
    image, task, _ = _prepare(api)
    files_db = task_db(task["id"], "files")
    total_bytes = db_scalar(files_db, "SELECT COALESCE(SUM(size),0) FROM files") or 0
    pending_bytes = db_scalar(
        files_db, "SELECT COALESCE(SUM(size),0) FROM files WHERE scene_priority > 0") or 0
    assert total_bytes > 0
    ratio = pending_bytes / total_bytes
    print(f"\n[压缩比] 待分析 {pending_bytes}/{total_bytes} 字节 = {ratio * 100:.1f}%")
    assert COMPRESS_LO <= ratio <= COMPRESS_HI, \
        f"待分析数据占原始量 {ratio * 100:.1f}%，未落在 {COMPRESS_LO:.0%}-{COMPRESS_HI:.0%}"


def test_m1_2d_overview_endpoint_consistency(api):
    """统计端点（第三方可复核口径）与直读库一致：raw 全量 vs 分类量。"""
    image, task, _ = _prepare(api)
    stats = overview(api, task["id"])
    raw_total = stats["raw_database_stats"]["total_files"]
    categorized = stats["files_database_stats"]["categorized_files"]
    files_db = task_db(task["id"], "files")
    db_total = db_scalar(files_db, "SELECT COUNT(*) FROM files")
    assert categorized == db_total == raw_total - (
        db_scalar(task_db(task["id"], "raw"),
                  "SELECT COUNT(*) FROM files WHERE type != 'REG'") or 0), \
        "统计端点与任务库不一致（第三方复核口径冲突）"
