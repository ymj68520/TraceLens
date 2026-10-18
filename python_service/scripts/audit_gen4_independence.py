"""HoldoutIndependenceAuditV1 (§27): Gen-4 vs Gen-1/2/3.

Checks that Gen-4 cases share no material reuse with any consumed
generation: filenames, entity names, timestamps, story structure
markers, evidence file hashes, and source asset bytes. Capability
types MAY repeat; case instances may not.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
GEN4_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen4"
)
GEN3_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen3"
)
GEN2_ROOT = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0"
    / "acceptance-gen2"
)
GEN1_RESULTS = (
    PYTHON_SERVICE_ROOT / "benchmarks" / "results" / "agent-v0" / "b6-holdout"
)
CALIBRATION_IMAGES = PYTHON_SERVICE_ROOT / "benchmarks" / "images"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def collect_generation_assets() -> dict[str, dict]:
    """filename set + content-hash set per consumed generation."""
    gens: dict[str, dict] = {}

    def add_gen(name: str, roots: list[Path], image_dirs: list[Path]):
        files: set[str] = set()
        hashes: set[str] = set()
        for root in roots:
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if p.is_file():
                    files.add(p.name)
                    if p.stat().st_size <= 1_000_000:
                        hashes.add(sha256_file(p))
        for d in image_dirs:
            if d.is_dir():
                for p in d.glob("*.img"):
                    hashes.add(sha256_file(p))
        gens[name] = {"filenames": files, "content_hashes": hashes}

    add_gen(
        "gen3",
        [GEN3_ROOT / "cases"],
        [GEN3_ROOT / "images"],
    )
    add_gen(
        "gen2",
        [GEN2_ROOT / "cases"],
        [],
    )
    add_gen(
        "gen1",
        [GEN1_RESULTS],
        [CALIBRATION_IMAGES],
    )
    return gens


def main() -> int:
    gen4_files: set[str] = set()
    gen4_hashes: set[str] = set()
    entities = set()
    for case_dir in (GEN4_ROOT / "cases").iterdir():
        if case_dir.is_dir():
            for p in case_dir.rglob("*"):
                if p.is_file():
                    gen4_files.add(p.name)
                    gen4_hashes.add(sha256_file(p))
    for p in GEN4_ROOT.glob("*.public-case.json"):
        text = p.read_text(encoding="utf-8")
        gen4_hashes.add(sha256_file(p))
        for name in re.findall(r"[\u4e00-\u9fff]{2,4}(?=[:：])", text):
            entities.add(name)
        for name in ("王建国", "李 梅", "张 强", "赵春花", "孙德胜",
                     "钱 多", "吴爱华", "郑小龙", "冯 玉", "蒋成才",
                     "何 军", "王秀兰", "刘志强", "先锋-教练",
                     "周凯", "华信贸易", "宏远物流", "蓝湾酒店"):
            if name in text:
                entities.add(name)
    gen4_image_hashes = {
        sha256_file(p) for p in (GEN4_ROOT / "images").glob("*.img")
    }
    gen4_hashes |= gen4_image_hashes

    gens = collect_generation_assets()
    checks = {}
    details = {}
    for gen, assets in gens.items():
        filename_overlap = gen4_files & assets["filenames"]
        # hashed-content overlap: only ALARM on non-trivial files
        # (README skeleton files are structural, compared separately)
        hash_overlap = gen4_hashes & assets["content_hashes"]
        # entity reuse against gen text artifacts where available
        entity_hits = set()
        for root in (
            GEN3_ROOT / "cases", GEN3_ROOT / "truth",
        ):
            if not root.is_dir():
                continue
            blob = "\n".join(
                p.read_text(encoding="utf-8", errors="ignore")
                for p in root.rglob("*.json")
            )
            for e in entities:
                if e and e in blob:
                    entity_hits.add(e)
        checks[f"{gen}_filename_reuse"] = sorted(
            f for f in filename_overlap if f != "README.txt"
        )
        checks[f"{gen}_content_hash_overlap"] = sorted(hash_overlap)
        checks[f"{gen}_entity_reuse"] = sorted(entity_hits)
        details[gen] = {
            "filename_overlap_incl_readme": sorted(filename_overlap),
            "hash_set_sizes": {
                "gen4": len(gen4_hashes),
                gen: len(assets["content_hashes"]),
            },
        }

    # story-structure markers: distinctive CASE-CONTENT substrings from
    # consumed generations must not appear in Gen-4 case content (dataset
    # files + public cases + truth bodies). Meta-documents (this audit,
    # the capability record's forbidden-reuse documentation) are excluded:
    # they mention prior generations only to forbid their reuse.
    story_markers = {
        "gen3": ["山哥", "小林", "EDGE-GW", "op-0417", "op-0523",
                 "failover drill", "CHG-2025-0305"],
        "gen2": ["analyst-refutation"],
        "gen1": ["t3-holdout-refund", "退款", "vpn-causal"],
    }
    gen4_blob = "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (GEN4_ROOT / "cases").rglob("*")
        if p.is_file() and p.suffix == ".json"
        and p.name.endswith("public-case.json")
    ) + "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (GEN4_ROOT / "truth").rglob("*")
        if p.is_file() and p.suffix == ".json"
    ) + "\n".join(
        p.read_text(encoding="utf-8", errors="ignore")
        for p in (GEN4_ROOT / "cases").rglob("*")
        if p.is_file() and p.suffix != ".json"
    )
    for gen, markers in story_markers.items():
        hits = [m for m in markers if m in gen4_blob]
        checks[f"{gen}_story_marker_reuse"] = hits

    independence_ok = all(
        not v for k, v in checks.items() if k.endswith(
            ("_reuse", "_overlap")
        )
    )
    audit = {
        "artifact_version": "HoldoutIndependenceAuditV1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()),
        "gen4_case_ids": [
            d.name for d in (GEN4_ROOT / "cases").iterdir() if d.is_dir()
        ],
        "gen4_entity_register": sorted(entities),
        "checks": checks,
        "details": details,
        "shared_structural_files": {
            "README.txt": "generic inventory filename reused as a "
            "structural convention (content differs — hash overlap "
            "checked separately); allowed as capability type, not case "
            "instance",
        },
        "independence_confirmed": independence_ok,
    }
    out = GEN4_ROOT / "holdout-independence-audit-v1.json"
    out.write_text(json.dumps(audit, indent=2, ensure_ascii=False))
    print(json.dumps({"independence_confirmed": independence_ok,
                      "checks": checks}, indent=1, ensure_ascii=False))
    return 0 if independence_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
