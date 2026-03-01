"""
Database reader module for fetching file records from SQLite database.
"""

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator, Iterator, Optional

from .exceptions import DatabaseError


@dataclass
class FileRecord:
    """
    Represents a file record from the database with LLM analysis.
    Mirrors the C++ FileRecordWithLLM structure from TOONExporter.
    """
    
    # Core file metadata
    id: int
    inode: int
    name: str
    path: str
    size: int
    extension: str
    category: str
    file_type: str
    mtime: int  # Unix timestamp
    ctime: int  # Unix timestamp
    is_deleted: bool
    md5: str
    
    # LLM analysis fields
    llm_summary: Optional[str] = None
    llm_description: Optional[str] = None
    llm_keywords: Optional[str] = None
    llm_analyzed_at: Optional[int] = None  # Unix timestamp
    llm_model_used: Optional[str] = None
    
    @property
    def has_llm_analysis(self) -> bool:
        """Check if this record has LLM analysis."""
        return self.llm_analyzed_at is not None and self.llm_analyzed_at > 0
    
    @property
    def mtime_datetime(self) -> Optional[datetime]:
        """Get modification time as datetime."""
        if self.mtime and self.mtime > 0:
            return datetime.fromtimestamp(self.mtime)
        return None
    
    @property
    def ctime_datetime(self) -> Optional[datetime]:
        """Get creation time as datetime."""
        if self.ctime and self.ctime > 0:
            return datetime.fromtimestamp(self.ctime)
        return None
    
    @property
    def keywords_list(self) -> list[str]:
        """Parse keywords string into list."""
        if not self.llm_keywords:
            return []
        # Keywords may be comma-separated or JSON array
        keywords = self.llm_keywords.strip()
        if keywords.startswith("["):
            import json
            try:
                return json.loads(keywords)
            except json.JSONDecodeError:
                pass
        return [k.strip() for k in keywords.split(",") if k.strip()]


class ForensicsDatabase:
    """
    Database reader for forensics SQLite database.
    Provides methods to fetch file records with LLM analysis.
    """
    
    # SQL query to fetch files with LLM data
    SELECT_FILES_SQL = """
        SELECT 
            id, inode, name, path, size, extension, category, type,
            mtime, ctime, is_deleted, md5,
            llm_summary, llm_description, llm_keywords, 
            llm_analyzed_at, llm_model_used
        FROM files
        {where_clause}
        ORDER BY path
        {limit_clause}
        {offset_clause}
    """
    
    COUNT_FILES_SQL = """
        SELECT COUNT(*) FROM files {where_clause}
    """
    
    def __init__(self, db_path: str | Path):
        """
        Initialize database reader.
        
        Args:
            db_path: Path to the SQLite database file.
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise DatabaseError(f"Database not found: {self.db_path}")
        
        self._connection: Optional[sqlite3.Connection] = None
    
    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connection.
        
        Yields:
            SQLite connection object.
        """
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            raise DatabaseError(f"Database connection error: {e}") from e
        finally:
            if conn:
                conn.close()
    
    def _build_where_clause(
        self,
        analyzed_only: bool = False,
        categories: Optional[list[str]] = None,
        min_size: Optional[int] = None,
        max_size: Optional[int] = None,
    ) -> tuple[str, list]:
        """
        Build WHERE clause and parameters for query.
        
        Returns:
            Tuple of (where_clause_string, parameters_list).
        """
        conditions = []
        params = []
        
        if analyzed_only:
            conditions.append("llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0")
        
        if categories:
            placeholders = ", ".join("?" for _ in categories)
            conditions.append(f"category IN ({placeholders})")
            params.extend(categories)
        
        if min_size is not None:
            conditions.append("size >= ?")
            params.append(min_size)
        
        if max_size is not None:
            conditions.append("size <= ?")
            params.append(max_size)
        
        if conditions:
            return "WHERE " + " AND ".join(conditions), params
        return "", params
    
    def count_files(
        self,
        analyzed_only: bool = False,
        categories: Optional[list[str]] = None,
    ) -> int:
        """
        Count files matching the given criteria.
        
        Args:
            analyzed_only: Only count files with LLM analysis.
            categories: Filter by category names.
        
        Returns:
            Number of matching files.
        """
        where_clause, params = self._build_where_clause(
            analyzed_only=analyzed_only,
            categories=categories,
        )
        
        query = self.COUNT_FILES_SQL.format(where_clause=where_clause)
        
        with self.connect() as conn:
            cursor = conn.execute(query, params)
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_files(
        self,
        analyzed_only: bool = False,
        categories: Optional[list[str]] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[FileRecord]:
        """
        Fetch file records from database.
        
        Args:
            analyzed_only: Only fetch files with LLM analysis.
            categories: Filter by category names.
            limit: Maximum number of records to fetch.
            offset: Number of records to skip.
        
        Returns:
            List of FileRecord objects.
        """
        where_clause, params = self._build_where_clause(
            analyzed_only=analyzed_only,
            categories=categories,
        )
        
        limit_clause = f"LIMIT {limit}" if limit else ""
        offset_clause = f"OFFSET {offset}" if offset > 0 else ""
        
        query = self.SELECT_FILES_SQL.format(
            where_clause=where_clause,
            limit_clause=limit_clause,
            offset_clause=offset_clause,
        )
        
        with self.connect() as conn:
            cursor = conn.execute(query, params)
            rows = cursor.fetchall()
            return [self._row_to_record(row) for row in rows]
    
    def iter_files_batched(
        self,
        batch_size: int = 100,
        analyzed_only: bool = False,
        categories: Optional[list[str]] = None,
    ) -> Iterator[list[FileRecord]]:
        """
        Iterate over files in batches.
        
        Args:
            batch_size: Number of records per batch.
            analyzed_only: Only fetch files with LLM analysis.
            categories: Filter by category names.
        
        Yields:
            Lists of FileRecord objects.
        """
        offset = 0
        while True:
            batch = self.get_files(
                analyzed_only=analyzed_only,
                categories=categories,
                limit=batch_size,
                offset=offset,
            )
            if not batch:
                break
            yield batch
            offset += len(batch)
    
    def _row_to_record(self, row: sqlite3.Row) -> FileRecord:
        """Convert a database row to FileRecord."""
        return FileRecord(
            id=row["id"],
            inode=row["inode"] or 0,
            name=row["name"] or "",
            path=row["path"] or "",
            size=row["size"] or 0,
            extension=row["extension"] or "",
            category=row["category"] or "",
            file_type=row["type"] or "",
            mtime=row["mtime"] or 0,
            ctime=row["ctime"] or 0,
            is_deleted=bool(row["is_deleted"]),
            md5=row["md5"] or "",
            llm_summary=row["llm_summary"],
            llm_description=row["llm_description"],
            llm_keywords=row["llm_keywords"],
            llm_analyzed_at=row["llm_analyzed_at"],
            llm_model_used=row["llm_model_used"],
        )
    
    def get_categories(self) -> list[str]:
        """
        Get list of unique categories in the database.
        
        Returns:
            List of category names.
        """
        query = "SELECT DISTINCT category FROM files WHERE category IS NOT NULL ORDER BY category"
        with self.connect() as conn:
            cursor = conn.execute(query)
            return [row[0] for row in cursor.fetchall()]
    
    def get_analysis_stats(self) -> dict:
        """
        Get statistics about LLM analysis in the database.
        
        Returns:
            Dictionary with statistics.
        """
        query = """
            SELECT 
                COUNT(*) as total_files,
                SUM(CASE WHEN llm_analyzed_at IS NOT NULL AND llm_analyzed_at > 0 THEN 1 ELSE 0 END) as analyzed_files,
                SUM(size) as total_size
            FROM files
        """
        with self.connect() as conn:
            cursor = conn.execute(query)
            row = cursor.fetchone()
            if row:
                return {
                    "total_files": row["total_files"],
                    "analyzed_files": row["analyzed_files"],
                    "total_size": row["total_size"],
                    "analysis_percentage": (
                        row["analyzed_files"] / row["total_files"] * 100
                        if row["total_files"] > 0 else 0
                    ),
                }
            return {"total_files": 0, "analyzed_files": 0, "total_size": 0, "analysis_percentage": 0}


# =============================================================================
# Base class for multi-source readers
# =============================================================================

class _BaseForensicsReader:
    """Base reader for forensic SQLite databases with common connection logic."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise DatabaseError(f"Database not found: {self.db_path}")

    @contextmanager
    def connect(self) -> Generator[sqlite3.Connection, None, None]:
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            raise DatabaseError(f"Database connection error: {e}") from e
        finally:
            if conn:
                conn.close()

    def _table_exists(self, table_name: str) -> bool:
        """Check if a table exists in the database."""
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                (table_name,),
            )
            return cursor.fetchone() is not None

    def _count_rows(self, table_name: str) -> int:
        """Count rows in a table."""
        if not self._table_exists(table_name):
            return 0
        with self.connect() as conn:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = cursor.fetchone()
            return row[0] if row else 0

    def _query_table(
        self,
        table_name: str,
        columns: str = "*",
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[sqlite3.Row]:
        """Generic table query with pagination."""
        if not self._table_exists(table_name):
            return []
        query = f"SELECT {columns} FROM {table_name}"
        query += f" LIMIT {limit}" if limit else ""
        query += f" OFFSET {offset}" if offset > 0 else ""
        with self.connect() as conn:
            cursor = conn.execute(query)
            return cursor.fetchall()


# =============================================================================
# Events Database Reader (_events.db)
# =============================================================================

class EventsDatabase(_BaseForensicsReader):
    """Reader for the events/timeline database ({image}_events.db)."""

    def get_events(
        self,
        event_type: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list:
        """Fetch timeline events."""
        from .forensic_data_types import TimelineEvent

        where = f"WHERE event_type = '{event_type}'" if event_type else ""
        query = f"""
            SELECT id, timestamp, event_type, file_path, inode,
                   description, file_size, file_type
            FROM events {where}
            ORDER BY timestamp
        """
        query += f" LIMIT {limit}" if limit else ""
        query += f" OFFSET {offset}" if offset > 0 else ""

        with self.connect() as conn:
            cursor = conn.execute(query)
            return [
                TimelineEvent(
                    id=r["id"],
                    timestamp=r["timestamp"] or 0,
                    event_type=r["event_type"] or "",
                    file_path=r["file_path"] or "",
                    inode=r["inode"] or 0,
                    description=r["description"] or "",
                    file_size=r["file_size"] or 0,
                    file_type=r["file_type"] or "",
                )
                for r in cursor.fetchall()
            ]

    def iter_events_batched(
        self, batch_size: int = 200, event_type: Optional[str] = None
    ) -> Iterator[list]:
        offset = 0
        while True:
            batch = self.get_events(event_type=event_type, limit=batch_size, offset=offset)
            if not batch:
                break
            yield batch
            offset += len(batch)

    def count_events(self) -> int:
        return self._count_rows("events")

    def get_event_stats(self) -> dict:
        """Get event count by type."""
        if not self._table_exists("events"):
            return {}
        with self.connect() as conn:
            cursor = conn.execute(
                "SELECT event_type, COUNT(*) as cnt FROM events GROUP BY event_type"
            )
            return {r["event_type"]: r["cnt"] for r in cursor.fetchall()}


# =============================================================================
# Windows Database Reader (_windows.db)
# =============================================================================

class WindowsDatabase(_BaseForensicsReader):
    """Reader for Windows analysis database ({image}_windows.db)."""

    def get_registry_values(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import WindowsRegistryValue
        rows = self._query_table("registry_values", limit=limit, offset=offset)
        return [
            WindowsRegistryValue(
                id=r["id"], key_path=r["key_path"] or "",
                value_name=r["value_name"] or "", value_type=r["value_type"] or "",
                value_data=r["value_data"] or "", last_modified=r["last_modified"] or 0,
            )
            for r in rows
        ]

    def get_event_logs(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import WindowsEventLog
        rows = self._query_table("event_log_entries", limit=limit, offset=offset)
        return [
            WindowsEventLog(
                id=r["id"], log_name=r["log_name"] or "",
                event_id=r["event_id"] or 0, level=r["level"] or "",
                source=r["source"] or "", timestamp=r["timestamp"] or 0,
                computer=r["computer"] or "", message=r["message"] or "",
                user_sid=r["user_sid"] or "",
            )
            for r in rows
        ]

    def get_prefetch_files(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import WindowsPrefetchInfo
        rows = self._query_table("prefetch_files", limit=limit, offset=offset)
        return [
            WindowsPrefetchInfo(
                id=r["id"], executable_name=r["executable_name"] or "",
                prefetch_hash=r["prefetch_hash"] or "",
                run_count=r["run_count"] or 0,
                last_run_time=r["last_run_time"] or 0,
                file_path=r["file_path"] or "",
            )
            for r in rows
        ]

    def get_user_accounts(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import WindowsUserInfo
        rows = self._query_table("user_accounts", limit=limit, offset=offset)
        return [
            WindowsUserInfo(
                id=r["id"], username=r["username"] or "",
                sid=r["sid"] or "", full_name=r["full_name"] or "",
                account_type=r["account_type"] or "",
                last_login=r["last_login"] or 0,
                login_count=r["login_count"] or 0,
                is_disabled=bool(r["is_disabled"]),
                is_locked=bool(r["is_locked"]),
            )
            for r in rows
        ]

    def get_usb_devices(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import WindowsUSBDevice
        rows = self._query_table("usb_devices", limit=limit, offset=offset)
        return [
            WindowsUSBDevice(
                id=r["id"], device_name=r["device_name"] or "",
                vendor_id=r["vendor_id"] or "", product_id=r["product_id"] or "",
                serial_number=r["serial_number"] or "",
                first_connected=r["first_connected"] or 0,
                last_connected=r["last_connected"] or 0,
                device_class=r["device_class"] or "",
            )
            for r in rows
        ]

    def get_browser_history(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import WindowsBrowserHistory
        rows = self._query_table("browser_history", limit=limit, offset=offset)
        return [
            WindowsBrowserHistory(
                id=r["id"], url=r["url"] or "", title=r["title"] or "",
                visit_count=r["visit_count"] or 0,
                last_visit=r["last_visit"] or 0,
                browser_name=r["browser_name"] or "",
            )
            for r in rows
        ]

    def get_services(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import WindowsService
        rows = self._query_table("windows_services", limit=limit, offset=offset)
        return [
            WindowsService(
                id=r["id"], service_name=r["service_name"] or "",
                display_name=r["display_name"] or "",
                binary_path=r["binary_path"] or "",
                start_type=r["start_type"] or "",
                service_type=r["service_type"] or "",
                account=r["account"] or "", state=r["state"] or "",
            )
            for r in rows
        ]

    def get_stats(self) -> dict:
        """Get Windows database statistics."""
        tables = [
            "registry_values", "event_log_entries", "prefetch_files",
            "user_accounts", "usb_devices", "browser_history",
            "windows_services", "amcache_entries", "srum_entries",
            "lnk_files", "jump_list_entries", "recycle_bin_entries",
        ]
        return {t: self._count_rows(t) for t in tables}

    def get_all_artifacts_batched(self, batch_size: int = 100) -> Iterator[tuple]:
        """Iterate over all artifact types, yielding (artifact_type, records)."""
        methods = [
            ("registry_values", self.get_registry_values),
            ("event_logs", self.get_event_logs),
            ("prefetch_files", self.get_prefetch_files),
            ("user_accounts", self.get_user_accounts),
            ("usb_devices", self.get_usb_devices),
            ("browser_history", self.get_browser_history),
            ("services", self.get_services),
        ]
        for artifact_type, method in methods:
            offset = 0
            while True:
                batch = method(limit=batch_size, offset=offset)
                if not batch:
                    break
                yield artifact_type, batch
                offset += len(batch)


# =============================================================================
# Linux Database Reader (_linux.db)
# =============================================================================

class LinuxDatabase(_BaseForensicsReader):
    """Reader for Linux analysis database ({image}_linux.db)."""

    def get_log_entries(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import LinuxLogEntry
        rows = self._query_table("log_entries", limit=limit, offset=offset)
        return [
            LinuxLogEntry(
                id=r["id"], log_file=r["log_file"] or "",
                timestamp=r["timestamp"] or 0, facility=r["facility"] or "",
                severity=r["severity"] or "", hostname=r["hostname"] or "",
                process_name=r["process_name"] or "", pid=r["pid"] or 0,
                message=r["message"] or "",
            )
            for r in rows
        ]

    def get_user_accounts(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import LinuxUserInfo
        rows = self._query_table("user_accounts", limit=limit, offset=offset)
        return [
            LinuxUserInfo(
                id=r["id"], username=r["username"] or "",
                uid=r["uid"] or 0, gid=r["gid"] or 0,
                home_dir=r["home_dir"] or "", shell=r["shell"] or "",
                gecos=r["gecos"] or "", password_hash=r["password_hash"] or "",
                last_password_change=r["last_password_change"] or 0,
            )
            for r in rows
        ]

    def get_shell_history(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import LinuxShellHistory
        rows = self._query_table("shell_history", limit=limit, offset=offset)
        return [
            LinuxShellHistory(
                id=r["id"], username=r["username"] or "",
                command=r["command"] or "", timestamp=r["timestamp"] or 0,
                shell_type=r["shell_type"] or "",
                sequence_num=r["sequence_num"] or 0,
            )
            for r in rows
        ]

    def get_login_records(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import LinuxLoginRecord
        rows = self._query_table("login_records", limit=limit, offset=offset)
        return [
            LinuxLoginRecord(
                id=r["id"], username=r["username"] or "",
                terminal=r["terminal"] or "", host=r["host"] or "",
                login_time=r["login_time"] or 0,
                logout_time=r["logout_time"] or 0,
                login_type=r["login_type"] or "",
            )
            for r in rows
        ]

    def get_groups(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import LinuxGroupInfo
        rows = self._query_table("groups", limit=limit, offset=offset)
        return [
            LinuxGroupInfo(
                id=r["id"], group_name=r["group_name"] or "",
                gid=r["gid"] or 0, members=r["members"] or "",
            )
            for r in rows
        ]

    def get_stats(self) -> dict:
        tables = ["log_entries", "user_accounts", "shell_history", "login_records", "groups"]
        return {t: self._count_rows(t) for t in tables}

    def get_all_artifacts_batched(self, batch_size: int = 100) -> Iterator[tuple]:
        methods = [
            ("user_accounts", self.get_user_accounts),
            ("shell_history", self.get_shell_history),
            ("login_records", self.get_login_records),
            ("log_entries", self.get_log_entries),
            ("groups", self.get_groups),
        ]
        for artifact_type, method in methods:
            offset = 0
            while True:
                batch = method(limit=batch_size, offset=offset)
                if not batch:
                    break
                yield artifact_type, batch
                offset += len(batch)


# =============================================================================
# Android Database Reader (_android.db)
# =============================================================================

class AndroidDatabase(_BaseForensicsReader):
    """Reader for Android analysis database ({image}_android.db)."""

    def get_contacts(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import AndroidContact
        rows = self._query_table("contacts", limit=limit, offset=offset)
        return [
            AndroidContact(
                id=r["id"], display_name=r["display_name"] or "",
                phone_number=r["phone_number"] or "",
                email=r["email"] or "",
                account_type=r["account_type"] or "",
                account_name=r["account_name"] or "",
            )
            for r in rows
        ]

    def get_sms_messages(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import AndroidSMS
        rows = self._query_table("sms_messages", limit=limit, offset=offset)
        return [
            AndroidSMS(
                id=r["id"], address=r["address"] or "",
                body=r["body"] or "", date=r["date"] or 0,
                date_sent=r["date_sent"] or 0, read=r["read"] or 0,
                type=r["type"] or 0, service_center=r["service_center"] or "",
            )
            for r in rows
        ]

    def get_call_logs(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import AndroidCallLog
        rows = self._query_table("call_logs", limit=limit, offset=offset)
        return [
            AndroidCallLog(
                id=r["id"], number=r["number"] or "",
                date=r["date"] or 0, duration=r["duration"] or 0,
                type=r["type"] or 0, name=r["name"] or "",
                geocoded_location=r["geocoded_location"] or "",
            )
            for r in rows
        ]

    def get_chat_messages(
        self, platform: str = "whatsapp", limit: Optional[int] = None, offset: int = 0,
    ) -> list:
        from .forensic_data_types import AndroidChatMessage
        table_map = {
            "whatsapp": "whatsapp_messages",
            "telegram": "telegram_messages",
            "wechat": "wechat_messages",
        }
        table = table_map.get(platform)
        if not table:
            return []
        rows = self._query_table(table, limit=limit, offset=offset)
        return [
            AndroidChatMessage(
                id=r["id"], platform=platform,
                sender=r["sender"] or "", receiver=r["receiver"] or "",
                content=r["content"] or "", timestamp=r["timestamp"] or 0,
                media_url=r["media_url"] or "", media_type=r["media_type"] or "",
            )
            for r in rows
        ]

    def get_chrome_history(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import AndroidChromeHistory
        rows = self._query_table("chrome_history", limit=limit, offset=offset)
        return [
            AndroidChromeHistory(
                id=r["id"], url=r["url"] or "", title=r["title"] or "",
                visit_count=r["visit_count"] or 0,
                last_visit_time=r["last_visit_time"] or 0,
                typed_count=r["typed_count"] or 0,
            )
            for r in rows
        ]

    def get_installed_packages(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import AndroidInstalledPackage
        rows = self._query_table("installed_packages", limit=limit, offset=offset)
        return [
            AndroidInstalledPackage(
                id=r["id"], package_name=r["package_name"] or "",
                code_path=r["code_path"] or "",
                first_install_time=r["first_install_time"] or 0,
                last_update_time=r["last_update_time"] or 0,
                version=r["version"] or "", installer=r["installer"] or "",
            )
            for r in rows
        ]

    def get_wifi_networks(self, limit: Optional[int] = None, offset: int = 0) -> list:
        from .forensic_data_types import AndroidWifiNetwork
        rows = self._query_table("wifi_networks", limit=limit, offset=offset)
        return [
            AndroidWifiNetwork(
                id=r["id"], ssid=r["ssid"] or "",
                pre_shared_key=r["pre_shared_key"] or "",
                key_mgmt=r["key_mgmt"] or "",
                last_connected=r["last_connected"] or 0,
            )
            for r in rows
        ]

    def get_stats(self) -> dict:
        tables = [
            "contacts", "sms_messages", "call_logs",
            "whatsapp_messages", "telegram_messages", "wechat_messages",
            "chrome_history", "installed_packages", "wifi_networks",
            "usage_stats",
        ]
        return {t: self._count_rows(t) for t in tables}

    def get_all_artifacts_batched(self, batch_size: int = 100) -> Iterator[tuple]:
        methods = [
            ("contacts", self.get_contacts),
            ("sms_messages", self.get_sms_messages),
            ("call_logs", self.get_call_logs),
            ("chrome_history", self.get_chrome_history),
            ("installed_packages", self.get_installed_packages),
            ("wifi_networks", self.get_wifi_networks),
        ]
        # Add chat platforms
        for platform in ["whatsapp", "telegram", "wechat"]:
            methods.append(
                (f"{platform}_messages", lambda limit=None, offset=0, p=platform: self.get_chat_messages(p, limit, offset))
            )
        for artifact_type, method in methods:
            offset = 0
            while True:
                batch = method(limit=batch_size, offset=offset)
                if not batch:
                    break
                yield artifact_type, batch
                offset += len(batch)


# =============================================================================
# Database Factory — Auto-discover per-image databases
# =============================================================================

@dataclass
class DiscoveredDatabases:
    """Container for discovered per-image databases."""
    raw_db: Optional[Path] = None
    files_db: Optional[Path] = None
    events_db: Optional[Path] = None
    windows_db: Optional[Path] = None
    linux_db: Optional[Path] = None
    android_db: Optional[Path] = None

    @property
    def available_types(self) -> list[str]:
        """Return list of available database types."""
        types = []
        if self.raw_db:
            types.append("raw")
        if self.files_db:
            types.append("files")
        if self.events_db:
            types.append("events")
        if self.windows_db:
            types.append("windows")
        if self.linux_db:
            types.append("linux")
        if self.android_db:
            types.append("android")
        return types

    def summary(self) -> str:
        lines = [f"Discovered databases ({len(self.available_types)} types):"]
        for db_type in self.available_types:
            path = getattr(self, f"{db_type}_db")
            lines.append(f"  - {db_type}: {path}")
        return "\n".join(lines)


class ForensicsDatabaseFactory:
    """
    Factory for discovering and creating readers for per-image databases.
    
    Given a base path (e.g., "Server_raw.db" or output directory),
    auto-discovers all available databases for that image.
    """

    # Suffix → attribute mapping
    DB_SUFFIXES = {
        "_raw.db": "raw_db",
        "_files.db": "files_db",
        "_events.db": "events_db",
        "_windows.db": "windows_db",
        "_linux.db": "linux_db",
        "_android.db": "android_db",
    }

    @classmethod
    def discover(
        cls,
        base_name: Optional[str] = None,
        output_dir: Optional[str] = None,
        any_db_path: Optional[str] = None,
    ) -> DiscoveredDatabases:
        """
        Discover all databases for an image.
        
        Args:
            base_name: Image base name (e.g., "Server").
            output_dir: Directory containing the databases.
            any_db_path: Path to any one of the databases; base name is inferred.
        
        Returns:
            DiscoveredDatabases with paths to available databases.
        """
        result = DiscoveredDatabases()

        # Infer base_name and output_dir from any_db_path
        if any_db_path:
            p = Path(any_db_path)
            output_dir = str(p.parent) if output_dir is None else output_dir
            stem = p.stem
            for suffix_stem in ["_raw", "_files", "_events", "_windows", "_linux", "_android"]:
                if stem.endswith(suffix_stem):
                    base_name = stem[: -len(suffix_stem)]
                    break
            if base_name is None:
                base_name = stem

        if base_name is None:
            raise DatabaseError("Cannot determine image base name. Provide base_name or any_db_path.")

        search_dir = Path(output_dir) if output_dir else Path(".")

        for suffix, attr in cls.DB_SUFFIXES.items():
            candidate = search_dir / f"{base_name}{suffix}"
            if candidate.exists():
                setattr(result, attr, candidate)

        return result

    @classmethod
    def create_readers(cls, discovered: DiscoveredDatabases) -> dict:
        """
        Create reader instances for all discovered databases.
        
        Returns:
            Dict mapping db_type → reader instance.
        """
        readers = {}

        if discovered.files_db:
            readers["files"] = ForensicsDatabase(discovered.files_db)
        if discovered.events_db:
            readers["events"] = EventsDatabase(discovered.events_db)
        if discovered.windows_db:
            readers["windows"] = WindowsDatabase(discovered.windows_db)
        if discovered.linux_db:
            readers["linux"] = LinuxDatabase(discovered.linux_db)
        if discovered.android_db:
            readers["android"] = AndroidDatabase(discovered.android_db)

        return readers
