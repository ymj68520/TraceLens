"""RCA-2A §2/§7 — Supervisor INTEGRATE contract schema audit.

Generates the ACTUAL PydanticAI-visible output-tool schema from the current
production models (same transformer the bridge uses for model-facing tool
schemas) and derives every complexity figure from that generated artifact —
never from documentation.

Outputs benchmarks/audits/cross-model-root-cause-audit-v1/
integration-schema-audit-v1.json with:
  raw + model-facing (inlined-$defs) schema bytes
  $defs counts, max nesting depth, anyOf/union branches, enums + values,
  required fields, per-action field/constraint inventory
for:
  SupervisorIntegrationDecisionV2   (production INTEGRATE contract)
  SupervisorPlanDecisionV2          (the stage that never failed — baseline)

Zero model calls; read-only.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

PYTHON_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(PYTHON_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT))

from httpserver.services.investigation.agent_integration_v2 import (  # noqa: E402
    SupervisorIntegrationDecisionV2,
    SupervisorPlanDecisionV2,
)
from pydantic_ai import InlineDefsJsonSchemaTransformer  # noqa: E402

OUT = (
    PYTHON_SERVICE_ROOT
    / "benchmarks" / "audits" / "cross-model-root-cause-audit-v1"
)


def model_facing_schema(schema: dict) -> dict:
    """The schema exactly as the model-facing tool would carry it: $defs
    inlined by pydantic-ai's own transformer (the bridge does the same for
    model-visible tool parameter schemas)."""
    return dict(InlineDefsJsonSchemaTransformer(schema).walk())


def max_depth(node, depth: int = 0) -> int:
    if isinstance(node, dict):
        return max(
            [depth] + [max_depth(v, depth + 1) for v in node.values()]
        ) if node else depth
    if isinstance(node, list):
        return max([depth] + [max_depth(v, depth + 1) for v in node]) \
            if node else depth
    return depth


def count_nodes(node, counts: Counter) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            counts[f"key:{key}"] += 1
            if key == "enum" and isinstance(value, list):
                counts["enum_definitions"] += 1
                counts["enum_total_values"] += len(value)
            if key == "anyOf":
                counts["anyOf_branch_groups"] += 1
                counts["anyOf_branches"] += len(value)
            if key in ("oneOf", "allOf"):
                counts[f"{key}_groups"] += 1
            count_nodes(value, counts)
    elif isinstance(node, list):
        for item in node:
            count_nodes(item, counts)


def action_inventory(schema: dict, discriminator: str) -> dict:
    """Per-variant inventory of the actions union (from the generated
    schema, not from code reading)."""
    inv: dict[str, dict] = {}
    stack = [schema]

    def walk(node):
        if isinstance(node, dict):
            props = node.get("properties") or {}
            if discriminator in props:
                variants = []
                for value in props[discriminator].get("enum", []):
                    variants.append(value)
                if variants:
                    inv["__variants__"] = variants
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(schema)
    # per-variant: locate the $defs entries whose discriminator value matches
    for name, definition in (schema.get("$defs") or {}).items():
        props = definition.get("properties") or {}
        disc = props.get(discriminator, {})
        values = disc.get("const") or (
            disc.get("enum")[0] if disc.get("enum") else None)
        if values is None:
            continue
        required = set(definition.get("required") or [])
        fields = {}
        for fname, fspec in props.items():
            fields[fname] = {
                "required": fname in required,
                "type": (
                    fspec.get("type")
                    or ("enum" if "enum" in fspec else None)
                    or ("$ref" if "$ref" in fspec else None)
                    or ("anyOf" if "anyOf" in fspec else None)
                ),
                "enum_values": fspec.get("enum"),
                "ref": fspec.get("$ref"),
                "anyOf": [
                    b.get("$ref") or b.get("type") or "enum"
                    for b in (fspec.get("anyOf") or [])
                ],
                "min_items": fspec.get("minItems"),
                "max_length": fspec.get("maxLength"),
            }
        inv[str(values)] = {
            "def_name": name,
            "field_count": len(props),
            "required_count": len(required),
            "fields": fields,
        }
    inv.pop("__variants__", None)
    return inv


def audit(schema_obj, label: str) -> dict:
    raw = schema_obj.model_json_schema()
    facing = model_facing_schema(raw)
    raw_counts: Counter = Counter()
    facing_counts: Counter = Counter()
    count_nodes(raw, raw_counts)
    count_nodes(facing, facing_counts)
    return {
        "label": label,
        "raw": {
            "schema_bytes": len(json.dumps(raw, sort_keys=True)),
            "defs": len(raw.get("$defs") or {}),
            "def_names": sorted((raw.get("$defs") or {}).keys()),
            "top_level_fields": sorted((raw.get("properties") or {}).keys()),
            "top_level_required": sorted(raw.get("required") or []),
            "max_depth": max_depth(raw),
            "anyOf_branches": raw_counts["anyOf_branches"],
            "enum_definitions": raw_counts["enum_definitions"],
            "enum_total_values": raw_counts["enum_total_values"],
        },
        "model_facing": {
            "schema_bytes": len(json.dumps(facing, sort_keys=True)),
            "defs_remaining": len(facing.get("$defs") or {}),
            "max_depth": max_depth(facing),
            "anyOf_branches": facing_counts["anyOf_branches"],
            "enum_definitions": facing_counts["enum_definitions"],
            "enum_total_values": facing_counts["enum_total_values"],
        },
        "actions_union": action_inventory(
            raw, "action_type" if label.startswith("integrate") else
            "action_kind"),
    }


def proposal_metrics() -> dict:
    """The experimental draft proposal (benchmarks tree, production-isolated)
    measured with the SAME machinery."""
    sys.path.insert(0, str(PYTHON_SERVICE_ROOT.parent))
    from benchmarks.contracts.experimental.integration_proposal_v1 import (
        SupervisorIntegrationProposalV1,
    )

    return audit(SupervisorIntegrationProposalV1, "proposal_v1_draft")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "artifact_version": "IntegrationSchemaAuditV1",
        "method": (
            "schema generated from the CURRENT production models via "
            "pydantic model_json_schema + pydantic-ai "
            "InlineDefsJsonSchemaTransformer (the same transform the "
            "model-facing tool bridge applies); all figures derive from "
            "the generated schema"
        ),
        "integrate_v2": audit(SupervisorIntegrationDecisionV2, "integrate_v2"),
        "plan_v2": audit(SupervisorPlanDecisionV2, "plan_v2"),
        "proposal_v1_draft": proposal_metrics(),
        "complexity_comparison_note": (
            "complexity reduction is DEMONSTRATED only; model reliability "
            "improvement is UNVERIFIED (no output-tool params or field-"
            "level errors exist for the 11 historical INTEGRATE retry "
            "exhaustions — RCA-1 audit finding F-3/F-10)"
        ),
    }
    out = OUT / "integration-schema-audit-v1.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    for key in ("integrate_v2", "plan_v2", "proposal_v1_draft"):
        r = report[key]
        print(f"{key}: raw {r['raw']['schema_bytes']}B defs={r['raw']['defs']} "
              f"depth={r['raw']['max_depth']} anyOf={r['raw']['anyOf_branches']} "
              f"enums={r['raw']['enum_definitions']}"
              f"({r['raw']['enum_total_values']} values) | facing "
              f"{r['model_facing']['schema_bytes']}B "
              f"depth={r['model_facing']['max_depth']}")
        variants = r["actions_union"]
        print(f"  actions: {len(variants)} variants: {sorted(variants)}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
