#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Explicit second-stage file/query/report/source checks of private candidate packages."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raid.core import RaidError
from raid.export import write_json
from raid.results import create_results, read_back
from raid.pipeline import analyze_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--inbox", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--max-files", type=int, default=128)
    args = parser.parse_args()
    batch = args.summary.resolve(strict=True).parent
    source = json.loads(args.summary.read_text())
    results = []
    for row in source["results"]:
        item = {"sample_id": row["sample_id"], "status": "NOT_RUN"}
        try:
            if row["inference_status"] != "UNIQUE_STRUCTURAL_CANDIDATE":
                item["status"] = "UNRESOLVED_NOT_ANALYZED"
            else:
                package = Path(row["package_directory"]).resolve(strict=True)
                if package.parent != batch:
                    raise RaidError("PACKAGE_ESCAPES_SELECTED_BATCH")
                chosen = json.loads((batch / (row["sample_id"] + "-inference.json")).read_text())["candidates"][0]
                item["files"] = create_results(args.inbox, package, volume_offset=chosen["volume_offset"],
                                               allow_partial=True, max_files=args.max_files)
                with sqlite3.connect(f"file:{package / 'file-results/results.db'}?mode=ro", uri=True) as db:
                    ids = [r[0] for r in db.execute("SELECT record_id FROM files WHERE status='READABLE' AND size>0 ORDER BY size LIMIT 1")]
                back = [read_back(args.inbox, package, identifier, allow_partial=True) for identifier in ids]
                write_json(package / "source-readback-samples.json", back)
                item["source_readback_count"] = len(back)
                item["native"] = analyze_package(package, args.analyzer, allow_partial=True)
                item["status"] = "PASS_BOUNDED_ANALYSIS_AND_SOURCE" if ids else "SOURCE_RECORD_NOT_AVAILABLE"
        except Exception as exc:
            item["status"] = "FAILED_OR_PARTIAL"
            item["error_code"] = str(exc) if isinstance(exc, RaidError) else type(exc).__name__
        results.append(item)
        write_json(batch / (row["sample_id"] + "-analysis-check.json"), item)
        print(json.dumps({"sample_id": item["sample_id"], "status": item["status"],
                          "source_readback_count": item.get("source_readback_count"),
                          "native_files": item.get("native", {}).get("file_count"),
                          "error": item.get("error_code")}), flush=True)
    write_json(batch / "analysis-summary.json", {"schema_version": 1, "status": "PARTIAL",
               "results": results, "max_files_checked_per_group": args.max_files,
               "warnings": ["FILE_ENUMERATION_LIMIT_REACHED", "CONTENT_REFERENCE_VALIDATION_REQUIRED",
                            "WEB_INTEGRATION_PENDING"]})


if __name__ == "__main__": main()
