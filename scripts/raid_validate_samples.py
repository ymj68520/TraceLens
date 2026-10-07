#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit local sample batch, all outcomes retained; private artifacts only.

Input ordering is randomized. Names/declared directory hints are NOT inference
parameters. No live service, Task, model, kernel device or original image writes.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raid.core import RaidError, digest_json
from raid.infer import infer
from raid.raw import RawRaidSession
from raid.export import export_array, write_json
from raid.results import create_results, read_back
from raid.pipeline import analyze_package


def validate(manifest_path, output_root, *, analyzer=None, inference_timeout=90, max_orders=256,
             only=None, run_analysis=False):
    manifest = json.loads(manifest_path.read_text())
    expected = manifest.pop("manifest_sha256")
    if digest_json(manifest) != expected:
        raise RaidError("SAMPLE_MANIFEST_CHANGED")
    source = Path(manifest["source_root"]).resolve(strict=True)
    output_root = output_root.resolve(strict=True)
    if output_root.is_relative_to(source) or source.is_relative_to(output_root):
        raise RaidError("OUTPUT_MUST_BE_EVIDENCE_DISJOINT")
    output = output_root / ("batch-" + uuid.uuid4().hex)
    output.mkdir(mode=0o700)
    results = []
    known = {item["source_file"]: item for item in manifest["files"]}
    for group in manifest["groups"]:
        if only and group["sample_id"] not in only: continue
        names = list(group["members"])
        random.Random(group["sample_id"]).shuffle(names)
        selected = [{"files": [name]} for name in names]
        entry = {"sample_id": group["sample_id"], "member_count": len(selected),
                 "input_order_randomized": True, "status": "FAILED", "content_reference_validation": "NOT_RUN"}
        try:
            found = infer(source, selected, timeout=inference_timeout, max_orders=max_orders)
            write_json(output / (group["sample_id"] + "-inference.json"), found)
            entry.update(inference_status=found["status"], candidates=len(found["candidates"]),
                         tested_orders=found["tested_orders"], inference_seconds=found["runtime_seconds"])
            if found["status"] != "UNIQUE_STRUCTURAL_CANDIDATE":
                entry["status"] = "NEEDS_REVIEW" if found["candidates"] else "UNRESOLVED"
            else:
                candidate = {**found["candidates"][0], "source_revision": found["source_revision"]}
                with RawRaidSession(source, selected, candidate["plan"], inference=candidate, parity_mode="observe") as session:
                    if digest_json(session._fingerprints) != found["source_revision"]:
                        raise RaidError("SOURCE_CHANGED_SINCE_INFERENCE")
                    actual_hashes = session.source_hashes()
                    if any(actual_hashes[name] != known[name]["sha256"] for name in names):
                        raise RaidError("ORIGINAL_SAMPLE_CHANGED")
                    exported = export_array(session, output, max_bytes=1024**3, timeout=600)
                package = Path(exported["package_directory"])
                entry.update(status="STRUCTURAL_CANDIDATE_MATERIALIZED", package_directory=str(package),
                             package_business_status=exported["status"],
                             parity_mismatching_requests=exported["validation"].get("parity", {}).get("mismatching_requests", 0),
                             logical_sha256=exported["derived_image"]["sha256"], source_unchanged=True)
                if run_analysis:
                    extracted = create_results(source, package, volume_offset=candidate["volume_offset"],
                                               allow_partial=True, max_files=512)
                    entry["file_results"] = extracted
                    with sqlite3.connect(f"file:{package / 'file-results/results.db'}?mode=ro", uri=True) as db:
                        row = db.execute("SELECT record_id FROM files WHERE status='READABLE' AND size>0 ORDER BY size LIMIT 1").fetchone()
                    if row:
                        read = read_back(source, package, row[0], allow_partial=True)
                        write_json(package / "source-readback.json", read)
                        entry["source_readback"] = read["status"]
                    if analyzer:
                        entry["native_analysis"] = analyze_package(package, analyzer, allow_partial=True)
        except Exception as exc:
            entry["error_code"] = str(exc) if isinstance(exc, RaidError) else type(exc).__name__
            if entry["status"] == "STRUCTURAL_CANDIDATE_MATERIALIZED":
                entry["status"] = "ANALYSIS_OR_READBACK_PARTIAL_FAILURE"
        results.append(entry)
        write_json(output / (group["sample_id"] + "-result.json"), entry)
        print(json.dumps({key: entry.get(key) for key in ("sample_id", "status", "inference_status", "candidates",
                         "package_business_status", "source_readback", "error_code")}), flush=True)
    summary = {"schema_version": 1, "status": "PARTIAL", "sample_manifest_sha256": expected,
               "selected_groups": len(results), "outcomes": dict(Counter(r["status"] for r in results)),
               "results": results, "warnings": ["NO_INDEPENDENT_REFERENCE_IMAGE", "TEACHING_SAMPLES_NOT_FIELD_ACCEPTANCE",
                                                  "WEB_TASK_AND_INVESTIGATION_INTEGRATION_PENDING"]}
    write_json(output / "batch-summary.json", summary)
    return {"summary_path": str(output / "batch-summary.json"), "outcomes": summary["outcomes"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path)
    parser.add_argument("--only", action="append")
    parser.add_argument("--analyze", action="store_true")
    parser.add_argument("--inference-timeout", type=int, default=90)
    parser.add_argument("--max-orders", type=int, default=256)
    args = parser.parse_args()
    print(json.dumps(validate(args.manifest, args.output_directory, analyzer=args.analyzer,
                             inference_timeout=args.inference_timeout, max_orders=args.max_orders,
                             only=args.only, run_analysis=args.analyze)))


if __name__ == "__main__": main()
