#!/usr/bin/env python3
"""P8B B3.5 §9-§12 corpus v5 authoring.

Builds the four new calibration cases (C4/C7/C8/C9) and two sealed
holdout cases as purpose-built minimal ext4 images + full case
packages (case.json / truth_manifest.json / reachability.json /
dataset_manifest.json).  All manifests are hash-bound via the frozen
Pydantic contracts.  Holdout cases are authored and frozen but NEVER
executed (§12).

Usage (from python_service/):
    .venv/bin/python scripts/author_corpus_v5.py
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

IMAGES_DIR = PYTHON_SERVICE_ROOT / "benchmarks" / "images"
CASES_ROOT = PYTHON_SERVICE_ROOT / "benchmarks" / "cases"
BUILD_DIR = PYTHON_SERVICE_ROOT / "build" / "data" / "benchimages-v5"


def _img_build(name: str, label: str, files: dict[str, str]) -> Path:
    """Create a 16MB ext4 image with the given files (path -> content)."""
    img = BUILD_DIR / name
    img.parent.mkdir(parents=True, exist_ok=True)
    if img.exists():
        img.unlink()
    subprocess.run(
        ["dd", "if=/dev/zero", f"of={img}", "bs=1M", "count=16"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["mke2fs", "-q", "-t", "ext4", "-L", label, "-I", "256",
         "-b", "1024", str(img)],
        check=True,
        capture_output=True,
    )
    dirs = sorted(
        {str(Path(p).parent) for p in files if Path(p).parent != Path(".") and str(Path(p).parent) != "/"}
    )
    for d in dirs:
        subprocess.run(
            ["debugfs", "-w", "-R", f"mkdir {d}", str(img)],
            check=True, capture_output=True,
        )
    # nested dirs need parents first — mkdir deepest-last handled by sorted()
    staging = BUILD_DIR / (name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    for rel, content in files.items():
        src = staging / rel
        src.parent.mkdir(parents=True, exist_ok=True)
        src.write_text(content, encoding="utf-8")
        subprocess.run(
            ["debugfs", "-w", "-R", f"write {src} {rel}", str(img)],
            check=True, capture_output=True,
        )
    return img


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_case(case: dict, truth_payload: dict, reach_records: list[dict],
                files: dict[str, str], img: Path) -> None:
    from httpserver.services.benchmarks.benchmark_case import (
        BenchmarkCaseV1,
        DatasetManifestV1,
    )
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )

    case_id = case["case_id"]
    case_dir = CASES_ROOT / case_id
    dataset_dir = case_dir / "dataset"
    if dataset_dir.exists():
        shutil.rmtree(dataset_dir)
    for rel, content in files.items():
        dst = dataset_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(content, encoding="utf-8")

    truth = TruthManifestV1(**truth_payload)
    (case_dir / "truth_manifest.json").write_text(
        truth.model_dump_json(indent=2), encoding="utf-8"
    )
    reach = ReachabilityManifestV1(
        case_id=case_id, records=reach_records
    )
    (case_dir / "reachability.json").write_text(
        reach.model_dump_json(indent=2), encoding="utf-8"
    )
    file_refs = [
        {
            "logical_id": Path(rel).stem.replace("_", "-"),
            "relative_path": rel,
            "size_bytes": len(content.encode("utf-8")),
            "sha256": _sha(content),
        }
        for rel, content in sorted(files.items())
    ]
    case_payload = dict(case)
    case_payload["dataset"] = {
        "dataset_id": f"ds-{case_id}",
        "files": file_refs,
    }
    case_payload["truth_manifest_id"] = truth.manifest_id
    case_payload["truth_manifest_hash"] = truth.input_hash
    benchmark_case = BenchmarkCaseV1(**case_payload)
    (case_dir / "case.json").write_text(
        benchmark_case.model_dump_json(indent=2), encoding="utf-8"
    )
    dataset = DatasetManifestV1(
        dataset_id=f"ds-{case_id}", files=file_refs
    )
    (case_dir / "dataset_manifest.json").write_text(
        dataset.model_dump_json(indent=2), encoding="utf-8"
    )
    shutil.copyfile(img, IMAGES_DIR / img.name)
    print(
        f"{case_id}: case={benchmark_case.input_hash[:12]} "
        f"truth={truth.input_hash[:12]} reach={len(reach_records)}"
    )


# ---------------------------------------------------------------------------
# case definitions
# ---------------------------------------------------------------------------

def case_c4_misleading_note() -> None:
    case_id = "t2-misleading-note"
    files = {
        "export/app.log": (
            "2024-05-09 23:55:01 SCHEDULE job=nightly_export account=svc_export triggered\n"
            "2024-05-10 01:03:22 EXPORT account=svc_export dataset=customers rows=184112 dest=/backup/customers_20240510.tar.gz\n"
            "2024-05-10 01:03:40 EXPORT account=svc_export status=success duration=18s\n"
            "2024-05-10 01:47:11 LOGIN account=lihua ip=198.51.100.44 result=FAILED reason=password\n"
            "2024-05-10 01:47:59 LOGIN account=lihua ip=198.51.100.44 result=FAILED reason=password\n"
        ),
        "scheduler/jobs.conf": (
            "# nightly customer export\n"
            "job nightly_export {\n"
            "  schedule 23:55 daily\n"
            "  run_as svc_export\n"
            "  task export_customers\n"
            "}\n"
        ),
        "README.txt": (
            "Seized application server. The export directory holds the "
            "application log; the scheduler directory holds the job "
            "definition. svc_export is a dedicated non-interactive "
            "service account used by scheduled jobs."
        ),
    }
    truth = {
        "case_id": case_id,
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": "/export/app.log: the customer-database export was executed by service account svc_export under the nightly scheduled job; lihua's only recorded activity is two FAILED logins.",
                "expected_evidence_key": "file:/export/app.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "export_audit_log",
                "related_claim_ids": ["TC-1", "TC-2"],
            }
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": "/scheduler/jobs.conf: the nightly_export job is configured to run as svc_export, corroborating the log.",
                "expected_evidence_key": "file:/scheduler/jobs.conf",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "semantic_role": "job_definition",
                "related_claim_ids": ["TC-1"],
            },
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": "/README.txt: context note identifying svc_export as a dedicated non-interactive service account.",
                "expected_evidence_key": "file:/README.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "semantic_role": "context_note",
                "related_claim_ids": ["TC-1", "TC-2"],
            },
        ],
        "expected_questions": [
            {
                "question_id": "TQ-1",
                "text": "An analyst hypothesized that employee lihua exported the customer database on 2024-05-10. Does the evidence support, refute, or leave open this attribution?",
                "expected_disposition": "answered",
                "required_evidence_ids": ["TE-1"],
                "priority": 0,
            }
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": "The customer-database export was executed by service account svc_export under the scheduled nightly_export job.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-2",
                "proposition": "lihua's involvement in the export is not supported by the recorded evidence; the only lihua activity is two failed login attempts.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
                "required_evidence_ids": ["TE-1"],
                "semantic_type": "actor_attribution",
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": "lihua exported the customer database.",
                "truth_status": "unsupported",
                "semantic_type": "actor_attribution",
                "forbidden_evidence_shortcuts": ["TE-1"],
            },
            {
                "claim_id": "TP-2",
                "proposition": "The failed logins prove lihua attempted to access the exported data.",
                "truth_status": "unsupported",
                "semantic_type": "intent",
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "export-attribution",
                "description": "The export's executor is established and the analyst hypothesis is corrected against the evidence.",
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1", "TE-2"],
            }
        ],
        "notes": "C4 misleading-analyst-note case: the seed question carries a WRONG analyst hypothesis (actor attribution); the evidence refutes it. The agent must not adopt the note's claim. Single-reviewer truth.",
    }
    reach = [
        {"truth_evidence_id": "TE-1", "resolved_evidence_keys": ["file:/export/app.log"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
        {"truth_evidence_id": "TE-2", "resolved_evidence_keys": ["file:/scheduler/jobs.conf"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
        {"truth_evidence_id": "TE-3", "resolved_evidence_keys": ["file:/README.txt"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
    ]
    img = _img_build("t2-misleading-note.img", "notefs", files)
    _write_case(
        {
            "case_id": case_id,
            "case_version": "1",
            "title": "T2 misleading analyst note: wrong actor attribution (notefs)",
            "goal": "Establish who executed the 2024-05-10 customer-database export, and evaluate the analyst's hypothesis against the recorded evidence.",
            "case_context": "A seized application server. An analyst note hypothesizes employee lihua exported the customer database. Verify the hypothesis against the evidence and state exactly what is supported.",
            "platform_composition": ["linux"],
            "tier": "T2",
            "negative_flags": {
                "incorrect_analyst_hypothesis": True,
                "misleading_case_context": True,
            },
            "expected_parser_profile": "linux",
            "benchmark_tags": ["misleading-note", "actor-attribution", "t2"],
        },
        truth,
        reach,
        files,
        img,
    )


def case_c7_correlation() -> None:
    case_id = "t2-cross-source-correlation"
    files = {
        "crm/orders.csv": (
            "order_id,buyer,amount_usdt,status\n"
            "ORD-70231,wangqiang,20000,paid\n"
            "ORD-70232,zhaolei,15000,paid\n"
            "ORD-70233,sunli,31500,paid\n"
            "ORD-70234,qianer,8000,cancelled\n"
        ),
        "payments/settlements.log": (
            "2024-06-01 settle order=ORD-70231 wallet=TXabc111 amount=20000 ok\n"
            "2024-06-01 settle order=ORD-70232 wallet=TXdef222 amount=15000 ok\n"
            "2024-06-02 settle order=ORD-70233 wallet=TXghi333 amount=31500 ok\n"
            "2024-06-02 settle order=ORD-72033 wallet=TXjkl444 amount=9999 ok\n"
        ),
        "README.txt": (
            "Seived merchant server. The CRM directory holds the order "
            "table; the payments directory holds the settlement log from "
            "the payment processor. Settlements reference CRM order ids "
            "verbatim. A settlement whose order id does not exist in the "
            "CRM table cannot be treated as the same order."
        ),
    }
    truth = {
        "case_id": case_id,
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": "/crm/orders.csv: three paid orders (ORD-70231/70232/70233) with buyer names and USDT amounts; ORD-70234 is cancelled.",
                "expected_evidence_key": "file:/crm/orders.csv",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "order_table",
                "related_claim_ids": ["TC-1", "TC-3"],
            },
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": "/payments/settlements.log: settlements matching ORD-70231/70232/70233 by exact order id, plus a distractor settlement order=ORD-72033 (digit-transposed, no CRM match).",
                "expected_evidence_key": "file:/payments/settlements.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "settlement_log",
                "related_claim_ids": ["TC-1", "TC-2", "TC-3"],
            },
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": "/README.txt: settlements reference CRM order ids verbatim; unmatched ids are not the same order.",
                "expected_evidence_key": "file:/README.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "semantic_role": "context_note",
                "related_claim_ids": ["TC-2"],
            },
        ],
        "expected_questions": [
            {
                "question_id": "TQ-1",
                "text": "Which paid CRM orders are confirmed by the payment processor's settlement log, and by what linkage?",
                "expected_disposition": "answered",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "priority": 0,
            },
            {
                "question_id": "TQ-2",
                "text": "The settlement log contains order=ORD-72033. Is that the same order as CRM ORD-70233?",
                "expected_disposition": "unresolved",
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
                "unacceptable_answers": ["asserting ORD-72033 is ORD-70233"],
                "priority": 0,
            },
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": "CRM orders ORD-70231, ORD-70232 and ORD-70233 are each settled in the payments log by exact order-id match, for the same USDT amounts.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-2",
                "proposition": "Settlement order=ORD-72033 has no exact match in the CRM order table and must not be treated as ORD-70233.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
                "semantic_type": "identity_merge",
            },
            {
                "claim_id": "TC-3",
                "proposition": "CRM order ORD-70234 is cancelled and has no settlement in the log.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "semantic_type": "factual",
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": "Settlement ORD-72033 is a typo for ORD-70233 and represents the same transaction.",
                "truth_status": "unsupported",
                "semantic_type": "identity_merge",
            },
        ],
        "expected_relations": [
            {
                "relation_id": "TR-1",
                "subject_entity": "ORD-70233@crm",
                "relation_family": "identity",
                "object_entity": "ORD-70233@payments",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "expected_evidence_ids": ["TE-1", "TE-2"],
                "identity_merge_allowed": True,
            },
            {
                "relation_id": "TR-2",
                "subject_entity": "ORD-70233@crm",
                "relation_family": "identity",
                "object_entity": "ORD-72033@payments",
                "truth_status": "unsupported",
                "identity_merge_allowed": False,
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "cross-source-settlement",
                "description": "Cross-source order-to-settlement linkage is established by exact-id match, and the near-miss id is kept separate.",
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1", "TE-2"],
            }
        ],
        "notes": "C7 multi-source correlation case: two systems linked by a shared unique identifier; includes a digit-transposed near-miss id that must NOT be merged. Single-reviewer truth.",
    }
    reach = [
        {"truth_evidence_id": "TE-1", "resolved_evidence_keys": ["file:/crm/orders.csv"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
        {"truth_evidence_id": "TE-2", "resolved_evidence_keys": ["file:/payments/settlements.log"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
        {"truth_evidence_id": "TE-3", "resolved_evidence_keys": ["file:/README.txt"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
    ]
    img = _img_build("t2-cross-source.img", "corrlfs", files)
    _write_case(
        {
            "case_id": case_id,
            "case_version": "1",
            "title": "T2 multi-source correlation: order-settlement linkage (corrlfs)",
            "goal": "Determine which CRM orders are confirmed by the payment processor's settlement log, and which log entries must stay separate.",
            "case_context": "A seized merchant server holding a CRM order table and a payment processor's settlement log. Settlements reference CRM order ids verbatim.",
            "platform_composition": ["linux"],
            "tier": "T2",
            "negative_flags": {"ambiguous_evidence": True},
            "expected_parser_profile": "linux",
            "benchmark_tags": ["multi-source", "correlation", "identity-trap", "t2"],
        },
        truth,
        reach,
        files,
        img,
    )


def case_c8_verification() -> None:
    case_id = "t2-verification-temptation"
    files = {
        "chat/account_main.log": (
            "[2024-07-03 22:14] me: 说实话这个盘我就是总操盘，钱都过我手\n"
            "[2024-07-03 22:16] me: 群里那帮人只管拉人，账我来平\n"
            "[2024-07-05 09:02] me: 最近风控严，先停几天\n"
        ),
        "ledger/flows.txt": (
            "2024-07-01 in 40000 USDT wallet-A\n"
            "2024-07-02 out 39000 USDT wallet-B\n"
            "2024-07-05 out 950 USDT wallet-C\n"
        ),
        "README.txt": (
            "Seized phone. The chat log is the device owner's own account. "
            "A self-descriptive boast in a chat is a statement that the "
            "statement was made; it is not independent proof of the role. "
            "No corroborating identity or operational data links the "
            "owner to the ledger flows."
        ),
    }
    truth = {
        "case_id": case_id,
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": "/chat/account_main.log: the device owner's account posted messages claiming to be the overall operator who balances the money.",
                "expected_evidence_key": "file:/chat/account_main.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "self_description",
                "related_claim_ids": ["TC-1", "AI-1"],
            },
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": "/ledger/flows.txt: USDT flows in/out of three wallets; no owner identity appears.",
                "expected_evidence_key": "file:/ledger/flows.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "semantic_role": "flow_ledger",
                "related_claim_ids": ["AI-1"],
            },
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": "/README.txt: the boast caveat — a self-description is a statement about the statement, not independent proof of the role; no corroborating link exists.",
                "expected_evidence_key": "file:/README.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "semantic_role": "context_note",
                "related_claim_ids": ["AI-1", "TC-2"],
            },
        ],
        "expected_questions": [
            {
                "question_id": "TQ-1",
                "text": "What did the device owner's account say, and at what assertion strength can the owner's actual role be stated?",
                "expected_disposition": "answered",
                "required_evidence_ids": ["TE-1", "TE-3"],
                "priority": 0,
            }
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": "The device owner's account posted messages claiming to be the overall operator of the scheme who personally balances the money.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-2",
                "proposition": "The ledger shows USDT flows through three wallets with no owner identity attached; nothing in the volume corroborates or contradicts the boast.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-2"],
                "semantic_type": "factual",
            },
        ],
        "acceptable_inferences": [
            {
                "claim_id": "AI-1",
                "proposition": "The owner may have been involved in operating the scheme, per the self-description; independent corroboration is absent.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "HYPOTHESIS",
                "required_evidence_ids": ["TE-1", "TE-3"],
                "semantic_type": "actor_attribution",
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": "The device owner operated the laundering scheme (stated as fact).",
                "truth_status": "unsupported",
                "semantic_type": "actor_attribution",
            },
            {
                "claim_id": "TP-2",
                "proposition": "The ledger flows are the owner's laundering proceeds (stated as fact).",
                "truth_status": "unsupported",
                "semantic_type": "causal",
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "assertion-strength",
                "description": "The self-description is reported as a statement; the owner's role stays at hypothesis ceiling with the corroboration gap stated.",
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1", "TE-3"],
            }
        ],
        "known_ambiguities": [
            "the boast may be true, exaggerated, or false; only its existence is factual"
        ],
        "notes": "C8 high-risk semantic verification case: the tempting conclusion (owner ran the scheme) is exactly one assertion class above the evidence ceiling; the SemanticVerifier's assertion-ceiling discipline is what this case measures. Single-reviewer truth.",
    }
    reach = [
        {"truth_evidence_id": "TE-1", "resolved_evidence_keys": ["file:/chat/account_main.log"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
        {"truth_evidence_id": "TE-2", "resolved_evidence_keys": ["file:/ledger/flows.txt"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
        {"truth_evidence_id": "TE-3", "resolved_evidence_keys": ["file:/README.txt"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
    ]
    img = _img_build("t2-verify-temptation.img", "veriffs", files)
    _write_case(
        {
            "case_id": case_id,
            "case_version": "1",
            "title": "T2 verification temptation: boast vs proof (veriffs)",
            "goal": "Report what the device owner's account stated, and state the owner's actual role at exactly the assertion strength the evidence supports.",
            "case_context": "A seized phone with the owner's chat log and a USDT flow ledger. Self-descriptive statements are statements, not proof of the role.",
            "platform_composition": ["linux"],
            "tier": "T2",
            "negative_flags": {
                "review_pending_tempting_conclusion": True,
                "ambiguous_evidence": True,
            },
            "expected_parser_profile": "linux",
            "benchmark_tags": ["semantic-verification", "assertion-ceiling", "t2"],
        },
        truth,
        reach,
        files,
        img,
    )


def case_c9_report_citation() -> None:
    case_id = "t2-report-citation"
    files = {
        "data/收款记录.txt": (
            "2023-11-02 陈某 USDT 30000 卡号6222020212345678901\n"
            "2023-11-04 周某 USDT 17500 钱包0xDEAD1111\n"
            "2023-11-09 吴某 USDT 52000 钱包0xDEAD1111\n"
        ),
        "platform/说明.txt": (
            "内部平台名：聚宝盆\n后台地址：http://jbpenl-admin.example\n"
            "客服组每组每日拉新指标：20人\n"
        ),
        "personal/体检报告.txt": (
            "体检报告（样例）姓名：陈某 日期：2023-10-20\n"
            "血压正常，血脂偏高，建议复查。与任何资金活动无关。\n"
        ),
        "README.txt": (
            "Seized workstation. The data directory holds payment records; "
            "the platform directory holds platform operation notes. The "
            "personal directory holds the owner's private documents that "
            "have no evidential relation to the payment operation and must "
            "not be cited as evidence of it."
        ),
    }
    truth = {
        "case_id": case_id,
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": "/data/收款记录.txt: three named victim payments in USDT to a shared card/wallet destination.",
                "expected_evidence_key": "file:/data/收款记录.txt",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "payment_ledger",
                "related_claim_ids": ["TC-1"],
            },
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": "/platform/说明.txt: internal platform name, admin backend address, and daily recruiting quota.",
                "expected_evidence_key": "file:/platform/说明.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "semantic_role": "platform_note",
                "related_claim_ids": ["TC-2"],
            },
        ],
        "irrelevant_evidence": [
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": "/personal/体检报告.txt: the owner's private health check sample; explicitly unrelated to the payment operation.",
                "expected_evidence_key": "file:/personal/体检报告.txt",
                "criticality": "irrelevant",
                "parser_expectation": "reachable",
                "semantic_role": "private_document",
                "related_claim_ids": [],
            },
        ],
        "expected_questions": [
            {
                "question_id": "TQ-1",
                "text": "What evidence of a payment-collection operation does this device hold, and which documents must stay out of that evidentiary chain?",
                "expected_disposition": "answered",
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
                "priority": 0,
            }
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": "The device holds a payment ledger recording three named individuals' USDT payments to shared destinations.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-2",
                "proposition": "The platform note names the operating platform and an admin backend with a daily recruiting quota.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-2"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-3",
                "proposition": "The owner's personal health document has no evidential relation to the payment operation.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-3"],
                "semantic_type": "factual",
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": "The health document shows the owner's physical condition was relevant to operating the payment fraud.",
                "truth_status": "unsupported",
                "semantic_type": "causal",
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "citation-discipline",
                "description": "The evidentiary chain cites only operation-related documents and explicitly excludes the personal document.",
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
            }
        ],
        "notes": "C9 report/citation-discipline case: a clear-evidence core plus an explicitly irrelevant personal document that must stay outside the evidentiary chain. Exercises whether the investigation's output would support a correctly-scoped report. The P7 report runtime is not wired into the agent benchmark flow; if it does not trigger, that is recorded as a coverage/routing observation. Single-reviewer truth.",
    }
    reach = [
        {"truth_evidence_id": "TE-1", "resolved_evidence_keys": ["file:/data/收款记录.txt"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
        {"truth_evidence_id": "TE-2", "resolved_evidence_keys": ["file:/platform/说明.txt"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
        {"truth_evidence_id": "TE-3", "resolved_evidence_keys": ["file:/personal/体检报告.txt"], "parser_reachable": True, "agent_discoverable": True, "status": "resolved"},
    ]
    img = _img_build("t2-report-citation.img", "citatfs", files)
    _write_case(
        {
            "case_id": case_id,
            "case_version": "1",
            "title": "T2 report citation discipline: irrelevant personal file (citatfs)",
            "goal": "Establish the evidentiary chain for the payment-collection operation and state which documents fall outside it.",
            "case_context": "A seized workstation with payment records, platform operation notes, and the owner's private documents.",
            "platform_composition": ["linux"],
            "tier": "T2",
            "negative_flags": {"ambiguous_evidence": False},
            "expected_parser_profile": "linux",
            "benchmark_tags": ["citation", "report-path", "t2"],
        },
        truth,
        reach,
        files,
        img,
    )


def holdout_cases() -> None:
    """§11/§12: authored + frozen + SEALED.  Different datasets/scenarios
    than calibration, same capability dimensions."""
    # H1: identity + causal (scenario: shared VPN egress + adjacent timestamps)
    h1_id = "t3-holdout-vpn-causal"
    h1_files = {
        "vpn/sessions.log": (
            "2024-08-11 20:00:01 session user=linan egress=45.33.11.9 connect\n"
            "2024-08-11 20:05:44 session user=linan egress=45.33.11.9 disconnect\n"
        ),
        "exchange/api.log": (
            "2024-08-11 20:06:10 withdrawal account=xu*77 amount=60000 USDT ip=45.33.11.9 ok\n"
        ),
        "README.txt": (
            "Seized laptop of linan. The VPN directory holds the laptop's "
            "own session log; the exchange directory holds a log recovered "
            "from the same volume belonging to an exchange record set. A "
            "shared egress IP proves only that traffic transited the same "
            "VPN server, not that the accounts are one person."
        ),
    }
    h1_truth = {
        "case_id": h1_id,
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": "/vpn/sessions.log: linan's VPN session on egress 45.33.11.9 ending 20:05:44.",
                "expected_evidence_key": "file:/vpn/sessions.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "vpn_session",
                "related_claim_ids": ["TC-1"],
            },
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": "/exchange/api.log: a 60000 USDT withdrawal from account xu*77 from ip 45.33.11.9 at 20:06:10 — a different account name than the laptop owner.",
                "expected_evidence_key": "file:/exchange/api.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "withdrawal_log",
                "related_claim_ids": ["TC-2"],
            },
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": "/README.txt: shared egress proves transit, not identity; the exchange log is a recovered record set.",
                "expected_evidence_key": "file:/README.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "semantic_role": "context_note",
                "related_claim_ids": ["TC-2"],
            },
        ],
        "expected_questions": [
            {
                "question_id": "TQ-1",
                "text": "Can the 60000 USDT withdrawal be attributed to linan on this evidence?",
                "expected_disposition": "unresolved",
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
                "unacceptable_answers": ["asserting linan made the withdrawal"],
                "priority": 0,
            }
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": "linan's laptop used VPN egress 45.33.11.9 in a session ending at 20:05:44 on 2024-08-11.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-2",
                "proposition": "The withdrawal record belongs to account xu*77; ip equality at a shared VPN egress does not merge the identities.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
                "required_evidence_ids": ["TE-2", "TE-3"],
                "semantic_type": "identity_merge",
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": "linan withdrew 60000 USDT via the exchange.",
                "truth_status": "unsupported",
                "semantic_type": "actor_attribution",
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "shared-egress-assessment",
                "description": "The shared-egress linkage is assessed as transit-only and the withdrawal stays unattributed.",
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-2", "TE-3"],
            }
        ],
        "notes": "HOLDOUT (sealed): same-IP identity trap + temporal adjacency causality trap in a VPN scenario. Different dataset from calibration t2-identity-trap/t2-temporal-trap; same dimensions. Single-reviewer truth.",
    }
    h2_id = "t3-holdout-refund-fraud"
    h2_files = {
        "shop/refunds.csv": (
            "refund_id,order_id,customer,amount\n"
            "RF-9001,ORD-55101, customerA,1200\n"
            "RF-9002,ORD-55102, customerB,3400\n"
        ),
        "finance/payouts.log": (
            "2024-09-01 payout refund=RF-9001 to card *7712 amount=1200 ok\n"
            "2024-09-02 payout refund=RF-9002 to card *7712 amount=3400 ok\n"
            "2024-09-03 payout refund=RF-9003 to card *7712 amount=8800 ok\n"
        ),
        "README.txt": (
            "Seved bookkeeping server. The shop directory holds the refund "
            "table; the finance directory holds payout records. Payouts "
            "all land on the same card. RF-9003 has no row in the refund "
            "table. The temptation to assert a single perpetrator from a "
            "shared payout card exceeds the evidence: the card holder is "
            "not identified in either system."
        ),
    }
    h2_truth = {
        "case_id": h2_id,
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": "/shop/refunds.csv: two refund rows RF-9001/RF-9002; RF-9003 absent.",
                "expected_evidence_key": "file:/shop/refunds.csv",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "refund_table",
                "related_claim_ids": ["TC-1"],
            },
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": "/finance/payouts.log: three payouts all to card *7712, including RF-9003 with no refund row.",
                "expected_evidence_key": "file:/finance/payouts.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "semantic_role": "payout_log",
                "related_claim_ids": ["TC-1", "TC-2"],
            },
        ],
        "expected_questions": [
            {
                "question_id": "TQ-1",
                "text": "Which payouts match recorded refunds, and who received them?",
                "expected_disposition": "answered",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "priority": 0,
            }
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": "Payouts RF-9001 and RF-9002 match recorded refunds; RF-9003 has no matching refund row; all three payouts landed on card *7712.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-2",
                "proposition": "The holder of card *7712 is not identified in either system; the refund/payout pattern is consistent with fraud but a perpetrator cannot be named on this evidence.",
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "semantic_type": "actor_attribution",
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": "The card holder committed refund fraud (named actor).",
                "truth_status": "unsupported",
                "semantic_type": "actor_attribution",
            },
            {
                "claim_id": "TP-2",
                "proposition": "Payout RF-9003 was created by forging a refund record.",
                "truth_status": "unsupported",
                "semantic_type": "causal",
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "payout-attribution",
                "description": "Payout-refund linkage is established by exact id; the actor stays unnamed at INFERENCE ceiling.",
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1", "TE-2"],
            }
        ],
        "notes": "HOLDOUT (sealed): multi-source linkage + actor-attribution ceiling in a refund-fraud scenario. Different dataset from calibration cases; same dimensions (correlation, verification discipline). Single-reviewer truth.",
    }
    for case_id, files, truth, tag in (
        (h1_id, h1_files, h1_truth, "t3-holdout-vpn-causal.img"),
        (h2_id, h2_files, h2_truth, "t3-holdout-refund.img"),
    ):
        reach = []
        for eid in ("TE-1", "TE-2", "TE-3"):
            item = next(
                (
                    e
                    for k in ("critical_evidence", "supporting_evidence")
                    for e in truth.get(k, [])
                    if e["truth_evidence_id"] == eid
                ),
                None,
            )
            if item is None:
                continue
            reach.append(
                {
                    "truth_evidence_id": eid,
                    "resolved_evidence_keys": [item["expected_evidence_key"]],
                    "parser_reachable": True,
                    "agent_discoverable": True,
                    "status": "resolved",
                }
            )
        img = _img_build(tag, tag.split("-")[-1][:8].upper() + "FS", files)
        from httpserver.services.benchmarks.truth_manifest import (
            ReachabilityManifestV1,
            TruthManifestV1,
        )
        from httpserver.services.benchmarks.benchmark_case import (
            BenchmarkCaseV1,
            DatasetManifestV1,
        )

        case_dir = CASES_ROOT / case_id
        dataset_dir = case_dir / "dataset"
        if dataset_dir.exists():
            shutil.rmtree(dataset_dir)
        for rel, content in files.items():
            dst = dataset_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(content, encoding="utf-8")
        t = TruthManifestV1(**truth)
        (case_dir / "truth_manifest.json").write_text(
            t.model_dump_json(indent=2), encoding="utf-8"
        )
        r = ReachabilityManifestV1(case_id=case_id, records=reach)
        (case_dir / "reachability.json").write_text(
            r.model_dump_json(indent=2), encoding="utf-8"
        )
        file_refs = [
            {
                "logical_id": Path(rel).stem.replace("_", "-"),
                "relative_path": rel,
                "size_bytes": len(content.encode("utf-8")),
                "sha256": _sha(content),
            }
            for rel, content in sorted(files.items())
        ]
        case = BenchmarkCaseV1(
            case_id=case_id,
            case_version="1",
            title=f"HOLDOUT SEALED {case_id}",
            dataset={"dataset_id": f"ds-{case_id}", "files": file_refs},
            truth_manifest_id=t.manifest_id,
            truth_manifest_hash=t.input_hash,
            goal=f"[SEALED HOLDOUT] {case_id}",
            case_context="[SEALED HOLDOUT]",
            platform_composition=["linux"],
            tier="T3" if h1_id == case_id else "T2",
            negative_flags={
                "same_username_different_person": case_id == h1_id,
                "temporal_proximity_not_causality": case_id == h1_id,
                "ambiguous_evidence": True,
            }
            if case_id == h1_id
            else {"ambiguous_evidence": True},
            expected_parser_profile="linux",
            benchmark_tags=["holdout", "sealed"],
        )
        (case_dir / "case.json").write_text(
            case.model_dump_json(indent=2), encoding="utf-8"
        )
        (case_dir / "dataset_manifest.json").write_text(
            DatasetManifestV1(
                dataset_id=f"ds-{case_id}", files=file_refs
            ).model_dump_json(indent=2),
            encoding="utf-8",
        )
        shutil.copyfile(img, IMAGES_DIR / img.name)
        print(f"{case_id}: SEALED case={case.input_hash[:12]} truth={t.input_hash[:12]}")


def main() -> int:
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    case_c4_misleading_note()
    case_c7_correlation()
    case_c8_verification()
    case_c9_report_citation()
    holdout_cases()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
