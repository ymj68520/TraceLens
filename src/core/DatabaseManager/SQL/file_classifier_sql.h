// file_classifier_sql.h
// SQL statements for file classification and categorization

#pragma once
#ifndef FILE_CLASSIFIER_SQL_H
#define FILE_CLASSIFIER_SQL_H

namespace FileClassifierSQL {

// ============================================================================
// CREATE TABLE Statements
// ============================================================================

inline const char* CREATE_MAIN_FILES_TABLE = R"(
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inode INTEGER,
        name TEXT,
        path TEXT,
        size INTEGER,
        extension TEXT,
        category TEXT,
        type TEXT,
        mtime INTEGER,
        ctime INTEGER,
        is_deleted INTEGER,
        md5 TEXT,
        llm_summary TEXT,
        llm_description TEXT,
        llm_keywords TEXT,
        llm_analyzed_at INTEGER,
        llm_model_used TEXT
    );
)";

// Template for category tables - use with table name substitution
inline const char* CREATE_CATEGORY_TABLE_TEMPLATE = R"(
    CREATE TABLE IF NOT EXISTS %TABLE_NAME% (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        inode INTEGER,
        name TEXT,
        path TEXT,
        size INTEGER,
        extension TEXT,
        mtime INTEGER,
        ctime INTEGER,
        is_deleted INTEGER,
        md5 TEXT
    );
)";

// ============================================================================
// LLM Analysis Tables (Issue 3 & 6)
// ============================================================================

// Analysis progress tracking table (Issue 6)
inline const char* CREATE_ANALYSIS_PROGRESS_TABLE = R"(
    CREATE TABLE IF NOT EXISTS analysis_progress (
        task_id TEXT PRIMARY KEY,
        total_files INTEGER,
        completed_files INTEGER,
        current_file TEXT,
        started_at INTEGER,
        last_updated INTEGER,
        status TEXT DEFAULT 'running'
    );
)";

// Migration: Add LLM columns to existing files table
inline const char* ALTER_FILES_ADD_LLM_COLUMNS[] = {
    "ALTER TABLE files ADD COLUMN llm_summary TEXT;",
    "ALTER TABLE files ADD COLUMN llm_description TEXT;",
    "ALTER TABLE files ADD COLUMN llm_keywords TEXT;",
    "ALTER TABLE files ADD COLUMN llm_analyzed_at INTEGER;",
    "ALTER TABLE files ADD COLUMN llm_model_used TEXT;"
};
inline const int ALTER_FILES_ADD_LLM_COLUMNS_COUNT = 5;

// Update LLM analysis result for a file
inline const char* UPDATE_FILE_LLM_ANALYSIS = R"(
    UPDATE files SET
        llm_summary = ?,
        llm_description = ?,
        llm_keywords = ?,
        llm_analyzed_at = ?,
        llm_model_used = ?
    WHERE path = ?;
)";

// Get file LLM analysis by path
inline const char* SELECT_FILE_LLM_ANALYSIS = R"(
    SELECT llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used
    FROM files WHERE path = ?;
)";

// Get files pending LLM analysis
inline const char* SELECT_FILES_PENDING_ANALYSIS = R"(
    SELECT path FROM files 
    WHERE llm_analyzed_at IS NULL 
    ORDER BY size ASC 
    LIMIT ?;
)";

// Progress tracking statements
inline const char* INSERT_ANALYSIS_PROGRESS = R"(
    INSERT INTO analysis_progress (task_id, total_files, completed_files, current_file, started_at, last_updated, status)
    VALUES (?, ?, 0, '', ?, ?, 'running');
)";

inline const char* UPDATE_ANALYSIS_PROGRESS = R"(
    UPDATE analysis_progress SET
        completed_files = ?,
        current_file = ?,
        last_updated = ?
    WHERE task_id = ?;
)";

inline const char* COMPLETE_ANALYSIS_PROGRESS = R"(
    UPDATE analysis_progress SET
        completed_files = total_files,
        status = 'completed',
        last_updated = ?
    WHERE task_id = ?;
)";

inline const char* SELECT_ANALYSIS_PROGRESS = R"(
    SELECT task_id, total_files, completed_files, current_file, started_at, last_updated, status
    FROM analysis_progress WHERE task_id = ?;
)";

// ============================================================================
// CREATE INDEX Statements
// ============================================================================

inline const char* CREATE_MAIN_FILES_INDICES = R"(
    CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
    CREATE INDEX IF NOT EXISTS idx_files_category ON files(category);
    CREATE INDEX IF NOT EXISTS idx_files_llm_analyzed ON files(llm_analyzed_at);
)";

// Template for category table indices
inline const char* CREATE_CATEGORY_INDEX_PATH_TEMPLATE = "CREATE INDEX IF NOT EXISTS idx_%TABLE_NAME%_path ON %TABLE_NAME%(path);";
inline const char* CREATE_CATEGORY_INDEX_EXTENSION_TEMPLATE = "CREATE INDEX IF NOT EXISTS idx_%TABLE_NAME%_extension ON %TABLE_NAME%(extension);";
inline const char* CREATE_CATEGORY_INDEX_SIZE_TEMPLATE = "CREATE INDEX IF NOT EXISTS idx_%TABLE_NAME%_size ON %TABLE_NAME%(size);";

// ============================================================================
// CREATE VIEW Statements
// ============================================================================

inline const char* CREATE_FILE_SUMMARY_VIEW = R"(
    CREATE VIEW IF NOT EXISTS file_summary AS
    SELECT
        'Images' as category,
        COUNT(*) as file_count,
        SUM(size) as total_size,
        ROUND(AVG(size), 2) as avg_size,
        MAX(size) as max_size
    FROM images
    UNION ALL
    SELECT 'Videos', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM videos
    UNION ALL
    SELECT 'Audio', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM audio_files
    UNION ALL
    SELECT 'Documents', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM documents
    UNION ALL
    SELECT 'Archives', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM archives
    UNION ALL
    SELECT 'Executables', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM executables
    UNION ALL
    SELECT 'Databases', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM databases
    UNION ALL
    SELECT 'Source Code', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM source_code
    UNION ALL
    SELECT 'Web Files', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM web_files
    UNION ALL
    SELECT 'Email', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM email_files
    UNION ALL
    SELECT 'System Files', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM system_files
    UNION ALL
    SELECT 'Encrypted', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM encrypted_files
    UNION ALL
    SELECT 'OS Config', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM os_config_files
    UNION ALL
    SELECT 'OS Boot', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM os_boot_files
    UNION ALL
    SELECT 'OS Libraries', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM os_libraries
    UNION ALL
    SELECT 'FS Journal', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM fs_journal
    UNION ALL
    SELECT 'FS Metadata', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM fs_metadata
    UNION ALL
    SELECT 'Logs', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM log_files
    UNION ALL
    SELECT 'Cache', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM cache_files
    UNION ALL
    SELECT 'Temp', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM temp_files
    UNION ALL
    SELECT 'Backup', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM backup_files
    UNION ALL
    SELECT 'Fonts', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM font_files
    UNION ALL
    SELECT 'Certificates', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM certificates
    UNION ALL
    SELECT 'Unknown', COUNT(*), SUM(size), ROUND(AVG(size), 2), MAX(size) FROM unknown_files;
)";

inline const char* CREATE_EXTENSION_STATISTICS_VIEW = R"(
    CREATE VIEW IF NOT EXISTS extension_statistics AS
    SELECT extension, COUNT(*) as count, SUM(size) as total_size
    FROM (
        SELECT extension, size FROM images
        UNION ALL SELECT extension, size FROM videos
        UNION ALL SELECT extension, size FROM audio_files
        UNION ALL SELECT extension, size FROM documents
        UNION ALL SELECT extension, size FROM archives
        UNION ALL SELECT extension, size FROM executables
        UNION ALL SELECT extension, size FROM databases
        UNION ALL SELECT extension, size FROM source_code
        UNION ALL SELECT extension, size FROM web_files
        UNION ALL SELECT extension, size FROM email_files
        UNION ALL SELECT extension, size FROM system_files
        UNION ALL SELECT extension, size FROM encrypted_files
        UNION ALL SELECT extension, size FROM os_config_files
        UNION ALL SELECT extension, size FROM os_boot_files
        UNION ALL SELECT extension, size FROM os_libraries
        UNION ALL SELECT extension, size FROM fs_journal
        UNION ALL SELECT extension, size FROM fs_metadata
        UNION ALL SELECT extension, size FROM log_files
        UNION ALL SELECT extension, size FROM cache_files
        UNION ALL SELECT extension, size FROM temp_files
        UNION ALL SELECT extension, size FROM backup_files
        UNION ALL SELECT extension, size FROM font_files
        UNION ALL SELECT extension, size FROM certificates
        UNION ALL SELECT extension, size FROM unknown_files
    )
    GROUP BY extension
    ORDER BY count DESC;
)";

inline const char* CREATE_DELETED_FILES_VIEW = R"(
    CREATE VIEW IF NOT EXISTS deleted_files AS
    SELECT 'Images' as category, name, path, size, extension FROM images WHERE is_deleted = 1
    UNION ALL
    SELECT 'Videos', name, path, size, extension FROM videos WHERE is_deleted = 1
    UNION ALL
    SELECT 'Audio', name, path, size, extension FROM audio_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'Documents', name, path, size, extension FROM documents WHERE is_deleted = 1
    UNION ALL
    SELECT 'Archives', name, path, size, extension FROM archives WHERE is_deleted = 1
    UNION ALL
    SELECT 'Executables', name, path, size, extension FROM executables WHERE is_deleted = 1
    UNION ALL
    SELECT 'Databases', name, path, size, extension FROM databases WHERE is_deleted = 1
    UNION ALL
    SELECT 'Source Code', name, path, size, extension FROM source_code WHERE is_deleted = 1
    UNION ALL
    SELECT 'Web Files', name, path, size, extension FROM web_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'Email', name, path, size, extension FROM email_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'System Files', name, path, size, extension FROM system_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'Encrypted', name, path, size, extension FROM encrypted_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'OS Config', name, path, size, extension FROM os_config_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'OS Boot', name, path, size, extension FROM os_boot_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'OS Libraries', name, path, size, extension FROM os_libraries WHERE is_deleted = 1
    UNION ALL
    SELECT 'FS Journal', name, path, size, extension FROM fs_journal WHERE is_deleted = 1
    UNION ALL
    SELECT 'FS Metadata', name, path, size, extension FROM fs_metadata WHERE is_deleted = 1
    UNION ALL
    SELECT 'Logs', name, path, size, extension FROM log_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'Cache', name, path, size, extension FROM cache_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'Temp', name, path, size, extension FROM temp_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'Backup', name, path, size, extension FROM backup_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'Fonts', name, path, size, extension FROM font_files WHERE is_deleted = 1
    UNION ALL
    SELECT 'Certificates', name, path, size, extension FROM certificates WHERE is_deleted = 1
    UNION ALL
    SELECT 'Unknown', name, path, size, extension FROM unknown_files WHERE is_deleted = 1;
)";

// ============================================================================
// INSERT Statements
// ============================================================================

// Template for inserting into category tables
inline const char* INSERT_INTO_CATEGORY_TABLE_TEMPLATE = 
    "INSERT INTO %TABLE_NAME% (inode, name, path, size, extension, mtime, ctime, is_deleted, md5) "
    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);";

inline const char* INSERT_INTO_FILES_TABLE = 
    "INSERT INTO files (inode, name, path, size, extension, category, type, mtime, ctime, is_deleted, md5) "
    "VALUES (?, ?, ?, ?, ?, ?, 'REG', ?, ?, ?, ?);";

// ============================================================================
// SELECT Statements
// ============================================================================

inline const char* SELECT_FILES_FOR_CLASSIFICATION = R"(
    SELECT inode, name, path, size, mtime, ctime, type, is_deleted, md5
    FROM files
    WHERE type = 'REG';
)";

// ============================================================================
// Transaction Statements
// ============================================================================

inline const char* BEGIN_TRANSACTION = "BEGIN TRANSACTION;";
inline const char* COMMIT_TRANSACTION = "COMMIT;";
inline const char* ROLLBACK_TRANSACTION = "ROLLBACK;";

} // namespace FileClassifierSQL

#endif // FILE_CLASSIFIER_SQL_H
