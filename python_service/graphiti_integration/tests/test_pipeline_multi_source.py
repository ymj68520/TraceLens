"""
Tests for multi-source database readers, forensic episode transformers,
and the MultiSourcePipeline.
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from graphiti_integration.database_reader import (
    EventsDatabase,
    WindowsDatabase,
    LinuxDatabase,
    AndroidDatabase,
    ForensicsDatabaseFactory,
    DiscoveredDatabases,
)
from graphiti_integration.forensic_data_types import (
    TimelineEvent,
    WindowsRegistryValue,
    LinuxShellHistory,
    AndroidContact,
)
from graphiti_integration.toon_transformer import ForensicEpisodeTransformer


# =============================================================================
# Fixtures: create temporary SQLite databases with test data
# =============================================================================

@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def events_db(tmp_dir):
    """Create a temporary events database."""
    db_path = tmp_dir / "TestImage_events.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            inode INTEGER,
            description TEXT,
            file_size INTEGER,
            file_type TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type) VALUES (?,?,?,?,?,?,?)",
        [
            (1700000000, "CREATED", "/home/user/doc.pdf", 12345, "File created", 1024, "REG"),
            (1700000100, "MODIFIED", "/home/user/doc.pdf", 12345, "File modified", 1200, "REG"),
            (1700000200, "ACCESSED", "/etc/passwd", 100, "passwd accessed", 2048, "REG"),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def windows_db(tmp_dir):
    """Create a temporary Windows database."""
    db_path = tmp_dir / "TestImage_windows.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS registry_values (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key_path TEXT, value_name TEXT, value_type TEXT,
            value_data TEXT, last_modified INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT, sid TEXT, full_name TEXT, account_type TEXT,
            last_login INTEGER, login_count INTEGER,
            is_disabled INTEGER, is_locked INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO registry_values (key_path, value_name, value_type, value_data, last_modified) VALUES (?,?,?,?,?)",
        [
            ("HKLM\\Software\\Test", "Version", "REG_SZ", "1.0", 1700000000),
            ("HKCU\\Software\\App", "Setting", "REG_DWORD", "42", 1700000500),
        ],
    )
    conn.executemany(
        "INSERT INTO user_accounts (username, sid, full_name, account_type, last_login, login_count, is_disabled, is_locked) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("admin", "S-1-5-21-xxx", "Administrator", "admin", 1700000000, 50, 0, 0),
            ("user1", "S-1-5-21-yyy", "Test User", "user", 1699999000, 10, 0, 0),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def linux_db(tmp_dir):
    """Create a temporary Linux database."""
    db_path = tmp_dir / "TestImage_linux.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS shell_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT, command TEXT, timestamp INTEGER,
            shell_type TEXT, sequence_num INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT, uid INTEGER, gid INTEGER,
            home_dir TEXT, shell TEXT, gecos TEXT,
            password_hash TEXT, last_password_change INTEGER
        )
    """)
    conn.executemany(
        "INSERT INTO shell_history (username, command, timestamp, shell_type, sequence_num) VALUES (?,?,?,?,?)",
        [
            ("root", "apt update", 1700000000, "bash", 1),
            ("root", "systemctl restart nginx", 1700000050, "bash", 2),
            ("user1", "ls -la", 1700000100, "bash", 1),
        ],
    )
    conn.executemany(
        "INSERT INTO user_accounts (username, uid, gid, home_dir, shell, gecos, password_hash, last_password_change) VALUES (?,?,?,?,?,?,?,?)",
        [
            ("root", 0, 0, "/root", "/bin/bash", "root", "x", 1699000000),
            ("user1", 1000, 1000, "/home/user1", "/bin/bash", "User 1", "x", 1699500000),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def android_db(tmp_dir):
    """Create a temporary Android database."""
    db_path = tmp_dir / "TestImage_android.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            display_name TEXT, phone_number TEXT, email TEXT,
            account_type TEXT, account_name TEXT, raw_contact_id INTEGER
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sms_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            thread_id INTEGER, address TEXT, person TEXT,
            date INTEGER, date_sent INTEGER, read INTEGER,
            status INTEGER, type INTEGER, body TEXT, service_center TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO contacts (display_name, phone_number, email, account_type, account_name) VALUES (?,?,?,?,?)",
        [
            ("Alice", "+1234567890", "alice@example.com", "google", "alice@gmail.com"),
            ("Bob", "+0987654321", "", "local", ""),
        ],
    )
    conn.executemany(
        "INSERT INTO sms_messages (address, body, date, type) VALUES (?,?,?,?)",
        [
            ("+1234567890", "Hello!", 1700000000, 1),
            ("+0987654321", "Meeting at 3pm", 1700001000, 2),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def files_db(tmp_dir):
    """Create a temporary files database."""
    db_path = tmp_dir / "TestImage_files.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inode INTEGER, name TEXT, path TEXT, size INTEGER,
            extension TEXT, category TEXT, type TEXT,
            mtime INTEGER, ctime INTEGER, is_deleted INTEGER, md5 TEXT,
            llm_summary TEXT, llm_description TEXT, llm_keywords TEXT,
            llm_analyzed_at INTEGER, llm_model_used TEXT
        )
    """)
    conn.executemany(
        "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            (100, "test.pdf", "/home/user/test.pdf", 5000, "pdf", "document", "REG", 1700000000, 1699900000, 0, "abc123"),
        ],
    )
    conn.commit()
    conn.close()
    return db_path


# =============================================================================
# Tests: Database Readers
# =============================================================================

class TestEventsDatabase:
    def test_get_events(self, events_db):
        reader = EventsDatabase(events_db)
        events = reader.get_events()
        assert len(events) == 3
        assert events[0].event_type == "CREATED"
        assert events[0].file_path == "/home/user/doc.pdf"

    def test_get_events_filtered(self, events_db):
        reader = EventsDatabase(events_db)
        events = reader.get_events(event_type="MODIFIED")
        assert len(events) == 1
        assert events[0].event_type == "MODIFIED"

    def test_count_events(self, events_db):
        reader = EventsDatabase(events_db)
        assert reader.count_events() == 3

    def test_iter_events_batched(self, events_db):
        reader = EventsDatabase(events_db)
        batches = list(reader.iter_events_batched(batch_size=2))
        assert len(batches) == 2
        assert len(batches[0]) == 2
        assert len(batches[1]) == 1

    def test_get_event_stats(self, events_db):
        reader = EventsDatabase(events_db)
        stats = reader.get_event_stats()
        assert stats["CREATED"] == 1
        assert stats["MODIFIED"] == 1
        assert stats["ACCESSED"] == 1


class TestWindowsDatabase:
    def test_get_registry_values(self, windows_db):
        reader = WindowsDatabase(windows_db)
        values = reader.get_registry_values()
        assert len(values) == 2
        assert values[0].key_path == "HKLM\\Software\\Test"

    def test_get_user_accounts(self, windows_db):
        reader = WindowsDatabase(windows_db)
        users = reader.get_user_accounts()
        assert len(users) == 2
        assert users[0].username == "admin"

    def test_get_stats(self, windows_db):
        reader = WindowsDatabase(windows_db)
        stats = reader.get_stats()
        assert stats["registry_values"] == 2
        assert stats["user_accounts"] == 2


class TestLinuxDatabase:
    def test_get_shell_history(self, linux_db):
        reader = LinuxDatabase(linux_db)
        history = reader.get_shell_history()
        assert len(history) == 3
        assert history[0].command == "apt update"

    def test_get_user_accounts(self, linux_db):
        reader = LinuxDatabase(linux_db)
        users = reader.get_user_accounts()
        assert len(users) == 2
        assert users[0].username == "root"

    def test_get_stats(self, linux_db):
        reader = LinuxDatabase(linux_db)
        stats = reader.get_stats()
        assert stats["shell_history"] == 3
        assert stats["user_accounts"] == 2


class TestAndroidDatabase:
    def test_get_contacts(self, android_db):
        reader = AndroidDatabase(android_db)
        contacts = reader.get_contacts()
        assert len(contacts) == 2
        assert contacts[0].display_name == "Alice"

    def test_get_sms_messages(self, android_db):
        reader = AndroidDatabase(android_db)
        messages = reader.get_sms_messages()
        assert len(messages) == 2
        assert messages[0].body == "Hello!"

    def test_get_stats(self, android_db):
        reader = AndroidDatabase(android_db)
        stats = reader.get_stats()
        assert stats["contacts"] == 2
        assert stats["sms_messages"] == 2


# =============================================================================
# Tests: Database Factory
# =============================================================================

class TestForensicsDatabaseFactory:
    def test_discover_from_directory(self, tmp_dir, events_db, windows_db, linux_db, files_db):
        discovered = ForensicsDatabaseFactory.discover(
            base_name="TestImage", output_dir=str(tmp_dir)
        )
        assert "events" in discovered.available_types
        assert "windows" in discovered.available_types
        assert "linux" in discovered.available_types
        assert "files" in discovered.available_types
        assert "android" not in discovered.available_types  # not created in this fixture combo

    def test_discover_from_any_db_path(self, tmp_dir, events_db, windows_db):
        discovered = ForensicsDatabaseFactory.discover(
            any_db_path=str(events_db)
        )
        assert "events" in discovered.available_types
        assert "windows" in discovered.available_types

    def test_create_readers(self, tmp_dir, events_db, windows_db, linux_db, files_db):
        discovered = ForensicsDatabaseFactory.discover(
            base_name="TestImage", output_dir=str(tmp_dir)
        )
        readers = ForensicsDatabaseFactory.create_readers(discovered)
        assert "events" in readers
        assert "windows" in readers
        assert "linux" in readers
        assert "files" in readers

    def test_summary(self, tmp_dir, events_db, windows_db):
        discovered = ForensicsDatabaseFactory.discover(
            base_name="TestImage", output_dir=str(tmp_dir)
        )
        summary = discovered.summary()
        assert "events" in summary
        assert "windows" in summary


# =============================================================================
# Tests: ForensicEpisodeTransformer
# =============================================================================

class TestForensicEpisodeTransformer:
    def test_transform_event(self):
        transformer = ForensicEpisodeTransformer()
        event = TimelineEvent(
            id=1, timestamp=1700000000, event_type="CREATED",
            file_path="/home/user/doc.pdf", inode=123,
            description="File created", file_size=1024, file_type="REG",
        )
        episode = transformer.transform_event(event)
        assert "event:CREATED:" in episode.name
        assert episode.category == "timeline_event"
        assert "CREATED" in episode.episode_body

    def test_transform_events_batch(self):
        transformer = ForensicEpisodeTransformer()
        events = [
            TimelineEvent(id=1, timestamp=1700000000, event_type="CREATED", file_path="/a"),
            TimelineEvent(id=2, timestamp=1700000100, event_type="MODIFIED", file_path="/b"),
        ]
        episodes, errors = transformer.transform_events_batch(events)
        assert len(episodes) == 2
        assert len(errors) == 0

    def test_transform_windows_artifact(self):
        transformer = ForensicEpisodeTransformer()
        reg = WindowsRegistryValue(
            id=1, key_path="HKLM\\Test", value_name="Ver",
            value_type="REG_SZ", value_data="1.0", last_modified=1700000000,
        )
        episode = transformer.transform_windows_artifact("registry_values", reg)
        assert "windows:registry_values:" in episode.name
        assert "HKLM" in episode.episode_body

    def test_transform_linux_artifact(self):
        transformer = ForensicEpisodeTransformer()
        entry = LinuxShellHistory(
            id=1, username="root", command="apt update",
            timestamp=1700000000, shell_type="bash", sequence_num=1,
        )
        episode = transformer.transform_linux_artifact("shell_history", entry)
        assert "linux:shell_history:" in episode.name
        assert "apt update" in episode.episode_body

    def test_transform_android_artifact(self):
        transformer = ForensicEpisodeTransformer()
        contact = AndroidContact(
            id=1, display_name="Alice", phone_number="+123",
            email="alice@test.com",
        )
        episode = transformer.transform_android_artifact("contacts", contact)
        assert "android:contacts:" in episode.name
        assert "Alice" in episode.episode_body


# =============================================================================
# Tests: Integration (reader + transformer)
# =============================================================================

class TestReaderTransformerIntegration:
    def test_events_full_pipeline(self, events_db):
        reader = EventsDatabase(events_db)
        transformer = ForensicEpisodeTransformer()

        events = reader.get_events()
        episodes, errors = transformer.transform_events_batch(events)

        assert len(episodes) == 3
        assert len(errors) == 0
        assert all(ep.category == "timeline_event" for ep in episodes)

    def test_windows_full_pipeline(self, windows_db):
        reader = WindowsDatabase(windows_db)
        transformer = ForensicEpisodeTransformer()

        all_episodes = []
        for artifact_type, batch in reader.get_all_artifacts_batched(batch_size=10):
            eps, errs = transformer.transform_windows_batch(artifact_type, batch)
            all_episodes.extend(eps)

        assert len(all_episodes) == 4  # 2 registry + 2 users

    def test_linux_full_pipeline(self, linux_db):
        reader = LinuxDatabase(linux_db)
        transformer = ForensicEpisodeTransformer()

        all_episodes = []
        for artifact_type, batch in reader.get_all_artifacts_batched(batch_size=10):
            eps, errs = transformer.transform_linux_batch(artifact_type, batch)
            all_episodes.extend(eps)

        assert len(all_episodes) == 5  # 2 users + 3 shell history

    def test_android_full_pipeline(self, android_db):
        reader = AndroidDatabase(android_db)
        transformer = ForensicEpisodeTransformer()

        all_episodes = []
        for artifact_type, batch in reader.get_all_artifacts_batched(batch_size=10):
            eps, errs = transformer.transform_android_batch(artifact_type, batch)
            all_episodes.extend(eps)

        assert len(all_episodes) == 4  # 2 contacts + 2 sms
