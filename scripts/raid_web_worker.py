#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Bounded local worker for the existing task form, no services/models/network."""
import json
from pathlib import Path
import resource
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from raid.core import RaidError, RaidSession, digest_json
from raid.raw import RawRaidSession
from raid.infer import infer
from raid.export import export_array


def main():
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024**2,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (1800, 1801))
    action, input_path = sys.argv[1:]
    path = Path(input_path)
    if path.stat().st_size > 256 * 1024: raise RaidError("WORKER_INPUT_LIMIT")
    data = json.loads(path.read_text())
    root, members = Path(data["source_root"]), data["members"]
    if action == "infer":
        try:
            with RaidSession(root, members) as session:
                result = {"schema_version": 1, "status": "UNIQUE_STRUCTURAL_CANDIDATE",
                          "mode": "md", "source_revision": digest_json(session._fingerprints),
                          "candidates": [{"candidate_id": digest_json(session.manifest()["layout"]),
                            "mode": "md", "plan": {"level": session.level, "layout": session.layout,
                                                     "chunk_size": session.chunk_size},
                            "content_reference_validation": "NOT_RUN"}]}
        except RaidError as exc:
            if str(exc) != "NO_SUPPORTED_MD_METADATA": raise
            result = infer(root, members, timeout=180, max_orders=4096)
            result["mode"] = "raw"
    elif action == "prepare":
        candidate = data["candidate"]
        session = (RaidSession(root, members) if data["mode"] == "md" else
                   RawRaidSession(root, members, candidate["plan"], inference=candidate,
                                  parity_mode="observe" if data["allow_partial"] else "strict"))
        with session:
            if digest_json(session._fingerprints) != data["source_revision"]:
                raise RaidError("SOURCE_CHANGED_SINCE_INFERENCE")
            result = export_array(session, Path(data["output_root"]), max_bytes=data["max_bytes"], timeout=1800)
    else:
        raise RaidError("UNKNOWN_WORKER_ACTION")
    print(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    try: main()
    except Exception as exc:
        print(json.dumps({"status": "FAILED", "code": str(exc) if isinstance(exc, RaidError) else
                          "RAID_WORKER_FAILED"}), file=sys.stderr)
        raise SystemExit(2)
