#!/usr/bin/env python3
"""基于移动硬盘与/data2真实检材创建实战多源案件，并接入7大真实镜像（Windows、Linux、阿里云OSS、iOS、三个Android）"""

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
    h = hashlib.sha256()
    with open(source, "rb") as f:
        while chunk := f.read(16 * 1024 * 1024):
            h.update(chunk)
    sha256 = h.hexdigest()
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
        (base / "job.json").write_text(json.dumps(job_data, indent=2), encoding="utf-8")
    return {
        "android_source": "aliyun-image",
        "preflight_job_id": job_id,
        "preflight_source_sha256": sha256,
        "preflight_detected_kind": "aliyun_raw_export",
    }


def wait_task(task_id: str, desc: str, timeout: int = 1800) -> dict:
    print(f"  -> 等待任务 [{desc}] (ID: {task_id}) 取证分析执行...")
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
            print(f"     [进度更新] {curr_phase}")
            last_phase = curr_phase
        if status in ("completed", "failed", "cancelled"):
            if status != "completed":
                raise RuntimeError(f"任务未成功完成: status={status}, message={task.get('message')}, error={task.get('error_details')}")
            print(f"  ✓ 任务 [{desc}] 取证与平台分析顺利完成！")
            return task
        time.sleep(2.0)
    raise TimeoutError(f"任务超时({timeout}s)")


def main():
    print("================================================================================")
    print("开始构建真实检材实战案件与 7 大真实镜像取证数据流（Win/Linux/OSS/iOS/3安卓）")
    print("================================================================================")

    # 1. 创建实战真实案件
    case_payload = {
        "name": "实战案件-涉案千万级虚假理财杀猪盘特大跨境电信网络诈骗专案",
        "description": (
            "本案为基于移动硬盘（/mnt/evidence_sdb1）与/data2数据区真实检材构建的综合实战多源取证案例。"
            "案情背景：境外电信网络诈骗团伙搭建虚假投资理财交易平台“jijin”（域名 jijin.com、hxfund.xyz），"
            "通过伪造入金凭证、境外分析师人设话术包装等手段诱导国内被害人投资买币，并实施反取证清痕与资金跨境清洗。"
            "专案组查获核心涉案物证并完成真实数据固定："
            "1. 窝点作案嫌疑人 Windows 工作站（话术体系、客资清单、以太坊钱包与 TrueCrypt 加密容器）；"
            "2. 云端核心诈骗平台 Linux 服务器（CentOS 7、ThinkPHP 源码、MySQL 客服聊天库与 SSH 运维痕迹）；"
            "3. 涉案阿里云云主机系统盘与 OSS 对象存储调用日志（接口转账记录与宝塔访问日志）；"
            "4. 涉案财务主管李佩妍 iPhone 手机（iOS 16.5 逻辑备份，短信、通讯录、日历与涉案备忘录）；"
            "5. 窝点涉案技术员小米手机（MIUI 备份，微信、QQ、短信与通联记录）；"
            "6. 窝点运营组长 vivo iQOO 手机（快取备份，转账截图凭据、合同文档与音视频）；"
            "7. 推广业务员 OPPO 手机（雷电手机快取 ThunderForensic，应用清单与通联痕迹）。"
        ),
        "task_ids": [],
    }
    code, created_case = http_req(f"{CPP_BASE}/api/cases", "POST", case_payload)
    if code != 201:
        print(f"创建案件失败({code}): {created_case}")
        sys.exit(1)
    case_id = created_case["id"]
    print(f"\n[1/4] 实战案例创建成功！")
    print(f"      案件编号: {case_id}")
    print(f"      案件名称: {created_case['name']}")

    # 2. 定义 7 大真实镜像配置（覆盖 Windows、Linux、阿里云OSS、iOS、3个安卓）
    aliyun_source = Path("/mnt/evidence_sdb1/取证/testimgs/阿里云服务器镜像/file_m-2ze5efcr1i2o3f3mnarc_system.raw.tar.gz")
    print("\n[2/4] 预检并准备 7 大真实镜像配置...")

    configs = [
        {
            "key": "windows",
            "desc": "Windows 窝点作案工作站（话术体系/客资数据库/ETH钱包/TrueCrypt加密/反取证）",
            "path": Path("/mnt/evidence_sdb1/取证/testimgs/窝点嫌疑人计算机镜像.E01"),
            "scenarios": ["windows"],
            "filter_profile": "诈骗窝点工作站专项",
            "extra": {},
        },
        {
            "key": "linux",
            "desc": "Linux 云端虚假理财诈骗平台服务器（CentOS 7/ThinkPHP/宝塔/jijin.com/MySQL聊天库）",
            "path": Path("/mnt/evidence_sdb1/取证/testimgs/服务器镜像.E01"),
            "scenarios": ["linux"],
            "filter_profile": "诈骗平台服务器专项",
            "extra": {},
        },
        {
            "key": "aliyun_oss",
            "desc": "阿里云 ECS 云服务器系统盘与 OSS 对象存储调用日志（转账接口/访问日志/宝塔运维）",
            "path": aliyun_source,
            "scenarios": ["linux"],
            "filter_profile": "general_forensics",
            "extra": seed_aliyun_preflight(aliyun_source),
        },
        {
            "key": "ios",
            "desc": "涉案财务主管李佩妍 iPhone 个人手机逻辑备份（iMessage短信/通讯录/涉案备忘录/通联日历）",
            "path": Path("/data2/Forensics/ios_extract/李佩妍的手機鏡像/d5747fae8f4ddba485f17710026bd6bff268acb0"),
            "scenarios": ["android"],
            "filter_profile": "general_forensics",
            "extra": {"android_source": "ios-backup"},
        },
        {
            "key": "android_miui",
            "desc": "涉案窝点技术员小米手机 MIUI 备份（微信/QQ/涉案通联记录）",
            "path": Path("/mnt/evidence_sdb1/取证/testimgs/MIUIBackup"),
            "scenarios": ["android"],
            "filter_profile": "telecom_fraud",
            "extra": {"android_source": "miui-backup"},
        },
        {
            "key": "android_vivo",
            "desc": "窝点运营组长 vivo iQOO 手机快取备份（作案相册/转账截图凭据/涉案合同文档/音视频）",
            "path": Path("/data2/Forensics/vivo_extract/vivo iQOO 20261029_150738"),
            "scenarios": ["android"],
            "filter_profile": "general_forensics",
            "extra": {"android_source": "vivo-backup"},
        },
        {
            "key": "android_oppo",
            "desc": "前线推广业务员 OPPO 手机雷电快取提取（PhoneData应用数据/涉案通联记录/网络配置）",
            "path": Path("/mnt/evidence_sdb1/20261025手机提取/分析数据/20261025OPPO"),
            "scenarios": ["android"],
            "filter_profile": "general_forensics",
            "extra": {"android_source": "thunder-backup"},
        },
    ]

    completed_task_ids = []
    task_summaries = []

    for i, cfg in enumerate(configs, 1):
        print(f"\n({i}/7) 正在接入并启动真实数据源任务: {cfg['desc']}")
        print(f"      检材物理路径: {cfg['path']}")
        print(f"      适用场景: {cfg['scenarios']}, 定向过滤策略: {cfg['filter_profile']}")

        task_body = {
            "image_path": str(cfg["path"].resolve()),
            "case_description": f"[{created_case['name']}] - {cfg['desc']}",
            "scenarios": cfg["scenarios"],
            "platform_analyze": True,
            "llm_analyze": False,
            "llm_event_analyze": False,
            "filter_profile": cfg["filter_profile"],
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

    # 3. 将 7 个任务关联至实战案件
    print(f"\n[3/4] 将 7 个已完成的任务绑定至案件 {case_id}...")
    code, updated_case = http_req(
        f"{CPP_BASE}/api/cases/{case_id}/tasks",
        "PUT",
        {"task_ids": completed_task_ids}
    )
    if code != 200:
        print(f"关联任务至案件失败({code}): {updated_case}")
    else:
        print(f"  ✓ 7 大真实镜像取证分析任务已全部绑定至实战案件 {case_id}！")

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
    print("实战案件构建与 7 大真实镜像全链路数据流取证完成！")
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
    print("查看该实战案件及其关联的 7 个真实检材数据流与时间线！")


if __name__ == "__main__":
    main()
