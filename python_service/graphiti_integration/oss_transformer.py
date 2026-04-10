"""OSS Transformer - Convert OSS objects to Graphiti episodes."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
import json

from .toon_transformer import EpisodeData


@dataclass
class OSSObjectRecord:
    """OSS object record."""
    id: int
    bucket: str
    key: str
    size: int
    content_type: str
    last_modified: int
    llm_summary: Optional[str] = None
    llm_description: Optional[str] = None
    llm_keywords: Optional[str] = None
    llm_analyzed_at: Optional[int] = None
    llm_model_used: Optional[str] = None

    @property
    def has_llm_analysis(self) -> bool:
        return self.llm_analyzed_at is not None


class OSSTransformer:
    """Transform OSS objects to EpisodeData."""

    def transform_oss_object(self, record: OSSObjectRecord) -> EpisodeData:
        """Transform OSS object to EpisodeData."""
        body = {
            "object_name": record.key.split("/")[-1],
            "object_key": record.key,
            "bucket": record.bucket,
            "content_type": record.content_type,
            "size_bytes": record.size,
        }

        if record.last_modified > 0:
            body["last_modified"] = datetime.fromtimestamp(
                record.last_modified, tz=timezone.utc
            ).isoformat()

        if record.has_llm_analysis:
            body["analysis"] = {}
            if record.llm_summary:
                body["analysis"]["summary"] = record.llm_summary
            if record.llm_description:
                body["analysis"]["description"] = record.llm_description
            if record.llm_keywords:
                body["analysis"]["keywords"] = record.llm_keywords.split(",")
            if record.llm_model_used:
                body["analysis"]["model"] = record.llm_model_used

        ref_time = datetime.fromtimestamp(
            record.llm_analyzed_at or record.last_modified or 0,
            tz=timezone.utc
        ) if (record.llm_analyzed_at or record.last_modified) else datetime.now(timezone.utc)

        return EpisodeData(
            name=f"oss:{record.bucket}:{record.key.split('/')[-1]}",
            episode_body=json.dumps(body, ensure_ascii=False),
            source_description="forensics_oss_analysis:oss_objects",
            reference_time=ref_time,
            file_path=f"oss://{record.bucket}/{record.key}",
            file_id=record.id,
            category="oss_object",
        )
