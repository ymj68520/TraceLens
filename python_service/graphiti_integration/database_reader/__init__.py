"""
Database reader module for fetching records from SQLite databases.

This module provides a modular interface for reading different types of forensics databases:
- Raw database (raw_reader): File metadata and LLM analysis
- Platform-specific databases: Windows, Linux, Android artifacts
- Events database (events_reader): Timeline events and event clusters

Backward compatibility: All classes and functions from the original database_reader.py
are re-exported from this module.
"""

# Import all classes and functions from submodules
from .raw_reader import (
    FileRecord,
    ForensicsDatabase,
    read_raw_database,
    get_files_metadata,
)
from .base_reader import _BaseForensicsReader
from .windows_reader import WindowsDatabase
from .linux_reader import LinuxDatabase
from .android_reader import AndroidDatabase
from .events_reader import (
    EventsDatabase,
    read_events_database,
    get_timeline_events,
)

# Import factory classes - define them here to avoid circular import
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from graphiti_integration.exceptions import DatabaseError


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
            else:
                # Also fall back to pure names like files.db, events.db
                pure_name = suffix.lstrip('_')
                candidate_pure = search_dir / pure_name
                if candidate_pure.exists():
                    setattr(result, attr, candidate_pure)

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


def read_files_database(db_path: str | Path, db_type: str = "files") -> _BaseForensicsReader:
    """
    Convenience function to read platform-specific files database.

    Args:
        db_path: Path to the files database file.
        db_type: Type of database ('windows', 'linux', 'android').

    Returns:
        Appropriate database reader instance.
    """
    reader_map = {
        "windows": WindowsDatabase,
        "linux": LinuxDatabase,
        "android": AndroidDatabase,
    }
    reader_class = reader_map.get(db_type.lower())
    if not reader_class:
        raise ValueError(f"Unknown database type: {db_type}. Must be one of {list(reader_map.keys())}")
    return reader_class(db_path)


def get_classified_files(
    db_path: str | Path,
    db_type: str,
    artifact_type: str,
    limit: Optional[int] = None,
    offset: int = 0,
) -> list:
    """
    Convenience function to fetch classified files from platform-specific database.

    Args:
        db_path: Path to the files database file.
        db_type: Type of database ('windows', 'linux', 'android').
        artifact_type: Type of artifact to fetch (e.g., 'registry_values', 'user_accounts').
        limit: Maximum number of records to fetch.
        offset: Number of records to skip.

    Returns:
        List of artifact objects.
    """
    db = read_files_database(db_path, db_type)

    # Map artifact types to methods
    method_map = {
        # Windows
        "registry_values": db.get_registry_values,
        "event_logs": db.get_event_logs,
        "prefetch_files": db.get_prefetch_files,
        "user_accounts": db.get_user_accounts,
        "usb_devices": db.get_usb_devices,
        "browser_history": db.get_browser_history,
        "services": db.get_services,
        # Linux
        "log_entries": db.get_log_entries,
        "shell_history": db.get_shell_history,
        "login_records": db.get_login_records,
        "groups": db.get_groups,
        # Android
        "contacts": db.get_contacts,
        "sms_messages": db.get_sms_messages,
        "call_logs": db.get_call_logs,
        "chrome_history": db.get_chrome_history,
        "installed_packages": db.get_installed_packages,
        "wifi_networks": db.get_wifi_networks,
    }

    method = method_map.get(artifact_type)
    if not method:
        raise ValueError(f"Unknown artifact type: {artifact_type} for {db_type}")

    return method(limit=limit, offset=offset)

__all__ = [
    # Raw database reader
    "FileRecord",
    "ForensicsDatabase",
    "read_raw_database",
    "get_files_metadata",
    # Base reader
    "_BaseForensicsReader",
    # Platform-specific database readers
    "WindowsDatabase",
    "LinuxDatabase",
    "AndroidDatabase",
    "read_files_database",
    "get_classified_files",
    # Events database reader
    "EventsDatabase",
    "read_events_database",
    "get_timeline_events",
    # Factory classes
    "DiscoveredDatabases",
    "ForensicsDatabaseFactory",
]
