#!/usr/bin/env python3
"""Fixed-argv bridge that writes a vivo backup's LevelDB index as JSON.

The C++ analyzer cannot read LevelDB without a new dependency, and shelling out
per file would be wasteful. This bridge parses the index once with the proven
Python library and writes a normalised document the extractor can mmap through.

Usage:
    vivo_backup_index_cli.py <backup_root> <output_json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python_service"))

from httpserver.services import vivo_backup_preflight  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print(json.dumps({"status": "ERROR", "code": "INVALID_ARGUMENT_COUNT"}),
              file=sys.stderr)
        return 2
    source = Path(sys.argv[1])
    output = Path(sys.argv[2])
    try:
        detail = vivo_backup_preflight.inspect(source)
        if detail.get("kind") == "unknown_directory":
            raise ValueError("VIVO_BACKUP_NOT_RECOGNIZED")
        # The extractor needs every item, not just counts. Re-read the index
        # with the internal reader so original paths and hashes are present.
        root = vivo_backup_preflight.locate_backup_root(source)
        if root is None:
            raise ValueError("VIVO_BACKUP_ROOT_NOT_FOUND")
        index = vivo_backup_preflight._parse_index(root)

        document = {
            "format": "tracelens-vivo-index-v1",
            "backup_root": str(root),
            "model": detail.get("model"),
            "backup_package_version": detail.get("backup_package_version"),
            "backup_time_ms": detail.get("backup_time_ms"),
            "index_version": detail.get("index_version"),
            "obfuscated": bool(detail.get("payload", {}).get("obfuscated")),
            "items": index.get("items", []),
            "applications": index.get("applications", []),
            "categories": detail.get("categories", []),
            "record_categories": detail.get("record_categories", []),
            "file_categories": detail.get("file_categories", []),
            "item_counts": detail.get("item_counts", {}),
            "warnings": detail.get("warnings", []),
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(output.suffix + ".tmp")
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(document, handle, ensure_ascii=False)
            handle.flush()
        temporary.replace(output)
        print(json.dumps({"status": "OK", "items": len(document["items"]),
                          "applications": len(document["applications"]),
                          "obfuscated": document["obfuscated"]},
                         ensure_ascii=True, separators=(",", ":")))
        return 0
    except Exception as exc:  # surfaced to the C++ caller as a failure code
        print(json.dumps({"status": "ERROR", "code": str(exc).split(":", 1)[0][:100]}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
