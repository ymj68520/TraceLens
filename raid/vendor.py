# SPDX-License-Identifier: AGPL-3.0-or-later
"""Load only pinned local upstream source; no pip, downloads or fallback."""
from __future__ import annotations

import hashlib
import importlib
import json
from functools import lru_cache
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1] / "third_party" / "raid"


@lru_cache(maxsize=32)
def load(name: str, module: str):
    spec = next(p for p in json.loads((ROOT / "sources.lock.json").read_text())["projects"] if p["name"] == name)
    root = ROOT / "upstream" / name
    manifest = json.loads((root / "SOURCE.json").read_text())
    if manifest["commit"] != spec["commit"]:
        raise RuntimeError("RAID_DEPENDENCY_PIN_MISMATCH")
    for relative, info in manifest["files"].items():
        path = root / relative
        if not path.resolve().is_relative_to(root.resolve()):
            raise RuntimeError("RAID_DEPENDENCY_PATH_ESCAPE")
        if "sha256" in info and hashlib.sha256(path.read_bytes()).hexdigest() != info["sha256"]:
            raise RuntimeError("RAID_DEPENDENCY_BYTES_CHANGED")
    sys.dont_write_bytecode = True
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    result = importlib.import_module(module)
    if not Path(result.__file__).resolve().is_relative_to(root.resolve()):
        raise RuntimeError("RAID_DEPENDENCY_SHADOWED")
    return result


def volume():
    load("dissect.util", "dissect.util")
    load("dissect.cstruct-4.7", "dissect.cstruct")
    return load("dissect.volume", "dissect.volume.md.md")
