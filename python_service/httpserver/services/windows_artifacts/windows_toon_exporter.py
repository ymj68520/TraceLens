"""
Windows Artifacts TOON Exporter — Export Windows artifacts to TOON format.

This module converts Windows artifact records to TOON (Token-Oriented Object Notation)
format for efficient LLM prompt integration.
"""

import logging
import sqlite3
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class WindowsArtifactTOONExporter:
    """Export Windows artifacts to TOON format."""

    # Field definitions for each artifact type
    ARTIFACT_SCHEMAS = {
        "registry_values": {
            "fields": ["key_path", "value_name", "value_data", "value_type", "last_modified", "summary", "keywords"],
            "display_name": "注册表记录",
        },
        "event_log_entries": {
            "fields": ["log_name", "event_id", "level", "source", "timestamp", "computer", "message", "summary"],
            "display_name": "事件日志",
        },
        "prefetch_files": {
            "fields": ["executable_name", "prefetch_hash", "run_count", "last_run_time", "file_path", "summary", "keywords"],
            "display_name": "Prefetch文件",
        },
        "browser_history": {
            "fields": ["url", "title", "visit_count", "last_visit", "browser_name", "summary", "keywords"],
            "display_name": "浏览器历史",
        },
        "usb_devices": {
            "fields": ["device_name", "vendor_id", "product_id", "serial_number", "first_connected", "last_connected", "summary"],
            "display_name": "USB设备",
        },
        "user_accounts": {
            "fields": ["username", "sid", "full_name", "account_type", "last_login", "login_count", "summary"],
            "display_name": "用户账户",
        },
        "windows_services": {
            "fields": ["service_name", "display_name", "binary_path", "start_type", "service_type", "state", "summary"],
            "display_name": "Windows服务",
        },
    }

    def __init__(self, delimiter: str = " | "):
        """
        Initialize TOON exporter.

        Args:
            delimiter: Field delimiter (default: " | ")
        """
        self.delimiter = delimiter

    def export_artifacts_toon(
        self,
        windows_db_path: str,
        artifact_type: Optional[str] = None,
        include_llm: bool = True,
        limit: Optional[int] = None,
        severity: Optional[str] = None,
    ) -> str:
        """
        Export Windows artifacts to TOON format.

        Args:
            windows_db_path: Path to _windows.db
            artifact_type: Specific artifact type (None = all with LLM analysis)
            include_llm: Include LLM analysis fields
            limit: Maximum records to export
            severity: Optional severity filter (bound as a query parameter)

        Returns:
            TOON formatted string
        """
        try:
            with sqlite3.connect(windows_db_path) as conn:
                conn.row_factory = sqlite3.Row

                if artifact_type:
                    # Export specific artifact type
                    return self._export_single_type(conn, artifact_type, include_llm, limit, severity)
                else:
                    # Export all artifacts with LLM analysis
                    return self._export_all_with_llm(conn, include_llm, limit, severity)

        except Exception as e:
            logger.error(f"Error exporting to TOON: {e}", exc_info=True)
            return "# Error: TOON export failed"

    def _export_single_type(
        self,
        conn: sqlite3.Connection,
        artifact_type: str,
        include_llm: bool,
        limit: Optional[int],
        severity: Optional[str],
    ) -> str:
        """Export a single artifact type to TOON format."""
        schema_info = self.ARTIFACT_SCHEMAS.get(artifact_type)
        if not schema_info:
            return f"# Error: Unsupported artifact type: {artifact_type}"

        # Build base fields
        base_fields = schema_info["fields"]

        # Add LLM fields if requested
        if include_llm:
            export_fields = base_fields + ["summary", "keywords"]
        else:
            export_fields = base_fields

        # Build query
        if include_llm:
            # Join with artifact_descriptions table
            query = f"""
                SELECT a.*, d.summary, d.keywords, d.severity
                FROM {artifact_type} a
                LEFT JOIN windows_artifact_descriptions d
                    ON d.artifact_type = '{artifact_type}' AND d.artifact_id = a.id
                WHERE 1=1
            """
            params = []
        else:
            query = f"SELECT * FROM {artifact_type} WHERE 1=1"
            params = []

        if severity:
            if not include_llm:
                return "# Severity filtering requires LLM fields"
            query += " AND d.severity = ?"
            params.append(severity)

        query += " ORDER BY a.id"
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        cur = conn.execute(query, params)
        rows = cur.fetchall()

        if not rows:
            return f"# No {schema_info['display_name']} found"

        # Build TOON output
        lines = [
            f"TOON.schema: {self.delimiter.join(export_fields)}",
            f"# records[{len(rows)}]",
            ""
        ]

        for row in rows:
            values = []
            for field in export_fields:
                value = row[field] if field in row.keys() else ""
                if value is None:
                    value = ""
                values.append(self._escape_value(str(value)))
            lines.append(self.delimiter.join(values))

        return "\n".join(lines)

    def _export_all_with_llm(
        self,
        conn: sqlite3.Connection,
        include_llm: bool,
        limit: Optional[int],
        severity: Optional[str] = None,
    ) -> str:
        """Export all artifacts with LLM analysis to TOON format."""
        # Get all artifacts with LLM descriptions
        params: list = []
        query = """
            SELECT artifact_type, artifact_id, summary, description, keywords, severity
            FROM windows_artifact_descriptions
        """
        if severity:
            query += " WHERE severity = ?"
            params.append(severity)
        query += " ORDER BY relevance DESC"
        if limit:
            query += " LIMIT ?"
            params.append(limit)

        cur = conn.execute(query, params)
        descriptions = cur.fetchall()

        if not descriptions:
            return "# No Windows artifact descriptions found"

        # Group by artifact type
        by_type: Dict[str, List[Dict]] = {}
        for desc in descriptions:
            atype = desc["artifact_type"]
            if atype not in by_type:
                by_type[atype] = []
            by_type[atype].append(desc)

        # Build TOON output with sections
        lines = []
        for atype, descs in by_type.items():
            schema_info = self.ARTIFACT_SCHEMAS.get(atype)
            if not schema_info:
                continue

            lines.append(f"## {schema_info['display_name']}")
            lines.append(f"TOON.schema: artifact_id{self.delimiter}summary{self.delimiter}keywords{self.delimiter}severity")
            lines.append(f"# records[{len(descs)}]")
            lines.append("")

            for desc in descs:
                lines.append(f"{desc['artifact_id']}{self.delimiter}{self._escape_value(desc['summary'] or '')}{self.delimiter}{self._escape_value(desc['keywords'] or '')}{self.delimiter}{desc['severity'] or 'low'}")

            lines.append("")

        return "\n".join(lines)

    def export_artifact_batch(
        self,
        artifacts: List[Dict[str, Any]],
        artifact_type: str,
        include_llm: bool = False,
    ) -> str:
        """
        Export a batch of artifact records to TOON format.

        Args:
            artifacts: List of artifact records
            artifact_type: Type of artifacts
            include_llm: Include LLM fields

        Returns:
            TOON formatted string
        """
        schema_info = self.ARTIFACT_SCHEMAS.get(artifact_type)
        if not schema_info:
            return f"# Error: Unsupported artifact type: {artifact_type}"

        base_fields = schema_info["fields"]
        export_fields = base_fields + (["summary", "keywords"] if include_llm else [])

        lines = [
            f"TOON.schema: {self.delimiter.join(export_fields)}",
            f"# records[{len(artifacts)}]",
            ""
        ]

        for artifact in artifacts:
            values = []
            for field in export_fields:
                value = artifact.get(field, "")
                if value is None:
                    value = ""
                values.append(self._escape_value(str(value)))
            lines.append(self.delimiter.join(values))

        return "\n".join(lines)

    def _escape_value(self, value: str) -> str:
        """Escape a value for TOON format."""
        if not value:
            return ""

        # Check if value contains delimiter
        if self.delimiter in value:
            # Quote and escape internal quotes
            return '"' + value.replace('"', '""') + '"'

        # Check if value contains special characters
        if any(c in value for c in ['\n', '\r', '"']):
            return '"' + value.replace('"', '""').replace('\n', '\\n').replace('\r', '\\r') + '"'

        return value

    def get_supported_types(self) -> List[str]:
        """Get list of supported artifact types."""
        return list(self.ARTIFACT_SCHEMAS.keys())

    def get_schema_for_type(self, artifact_type: str) -> Optional[Dict[str, Any]]:
        """Get schema information for an artifact type."""
        return self.ARTIFACT_SCHEMAS.get(artifact_type)
