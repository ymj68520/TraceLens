"""Acceptance Generation 2 — sealed public holdout contract tests.

Pins the Generation-2 invariants (spec §10/§13/§14/§16/§25/§35):

  - the B6 runtime cannot author a charter (construction-only semantics)
  - coverage-to-question links are declared, never inferred
  - every Agent-visible field is hash-bound
  - negative_flags are evaluator-only truth metadata (structurally absent)
  - TruthManifest content cannot enter Agent-visible inputs
  - bootstrap + attention preflight are deterministic
  - seal mismatch / post-seal mutation BLOCK execution
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.services.benchmarks.holdout_contract import (
    ExecutionBlockedError,
    HoldoutContractError,
    HoldoutSealV2,
    NEGATIVE_FLAGS_OWNERSHIP,
    PublicHoldoutCaseV2,
    build_gen2_seal,
    build_holdout_working_state,
    derive_benchmark_case_v1,
    enforce_execution_gate,
    load_public_holdout_case,
    serialize_agent_visible_inputs,
    verify_holdout_seal,
    verify_truth_public_isolation,
)
from httpserver.services.benchmarks.truth_manifest import TruthManifestV1
from httpserver.services.investigation.agent_attention import AttentionBuilder


# -- fixtures ----------------------------------------------------------------


def _public_case_dict() -> dict:
    return {
        "case_id": "gen2-example",
        "case_family": "example_family",
        "goal": "Determine exactly what the recorded evidence supports.",
        "case_context": "A seized terminal with two record sets.",
        "charter": [
            {
                "question_id": "q-1",
                "text": "What does record set A support?",
            },
            {
                "question_id": "q-2",
                "text": "What does record set B support?",
            },
        ],
        "required_coverage_dimensions": ["dim-a", "dim-b"],
        "coverage_question_links": [
            {
                "dimension_id": "dim-a",
                "related_question_ids": ["q-1"],
            },
            {
                "dimension_id": "dim-b",
                "related_question_ids": ["q-1", "q-2"],
            },
        ],
        "public_assets": [
            {
                "logical_id": "README",
                "relative_path": "README.txt",
                "sha256": "0" * 64,
            }
        ],
    }


def _truth_manifest(case_id: str = "gen2-example") -> TruthManifestV1:
    return TruthManifestV1(
        manifest_id="tman:test000000000000000000",
        case_id=case_id,
        case_version="1",
        critical_evidence=[
            {
                "truth_evidence_id": "TE-1",
                "evidence_identity_description": (
                    "/app/actions.log row 1: the operator export action "
                    "recorded by the console at 21:05:02"
                ),
                "criticality": "critical",
                "parser_expectation": "reachable",
                "source_kind": "file",
            }
        ],
        expected_questions=[
            {
                "question_id": "q-1",
                "text": "truth-side phrasing",
                "expected_disposition": "answered",
                "acceptable_answers": [
                    "the console account performed the export"
                ],
            }
        ],
        confirmed_claims=[],
        unsupported_or_prohibited_overclaims=[
            {
                "claim_id": "TP-1",
                "proposition": (
                    "the badge holder and the console operator are the "
                    "same person"
                ),
                "truth_status": "unsupported",
                "semantic_type": "identity_merge",
            }
        ],
        expected_coverage=[
            {
                "dimension_id": "dim-a",
                "description": "truth-side coverage expectation",
                "expected_status": "covered",
            }
        ],
        created_at="2026-10-01T00:00:00+00:00",
    )


# -- §13: B6 runtime cannot author charter semantics -------------------------


def test_module_exposes_no_charter_authoring_api():
    import httpserver.services.benchmarks.holdout_contract as mod

    forbidden = ("author", "infer", "derive_charter", "create_charter")
    for name in mod.__all__:
        lowered = name.lower()
        assert not any(word in lowered for word in forbidden), (
            f"holdout contract module must not expose a semantic-authoring "
            f"API: {name}"
        )


def test_public_case_requires_charter_at_construction():
    payload = _public_case_dict()
    del payload["charter"]
    with pytest.raises(ValidationError):
        PublicHoldoutCaseV2(**payload)


def test_placeholder_markers_rejected_at_construction():
    payload = _public_case_dict()
    payload["goal"] = "[SEALED HOLDOUT] gen2-example"
    with pytest.raises(ValidationError):
        PublicHoldoutCaseV2(**payload)


def test_negative_flags_are_not_part_of_the_public_contract():
    assert NEGATIVE_FLAGS_OWNERSHIP == "evaluator_only_truth_metadata"
    payload = _public_case_dict()
    payload["negative_flags"] = {"ambiguous_evidence": True}
    with pytest.raises(ValidationError):
        # extra=forbid: evaluator-only truth metadata cannot enter the
        # Agent-visible public contract
        PublicHoldoutCaseV2(**payload)


# -- §14: declared links are used verbatim, never inferred -------------------


def test_projection_uses_declared_links_verbatim():
    case = PublicHoldoutCaseV2(**_public_case_dict())
    state = build_holdout_working_state(
        case, task_id="t", investigation_id="i"
    )
    by_dim = {c.dimension_id: c for c in state.coverage}
    # dim-b declares BOTH questions even though a single-question link
    # might look "natural" — the projection must not second-guess
    assert by_dim["dim-b"].related_question_ids == ("q-1", "q-2")
    assert by_dim["dim-a"].related_question_ids == ("q-1",)
    assert [q.question_id for q in state.questions] == ["q-1", "q-2"]
    assert [q.text for q in state.questions] == [
        "What does record set A support?",
        "What does record set B support?",
    ]


def test_undeclared_link_target_rejected():
    payload = _public_case_dict()
    payload["coverage_question_links"][0]["related_question_ids"] = ["q-9"]
    with pytest.raises(ValidationError):
        PublicHoldoutCaseV2(**payload)


def test_incomplete_link_coverage_rejected():
    payload = _public_case_dict()
    payload["coverage_question_links"] = payload["coverage_question_links"][:1]
    with pytest.raises(ValidationError):
        PublicHoldoutCaseV2(**payload)


def test_retired_generation1_namespace_rejected():
    payload = _public_case_dict()
    payload["case_id"] = "t3-holdout-refund-fraud"
    with pytest.raises(ValidationError):
        PublicHoldoutCaseV2(**payload)


# -- §10: every Agent-visible field is hash-bound ----------------------------


def test_input_hash_binds_every_agent_visible_field():
    base = PublicHoldoutCaseV2(**_public_case_dict())
    mutations = {
        "case_id": "gen2-example-2",
        "case_family": "other_family",
        "goal": "A different investigation objective entirely.",
        "case_context": "Different context.",
        "source_scope_ids": ("linux",),
    }
    for field, value in mutations.items():
        payload = _public_case_dict()
        payload[field] = value
        assert (
            PublicHoldoutCaseV2(**payload).input_hash != base.input_hash
        ), f"field {field} is not hash-bound"
    # nested semantic content is bound too
    payload = _public_case_dict()
    payload["charter"][0]["text"] = "Rewritten charter question."
    assert PublicHoldoutCaseV2(**payload).input_hash != base.input_hash
    payload = _public_case_dict()
    payload["coverage_question_links"][1]["related_question_ids"] = ["q-2"]
    assert PublicHoldoutCaseV2(**payload).input_hash != base.input_hash
    payload = _public_case_dict()
    payload["public_assets"][0]["sha256"] = "1" * 64
    assert PublicHoldoutCaseV2(**payload).input_hash != base.input_hash


def test_hash_is_idempotent_on_reload():
    payload = _public_case_dict()
    first = PublicHoldoutCaseV2(**payload)
    second = PublicHoldoutCaseV2(**json.loads(first.model_dump_json()))
    assert first.input_hash == second.input_hash


# -- §16: truth cannot enter Agent-visible inputs ----------------------------


def test_agent_visible_serialization_is_truth_free():
    case = PublicHoldoutCaseV2(**_public_case_dict())
    truth = _truth_manifest()
    assert verify_truth_public_isolation(case, truth) == ()
    serialized = serialize_agent_visible_inputs(case)
    # direction-1 spot checks: truth-only vocabulary absent
    for token in (
        "expected_disposition",
        "unsupported_or_prohibited_overclaims",
        "evidence_identity_description",
        "the badge holder and the console operator",
    ):
        assert token not in serialized


def test_truth_content_in_public_context_is_detected():
    # negative control: if the truth author's semantic content is pasted
    # into the public surface, the isolation check MUST flag it
    payload = _public_case_dict()
    payload["case_context"] = (
        "A seized terminal. The badge holder and the console operator "
        "are the same person according to records."
    )
    case = PublicHoldoutCaseV2(**payload)
    truth = _truth_manifest()
    violations = verify_truth_public_isolation(case, truth)
    assert violations, "truth leak into public surface went undetected"


def test_truth_manifest_object_cannot_satisfy_public_contract():
    truth = _truth_manifest().model_dump(mode="json")
    with pytest.raises(ValidationError):
        PublicHoldoutCaseV2(**truth)


def test_derived_runner_case_carries_no_truth_content():
    case = PublicHoldoutCaseV2(**_public_case_dict())
    truth = _truth_manifest()
    derived = derive_benchmark_case_v1(
        case,
        dataset_manifest={
            "dataset_id": "ds-example",
            "files": [],
            "created_at": "2026-10-01T00:00:00+00:00",
        },
        truth_manifest_id=truth.manifest_id,
        truth_manifest_hash=truth.input_hash,
        platform_composition=("linux",),
        expected_parser_profile="linux",
        tier="T2",
        title="gen2 example case",
    )
    assert derived.truth_manifest_id == truth.manifest_id  # hash-only binding
    assert not derived.negative_flags.model_dump().get(
        "ambiguous_evidence", True
    )
    derived_text = derived.model_dump_json()
    assert "evidence_identity_description" not in derived_text
    assert "the badge holder and the console operator" not in derived_text


# -- determinism --------------------------------------------------------------


def test_bootstrap_is_deterministic():
    case = PublicHoldoutCaseV2(**_public_case_dict())
    from httpserver.services.investigation.agent_runtime import (
        canonical_state_json,
        state_hash_of,
    )

    hashes = {
        state_hash_of(
            canonical_state_json(
                build_holdout_working_state(
                    case,
                    task_id=f"t-{run}",
                    investigation_id=f"i-{run}",
                ).model_dump(mode="json")
            )
        )
        for run in range(3)
    }
    # task/investigation ids differ per run; everything projectable must
    # not: compare projections under IDENTICAL ids instead
    states = [
        build_holdout_working_state(
            case, task_id="t", investigation_id="i"
        )
        for _ in range(3)
    ]
    assert len({state_hash_of(canonical_state_json(s.model_dump(mode="json"))) for s in states}) == 1


def test_attention_preflight_deterministic_and_topologically_valid():
    case = PublicHoldoutCaseV2(**_public_case_dict())
    builder = AttentionBuilder()
    states = [
        build_holdout_working_state(
            case, task_id="t", investigation_id="i"
        )
        for _ in range(2)
    ]
    attention_runs = [
        builder.build_full_set(state, state_revision=1) for state in states
    ]
    item_sets = [
        [(i.item_id, tuple(getattr(i, "related_question_ids", ()) or ()))
         for i in attention.items]
        for attention in attention_runs
    ]
    assert item_sets[0] == item_sets[1]
    item_ids = [item_id for item_id, _ in item_sets[0]]
    assert not any(i.startswith("coverage:") for i in item_ids), (
        "coverage dimensions must fold into their linked question items"
    )
    delegable_refs = []
    for attention in attention_runs[:1]:
        for item in attention.items:
            if any(
                a.value in ("delegate_source", "delegate_investigation")
                for a in getattr(item, "eligible_action_types", ())
            ):
                refs = tuple(
                    getattr(item, "related_question_ids", ()) or ()
                )
                delegable_refs.extend(refs or (item.item_id,))
    assert len(delegable_refs) == len(set(delegable_refs)), (
        "duplicate question×scope delegable topology"
    )


# -- §25/§35: seal + execution gate ------------------------------------------


class _Gen2Tree:
    """Minimal on-disk generation tree for seal round-trip tests."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "acceptance-gen2"
        self.cases = self.root / "cases"
        self.truth = self.root / "truth"
        self.cases.mkdir(parents=True)
        self.truth.mkdir(parents=True)
        case = PublicHoldoutCaseV2(**_public_case_dict())
        (self.cases / "gen2-example.public-case.json").write_text(
            case.model_dump_json(), encoding="utf-8"
        )
        dataset = self.cases / "gen2-example" / "dataset"
        dataset.mkdir(parents=True)
        (dataset / "README.txt").write_text(
            "Seized terminal example.", encoding="utf-8"
        )
        truth = _truth_manifest()
        (self.truth / "gen2-example.truth.json").write_text(
            truth.model_dump_json(), encoding="utf-8"
        )
        (self.truth / "gen2-example.reachability.json").write_text(
            json.dumps({"records": []}), encoding="utf-8"
        )
        self.profile = self.root / "profile.json"
        self.profile.write_text("{}", encoding="utf-8")
        self.binding = self.root / "binding.json"
        self.binding.write_text("{}", encoding="utf-8")
        self.substrate = self.root / "substrate.img"
        self.substrate.write_bytes(b"\x00" * 16)

    def seal(self) -> HoldoutSealV2:
        return build_gen2_seal(
            cases_dir=self.cases,
            truth_dir=self.truth,
            acceptance_profile_path=self.profile,
            calibration_binding_path=self.binding,
            provisioning_substrate_path=self.substrate,
            seal_reason="test construction",
        )

    def verify_kwargs(self) -> dict:
        return {
            "cases_dir": self.cases,
            "truth_dir": self.truth,
            "acceptance_profile_path": self.profile,
            "calibration_binding_path": self.binding,
            "provisioning_substrate_path": self.substrate,
        }


def test_seal_roundtrip_and_gate(tmp_path):
    tree = _Gen2Tree(tmp_path)
    seal = tree.seal()
    assert verify_holdout_seal(seal, **tree.verify_kwargs()) == ()
    enforce_execution_gate(seal, **tree.verify_kwargs())  # must not raise


def test_post_seal_public_mutation_blocks_execution(tmp_path):
    tree = _Gen2Tree(tmp_path)
    seal = tree.seal()
    # mutate a public case AFTER sealing
    path = tree.cases / "gen2-example.public-case.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["goal"] = "A mutated goal written after the seal."
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ExecutionBlockedError):
        enforce_execution_gate(seal, **tree.verify_kwargs())


def test_post_seal_asset_mutation_blocks_execution(tmp_path):
    tree = _Gen2Tree(tmp_path)
    seal = tree.seal()
    dataset_file = (
        tree.cases / "gen2-example" / "dataset" / "README.txt"
    )
    dataset_file.write_text("Tampered content", encoding="utf-8")
    with pytest.raises(ExecutionBlockedError):
        enforce_execution_gate(seal, **tree.verify_kwargs())


def test_post_seal_truth_mutation_blocks_execution(tmp_path):
    tree = _Gen2Tree(tmp_path)
    seal = tree.seal()
    truth_file = tree.truth / "gen2-example.truth.json"
    payload = json.loads(truth_file.read_text(encoding="utf-8"))
    payload["notes"] = "mutated after seal"
    truth_file.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ExecutionBlockedError):
        enforce_execution_gate(seal, **tree.verify_kwargs())


def test_tampered_seal_record_detected(tmp_path):
    tree = _Gen2Tree(tmp_path)
    seal = tree.seal()
    # realistic tamper 1: naive JSON edit of the seal hash
    forged_hash = HoldoutSealV2(
        **{**seal.model_dump(), "seal_hash": "f" * 64}
    )
    # model_validate re-derives, so emulate the naive edit at the dict level
    violations = verify_holdout_seal(seal, **tree.verify_kwargs())
    assert violations == ()
    edited = seal.model_dump()
    edited["seal_reason"] = "forged reason"  # hash NOT re-derived
    naive = HoldoutSealV2.model_construct(**edited)
    violations = verify_holdout_seal(naive, **tree.verify_kwargs())
    assert any("seal_hash" in v for v in violations), (
        "a JSON-edited seal record must fail the internal consistency check"
    )


def test_load_refuses_tampered_public_case(tmp_path):
    tree = _Gen2Tree(tmp_path)
    path = tree.cases / "gen2-example.public-case.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["goal"] = "Tampered."
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(HoldoutContractError):
        load_public_holdout_case(path)
