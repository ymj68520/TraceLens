#!/usr/bin/env python3
"""Fixed-argv Task bridge for Android image normalization (no shell/eval)."""

from __future__ import annotations

import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python_service"))
from httpserver.services.android_container_pipeline import AndroidImageNormalizationPipeline  # noqa: E402


if __name__ == "__main__":
    try:
        if len(sys.argv) != 6:
            raise ValueError("INVALID_ARGUMENT_COUNT")
        source, work, source_sha256, plan_sha256, slot_text = sys.argv[1:]
        if len(source_sha256) != 64 or len(plan_sha256) != 64 or \
                not all(ch in "0123456789abcdef" for ch in source_sha256 + plan_sha256):
            raise ValueError("INVALID_HASH_ARGUMENT")
        slot = int(slot_text)
        result = AndroidImageNormalizationPipeline.normalize(Path(source), Path(work),
                                expected_source_sha256=source_sha256,
                                expected_plan_sha256=plan_sha256,
                                selected_slot=slot)
        print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "code": str(exc).split(":", 1)[0][:100]}),
              file=sys.stderr)
        raise SystemExit(2)
