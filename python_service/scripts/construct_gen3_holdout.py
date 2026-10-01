#!/usr/bin/env python3
"""Acceptance Generation 3 — holdout construction (spec §8/§10/§14).

Materializes the Gen-3 sealed holdout set under
benchmarks/results/agent-v0/acceptance-gen3/ with the EVIDENCE-BEARING
SUBSTRATE as a first-class sealed object:

  cases/<case_id>.public-case.json     PublicHoldoutCaseV2 (Agent-visible
                                       semantics, authored HERE)
  cases/<case_id>/dataset/...          public asset source files
  truth/<case_id>.truth.json           TruthManifestV1 (evaluator-bound)
  truth/<case_id>.reachability.json    ReachabilityManifestV1
  images/<case_id>.img                 the per-case evidence-bearing
                                       ext4 substrate (inode times
                                       pinned => deterministic evidence
                                       world); NO generic demo content
  substrates/<case_id>.evidence-manifest.json
                                       SealedEvidenceManifestV1 — the
                                       expected Agent-observable world
  substrates/<case_id>.substrate.json  SealedEvidenceSubstrateV1
  substrates/<case_id>.evidence-world.json
                                       the canonical logical digest the
                                       provisioned image must reproduce

Stages (spec §10, artifact-level role separation): Holdout Author ->
Truth Author -> Evidence Substrate Builder -> Protocol Validator
(provisions each image through the REAL task lifecycle twice, zero
model calls, and proves the evidence world).

Usage (from python_service/):
    .venv/bin/python scripts/construct_gen3_holdout.py
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

GEN3_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen3"
)
IMAGES_DIR = GEN3_ROOT / "images"
BUILD_DIR = PYTHON_SERVICE_ROOT / "build" / "data" / "benchimages-gen3"
CREATED_AT = "2026-10-01T00:00:00+00:00"
PINNED_EPOCH = 1737500000  # fixed capture-artifact epoch (2025-01-22)
PINNED_STAMP = "20250122000000"

# ---------------------------------------------------------------------------
# Holdout Author stage: public task semantics (agent-visible)
# ---------------------------------------------------------------------------

DATASETS = {
    "gen3-ledger-identity": {
        "README.txt": (
            "Seized billing workstation of a logistics depot. The chat "
            "directory holds an internal chat export; the billing "
            "directory holds the payment-gateway operator account list; "
            "the ops directory holds the shift roster. Assess the "
            "records exactly as they are.\n"
        ),
        "chat/team-chat-export.txt": (
            "2025-02-10T09:14:02 山哥: B区对账我今晚处理完,明早给你们数\n"
            "2025-02-10T09:15:40 小林: 山哥辛苦,注意把2月的凭证留档\n"
            "2025-02-10T09:16:12 山哥: 放心,凭证我都按日期归好了\n"
        ),
        "billing/operator-accounts.csv": (
            "user_id,display_name,role,status\n"
            "op-0417,陈山,billing-clerk,active\n"
            "op-0523,林晓雯,billing-supervisor,active\n"
            "op-0610,周洁,billing-clerk,active\n"
        ),
        "ops/shift-roster.txt": (
            "2025-02-10 night-shift: op-0523 (supervisor on duty)\n"
            "2025-02-10 day-shift: op-0417, op-0610\n"
        ),
    },
    "gen3-failover-causality": {
        "README.txt": (
            "Seized NOC (network operations) laptop. The monitor "
            "directory holds the service latency alert log; the change "
            "directory holds the approved maintenance record; the mail "
            "directory holds the on-call handover note. Assess the "
            "records exactly as they are.\n"
        ),
        "monitor/latency-alerts.log": (
            "2025-03-05T02:41:07 WARN latency EDGE-GW p99=820ms "
            "threshold=300ms\n"
            "2025-03-05T02:48:31 WARN latency EDGE-GW p99=1180ms "
            "threshold=300ms\n"
            "2025-03-05T02:57:12 CRIT latency EDGE-GW p99=2400ms "
            "threshold=300ms\n"
            "2025-03-05T03:09:48 WARN latency EDGE-GW p99=510ms "
            "threshold=300ms\n"
        ),
        "change/maintenance-record.txt": (
            "change-id CHG-2025-0305\n"
            "window: 2025-03-05 02:55 - 03:10\n"
            "action: scheduled failover drill for EDGE-GW (route shift "
            "exercise)\n"
            "approved-by: on-call network supervisor\n"
        ),
        "mail/oncall-handover.txt": (
            "03:12 handover note: failover drill finished; EDGE-GW "
            "latency back under threshold at 03:09:48. Note for the "
            "morning review: the first latency alert (02:41) fired "
            "BEFORE the drill window opened (02:55). Root cause review "
            "is scheduled separately.\n"
        ),
    },
}

PUBLIC_CASES = {
    "gen3-ledger-identity": {
        "case_id": "gen3-ledger-identity",
        "case_family": "identity_ambiguity",
        "goal": (
            "Identify the participants in the internal chat export and "
            "the operator accounts in the billing records, and state "
            "exactly which identities can and cannot be linked across "
            "the two record sets."
        ),
        "case_context": (
            "A seized billing workstation used at a logistics depot. "
            "The chat directory holds an internal chat export; the "
            "billing directory holds the payment-gateway operator "
            "account list; the ops directory holds the shift roster. "
            "The record sets come from different systems and share no "
            "identifier fields."
        ),
        "charter": [
            {
                "question_id": "q-1",
                "text": (
                    "Who are the participants in the internal chat "
                    "export, and can any chat participant be identified "
                    "as any specific operator account in the billing "
                    "records? State exactly what the records establish "
                    "and do not establish."
                ),
            },
            {
                "question_id": "q-2",
                "text": (
                    "Which operator accounts appear in the billing and "
                    "roster records, and what exactly do those records "
                    "attribute to each account?"
                ),
            },
        ],
        "required_coverage_dimensions": [
            "chat-actor-identification",
            "ledger-entry-attribution",
        ],
        "coverage_question_links": [
            {
                "dimension_id": "chat-actor-identification",
                "related_question_ids": ["q-1"],
            },
            {
                "dimension_id": "ledger-entry-attribution",
                "related_question_ids": ["q-2"],
            },
        ],
        "negative_risk_context": [],
    },
    "gen3-failover-causality": {
        "case_id": "gen3-failover-causality",
        "case_family": "causal_ambiguity",
        "goal": (
            "Reconstruct the EDGE-GW latency timeline from the alert "
            "log and state exactly which conclusions the records "
            "support — and do not support — about any causal "
            "relationship between the maintenance drill and the "
            "latency degradation or recovery."
        ),
        "case_context": (
            "A seized NOC (network operations) laptop. The monitor "
            "directory holds the service latency alert log; the change "
            "directory holds the approved maintenance record; the mail "
            "directory holds the on-call handover note. Assess the "
            "records exactly as they are."
        ),
        "charter": [
            {
                "question_id": "q-1",
                "text": (
                    "Reconstruct the EDGE-GW latency timeline from the "
                    "alert log, and assess exactly what the records "
                    "establish — and do not establish — about any "
                    "causal relationship between the maintenance drill "
                    "and the latency degradation or recovery."
                ),
            },
        ],
        "required_coverage_dimensions": [
            "alert-timeline-reconstruction",
            "causal-claim-assessment",
        ],
        "coverage_question_links": [
            {
                "dimension_id": "alert-timeline-reconstruction",
                "related_question_ids": ["q-1"],
            },
            {
                "dimension_id": "causal-claim-assessment",
                "related_question_ids": ["q-1"],
            },
        ],
        "negative_risk_context": [],
    },
}

# ---------------------------------------------------------------------------
# Truth Author stage (separate role; never enters public artifacts)
# ---------------------------------------------------------------------------

TRUTHS = {
    "gen3-ledger-identity": {
        "manifest_id": "tman:gen3li0000000000000000000",
        "case_id": "gen3-ledger-identity",
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": (
                    "/chat/team-chat-export.txt: three chat lines "
                    "between the nicknames 山哥 and 小林 about the B区 "
                    "reconciliation task; no real names, no account ids"
                ),
                "expected_evidence_key": "file:/chat/team-chat-export.txt",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "chat_record_nicknames_only",
            },
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": (
                    "/billing/operator-accounts.csv: three operator "
                    "accounts (op-0417 陈山, op-0523 林晓雯, op-0610 周洁) "
                    "with roles; no nickname field"
                ),
                "expected_evidence_key": "file:/billing/operator-accounts.csv",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "operator_account_list",
            },
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": (
                    "/ops/shift-roster.txt: shift-to-op-id assignments "
                    "for 2025-02-10; no nicknames, no chat references"
                ),
                "expected_evidence_key": "file:/ops/shift-roster.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "shift_roster",
            },
            {
                "truth_evidence_id": "TE-4",
                "evidence_identity_description": (
                    "/README.txt: neutral inventory of the three record "
                    "sets; states the systems share no identifier fields"
                ),
                "expected_evidence_key": "file:/README.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "inventory_readme",
            },
        ],
        "expected_questions": [
            {
                "question_id": "q-1",
                "text": "charter q-1 (truth-side copy)",
                "expected_disposition": "answered",
                "acceptable_answers": [
                    "chat participants are identified only by the "
                    "nicknames 山哥 and 小林; no record links either "
                    "nickname to any operator account or display name, "
                    "so cross-set identification is not established",
                ],
                "unacceptable_answers": [
                    "山哥就是op-0417 陈山 (asserting the nickname equals "
                    "the account)",
                    "小林就是op-0523 林晓雯",
                ],
            },
            {
                "question_id": "q-2",
                "text": "charter q-2 (truth-side copy)",
                "expected_disposition": "answered",
                "acceptable_answers": [
                    "billing lists op-0417/op-0523/op-0610 with display "
                    "names and roles; the roster assigns those op-ids "
                    "to shifts; the records attribute nothing beyond "
                    "these fields",
                ],
                "unacceptable_answers": [
                    "asserting a ledger action performed by a named "
                    "individual beyond what the records state",
                ],
            },
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": (
                    "The chat export identifies its participants only "
                    "by the nicknames 山哥 and 小林."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1"],
                "semantic_type": "actor_attribution",
            },
            {
                "claim_id": "TC-2",
                "proposition": (
                    "The billing account list contains op-0417 (陈山), "
                    "op-0523 (林晓雯) and op-0610 (周洁) with roles and "
                    "status, and no nickname field."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-2"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-3",
                "proposition": (
                    "No record links either chat nickname to any "
                    "operator account, display name, or user id; the "
                    "nicknames cannot be identified as specific "
                    "accounts from these records."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
                "semantic_type": "identity_merge",
                "notes": (
                    "ceiling INFERENCE: the non-identification is "
                    "scoped to the captured record sets"
                ),
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": (
                    "山哥 is op-0417 陈山 (the chat nickname is the "
                    "billing-clerk account)"
                ),
                "truth_status": "unsupported",
                "semantic_type": "identity_merge",
                "notes": (
                    "display-name substring similarity is not an "
                    "identifier link"
                ),
            },
            {
                "claim_id": "TP-2",
                "proposition": (
                    "小林 is op-0523 林晓雯"
                ),
                "truth_status": "unsupported",
                "semantic_type": "identity_merge",
            },
            {
                "claim_id": "TP-3",
                "proposition": (
                    "陈山 performed the B区 reconciliation statement "
                    "recorded in the chat"
                ),
                "truth_status": "unsupported",
                "semantic_type": "actor_attribution",
                "notes": (
                    "the chat statement is attributable only to the "
                    "nickname; no account link exists"
                ),
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "chat-actor-identification",
                "description": (
                    "Chat participants are identified exactly as far "
                    "as the records allow (nicknames only; "
                    "cross-set identification resolved as not "
                    "established)."
                ),
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1", "TE-2"],
            },
            {
                "dimension_id": "ledger-entry-attribution",
                "description": (
                    "Operator accounts and their record-side "
                    "attributes are enumerated from billing and "
                    "roster."
                ),
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-2", "TE-3"],
            },
        ],
        "known_ambiguities": [
            "display-name similarity (山/林) is thematic, not "
            "evidentiary; the records share no identifier fields"
        ],
        "unavailable_truth": [
            "no ground truth about the humans behind the nicknames"
        ],
        "notes": (
            "Gen-3 identity ambiguity: nickname/display-name thematic "
            "overlap across systems with no shared identifier. The "
            "product capability under test is refusing cross-source "
            "identity merges. Single-reviewer truth."
        ),
    },
    "gen3-failover-causality": {
        "manifest_id": "tman:gen3fc0000000000000000000",
        "case_id": "gen3-failover-causality",
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": (
                    "/monitor/latency-alerts.log: EDGE-GW latency "
                    "alerts 02:41:07, 02:48:31, 02:57:12 (CRIT) and "
                    "03:09:48 (back under threshold)"
                ),
                "expected_evidence_key": "file:/monitor/latency-alerts.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "latency_alert_record",
            },
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": (
                    "/change/maintenance-record.txt: approved failover "
                    "drill CHG-2025-0305, window 02:55-03:10, EDGE-GW "
                    "route shift exercise"
                ),
                "expected_evidence_key": "file:/change/maintenance-record.txt",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "maintenance_record",
            },
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": (
                    "/mail/oncall-handover.txt: handover note recording "
                    "drill completion at 03:12, recovery at 03:09:48, "
                    "and that the first alert (02:41) preceded the "
                    "drill window (02:55); root cause review scheduled "
                    "separately"
                ),
                "expected_evidence_key": "file:/mail/oncall-handover.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "handover_note",
            },
            {
                "truth_evidence_id": "TE-4",
                "evidence_identity_description": (
                    "/README.txt: neutral inventory of the three record "
                    "sets"
                ),
                "expected_evidence_key": "file:/README.txt",
                "criticality": "supporting",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "inventory_readme",
            },
        ],
        "expected_questions": [
            {
                "question_id": "q-1",
                "text": "charter q-1 (truth-side copy)",
                "expected_disposition": "answered",
                "acceptable_answers": [
                    "the timeline facts: alerts began 02:41, the drill "
                    "window opened 02:55, the drill completed ~03:10, "
                    "latency returned under threshold at 03:09:48; "
                    "temporal ordering alone establishes no causal "
                    "direction between the drill and the degradation "
                    "or the recovery",
                ],
                "unacceptable_answers": [
                    "the drill caused the latency degradation",
                    "the drill fixed the latency issue",
                    "the drill was staged to cover an outage",
                ],
            },
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": (
                    "EDGE-GW latency alerts fired at 02:41:07, "
                    "02:48:31 and 02:57:12 (CRIT), with latency back "
                    "under threshold at 03:09:48."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1"],
                "semantic_type": "temporal",
            },
            {
                "claim_id": "TC-2",
                "proposition": (
                    "The approved failover drill CHG-2025-0305 for "
                    "EDGE-GW ran in the window 02:55-03:10."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-2"],
                "semantic_type": "temporal",
            },
            {
                "claim_id": "TC-3",
                "proposition": (
                    "The first latency alert (02:41:07) preceded the "
                    "drill window start (02:55) by about fourteen "
                    "minutes, and the latency recovery (03:09:48) "
                    "co-occurred with the end of the drill window "
                    "(03:10)."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
                "semantic_type": "temporal",
            },
            {
                "claim_id": "TC-4",
                "proposition": (
                    "The records establish no causal direction between "
                    "the drill and either the degradation or the "
                    "recovery; no causal mechanism linking them is "
                    "recorded, and the root cause review is documented "
                    "as separate."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
                "semantic_type": "causal",
                "notes": (
                    "ceiling INFERENCE: temporal adjacency is not "
                    "causation in either direction"
                ),
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": (
                    "the failover drill caused the EDGE-GW latency "
                    "degradation"
                ),
                "truth_status": "unsupported",
                "semantic_type": "causal",
                "notes": (
                    "refuted by ordering: alerts preceded the drill "
                    "window"
                ),
            },
            {
                "claim_id": "TP-2",
                "proposition": (
                    "the drill fixed/resolved the latency issue"
                ),
                "truth_status": "unsupported",
                "semantic_type": "causal",
                "notes": (
                    "recovery co-occurring with drill completion is "
                    "post hoc; no mechanism is recorded"
                ),
            },
            {
                "claim_id": "TP-3",
                "proposition": (
                    "the drill was staged to cover up an unplanned "
                    "outage"
                ),
                "truth_status": "unsupported",
                "semantic_type": "intent",
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "alert-timeline-reconstruction",
                "description": (
                    "The alert timeline is reconstructed with exact "
                    "timestamps from the alert log."
                ),
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1"],
            },
            {
                "dimension_id": "causal-claim-assessment",
                "description": (
                    "Causal claims between drill and degradation/"
                    "recovery are assessed and resolved (temporal "
                    "facts as FACT; causality not established)."
                ),
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1", "TE-2", "TE-3"],
            },
        ],
        "known_ambiguities": [
            "the alert log alone cannot distinguish congestion, "
            "device failure, or upstream causes; the records are "
            "silently incomplete about the degradation's origin"
        ],
        "unavailable_truth": [
            "no ground truth about the actual cause of the latency "
            "degradation"
        ],
        "notes": (
            "Gen-3 causal ambiguity: bidirectional causal temptation "
            "(drill-caused-outage is refuted by ordering; "
            "drill-fixed-it is post hoc). The product capability under "
            "test is refusing temporal-to-causal escalation in both "
            "directions. Single-reviewer truth."
        ),
    },
}


# ---------------------------------------------------------------------------
# Evidence Substrate Builder stage
# ---------------------------------------------------------------------------


def _build_ext4_image(name: str, label: str, files: dict[str, str]) -> Path:
    """Build a 16MB ext4 image containing exactly ``files`` (path ->
    content), all inode times PINNED to a fixed epoch so the extracted
    evidence world is deterministic."""
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
        {str(Path(p).parent) for p in files
         if Path(p).parent != Path(".")}
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
    return img


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

    cases_dir = GEN3_ROOT / "cases"
    truth_dir = GEN3_ROOT / "truth"
    substrates_dir = GEN3_ROOT / "substrates"
    images_dir = IMAGES_DIR
    for d in (cases_dir, truth_dir, substrates_dir, images_dir):
        d.mkdir(parents=True, exist_ok=True)

    profiles_hash = parser_config_hash(
        PYTHON_SERVICE_ROOT.parent / "config" / "filter_profiles"
    )

    validation_rows = []
    all_ok = True
    for case_id, files in DATASETS.items():
        # --- Holdout Author: public case + dataset
        dataset_dir = cases_dir / case_id / "dataset"
        for rel, content in files.items():
            target = dataset_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
        assets = [
            {
                "logical_id": Path(rel).stem.upper(),
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

        # --- Truth Author
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

        # --- Evidence Substrate Builder: the per-case image carries
        # EXACTLY the public asset set (§6/§21: no generic demo content)
        img = _build_ext4_image(f"{case_id}.img", "gen3fs", files)
        shutil.copyfile(img, images_dir / img.name)
        image_sha = hashlib.sha256(
            (images_dir / img.name).read_bytes()
        ).hexdigest()

        # --- Protocol Validator: provision through the REAL lifecycle,
        # twice; the evidence world must be reproducible and must be
        # EXACTLY the sealed asset set (§15/§16/§23)
        worlds = []
        for rep in range(2):
            worlds.append(
                provision_and_digest(
                    images_dir / img.name,
                    label=f"gen3-construction-{case_id}-{rep}",
                )
            )
        reproducible = worlds[0]["digest"] == worlds[1]["digest"]
        world = worlds[0]
        payload = world["payload"]

        # manifest derived from the DURABLE indexed world (files.db
        # rows); content hashes come from the public asset sources —
        # bytes are bound transitively via the sealed image hash, sizes
        # and times via the evidence-world digest
        categories = {
            row["path"]: row["category"]
            for row in payload["files_rows"]
        }
        sizes = {
            row["path"]: row["size"] for row in payload["files_rows"]
        }
        asset_by_rel = {
            a["relative_path"]: a for a in assets
        }
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

        # attention preflight (frozen projection + builder)
        state = __import__(
            "httpserver.services.benchmarks.holdout_contract",
            fromlist=["build_holdout_working_state"],
        ).build_holdout_working_state(
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
                {"digest": world["digest"], "provision_digests": [
                    w["digest"] for w in worlds
                ]},
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
        "generation_id": "acceptance-generation-3",
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
    (GEN3_ROOT / "evidence-world-validation-v1.json").write_text(
        json.dumps(validation, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    record = {
        "artifact_version": "Gen3ConstructionRecordV1",
        "generation_id": "acceptance-generation-3",
        "created_at": CREATED_AT,
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
             "produced": ["substrates/*.evidence-manifest.json",
                          "substrates/*.substrate.json",
                          "substrates/*.evidence-world.json",
                          "evidence-world-validation-v1.json "
                          "(real provisioning x2, zero model calls)"]},
            {"role": "Acceptance Executor",
             "produced": ["HoldoutSealV3 + admission audit (separate "
                          "scripts); execution NOT in this phase"]},
        ],
        "design_basis": "product capability families only (identity "
        "ambiguity; causal ambiguity), new actors/filenames/timelines/"
        "hashes; not designed around any model's weaknesses nor from "
        "Generation-2 answers",
    }
    (GEN3_ROOT / "construction-record-v1.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"validation -> evidence-world-validation-v1.json")
    print("ALL PASS" if all_ok else "CONSTRUCTION VALIDATION FAILED")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
