"""
TOON-like transformer for converting database records to Graphiti episodes.

Inspired by the C++ TOONExporter module, this transforms file records with
LLM analysis into a format suitable for Graphiti ingestion.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .database_reader import FileRecord
from .exceptions import TransformationError


@dataclass
class EpisodeData:
    """
    Data structure representing a Graphiti episode.
    
    Each episode corresponds to a file record with LLM analysis,
    formatted for knowledge graph ingestion.
    """
    
    # Episode metadata
    name: str
    episode_body: str  # JSON string
    source_description: str
    reference_time: datetime
    
    # Original record reference
    file_path: str
    file_id: int
    
    # Optional: for saga grouping
    category: Optional[str] = None
    
    @property
    def as_dict(self) -> dict:
        """Convert to dictionary for Graphiti add_episode()."""
        return {
            "name": self.name,
            "episode_body": self.episode_body,
            "source_description": self.source_description,
            "reference_time": self.reference_time,
        }


class TOONTransformer:
    """
    Transforms database FileRecords into Graphiti EpisodeData.
    
    The transformation creates structured episodes that Graphiti can
    process to extract entities and relationships for the knowledge graph.
    """
    
    def __init__(
        self,
        include_metadata: bool = True,
        include_analysis: bool = True,
        source_description: str = "forensics_file_analysis",
    ):
        """
        Initialize transformer.
        
        Args:
            include_metadata: Include file metadata (size, timestamps, etc.)
            include_analysis: Include LLM analysis fields
            source_description: Description for the episode source
        """
        self.include_metadata = include_metadata
        self.include_analysis = include_analysis
        self.source_description = source_description
    
    def transform(self, record: FileRecord) -> EpisodeData:
        """
        Transform a single FileRecord into an EpisodeData.
        
        Args:
            record: The file record to transform.
        
        Returns:
            EpisodeData ready for Graphiti ingestion.
        
        Raises:
            TransformationError: If transformation fails.
        """
        try:
            # Build episode body as structured JSON
            body = self._build_episode_body(record)
            
            # Create episode name from file info
            name = self._create_episode_name(record)
            
            # Use analysis time or current time as reference
            if record.llm_analyzed_at and record.llm_analyzed_at > 0:
                reference_time = datetime.fromtimestamp(
                    record.llm_analyzed_at, tz=timezone.utc
                )
            else:
                reference_time = datetime.now(timezone.utc)
            
            return EpisodeData(
                name=name,
                episode_body=json.dumps(body, ensure_ascii=False),
                source_description=self.source_description,
                reference_time=reference_time,
                file_path=record.path,
                file_id=record.id,
                category=record.category,
            )
        
        except Exception as e:
            raise TransformationError(
                f"Failed to transform record {record.path}: {e}"
            ) from e
    
    def transform_batch(
        self,
        records: list[FileRecord],
        skip_errors: bool = True,
    ) -> tuple[list[EpisodeData], list[tuple[FileRecord, Exception]]]:
        """
        Transform a batch of FileRecords.
        
        Args:
            records: List of file records to transform.
            skip_errors: If True, continue on errors and collect failed records.
        
        Returns:
            Tuple of (successful_episodes, failed_records_with_errors).
        """
        episodes = []
        errors = []
        
        for record in records:
            try:
                episode = self.transform(record)
                episodes.append(episode)
            except TransformationError as e:
                if skip_errors:
                    errors.append((record, e))
                else:
                    raise
        
        return episodes, errors
    
    def _build_episode_body(self, record: FileRecord) -> dict:
        """
        Build the episode body dictionary.
        
        This creates a structured representation of the file that
        Graphiti can use to extract entities and relationships.
        """
        body = {
            "file_name": record.name,
            "file_path": record.path,
            "category": record.category,
            "file_extension": record.extension,
        }
        
        if self.include_metadata:
            body["metadata"] = {
                "size_bytes": record.size,
                "md5_hash": record.md5,
                "is_deleted": record.is_deleted,
                "file_type": record.file_type,
            }
            
            # Add timestamps if available
            if record.mtime_datetime:
                body["metadata"]["modified_at"] = record.mtime_datetime.isoformat()
            if record.ctime_datetime:
                body["metadata"]["created_at"] = record.ctime_datetime.isoformat()
        
        if self.include_analysis and record.has_llm_analysis:
            body["analysis"] = {}
            
            if record.llm_summary:
                body["analysis"]["summary"] = record.llm_summary
            
            if record.llm_description:
                body["analysis"]["description"] = record.llm_description
            
            if record.llm_keywords:
                body["analysis"]["keywords"] = record.keywords_list
            
            if record.llm_model_used:
                body["analysis"]["model"] = record.llm_model_used
        
        return body
    
    def _create_episode_name(self, record: FileRecord) -> str:
        """
        Create a descriptive name for the episode.
        """
        # Use category and filename for episode name
        category = record.category or "file"
        name = record.name or f"file_{record.id}"
        return f"{category}:{name}"
    
    def to_toon_format(self, records: list[FileRecord]) -> str:
        """
        Export records to TOON text format (similar to C++ TOONExporter).
        
        This is an alternative output format that can be used for
        debugging or direct text-based processing.
        
        Args:
            records: List of file records.
        
        Returns:
            TOON-formatted string.
        """
        lines = []
        
        # Schema header
        fields = ["name", "path", "category", "size", "llm_summary", "llm_keywords"]
        lines.append(f"TOON.schema: {' | '.join(fields)}")
        lines.append(f"# records[{len(records)}]")
        
        # Data rows
        for record in records:
            values = [
                self._escape_value(record.name),
                self._escape_value(record.path),
                self._escape_value(record.category),
                str(record.size),
                self._escape_value(record.llm_summary or ""),
                self._escape_value(record.llm_keywords or ""),
            ]
            lines.append(" | ".join(values))
        
        return "\n".join(lines)
    
    @staticmethod
    def _escape_value(value: str) -> str:
        """Escape special characters in TOON value."""
        if not value:
            return '""'
        
        needs_quoting = any(c in value for c in '|"\n\r,')
        needs_quoting = needs_quoting or value[0].isspace() or value[-1].isspace()
        
        if not needs_quoting:
            return value
        
        escaped = value.replace('"', '""').replace('\n', '\\n').replace('\r', '\\r')
        return f'"{escaped}"'
