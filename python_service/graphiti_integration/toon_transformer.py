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


class ForensicEpisodeTransformer:
    """
    Extended transformer for all forensic data sources.
    
    Converts records from events, Windows, Linux, and Android databases
    into EpisodeData suitable for Graphiti knowledge graph ingestion.
    """

    def __init__(self, source_description: str = "forensics_multi_source"):
        self.source_description = source_description

    # -------------------------------------------------------------------------
    # Timeline Events
    # -------------------------------------------------------------------------

    def transform_event(self, event) -> EpisodeData:
        """Transform a TimelineEvent into an EpisodeData."""
        body = {
            "event_type": event.event_type,
            "file_path": event.file_path,
            "timestamp": event.timestamp,
            "description": event.description,
            "file_size": event.file_size,
            "file_type": event.file_type,
            "inode": event.inode,
        }
        ref_time = (
            datetime.fromtimestamp(event.timestamp, tz=timezone.utc)
            if event.timestamp > 0
            else datetime.now(timezone.utc)
        )
        return EpisodeData(
            name=f"event:{event.event_type}:{event.file_path}",
            episode_body=json.dumps(body, ensure_ascii=False),
            source_description=f"{self.source_description}:events",
            reference_time=ref_time,
            file_path=event.file_path,
            file_id=event.id,
            category="timeline_event",
        )

    def transform_events_batch(
        self, events: list, skip_errors: bool = True
    ) -> tuple[list[EpisodeData], list[tuple]]:
        episodes, errors = [], []
        for ev in events:
            try:
                episodes.append(self.transform_event(ev))
            except Exception as e:
                if skip_errors:
                    errors.append((ev, e))
                else:
                    raise
        return episodes, errors

    # -------------------------------------------------------------------------
    # Windows Artifacts
    # -------------------------------------------------------------------------

    def transform_windows_artifact(self, artifact_type: str, record) -> EpisodeData:
        """Transform a Windows artifact record into an EpisodeData."""
        body = self._windows_to_body(artifact_type, record)
        ref_time = self._extract_timestamp(record, ["last_modified", "timestamp",
            "last_run_time", "last_login", "first_connected", "last_visit"]) 
        return EpisodeData(
            name=f"windows:{artifact_type}:{self._windows_name(artifact_type, record)}",
            episode_body=json.dumps(body, ensure_ascii=False),
            source_description=f"{self.source_description}:windows",
            reference_time=ref_time,
            file_path=getattr(record, "file_path", getattr(record, "key_path", "")),
            file_id=record.id,
            category=f"windows_{artifact_type}",
        )

    def _windows_to_body(self, artifact_type: str, r) -> dict:
        if artifact_type == "registry_values":
            return {"key_path": r.key_path, "value_name": r.value_name,
                    "value_type": r.value_type, "value_data": r.value_data,
                    "last_modified": r.last_modified}
        elif artifact_type == "event_logs":
            return {"log_name": r.log_name, "event_id": r.event_id, "level": r.level,
                    "source": r.source, "timestamp": r.timestamp, "computer": r.computer,
                    "message": r.message, "user_sid": r.user_sid}
        elif artifact_type == "prefetch_files":
            return {"executable_name": r.executable_name, "prefetch_hash": r.prefetch_hash,
                    "run_count": r.run_count, "last_run_time": r.last_run_time,
                    "file_path": r.file_path}
        elif artifact_type == "user_accounts":
            return {"username": r.username, "sid": r.sid, "full_name": r.full_name,
                    "account_type": r.account_type, "last_login": r.last_login,
                    "login_count": r.login_count, "is_disabled": r.is_disabled}
        elif artifact_type == "usb_devices":
            return {"device_name": r.device_name, "vendor_id": r.vendor_id,
                    "product_id": r.product_id, "serial_number": r.serial_number,
                    "first_connected": r.first_connected, "last_connected": r.last_connected}
        elif artifact_type == "browser_history":
            return {"url": r.url, "title": r.title, "visit_count": r.visit_count,
                    "last_visit": r.last_visit, "browser_name": r.browser_name}
        elif artifact_type == "services":
            return {"service_name": r.service_name, "display_name": r.display_name,
                    "binary_path": r.binary_path, "start_type": r.start_type,
                    "account": r.account, "state": r.state}
        return {k: v for k, v in vars(r).items() if not k.startswith("_")}

    def _windows_name(self, artifact_type: str, r) -> str:
        name_fields = {
            "registry_values": "key_path", "event_logs": "source",
            "prefetch_files": "executable_name", "user_accounts": "username",
            "usb_devices": "device_name", "browser_history": "url",
            "services": "service_name",
        }
        field = name_fields.get(artifact_type, "id")
        return str(getattr(r, field, r.id))[:120]

    def transform_windows_batch(
        self, artifact_type: str, records: list, skip_errors: bool = True
    ) -> tuple[list[EpisodeData], list[tuple]]:
        episodes, errors = [], []
        for r in records:
            try:
                episodes.append(self.transform_windows_artifact(artifact_type, r))
            except Exception as e:
                if skip_errors:
                    errors.append((r, e))
                else:
                    raise
        return episodes, errors

    # -------------------------------------------------------------------------
    # Linux Artifacts
    # -------------------------------------------------------------------------

    def transform_linux_artifact(self, artifact_type: str, record) -> EpisodeData:
        """Transform a Linux artifact record into an EpisodeData."""
        body = self._linux_to_body(artifact_type, record)
        ref_time = self._extract_timestamp(record, ["timestamp", "login_time", "last_password_change"])
        return EpisodeData(
            name=f"linux:{artifact_type}:{self._linux_name(artifact_type, record)}",
            episode_body=json.dumps(body, ensure_ascii=False),
            source_description=f"{self.source_description}:linux",
            reference_time=ref_time,
            file_path=getattr(record, "log_file", getattr(record, "home_dir", "")),
            file_id=record.id,
            category=f"linux_{artifact_type}",
        )

    def _linux_to_body(self, artifact_type: str, r) -> dict:
        if artifact_type == "log_entries":
            return {"log_file": r.log_file, "timestamp": r.timestamp, "facility": r.facility,
                    "severity": r.severity, "hostname": r.hostname,
                    "process_name": r.process_name, "pid": r.pid, "message": r.message}
        elif artifact_type == "user_accounts":
            return {"username": r.username, "uid": r.uid, "gid": r.gid,
                    "home_dir": r.home_dir, "shell": r.shell, "gecos": r.gecos}
        elif artifact_type == "shell_history":
            return {"username": r.username, "command": r.command,
                    "timestamp": r.timestamp, "shell_type": r.shell_type,
                    "sequence_num": r.sequence_num}
        elif artifact_type == "login_records":
            return {"username": r.username, "terminal": r.terminal, "host": r.host,
                    "login_time": r.login_time, "logout_time": r.logout_time,
                    "login_type": r.login_type}
        elif artifact_type == "groups":
            return {"group_name": r.group_name, "gid": r.gid, "members": r.members}
        return {k: v for k, v in vars(r).items() if not k.startswith("_")}

    def _linux_name(self, artifact_type: str, r) -> str:
        name_fields = {
            "log_entries": "process_name", "user_accounts": "username",
            "shell_history": "command", "login_records": "username",
            "groups": "group_name",
        }
        field = name_fields.get(artifact_type, "id")
        return str(getattr(r, field, r.id))[:120]

    def transform_linux_batch(
        self, artifact_type: str, records: list, skip_errors: bool = True
    ) -> tuple[list[EpisodeData], list[tuple]]:
        episodes, errors = [], []
        for r in records:
            try:
                episodes.append(self.transform_linux_artifact(artifact_type, r))
            except Exception as e:
                if skip_errors:
                    errors.append((r, e))
                else:
                    raise
        return episodes, errors

    # -------------------------------------------------------------------------
    # Android Artifacts
    # -------------------------------------------------------------------------

    def transform_android_artifact(self, artifact_type: str, record) -> EpisodeData:
        """Transform an Android data record into an EpisodeData."""
        body = self._android_to_body(artifact_type, record)
        ref_time = self._extract_timestamp(record, ["timestamp", "date", "last_visit_time",
            "first_install_time", "last_time_used", "last_connected"])
        return EpisodeData(
            name=f"android:{artifact_type}:{self._android_name(artifact_type, record)}",
            episode_body=json.dumps(body, ensure_ascii=False),
            source_description=f"{self.source_description}:android",
            reference_time=ref_time,
            file_path="",
            file_id=record.id,
            category=f"android_{artifact_type}",
        )

    def _android_to_body(self, artifact_type: str, r) -> dict:
        if artifact_type == "contacts":
            return {"display_name": r.display_name, "phone_number": r.phone_number,
                    "email": r.email, "account_type": r.account_type}
        elif artifact_type == "sms_messages":
            return {"address": r.address, "body": r.body, "date": r.date,
                    "type": r.type}
        elif artifact_type == "call_logs":
            return {"number": r.number, "date": r.date, "duration": r.duration,
                    "type": r.type, "name": r.name}
        elif artifact_type.endswith("_messages"):
            return {"platform": getattr(r, "platform", artifact_type.split("_")[0]),
                    "sender": r.sender, "receiver": r.receiver,
                    "content": r.content, "timestamp": r.timestamp}
        elif artifact_type == "chrome_history":
            return {"url": r.url, "title": r.title, "visit_count": r.visit_count,
                    "last_visit_time": r.last_visit_time}
        elif artifact_type == "installed_packages":
            return {"package_name": r.package_name, "version": r.version,
                    "first_install_time": r.first_install_time,
                    "last_update_time": r.last_update_time}
        elif artifact_type == "wifi_networks":
            return {"ssid": r.ssid, "key_mgmt": r.key_mgmt,
                    "last_connected": r.last_connected}
        return {k: v for k, v in vars(r).items() if not k.startswith("_")}

    def _android_name(self, artifact_type: str, r) -> str:
        name_fields = {
            "contacts": "display_name", "sms_messages": "address",
            "call_logs": "number", "whatsapp_messages": "sender",
            "telegram_messages": "sender", "wechat_messages": "sender",
            "chrome_history": "url", "installed_packages": "package_name",
            "wifi_networks": "ssid",
        }
        field = name_fields.get(artifact_type, "id")
        return str(getattr(r, field, r.id))[:120]

    def transform_android_batch(
        self, artifact_type: str, records: list, skip_errors: bool = True
    ) -> tuple[list[EpisodeData], list[tuple]]:
        episodes, errors = [], []
        for r in records:
            try:
                episodes.append(self.transform_android_artifact(artifact_type, r))
            except Exception as e:
                if skip_errors:
                    errors.append((r, e))
                else:
                    raise
        return episodes, errors

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _extract_timestamp(self, record, fields: list[str]) -> datetime:
        """Try to extract a Unix timestamp from one of the given fields."""
        for field in fields:
            val = getattr(record, field, None)
            if val and isinstance(val, (int, float)) and val > 0:
                return datetime.fromtimestamp(val, tz=timezone.utc)
        return datetime.now(timezone.utc)

