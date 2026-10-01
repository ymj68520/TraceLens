"""Acceptance Generation 3 — evidence-substrate contract tests.

Pins the Gen-3 supreme invariant and the §30-§37 regression class:
the Gen-2 failure mode (sealed semantic contract != actual indexed
Evidence world) must be UNPROVISIONABLE — every mismatch blocks the
execution gate BEFORE any model call.

These tests exercise the gate/equivalence LOGIC against deterministic
synthetic task stores; the real end-to-end provisioning equivalence
runs in the admission preflight (zero model calls).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
from pathlib import Path

import pytest

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parents[3]
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.services.benchmarks.holdout_contract import (
    ExecutionBlockedError,
    PublicHoldoutCaseV2,
)
from httpserver.services.benchmarks.holdout_contract_v3 import (
    HoldoutSealV3,
    SealedEvidenceManifestV1,
    SealedEvidenceSubstrateV1,
    compute_evidence_world_digest,
    enforce_execution_gate_v3,
    parser_config_hash,
    provision_and_digest,
    verify_holdout_seal_v3,
)


# -- fixtures -----------------------------------------------------------------


def _write_store(task_dir: Path, files_rows: list[dict],
                 events_rows: list[dict], extracted: dict[str, bytes]):
    """Build a minimal parsed-store fixture matching the production
    schema columns the digest reads."""
    task_dir.mkdir(parents=True, exist_ok=True)
    (task_dir / "extracted_files").mkdir(exist_ok=True)
    conn = sqlite3.connect(task_dir / "files.db")
    conn.execute(
        "create table files (id integer primary key, inode integer, "
        "name text, path text, size integer, extension text, "
        "category text, type text, mtime integer, ctime integer, "
        "is_deleted integer, md5 text)"
    )
    for i, row in enumerate(files_rows, start=1):
        conn.execute(
            "insert into files (id, inode, name, path, size, category, "
            "mtime, ctime, is_deleted, md5) values (?,?,?,?,?,?,?,?,?,?)",
            (
                i, row.get("inode", i), row["path"].rsplit("/", 1)[-1],
                row["path"], row["size"], row.get("category", ""),
                row["mtime"], row["ctime"], 0, "",
            ),
        )
    conn.commit()
    conn.close()

    conn = sqlite3.connect(task_dir / "events.db")
    conn.execute(
        "create table events (id integer primary key, timestamp integer, "
        "event_type text, file_path text, inode integer, "
        "description text, file_size integer, file_type text, "
        "system_context text, priority text, severity text, "
        "event_source text)"
    )
    for i, row in enumerate(events_rows, start=1):
        conn.execute(
            "insert into events (id, timestamp, event_type, file_path, "
            "inode, event_source, system_context) values (?,?,?,?,?,?,?)",
            (
                i, row["timestamp"], row["event_type"], row["file_path"],
                row.get("inode", 0), row.get("event_source", "FILE_SYSTEM"),
                row.get("system_context", ""),
            ),
        )
    conn.commit()
    conn.close()

    for rel, content in extracted.items():
        target = task_dir / "extracted_files" / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


SUBSTRATE_FILES = {
    "access/door-scan.log": b"2025-02-10T08:01 door=D2 badge=B-9931\n",
    "ops/asset-registry.csv": b"asset,terminal\nW-5521,TOK-330117\n",
    "README.txt": b"Seized billing workstation.\n",
}
STAGED_BUT_UNINDEXED = {
    "late/never-indexed.txt": b"copied after extraction\n",
}


def _substrate_world() -> tuple[list[dict], list[dict], dict[str, bytes]]:
    """files/events rows the SUBSTRATE IMAGE yields (indexed world)."""
    files_rows = [
        {"path": "/access/door-scan.log", "size": 43, "mtime": 1737360060,
         "ctime": 1737360060},
        {"path": "/README.txt", "size": 29, "mtime": 1737360060,
         "ctime": 1737360060},
        {"path": "/ops/asset-registry.csv", "size": 30,
         "mtime": 1737360060, "ctime": 1737360060},
    ]
    events_rows = [
        {"timestamp": 1737360060, "event_type": "FILE_MODIFIED",
         "file_path": row["path"], "inode": i}
        for i, row in enumerate(files_rows, start=11)
    ] + [
        {"timestamp": 1737360067, "event_type": "FILE_CREATED",
         "file_path": row["path"], "inode": i}
        for i, row in enumerate(files_rows, start=11)
    ]
    return files_rows, events_rows, dict(SUBSTRATE_FILES)


def _gen3_tree(tmp_path: Path):
    """Full Gen-3 generation tree for seal round-trip tests."""
    root = tmp_path / "acceptance-gen3"
    cases = root / "cases"
    truth = root / "truth"
    substrates = root / "substrates"
    images = root / "images"
    profiles = root / "config" / "filter_profiles"
    for d in (cases, truth, substrates, images, profiles):
        d.mkdir(parents=True)

    public = PublicHoldoutCaseV2(
        case_id="gen3-example",
        case_family="example_family",
        goal="Determine what the recorded evidence supports.",
        case_context="A seized workstation with two record sets.",
        charter=[
            {"question_id": "q-1", "text": "What does the record support?"}
        ],
        required_coverage_dimensions=["dim-a"],
        coverage_question_links=[
            {"dimension_id": "dim-a", "related_question_ids": ["q-1"]}
        ],
        public_assets=[
            {
                "logical_id": k.upper(),
                "relative_path": k,
                "sha256": hashlib.sha256(v).hexdigest(),
            }
            for k, v in SUBSTRATE_FILES.items()
        ],
    )
    (cases / "gen3-example.public-case.json").write_text(
        public.model_dump_json(), encoding="utf-8"
    )
    dataset = cases / "gen3-example" / "dataset"
    for rel, content in SUBSTRATE_FILES.items():
        target = dataset / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)

    (truth / "gen3-example.truth.json").write_text(
        json.dumps(
            {
                "manifest_id": "tman:gen3ex000000000000000000",
                "case_id": "gen3-example",
                "case_version": "1",
                "input_hash": "t" * 64,
                "created_at": "2026-10-01T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    (truth / "gen3-example.reachability.json").write_text(
        json.dumps({"records": []}), encoding="utf-8"
    )

    image = images / "gen3-example.img"
    image.write_bytes(b"\x00" * 64)
    files_rows, events_rows, _ = _substrate_world()
    scratch = tmp_path / "scratch-task"
    _write_store(scratch, files_rows, events_rows, SUBSTRATE_FILES)
    world = compute_evidence_world_digest(scratch)

    manifest = SealedEvidenceManifestV1(
        case_id="gen3-example",
        entries=[
            {
                "normalized_path": f"/{rel}",
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "expected_evidence_key": f"file:/{rel}",
            }
            for rel, content in SUBSTRATE_FILES.items()
        ],
    )
    (substrates / "gen3-example.evidence-manifest.json").write_text(
        manifest.model_dump_json(), encoding="utf-8"
    )
    # parser configuration must exist BEFORE the substrate binds its hash
    (profiles / "general_forensics.json").write_text(
        json.dumps({"profile_name": "general_forensics"}),
        encoding="utf-8",
    )
    substrate = SealedEvidenceSubstrateV1(
        substrate_id="sub-gen3-example",
        case_id="gen3-example",
        image_relative_path="gen3-example.img",
        image_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),
        image_size_bytes=image.stat().st_size,
        expected_public_asset_manifest_hash=public.input_hash,
        parser_config_hash=parser_config_hash(profiles),
        expected_evidence_manifest_hash=manifest.input_hash,
    )
    (substrates / "gen3-example.substrate.json").write_text(
        substrate.model_dump_json(), encoding="utf-8"
    )
    (substrates / "gen3-example.evidence-world.json").write_text(
        json.dumps({"digest": world["digest"]}), encoding="utf-8"
    )

    anchor = root / "anchors"
    anchor.mkdir()
    for name in ("profile.json", "binding.json", "gen-binding.json"):
        (anchor / name).write_text("{}", encoding="utf-8")
    model_cfg = anchor / "model-config.json"
    model_cfg.write_text("{}", encoding="utf-8")

    return {
        "root": root,
        "cases": cases,
        "truth": truth,
        "substrates": substrates,
        "images": images,
        "profiles": profiles,
        "anchor": anchor,
        "model_config": model_cfg,
        "public": public,
        "manifest": manifest,
        "substrate": substrate,
        "world": world,
        "runtime_hash": "r" * 64,
    }


def _gate_kwargs(tree: dict) -> dict:
    return {
        "gen3_root": tree["root"],
        "profiles_dir": tree["profiles"],
        "acceptance_profile_path": tree["anchor"] / "profile.json",
        "calibration_binding_path": tree["anchor"] / "binding.json",
        "generation_binding_path": tree["anchor"] / "gen-binding.json",
        "runtime_investigation_subtree_hash": tree["runtime_hash"],
        "model_config_path": tree["model_config"],
    }


def _world_args(case_id: str, world: dict) -> dict:
    return {
        "evidence_world_digests": {case_id: world["digest"]},
        "evidence_world_keys": {
            case_id: set(world["payload"]["evidence_keys"])
        },
        "evidence_world_files": {
            case_id: set(world["payload"]["extracted_files"])
        },
    }


# -- seal round trip + happy-path gate ----------------------------------------


def test_gen3_seal_roundtrip_and_gate(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = HoldoutSealV3(**json.loads(
        _build_seal(tree).model_dump_json()
    ))
    assert verify_holdout_seal_v3(seal, **_gate_kwargs(tree)) == ()
    enforce_execution_gate_v3(
        seal, **_gate_kwargs(tree), **_world_args("gen3-example", tree["world"])
    )


def _build_seal(tree: dict) -> HoldoutSealV3:
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        build_gen3_seal,
    )

    return build_gen3_seal(
        gen3_root=tree["root"],
        profiles_dir=tree["profiles"],
        acceptance_profile_path=tree["anchor"] / "profile.json",
        calibration_binding_path=tree["anchor"] / "binding.json",
        generation_binding_path=tree["anchor"] / "gen-binding.json",
        runtime_investigation_subtree_hash=tree["runtime_hash"],
        model_config_path=tree["model_config"],
        seal_reason="test construction",
    )


# -- §30: wrong generic image (generic demo evidence instead of sealed) -------


def test_wrong_generic_image_blocks_gate(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    # the agent's world is a GENERIC DEMO image's content (the Gen-2
    # failure): none of the sealed evidence keys present, demo files extra
    demo_files_rows = [
        {"path": "/data/customer-list.csv", "size": 136,
         "mtime": 1789924915, "ctime": 1789924915},
        {"path": "/scripts/opening.txt", "size": 251,
         "mtime": 1789924915, "ctime": 1789924915},
    ]
    demo_events = [
        {"timestamp": 1789924915, "event_type": "FILE_MODIFIED",
         "file_path": row["path"], "inode": i}
        for i, row in enumerate(demo_files_rows, start=21)
    ]
    scratch = tmp_path / "demo-task"
    _write_store(scratch, demo_files_rows, demo_events,
                 {"data/customer-list.csv": b"x" * 136})
    demo_world = compute_evidence_world_digest(scratch)
    with pytest.raises(ExecutionBlockedError) as excinfo:
        enforce_execution_gate_v3(
            seal, **_gate_kwargs(tree),
            **_world_args("gen3-example", demo_world),
        )
    message = str(excinfo.value)
    assert "EXPECTED_EVIDENCE_KEYS_PRESENT" in message
    assert "UNEXPECTED_SEMANTIC_EVIDENCE_ABSENT" in message


# -- §31: late copied file is NOT legal evidence provisioning -----------------


def test_late_copied_file_fails_equivalence(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    # the image world indexed ONLY some substrate files; a required file
    # was copied into extracted_files AFTER extraction (Gen-2 mechanism)
    files_rows, events_rows, _ = _substrate_world()
    partial_rows = [r for r in files_rows
                    if r["path"] != "/access/door-scan.log"]
    partial_events = [e for e in events_rows
                      if e["file_path"] != "/access/door-scan.log"]
    scratch = tmp_path / "late-copy-task"
    _write_store(scratch, partial_rows, partial_events,
                 {**SUBSTRATE_FILES, **STAGED_BUT_UNINDEXED})
    late_world = compute_evidence_world_digest(scratch)
    # the late-copied files ARE on disk...
    assert "access/door-scan.log" in late_world["payload"]["extracted_files"]
    assert "late/never-indexed.txt" in late_world["payload"]["extracted_files"]
    with pytest.raises(ExecutionBlockedError) as excinfo:
        enforce_execution_gate_v3(
            seal, **_gate_kwargs(tree),
            **_world_args("gen3-example", late_world),
        )
    message = str(excinfo.value)
    # late copy != legal provisioning: digest drifts, key missing, extra file
    assert "EVIDENCE_WORLD_DIGEST_MATCH" in message
    assert "EXPECTED_EVIDENCE_KEYS_PRESENT" in message
    assert "UNEXPECTED_SEMANTIC_EVIDENCE_ABSENT" in message


# -- §32: missing sealed evidence ---------------------------------------------


def test_missing_sealed_evidence_blocks_gate(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    files_rows, events_rows, _ = _substrate_world()
    partial_rows = [r for r in files_rows
                    if r["path"] != "/README.txt"]
    partial_events = [e for e in events_rows
                      if e["file_path"] != "/README.txt"]
    scratch = tmp_path / "missing-task"
    _write_store(scratch, partial_rows, partial_events,
                 {"access/door-scan.log": SUBSTRATE_FILES["access/door-scan.log"],
                  "ops/asset-registry.csv": SUBSTRATE_FILES["ops/asset-registry.csv"]})
    world = compute_evidence_world_digest(scratch)
    with pytest.raises(ExecutionBlockedError):
        enforce_execution_gate_v3(
            seal, **_gate_kwargs(tree), **_world_args("gen3-example", world)
        )


# -- §33: unexpected semantic evidence -----------------------------------------


def test_unexpected_semantic_evidence_blocks_gate(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    files_rows, events_rows, extracted = _substrate_world()
    extra_file = dict(extracted)
    extra_file["samples/demo-transaction.csv"] = b"acct,amount\nA,1\n"
    scratch = tmp_path / "extra-task"
    _write_store(scratch, files_rows, events_rows, extra_file)
    world = compute_evidence_world_digest(scratch)
    with pytest.raises(ExecutionBlockedError) as excinfo:
        enforce_execution_gate_v3(
            seal, **_gate_kwargs(tree), **_world_args("gen3-example", world)
        )
    assert "UNEXPECTED_SEMANTIC_EVIDENCE_ABSENT" in str(excinfo.value)


# -- §34: post-seal image mutation ---------------------------------------------


def test_image_mutation_blocks_execution(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    image = tree["images"] / "gen3-example.img"
    image.write_bytes(b"\x01" * 64)
    violations = verify_holdout_seal_v3(seal, **_gate_kwargs(tree))
    assert any("SUBSTRATE_IMAGE_HASH_MISMATCH" in v for v in violations)


# -- §35: parser config mutation ------------------------------------------------


def test_parser_config_mutation_blocks_execution(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    profile = tree["profiles"] / "general_forensics.json"
    profile.write_text(
        json.dumps({"profile_name": "general_forensics", "version": 99}),
        encoding="utf-8",
    )
    violations = verify_holdout_seal_v3(seal, **_gate_kwargs(tree))
    assert any("PARSER_CONFIG_HASH_MISMATCH" in v for v in violations)


# -- §36: logical DB drift -------------------------------------------------------


def test_logical_db_drift_blocks_execution(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    files_rows, events_rows, extracted = _substrate_world()
    # same files, one event timestamp drifts (parser output changed)
    events_rows = [dict(e) for e in events_rows]
    events_rows[0]["timestamp"] += 1
    scratch = tmp_path / "drift-task"
    _write_store(scratch, files_rows, events_rows, extracted)
    world = compute_evidence_world_digest(scratch)
    assert world["digest"] != tree["world"]["digest"]
    with pytest.raises(ExecutionBlockedError) as excinfo:
        enforce_execution_gate_v3(
            seal, **_gate_kwargs(tree), **_world_args("gen3-example", world)
        )
    assert "EVIDENCE_WORLD_DIGEST_MATCH" in str(excinfo.value)


# -- §23: reproducibility of the evidence world ----------------------------------


def test_evidence_world_digest_deterministic(tmp_path):
    files_rows, events_rows, extracted = _substrate_world()
    digests = set()
    for run in range(2):
        scratch = tmp_path / f"task-{run}"
        _write_store(scratch, files_rows, events_rows, extracted)
        digests.add(compute_evidence_world_digest(scratch)["digest"])
    assert len(digests) == 1


def test_equivalence_check_reports_reproducibility_violation(tmp_path):
    from httpserver.services.benchmarks.holdout_contract_v3 import (
        provisioning_equivalence_check,
    )

    tree = _gen3_tree(tmp_path)
    substrate = tree["substrate"]
    manifest = tree["manifest"]

    calls = {"n": 0}

    def fake_provision(image_path, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return tree["world"]
        drifted = {
            "digest": "d" * 64,
            "payload": tree["world"]["payload"],
        }
        return drifted

    import httpserver.services.benchmarks.holdout_contract_v3 as v3

    original = v3.provision_and_digest
    v3.provision_and_digest = fake_provision
    try:
        result = provisioning_equivalence_check(
            substrate,
            manifest,
            tree["world"]["digest"],
            images_dir=tree["images"],
        )
    finally:
        v3.provision_and_digest = original
    assert not result["ok"]
    assert any("reproducible" in v for v in result["violations"])


# -- §37: Agent-visible completeness includes the substrate identity -------------


def test_substrate_identity_is_hash_bound_in_seal(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    # mutate the substrate record (different image identity) -> seal and
    # verification must diverge
    substrate_path = tree["substrates"] / "gen3-example.substrate.json"
    payload = json.loads(substrate_path.read_text(encoding="utf-8"))
    payload["image_sha256"] = "a" * 64
    substrate_path.write_text(json.dumps(payload), encoding="utf-8")
    violations = verify_holdout_seal_v3(seal, **_gate_kwargs(tree))
    assert any("SUBSTRATE_IMAGE_HASH_MISMATCH" in v for v in violations)
    assert any("evidence_substrate_hashes" in v for v in violations)


def test_seal_covers_all_agent_visible_domains(tmp_path):
    tree = _gen3_tree(tmp_path)
    seal = _build_seal(tree)
    for section in (
        "public_case_hashes",
        "public_asset_hashes",
        "truth_hashes",
        "evidence_substrate_hashes",
        "evidence_world_digests",
        "evidence_manifest_hashes",
        "parser_config_hash",
        "bootstrap_transform",
        "evaluator",
        "acceptance_profile_sha256",
        "calibration_binding_sha256",
        "runtime_investigation_subtree_hash",
        "model_config_hash",
    ):
        value = getattr(seal, section)
        assert value, f"seal section {section} must be populated"
