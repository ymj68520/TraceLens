// event_extractor_sql.h
// SQL statements for forensic event extraction

#pragma once
#ifndef EVENT_EXTRACTOR_SQL_H
#define EVENT_EXTRACTOR_SQL_H

namespace EventExtractorSQL {

// ============================================================================
// CREATE TABLE Statements
// ============================================================================

const char* CREATE_EVENTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        file_path TEXT NOT NULL,
        inode INTEGER,
        description TEXT,
        file_size INTEGER,
        file_type TEXT
    );
)";

const char* CREATE_CREATION_EVENTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS creation_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        inode INTEGER,
        file_size INTEGER,
        file_type TEXT
    );
)";

const char* CREATE_MODIFICATION_EVENTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS modification_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        inode INTEGER,
        file_size INTEGER,
        file_type TEXT
    );
)";

const char* CREATE_ACCESS_EVENTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS access_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        inode INTEGER,
        file_size INTEGER,
        file_type TEXT
    );
)";

const char* CREATE_CHANGE_EVENTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS change_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        inode INTEGER,
        file_size INTEGER,
        file_type TEXT,
        description TEXT
    );
)";

const char* CREATE_DELETION_EVENTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS deletion_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        file_path TEXT NOT NULL,
        inode INTEGER,
        file_size INTEGER,
        file_type TEXT
    );
)";

// ============================================================================
// CREATE INDEX Statements
// ============================================================================

const char* CREATE_EVENT_INDICES = R"(
    CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);
    CREATE INDEX IF NOT EXISTS idx_events_path ON events(file_path);
    CREATE INDEX IF NOT EXISTS idx_events_inode ON events(inode);
)";

// ============================================================================
// CREATE VIEW Statements
// ============================================================================

const char* CREATE_TIMELINE_VIEW = R"(
    CREATE VIEW IF NOT EXISTS timeline AS
    SELECT
        datetime(timestamp, 'unixepoch') as event_time,
        event_type,
        file_path,
        inode,
        file_size,
        file_type,
        description
    FROM events
    ORDER BY timestamp DESC;
)";

const char* CREATE_STATISTICS_VIEW = R"(
    CREATE VIEW IF NOT EXISTS event_statistics AS
    SELECT
        event_type,
        COUNT(*) as event_count,
        MIN(timestamp) as first_event,
        MAX(timestamp) as last_event,
        datetime(MIN(timestamp), 'unixepoch') as first_event_time,
        datetime(MAX(timestamp), 'unixepoch') as last_event_time
    FROM events
    GROUP BY event_type;
)";

const char* CREATE_HOURLY_ACTIVITY_VIEW = R"(
    CREATE VIEW IF NOT EXISTS hourly_activity AS
    SELECT
        strftime('%Y-%m-%d %H:00:00', datetime(timestamp, 'unixepoch')) as hour,
        event_type,
        COUNT(*) as event_count
    FROM events
    GROUP BY hour, event_type
    ORDER BY hour DESC;
)";

// ============================================================================
// INSERT Statements
// ============================================================================

const char* INSERT_EVENT = R"(
    INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type)
    VALUES (?, ?, ?, ?, ?, 0, '');
)";

const char* INSERT_CREATION_EVENT = R"(
    INSERT INTO creation_events (timestamp, file_path, inode, file_size, file_type)
    VALUES (?, ?, ?, ?, ?);
)";

const char* INSERT_MODIFICATION_EVENT = R"(
    INSERT INTO modification_events (timestamp, file_path, inode, file_size, file_type)
    VALUES (?, ?, ?, ?, ?);
)";

const char* INSERT_ACCESS_EVENT = R"(
    INSERT INTO access_events (timestamp, file_path, inode, file_size, file_type)
    VALUES (?, ?, ?, ?, ?);
)";

const char* INSERT_CHANGE_EVENT = R"(
    INSERT INTO change_events (timestamp, file_path, inode, file_size, file_type, description)
    VALUES (?, ?, ?, ?, ?, ?);
)";

const char* INSERT_DELETION_EVENT = R"(
    INSERT INTO deletion_events (timestamp, file_path, inode, file_size, file_type)
    VALUES (?, ?, ?, ?, ?);
)";

// ============================================================================
// SELECT Statements
// ============================================================================

const char* SELECT_FILES_FOR_EVENT_EXTRACTION = R"(
    SELECT inode, path, atime, mtime, ctime, crtime, type, size, is_deleted
    FROM files
    WHERE type = 'REG';
)";

// ============================================================================
// Transaction Statements
// ============================================================================

const char* BEGIN_TRANSACTION = "BEGIN TRANSACTION;";
const char* COMMIT_TRANSACTION = "COMMIT;";
const char* ROLLBACK_TRANSACTION = "ROLLBACK;";

} // namespace EventExtractorSQL

#endif // EVENT_EXTRACTOR_SQL_H
