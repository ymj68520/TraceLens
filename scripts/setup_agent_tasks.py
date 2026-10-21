"""Setup task directories, symlinks, and complete investigation.db fixtures.
Ensures both server and suspect workstation images have complete, verifiable data.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

# Add python_service to sys.path
INTEGRATION_ROOT = Path("/home/ymj68520/projects/TraceLens-agent-v0-integration")
if str(INTEGRATION_ROOT / "python_service") not in sys.path:
    sys.path.insert(0, str(INTEGRATION_ROOT / "python_service"))

from httpserver.services.investigation.agent_runtime import AgentRuntimeRepository
from httpserver.services.investigation.agent_working_state import (
    AgentWorkingStateV1,
    EvidenceRelevanceStatus,
    EvidenceWorkingSetItem,
    Hypothesis,
    HypothesisStatus,
    QuestionPriority,
    QuestionSource,
    QuestionStatus,
    WorkingQuestion,
    working_state_to_json,
)
from httpserver.services.investigation.repository import InvestigationRepository

PROJECT_TASKS_DIR = Path("/home/ymj68520/projects/TraceLens/build/data/tasks")
PROJECT_BUILD_DIR = Path("/home/ymj68520/projects/TraceLens/build")
INTEGRATION_BUILD_DIR = Path("/home/ymj68520/projects/TraceLens-agent-v0-integration/build")

SERVER_FILES_DB = PROJECT_BUILD_DIR / "服务器镜像_files.db"
SERVER_EVENTS_DB = PROJECT_BUILD_DIR / "服务器镜像_events.db"
SERVER_RAW_DB = PROJECT_BUILD_DIR / "服务器镜像_raw.db"

WODIAN_FILES_DB = PROJECT_BUILD_DIR / "窝点嫌疑人计算机镜像_files.db"
WODIAN_EVENTS_DB = PROJECT_BUILD_DIR / "窝点嫌疑人计算机镜像_events.db"
WODIAN_RAW_DB = PROJECT_BUILD_DIR / "窝点嫌疑人计算机镜像_raw.db"


def setup_all_tasks_symlinks():
    """Ensure every server & suspect image task has its db symlinks."""
    tasks_json_path = PROJECT_BUILD_DIR / "data/tasks.json"
    with open(tasks_json_path) as f:
        tasks = json.load(f)

    PROJECT_TASKS_DIR.mkdir(parents=True, exist_ok=True)
    count = 0
    for t in tasks:
        tid = t.get("id")
        img = str(t.get("image_path", ""))
        if not tid:
            continue
        task_dir = PROJECT_TASKS_DIR / tid

        if "服务器镜像" in img:
            task_dir.mkdir(parents=True, exist_ok=True)
            for db_name, target in [
                ("files.db", SERVER_FILES_DB),
                ("events.db", SERVER_EVENTS_DB),
                ("raw.db", SERVER_RAW_DB),
                ("raw.db.filtered", SERVER_RAW_DB),
            ]:
                link = task_dir / db_name
                if link.is_symlink() or link.exists():
                    link.unlink()
                link.symlink_to(target)
            count += 1
        elif "窝点嫌疑人计算机镜像" in img:
            task_dir.mkdir(parents=True, exist_ok=True)
            for db_name, target in [
                ("files.db", WODIAN_FILES_DB),
                ("events.db", WODIAN_EVENTS_DB),
                ("raw.db", WODIAN_RAW_DB),
                ("raw.db.filtered", WODIAN_RAW_DB),
            ]:
                link = task_dir / db_name
                if link.is_symlink() or link.exists():
                    link.unlink()
                link.symlink_to(target)
            count += 1

    print(f"Set up symlinks for {count} tasks pointing to real databases.")

    # Ensure integration worktree build/data points to TraceLens/build/data
    int_data = INTEGRATION_BUILD_DIR / "data"
    int_data.mkdir(parents=True, exist_ok=True)
    for name in ["tasks", "tasks.json", "cases.json"]:
        src = PROJECT_BUILD_DIR / "data" / name
        dst = int_data / name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src)


def setup_server_task_investigation():
    """Build investigation.db for server image task 599d6bf5-8ebe-4ae2-baa5-6dc0fd39b5fc."""
    task_id = "599d6bf5-8ebe-4ae2-baa5-6dc0fd39b5fc"
    inv_id = "inv_c70d4f145b09"
    task_dir = PROJECT_TASKS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    db_path = task_dir / "investigation.db"

    if db_path.exists():
        db_path.unlink()

    repo = InvestigationRepository(db_path, task_id)
    runtime = AgentRuntimeRepository(repo)

    questions = (
        WorkingQuestion(
            question_id="Q1",
            text="调查系统部署与运维执行痕迹，排查宝塔面板(BT Panel)、下载脚本与服务安装行为",
            source=QuestionSource.charter,
            priority=QuestionPriority.required,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="Q2",
            text="调查涉案嫌疑人账号与身份凭据，排查 adduser/passwd 新增账号与异常提权记录",
            source=QuestionSource.charter,
            priority=QuestionPriority.high,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="Q3",
            text="调查服务自启动与开机持久化配置，排查 chkconfig/systemd 等异常自启服务",
            source=QuestionSource.charter,
            priority=QuestionPriority.high,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="q-61dff02c",
            text="调查远程网络连接与外部 IP 通信记录，确认外部控制源与数据通道",
            source=QuestionSource.charter,
            priority=QuestionPriority.normal,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="q-ad56bfce",
            text="调查反取证与日志篡改行为，定位系统日志与认证日志中的异常时间跳变与删除痕迹",
            source=QuestionSource.charter,
            priority=QuestionPriority.required,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="q-b856d85c",
            text="调查系统登录历史与主机重启事件，核查 wtmp/last 记录与终端会话对应关系",
            source=QuestionSource.charter,
            priority=QuestionPriority.normal,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="q-de74d9f4",
            text="调查受害主机系统环境与发行版特征，固化 /etc/redhat-release 与系统配置文件",
            source=QuestionSource.charter,
            priority=QuestionPriority.normal,
            status=QuestionStatus.open,
        ),
    )

    hypotheses = (
        Hypothesis(
            hypothesis_id="hyp-srv-persistence-01",
            text="该服务器被用于架设涉案网络服务平台，嫌疑人通过部署宝塔面板降低运维门槛，创建 wangwu 账户维持后门访问，并存在日志时间异常对抗取证检测",
            status=HypothesisStatus.active,
            supporting_refs=("file:/root/.bash_history", "file:/etc/passwd"),
        ),
    )

    evidence_working_set = (
        EvidenceWorkingSetItem(evidence_key="file:/root/.bash_history", related_question_ids=("Q1", "Q2", "Q3"), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/etc/passwd", related_question_ids=("Q2",), status=EvidenceRelevanceStatus.relevant),
        EvidenceWorkingSetItem(evidence_key="file:/etc/inittab", related_question_ids=("Q3",), status=EvidenceRelevanceStatus.candidate),
        EvidenceWorkingSetItem(evidence_key="file:/etc/group", related_question_ids=("Q2", "q-de74d9f4"), status=EvidenceRelevanceStatus.candidate),
        EvidenceWorkingSetItem(evidence_key="cluster:v1:27555927:CREATED", related_question_ids=("q-ad56bfce",), status=EvidenceRelevanceStatus.candidate),
    )

    finding_refs = (
        "f-srv-bt-install-01",
        "f-srv-user-wangwu-02",
        "f-srv-tampering-gap-03",
        "f-srv-sys-chkconfig-04",
        "f-srv-os-fingerprint-05",
    )

    # Initial State Rev 1
    state_v1 = AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=inv_id,
        objective="服务器镜像取证研判：固定宝塔面板部署、非授权账户创建(wangwu)、日志时间跳变与系统持久化配置痕迹",
        questions=questions,
        hypotheses=hypotheses,
        evidence_working_set=evidence_working_set,
    )

    runtime.create_investigation(
        working_state_to_json(state_v1),
        investigation_id=inv_id,
    )

    # Commit State Rev 2 with finding_refs
    state_v2 = state_v1.model_copy(update={"finding_refs": finding_refs})
    rev2 = runtime.commit_working_state(inv_id, state_v2.model_dump(mode="json"), expected_revision=1)
    print("Server investigation committed Rev 2:", rev2.revision, rev2.state_hash)

    # Insert findings
    findings = [
        ("f-srv-bt-install-01", "prop_srv_bt_01", "disp_srv_bt_01", "嫌疑人在服务器上执行一键脚本安装宝塔Linux面板 (http://download.bt.cn/install/install_6.0.sh)，并运行 bt 14 查询初始后台登录入口与管理员密码", "FACT", json.dumps({"refs": ["file:/root/.bash_history"]}), "grnd_srv_bt_01", "review_pending", None, None, None, None),
        ("f-srv-user-wangwu-02", "prop_srv_user_02", "disp_srv_user_02", "嫌疑人使用 adduser wangwu 新增非授权系统账户，并执行 passwd wangwu admin 设置弱口令 ('admin') 作为持久化维持手段", "FACT", json.dumps({"refs": ["file:/root/.bash_history", "file:/etc/passwd"]}), "grnd_srv_user_02", "review_pending", None, None, None, None),
        ("f-srv-tampering-gap-03", "prop_srv_tamper_03", "disp_srv_tamper_03", "系统日志中检出多处时间跳变异常（TIME_WINDOW_GAP，最大间隔超17亿秒），疑似通过修改系统时间或清除日志进行反取证对抗", "INFERENCE", json.dumps({"refs": ["file:/root/.bash_history", "cluster:v1:27555927:CREATED"]}), "grnd_srv_tamper_03", "review_pending", None, None, None, None),
        ("f-srv-sys-chkconfig-04", "prop_srv_chkconfig_04", "disp_srv_chkconfig_04", "嫌疑人执行 chkconfig 检查系统服务自启配置，排查后台守护进程与开机持久化启动项", "FACT", json.dumps({"refs": ["file:/root/.bash_history", "file:/etc/inittab"]}), "grnd_srv_chkconfig_04", "review_pending", None, None, None, None),
        ("f-srv-os-fingerprint-05", "prop_srv_os_05", "disp_srv_os_05", "检出服务器系统发行版探查痕迹 (cat /etc/redhat-release)，嫌疑人对主机运行环境进行了信息收集", "FACT", json.dumps({"refs": ["file:/root/.bash_history", "file:/etc/group"]}), "grnd_srv_os_05", "accepted", "2026-10-18T14:35:00Z", "analyst_auto", "通过历史执行记录与系统组文件双重印证，准予采纳", "rev_decision_05"),
    ]

    with runtime._connect() as conn:
        for f in findings:
            conn.execute("""
                INSERT INTO investigation_findings (
                    finding_id, task_id, investigation_id, proposal_id, disposition_id,
                    text, assertion_class, evidence_refs_json, relationship_refs_json,
                    grounding_id, limitations_json, status, reviewed_at, reviewer,
                    review_note, review_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, '{"limitations": []}', ?, ?, ?, ?, ?, '2026-10-18T14:35:00Z')
            """, [
                f[0], task_id, inv_id, f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[10], f[11]
            ])
        conn.execute("""
            INSERT INTO investigation_finding_reviews (
                review_id, task_id, investigation_id, finding_id, decision, reviewer, note, created_at
            ) VALUES ('rev_decision_05', ?, ?, 'f-srv-os-fingerprint-05', 'accepted', 'analyst_auto', '通过历史执行记录与系统组文件双重印证，准予采纳', '2026-10-18T14:35:00Z')
        """, [task_id, inv_id])
        conn.commit()

    print("Server task investigation.db successfully populated.")


def setup_wodian_task_investigation():
    """Build investigation.db for suspect workstation task 60dedf82-7f35-48be-a104-b4d283a4fe92."""
    task_id = "60dedf82-7f35-48be-a104-b4d283a4fe92"
    inv_id = "inv_wo_dian_002"
    task_dir = PROJECT_TASKS_DIR / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    db_path = task_dir / "investigation.db"

    if db_path.exists():
        db_path.unlink()

    repo = InvestigationRepository(db_path, task_id)
    runtime = AgentRuntimeRepository(repo)

    questions = (
        WorkingQuestion(
            question_id="Q1",
            text="诈骗话术体系与培训资料库：固定磁盘/话术/目录下多套话术范例、剧本及新人培训资料",
            source=QuestionSource.charter,
            priority=QuestionPriority.required,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="Q2",
            text="涉案嫌疑人身份与层级架构：排查窝点业务员、主管（如老师包装）与组织协作身份",
            source=QuestionSource.charter,
            priority=QuestionPriority.required,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="Q3",
            text="涉诈赃款归集与虚拟货币钱包：发现 TrueCrypt 隐藏卷、ETH 钱包、加密货币买币教程",
            source=QuestionSource.charter,
            priority=QuestionPriority.high,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="q-61dff02c",
            text="受害人与客源引流渠道：挖掘客源线索、引流群组以及多日客户沟通推进记录",
            source=QuestionSource.charter,
            priority=QuestionPriority.normal,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="q-ad56bfce",
            text="反取证与技术防范行为：检查磁盘加密、痕迹清理工具及反取证操作痕迹",
            source=QuestionSource.charter,
            priority=QuestionPriority.required,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="q-b856d85c",
            text="作案终端与涉诈平台闭环关联：构建终端环境与受害人被骗平台的网络与数据闭环",
            source=QuestionSource.charter,
            priority=QuestionPriority.normal,
            status=QuestionStatus.open,
        ),
        WorkingQuestion(
            question_id="q-de74d9f4",
            text="涉诈平台技术特征与部署环境：提取涉案平台源码、配置、部署日志与交互协议特征",
            source=QuestionSource.charter,
            priority=QuestionPriority.normal,
            status=QuestionStatus.open,
        ),
    )

    hypotheses = (
        Hypothesis(
            hypothesis_id="h-785f674c",
            text="该工作站采用 TrueCrypt 加密容器隐藏数据，并借助 WYWZ（无影无踪）文件粉碎工具清除痕迹，同时通过 Xshell 远程控制涉诈服务器",
            status=HypothesisStatus.active,
            supporting_refs=("file:/Program Files/TrueCrypt/TrueCrypt.exe", "file:/Users/Administrator/Documents/NetSarang Computer/7/Xshell/Sessions/39.102.228.118.xsh"),
        ),
    )

    evidence_working_set = (
        EvidenceWorkingSetItem(evidence_key="file:/话术/老师包装.txt", related_question_ids=("Q1",), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/话术/拒绝视频话术.txt", related_question_ids=("Q1",), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/Users/Administrator/AppData/Roaming/Microsoft/Windows/Recent/6月重点目标.xlsx.lnk", related_question_ids=("Q2", "q-61dff02c"), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/Program Files (x86)/WYWZ/Wywz.exe", related_question_ids=("q-ad56bfce",), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/Program Files/TrueCrypt/TrueCrypt.exe", related_question_ids=("Q3", "q-ad56bfce"), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/soft/TrueCrypt/importent", related_question_ids=("Q3", "q-ad56bfce"), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/Users/Administrator/Documents/NetSarang Computer/7/Xshell/Sessions/39.102.228.118.xsh", related_question_ids=("q-b856d85c", "q-de74d9f4"), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/Users/Administrator/Downloads/OKX-android_APPEX668.apk", related_question_ids=("Q3",), status=EvidenceRelevanceStatus.relevant),
        EvidenceWorkingSetItem(evidence_key="file:/$OrphanFiles/mima.txt", related_question_ids=("Q2", "Q3"), status=EvidenceRelevanceStatus.high_value),
        EvidenceWorkingSetItem(evidence_key="file:/$OrphanFiles/菜商数据（大炜）.7z", related_question_ids=("Q2", "q-61dff02c"), status=EvidenceRelevanceStatus.high_value),
    )

    finding_refs = (
        "f-pillar1-scripts-01",
        "f-pillar1-scripts-02",
        "f-pillar2-targets-01",
        "f-pillar4-antiforensics-01",
        "f-pillar4-antiforensics-02",
        "f-pillar5-infra-01",
        "f-pillar5-infra-02",
        "f-pillar3-loot-01",
        "f-pillar2-targets-02",
        "f-pillar6-cryptocoin-01",
    )

    state_v1 = AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=inv_id,
        objective="涉诈投资平台（杀猪盘）窝点作案终端案：固定窝点话术体系、受害人与客源数据、赃款归集线索与反取证行为，并闭环终端与平台关联",
        questions=questions,
        hypotheses=hypotheses,
        evidence_working_set=evidence_working_set,
    )

    runtime.create_investigation(
        working_state_to_json(state_v1),
        investigation_id=inv_id,
    )

    state_v2 = state_v1.model_copy(update={"finding_refs": finding_refs})
    rev2 = runtime.commit_working_state(inv_id, state_v2.model_dump(mode="json"), expected_revision=1)
    print("Wodian investigation committed Rev 2:", rev2.revision, rev2.state_hash)

    findings = [
        ("f-pillar1-scripts-01", "prop_wd_01", "disp_wd_01", "磁盘根目录存在完整诈骗话术培训资料库（/话术/），包含《老师包装.txt》、《拒绝视频话术.txt》、《Crypto.com买币流程.docx》", "FACT", json.dumps({"refs": ["file:/话术/老师包装.txt", "file:/话术/拒绝视频话术.txt"]}), "grnd_wd_01", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "真实话术文件查验属实", "rev_wd_01"),
        ("f-pillar1-scripts-02", "prop_wd_02", "disp_wd_02", "/话术/目录包含分阶段（第一天至第六天）新人洗脑与情感包装教程、包装例1/包装例2、聊天思维以及细节拿捏、使用USDT的买币教程", "FACT", json.dumps({"refs": ["file:/话术/老师包装.txt"]}), "grnd_wd_02", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "教程资料固定完整", "rev_wd_02"),
        ("f-pillar2-targets-01", "prop_wd_03", "disp_wd_03", "Administrator 用户 Recent 访问记录中存在重点目标表格快捷方式《6月重点目标.xlsx.lnk》，表明嫌疑人具有针对特定高净值受害人的定向诱导行为", "FACT", json.dumps({"refs": ["file:/Users/Administrator/AppData/Roaming/Microsoft/Windows/Recent/6月重点目标.xlsx.lnk"]}), "grnd_wd_03", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "重点目标清单属实", "rev_wd_03"),
        ("f-pillar4-antiforensics-01", "prop_wd_04", "disp_wd_04", "检出 WYWZ（无影无踪）反取证痕迹擦除软件（/Program Files (x86)/WYWZ/），具有反取证数据粉碎目的", "FACT", json.dumps({"refs": ["file:/Program Files (x86)/WYWZ/Wywz.exe"]}), "grnd_wd_04", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "反取证工具固定完成", "rev_wd_04"),
        ("f-pillar4-antiforensics-02", "prop_wd_05", "disp_wd_05", "系统安装有开源卷加密软件 TrueCrypt（/Program Files/TrueCrypt/），并在 /soft/TrueCrypt/ 下发现加密卷容器 importent", "FACT", json.dumps({"refs": ["file:/Program Files/TrueCrypt/TrueCrypt.exe", "file:/soft/TrueCrypt/importent"]}), "grnd_wd_05", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "加密卷软件配置属实", "rev_wd_05"),
        ("f-pillar5-infra-01", "prop_wd_06", "disp_wd_06", "检出 NetSarang Xshell 7 远程管理会话《39.102.228.118.xsh》以及 5 份历史连接运行配置，直接关联远程涉诈云端服务器", "FACT", json.dumps({"refs": ["file:/Users/Administrator/Documents/NetSarang Computer/7/Xshell/Sessions/39.102.228.118.xsh"]}), "grnd_wd_06", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "远程控制端闭环", "rev_wd_06"),
        ("f-pillar5-infra-02", "prop_wd_07", "disp_wd_07", "用户 Downloads 目录检出两款主流加密数字资产交易所客户端安装包（OKX-android_APPEX668.apk 等），结合受害人入金资金流印证涉案赃款向虚拟资产兑换", "FACT", json.dumps({"refs": ["file:/Users/Administrator/Downloads/OKX-android_APPEX668.apk"]}), "grnd_wd_07", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "入金通道属实", "rev_wd_07"),
        ("f-pillar3-loot-01", "prop_wd_08", "disp_wd_08", "孤立文件目录检出被删除的密码备忘录《mima.txt》（file:/$OrphanFiles/mima.txt），该文件包含各类社交与平台运维明文凭据", "FACT", json.dumps({"refs": ["file:/$OrphanFiles/mima.txt"]}), "grnd_wd_08", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "孤立密码文件固定", "rev_wd_08"),
        ("f-pillar2-targets-02", "prop_wd_09", "disp_wd_09", "孤立文件目录检出被删除的压缩包《菜商数据（大炜）.7z》（文件大小 64,890,236 字节），结合案情中“菜商/黑产数据源”线索，确认其为大规模公民个人信息与引流受害者底库", "FACT", json.dumps({"refs": ["file:/$OrphanFiles/菜商数据（大炜）.7z"]}), "grnd_wd_09", "accepted", "2026-10-18T12:00:00Z", "lead_analyst", "菜商黑产数据包核验通过", "rev_wd_09"),
        ("f-pillar6-cryptocoin-01", "prop_wd_10", "disp_wd_10", "嫌疑人使用 TrueCrypt 加密容器存储私钥备忘，并记录以太坊钱包地址归集涉诈赃款，存在多笔加密币出入金对账痕迹", "FACT", json.dumps({"refs": ["file:/Program Files/TrueCrypt/TrueCrypt.exe", "file:/soft/TrueCrypt/importent", "file:/$OrphanFiles/mima.txt"]}), "grnd_wd_10", "review_pending", None, None, None, None),
    ]

    with runtime._connect() as conn:
        for f in findings:
            conn.execute("""
                INSERT INTO investigation_findings (
                    finding_id, task_id, investigation_id, proposal_id, disposition_id,
                    text, assertion_class, evidence_refs_json, relationship_refs_json,
                    grounding_id, limitations_json, status, reviewed_at, reviewer,
                    review_note, review_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, '{"limitations": []}', ?, ?, ?, ?, ?, '2026-10-18T12:00:00Z')
            """, [
                f[0], task_id, inv_id, f[1], f[2], f[3], f[4], f[5], f[6], f[7], f[8], f[9], f[10], f[11]
            ])
            if f[11]:
                conn.execute("""
                    INSERT INTO investigation_finding_reviews (
                        review_id, task_id, investigation_id, finding_id, decision, reviewer, note, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, '2026-10-18T12:00:00Z')
                """, [f[11], task_id, inv_id, f[0], f[7], f[9], f[10]])
        conn.commit()

    print("Wodian task investigation.db successfully populated.")


if __name__ == "__main__":
    setup_all_tasks_symlinks()
    setup_server_task_investigation()
    setup_wodian_task_investigation()
    print("ALL TASK SETUP COMPLETED!")
