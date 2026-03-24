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
        file_path TEXT,
        inode INTEGER,
        description TEXT,
        file_size INTEGER,
        file_type TEXT,
        system_context TEXT,
        priority TEXT,         -- 事件优先级: LOW, MEDIUM, HIGH, CRITICAL
        severity TEXT,         -- 事件严重程度: INFO, WARNING, ERROR, CRITICAL
        event_source TEXT,     -- 事件来源: FILE_SYSTEM, WINDOWS_EVENT_LOG, LINUX_SYSLOG, etc.
        event_category TEXT,   -- 事件类别: FILE_OPERATION, SYSTEM_ACTIVITY, etc.
        normalized_type TEXT,  -- 标准化事件类型
        source_id TEXT         -- 事件来源ID
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

const char* CREATE_SYSTEM_EVENTS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS system_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER NOT NULL,
        event_type TEXT NOT NULL,
        source TEXT,
        user TEXT,
        process TEXT,
        ip_address TEXT,
        port INTEGER,
        service TEXT,
        description TEXT,
        severity TEXT,
        system_context TEXT
    );
)";

const char* CREATE_EVENT_CORRELATIONS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS event_correlations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_id1 INTEGER NOT NULL,
        event_id2 INTEGER NOT NULL,
        correlation_type TEXT NOT NULL,
        confidence REAL NOT NULL,
        description TEXT,
        FOREIGN KEY (event_id1) REFERENCES events(id),
        FOREIGN KEY (event_id2) REFERENCES events(id)
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
    CREATE INDEX IF NOT EXISTS idx_system_events_timestamp ON system_events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_system_events_type ON system_events(event_type);
    CREATE INDEX IF NOT EXISTS idx_system_events_source ON system_events(source);
    CREATE INDEX IF NOT EXISTS idx_system_events_user ON system_events(user);
    CREATE INDEX IF NOT EXISTS idx_event_correlations_event1 ON event_correlations(event_id1);
    CREATE INDEX IF NOT EXISTS idx_event_correlations_event2 ON event_correlations(event_id2);
    CREATE INDEX IF NOT EXISTS idx_event_correlations_type ON event_correlations(correlation_type);
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

const char* CREATE_SYSTEM_EVENT_VIEW = R"(
    CREATE VIEW IF NOT EXISTS system_event_view AS
    SELECT
        id,
        datetime(timestamp, 'unixepoch') as event_time,
        event_type,
        source,
        user,
        process,
        ip_address,
        port,
        service,
        description,
        severity,
        system_context
    FROM system_events
    ORDER BY timestamp DESC;
)";

const char* CREATE_EVENT_CORRELATION_VIEW = R"(
    CREATE VIEW IF NOT EXISTS event_correlation_view AS
    SELECT
        ec.id,
        e1.id as event_id1,
        e1.event_type as event_type1,
        e1.timestamp as timestamp1,
        e1.file_path as file_path1,
        e2.id as event_id2,
        e2.event_type as event_type2,
        e2.timestamp as timestamp2,
        e2.file_path as file_path2,
        ec.correlation_type,
        ec.confidence,
        ec.description
    FROM event_correlations ec
    JOIN events e1 ON ec.event_id1 = e1.id
    JOIN events e2 ON ec.event_id2 = e2.id
    ORDER BY ec.confidence DESC;
)";

const char* CREATE_ENHANCED_TIMELINE_VIEW = R"(
    CREATE VIEW IF NOT EXISTS enhanced_timeline AS
    SELECT
        id,
        datetime(timestamp, 'unixepoch') as event_time,
        event_type,
        file_path,
        inode,
        description,
        system_context,
        'file' as event_source
    FROM events
    UNION ALL
    SELECT
        id,
        datetime(timestamp, 'unixepoch') as event_time,
        event_type,
        NULL as file_path,
        NULL as inode,
        description,
        system_context,
        'system' as event_source
    FROM system_events
    ORDER BY timestamp DESC;
)";

const char* CREATE_ENHANCED_STATISTICS_VIEW = R"(
    CREATE VIEW IF NOT EXISTS enhanced_event_statistics AS
    SELECT
        event_type,
        COUNT(*) as event_count,
        MIN(timestamp) as first_event,
        MAX(timestamp) as last_event,
        datetime(MIN(timestamp), 'unixepoch') as first_event_time,
        datetime(MAX(timestamp), 'unixepoch') as last_event_time,
        'file' as event_source
    FROM events
    GROUP BY event_type
    UNION ALL
    SELECT
        event_type,
        COUNT(*) as event_count,
        MIN(timestamp) as first_event,
        MAX(timestamp) as last_event,
        datetime(MIN(timestamp), 'unixepoch') as first_event_time,
        datetime(MAX(timestamp), 'unixepoch') as last_event_time,
        'system' as event_source
    FROM system_events
    GROUP BY event_type;
)";

// ============================================================================
// INSERT Statements
// ============================================================================

const char* INSERT_EVENT = R"(
    INSERT INTO events (timestamp, event_type, file_path, inode, description, file_size, file_type, system_context, priority, severity, event_source, event_category, normalized_type, source_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
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

const char* INSERT_SYSTEM_EVENT = R"(
    INSERT INTO system_events (timestamp, event_type, source, user, process, ip_address, port, service, description, severity, system_context)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
)";

const char* INSERT_EVENT_CORRELATION = R"(
    INSERT INTO event_correlations (event_id1, event_id2, correlation_type, confidence, description)
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
