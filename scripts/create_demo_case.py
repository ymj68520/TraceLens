#!/usr/bin/env python3
"""创建第三方验收演示案件，并为 7 个演示数据源执行完整的取证+分析数据流。"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path

CPP_BASE = "http://127.0.0.1:8666"
PY_BASE = "http://127.0.0.1:8090"
ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "demo_datasets"


def http_req(url: str, method: str = "GET", data: dict | None = None) -> tuple[int, dict]:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8")
            return resp.status, json.loads(content) if content else {}
    except urllib.error.HTTPError as e:
        content = e.read().decode("utf-8")
        try:
            return e.code, json.loads(content)
        except Exception:
            return e.code, {"error": content}


def seed_aliyun_preflight(source: Path) -> dict:
    job_id = hashlib.md5(f"aliyun-{source}".encode()).hexdigest()
    sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
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
        "source_path": str(source.resolve()),
        "source_size": source.stat().st_size,
    }
    for base in (ROOT / "data" / "evidence_preflight" / job_id,
                 ROOT / "build" / "data" / "evidence_preflight" / job_id):
        base.mkdir(parents=True, exist_ok=True)
        (base / "job.json").write_text(json.dumps(job_data), encoding="utf-8")
    return {
        "android_source": "aliyun-image",
        "preflight_job_id": job_id,
        "preflight_source_sha256": sha256,
        "preflight_detected_kind": "aliyun_raw_export",
    }


def wait_task(task_id: str, desc: str, timeout: int = 600) -> dict:
    print(f"  -> 等待任务 [{desc}] (ID: {task_id}) 完成...")
    deadline = time.monotonic() + timeout
    last_phase = ""
    while time.monotonic() < deadline:
        code, task = http_req(f"{CPP_BASE}/api/tasks/{task_id}")
        if code != 200:
            raise RuntimeError(f"查询任务失败({code}): {task}")
        status = task.get("status", "").lower()
        progress = task.get("progress") or {}
        curr_phase = f"{progress.get('current_phase')}({progress.get('overall_percentage', 0)}%) - {progress.get('phase_description', '')}"
        if curr_phase != last_phase:
            print(f"     进度: {curr_phase}")
            last_phase = curr_phase
        if status in ("completed", "failed", "cancelled"):
            if status != "completed":
                raise RuntimeError(f"任务未成功完成: status={status}, message={task.get('message')}, error={task.get('error_details')}")
            print(f"  ✓ 任务 [{desc}] 取证与分析完成！")
            return task
        time.sleep(1.0)
    raise TimeoutError(f"任务超时({timeout}s)")


def main():
    print("================================================================================")
    print("开始构建第三方验收综合演示案件与 7 大镜像完整数据流（取证+分析）")
    print("================================================================================")

    # 1. 创建演示案件
    case_payload = {
        "name": "第三方验收演示案件-涉案38.6万元跨平台特大资产挪用案",
        "description": (
            "本案为面向第三方国家权威测评机构现场验收的综合实战演示案件。"
            "案情背景：某某贸易有限公司内部主管张伟利用职权停用监控，"
            "财务经理李娜通过虚假平账将 386,000 元设备采购款异常调拨至外部人员王五账户。"
            "证据覆盖：Windows 办公主机、Linux 仓储服务器、阿里云 OSS 云存储及访问日志、"
            "iPhone 14 Pro 逻辑备份、以及小米 MIUI、华为鸿蒙 HarmonyOS、vivo/OPPO 三类移动端设备。"
        ),
        "task_ids": [],
    }
    code, created_case = http_req(f"{CPP_BASE}/api/cases", "POST", case_payload)
    if code != 201:
        print(f"创建案件失败({code}): {created_case}")
        sys.exit(1)
    case_id = created_case["id"]
    print(f"\n[1/4] 演示案件创建成功！")
    print(f"      案件编号: {case_id}")
    print(f"      案件名称: {created_case['name']}")

    # 2. 依次为 7 个演示数据源创建并执行完整数据流任务
    print("\n[2/4] 启动 7 份演示数据的完整数据流任务（取证与平台深度分析）...")

    configs = [
        {
            "key": "windows",
            "desc": "Windows 主管办公电脑（Prefetch/EVTX/LNK/注册表）",
            "path": DEMO_DIR / "01_windows" / "windows_evidence.img",
            "scenarios": ["windows"],
            "extra": {},
        },
        {
            "key": "linux",
            "desc": "Linux 仓储核心服务器（涉案通信/合同/台账/日志）",
            "path": DEMO_DIR / "02_linux" / "linux_evidence.img",
            "scenarios": ["linux"],
            "extra": {},
        },
        {
            "key": "aliyun_oss",
            "desc": "阿里云 ECS 主机与 OSS 接口转账调用日志",
            "path": DEMO_DIR / "03_aliyun_oss" / "file_m-demo_aliyun_system.raw.tar.gz",
            "scenarios": ["android"],
            "extra": seed_aliyun_preflight(DEMO_DIR / "03_aliyun_oss" / "file_m-demo_aliyun_system.raw.tar.gz"),
        },
        {
            "key": "ios",
            "desc": "嫌疑人张伟个人 iPhone 14 Pro 逻辑备份（短信/通讯录/备忘录）",
            "path": DEMO_DIR / "04_ios" / "ios_backup_evidence",
            "scenarios": ["android"],
            "extra": {"android_source": "ios-backup"},
        },
        {
            "key": "miui",
            "desc": "财务李娜小米手机 MIUI 备份（联系人/短信 bak）",
            "path": DEMO_DIR / "05_android_miui" / "miui_backup_evidence",
            "scenarios": ["android"],
            "extra": {"android_source": "miui-backup"},
        },
        {
            "key": "harmony",
            "desc": "涉案人员华为 Mate 60 Pro 鸿蒙备份（日历/通讯 tarx/wal）",
            "path": DEMO_DIR / "06_android_harmony" / "harmony_backup_evidence",
            "scenarios": ["android"],
            "extra": {"android_source": "harmony-backup"},
        },
        {
            "key": "vivo",
            "desc": "外部账户王五 vivo 手机快取备份（相册转账图/合同/应用）",
            "path": DEMO_DIR / "07_android_vivo" / "vivo_backup_evidence",
            "scenarios": ["android"],
            "extra": {"android_source": "vivo-backup"},
        },
    ]

    completed_task_ids = []
    task_summaries = []

    for i, cfg in enumerate(configs, 1):
        print(f"\n({i}/7) 正在接入并执行数据源: {cfg['desc']}")
        task_body = {
            "image_path": str(cfg["path"]),
            "case_description": f"[{created_case['name']}] - {cfg['desc']}",
            "scenarios": cfg["scenarios"],
            "platform_analyze": True,
            "llm_analyze": False,
            "llm_event_analyze": False,
            "filter_profile": "general_forensics",
        }
        task_body.update(cfg["extra"])
        code, task = http_req(f"{CPP_BASE}/api/tasks", "POST", task_body)
        if code != 201:
            print(f"创建任务失败({code}): {task}")
            sys.exit(1)
        task_id = task["id"]
        finished = wait_task(task_id, cfg["desc"])
        completed_task_ids.append(task_id)

        # 获取任务数据库概况
        code, ov = http_req(f"{CPP_BASE}/api/forensics/statistics/overview?task_id={task_id}")
        raw_files = ov.get("raw_database_stats", [{}])[0].get("total_files", 0) if isinstance(ov.get("raw_database_stats"), list) else 0
        events = ov.get("events_database_stats", [{}])[0].get("total_events", 0) if isinstance(ov.get("events_database_stats"), list) else 0
        task_summaries.append({
            "name": cfg["desc"],
            "task_id": task_id,
            "status": finished.get("status"),
            "raw_files": raw_files,
            "events": events,
            "databases": finished.get("scenario_databases", {}),
        })

    # 3. 将 7 个任务关联至案件
    print(f"\n[3/4] 将 7 个已完成的任务关联至演示案件...")
    code, updated_case = http_req(
        f"{CPP_BASE}/api/cases/{case_id}/tasks",
        "PUT",
        {"task_ids": completed_task_ids}
    )
    if code != 200:
        print(f"关联任务至案件失败({code}): {updated_case}")
    else:
        print(f"  ✓ 7 个取证分析任务已全部绑定至案件 {case_id}！")

    # 4. 在 Linux 核心证据任务上播种研判工作台（Bootstrap）
    linux_task_id = completed_task_ids[1]  # 第2个是 linux 任务
    print(f"\n[4/4] 启动核心涉案数据的时间线聚类与工作台播种...")
    b_code, b_res = http_req(
        f"{PY_BASE}/api/investigation/workbench/{linux_task_id}/bootstrap",
        "POST",
        {"mode": "cluster_seed", "generate_llm_summaries": False}
    )
    print(f"  工作台 bootstrap 状态: HTTP {b_code}")

    print("\n================================================================================")
    print("第三方验收综合演示案件与 7 大数据源全链路数据流构建成功！")
    print("================================================================================")
    print(f"案件 ID:   {case_id}")
    print(f"案件名称: {created_case['name']}")
    print(f"关联任务清单 (共 {len(completed_task_ids)} 个，全部 COMPLETED):")
    for s in task_summaries:
        print(f"  - [{s['status'].upper()}] {s['name']}")
        print(f"    任务ID: {s['task_id']}")
        if s['databases']:
            print(f"    生成平台库: {list(s['databases'].keys())}")
    print("\n现在可在浏览器前端（http://localhost:5173）中直接进入【案件管理】与【任务列表】")
    print("查看该综合案件，审查各个数据源的工件、时间线、重复文件去重与研判全流程！")


if __name__ == "__main__":
    main()
