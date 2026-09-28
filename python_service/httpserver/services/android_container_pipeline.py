"""A bounded, read-only-source Android sparse/super normalization pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os

from .android_image_preflight import inspect as inspect_userdata
from .android_lp_image import (LpError, AndroidSuperImageProbe, derive_super_region,
                               extract_selected, select_partitions)
from .android_sparse_image import (SparseError, file_sha256, normalize_sparse,
                                   validate_sparse, SPARSE_MAGIC)

MAX_NORMALIZATION_DEPTH = 3


class NormalizationError(ValueError):
    pass


def _is_sparse(path: Path) -> bool:
    with path.open("rb") as source:
        return source.read(4) == SPARSE_MAGIC.to_bytes(4, "little")


def _plan_fingerprint(kind: str, source_sha256: str, sparse: dict | None,
                      region: dict | None, super_inventory: dict | None,
                      userdata: dict | None, slot: int) -> str:
    selected = (super_inventory or {}).get("partitions", [])
    payload = {
        "kind": kind, "source_sha256": source_sha256, "slot": slot,
        "expanded_size": (sparse or {}).get("expanded_size"),
        "chunk_count": (sparse or {}).get("chunk_count"),
        "region": {k: region.get(k) for k in ("offset", "size", "partition_number")}
                  if region else None,
        "metadata_version": (super_inventory or {}).get("metadata_version"),
        "metadata_slot_count": (super_inventory or {}).get("metadata_slot_count"),
        "partitions": [{k: item.get(k) for k in ("name", "size", "attributes",
                                                 "group_name", "first_extent_index", "extent_count")}
                       for item in selected],
        "extents": (super_inventory or {}).get("extents", []),
        "userdata_fs": ((userdata or {}).get("selected_partition") or {}).get("kind"),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def inspect_container(source: Path, work: Path, *, source_sha256: str,
                      full_hash: bool, selected_slot: int = 0,
                      retain_derived: bool = False) -> dict:
    """Classify sparse userdata, raw/sparse super or full-disk super.

    Preflight derivatives are preview-only and removed on exit. Task-owned
    derivatives are retained and hashed in the normalization manifest.
    """
    source = Path(source).resolve(strict=True)
    work = Path(work)
    if source.is_symlink() or not source.is_file() or not 0 <= selected_slot <= 31:
        raise NormalizationError("INVALID_NORMALIZATION_INPUT")
    if not work.is_dir() or work.is_symlink():
        raise NormalizationError("NORMALIZATION_WORKDIR_REQUIRED")
    result = {"kind": "NOT_CONTAINER", "ready": False, "selected_slot": selected_slot,
              "active_slot": "ACTIVE_SLOT_UNKNOWN", "warnings": [], "steps": []}
    current = source
    current_hash = source_sha256
    generated: list[Path] = []
    sparse = None
    try:
        if _is_sparse(source):
            sparse = validate_sparse(source)
            result["sparse"] = sparse
            if sparse["validation_status"] != "VALIDATED":
                result.update(kind="ANDROID_SPARSE_UNREADY", reason=sparse.get("error", "SPARSE_INVALID"))
                return result
            if not full_hash or not source_sha256:
                result.update(kind="ANDROID_SPARSE_UNREADY", reason="FULL_HASH_REQUIRED")
                return result
            raw = work / "unsparsed.raw"
            conversion = normalize_sparse(source, raw, sparse, expected_sha256=source_sha256)
            generated.append(raw)
            current, current_hash = raw, conversion["derived_sha256"]
            result["sparse_conversion"] = conversion
            result["steps"].append({"operation": "UNSPARSE", "input_sha256": source_sha256,
                                     "output_sha256": current_hash,
                                     "input_format": "android_sparse", "output_format": "raw",
                                     "tool": conversion["tool"], "tool_version": conversion["tool_version"],
                                     "parameters": {"expanded_size": sparse["expanded_size"]},
                                     "status": "SUCCESS", "warnings": sparse.get("warnings", [])})
            if len(result["steps"]) > MAX_NORMALIZATION_DEPTH:
                raise NormalizationError("NORMALIZATION_DEPTH_LIMIT")

        regions = AndroidSuperImageProbe.find_regions(current)
        if len(regions) > 1:
            result.update(kind="MULTIPLE_SUPER_REGIONS", reason="EXPLICIT_REGION_SELECTION_REQUIRED")
            return result
        if regions:
            region = regions[0]
            result["super_region"] = region
            super_path = current
            if region["offset"] or region["size"] != current.stat().st_size:
                if not full_hash or not source_sha256:
                    result.update(kind="ANDROID_SUPER_UNREADY", reason="FULL_HASH_REQUIRED")
                    return result
                derived = work / "super_partition.raw"
                provenance = derive_super_region(current, region, derived,
                                                 source_sha256=current_hash)
                generated.append(derived)
                super_path = derived
                result["super_partition_derivation"] = provenance
                result["steps"].append({"operation": "SUPER_PARTITION_COPY",
                                         "input_sha256": current_hash,
                                         "output_sha256": provenance["derived_super_sha256"],
                                         "input_format": "raw_or_e01_disk", "output_format": "raw_super",
                                         "tool": "qnxprobe_readonly_block_view",
                                         "tool_version": "pinned-qnxprobe-1.34",
                                         "parameters": {"partition_offset": region["offset"],
                                                        "partition_length": region["size"]},
                                         "status": "SUCCESS", "warnings": []})
            inventory = AndroidSuperImageProbe.inspect(super_path, selected_slot)
            result["super_inventory"] = inventory
            if inventory["status"] != "ANDROID_SUPER":
                result.update(kind="MALFORMED_SUPER", reason=inventory.get("reason", "LP_INVALID"))
                return result
            result["available_slots"] = [selected_slot]
            for slot in range(min(int(inventory["metadata_slot_count"]), 32)):
                if slot == selected_slot:
                    continue
                candidate = AndroidSuperImageProbe.inspect(super_path, slot)
                if candidate["status"] == "ANDROID_SUPER":
                    result["available_slots"].append(slot)
                else:
                    result["warnings"].append(f"METADATA_SLOT_{slot}_UNREADABLE")
            result["available_slots"].sort()
            result["source_super_sha256"] = file_sha256(super_path)
            result["super_path"] = str(super_path)
            result["kind"] = "ANDROID_SPARSE_SUPER" if sparse else \
                "ANDROID_RAW_SUPER" if region["offset"] == 0 else "ANDROID_FULL_DISK_SUPER"
            result["ready"] = bool(inventory.get("ready") and full_hash and source_sha256)
            result["reason"] = inventory.get("reason", "LP_METADATA_VALIDATED")
            if result["ready"] and not select_partitions(inventory, slot=selected_slot):
                result["ready"] = False
                result["reason"] = "NO_SUPPORTED_LOGICAL_PARTITIONS"
            result["userdata"] = {"status": "NOT_PRESENT_IN_SOURCE"}
            result["plan_sha256"] = _plan_fingerprint(result["kind"], source_sha256,
                sparse, region, inventory, None, selected_slot)
            return result

        if sparse:
            userdata = inspect_userdata(current)
            result["userdata_preflight"] = userdata
            if selected_slot != 0:
                result.update(kind="ANDROID_SPARSE_UNKNOWN", reason="SLOT_NOT_APPLICABLE_TO_USERDATA")
                return result
            if userdata.get("ready") and userdata.get("selected_partition", {}).get("base") == 0:
                result["kind"] = "ANDROID_SPARSE_USERDATA"
                result["ready"] = True
                result["derived_image"] = str(current)
                result["derived_sha256"] = current_hash
                result["plan_sha256"] = _plan_fingerprint(result["kind"], source_sha256,
                    sparse, None, None, userdata, selected_slot)
            else:
                result.update(kind="ANDROID_SPARSE_UNKNOWN", reason="NO_SUPPORTED_USERDATA_OR_SUPER")
        return result
    finally:
        if not retain_derived:
            for item in reversed(generated):
                if item.is_file() and item.parent.resolve() == work.resolve():
                    item.unlink()
            # These fields describe a preview, not a retained Task derivative.
            if generated:
                result["preview_removed"] = True
            if "sparse_conversion" in result:
                result["sparse_conversion"]["derived_path"] = None
            if "super_partition_derivation" in result:
                result["super_partition_derivation"]["derived_super_path"] = None
            result.pop("derived_image", None)
            result.pop("super_path", None)


def normalize_task(source: Path, work: Path, *, expected_source_sha256: str,
                   expected_plan_sha256: str, selected_slot: int = 0) -> dict:
    source = Path(source).resolve(strict=True)
    work = Path(work).resolve(strict=True)
    if work.name != "android_normalization" or work.parent.name != "work":
        raise NormalizationError("TASK_WORKDIR_CONFINEMENT_FAILED")
    if file_sha256(source) != expected_source_sha256:
        raise NormalizationError("EVIDENCE_CHANGED_AFTER_PREFLIGHT")
    result = inspect_container(source, work, source_sha256=expected_source_sha256,
                               full_hash=True, selected_slot=selected_slot,
                               retain_derived=True)
    if not result["ready"] or result.get("plan_sha256") != expected_plan_sha256:
        raise NormalizationError(result.get("reason", "NORMALIZATION_PLAN_MISMATCH"))
    if file_sha256(source) != expected_source_sha256:
        raise NormalizationError("EVIDENCE_CHANGED_AFTER_PREFLIGHT")
    previous = "original"
    steps = [{"step_id": previous, "parent_step": None, "operation": "SOURCE",
              "input_id": None, "input_sha256": None, "input_format": None,
              "tool": None, "tool_version": None, "parameters": {},
              "output_id": "source", "output_sha256": expected_source_sha256,
              "output_format": "android_sparse" if result.get("sparse") else "raw_or_e01",
              "status": "SUCCESS", "warnings": []}]
    for index, step in enumerate(result["steps"], 1):
        steps.append({"step_id": f"step-{index}", "parent_step": previous,
                      "input_id": steps[-1]["output_id"],
                      "output_id": f"derived-{index}", **step})
        previous = f"step-{index}"
    output = {"status": "COMPLETE", "parser_version": "android-container-normalization-v1",
              "source": str(source), "source_sha256": expected_source_sha256,
              "source_size": source.stat().st_size, "kind": result["kind"],
              "selected_slot": selected_slot, "active_slot": "ACTIVE_SLOT_UNKNOWN",
              "plan_sha256": expected_plan_sha256,
              "created_at": datetime.now(timezone.utc).isoformat(),
              "steps": steps, "warnings": result["warnings"],
              "userdata": result.get("userdata", {}),
              "performance": {"source_size": source.stat().st_size,
                              "expanded_size": (result.get("sparse") or {}).get("expanded_size"),
                              "conversion_seconds": (result.get("sparse_conversion") or {}).get("conversion_seconds"),
                              "bytes_written": (result.get("sparse_conversion") or {}).get("bytes_written")}}
    if result["kind"] == "ANDROID_SPARSE_USERDATA":
        derived = Path(result["derived_image"])
        if file_sha256(derived) != result["derived_sha256"]:
            raise NormalizationError("DERIVED_IMAGE_HASH_MISMATCH")
        userdata = inspect_userdata(derived)
        if not userdata.get("ready"):
            raise NormalizationError("DERIVED_USERDATA_PROBE_FAILED")
        output["userdata"] = {"status": "READY", "filesystem":
                              userdata["selected_partition"]["kind"]}
        output["derived_image"] = str(derived)
        output["derived_sha256"] = result["derived_sha256"]
        output["normalized_kind"] = "userdata"
        steps.append({"step_id": "filesystem", "parent_step": previous,
                      "operation": "FILESYSTEM_PROBE", "input_id": steps[-1]["output_id"],
                      "input_sha256": result["derived_sha256"], "input_format": "raw",
                      "tool": "AndroidImagePreflight", "tool_version": "stage4",
                      "parameters": {"filesystem": output["userdata"]["filesystem"]},
                      "output_id": "userdata-filesystem", "output_sha256": result["derived_sha256"],
                      "output_format": output["userdata"]["filesystem"],
                      "status": "SUCCESS", "warnings": []})
    else:
        inventory = result["super_inventory"]
        super_path = Path(result["super_path"])
        super_hash = file_sha256(super_path)
        if super_hash != result["source_super_sha256"]:
            raise NormalizationError("DERIVED_SUPER_HASH_MISMATCH")
        partitions_dir = work / "super"
        partitions_dir.mkdir(mode=0o700)
        partitions, metrics = extract_selected(super_path, inventory, partitions_dir,
            slot=selected_slot, source_sha256=super_hash,
            source_image_sha256=expected_source_sha256)
        if len(steps) + 1 > MAX_NORMALIZATION_DEPTH + 1:
            raise NormalizationError("NORMALIZATION_DEPTH_LIMIT")
        super_input_id = steps[-1]["output_id"]
        for index, partition in enumerate(partitions, 1):
            steps.append({"step_id": f"lp-{index}", "parent_step": previous,
                          "operation": "LOGICAL_PARTITION_EXTRACT",
                          "input_id": super_input_id,
                          "input_sha256": super_hash, "input_format": "raw_super",
                          "tool": "lpunpack", "tool_version": partition["tool_version"],
                          "parameters": {"name": partition["logical_partition_name"],
                                         "slot": selected_slot,
                                         "extent_mapping": partition["extent_mapping"]},
                          "output_id": partition["logical_partition_name"],
                          "output_sha256": partition["derived_partition_sha256"],
                          "output_format": partition["filesystem_type"],
                          "status": "SUCCESS" if partition["filesystem_type"] in ("EXT4", "F2FS")
                              else "UNSUPPORTED_FILESYSTEM", "warnings": []})
        output["normalized_kind"] = "super"
        output["super_inventory"] = inventory
        output["partition_provenance"] = partitions
        output["performance"].update(metrics)
        output["userdata"] = {"status": "NOT_PRESENT_IN_SOURCE"}
    if file_sha256(source) != expected_source_sha256:
        raise NormalizationError("EVIDENCE_CHANGED_AFTER_PREFLIGHT")
    manifest_path = work.parent.parent / "android_normalization_manifest.json"
    temporary = manifest_path.with_suffix(".json.tmp")
    with temporary.open("x", encoding="utf-8") as sink:
        json.dump(output, sink, ensure_ascii=False, indent=2)
        sink.flush()
        os.fsync(sink.fileno())
    os.replace(temporary, manifest_path)
    output["manifest_path"] = str(manifest_path)
    return output


class AndroidImageNormalizationPipeline:
    MAX_NORMALIZATION_DEPTH = MAX_NORMALIZATION_DEPTH

    @staticmethod
    def inspect(source: Path, work: Path, *, source_sha256: str,
                full_hash: bool, selected_slot: int = 0,
                retain_derived: bool = False) -> dict:
        return inspect_container(source, work, source_sha256=source_sha256,
                                 full_hash=full_hash, selected_slot=selected_slot,
                                 retain_derived=retain_derived)

    @staticmethod
    def normalize(source: Path, work: Path, *, expected_source_sha256: str,
                  expected_plan_sha256: str, selected_slot: int = 0) -> dict:
        return normalize_task(source, work, expected_source_sha256=expected_source_sha256,
                              expected_plan_sha256=expected_plan_sha256,
                              selected_slot=selected_slot)
