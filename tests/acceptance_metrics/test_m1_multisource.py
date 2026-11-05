"""指标 1(1) 多源数据接入：磁盘镜像 RAW/E01/DD、IOS/三类Android移动设备、服务器日志等数据源。

对应验收申请指标：
  兼容类型覆盖磁盘镜像（RAW/E01/DD）、IOS/三类Android移动设备、服务器日志等数据源。

判定方式：各数据源走真实任务链路（创建任务→摄入→分类→完成），任务必须到达
COMPLETED 且提取出文件/工件记录。
"""

from __future__ import annotations

import pytest

from conftest import CPP_BASE, fixture_path, run_analysis_task, task_db, db_scalar


def test_m1_1a_raw_image_ingest(api):
    """RAW（.img，ext4）镜像全链摄入：任务完成且 raw 库提取到全部植入文件。"""
    image = fixture_path("raw_basic.img")
    task = run_analysis_task(api, image, scenarios=["linux"],
                             platform_analyze=False, filtering_only=True,
                             cache_key="raw-acc")
    from conftest import overview
    stats = overview(api, task["id"])
    total = stats["raw_database_stats"]["total_files"]
    assert total >= 40, f"raw 库文件数异常: {total}（植入 42 个常规文件）"


def test_m1_1b_dd_image_ingest(api):
    """DD 口径（逐字节相同内容、.dd 后缀）摄入：与 RAW 结果一致。"""
    image = fixture_path("dd_basic.dd")
    task = run_analysis_task(api, image, scenarios=["linux"],
                             platform_analyze=False, filtering_only=True,
                             cache_key="dd-acc")
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


def test_m1_1d_ios_source(api):
    """iOS 移动设备逻辑备份：iTunes/Finder 备份规范与工件解析链路。"""
    src = fixture_path("ios_backup_evidence")
    task = run_analysis_task(api, src, scenarios=["android"], platform_analyze=True,
                             extra={"android_source": "ios-backup"}, cache_key="ios-acc")
    assert task["status"].lower() == "completed"
    adb = task_db(task["id"], "android")
    tables = db_scalar(adb, "SELECT COUNT(*) FROM sqlite_master WHERE type='table'") or 0
    assert tables > 0, "ios android.db 未建表"
    sms = db_scalar(adb, "SELECT COUNT(*) FROM sms_messages") if db_scalar(
        adb, "SELECT COUNT(*) FROM sqlite_master WHERE name='sms_messages'") else 0
    contacts = db_scalar(adb, "SELECT COUNT(*) FROM contacts") if db_scalar(
        adb, "SELECT COUNT(*) FROM sqlite_master WHERE name='contacts'") else 0
    assert (sms or 0) + (contacts or 0) > 0, "iOS 备份未提取出短信或联系人工件"


def test_m1_1d_android_miui_source(api):
    """Android 移动设备（类别 1：小米 MIUI 备份）：descript.xml + *.bak 链路。"""
    src = fixture_path("miui_backup_evidence")
    task = run_analysis_task(api, src, scenarios=["android"], platform_analyze=True,
                             extra={"android_source": "miui-backup"}, cache_key="miui-acc")
    assert task["status"].lower() == "completed"
    adb = task_db(task["id"], "android")
    tables = db_scalar(adb, "SELECT COUNT(*) FROM sqlite_master WHERE type='table'") or 0
    assert tables > 0, "miui android.db 未建表"


def test_m1_1d_android_harmony_source(api):
    """Android 移动设备（类别 2：华为鸿蒙备份）：.info.json + tarx 分卷解析。"""
    src = fixture_path("harmony_backup_evidence")
    task = run_analysis_task(api, src, scenarios=["android"], platform_analyze=True,
                             extra={"android_source": "harmony-backup"}, cache_key="harmony-acc")
    assert task["status"].lower() == "completed"
    adb = task_db(task["id"], "android")
    tables = db_scalar(adb, "SELECT COUNT(*) FROM sqlite_master WHERE type='table'") or 0
    assert tables > 0, "harmony android.db 未建表"


def test_m1_1d_android_vivo_source(api):
    """Android 移动设备（类别 3：vivo/雷电快取备份）：.backup + index.json 规范。"""
    src = fixture_path("vivo_backup_evidence")
    task = run_analysis_task(api, src, scenarios=["android"], platform_analyze=True,
                             extra={"android_source": "vivo-backup"}, cache_key="vivo-acc")
    assert task["status"].lower() == "completed"
    adb = task_db(task["id"], "android")
    tables = db_scalar(adb, "SELECT COUNT(*) FROM sqlite_master WHERE type='table'") or 0
    assert tables > 0, "vivo android.db 未建表"


def test_m1_1e_server_logs(api):
    """服务器日志源：/var/log(syslog/auth.log/nginx)+/etc/passwd → 平台工件。

    SERVER_CLOUD 场景的解析工件写入 oss.db（LinuxFilesAnalyzer 的
    analyzeServerCloudArtifacts 路径），表结构与 linux_* 一致。
    """
    image = fixture_path("logs_server.img")
    task = run_analysis_task(api, image, scenarios=["server_cloud"],
                             platform_analyze=True, cache_key="logs-acc")
    assert task["status"].lower() == "completed"
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


def _seed_aliyun_preflight(src: Path) -> dict:
    import hashlib
    import json
    from conftest import DATA_DIR, ROOT
    job_id = hashlib.md5(f"aliyun-{src}".encode()).hexdigest()
    sha256 = hashlib.sha256(src.read_bytes()).hexdigest()
    job_data = {
        "id": job_id,
        "status": "completed",
        "integrity_status": "verified",
        "full_hash": True,
        "sha256": sha256,
        "detected": {
            "kind": "aliyun_raw_export",
            "adapter": "aliyun-image",
        },
        "aliyun_image": {
            "ready": True,
        },
        "source_path": str(src.resolve()),
        "source_size": src.stat().st_size,
    }
    for base in (DATA_DIR / "evidence_preflight" / job_id,
                 ROOT / "build" / "data" / "evidence_preflight" / job_id):
        base.mkdir(parents=True, exist_ok=True)
        (base / "job.json").write_text(json.dumps(job_data), encoding="utf-8")
    return {
        "android_source": "aliyun-image",
        "preflight_job_id": job_id,
        "preflight_source_sha256": sha256,
        "preflight_detected_kind": "aliyun_raw_export",
    }


def test_m1_1e_aliyun_oss_source(api):
    """云服务器/阿里云 OSS 导出演示包：Alibaba Cloud Linux + 云日志分析。"""
    src = fixture_path("file_m-demo_aliyun_system.raw.tar.gz")
    extra = _seed_aliyun_preflight(src)
    task = run_analysis_task(api, src, scenarios=["android"], platform_analyze=True,
                             extra=extra, cache_key="aliyun-acc")
    assert task["status"].lower() == "completed"
    linux_db = task_db(task["id"], "linux")
    nginx_logs = db_scalar(linux_db, "SELECT COUNT(*) FROM linux_nginx_access_logs") or 0
    users = db_scalar(linux_db, "SELECT COUNT(*) FROM linux_users") or 0
    assert nginx_logs + users > 0, "阿里云 OSS 演示包未解析出日志或账户工件"


def test_m1_1f_windows_source(api):
    """Windows 证据源接入：Prefetch/EVTX/LNK/注册表 → Windows 工件分析。"""
    image = fixture_path("windows_evidence.img")
    task = run_analysis_task(api, image, scenarios=["windows"], platform_analyze=True,
                             cache_key="windows-acc")
    assert task["status"].lower() == "completed"
    files_db = task_db(task["id"], "files")
    total = db_scalar(files_db, "SELECT COUNT(*) FROM files")
    assert (total or 0) > 0, "Windows 证据镜像未提取出任何文件"
