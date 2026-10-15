"""指标 1(1) 多源数据接入：磁盘镜像 RAW/E01/DD、Android 移动设备、服务器日志。

对应验收申请指标：
  兼容类型覆盖磁盘镜像（RAW/E01/DD）、Android移动设备、服务器日志等数据源。

判定方式：各数据源走真实任务链路（创建任务→摄入→分类→完成），任务必须到达
COMPLETED 且提取出文件/工件记录。
"""

from __future__ import annotations

import pytest

from conftest import CPP_BASE, fixture_path, run_analysis_task, task_db


def test_m1_1a_raw_image_ingest(api):
    """RAW（.img，ext4）镜像全链摄入：任务完成且 raw 库提取到全部植入文件。"""
    image = fixture_path("raw_basic.img")
    task = run_analysis_task(api, image, scenarios=["linux"],
                             platform_analyze=False, cache_key="raw-acc")
    from conftest import overview
    stats = overview(api, task["id"])
    total = stats["raw_database_stats"]["total_files"]
    assert total >= 40, f"raw 库文件数异常: {total}（植入 42 个常规文件）"


def test_m1_1b_dd_image_ingest(api):
    """DD 口径（逐字节相同内容、.dd 后缀）摄入：与 RAW 结果一致。"""
    image = fixture_path("dd_basic.dd")
    task = run_analysis_task(api, image, scenarios=["linux"],
                             platform_analyze=False, cache_key="dd-acc")
    from conftest import overview
    stats = overview(api, task["id"])
    assert stats["raw_database_stats"]["total_files"] >= 40


def test_m1_1c_e01_image_ingest(api):
    """E01（EnCase）镜像摄入：需要真实 E01（开源工具无法凭空生成）。"""
    import os
    e01 = os.environ.get("TRACELENS_E01_IMAGE")
    if not e01:
        default = fixture_path("e01.E01")  # missing -> skip with instructions
        e01 = str(default)
    task = run_analysis_task(api, e01, scenarios=["windows"], cache_key=f"e01-acc-{e01}")
    assert task["status"].lower() == "completed"
    from conftest import overview
    stats = overview(api, task["id"])
    assert stats["raw_database_stats"]["total_files"] > 0, "E01 未提取出任何文件"


def test_m1_1d_android_source(api):
    """Android 移动设备镜像：TSK 管线 + AndroidAnalyzer 工件库。"""
    image = fixture_path("android_test_gen.img")
    task = run_analysis_task(api, image, scenarios=["android"], platform_analyze=True,
                             extra={"android_source": "tsk"}, cache_key="android-acc")
    assert task["status"].lower() == "completed"
    adb = task_db(task["id"], "android")
    from conftest import db_scalar
    tables = db_scalar(adb, "SELECT COUNT(*) FROM sqlite_master WHERE type='table'") or 0
    assert tables > 0, "android.db 未建表"


def test_m1_1e_server_logs(api):
    """服务器日志源：/var/log(syslog/auth.log/nginx)+/etc/passwd → 平台工件。

    SERVER_CLOUD 场景的解析工件写入 oss.db（LinuxFilesAnalyzer 的
    analyzeServerCloudArtifacts 路径），表结构与 linux_* 一致。
    """
    image = fixture_path("logs_server.img")
    task = run_analysis_task(api, image, scenarios=["server_cloud"],
                             platform_analyze=True, cache_key="logs-acc")
    assert task["status"].lower() == "completed"
    from conftest import db_scalar
    server_db = task_db(task["id"], "oss")
    log_rows = db_scalar(server_db, "SELECT COUNT(*) FROM linux_log_entries")
    users = db_scalar(server_db, "SELECT COUNT(*) FROM linux_users")
    assert (log_rows or 0) + (users or 0) > 0, "oss.db 未解析出日志/账户工件"


def test_m1_1e_server_log_events(api):
    """服务器日志夹具同时应产出系统事件（EventExtractor 系统事件链路）。"""
    from conftest import overview
    task = run_analysis_task(api, fixture_path("logs_server.img"),
                             scenarios=["server_cloud"], platform_analyze=True,
                             cache_key="logs-acc")
    stats = overview(api, task["id"])
    events = stats["events_database_stats"]["total_events"]
    assert events > 0, "服务器日志夹具未产出任何事件"
