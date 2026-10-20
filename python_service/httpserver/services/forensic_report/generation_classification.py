"""Internal helpers for the existing report executor, not a separate service.

Only frozen input is read. Classification never changes evidence adoption,
source snapshots, or human review. Legacy report execution remains unchanged.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath

from .models import (
    ClassificationQuestion,
    EvidenceClassificationBatch,
    ReportEvidenceClassification,
)
from .generation_structured import _loads_strict

TOPIC_NAMES = {
    "funds": "资金活动",
    "identity_accounts": "人员账号",
    "communications": "通讯联系",
    "location": "位置轨迹",
    "network": "网络行为",
    "tools": "工具配置",
}
UNCLASSIFIED_GROUP = "unclassified"
UNCLASSIFIED_NAME = "待分类材料"
BATCH_SIZE = 6
BASIS_LIMIT = 1200


def snapshot_hash(item):
    raw = json.dumps(item.snapshot.model_dump(mode="json"), ensure_ascii=False,
                     sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def classification_questions(background):
    """Stable IDs for exact background excerpts; no invented case facts."""
    excerpts = []
    for text in re.split(r"[。！？；\n]+", background):
        text = text.strip()
        for start in range(0, len(text), 500):
            if text[start:start + 500]:
                excerpts.append(text[start:start + 500])
    # Punctuation-heavy backgrounds must not explode the repeated batch input.
    # Fall back to exact contiguous windows, retaining the entire frozen scope.
    if len(excerpts) > 32:
        excerpts = [background[start:start + 500] for start in range(0, len(background), 500)]
    return tuple(ClassificationQuestion(question_id=f"q{i:03}", text=text)
                 for i, text in enumerate(dict.fromkeys(excerpts), 1))


def classification_input(item):
    payload = item.snapshot.payload.model_dump(mode="json")
    states = []
    if payload.get("is_deleted"):
        states.append("deleted")  # deletion does not establish recovery
    if item.snapshot.evidence_type == "android_artifact":
        fields = payload.get("record_fields") or {}
        full = json.dumps(fields, ensure_ascii=False, sort_keys=True) if fields else ""
        basis_type = "android_record"
        material_type = "android_artifact"
        provenance = payload.get("provenance") or {}
        if not provenance.get("input_file") or not provenance.get("original_primary_key"):
            states.append("incomplete_provenance")
    else:
        full = "\n".join(dict.fromkeys(str(payload.get(k) or "").strip()
                                     for k in ("initial_summary", "initial_description"))).strip()
        basis_type = "initial_analysis" if full else "metadata"
        extension = PurePosixPath((payload.get("normalized_path") or "").replace("\\", "/")).suffix.lower()
        material_type = (
            "image" if extension in {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tif", ".tiff"}
            else "log" if extension == ".log"
            else "document" if extension in {".txt", ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".rtf", ".ppt", ".pptx"}
            else "unknown"
        )
        # Existing file snapshots have summaries, not addressable original text.
        states.append("incomplete_provenance")
    if not full:
        states.append("insufficient_content")
    return {
        "evidence_key": item.evidence_key, "material_type": material_type,
        "basis_type": basis_type, "basis_text": full[:BASIS_LIMIT],
        "basis_truncated": len(full) > BASIS_LIMIT,
        "material_states": tuple(states), "source_hash": snapshot_hash(item),
    }


def unassessed_classification(value, *, failed=False):
    return ReportEvidenceClassification(
        evidence_key=value["evidence_key"], material_type=value["material_type"],
        material_states=value["material_states"], basis_type=value["basis_type"],
        basis_truncated=value["basis_truncated"], source_hash=value["source_hash"],
        assessment_status="failed" if failed else "insufficient",
        reason="机器分类未通过校验或暂不可用，保留材料待复核。" if failed else "可用内容不足，暂无法判断业务主题及核查优先级。",
    )


def parse_classifications(content, inputs, questions, model):
    batch = EvidenceClassificationBatch.model_validate(_loads_strict(content))
    by_key = {value["evidence_key"]: value for value in inputs}
    keys = [value.evidence_key for value in batch.classifications]
    if len(keys) != len(set(keys)) or set(keys) != set(by_key):
        raise ValueError("classification must cover exactly the input evidence")
    question_ids = {q.question_id for q in questions}
    results = []
    for suggestion in batch.classifications:
        value = by_key[suggestion.evidence_key]
        if not suggestion.basis_quote.strip() or suggestion.basis_quote not in value["basis_text"]:
            raise ValueError("classification basis does not belong to this input")
        if any(r.question_id not in question_ids for r in suggestion.relations):
            raise ValueError("classification question is outside frozen case context")
        relationships = {r.relation for r in suggestion.relations}
        priority = (
            "P1" if "inconsistent" in relationships or ("supports" in relationships and suggestion.key_issue)
            else "P2" if "supports" in relationships
            else "P3" if relationships == {"background"}
            else "unassessed"
        )
        material_type = value["material_type"]
        if material_type not in ("image", "android_artifact"):
            material_type = suggestion.material_type
            if material_type == "android_artifact":
                raise ValueError("file cannot be relabelled as an Android record")
        results.append(ReportEvidenceClassification(
            evidence_key=suggestion.evidence_key, material_type=material_type,
            topics=suggestion.topics, relations=suggestion.relations,
            priority=priority, material_states=value["material_states"],
            reason=suggestion.reason, basis_quote=suggestion.basis_quote,
            basis_type=value["basis_type"], basis_truncated=value["basis_truncated"],
            source_hash=value["source_hash"], assessment_status="classified",
            model=model or None,
        ))
    return results


def classified_groups(envelope, classifications):
    """One chapter owner, multiple display topics; no path/deletion taxonomy."""
    lookup = {c.evidence_key: c for c in classifications.items}
    groups = {}
    for item in (*envelope.main_evidence, *envelope.appendix_evidence):
        topics = lookup[item.evidence_key].topics
        group = topics[0] if topics else UNCLASSIFIED_GROUP
        groups.setdefault(group, []).append(item)
    return [(key, name, groups[key]) for key, name in
            [*TOPIC_NAMES.items(), (UNCLASSIFIED_GROUP, UNCLASSIFIED_NAME)] if key in groups]
