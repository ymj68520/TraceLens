import hashlib
import json
import re
import unicodedata


def stable_record_id(
    evidence_id: str,
    platform: str,
    category: str,
    source_table: str,
    source_record_id: str,
) -> str:
    canonical = json.dumps(
        [evidence_id, platform, category, source_table, str(source_record_id)],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "rec_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def safe_segment(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).strip().lower()
    slug = re.sub(r"[^a-z0-9_-]+", "-", normalized).strip("-_")[:48]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{slug or 'item'}-{digest}"
