#include "DatabaseManager.h"
#include "AuditLog/AuditLog.h"
#include "ConfigManager/ConfigManager.h"
#include "SQL/file_classifier_sql.h"  // Include migration SQL
#include <iostream>
#include <sstream>
#include <sqlite3.h>

DatabaseManager::DatabaseManager(const std::string& dbPath)
	: dbPath_(dbPath), db_(nullptr) {
}

DatabaseManager::~DatabaseManager() {
	flushInsertBatch();
	if (insertFileStmt_) {
		sqlite3_finalize(insertFileStmt_);
		insertFileStmt_ = nullptr;
	}
	if (db_) {
		sqlite3_close(db_);
	}
}

bool DatabaseManager::initialize() {
	int rc = sqlite3_open(dbPath_.c_str(), &db_);
	if (rc != SQLITE_OK) {
		std::cerr << "Cannot open database: " << sqlite3_errmsg(db_) << std::endl;
		AuditLog::instance().log("SYSTEM", "DB_INIT_FAILED", "Failed to open database: " + dbPath_);
		return false;
	}

	// Apply performance settings from ConfigManager
	auto& config = forensics::ConfigManager::instance();
	sqlite3_busy_timeout(db_, config.getDBBusyTimeoutMs());
	
	std::string journalMode = config.getDBJournalMode();
	executeSQL("PRAGMA journal_mode = " + journalMode + ";");

	// Schema creation is several statements, and the default FULL sync commits
	// each one. On the spinning extraction disk that measured ~4.8 s before a
	// single file was walked. NORMAL keeps the WAL durable per checkpoint
	// while collapsing that into one wait; the row inserts are batched and
	// committed separately.
	if (config.getDBSyncOff()) {
		executeSQL("PRAGMA synchronous = OFF;");
	} else {
		executeSQL("PRAGMA synchronous = NORMAL;");
	}

	// Enable foreign keys
	executeSQL("PRAGMA foreign_keys = ON;");

	// Create tables
	if (!createTables()) {
		return false;
	}

    // Migration: Check and add LLM columns if they don't exist
    checkAndMigrate();

	AuditLog::instance().log("SYSTEM", "DB_INIT", "Database initialized: " + dbPath_);
	return true;
}

void DatabaseManager::checkAndMigrate() {
    // Check if llm_summary column exists in files table
    sqlite3_stmt* stmt;
    const char* checkSql = "PRAGMA table_info(files);";
    bool hasLlmSummary = false;

    if (sqlite3_prepare_v2(db_, checkSql, -1, &stmt, nullptr) == SQLITE_OK) {
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* colName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
            if (colName && std::string(colName) == "llm_summary") {
                hasLlmSummary = true;
                break;
            }
        }
        sqlite3_finalize(stmt);
    }

    if (!hasLlmSummary) {
        std::cout << "[DB Migration] Adding LLM columns to files table in " << dbPath_ << std::endl;
        for (int i = 0; i < FileClassifierSQL::ALTER_FILES_ADD_LLM_COLUMNS_COUNT; ++i) {
            executeSQL(FileClassifierSQL::ALTER_FILES_ADD_LLM_COLUMNS[i]);
        }
    }
}

bool DatabaseManager::createTables() {
	// Files table
	std::string createFilesTable = R"(
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            inode INTEGER,
            name TEXT,
            path TEXT,
            size INTEGER,
            atime INTEGER,
            mtime INTEGER,
            ctime INTEGER,
            crtime INTEGER,
            type TEXT,
            md5 TEXT,
            is_deleted INTEGER,
            is_allocated INTEGER,
            permissions TEXT,
            uid INTEGER,
            gid INTEGER,
            llm_summary TEXT,
            llm_description TEXT,
            llm_keywords TEXT,
            llm_analyzed_at INTEGER,
            llm_model_used TEXT,
            partition_num INTEGER DEFAULT 0
        );
    )";

	if (!executeSQL(createFilesTable)) {
		return false;
	}

	// Migration: older databases created before partition_num existed won't have
	// the column (CREATE TABLE IF NOT EXISTS does not alter existing tables).
	// Add it with a default of 0 so single-partition images keep working.
	// sqlite3_prepare_v2 returns an error if the column already exists; ignore it.
	{
		sqlite3_stmt* migStmt = nullptr;
		if (sqlite3_prepare_v2(db_, "ALTER TABLE files ADD COLUMN partition_num INTEGER DEFAULT 0;",
		                       -1, &migStmt, nullptr) == SQLITE_OK) {
			sqlite3_step(migStmt);
		}
		if (migStmt) sqlite3_finalize(migStmt);
	}

	// Partitions table
	std::string createPartitionsTable = R"(
        CREATE TABLE IF NOT EXISTS partitions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            partition_num INTEGER,
            start_offset INTEGER,
            length INTEGER,
            description TEXT,
            fs_type TEXT
        );
    )";

	if (!executeSQL(createPartitionsTable)) {
		return false;
	}

	// Create indices
	executeSQL("CREATE INDEX IF NOT EXISTS idx_files_inode ON files(inode);");
	executeSQL("CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);");
	executeSQL("CREATE INDEX IF NOT EXISTS idx_files_type ON files(type);");
	executeSQL("CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(is_deleted);");
	executeSQL("CREATE INDEX IF NOT EXISTS idx_files_partition ON files(partition_num);");

	return true;
}

bool DatabaseManager::insertFileRecord(const FileRecord& record) {
	std::lock_guard<std::mutex> lock(insertMutex_);
	if (!db_) return false;

	// Prepared once, reset per call: the statement text is constant and
	// sqlite3_prepare_v2 per row was measurable CPU overhead on 100k-row walks.
	if (!insertFileStmt_) {
		const char* sql = R"(
        INSERT INTO files (inode, name, path, size, atime, mtime, ctime, crtime,
                          type, md5, is_deleted, is_allocated, permissions, uid, gid,
                          partition_num)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    )";
		if (sqlite3_prepare_v2(db_, sql, -1, &insertFileStmt_, nullptr) != SQLITE_OK) {
			std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db_) << std::endl;
			return false;
		}
	}

	// Batch rows into one transaction per kInsertBatchRows rows. Each row in
	// its own autocommit transaction costs one WAL fsync — measured ~0.5 s per
	// fsync on the (spinning-disk) extraction volume, which capped the
	// metadata walk at single-digit files/s.
	if (uncommittedInserts_ == 0 && !executeSQL("BEGIN IMMEDIATE")) {
		return false;
	}

	sqlite3_reset(insertFileStmt_);
	sqlite3_clear_bindings(insertFileStmt_);

	sqlite3_bind_int64(insertFileStmt_, 1, record.inode);
	sqlite3_bind_text(insertFileStmt_, 2, record.name.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(insertFileStmt_, 3, record.path.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int64(insertFileStmt_, 4, record.size);
	sqlite3_bind_int64(insertFileStmt_, 5, record.atime);
	sqlite3_bind_int64(insertFileStmt_, 6, record.mtime);
	sqlite3_bind_int64(insertFileStmt_, 7, record.ctime);
	sqlite3_bind_int64(insertFileStmt_, 8, record.crtime);
	sqlite3_bind_text(insertFileStmt_, 9, record.type.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(insertFileStmt_, 10, record.md5.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int(insertFileStmt_, 11, record.isDeleted);
	sqlite3_bind_int(insertFileStmt_, 12, record.isAllocated);
	sqlite3_bind_text(insertFileStmt_, 13, record.permissions.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int(insertFileStmt_, 14, record.uid);
	sqlite3_bind_int(insertFileStmt_, 15, record.gid);
	sqlite3_bind_int(insertFileStmt_, 16, record.partitionNum);

	int rc = sqlite3_step(insertFileStmt_);
	if (rc != SQLITE_DONE) {
		// A failed statement cannot be trusted inside the open batch:
		// roll the batch back so callers see either the batch or nothing,
		// matching the all-or-nothing expectation of a walk.
		executeSQL("ROLLBACK");
		uncommittedInserts_ = 0;
		sqlite3_reset(insertFileStmt_);
		return false;
	}

	if (++uncommittedInserts_ >= kInsertBatchRows) {
		executeSQL("COMMIT");
		uncommittedInserts_ = 0;
	}
	return rc == SQLITE_DONE;
}

void DatabaseManager::flushInsertBatch() {
	std::lock_guard<std::mutex> lock(insertMutex_);
	if (uncommittedInserts_ > 0) {
		executeSQL("COMMIT");
		uncommittedInserts_ = 0;
	}
}

bool DatabaseManager::insertPartitionInfo(int partNum, int64_t start,
	int64_t length, const std::string& desc,
	const std::string& fsType) {
	const char* sql = R"(
        INSERT INTO partitions (partition_num, start_offset, length, description, fs_type)
        VALUES (?, ?, ?, ?, ?);
    )";

	sqlite3_stmt* stmt;
	int rc = sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr);

	if (rc != SQLITE_OK) {
		return false;
	}

	sqlite3_bind_int(stmt, 1, partNum);
	sqlite3_bind_int64(stmt, 2, start);
	sqlite3_bind_int64(stmt, 3, length);
	sqlite3_bind_text(stmt, 4, desc.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 5, fsType.c_str(), -1, SQLITE_TRANSIENT);

	rc = sqlite3_step(stmt);
	sqlite3_finalize(stmt);

	return rc == SQLITE_DONE;
}

int DatabaseManager::getFileCount() {
	// Same-connection reads see the open insert batch, but downstream
	// consumers (LLM smart selection etc.) open NEW connections after this
	// count is reported — flush so the reported count is externally visible.
	flushInsertBatch();
	sqlite3_stmt* stmt = nullptr;
	if (sqlite3_prepare_v2(db_, "SELECT COUNT(*) FROM files;", -1, &stmt, nullptr) != SQLITE_OK) {
		return -1;
	}
	int count = -1;
	if (sqlite3_step(stmt) == SQLITE_ROW) {
		count = sqlite3_column_int(stmt, 0);
	}
	sqlite3_finalize(stmt);
	return count;
}

bool DatabaseManager::executeSQL(const std::string& sql) {
	char* errMsg = nullptr;
	int rc = sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &errMsg);

	if (rc != SQLITE_OK) {
		std::cerr << "SQL error: " << errMsg << std::endl;
		sqlite3_free(errMsg);
		return false;
	}

	return true;
}