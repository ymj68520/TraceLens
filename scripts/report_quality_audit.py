#!/usr/bin/env python3
"""Report quality audit: narrative strength + thread-table case usefulness.

Objective checks only, computed from the published manifest:

  Thread table (does it help an investigator?)
    - threads that name a case object AND a behaviour
    - coverage: every validated direction lands in a thread
    - size spread: one thread must not swallow the case (max share)
    - low-value (license/icon/manifest) threads are marked and ranked last
    - share of threads that carry anchored key facts

  Narrative (does the report read like a case?)
    - case objects present in the opening chapter (Quasar, 控制端, C2, ...)
    - chapter headings that name an object rather than a material type
    - every chapter carries a closing summary
    - no prompt-internal ids in published prose

Usage: python3 scripts/report_quality_audit.py <manifest.json>
Exit code 1 when a hard gate fails.
"""
import json
import re
import sys
from pathlib import Path

# Reuse the production rule instead of restating it: two regexes drifted once
# already (this audit rejected names the generator considers readable).
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python_service"))
from httpserver.services.forensic_report.generation_stages import (  # noqa: E402
    _THREAD_BEHAVIOUR_RE as THREAD_NAME_BEHAVIOUR,
)
MATERIAL_TYPE_NAME = re.compile(
    r"^(?:prefetch|evtx|pf|dll|exe|日志|事件日志|预取记录?|许可证|清单)", re.IGNORECASE)
ID_RE = re.compile(r"(?<![A-Za-z0-9_])m\d{3,4}(?![A-Za-z0-9_])")
# Case objects this image is known to contain; used to check the opening
# chapter actually names the case rather than the file types.
CASE_TOKENS = ("quasar", "控制端", "4782", "远控", "privazer", "foxmail", "wftp", "crack")


def audit(manifest):
    sections = manifest["sections"]
    stage = manifest.get("stage_analysis") or {}
    directions = stage.get("directions") or []
    first = sections[0] if sections else {}
    table = first.get("thread_table") or {}
    rows = table.get("rows") or []
    problems, notes = [], []

    # ---- thread table ----
    total_dirs = table.get("total_directions") or len(directions)
    covered = table.get("covered_directions") or 0
    if total_dirs and covered != total_dirs:
        problems.append(f"thread coverage {covered}/{total_dirs} is not exhaustive")

    readable = [r for r in rows
                if THREAD_NAME_BEHAVIOUR.search(r["name"])
                and not MATERIAL_TYPE_NAME.match(r["name"].strip())]
    readable_ratio = len(readable) / len(rows) if rows else 0
    if readable_ratio < 0.85:
        problems.append(
            f"only {len(readable)}/{len(rows)} thread names name a case object + behaviour")

    with_facts = [r for r in rows if r.get("key_facts")]
    fact_ratio = len(with_facts) / len(rows) if rows else 0
    if fact_ratio < 0.7:
        problems.append(f"only {len(with_facts)}/{len(rows)} threads carry anchored key facts")

    max_share = (max((r["direction_count"] for r in rows), default=0) / total_dirs) if total_dirs else 0
    if max_share > 0.35:
        problems.append(
            f"one thread holds {max_share:.0%} of all directions "
            f"({max((r['direction_count'] for r in rows), default=0)}/{total_dirs}) — the case is buried")

    low_value = [r for r in rows if r.get("low_value")]
    if low_value:
        indices = [rows.index(r) for r in low_value]
        if indices and min(indices) < len(rows) - len(low_value):
            problems.append("bundled-artifact threads are not ranked last")

    case_in_table = [r["name"] for r in rows
                     if any(tok in r["name"].lower() for tok in CASE_TOKENS)]
    if not case_in_table:
        problems.append("no thread names a known case object (Quasar/控制端/C2/...)")

    # ---- narrative ----
    opening = (first.get("content") or "").lower()
    opening_hits = [tok for tok in CASE_TOKENS if tok in opening]
    if not opening_hits:
        problems.append("opening chapter names no known case object")

    chapters = [s for s in sections if not s.get("recall_table")]
    type_named = [s["heading"] for s in chapters if MATERIAL_TYPE_NAME.match(s["heading"].strip())]
    if len(type_named) > len(chapters) * 0.3:
        problems.append(f"{len(type_named)}/{len(chapters)} chapter headings name a material type")

    missing_summary = [s["heading"] for s in chapters if not s.get("summary")]
    if missing_summary:
        problems.append(f"chapters without a closing summary: {missing_summary}")

    leaks = []
    for s in sections:
        blob = " ".join(str(s.get(k) or "") for k in ("heading", "content", "summary"))
        if ID_RE.search(blob):
            leaks.append(s.get("heading"))
    if leaks:
        problems.append(f"prompt-internal ids in prose: {leaks}")

    return {
        "threads": len(rows),
        "coverage": f"{covered}/{total_dirs}",
        "readable_names": f"{len(readable)}/{len(rows)} ({readable_ratio:.0%})",
        "with_key_facts": f"{len(with_facts)}/{len(rows)} ({fact_ratio:.0%})",
        "largest_thread_share": f"{max_share:.0%}",
        "low_value_threads": [r["name"] for r in low_value],
        "case_named_threads": case_in_table,
        "opening_case_tokens": opening_hits,
        "chapters": len(chapters),
        "type_named_chapters": type_named,
        "problems": problems,
    }


if __name__ == "__main__":
    path = sys.argv[1]
    report = audit(json.load(open(path)))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    sys.exit(1 if report["problems"] else 0)
