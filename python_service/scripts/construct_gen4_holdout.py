"""Acceptance Generation 4 construction (§5-§13).

Holdout Author / Truth Author / Evidence Substrate Builder / Protocol
Validator stages, mirroring the frozen Gen-3 protocol exactly (same
contract classes, same per-case substrate discipline, zero model calls).
The hydration preseal validation (§14-§17) is a separate script
(validate_gen4_hydration.py) that exercises the PRODUCTION content read
path against these sealed manifests.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

REPO_ROOT = PYTHON_SERVICE_ROOT.parent
GEN4_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen4"
)
IMAGES_DIR = GEN4_ROOT / "images"
BUILD_DIR = PYTHON_SERVICE_ROOT / "build" / "data" / "benchimages-gen4"
CREATED_AT = "2026-10-01T00:00:00+00:00"
PINNED_STAMP = "20250301000000"  # fixed capture-artifact stamp (2025-03-01)


def _build_ext4_image(name: str, label: str, files: dict[str, str]) -> Path:
    """16MB ext4 image with exactly ``files``; inode times pinned."""
    img = BUILD_DIR / name
    img.parent.mkdir(parents=True, exist_ok=True)
    if img.exists():
        img.unlink()
    subprocess.run(
        ["dd", "if=/dev/zero", f"of={img}", "bs=1M", "count=16"],
        check=True, capture_output=True,
    )
    subprocess.run(
        ["mke2fs", "-q", "-t", "ext4", "-L", label, "-I", "256",
         "-b", "1024", str(img)],
        check=True, capture_output=True,
    )
    dirs = sorted(
        {str(Path(p).parent) for p in files if Path(p).parent != Path(".")}
    )
    for d in dirs:
        subprocess.run(
            ["debugfs", "-w", "-R", f"mkdir {d}", str(img)],
            check=True, capture_output=True,
        )
    staging = BUILD_DIR / (name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    for rel, content in files.items():
        src = staging / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(content, encoding="utf-8", newline="\n")
        subprocess.run(
            ["debugfs", "-w", "-R", f"write {src} {rel}", str(img)],
            check=True, capture_output=True,
        )
        for field in ("mtime", "ctime"):
            subprocess.run(
                ["debugfs", "-w", "-R",
                 f"set_inode_field /{rel} {field} {PINNED_STAMP}",
                 str(img)],
                check=True, capture_output=True,
            )
    shutil.rmtree(staging)
    return img


# ---------------------------------------------------------------------------
# Holdout Author stage (agent-visible semantics only)
# ---------------------------------------------------------------------------

DATASETS = {
    "gen4-layered-dispersion": {
        "README.txt": (
            "Seized personal laptop used to operate a remittance "
            "settlement account. The bank directory holds the exported "
            "transfer statement of the account; the chat directory "
            "holds a coordination group export; the notes directory "
            "holds a card allocation worksheet; the docs directory "
            "holds a rental agreement. Assess the records exactly as "
            "they are.\n"
        ),
        "bank/transfer-records.csv": (
            "txn_time,counterparty_account,counterparty_name,direction,"
            "amount_cny,remark\n"
            "2025-04-10 09:02:11,6222****4171,王建国,IN,200000.00,项目分红\n"
            "2025-04-10 09:11:05,6217****8834,李 梅,OUT,19800.00,周转\n"
            "2025-04-10 09:12:19,6217****9926,张 强,OUT,19500.00,周转\n"
            "2025-04-10 09:13:44,6228****0045,赵春花,OUT,19900.00,周转\n"
            "2025-04-10 09:15:02,6217****3312,孙德胜,OUT,19600.00,周转\n"
            "2025-04-10 09:17:38,6228****7741,钱 多,OUT,19200.00,周转\n"
            "2025-04-10 09:20:55,6217****5560,吴爱华,OUT,19800.00,周转\n"
            "2025-04-10 09:24:10,6222****8813,郑小龙,OUT,19400.00,周转\n"
            "2025-04-10 09:26:47,6217****0029,冯 玉,OUT,19700.00,周转\n"
            "2025-04-10 09:28:31,6228****6674,蒋成才,OUT,19950.00,周转\n"
            "2025-04-10 10:05:12,6222****7788,何 军,OUT,95000.00,归集\n"
            "2025-04-11 14:30:00,6222****1190,王秀兰,OUT,4500.00,4月房租\n"
        ),
        "chat/group-instructions.txt": (
            "2025-04-09 21:47 先锋-教练: 各位家人,明天上午有重要分红安排,"
            "保持在线\n"
            "2025-04-10 08:55 先锋-教练: 收到分红的家人注意:资金立即分散"
            "转出,每笔控制在2万以内,卡越多越好\n"
            "2025-04-10 08:56 先锋-教练: 不要用同一个银行,转完把截图发群里\n"
            "2025-04-10 10:12 先锋-教练: 剩余大头的部分等通知,统一归集到"
            "金卡\n"
            "2025-04-10 10:31 刘志强: 已分10笔转出,截图稍后补\n"
        ),
        "notes/card-worksheet.txt": (
            "卡片分配表(4月)\n"
            "1. 李梅 19800\n"
            "2. 张强 19500\n"
            "3. 赵春花 19900\n"
            "4. 孙德胜 19600\n"
            "5. 钱多 19200\n"
            "6. 吴爱华 19800\n"
            "7. 郑小龙 19400\n"
            "8. 冯玉 19700\n"
            "9. 蒋成才 19950\n"
            "10. (备用卡) 20000\n"
            "金卡(何军): 归集主卡,只进不出\n"
            "房租另算,不动这张表的钱\n"
        ),
        "docs/rental-agreement.txt": (
            "房屋租赁合同(节选)\n"
            "出租方: 王秀兰\n"
            "承租方: 刘志强\n"
            "月租金: 人民币4,500元整,每月11日前支付\n"
            "租期: 2024-11-12 至 2026-11-11\n"
        ),
    },
    "gen4-departure-staging": {
        "README.txt": (
            "Seized engineering workstation returned at offboarding. "
            "The logs directory holds the endpoint bulk-copy audit log; "
            "the policy directory holds the IT backup policy; the mail "
            "directory holds the approved backup ticket; the data "
            "directory holds an index of the managed client-data share; "
            "the hr directory holds the offboarding notice. Assess the "
            "records exactly as they are.\n"
        ),
        "logs/bulk-copy-audit.log": (
            "2025-05-16 21:30:02 EVENT sync-client SUSPENDED "
            "user=zhoukai reason=manual\n"
            "2025-05-16 21:32:11 BULKCOPY_START "
            "src=D:/projects/phoenix-client "
            "dst=E:/personal_backup/phoenix-client\n"
            "2025-05-16 21:47:40 progress src=D:/projects/phoenix-client "
            "files=612\n"
            "2025-05-16 22:03:05 BULKCOPY_START src=D:/clients "
            "dst=E:/personal_backup/clients\n"
            "2025-05-16 22:18:22 progress src=D:/clients files=214 "
            "(source complete)\n"
            "2025-05-16 22:31:57 progress src=D:/projects/phoenix-client "
            "files=1102\n"
            "2025-05-16 22:47:12 BULKCOPY_DONE copied_total=1847 "
            "(phoenix-client=1633, clients=214) duration=75m01s\n"
            "2025-05-16 22:50:11 EVENT sync-client RESUMED "
            "user=zhoukai reason=manual\n"
        ),
        "policy/it-backup-policy.txt": (
            "IT 资产与备份管理政策(节选,2024-12 修订)\n"
            "1. 员工可将本人名下的个人项目目录备份至个人移动存储介质。\n"
            "2. 客户数据目录(含 D:/clients 及其后代目录)属于受管数据:"
            "禁止复制至未经 IT 登记的设备;禁止通过个人渠道传输。\n"
            "3. 任何备份行为须经工单审批,批准范围以工单载明目录为准。\n"
        ),
        "mail/ticket-2025-0412.txt": (
            "工单 HD-2025-0412\n"
            "申请人: 周凯 (研发部)\n"
            "申请内容: 将 D:/projects/phoenix-client(本人个人项目目录)"
            "备份至个人移动硬盘\n"
            "IT 批复: 同意。批准范围仅限 D:/projects/phoenix-client 目录"
            "本身,不含其他目录。\n"
            "批复时间: 2025-04-12\n"
        ),
        "data/clients-index.txt": (
            "D:/clients 受管客户档案索引(节选)\n"
            "clients/C-1001/合同-华信贸易.docx\n"
            "clients/C-1002/对账单-宏远物流.xlsx\n"
            "clients/C-1003/方案书-蓝湾酒店.pptx\n"
            "(共 214 个文件,完整清单存于受管存储)\n"
            "备注: 该目录内容为未公开客户商务数据\n"
        ),
        "hr/offboard-notice.txt": (
            "离职交接通知\n"
            "姓名: 周凯\n"
            "最后工作日: 2025-05-23\n"
            "工作站交回: 2025-05-23 17:00,IT 验收\n"
        ),
    },
}

PUBLIC_CASES = {
    "gen4-layered-dispersion": {
        "case_id": "gen4-layered-dispersion",
        "case_family": "fund_flow_layering",
        "goal": (
            "Reconstruct from the transfer statement the fund operation "
            "pattern that followed the 2025-04-10 inflow; identify "
            "which recorded transfer is structurally different from "
            "that pattern and on what recorded basis; and state "
            "exactly what the records do and do not establish about "
            "the origin and nature of the funds."
        ),
        "case_context": (
            "A seized personal laptop used to operate a remittance "
            "settlement account. The bank directory holds the exported "
            "statement of the account; the chat directory holds a "
            "coordination group export; the notes directory holds a "
            "card allocation worksheet; the docs directory holds a "
            "rental agreement. Assess the records exactly as they are."
        ),
        "charter": [
            {
                "question_id": "q-1",
                "text": (
                    "依据转账流水,2025-04-10 09:02 资金流入后该账户当日"
                    "发生了怎样的转出操作?请仅依据记录给出事实描述:流入"
                    "金额、分散转出的笔数、对象账户数量、单笔金额范围、"
                    "时间跨度,以及其后的大额转出。"
                ),
            },
            {
                "question_id": "q-2",
                "text": (
                    "流水中哪一笔转出与上述操作模式在记录特征上不同?"
                    "其用途的记录依据是什么?"
                ),
            },
            {
                "question_id": "q-3",
                "text": (
                    "这些记录能否证明流入资金的违法犯罪来源,或持有人对"
                    "资金性质的明知?请精确说明记录能确立与不能确立的边界。"
                ),
            },
        ],
        "required_coverage_dimensions": [
            "inflow-dispersion-pattern",
            "benign-transfer-discrimination",
            "source-and-intent-boundary",
        ],
        "coverage_question_links": [
            {
                "dimension_id": "inflow-dispersion-pattern",
                "related_question_ids": ["q-1"],
            },
            {
                "dimension_id": "benign-transfer-discrimination",
                "related_question_ids": ["q-2"],
            },
            {
                "dimension_id": "source-and-intent-boundary",
                "related_question_ids": ["q-3"],
            },
        ],
        "negative_risk_context": [],
    },
    "gen4-departure-staging": {
        "case_id": "gen4-departure-staging",
        "case_family": "bulk_staging_discrimination",
        "goal": (
            "Establish from the endpoint audit log what bulk file "
            "operation occurred on 2025-05-16 and its exact scope; "
            "assess that operation against the frozen authorization "
            "records; and state exactly what the records do and do not "
            "establish about any transfer of the copied data to third "
            "parties."
        ),
        "case_context": (
            "A seized engineering workstation returned at offboarding. "
            "The logs directory holds the endpoint bulk-copy audit log; "
            "the policy directory holds the IT backup policy; the mail "
            "directory holds the approved backup ticket; the data "
            "directory holds an index of the managed client-data "
            "share; the hr directory holds the offboarding notice. "
            "Assess the records exactly as they are."
        ),
        "charter": [
            {
                "question_id": "q-1",
                "text": (
                    "依据审计日志,2025-05-16 晚间该工作站发生了什么批量"
                    "文件操作?请仅依据记录给出事实描述:操作时间窗、涉及"
                    "的源目录、目标位置、文件规模,以及云盘同步客户端的"
                    "状态变化。"
                ),
            },
            {
                "question_id": "q-2",
                "text": (
                    "该操作与已批准的备份授权(工单与政策)相对照,哪些部分"
                    "在授权范围内,哪些部分超出了授权范围?依据是什么?"
                ),
            },
            {
                "question_id": "q-3",
                "text": (
                    "这些记录能否证明被复制的客户数据已被传输给第三方,或"
                    "已被用于离职后的用途?请精确说明记录能确立与不能确立"
                    "的边界。"
                ),
            },
        ],
        "required_coverage_dimensions": [
            "bulk-copy-timeline",
            "authorization-scope-assessment",
            "third-party-transfer-boundary",
        ],
        "coverage_question_links": [
            {
                "dimension_id": "bulk-copy-timeline",
                "related_question_ids": ["q-1"],
            },
            {
                "dimension_id": "authorization-scope-assessment",
                "related_question_ids": ["q-2"],
            },
            {
                "dimension_id": "third-party-transfer-boundary",
                "related_question_ids": ["q-3"],
            },
        ],
        "negative_risk_context": [],
    },
}


def _ev(tid, desc, key, crit, role, claims=(), notes=""):
    return {
        "truth_evidence_id": tid,
        "evidence_identity_description": desc,
        "expected_evidence_key": key,
        "criticality": crit,
        "parser_expectation": "reachable",
        "source_kind": "file",
        "semantic_role": role,
        "related_claim_ids": list(claims),
        "notes": notes,
    }


def _claim(cid, prop, status, ceiling, ev, semantic, shortcuts=(), notes=""):
    return {
        "claim_id": cid,
        "proposition": prop,
        "truth_status": status,
        "maximum_assertion_class": ceiling,
        "required_evidence_ids": list(ev),
        "acceptable_evidence_sets": [],
        "forbidden_evidence_shortcuts": list(shortcuts),
        "semantic_type": semantic,
        "notes": notes,
    }


def _q(qid, disp, acceptable, unacceptable, priority=0, notes=""):
    return {
        "question_id": qid,
        "text": f"charter {qid} (truth-side copy)",
        "expected_disposition": disp,
        "required_evidence_ids": [],
        "acceptable_answers": acceptable,
        "unacceptable_answers": unacceptable,
        "priority": priority,
        "notes": notes,
    }


def _dim(did, desc, ev, notes=""):
    return {
        "dimension_id": did,
        "description": desc,
        "expected_status": "covered",
        "requires_closure_basis": True,
        "required_evidence_ids": list(ev),
        "notes": notes,
    }


TRUTHS = {
    "gen4-layered-dispersion": {
        "manifest_id": "tman:gen4ld0000000000000000000",
        "case_id": "gen4-layered-dispersion",
        "case_version": "1",
        "critical_evidence": [
            _ev(
                "TE-1",
                "/bank/transfer-records.csv: statement of the settlement "
                "account — one 200,000.00 IN at 2025-04-10 09:02:11 from "
                "王建国 (remark 项目分红); ten OUT transfers 19,200.00–"
                "19,950.00 between 09:11:05 and 09:28:31 to ten distinct "
                "accounts (each remark 周转); one OUT 95,000.00 at 10:05:12 "
                "to 何军 (remark 归集); one OUT 4,500.00 on 2025-04-11 to "
                "王秀兰 (remark 4月房租)",
                "file:/bank/transfer-records.csv",
                "critical",
                "bank_transfer_statement",
                claims=["TC-1", "TC-2", "TC-4", "TC-5"],
            ),
        ],
        "supporting_evidence": [
            _ev(
                "TE-2",
                "/chat/group-instructions.txt: group export in which "
                "先锋-教练 instructs dispersion of incoming funds in "
                "increments under 20k across as many cards/banks as "
                "possible and later aggregation of the remainder to the "
                "金卡; 刘志强 reports ten transfers completed",
                "file:/chat/group-instructions.txt",
                "supporting",
                "coordination_group_export",
                claims=["TC-3", "TC-5"],
            ),
            _ev(
                "TE-3",
                "/notes/card-worksheet.txt: a card allocation worksheet "
                "listing nine named cards with matching amounts plus one "
                "reserved 20,000 card, a 金卡 (何军) marked aggregation-"
                "only, and a note that rent is settled outside this sheet",
                "file:/notes/card-worksheet.txt",
                "supporting",
                "allocation_worksheet",
                claims=["TC-5"],
            ),
            _ev(
                "TE-4",
                "/docs/rental-agreement.txt: lease between 王秀兰 "
                "(lessor) and 刘志强 (lessee), monthly rent 4,500 CNY due "
                "before the 11th, term 2024-11-12 to 2026-11-11",
                "file:/docs/rental-agreement.txt",
                "supporting",
                "rental_agreement",
                claims=["TC-4"],
            ),
            _ev(
                "TE-5",
                "/README.txt: neutral inventory of the four record sets",
                "file:/README.txt",
                "supporting",
                "inventory_readme",
            ),
        ],
        "irrelevant_evidence": [],
        "expected_questions": [
            _q(
                "q-1",
                "answered",
                [
                    "statement records a 200,000.00 inflow at 09:02:11; "
                    "between 09:11:05 and 09:28:31 (under 18 minutes) ten "
                    "outbound transfers of 19,200.00–19,950.00 to ten "
                    "distinct accounts, each remarked 周转; a 95,000.00 "
                    "outbound remarked 归集 at 10:05:12",
                ],
                [
                    "asserting the funds are crime proceeds as part of "
                    "the pattern description",
                    "inventing additional transfers not present in the "
                    "statement",
                ],
                priority=0,
            ),
            _q(
                "q-2",
                "answered",
                [
                    "the 4,500.00 transfer on 2025-04-11 to 王秀兰 marked "
                    "4月房租 is structurally different: single recurring "
                    "amount matching the rental agreement (monthly rent "
                    "4,500 due before the 11th), counterparty is the "
                    "lessor, timing follows the rent schedule rather than "
                    "the dispersion window",
                ],
                [
                    "treating the rent transfer as part of the dispersion "
                    "operation",
                ],
                priority=0,
            ),
            _q(
                "q-3",
                "answered",
                [
                    "the records establish the transfer pattern and the "
                    "coordination instructions, but do not establish the "
                    "origin of the inflow beyond the payer label 项目分红, "
                    "do not establish that the funds are crime proceeds, "
                    "and do not establish the holder's knowledge of any "
                    "illegality — source and intent are not established "
                    "by these records",
                ],
                [
                    "asserting the inflow is fraud/gambling/laundering "
                    "proceeds as fact",
                    "asserting 刘志强 committed or knew of money "
                    "laundering",
                ],
                priority=0,
                notes=(
                    "the pattern is observable fact; criminal source and "
                    "intent stay outside the record boundary"
                ),
            ),
        ],
        "confirmed_claims": [
            _claim(
                "TC-1",
                "The statement records a single 200,000.00 CNY inflow at "
                "2025-04-10 09:02:11 from account 6222****4171 (王建国) "
                "remarked 项目分红.",
                "confirmed", "FACT", ["TE-1"], "factual",
            ),
            _claim(
                "TC-2",
                "Between 09:11:05 and 09:28:31 on 2025-04-10 the account "
                "made ten outbound transfers of 19,200.00–19,950.00 CNY "
                "to ten distinct counterparty accounts, each remarked "
                "周转.",
                "confirmed", "FACT", ["TE-1"], "factual",
            ),
            _claim(
                "TC-3",
                "The group export contains instructions to disperse "
                "incoming funds in increments under 20,000 CNY across as "
                "many cards and banks as possible, and later to aggregate "
                "the remainder to the 金卡; 刘志强 reports ten transfers "
                "completed.",
                "confirmed", "FACT", ["TE-2"], "factual",
            ),
            _claim(
                "TC-4",
                "The 2025-04-11 outbound 4,500.00 CNY to 王秀兰 remarked "
                "4月房租 matches the rental agreement (monthly rent "
                "4,500 due before the 11th; lessor 王秀兰).",
                "confirmed", "FACT", ["TE-1", "TE-4"], "factual",
            ),
            _claim(
                "TC-5",
                "The ten transfers fall within the instructed dispersion "
                "parameters (each under 20,000, multiple cards), and the "
                "95,000.00 outbound to 何军 corresponds to the instructed "
                "aggregation step recorded for the 金卡.",
                "confirmed", "INFERENCE",
                ["TE-1", "TE-2", "TE-3"], "causal",
                notes="pattern consistency is inferential; it does not "
                "establish criminality",
            ),
            _claim(
                "TC-6",
                "The records do not identify the origin of the inflow "
                "beyond the payer label 项目分红, and contain no record "
                "establishing that the funds are crime proceeds or that "
                "the holder knew of any illegality.",
                "confirmed", "FACT", ["TE-1", "TE-2"],
                "factual",
            ),
        ],
        "acceptable_inferences": [],
        "unsupported_or_prohibited_overclaims": [
            _claim(
                "TP-1",
                "The 200,000.00 inflow is proceeds of fraud/gambling/"
                "laundering (asserting criminal source as fact).",
                "unsupported", None, [], "intent",
                notes="the statement's payer remark is not evidence of "
                "criminal origin",
            ),
            _claim(
                "TP-2",
                "刘志强 knew the funds were illegal and committed money "
                "laundering (asserting intent/crime as fact).",
                "unsupported", None, [], "intent",
            ),
            _claim(
                "TP-3",
                "The 4,500.00 rent transfer was part of the dispersion "
                "operation.",
                "unsupported", None, [], "factual",
                shortcuts=["TE-1"],
                notes="forbidden shortcut: using the statement without "
                "the rental-agreement corroboration",
            ),
            _claim(
                "TP-4",
                "Over 300,000 CNY of criminal funds moved through the "
                "account (aggregate criminalization including the rent "
                "and inflow as laundered proceeds).",
                "unsupported", None, [], "intent",
            ),
        ],
        "expected_relations": [],
        "expected_coverage": [
            _dim(
                "inflow-dispersion-pattern",
                "The inflow and the ten-transfer dispersion window are "
                "reconstructed from the statement with counts, amounts, "
                "accounts and timing.",
                ["TE-1"],
            ),
            _dim(
                "benign-transfer-discrimination",
                "The rent transfer is discriminated on record-based "
                "features corroborated by the rental agreement.",
                ["TE-1", "TE-4"],
            ),
            _dim(
                "source-and-intent-boundary",
                "A closure basis states exactly that criminal source and "
                "holder knowledge are not established by the records.",
                ["TE-1", "TE-2"],
                notes="refusal language on source/intent is required; "
                "the pattern itself may be stated as fact/inference",
            ),
        ],
        "known_ambiguities": [
            "counterparty account numbers are masked in the statement; "
            "identities beyond displayed names are not corroborated",
            "the chat references screenshots that are not present on "
            "the device",
        ],
        "unavailable_truth": [
            "no ground truth about the ultimate origin or onward movement "
            "of the aggregated funds beyond these records",
        ],
        "notes": (
            "Gen-4 fund_flow_layering family: multi-account dispersion "
            "topology with an aggregation endpoint and a benign rent "
            "counter-example; single-reviewer truth"
        ),
    },
    "gen4-departure-staging": {
        "manifest_id": "tman:gen4ds0000000000000000000",
        "case_id": "gen4-departure-staging",
        "case_version": "1",
        "critical_evidence": [
            _ev(
                "TE-1",
                "/logs/bulk-copy-audit.log: on 2025-05-16 the corporate "
                "sync client was manually suspended at 21:30:02; "
                "BULKCOPY_START 21:32:11 src=D:/projects/phoenix-client "
                "dst=E:/personal_backup/phoenix-client; second "
                "BULKCOPY_START 22:03:05 src=D:/clients dst=E:/"
                "personal_backup/clients; progress lines (612 / 214 "
                "complete / 1102); BULKCOPY_DONE 22:47:12 copied_total="
                "1847 (phoenix-client=1633, clients=214); sync client "
                "resumed 22:50:11",
                "file:/logs/bulk-copy-audit.log",
                "critical",
                "endpoint_bulk_copy_audit",
                claims=["ST-1", "ST-2", "ST-5"],
            ),
        ],
        "supporting_evidence": [
            _ev(
                "TE-2",
                "/policy/it-backup-policy.txt: IT policy — personal "
                "project directories may be backed up to personal media; "
                "client-data directories (D:/clients and descendants) are "
                "managed data and must not be copied to unregistered "
                "devices; all backups require ticket approval scoped to "
                "the directories named in the ticket",
                "file:/policy/it-backup-policy.txt",
                "supporting",
                "backup_policy",
                claims=["ST-4", "ST-5"],
            ),
            _ev(
                "TE-3",
                "/mail/ticket-2025-0412.txt: ticket HD-2025-0412 — 周凯 "
                "requested backup of D:/projects/phoenix-client to a "
                "personal drive; IT approved with scope limited to that "
                "directory only, excluding all other directories",
                "file:/mail/ticket-2025-0412.txt",
                "supporting",
                "approval_ticket",
                claims=["ST-3", "ST-5"],
            ),
            _ev(
                "TE-4",
                "/data/clients-index.txt: index of the managed client-"
                "data share D:/clients (214 files of unpublished client "
                "commercial data)",
                "file:/data/clients-index.txt",
                "supporting",
                "managed_share_index",
                claims=["ST-5"],
            ),
            _ev(
                "TE-5",
                "/hr/offboard-notice.txt: 周凯's last working day "
                "2025-05-23; workstation returned to IT 2025-05-23 17:00",
                "file:/hr/offboard-notice.txt",
                "supporting",
                "offboarding_notice",
                claims=["ST-6"],
            ),
            _ev(
                "TE-6",
                "/README.txt: neutral inventory of the five record sets",
                "file:/README.txt",
                "supporting",
                "inventory_readme",
            ),
        ],
        "irrelevant_evidence": [],
        "expected_questions": [
            _q(
                "q-1",
                "answered",
                [
                    "between 21:32:11 and 22:47:12 on 2025-05-16 a bulk "
                    "copy moved 1,847 files from D:/projects/phoenix-client"
                    " (1,633) and D:/clients (214) to E:/personal_backup; "
                    "the corporate sync client was manually suspended at "
                    "21:30:02 and resumed at 22:50:11",
                ],
                [
                    "asserting data reached a third party as part of the "
                    "timeline",
                    "asserting files were deleted or the workstation "
                    "wiped",
                ],
                priority=0,
            ),
            _q(
                "q-2",
                "answered",
                [
                    "the D:/projects/phoenix-client copy (1,633 files) "
                    "was within the approved ticket scope; the D:/clients "
                    "copy (214 files) exceeded authorization — the policy "
                    "prohibits copying the managed client share to "
                    "unregistered personal media and requires ticket-"
                    "scoped approval, and no record authorizes D:/clients",
                ],
                [
                    "treating the entire operation as unauthorized",
                    "treating the clients copy as authorized",
                ],
                priority=0,
            ),
            _q(
                "q-3",
                "answered",
                [
                    "the records do not establish any transfer of the "
                    "copied data to a third party, nor any post-departure "
                    "use: the recorded destination is a local disk path "
                    "on the workstation that was returned to IT on "
                    "2025-05-23; both remain unproven by these records",
                ],
                [
                    "asserting the client data was leaked to a competitor "
                    "or third party",
                    "asserting 周凯 used the data after departure",
                ],
                priority=0,
                notes="destination on the returned device bounds what the "
                "records can establish",
            ),
        ],
        "confirmed_claims": [
            _claim(
                "ST-1",
                "Between 21:32:11 and 22:47:12 on 2025-05-16 a bulk copy "
                "operation moved 1,847 files from D:/projects/phoenix-"
                "client (1,633 files) and D:/clients (214 files) to "
                "E:/personal_backup on the workstation.",
                "confirmed", "FACT", ["TE-1"], "factual",
            ),
            _claim(
                "ST-2",
                "The corporate cloud-sync client was manually suspended "
                "at 21:30:02 and manually resumed at 22:50:11 on "
                "2025-05-16, bracketing the bulk copy window.",
                "confirmed", "FACT", ["TE-1"], "factual",
            ),
            _claim(
                "ST-3",
                "Ticket HD-2025-0412 approved backing up only "
                "D:/projects/phoenix-client to a personal drive, "
                "expressly excluding all other directories.",
                "confirmed", "FACT", ["TE-3"], "factual",
            ),
            _claim(
                "ST-4",
                "The IT policy designates D:/clients and its descendants "
                "as managed client data that must not be copied to "
                "unregistered personal media, and requires ticket-scoped "
                "approval for backups.",
                "confirmed", "FACT", ["TE-2"], "factual",
            ),
            _claim(
                "ST-5",
                "The 214-file copy of D:/clients to the personal drive "
                "exceeded the granted backup authorization.",
                "confirmed", "INFERENCE",
                ["TE-1", "TE-2", "TE-3", "TE-4"],
                "causal",
                notes="inferential synthesis of log + policy + ticket + "
                "managed-share index",
            ),
            _claim(
                "ST-6",
                "周凯's last working day was 2025-05-23 and the "
                "workstation was returned to IT on that date — seven days "
                "after the copy operation.",
                "confirmed", "FACT", ["TE-5"], "temporal",
            ),
            _claim(
                "ST-7",
                "The records do not establish any transfer of the copied "
                "data to a third party or any post-departure use of it; "
                "the only recorded destination is a local disk path on "
                "the workstation returned to IT.",
                "confirmed", "FACT", ["TE-1"],
                "factual",
            ),
        ],
        "acceptable_inferences": [],
        "unsupported_or_prohibited_overclaims": [
            _claim(
                "TP-1",
                "周凯 stole company client data (asserting theft intent "
                "as fact).",
                "unsupported", None, [], "intent",
            ),
            _claim(
                "TP-2",
                "The client data was leaked to a third party or "
                "competitor.",
                "unsupported", None, [], "causal",
                notes="no third-party transfer appears in any record",
            ),
            _claim(
                "TP-3",
                "The entire backup operation was unauthorized.",
                "unsupported", None, [], "factual",
                shortcuts=["TE-3"],
                notes="forbidden shortcut: ignoring the approved ticket "
                "scope for phoenix-client",
            ),
            _claim(
                "TP-4",
                "周凯 used the data after leaving the company.",
                "unsupported", None, [], "temporal",
            ),
        ],
        "expected_relations": [],
        "expected_coverage": [
            _dim(
                "bulk-copy-timeline",
                "The bulk copy window, source trees, destination and "
                "scale are reconstructed from the audit log, including "
                "the sync-client state changes.",
                ["TE-1"],
            ),
            _dim(
                "authorization-scope-assessment",
                "The operation is assessed against the policy and ticket: "
                "phoenix-client in scope, clients out of scope.",
                ["TE-1", "TE-2", "TE-3"],
            ),
            _dim(
                "third-party-transfer-boundary",
                "A closure basis states exactly that third-party transfer "
                "and post-departure use are not established by the "
                "records.",
                ["TE-1"],
                notes="refusal language on exfiltration/intent is "
                "required",
            ),
        ],
        "known_ambiguities": [
            "the audit log's totals are the endpoint's own accounting; "
            "no independent inventory of E:/personal_backup exists on "
            "the returned image",
            "whether E:/personal_backup remained on the device at return "
            "is not recorded",
        ],
        "unavailable_truth": [
            "no ground truth about any movement of the copied files off "
            "the workstation beyond these records",
        ],
        "notes": (
            "Gen-4 bulk_staging_discrimination family: the question set "
            "deliberately excludes attribution (who) and asks what "
            "operation, against what authorization, with what record "
            "boundary; single-reviewer truth"
        ),
    },
}


def main() -> int:
    from httpserver.services.benchmarks.holdout_contract import (
        PublicHoldoutCaseV2,
        verify_truth_public_isolation,
    )
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        SealedEvidenceManifestV1,
        SealedEvidenceSubstrateV1,
        compute_evidence_world_digest,
        parser_config_hash,
        provision_and_digest,
    )
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )
    from httpserver.services.investigation.agent_attention import (
        AttentionBuilder,
    )
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )
    from httpserver.services.benchmarks.holdout_contract import (
        build_holdout_working_state,
    )

    cases_dir = GEN4_ROOT / "cases"
    truth_dir = GEN4_ROOT / "truth"
    substrates_dir = GEN4_ROOT / "substrates"
    images_dir = IMAGES_DIR
    for d in (cases_dir, truth_dir, substrates_dir, images_dir):
        d.mkdir(parents=True, exist_ok=True)

    profiles_hash = parser_config_hash(
        REPO_ROOT / "config" / "filter_profiles"
    )

    validation_rows = []
    all_ok = True
    for case_id, files in DATASETS.items():
        dataset_dir = cases_dir / case_id / "dataset"
        for rel, content in files.items():
            target = dataset_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        assets = [
            {
                "logical_id": rel.replace("/", "-").replace(".", "-").upper(),
                "relative_path": rel,
                "sha256": hashlib.sha256(
                    (dataset_dir / rel).read_bytes()
                ).hexdigest(),
            }
            for rel in files
        ]
        public_case = PublicHoldoutCaseV2(
            **{**PUBLIC_CASES[case_id], "public_assets": assets}
        )
        (cases_dir / f"{case_id}.public-case.json").write_text(
            public_case.model_dump_json(indent=1), encoding="utf-8"
        )

        truth = TruthManifestV1(
            **{**TRUTHS[case_id], "created_at": CREATED_AT}
        )
        (truth_dir / f"{case_id}.truth.json").write_text(
            truth.model_dump_json(indent=1), encoding="utf-8"
        )
        all_truth_items = list(truth.critical_evidence) + list(
            truth.supporting_evidence
        ) + list(truth.irrelevant_evidence)
        reach = ReachabilityManifestV1(
            case_id=case_id,
            records=[
                {
                    "truth_evidence_id": item.truth_evidence_id,
                    "resolved_evidence_keys": [item.expected_evidence_key],
                    "parser_reachable": True,
                    "agent_discoverable": True,
                    "status": "resolved",
                    "unavailable_reason": "",
                }
                for item in all_truth_items
            ],
            created_at=CREATED_AT,
        )
        (truth_dir / f"{case_id}.reachability.json").write_text(
            reach.model_dump_json(indent=1), encoding="utf-8"
        )

        img = _build_ext4_image(
            f"{case_id}.img", "gen4fs", files
        )
        shutil.copyfile(img, images_dir / img.name)
        image_sha = hashlib.sha256(
            (images_dir / img.name).read_bytes()
        ).hexdigest()

        worlds = []
        for rep in range(2):
            worlds.append(
                provision_and_digest(
                    images_dir / img.name,
                    label=f"gen4-construction-{case_id}-{rep}",
                )
            )
        reproducible = worlds[0]["digest"] == worlds[1]["digest"]
        world = worlds[0]
        payload = world["payload"]

        categories = {
            row["path"]: row["category"]
            for row in payload["files_rows"]
        }
        sizes = {
            row["path"]: row["size"] for row in payload["files_rows"]
        }
        asset_by_rel = {a["relative_path"]: a for a in assets}
        entries = []
        for row in sorted(payload["files_rows"], key=lambda r: r["path"]):
            if row["is_deleted"]:
                continue
            rel = row["path"].lstrip("/")
            entries.append(
                {
                    "normalized_path": row["path"],
                    "size_bytes": sizes[row["path"]],
                    "sha256": asset_by_rel[rel]["sha256"],
                    "expected_evidence_key": f"file:/{rel}",
                    "category": categories.get(row["path"], ""),
                }
            )
        manifest = SealedEvidenceManifestV1(case_id=case_id, entries=entries)

        checks = {
            "provisioning_reproducible": reproducible,
            "expected_keys_match_assets": (
                set(payload["evidence_keys"])
                == {f"file:/{rel}" for rel in files}
            ),
            "indexed_world_matches_asset_set": (
                {row["path"] for row in payload["files_rows"]
                 if not row["is_deleted"]}
                == {f"/{rel}" for rel in files}
            ),
            "indexed_sizes_match_public_assets": all(
                sizes.get(f"/{rel}") == len(content.encode("utf-8"))
                for rel, content in files.items()
            ),
            "truth_public_separation_clean": not (
                verify_truth_public_isolation(public_case, truth)
            ),
        }

        state = build_holdout_working_state(
            public_case, task_id="t", investigation_id="i"
        )
        attention = AttentionBuilder().build_full_set(
            state, state_revision=1
        )
        item_ids = [i.item_id for i in attention.items]
        checks["attention_no_standalone_coverage"] = not any(
            i.startswith("coverage:") for i in item_ids
        )
        delegable_refs = []
        for item in attention.items:
            if any(
                a.value in ("delegate_source", "delegate_investigation")
                for a in getattr(item, "eligible_action_types", ())
            ):
                refs = tuple(
                    getattr(item, "related_question_ids", ()) or ()
                )
                delegable_refs.extend(refs or (item.item_id,))
        checks["attention_no_duplicate_topology"] = len(
            delegable_refs
        ) == len(set(delegable_refs))

        ok = all(checks.values())
        all_ok &= ok
        validation_rows.append(
            {
                "case_id": case_id,
                "case_family": public_case.case_family,
                "public_input_hash": public_case.input_hash,
                "truth_input_hash": truth.input_hash,
                "image_sha256": image_sha,
                "image_size_bytes": (images_dir / img.name).stat().st_size,
                "evidence_world_digest": world["digest"],
                "provision_digests": [w["digest"] for w in worlds],
                "evidence_keys": payload["evidence_keys"],
                "manifest_input_hash": manifest.input_hash,
                "sealed_content_hashes": {
                    e["expected_evidence_key"]: e["sha256"]
                    for e in entries
                },
                "checks": checks,
                "ok": ok,
            }
        )
        print(f"{case_id:28s} {'PASS' if ok else 'FAIL'} "
              f"| world={world['digest'][:12]}…")

        (substrates_dir / f"{case_id}.evidence-manifest.json").write_text(
            manifest.model_dump_json(indent=1), encoding="utf-8"
        )
        (substrates_dir / f"{case_id}.evidence-world.json").write_text(
            json.dumps(
                {"digest": world["digest"],
                 "provision_digests": [w["digest"] for w in worlds]},
                indent=1,
            ),
            encoding="utf-8",
        )
        substrate = SealedEvidenceSubstrateV1(
            substrate_id=f"sub-{case_id}",
            case_id=case_id,
            image_relative_path=img.name,
            image_sha256=image_sha,
            image_size_bytes=(images_dir / img.name).stat().st_size,
            expected_public_asset_manifest_hash=public_case.input_hash,
            parser_config_hash=profiles_hash,
            expected_evidence_manifest_hash=manifest.input_hash,
        )
        (substrates_dir / f"{case_id}.substrate.json").write_text(
            substrate.model_dump_json(indent=1), encoding="utf-8"
        )

    validation = {
        "artifact_version": "EvidenceWorldValidationV1",
        "generation_id": "acceptance-generation-4",
        "created_at": CREATED_AT,
        "zero_model_calls": True,
        "provisioning_repetitions": 2,
        "cases": validation_rows,
        "all_passed": all_ok,
        "input_hash": "",
    }
    validation["input_hash"] = state_hash_of(
        canonical_state_json(
            {k: v for k, v in validation.items() if k != "input_hash"}
        )
    )
    (GEN4_ROOT / "evidence-world-validation-v1.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    record = {
        "artifact_version": "Gen4ConstructionRecordV1",
        "generation_id": "acceptance-generation-4",
        "created_at": CREATED_AT,
        "capability_selection_record": (
            "capability-selection-record-v1.json (created BEFORE any "
            "case content, §8)"
        ),
        "role_stages": [
            {"role": "Holdout Author",
             "produced": ["cases/*.public-case.json",
                          "cases/*/dataset/*"]},
            {"role": "Truth Author",
             "produced": ["truth/*.truth.json",
                          "truth/*.reachability.json"]},
            {"role": "Evidence Substrate Builder",
             "produced": ["images/*.img (per-case ext4, pinned inode "
                          "times, contains EXACTLY the public asset "
                          "set — no generic demo content)"]},
            {"role": "Protocol Validator",
             "produced": ["substrates/*.evidence-manifest.json (per-file "
                          "content sha256 sealed, §12)",
                          "substrates/*.substrate.json",
                          "substrates/*.evidence-world.json",
                          "evidence-world-validation-v1.json "
                          "(real provisioning x2, zero model calls)"]},
            {"role": "Hydration Preseal Validator",
             "produced": ["validate_gen4_hydration.py outputs (§14-§17, "
                          "production content read path, restart proof) — "
                          "separate step"]},
            {"role": "Acceptance Executor",
             "produced": ["HoldoutSealV3 + admission audit (separate "
                          "scripts); execution NOT in this phase"]},
        ],
        "design_basis": "product capability families only (fund flow "
        "layering; bulk staging discrimination) per "
        "capability-selection-record-v1; new actors/filenames/timelines/"
        "hashes; not designed around any model's weaknesses nor from any "
        "consumed generation's answers",
    }
    (GEN4_ROOT / "construction-record-v1.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("validation -> evidence-world-validation-v1.json")
    print("ALL PASS" if all_ok else "CONSTRUCTION VALIDATION FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
