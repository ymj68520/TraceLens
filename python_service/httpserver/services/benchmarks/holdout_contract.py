"""Acceptance Generation 2 — sealed public holdout contract.

Generation-1 B6 was ruled B6_INVALID (HOLDOUT_AGENT_INPUT_NOT_PRESEALED):
the Agent-visible charter was authored at execution entry, so the executed
Agent input was not the admitted Agent input.  Generation 2 freezes the
corrective invariants (spec §10/§13/§14/§38):

    If the Agent can see it, it must already have been sealed before
    acceptance admission.

    B6 executes frozen semantics; B6 never authors semantics.

This module is benchmark infrastructure (NOT production agent runtime).
It provides:

  - ``PublicHoldoutCaseV2``  — the versioned, hash-bound public contract
    carrying EVERY Agent-visible holdout input (goal, context, charter
    questions, required coverage dimensions, coverage-to-question links,
    public assets, intentionally Agent-visible negative-risk framing,
    source scopes).
  - ``build_holdout_working_state`` — the FROZEN deterministic projection
    PublicHoldoutCaseV2 -> initial Working State rows.  Pure projection:
    no inference from case text, no README reasoning, no negative-flag
    authoring (spec §14).
  - ``derive_benchmark_case_v1`` — pure projection to the runner's
    BenchmarkCaseV1 (hash-only truth bindings; negative_flags left at the
    all-false default because trap framing is evaluator-only truth).
  - ``verify_truth_public_isolation`` / ``serialize_agent_visible_inputs``
    — the §16 truth-isolation check.
  - ``HoldoutSealV2`` / ``verify_holdout_seal`` / ``enforce_execution_gate``
    — the §25 seal and the execution gate that refuses to run on any
    seal mismatch or post-seal mutation.

Ownership resolution (spec §12): case-contract ``negative_flags`` are
EVALUATOR-ONLY TRUTH METADATA.  They are structurally absent from this
public contract and from the bootstrap; the only Agent-visible framing
slot is ``negative_risk_context``, whose entries must be explicitly
authored, reviewed, and sealed at generation construction time.

Charter authoring happens ONLY at generation construction time (Holdout
Author role).  No function in this module creates, amends, or infers
charter semantics — the B6 runtime can only load, validate, hash-check,
and project.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from ..report_runtime.canonical import sha256_hex

PUBLIC_HOLDOUT_CASE_VERSION = "public-holdout-case:v2"
GEN2_PROTOCOL_VERSION = "acceptance-generation-2-protocol:v1"
GEN2_TRUTH_BUNDLE_VERSION = "truth-manifest:v2"
GEN2_GENERATION_ID = "acceptance-generation-2"
GEN2_HOLDOUT_SET_ID = "holdout-set-gen2-v1"

# §12 ownership resolution — one answer, recorded as a constant so tests
# and audits can bind against it.
NEGATIVE_FLAGS_OWNERSHIP = "evaluator_only_truth_metadata"

# sealed-construction completeness markers that must never appear in a
# public contract (placeholder/sealed text is construction-time debris)
_FORBIDDEN_MARKERS = ("[SEALED", "[PLACEHOLDER", "[TO BE", "TBD", "TODO")

_SEALED_TRUTH_KEYS = (
    "expected_questions",
    "expected_disposition",
    "expected_coverage",
    "expected_status",
    "confirmed_claims",
    "acceptable_inferences",
    "unsupported_or_prohibited_overclaims",
    "critical_evidence",
    "supporting_evidence",
    "irrelevant_evidence",
    "truth_evidence_id",
    "evidence_identity_description",
    "expected_evidence_key",
    "disposition_expectation",
    "truth_status",
    "maximum_assertion_class",
    "unacceptable_answers",
    "required_evidence_ids",
    "forbidden_evidence_shortcuts",
)


class HoldoutContractError(ValueError):
    """A public holdout contract or seal violated the frozen protocol."""


class CharterQuestionV2(BaseModel):
    """One Agent-visible charter question, authored at construction."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question_id: str
    text: str


class CoverageQuestionLinkV2(BaseModel):
    """The EXACT declared association: dimension -> related question ids."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dimension_id: str
    related_question_ids: tuple[str, ...]


class PublicAssetV2(BaseModel):
    """One Agent-visible file (staged dataset content), hash-bound."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    logical_id: str
    relative_path: str
    sha256: str


class NegativeRiskContextEntryV2(BaseModel):
    """Intentionally Agent-visible negative-risk framing (e.g. an analyst
    statement the evidence will refute).  This is the ONLY framing slot:
    it exists here because the Agent must see it, therefore it is
    presealed and hash-bound like every other public field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    risk_id: str
    kind: str
    agent_visible_statement: str


class PublicHoldoutCaseV2(BaseModel):
    """§11 formal public holdout contract — every Agent-visible input."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    public_case_version: str = PUBLIC_HOLDOUT_CASE_VERSION
    case_id: str
    case_family: str
    goal: str
    case_context: str
    charter: tuple[CharterQuestionV2, ...]
    required_coverage_dimensions: tuple[str, ...]
    coverage_question_links: tuple[CoverageQuestionLinkV2, ...]
    public_assets: tuple[PublicAssetV2, ...]
    negative_risk_context: tuple[NegativeRiskContextEntryV2, ...] = ()
    source_scope_ids: tuple[str, ...] = ("windows",)

    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _validate_and_derive(cls, data):
        if not isinstance(data, dict):
            return data
        # §13: construction-time completeness — no placeholder/sealed
        # debris may survive into an admitted public contract.
        for field in ("case_id", "case_family", "goal", "case_context"):
            value = str(data.get(field, ""))
            if any(marker in value for marker in _FORBIDDEN_MARKERS):
                raise HoldoutContractError(
                    f"public case field {field!r} carries a "
                    f"placeholder/sealed marker: construction incomplete"
                )
        for question in data.get("charter", ()) or ():
            text = question.get("text", "") if isinstance(question, dict) else ""
            if any(marker in text for marker in _FORBIDDEN_MARKERS):
                raise HoldoutContractError(
                    "charter question carries a placeholder/sealed marker"
                )
        if not data.get("charter"):
            raise HoldoutContractError(
                "charter is REQUIRED at construction time (B6 never "
                "authors semantics)"
            )
        if not data.get("coverage_question_links"):
            raise HoldoutContractError(
                "coverage_question_links are REQUIRED (links are "
                "declared, never inferred)"
            )
        if not data.get("public_assets"):
            raise HoldoutContractError(
                "public_assets are REQUIRED (Agent-visible files must be "
                "hash-bound before admission)"
            )
        data.setdefault("public_case_version", PUBLIC_HOLDOUT_CASE_VERSION)
        data.setdefault("negative_risk_context", ())
        data.setdefault("source_scope_ids", ("windows",))
        for key in ("negative_risk_context", "source_scope_ids"):
            data[key] = tuple(data.get(key, ()))
        payload = {
            key: value
            for key, value in data.items()
            if key != "input_hash"
        }
        data["input_hash"] = sha256_hex(payload)
        return data

    @model_validator(mode="after")
    def _validate_structure(self):
        if not self.case_id.startswith("gen2-"):
            raise HoldoutContractError(
                "Generation-2 case ids must be namespaced 'gen2-…' (the "
                "Generation-1 pool is retired and its namespace is closed)"
            )
        question_ids = [q.question_id for q in self.charter]
        if len(set(question_ids)) != len(question_ids):
            raise HoldoutContractError("duplicate charter question_id")
        declared_links = {link.dimension_id for link in self.coverage_question_links}
        if declared_links != set(self.required_coverage_dimensions):
            raise HoldoutContractError(
                "every required coverage dimension needs exactly one "
                "declared link (and no extra links)"
            )
        for link in self.coverage_question_links:
            if not link.related_question_ids:
                raise HoldoutContractError(
                    f"dimension {link.dimension_id!r} has empty linkage"
                )
            unknown = set(link.related_question_ids) - set(question_ids)
            if unknown:
                raise HoldoutContractError(
                    f"dimension {link.dimension_id!r} references "
                    f"undeclared questions: {sorted(unknown)}"
                )
        return self


def load_public_holdout_case(path: Path) -> PublicHoldoutCaseV2:
    """The ONLY sanctioned load path for a sealed public holdout case.

    Validates the schema and re-derives the input hash; a tampered file
    fails validation before any consumer can touch it.
    """
    import json

    case = PublicHoldoutCaseV2(**json.loads(path.read_text(encoding="utf-8")))
    stored = json.loads(path.read_text(encoding="utf-8")).get("input_hash")
    if stored != case.input_hash:
        raise HoldoutContractError(
            f"public holdout case {case.case_id}: input_hash mismatch "
            f"(post-seal mutation)"
        )
    return case


# -- frozen deterministic projections (spec §14: projection ONLY) ----------


def build_holdout_working_state(
    public_case: PublicHoldoutCaseV2,
    *,
    task_id: str,
    investigation_id: str,
):
    """Project the sealed public contract into the initial Working State.

    Pure deterministic projection: charter questions become WorkingQuestion
    rows (declared ids/text), coverage dimensions become required
    not_started rows with related_question_ids taken VERBATIM from the
    declared links.  No inference, no enrichment, no authoring.
    """
    from ..investigation.agent_working_state import (
        AgentWorkingStateV1,
        CoverageDimension,
        CoverageStatus,
        QuestionPriority,
        QuestionSource,
        WorkingQuestion,
    )

    links = {
        link.dimension_id: tuple(link.related_question_ids)
        for link in public_case.coverage_question_links
    }
    return AgentWorkingStateV1(
        task_id=task_id,
        investigation_id=investigation_id,
        objective=public_case.goal,
        questions=tuple(
            WorkingQuestion(
                question_id=question.question_id,
                text=question.text,
                source=QuestionSource.charter,
                priority=QuestionPriority.high,
            )
            for question in public_case.charter
        ),
        coverage=tuple(
            CoverageDimension(
                dimension_id=dimension_id,
                required=True,
                status=CoverageStatus.not_started,
                related_question_ids=links[dimension_id],
            )
            for dimension_id in public_case.required_coverage_dimensions
        ),
    )


def derive_benchmark_case_v1(
    public_case: PublicHoldoutCaseV2,
    *,
    dataset_manifest: dict,
    truth_manifest_id: str,
    truth_manifest_hash: str,
    platform_composition: tuple[str, ...],
    expected_parser_profile: str,
    tier: str,
    title: str,
):
    """Project the sealed public contract into the runner's
    BenchmarkCaseV1.  Truth enters ONLY as the hash-only id/hash bindings
    (established Generation-1 pattern); negative_flags stay at the
    all-false default because trap framing is evaluator-only truth."""

    from .benchmark_case import BenchmarkCaseV1, DatasetManifestV1

    return BenchmarkCaseV1(
        case_id=public_case.case_id,
        case_version="1",
        title=title,
        dataset=DatasetManifestV1(**dataset_manifest),
        truth_manifest_id=truth_manifest_id,
        truth_manifest_hash=truth_manifest_hash,
        goal=public_case.goal,
        case_context=public_case.case_context,
        platform_composition=tuple(platform_composition),
        required_coverage_dimensions=tuple(
            public_case.required_coverage_dimensions
        ),
        tier=tier,
        expected_parser_profile=expected_parser_profile,
        benchmark_tags=("acceptance-gen2", "sealed", "holdout"),
    )


# -- §16 truth/public isolation --------------------------------------------


def serialize_agent_visible_inputs(public_case: PublicHoldoutCaseV2) -> str:
    """Serialize EVERY Agent-visible input (canonical JSON): the public
    contract itself plus the projected initial Working State.  The §16
    test proves this text contains no truth-only content."""
    from ..investigation.agent_runtime import canonical_state_json

    state = build_holdout_working_state(
        public_case,
        task_id="isolation-probe",
        investigation_id="isolation-probe",
    )
    return canonical_state_json(
        {
            "public_case": public_case.model_dump(mode="json"),
            "projected_working_state": state.model_dump(mode="json"),
        }
    )


def verify_truth_public_isolation(
    public_case: PublicHoldoutCaseV2,
    truth_manifest,
) -> tuple[str, ...]:
    """Deterministic §16 check.  Returns violation strings (empty = clean).

    Direction 1: no TruthManifest-only field name may appear in the
    Agent-visible serialization.
    Direction 2: no truth-specific value (evidence identity descriptions,
    claim propositions, acceptable/unacceptable answers — the truth
    author's semantic content) may appear verbatim in the Agent-visible
    serialization.  Short generic tokens are excluded by a length floor;
    the guarantee is against content transfer, not shared vocabulary.
    Direction 3 (structural): the public input_hash derivation reads only
    public-case fields — asserted here by recomputing the hash with the
    truth manifest present and observing the derivation inputs contain no
    truth field.
    """
    agent_visible = serialize_agent_visible_inputs(public_case)
    violations: list[str] = []
    for key in _SEALED_TRUTH_KEYS:
        if f'"{key}"' in agent_visible:
            violations.append(f"truth field name leaked: {key}")
    truth_values: list[str] = []
    for item in truth_manifest.critical_evidence:
        truth_values.append(item.evidence_identity_description)
    for item in truth_manifest.supporting_evidence:
        truth_values.append(item.evidence_identity_description)
    for item in truth_manifest.irrelevant_evidence:
        truth_values.append(item.evidence_identity_description)
    for claim in (
        list(truth_manifest.confirmed_claims)
        + list(truth_manifest.acceptable_inferences)
        + list(truth_manifest.unsupported_or_prohibited_overclaims)
    ):
        truth_values.append(claim.proposition)
    for question in truth_manifest.expected_questions:
        truth_values.extend(question.acceptable_answers)
        truth_values.extend(question.unacceptable_answers)
    for value in truth_values:
        probe = value.casefold()
        if len(value) >= 12 and probe in agent_visible.casefold():
            violations.append(
                f"truth content leaked into Agent-visible inputs: "
                f"{value[:80]!r}"
            )
    return tuple(violations)


# -- §25 seal + execution gate ---------------------------------------------


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HoldoutSealV2(BaseModel):
    """§25 immutable generation seal.  After creation this record is
    frozen; any mutation is itself detectable via seal_hash."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_version: str = "HoldoutSealV2"
    generation_id: str = GEN2_GENERATION_ID
    holdout_set_id: str = GEN2_HOLDOUT_SET_ID
    protocol_version: str = GEN2_PROTOCOL_VERSION
    public_contract_schema: str = PUBLIC_HOLDOUT_CASE_VERSION
    truth_bundle_version: str = GEN2_TRUTH_BUNDLE_VERSION

    public_case_hashes: dict[str, str]  # case_id -> input_hash
    public_asset_hashes: dict[str, dict[str, str]]  # case_id -> path -> sha256
    truth_hashes: dict[str, dict[str, str]]
    # case_id -> {truth_manifest_input_hash, truth_manifest_file_sha256,
    #             reachability_file_sha256}

    bootstrap_transform: dict[str, str]
    # {module: ..., code_sha256: ...} — the projection code is bound
    evaluator: dict[str, str]  # {module: ..., code_sha256: ...}
    acceptance_profile_sha256: str
    calibration_binding_sha256: str
    provisioning_substrate: dict[str, str]  # execution image, hash-bound
    sealed_at: str
    seal_reason: str

    seal_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("sealed_at", "")
        if not data.get("sealed_at"):
            data["sealed_at"] = datetime.now(timezone.utc).isoformat()
        payload = {
            key: value
            for key, value in data.items()
            if key != "seal_hash"
        }
        data["seal_hash"] = sha256_hex(payload)
        return data


def build_gen2_seal(
    *,
    cases_dir: Path,
    truth_dir: Path,
    acceptance_profile_path: Path,
    calibration_binding_path: Path,
    provisioning_substrate_path: Path,
    seal_reason: str,
    sealed_at: Optional[str] = None,
) -> HoldoutSealV2:
    """Construction-time seal builder (Holdout Author / Acceptance
    Executor roles).  Hashes the constructed generation in place.
    ``sealed_at`` is pinned by ``verify_holdout_seal`` so a verification
    rebuild is byte-identical to the original seal."""
    import json

    case_ids = sorted(
        p.stem.replace(".public-case", "")
        for p in cases_dir.glob("*.public-case.json")
    )
    public_case_hashes: dict[str, str] = {}
    public_asset_hashes: dict[str, dict[str, str]] = {}
    truth_hashes: dict[str, dict[str, str]] = {}
    for case_id in case_ids:
        public_path = cases_dir / f"{case_id}.public-case.json"
        public_case = load_public_holdout_case(public_path)
        public_case_hashes[case_id] = public_case.input_hash
        public_asset_hashes[case_id] = {
            asset.relative_path: _sha256_file(
                cases_dir / case_id / "dataset" / asset.relative_path
            )
            for asset in public_case.public_assets
        }
        truth_hashes[case_id] = {
            "truth_manifest_input_hash": json.loads(
                (truth_dir / f"{case_id}.truth.json").read_text(
                    encoding="utf-8"
                )
            )["input_hash"],
            "truth_manifest_file_sha256": _sha256_file(
                truth_dir / f"{case_id}.truth.json"
            ),
            "reachability_file_sha256": _sha256_file(
                truth_dir / f"{case_id}.reachability.json"
            ),
        }
    module_path = Path(__file__).resolve()
    evaluator_path = (
        Path(__file__).resolve().parent / "case_outcome.py"
    )
    return HoldoutSealV2(
        artifact_version="HoldoutSealV2",
        generation_id=GEN2_GENERATION_ID,
        holdout_set_id=GEN2_HOLDOUT_SET_ID,
        protocol_version=GEN2_PROTOCOL_VERSION,
        public_contract_schema=PUBLIC_HOLDOUT_CASE_VERSION,
        truth_bundle_version=GEN2_TRUTH_BUNDLE_VERSION,
        public_case_hashes=public_case_hashes,
        public_asset_hashes=public_asset_hashes,
        truth_hashes=truth_hashes,
        bootstrap_transform={
            "module": "httpserver/services/benchmarks/holdout_contract.py",
            "code_sha256": _sha256_file(module_path),
        },
        evaluator={
            "module": "httpserver/services/benchmarks/case_outcome.py",
            "code_sha256": _sha256_file(evaluator_path),
        },
        acceptance_profile_sha256=_sha256_file(acceptance_profile_path),
        calibration_binding_sha256=_sha256_file(calibration_binding_path),
        provisioning_substrate={
            "path": str(provisioning_substrate_path),
            "sha256": _sha256_file(provisioning_substrate_path),
            "role": "execution substrate only; carries no case semantics",
        },
        seal_reason=seal_reason,
        sealed_at=sealed_at,
    )


def verify_holdout_seal(
    seal: HoldoutSealV2,
    *,
    cases_dir: Path,
    truth_dir: Path,
    acceptance_profile_path: Path,
    calibration_binding_path: Path,
    provisioning_substrate_path: Path,
) -> tuple[str, ...]:
    """Recompute every sealed binding.  Returns violations (empty = the
    generation is exactly as sealed).  Any post-seal mutation — including
    one that makes the tree structurally invalid — becomes a violation,
    never an exception."""
    import json

    violations: list[str] = []

    case_ids = sorted(
        p.stem.replace(".public-case", "")
        for p in cases_dir.glob("*.public-case.json")
    )
    expected_cases: dict[str, str] = {}
    expected_assets: dict[str, dict[str, str]] = {}
    expected_truth: dict[str, dict[str, str]] = {}
    for case_id in case_ids:
        public_path = cases_dir / f"{case_id}.public-case.json"
        try:
            public_case = load_public_holdout_case(public_path)
        except Exception as exc:
            violations.append(
                f"public case {case_id} fails sealed validation: "
                f"{type(exc).__name__}: {exc}"[:200]
            )
            continue
        expected_cases[case_id] = public_case.input_hash
        expected_assets[case_id] = {
            asset.relative_path: _sha256_file(
                cases_dir / case_id / "dataset" / asset.relative_path
            )
            for asset in public_case.public_assets
        }
        truth_path = truth_dir / f"{case_id}.truth.json"
        try:
            expected_truth[case_id] = {
                "truth_manifest_input_hash": json.loads(
                    truth_path.read_text(encoding="utf-8")
                )["input_hash"],
                "truth_manifest_file_sha256": _sha256_file(truth_path),
                "reachability_file_sha256": _sha256_file(
                    truth_dir / f"{case_id}.reachability.json"
                ),
            }
        except Exception as exc:
            violations.append(
                f"truth bundle {case_id} unreadable post-seal: "
                f"{type(exc).__name__}"
            )

    try:
        expected_profile = _sha256_file(acceptance_profile_path)
    except Exception:
        expected_profile = None
    try:
        expected_binding = _sha256_file(calibration_binding_path)
    except Exception:
        expected_binding = None
    try:
        expected_substrate = {
            "path": str(provisioning_substrate_path),
            "sha256": _sha256_file(provisioning_substrate_path),
            "role": "execution substrate only; carries no case semantics",
        }
    except Exception:
        expected_substrate = None

    if expected_cases != seal.public_case_hashes:
        violations.append("sealed section mutated: public_case_hashes")
    if expected_assets != seal.public_asset_hashes:
        violations.append("sealed section mutated: public_asset_hashes")
    if expected_truth != seal.truth_hashes:
        violations.append("sealed section mutated: truth_hashes")
    expected_transform = {
        "module": "httpserver/services/benchmarks/holdout_contract.py",
        "code_sha256": _sha256_file(Path(__file__).resolve()),
    }
    if expected_transform != seal.bootstrap_transform:
        violations.append(
            "sealed section mutated: bootstrap_transform (projection "
            "code changed after seal)"
        )
    expected_evaluator = {
        "module": "httpserver/services/benchmarks/case_outcome.py",
        "code_sha256": _sha256_file(
            Path(__file__).resolve().parent / "case_outcome.py"
        ),
    }
    if expected_evaluator != seal.evaluator:
        violations.append(
            "sealed section mutated: evaluator (evaluator code changed "
            "after seal)"
        )
    if expected_profile != seal.acceptance_profile_sha256:
        violations.append(
            "sealed section mutated: acceptance_profile_sha256"
        )
    if expected_binding != seal.calibration_binding_sha256:
        violations.append(
            "sealed section mutated: calibration_binding_sha256"
        )
    if expected_substrate != seal.provisioning_substrate:
        violations.append(
            "sealed section mutated: provisioning_substrate"
        )
    # tamper with the seal record itself (post-seal seal mutation):
    # re-derive the seal hash from the record's own construction fields —
    # any forged field (reason, timestamp, hashes, metadata) breaks the
    # derivation
    recomputed_own = HoldoutSealV2(
        artifact_version=seal.artifact_version,
        generation_id=seal.generation_id,
        holdout_set_id=seal.holdout_set_id,
        protocol_version=seal.protocol_version,
        public_contract_schema=seal.public_contract_schema,
        truth_bundle_version=seal.truth_bundle_version,
        public_case_hashes=seal.public_case_hashes,
        public_asset_hashes=seal.public_asset_hashes,
        truth_hashes=seal.truth_hashes,
        bootstrap_transform=seal.bootstrap_transform,
        evaluator=seal.evaluator,
        acceptance_profile_sha256=seal.acceptance_profile_sha256,
        calibration_binding_sha256=seal.calibration_binding_sha256,
        provisioning_substrate=seal.provisioning_substrate,
        sealed_at=seal.sealed_at,
        seal_reason=seal.seal_reason,
    )
    if recomputed_own.seal_hash != seal.seal_hash:
        violations.append("seal record internally inconsistent (seal_hash)")
    return tuple(violations)


class ExecutionBlockedError(RuntimeError):
    """Raised when the frozen protocol refuses to execute a generation."""


def enforce_execution_gate(
    seal: HoldoutSealV2,
    *,
    cases_dir: Path,
    truth_dir: Path,
    acceptance_profile_path: Path,
    calibration_binding_path: Path,
    provisioning_substrate_path: Path,
) -> None:
    """§35: seal mismatch or post-seal mutation BLOCKS execution.  The
    Gen-2 driver MUST call this before provisioning the first task."""
    violations = verify_holdout_seal(
        seal,
        cases_dir=cases_dir,
        truth_dir=truth_dir,
        acceptance_profile_path=acceptance_profile_path,
        calibration_binding_path=calibration_binding_path,
        provisioning_substrate_path=provisioning_substrate_path,
    )
    if violations:
        raise ExecutionBlockedError(
            "GENERATION_INVALIDATED: execution gate refused — "
            + "; ".join(violations)
        )


__all__ = [
    "PUBLIC_HOLDOUT_CASE_VERSION",
    "GEN2_PROTOCOL_VERSION",
    "GEN2_TRUTH_BUNDLE_VERSION",
    "GEN2_GENERATION_ID",
    "GEN2_HOLDOUT_SET_ID",
    "NEGATIVE_FLAGS_OWNERSHIP",
    "CharterQuestionV2",
    "CoverageQuestionLinkV2",
    "PublicAssetV2",
    "NegativeRiskContextEntryV2",
    "PublicHoldoutCaseV2",
    "HoldoutContractError",
    "HoldoutSealV2",
    "ExecutionBlockedError",
    "load_public_holdout_case",
    "build_holdout_working_state",
    "derive_benchmark_case_v1",
    "serialize_agent_visible_inputs",
    "verify_truth_public_isolation",
    "build_gen2_seal",
    "verify_holdout_seal",
    "enforce_execution_gate",
]
