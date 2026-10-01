"""Acceptance Generation 3 — sealed evidence substrate contract.

Generation-2 B6 was ruled B6_INVALID
(HOLDOUT_EVIDENCE_SUBSTRATE_NOT_CORRECTLY_PRESEALED, see
generation2-interpretation-addendum-v1.json): the provisioning substrate
image's extraction content formed the agents' entire indexed evidence
universe while the sealed public assets never entered it.

Generation 3 freezes the corrective supreme invariant (spec §4):

    If the Agent can observe it, directly or through parsing/indexing,
    it must be frozen and hash-bound before admission.

This module (benchmark infrastructure, NOT production runtime) adds:

  - ``SealedEvidenceManifestV1`` — the expected Agent-observable
    Evidence world per case: normalized paths, sizes, hashes, expected
    canonical ``file:`` evidence keys, extra-evidence policy.
  - ``SealedEvidenceSubstrateV1`` — the evidence-bearing disk image as
    a formal protocol object: image hash/size, parser configuration
    hash, expected evidence-manifest binding.
  - ``compute_evidence_world_digest`` — the canonical LOGICAL digest of
    a provisioned task's parsed stores (``files.db`` files rows,
    ``events.db`` events rows, ``extracted_files`` listing, derived
    ``file:`` evidence keys).  Canonical logical digest, NOT a SQLite
    byte hash (spec §18).
  - ``provision_and_digest`` / ``provisioning_equivalence_check`` —
    deterministic provisioning of a sealed image through the real task
    lifecycle (LLM disabled) and digest comparison against the seal
    (spec §19); zero model calls.
  - ``HoldoutSealV3`` / ``verify_holdout_seal_v3`` /
    ``enforce_execution_gate_v3`` — the extended seal domain (substrate
    hashes, evidence manifests, evidence-world digests, parser config)
    and the execution gate with the substrate checks of spec §20.

Role separation (spec §10) is recorded in the Gen-3 construction
record: Holdout Author, Truth Author, Evidence Substrate Builder,
Protocol Validator, Acceptance Executor.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, model_validator

from ..report_runtime.canonical import sha256_hex
from .holdout_contract import (
    ExecutionBlockedError,
    HoldoutContractError,
    _sha256_file,
    load_public_holdout_case,
)

GEN3_GENERATION_ID = "acceptance-generation-3"
GEN3_HOLDOUT_SET_ID = "holdout-set-gen3-v1"
GEN3_PROTOCOL_VERSION = "acceptance-generation-3-protocol:v1"
SEALED_EVIDENCE_SUBSTRATE_VERSION = "sealed-evidence-substrate:v1"
SEALED_EVIDENCE_MANIFEST_VERSION = "sealed-evidence-manifest:v1"


class ManifestEntryV1(BaseModel):
    """One expected Agent-observable Evidence file.  NO LLM-derived
    descriptions are stored here (spec §13)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    normalized_path: str  # e.g. "/billing/operator-accounts.csv"
    size_bytes: int
    sha256: str
    expected_evidence_key: str  # e.g. "file:/billing/operator-accounts.csv"
    category: str = ""  # parser category, recorded at validation time


class SealedEvidenceManifestV1(BaseModel):
    """The expected Evidence world for one case (spec §13/§16)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    manifest_version: str = SEALED_EVIDENCE_MANIFEST_VERSION
    case_id: str
    entries: tuple[ManifestEntryV1, ...]
    # §17 extra-evidence policy: any semantic-bearing file outside this
    # manifest is a seal failure; only allowlisted non-semantic artifacts
    # may additionally appear.
    extra_evidence_policy: str = "fail_unless_allowlisted"
    allowlisted_non_semantic_patterns: tuple[str, ...] = ()

    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        entries = [
            ManifestEntryV1.model_validate(item)
            for item in (data.get("entries") or ())
        ]
        data["entries"] = tuple(
            sorted(entries, key=lambda e: e.normalized_path)
        )
        # defaulted fields MUST be pinned BEFORE hashing so a JSON reload
        # hashes the same payload as the first build (idempotency)
        data.setdefault("manifest_version", SEALED_EVIDENCE_MANIFEST_VERSION)
        data.setdefault("extra_evidence_policy", "fail_unless_allowlisted")
        data.setdefault(
            "allowlisted_non_semantic_patterns", ()
        )
        payload = {
            key: value
            for key, value in data.items()
            if key != "input_hash"
        }
        data["input_hash"] = sha256_hex(payload)
        return data


class SealedEvidenceSubstrateV1(BaseModel):
    """The evidence-bearing disk image as a formal protocol object
    (spec §5).  The substrate IS Agent-visible input: it determines the
    entire indexed Evidence world."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    substrate_version: str = SEALED_EVIDENCE_SUBSTRATE_VERSION
    substrate_id: str
    case_id: str

    image_relative_path: str
    image_sha256: str
    image_size_bytes: int

    # ties the substrate to the sealed public contract's asset set
    expected_public_asset_manifest_hash: str
    # the parser/extractor configuration binding (filter profiles)
    parser_config_hash: str
    # the expected Evidence world this image must yield
    expected_evidence_manifest_hash: str

    build_tool: str = "ext4 (dd + mke2fs + debugfs), inode times pinned"

    input_hash: str = ""

    @model_validator(mode="before")
    @classmethod
    def _derive(cls, data):
        if not isinstance(data, dict):
            return data
        data.setdefault("substrate_version", SEALED_EVIDENCE_SUBSTRATE_VERSION)
        data.setdefault("build_tool", "ext4 (dd + mke2fs + debugfs), "
        "inode times pinned")
        payload = {
            key: value
            for key, value in data.items()
            if key != "input_hash"
        }
        data["input_hash"] = sha256_hex(payload)
        return data


# -- evidence-world logical digest (spec §18) --------------------------------


def compute_evidence_world_digest(task_dir: Path) -> dict:
    """Canonical LOGICAL digest of one provisioned task's parsed stores.

    Reads ``files.db`` (files table), ``events.db`` (events table) and
    the ``extracted_files`` listing.  Never a SQLite byte hash; row sets
    are canonically serialized.  Also derives the ``file:`` evidence-key
    set from the indexed files.
    """
    import sqlite3

    def _rows(db: str, sql: str) -> list[dict]:
        conn = sqlite3.connect(task_dir / db)
        try:
            cursor = conn.execute(sql)
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        finally:
            conn.close()

    files_rows = _rows(
        "files.db",
        "select path, name, size, category, mtime, ctime, is_deleted, "
        "md5, inode from files order by path",
    )
    events_rows = _rows(
        "events.db",
        "select timestamp, event_type, file_path, inode, event_source, "
        "system_context from events order by timestamp, file_path, "
        "event_type",
    )
    # NOTE: the backend removes extracted_files shortly after completion;
    # the parsed stores ARE the durable Evidence world.  The listing is
    # captured best-effort when still present.
    extracted_dir = task_dir / "extracted_files"
    extracted = sorted(
        str(p.relative_to(extracted_dir))
        for p in extracted_dir.rglob("*")
        if p.is_file()
    ) if extracted_dir.is_dir() else []
    extracted_hashes = {
        rel: hashlib.sha256(
            (extracted_dir / rel).read_bytes()
        ).hexdigest()
        for rel in extracted
    }
    evidence_keys = sorted(
        f"file:{row['path']}" for row in files_rows if not row["is_deleted"]
    )
    indexed_paths = sorted(
        row["path"] for row in files_rows if not row["is_deleted"]
    )
    payload = {
        "files_rows": files_rows,
        "events_rows": events_rows,
        "extracted_files": extracted,
        "extracted_hashes": extracted_hashes,
        "evidence_keys": evidence_keys,
        "indexed_paths": indexed_paths,
    }
    return {
        "digest": sha256_hex(payload),
        "payload": payload,
    }


# -- deterministic provisioning + equivalence (spec §15/§19) -----------------


def provision_and_digest(
    image_path: Path,
    *,
    service_base_url: str = "http://127.0.0.1:8666",
    label: str = "gen3-provisioning-check",
    cleanup: bool = True,
) -> dict:
    """Provision ONE scratch task from ``image_path`` through the real
    task lifecycle (LLM disabled), compute the evidence-world digest of
    the parsed stores, optionally delete the task.  Zero model calls."""
    body = json.dumps(
        {
            "image_path": str(image_path),
            "case_description": f"{label} (deterministic provisioning "
            "equivalence check; no agent execution)",
            "llm_analyze": False,
            "llm_event_analyze": False,
            "priority": "high",
        }
    ).encode("utf-8")
    task_id = None
    for attempt in range(4):
        req = urllib.request.Request(
            f"{service_base_url}/api/tasks",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                task_id = json.loads(resp.read().decode("utf-8"))["id"]
            break
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 500, 502, 503) and attempt < 3:
                time.sleep(5 * (attempt + 1))
                continue
            raise
    if task_id is None:
        raise RuntimeError("provisioning task creation failed after retries")
    deadline = time.monotonic() + 600
    record = {}
    while time.monotonic() < deadline:
        with urllib.request.urlopen(
            f"{service_base_url}/api/tasks/{task_id}", timeout=15
        ) as resp:
            record = json.loads(resp.read().decode("utf-8"))
        if record.get("status") in ("completed", "failed", "cancelled"):
            break
        time.sleep(3)
    try:
        if record.get("status") != "completed":
            raise RuntimeError(
                f"provisioning task {task_id} terminal="
                f"{record.get('status')}"
            )
        extraction_dir = Path(record["extraction_directory"])
        task_dir = extraction_dir.parent
        world = compute_evidence_world_digest(task_dir)
        world["task_id"] = task_id
        return world
    finally:
        if cleanup:
            try:
                req = urllib.request.Request(
                    f"{service_base_url}/api/tasks/{task_id}",
                    method="DELETE",
                )
                with urllib.request.urlopen(req, timeout=60):
                    pass
            except Exception:
                pass  # cleanup best-effort; digest already computed


def provisioning_equivalence_check(
    substrate: SealedEvidenceSubstrateV1,
    manifest: SealedEvidenceManifestV1,
    expected_digest: str,
    *,
    images_dir: Path,
    service_base_url: str = "http://127.0.0.1:8666",
    repetitions: int = 2,
) -> dict:
    """§19/§23: provision the sealed image ``repetitions`` times; every
    run must yield the SAME evidence-world digest equal to the sealed
    expectation, the manifest keys must all be present, and no
    unexpected semantic file may appear."""
    violations: list[str] = []
    digests = []
    payload = None
    for index in range(repetitions):
        world = provision_and_digest(
            images_dir / substrate.image_relative_path,
            service_base_url=service_base_url,
            label=f"gen3-equivalence-{substrate.case_id}-{index}",
        )
        digests.append(world["digest"])
        payload = world["payload"]
        if world["digest"] != expected_digest:
            violations.append(
                f"repetition {index}: evidence-world digest mismatch"
            )
    if len(set(digests)) != 1:
        violations.append("provisioning not reproducible across repetitions")
    actual_keys = set(payload["evidence_keys"])
    expected_keys = {e.expected_evidence_key for e in manifest.entries}
    missing = expected_keys - actual_keys
    if missing:
        violations.append(f"missing expected evidence keys: {sorted(missing)}")
    # unexpected indexed Evidence (semantic-bearing) is a seal failure;
    # the parsed stores are the durable Evidence world
    expected_paths = {e.normalized_path for e in manifest.entries}
    extra_indexed = set(payload.get("indexed_paths", [])) - expected_paths
    if extra_indexed:
        violations.append(
            f"unexpected indexed evidence: {sorted(extra_indexed)}"
        )
    extra_extracted = set(payload.get("extracted_files", [])) - {
        e.normalized_path.lstrip("/") for e in manifest.entries
    }
    if extra_extracted:
        violations.append(
            f"unexpected extracted files: {sorted(extra_extracted)}"
        )
    return {
        "case_id": substrate.case_id,
        "digests": digests,
        "violations": violations,
        "ok": not violations,
    }


def derive_runner_case_for_gen3(public_case, truth, reach, cases_dataset_dir: Path):
    """Frozen projection: the sealed public contract + hash-only truth
    bindings -> the runner's BenchmarkCaseV1 (Gen-3 variant with the
    substrate-anchored dataset manifest)."""
    from .benchmark_case import BenchmarkCaseV1, DatasetManifestV1

    dataset_manifest = {
        "dataset_version": "benchmark-dataset:v1",
        "dataset_id": f"ds-{public_case.case_id}",
        "files": [
            {
                "logical_id": asset.logical_id,
                "relative_path": asset.relative_path,
                "size_bytes": (
                    cases_dataset_dir / asset.relative_path
                ).stat().st_size,
                "sha256": asset.sha256,
            }
            for asset in public_case.public_assets
        ],
        "created_at": "2026-10-01T00:00:00+00:00",
    }
    return BenchmarkCaseV1(
        case_id=public_case.case_id,
        case_version="1",
        title=f"GEN3 SEALED {public_case.case_id}",
        dataset=DatasetManifestV1(**dataset_manifest),
        truth_manifest_id=truth.manifest_id,
        truth_manifest_hash=truth.input_hash,
        goal=public_case.goal,
        case_context=public_case.case_context,
        platform_composition=("linux",),
        required_coverage_dimensions=tuple(
            public_case.required_coverage_dimensions
        ),
        tier="T2",
        expected_parser_profile="linux",
        benchmark_tags=("acceptance-gen3", "sealed", "holdout"),
    )


# -- HoldoutSealV3 + gates (spec §38-§40) -------------------------------------


def parser_config_hash(profiles_dir: Path) -> str:
    """Bind the parser/extractor filter-profile configuration: canonical
    hash over the sorted (relative path, sha256) of every profile file."""
    entries = sorted(
        (str(p.relative_to(profiles_dir)), _sha256_file(p))
        for p in profiles_dir.rglob("*.json")
    )
    return sha256_hex(entries)


class HoldoutSealV3(BaseModel):
    """§38/§39: the seal domain now includes the Evidence substrate,
    Evidence manifests, logical Evidence-world digests and the parser
    configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    artifact_version: str = "HoldoutSealV3"
    generation_id: str = GEN3_GENERATION_ID
    holdout_set_id: str = GEN3_HOLDOUT_SET_ID
    protocol_version: str = GEN3_PROTOCOL_VERSION

    public_case_hashes: dict[str, str]
    public_asset_hashes: dict[str, dict[str, str]]
    truth_hashes: dict[str, dict[str, str]]

    evidence_substrate_hashes: dict[str, dict[str, Any]]
    # case_id -> {substrate_input_hash, image_sha256, image_size_bytes,
    #             expected_evidence_manifest_hash, parser_config_hash,
    #             expected_public_asset_manifest_hash}
    evidence_world_digests: dict[str, str]
    evidence_manifest_hashes: dict[str, str]

    parser_config_hash: str
    bootstrap_transform: dict[str, str]
    evaluator: dict[str, str]
    acceptance_profile_sha256: str
    calibration_binding_sha256: str
    acceptance_profile_generation_binding_sha256: str
    runtime_investigation_subtree_hash: str
    model_config_hash: str

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


def build_gen3_seal(
    *,
    gen3_root: Path,
    profiles_dir: Path,
    acceptance_profile_path: Path,
    calibration_binding_path: Path,
    generation_binding_path: Path,
    runtime_investigation_subtree_hash: str,
    model_config_path: Path,
    seal_reason: str,
    sealed_at: Optional[str] = None,
) -> HoldoutSealV3:
    from .holdout_contract import HoldoutSealV2  # noqa: F401 (domain ref)

    cases_dir = gen3_root / "cases"
    truth_dir = gen3_root / "truth"
    substrates_dir = gen3_root / "substrates"
    images_dir = gen3_root / "images"

    case_ids = sorted(
        p.stem.replace(".public-case", "")
        for p in cases_dir.glob("*.public-case.json")
    )
    public_case_hashes: dict[str, str] = {}
    public_asset_hashes: dict[str, dict[str, str]] = {}
    truth_hashes: dict[str, dict[str, str]] = {}
    substrate_hashes: dict[str, dict[str, str]] = {}
    world_digests: dict[str, str] = {}
    manifest_hashes: dict[str, str] = {}

    for case_id in case_ids:
        case = load_public_holdout_case(
            cases_dir / f"{case_id}.public-case.json"
        )
        public_case_hashes[case_id] = case.input_hash
        public_asset_hashes[case_id] = {
            asset.relative_path: _sha256_file(
                cases_dir / case_id / "dataset" / asset.relative_path
            )
            for asset in case.public_assets
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
        substrate = SealedEvidenceSubstrateV1(
            **json.loads(
                (substrates_dir / f"{case_id}.substrate.json").read_text(
                    encoding="utf-8"
                )
            )
        )
        image_path = images_dir / substrate.image_relative_path
        actual_image_hash = _sha256_file(image_path)
        if actual_image_hash != substrate.image_sha256:
            raise HoldoutContractError(
                f"{case_id}: substrate image hash mismatch at seal time"
            )
        manifest = SealedEvidenceManifestV1(
            **json.loads(
                (substrates_dir / f"{case_id}.evidence-manifest.json")
                .read_text(encoding="utf-8")
            )
        )
        if manifest.case_id != case_id:
            raise HoldoutContractError(
                f"{case_id}: evidence manifest case mismatch"
            )
        world_digest_file = json.loads(
            (substrates_dir / f"{case_id}.evidence-world.json").read_text(
                encoding="utf-8"
            )
        )
        substrate_hashes[case_id] = {
            "substrate_input_hash": substrate.input_hash,
            "image_sha256": substrate.image_sha256,
            "image_size_bytes": substrate.image_size_bytes,
            "expected_evidence_manifest_hash": substrate.expected_evidence_manifest_hash,
            "parser_config_hash": substrate.parser_config_hash,
            "expected_public_asset_manifest_hash": substrate.expected_public_asset_manifest_hash,
        }
        if (
            substrate.expected_evidence_manifest_hash
            != manifest.input_hash
        ):
            raise HoldoutContractError(
                f"{case_id}: substrate does not bind its evidence manifest"
            )
        manifest_hashes[case_id] = manifest.input_hash
        world_digests[case_id] = world_digest_file["digest"]

    pconfig = parser_config_hash(profiles_dir)
    for case_id, entry in substrate_hashes.items():
        if entry["parser_config_hash"] != pconfig:
            raise HoldoutContractError(
                f"{case_id}: substrate parser-config hash differs from "
                f"the current parser configuration"
            )

    module_path = Path(__file__).resolve()
    return HoldoutSealV3(
        artifact_version="HoldoutSealV3",
        generation_id=GEN3_GENERATION_ID,
        holdout_set_id=GEN3_HOLDOUT_SET_ID,
        protocol_version=GEN3_PROTOCOL_VERSION,
        public_case_hashes=public_case_hashes,
        public_asset_hashes=public_asset_hashes,
        truth_hashes=truth_hashes,
        evidence_substrate_hashes=substrate_hashes,
        evidence_world_digests=world_digests,
        evidence_manifest_hashes=manifest_hashes,
        parser_config_hash=pconfig,
        bootstrap_transform={
            "module": "httpserver/services/benchmarks/holdout_contract.py",
            "code_sha256": _sha256_file(module_path.parent
                                        / "holdout_contract.py"),
        },
        evaluator={
            "module": "httpserver/services/benchmarks/case_outcome.py",
            "code_sha256": _sha256_file(
                module_path.parent / "case_outcome.py"
            ),
        },
        acceptance_profile_sha256=_sha256_file(acceptance_profile_path),
        calibration_binding_sha256=_sha256_file(calibration_binding_path),
        acceptance_profile_generation_binding_sha256=_sha256_file(
            generation_binding_path
        ),
        runtime_investigation_subtree_hash=runtime_investigation_subtree_hash,
        model_config_hash=_sha256_file(model_config_path),
        seal_reason=seal_reason,
        sealed_at=sealed_at,
    )


def verify_holdout_seal_v3(
    seal: HoldoutSealV3,
    *,
    gen3_root: Path,
    profiles_dir: Path,
    acceptance_profile_path: Path,
    calibration_binding_path: Path,
    generation_binding_path: Path,
    runtime_investigation_subtree_hash: str,
    model_config_path: Path,
) -> tuple[str, ...]:
    """Recompute every sealed binding.  Returns violations (empty = the
    generation is exactly as sealed)."""
    violations: list[str] = []
    cases_dir = gen3_root / "cases"
    truth_dir = gen3_root / "truth"
    substrates_dir = gen3_root / "substrates"
    images_dir = gen3_root / "images"

    case_ids = sorted(
        p.stem.replace(".public-case", "")
        for p in cases_dir.glob("*.public-case.json")
    )
    expected_cases: dict[str, str] = {}
    expected_assets: dict[str, dict[str, str]] = {}
    expected_truth: dict[str, dict[str, str]] = {}
    expected_substrates: dict[str, dict[str, str]] = {}
    expected_manifests: dict[str, str] = {}
    for case_id in case_ids:
        try:
            case = load_public_holdout_case(
                cases_dir / f"{case_id}.public-case.json"
            )
        except Exception as exc:
            violations.append(
                f"public case {case_id} fails sealed validation: "
                f"{type(exc).__name__}: {exc}"[:200]
            )
            continue
        expected_cases[case_id] = case.input_hash
        expected_assets[case_id] = {
            asset.relative_path: _sha256_file(
                cases_dir / case_id / "dataset" / asset.relative_path
            )
            for asset in case.public_assets
        }
        try:
            expected_truth[case_id] = {
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
        except Exception:
            violations.append(f"truth bundle {case_id} unreadable")
        try:
            substrate = SealedEvidenceSubstrateV1(
                **json.loads(
                    (substrates_dir / f"{case_id}.substrate.json")
                    .read_text(encoding="utf-8")
                )
            )
            expected_substrates[case_id] = {
                "substrate_input_hash": substrate.input_hash,
                "image_sha256": substrate.image_sha256,
                "image_size_bytes": substrate.image_size_bytes,
                "expected_evidence_manifest_hash": substrate.expected_evidence_manifest_hash,
                "parser_config_hash": substrate.parser_config_hash,
                "expected_public_asset_manifest_hash": substrate.expected_public_asset_manifest_hash,
            }
            actual_image = _sha256_file(
                images_dir / substrate.image_relative_path
            )
            if actual_image != substrate.image_sha256:
                violations.append(
                    f"SUBSTRATE_IMAGE_HASH_MISMATCH: {case_id}"
                )
            manifest = SealedEvidenceManifestV1(
                **json.loads(
                    (substrates_dir / f"{case_id}.evidence-manifest.json")
                    .read_text(encoding="utf-8")
                )
            )
            expected_manifests[case_id] = manifest.input_hash
        except HoldoutContractError as exc:
            violations.append(str(exc)[:200])
        except Exception as exc:
            violations.append(
                f"substrate {case_id} unreadable: {type(exc).__name__}"
            )

    if expected_cases != seal.public_case_hashes:
        violations.append("sealed section mutated: public_case_hashes")
    if expected_assets != seal.public_asset_hashes:
        violations.append("sealed section mutated: public_asset_hashes")
    if expected_truth != seal.truth_hashes:
        violations.append("sealed section mutated: truth_hashes")
    if expected_substrates != seal.evidence_substrate_hashes:
        violations.append("sealed section mutated: evidence_substrate_hashes")
    if expected_manifests != seal.evidence_manifest_hashes:
        violations.append("sealed section mutated: evidence_manifest_hashes")

    pconfig = parser_config_hash(profiles_dir)
    if pconfig != seal.parser_config_hash:
        violations.append(
            "PARSER_CONFIG_HASH_MISMATCH (parser configuration changed "
            "after seal)"
        )

    module = Path(__file__).resolve().parent / "holdout_contract.py"
    expected_transform = {
        "module": "httpserver/services/benchmarks/holdout_contract.py",
        "code_sha256": _sha256_file(module),
    }
    if expected_transform != seal.bootstrap_transform:
        violations.append("sealed section mutated: bootstrap_transform")
    expected_evaluator = {
        "module": "httpserver/services/benchmarks/case_outcome.py",
        "code_sha256": _sha256_file(
            Path(__file__).resolve().parent / "case_outcome.py"
        ),
    }
    if expected_evaluator != seal.evaluator:
        violations.append("sealed section mutated: evaluator")
    for name, path, expected in (
        (
            "acceptance_profile_sha256",
            acceptance_profile_path,
            seal.acceptance_profile_sha256,
        ),
        (
            "calibration_binding_sha256",
            calibration_binding_path,
            seal.calibration_binding_sha256,
        ),
        (
            "acceptance_profile_generation_binding_sha256",
            generation_binding_path,
            seal.acceptance_profile_generation_binding_sha256,
        ),
    ):
        if _sha256_file(path) != expected:
            violations.append(f"sealed section mutated: {name}")
    if (
        runtime_investigation_subtree_hash
        != seal.runtime_investigation_subtree_hash
    ):
        violations.append("sealed section mutated: runtime subtree hash")
    if _sha256_file(model_config_path) != seal.model_config_hash:
        violations.append("sealed section mutated: model_config_hash")

    # tampered seal record itself
    recomputed_own = HoldoutSealV3(
        artifact_version=seal.artifact_version,
        generation_id=seal.generation_id,
        holdout_set_id=seal.holdout_set_id,
        protocol_version=seal.protocol_version,
        public_case_hashes=seal.public_case_hashes,
        public_asset_hashes=seal.public_asset_hashes,
        truth_hashes=seal.truth_hashes,
        evidence_substrate_hashes=seal.evidence_substrate_hashes,
        evidence_world_digests=seal.evidence_world_digests,
        evidence_manifest_hashes=seal.evidence_manifest_hashes,
        parser_config_hash=seal.parser_config_hash,
        bootstrap_transform=seal.bootstrap_transform,
        evaluator=seal.evaluator,
        acceptance_profile_sha256=seal.acceptance_profile_sha256,
        calibration_binding_sha256=seal.calibration_binding_sha256,
        acceptance_profile_generation_binding_sha256=(
            seal.acceptance_profile_generation_binding_sha256
        ),
        runtime_investigation_subtree_hash=(
            seal.runtime_investigation_subtree_hash
        ),
        model_config_hash=seal.model_config_hash,
        sealed_at=seal.sealed_at,
        seal_reason=seal.seal_reason,
    )
    if recomputed_own.seal_hash != seal.seal_hash:
        violations.append("seal record internally inconsistent (seal_hash)")
    return tuple(violations)


def enforce_execution_gate_v3(
    seal: HoldoutSealV3,
    *,
    gen3_root: Path,
    profiles_dir: Path,
    acceptance_profile_path: Path,
    calibration_binding_path: Path,
    generation_binding_path: Path,
    runtime_investigation_subtree_hash: str,
    model_config_path: Path,
    evidence_world_digests: dict[str, str],
    evidence_world_keys: dict[str, set[str]],
    evidence_world_files: dict[str, set[str]],
) -> None:
    """§20 substrate gate.  ``evidence_world_*`` are supplied by the
    caller's freshly executed provisioning_equivalence_check (recorded
    in the preflight artifact); ``evidence_world_files`` must contain
    the DURABLE indexed paths (files.db) plus any extracted listing.
    This gate refuses to pass unless everything matches the seal.

    Checks:
      SUBSTRATE_IMAGE_HASH_MATCH        (in verify_holdout_seal_v3)
      EVIDENCE_WORLD_DIGEST_MATCH       (below)
      EXPECTED_EVIDENCE_KEYS_PRESENT    (below)
      UNEXPECTED_SEMANTIC_EVIDENCE_ABSENT (below)
      PARSER_CONFIG_HASH_MATCH          (in verify_holdout_seal_v3)
    """
    violations = list(
        verify_holdout_seal_v3(
            seal,
            gen3_root=gen3_root,
            profiles_dir=profiles_dir,
            acceptance_profile_path=acceptance_profile_path,
            calibration_binding_path=calibration_binding_path,
            generation_binding_path=generation_binding_path,
            runtime_investigation_subtree_hash=(
                runtime_investigation_subtree_hash
            ),
            model_config_path=model_config_path,
        )
    )
    for case_id, expected in seal.evidence_world_digests.items():
        actual = evidence_world_digests.get(case_id)
        if actual != expected:
            violations.append(
                f"EVIDENCE_WORLD_DIGEST_MATCH failed: {case_id}"
            )
        manifest = SealedEvidenceManifestV1(
            **json.loads(
                (
                    gen3_root / "substrates"
                    / f"{case_id}.evidence-manifest.json"
                ).read_text(encoding="utf-8")
            )
        )
        missing = {
            e.expected_evidence_key for e in manifest.entries
        } - evidence_world_keys.get(case_id, set())
        if missing:
            violations.append(
                f"EXPECTED_EVIDENCE_KEYS_PRESENT failed: {case_id} "
                f"missing {sorted(missing)}"
            )
        allowlist = set(manifest.allowlisted_non_semantic_patterns)
        extra = evidence_world_files.get(case_id, set()) - {
            e.normalized_path.lstrip("/") for e in manifest.entries
        }
        unallowlisted = {
            f for f in extra
            if not any(
                pattern in f for pattern in allowlist
            )
        }
        if unallowlisted:
            violations.append(
                f"UNEXPECTED_SEMANTIC_EVIDENCE_ABSENT failed: {case_id} "
                f"extra {sorted(unallowlisted)}"
            )
    if violations:
        raise ExecutionBlockedError(
            "GENERATION_INVALIDATED: execution gate refused — "
            + "; ".join(violations)
        )


__all__ = [
    "GEN3_GENERATION_ID",
    "GEN3_HOLDOUT_SET_ID",
    "GEN3_PROTOCOL_VERSION",
    "SEALED_EVIDENCE_SUBSTRATE_VERSION",
    "SEALED_EVIDENCE_MANIFEST_VERSION",
    "ManifestEntryV1",
    "SealedEvidenceManifestV1",
    "SealedEvidenceSubstrateV1",
    "HoldoutSealV3",
    "HoldoutContractError",
    "ExecutionBlockedError",
    "compute_evidence_world_digest",
    "provision_and_digest",
    "provisioning_equivalence_check",
    "parser_config_hash",
    "build_gen3_seal",
    "verify_holdout_seal_v3",
    "enforce_execution_gate_v3",
    "load_public_holdout_case",
]
