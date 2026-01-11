#include "DatabaseManager.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>

DatabaseManager::DatabaseManager(const std::string& dbPath)
	: dbPath_(dbPath), db_(nullptr) {
}

DatabaseManager::~DatabaseManager() {
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

	// Enable foreign keys
	executeSQL("PRAGMA foreign_keys = ON;");

	// Create tables
	bool result = createTables();
	if (result) {
		AuditLog::instance().log("SYSTEM", "DB_INIT", "Database initialized: " + dbPath_);
	}
	return result;
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
            gid INTEGER
        );
    )";

	if (!executeSQL(createFilesTable)) {
		return false;
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

	return true;
}

bool DatabaseManager::insertFileRecord(const FileRecord& record) {
	const char* sql = R"(
        INSERT INTO files (inode, name, path, size, atime, mtime, ctime, crtime,
                          type, md5, is_deleted, is_allocated, permissions, uid, gid)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    )";

	sqlite3_stmt* stmt;
	int rc = sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr);

	if (rc != SQLITE_OK) {
		std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db_) << std::endl;
		return false;
	}

	sqlite3_bind_int64(stmt, 1, record.inode);
	sqlite3_bind_text(stmt, 2, record.name.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 3, record.path.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int64(stmt, 4, record.size);
	sqlite3_bind_int64(stmt, 5, record.atime);
	sqlite3_bind_int64(stmt, 6, record.mtime);
	sqlite3_bind_int64(stmt, 7, record.ctime);
	sqlite3_bind_int64(stmt, 8, record.crtime);
	sqlite3_bind_text(stmt, 9, record.type.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_text(stmt, 10, record.md5.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int(stmt, 11, record.isDeleted);
	sqlite3_bind_int(stmt, 12, record.isAllocated);
	sqlite3_bind_text(stmt, 13, record.permissions.c_str(), -1, SQLITE_TRANSIENT);
	sqlite3_bind_int(stmt, 14, record.uid);
	sqlite3_bind_int(stmt, 15, record.gid);

	rc = sqlite3_step(stmt);
	sqlite3_finalize(stmt);

	return rc == SQLITE_DONE;
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