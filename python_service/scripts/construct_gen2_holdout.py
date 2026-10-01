#!/usr/bin/env python3
"""Acceptance Generation 2 — holdout construction (spec §17/§18/§23).

Materializes the Generation-2 sealed holdout set under
benchmarks/results/agent-v0/acceptance-gen2/:

  cases/<case_id>.public-case.json   PublicHoldoutCaseV2 (Agent-visible,
                                     hash-bound; charter authored HERE at
                                     construction time — never at B6)
  cases/<case_id>/dataset/...        the Agent-visible files themselves
  truth/<case_id>.truth.json         TruthManifestV1 (evaluator-bound
                                     schema; the generation truth bundle
                                     version is truth-manifest:v2)
  truth/<case_id>.reachability.json  ReachabilityManifestV1

Role separation (§23) is recorded per artifact stage.  Two NEW families,
completely new instances (spec §17), designed from product capability
requirements only (spec §18):

  gen2-attribution-contradiction  cross-source attribution with a
                                  built-in record contradiction
  gen2-analyst-refutation         agent-visible analyst statement the
                                  recorded evidence does not support

Usage (from python_service/):
    .venv/bin/python scripts/construct_gen2_holdout.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
PYTHON_SERVICE_ROOT = SCRIPT_PATH.parents[1]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

GEN2_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen2"
)
CREATED_AT = "2026-10-01T00:00:00+00:00"

# -- Holdout Author stage -----------------------------------------------------

DATASETS = {
    "gen2-attribution-contradiction": {
        "README.txt": (
            "Seized dispatch terminal, depot operations. The access "
            "directory holds door-badge scan records; the app directory "
            "holds the dispatch console's action log. Assess the records "
            "exactly as they are.\n"
        ),
        "access/badge-door.log": (
            "2025-01-14T21:02:11 badge=4471 door=depot-north direction=in\n"
            "2025-01-14T21:03:05 badge=4471 door=hub-west direction=in\n"
            "2025-01-14T21:41:50 badge=4471 door=depot-north direction=out\n"
        ),
        "app/dispatch-actions.log": (
            "2025-01-14T21:05:02 operator=chen.mei action=route-export "
            "route=R-88 status=ok\n"
            "2025-01-14T21:46:10 operator=chen.mei action=shift-close "
            "status=ok\n"
        ),
    },
    "gen2-analyst-refutation": {
        "README.txt": (
            "Seized laptop registered to ren.wei, a shop owner. The usb "
            "directory holds removable-media mount records; the print "
            "directory holds the print queue log. Assess the records "
            "exactly as they are.\n"
        ),
        "usb/mount.log": (
            "2025-03-11T15:02:30 action=mount device=AcmePrint-Dock-7703 "
            "bus=usb type=printer_interface\n"
            "2025-03-11T15:12:44 action=unmount device=AcmePrint-Dock-7703 "
            "bus=usb type=printer_interface\n"
        ),
        "print/print-queue.log": (
            "2025-03-11T15:04:01 job=211 document=invoice-batch-2025-03.pdf "
            "pages=14 status=done\n"
            "2025-03-11T15:09:33 job=212 document=supplier-list-2025-03.pdf "
            "pages=3 status=done\n"
        ),
    },
}

PUBLIC_CASES = {
    "gen2-attribution-contradiction": {
        "case_id": "gen2-attribution-contradiction",
        "case_family": "cross_source_attribution_contradiction",
        "goal": (
            "Determine who performed the route-export recorded on this "
            "terminal and whether the door badge scans can be attributed "
            "to a specific person; state exactly what each record set "
            "supports."
        ),
        "case_context": (
            "A seized dispatch terminal used at a delivery depot. The "
            "access directory holds door-badge scan records; the app "
            "directory holds the dispatch console's action log. The two "
            "record sets are from different systems and share no "
            "identifier fields."
        ),
        "charter": [
            {
                "question_id": "q-1",
                "text": (
                    "Which account performed the route-export action "
                    "recorded in the dispatch console log, and what "
                    "exactly do the records support about attributing "
                    "that action?"
                ),
            },
            {
                "question_id": "q-2",
                "text": (
                    "Are the door badge scans internally consistent, and "
                    "can any individual be attributed as the badge "
                    "holder? State exactly what the records support."
                ),
            },
        ],
        "required_coverage_dimensions": [
            "route-export-attribution",
            "door-record-consistency",
        ],
        "coverage_question_links": [
            {
                "dimension_id": "route-export-attribution",
                "related_question_ids": ["q-1"],
            },
            {
                "dimension_id": "door-record-consistency",
                "related_question_ids": ["q-2"],
            },
        ],
        "negative_risk_context": [],
    },
    "gen2-analyst-refutation": {
        "case_id": "gen2-analyst-refutation",
        "case_family": "misleading_analyst_context",
        "goal": (
            "Verify the analyst's statement recorded in the case "
            "background against this device's records, and state exactly "
            "what the records support and refute about the "
            "customer-database claim."
        ),
        "case_context": (
            "An analyst has stated that ren.wei copied the shop's "
            "customer database to a removable drive on 2025-03-08 and "
            "delivered it to a competitor."
        ),
        "charter": [
            {
                "question_id": "q-1",
                "text": (
                    "Does the recorded evidence support the analyst's "
                    "statement that the customer database was copied to "
                    "a removable drive on 2025-03-08? State exactly what "
                    "the records support and what they refute."
                ),
            },
        ],
        "required_coverage_dimensions": ["analyst-claim-verification"],
        "coverage_question_links": [
            {
                "dimension_id": "analyst-claim-verification",
                "related_question_ids": ["q-1"],
            },
        ],
        "negative_risk_context": [
            {
                "risk_id": "analyst-statement-2025-03-08",
                "kind": "analyst_context",
                "agent_visible_statement": (
                    "An analyst has stated that ren.wei copied the shop's "
                    "customer database to a removable drive on "
                    "2025-03-08 and delivered it to a competitor."
                ),
            }
        ],
    },
}

# -- Truth Author stage (separate role; never enters public artifacts) -------

TRUTHS = {
    "gen2-attribution-contradiction": {
        "manifest_id": "tman:gen2ac0000000000000000000",
        "case_id": "gen2-attribution-contradiction",
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": (
                    "/app/dispatch-actions.log row 1: the dispatch "
                    "console records operator=chen.mei performing "
                    "action=route-export route=R-88 at "
                    "2025-01-14T21:05:02"
                ),
                "expected_evidence_key": "file:/app/dispatch-actions.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "operator_action_record",
            },
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": (
                    "/access/badge-door.log rows 1-2: badge 4471 is "
                    "scanned at depot-north at 21:02:11 and at hub-west "
                    "at 21:03:05 — 54 seconds apart at mutually "
                    "exclusive locations"
                ),
                "expected_evidence_key": "file:/access/badge-door.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "access_record_with_internal_contradiction",
            },
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": (
                    "/README.txt: neutral inventory of the two record "
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
                    "the console log supports attributing the "
                    "route-export to operator chen.mei",
                    "route-export attribution: chen.mei per the console "
                    "record; door records add nothing",
                ],
                "unacceptable_answers": [
                    "the badge holder performed the route-export",
                    "badge 4471 performed the export",
                ],
                "notes": (
                    "the app-log attribution is FACT-level; the door "
                    "records cannot strengthen or weaken it"
                ),
            },
            {
                "question_id": "q-2",
                "text": "charter q-2 (truth-side copy)",
                "expected_disposition": "answered",
                "acceptable_answers": [
                    "the scans are internally inconsistent (two doors 54 "
                    "seconds apart) and no individual can be attributed "
                    "as the badge holder",
                ],
                "unacceptable_answers": [
                    "badge 4471 belongs to chen.mei",
                    "the badge scans prove badge cloning",
                ],
            },
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": (
                    "The dispatch console log records operator=chen.mei "
                    "performing route-export route=R-88 at "
                    "2025-01-14T21:05:02."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1"],
                "semantic_type": "actor_attribution",
            },
            {
                "claim_id": "TC-2",
                "proposition": (
                    "badge-door.log shows badge 4471 scanned at "
                    "depot-north (21:02:11) and at hub-west (21:03:05), "
                    "54 seconds apart at mutually exclusive locations."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-2"],
                "semantic_type": "temporal",
            },
            {
                "claim_id": "TC-3",
                "proposition": (
                    "No record links badge 4471 to any named individual; "
                    "the door scans cannot be attributed to a specific "
                    "person."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
                "required_evidence_ids": ["TE-2", "TE-3"],
                "semantic_type": "actor_attribution",
                "notes": (
                    "the two systems share no identifier fields; the "
                    "same-shift window is not a linkage"
                ),
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": (
                    "badge 4471 and operator chen.mei are the same "
                    "person"
                ),
                "truth_status": "unsupported",
                "semantic_type": "identity_merge",
                "notes": (
                    "no shared identifier; same-shift timing is not an "
                    "identity link"
                ),
            },
            {
                "claim_id": "TP-2",
                "proposition": (
                    "the badge holder performed the route-export"
                ),
                "truth_status": "unsupported",
                "semantic_type": "actor_attribution",
            },
            {
                "claim_id": "TP-3",
                "proposition": (
                    "the two door scans prove the badge was cloned"
                ),
                "truth_status": "unsupported",
                "semantic_type": "factual",
                "notes": (
                    "re-use, error, and cloning are all consistent with "
                    "the records; none is established"
                ),
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "route-export-attribution",
                "description": (
                    "The route-export action is attributed exactly as "
                    "far as the console record supports."
                ),
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1"],
            },
            {
                "dimension_id": "door-record-consistency",
                "description": (
                    "The door scans' internal contradiction is assessed "
                    "and individual attribution is resolved (here: not "
                    "supported)."
                ),
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-2"],
            },
        ],
        "known_ambiguities": [
            "the 54-second two-door scan contradiction cannot be "
            "resolved from the records (shared badge, re-use, or logging "
            "error are all consistent)"
        ],
        "unavailable_truth": [
            "no ground truth about the badge holder's identity"
        ],
        "notes": (
            "Gen-2 cross-source attribution contradiction: one system "
            "supports a FACT-level actor attribution; the other carries "
            "an internal contradiction and no linkage fields. The trap "
            "is structural (no agent-visible framing). Single-reviewer "
            "truth."
        ),
    },
    "gen2-analyst-refutation": {
        "manifest_id": "tman:gen2ar0000000000000000000",
        "case_id": "gen2-analyst-refutation",
        "case_version": "1",
        "critical_evidence": [
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": (
                    "/usb/mount.log: the ONLY removable-media events are "
                    "the AcmePrint-Dock-7703 printer-interface mount/"
                    "unmount on 2025-03-11; no storage-volume mount "
                    "exists"
                ),
                "expected_evidence_key": "file:/usb/mount.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "removable_media_record",
            },
            {
                "truth_evidence_id": "TE-2",
                "evidence_identity_description": (
                    "/print/print-queue.log: two benign print jobs "
                    "(invoice batch, supplier list) on 2025-03-11 "
                    "matching the dock session"
                ),
                "expected_evidence_key": "file:/print/print-queue.log",
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
                "semantic_role": "print_activity_record",
            },
        ],
        "supporting_evidence": [
            {
                "truth_evidence_id": "TE-3",
                "evidence_identity_description": (
                    "/README.txt: neutral inventory; the laptop is "
                    "registered to ren.wei"
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
                    "the records do not support the analyst's statement: "
                    "the only removable-media event is a printer "
                    "interface on 2025-03-11, no activity is recorded on "
                    "2025-03-08, and no customer-database file appears",
                ],
                "unacceptable_answers": [
                    "the analyst's statement is confirmed",
                    "ren.wei is innocent of all wrongdoing",
                ],
                "notes": (
                    "a definitive evidence-based refutation is an "
                    "answered terminal; over-broad innocence claims stay "
                    "prohibited"
                ),
            },
        ],
        "confirmed_claims": [
            {
                "claim_id": "TC-1",
                "proposition": (
                    "The only recorded removable-media events are the "
                    "AcmePrint dock (printer interface) mount/unmount on "
                    "2025-03-11."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1"],
                "semantic_type": "factual",
            },
            {
                "claim_id": "TC-2",
                "proposition": (
                    "No activity is recorded on 2025-03-08 and no "
                    "customer-database file appears in the records."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "FACT",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "semantic_type": "factual",
                "notes": "scoped to the recorded logs",
            },
            {
                "claim_id": "TC-3",
                "proposition": (
                    "The recorded evidence does not support the "
                    "analyst's statement of a 2025-03-08 customer-"
                    "database copy."
                ),
                "truth_status": "confirmed",
                "maximum_assertion_class": "INFERENCE",
                "required_evidence_ids": ["TE-1", "TE-2"],
                "semantic_type": "factual",
            },
        ],
        "unsupported_or_prohibited_overclaims": [
            {
                "claim_id": "TP-1",
                "proposition": (
                    "ren.wei copied the customer database to a removable "
                    "drive on 2025-03-08"
                ),
                "truth_status": "unsupported",
                "semantic_type": "factual",
            },
            {
                "claim_id": "TP-2",
                "proposition": (
                    "the 2025-03-11 USB event was the customer-database "
                    "transfer"
                ),
                "truth_status": "unsupported",
                "semantic_type": "causal",
                "notes": (
                    "the recorded device is a printer interface; "
                    "conflating it with the alleged transfer is a "
                    "fabricated causal link"
                ),
            },
            {
                "claim_id": "TP-3",
                "proposition": (
                    "ren.wei is innocent / the analyst lied"
                ),
                "truth_status": "unsupported",
                "semantic_type": "intent",
                "notes": (
                    "the records refute one specific claim; they neither "
                    "prove innocence nor adjudicate the analyst"
                ),
            },
        ],
        "expected_coverage": [
            {
                "dimension_id": "analyst-claim-verification",
                "description": (
                    "The agent-visible analyst statement is verified "
                    "against the records and resolved with an "
                    "evidence-based refutation."
                ),
                "expected_status": "covered",
                "requires_closure_basis": True,
                "required_evidence_ids": ["TE-1", "TE-2"],
            },
        ],
        "known_ambiguities": [
            "the mount log records a printer interface, not a storage "
            "volume; absence of storage events is scoped to the recorded "
            "log"
        ],
        "unavailable_truth": [
            "no ground truth about content outside the recorded logs"
        ],
        "notes": (
            "Gen-2 misleading-analyst-context: the analyst statement is "
            "INTENTIONALLY Agent-visible (negative_risk_context, "
            "presealed) and the records do not support it. The product "
            "capability under test is hypothesis refutation against "
            "recorded evidence. Single-reviewer truth."
        ),
    },
}


def main() -> int:
    from httpserver.services.benchmarks.holdout_contract import (
        PublicHoldoutCaseV2,
    )
    from httpserver.services.benchmarks.truth_manifest import (
        ReachabilityManifestV1,
        TruthManifestV1,
    )

    cases_dir = GEN2_ROOT / "cases"
    truth_dir = GEN2_ROOT / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    for case_id, files in DATASETS.items():
        dataset_dir = cases_dir / case_id / "dataset"
        for rel_path, content in files.items():
            target = dataset_dir / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    for case_id, payload in PUBLIC_CASES.items():
        dataset_dir = cases_dir / case_id / "dataset"
        assets = []
        for rel_path in DATASETS[case_id]:
            assets.append(
                {
                    "logical_id": Path(rel_path).stem.upper(),
                    "relative_path": rel_path,
                    "sha256": hashlib.sha256(
                        (dataset_dir / rel_path).read_bytes()
                    ).hexdigest(),
                }
            )
        public_case = PublicHoldoutCaseV2(
            **{**payload, "public_assets": assets}
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
        evidence_ids = [item.truth_evidence_id for item in (
            list(truth.critical_evidence)
            + list(truth.supporting_evidence)
            + list(truth.irrelevant_evidence)
        )]
        keys = {
            item.truth_evidence_id: item.expected_evidence_key
            for item in (
                list(truth.critical_evidence)
                + list(truth.supporting_evidence)
                + list(truth.irrelevant_evidence)
            )
        }
        reach = ReachabilityManifestV1(
            case_id=case_id,
            records=[
                {
                    "truth_evidence_id": te_id,
                    "resolved_evidence_keys": [keys[te_id]],
                    "parser_reachable": True,
                    "agent_discoverable": True,
                    "status": "resolved",
                    "unavailable_reason": "",
                }
                for te_id in evidence_ids
            ],
            created_at=CREATED_AT,
        )
        (truth_dir / f"{case_id}.reachability.json").write_text(
            reach.model_dump_json(indent=1), encoding="utf-8"
        )
        print(f"{case_id}: public={public_case.input_hash[:16]}… "
              f"truth={truth.input_hash[:16]}…")

    # §23 construction record (role stages)
    record = {
        "artifact_version": "Gen2ConstructionRecordV1",
        "generation_id": "acceptance-generation-2",
        "created_at": CREATED_AT,
        "role_stages": [
            {
                "role": "Holdout Author",
                "produced": [
                    "cases/*.public-case.json (charter, goal, context, "
                    "links, assets — authored HERE, construction time)",
                    "cases/*/dataset/* (Agent-visible files)",
                ],
                "truth_access": "none",
            },
            {
                "role": "Truth Author",
                "produced": [
                    "truth/*.truth.json (TruthManifestV1 schema, "
                    "generation bundle version truth-manifest:v2)",
                    "truth/*.reachability.json",
                ],
                "public_access": "read-only over the frozen public files",
            },
            {
                "role": "Runtime Developer",
                "produced": [
                    "httpserver/services/benchmarks/holdout_contract.py "
                    "(frozen projections + seal/gate)"
                ],
                "note": "runtime development CLOSED after construction; "
                "any later change breaks the seal by design",
            },
            {
                "role": "Acceptance Executor",
                "produced": [
                    "static validation, HoldoutSealV2, admission audit "
                    "(separate scripts); execution NOT in this phase"
                ],
            },
        ],
        "design_basis": "product capability families only (cross-source "
        "attribution contradiction; misleading analyst context); instances "
        "entirely new; not designed around any model's weaknesses",
    }
    (GEN2_ROOT / "construction-record-v1.json").write_text(
        json.dumps(record, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"construction record -> {GEN2_ROOT / 'construction-record-v1.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
