#pragma once
#ifndef DATABASE_MANAGER_H
#define DATABASE_MANAGER_H

#include <string>
#include <sqlite3.h>
#include <memory>
#include <mutex>
#include <vector>
#include <tsk/libtsk.h>

#include "DatabaseManagerDataTypes.h"

/**
 * @brief Manages SQLite database operations for forensic analysis
 * Handles database initialization, record insertion, and query execution.
 */
class DatabaseManager {
public:
	/**
	 * @brief Construct a new Database Manager object
	 * @param dbPath Path to the SQLite database file
	 */
	explicit DatabaseManager(const std::string& dbPath);

	/**
	 * @brief Destroy the Database Manager object and close connection
	 */
	~DatabaseManager();

	/**
	 * @brief Initialize the database
	 * Opens connection and creates necessary tables.
	 * @return true if initialization successful
	 */
	bool initialize();

	/**
	 * @brief Insert a file record into the database
	 * @param record The file record to insert
	 * @return true if insertion successful
	 */
	bool insertFileRecord(const FileRecord& record);

	/**
	 * @brief Commit rows batched by insertFileRecord's auto-batching.
	 *
	 * insertFileRecord wraps rows in implicit multi-row transactions (one
	 * commit per kInsertBatchRows rows) so a per-row autocommit fsync cannot
	 * dominate extraction throughput on spinning disks (measured ~0.5 s per
	 * fsync on the extraction disk). Readers on OTHER connections only see
	 * committed rows — call this after a bulk walk and before the DB is
	 * handed to downstream consumers on new connections.
	 */
	void flushInsertBatch();

	/**
	 * @brief Insert an event record into the database
	 * @param record The event record to insert
	 * @return true if insertion successful
	 */
	bool insertEventRecord(const EventRecord& record);

	/**
	 * @brief Insert partition information
	 * @param partNum Partition number
	 * @param start Start offset
	 * @param length Partition length
	 * @param desc Description of the partition
	 * @param fsType File system type
	 * @return true if insertion successful
	 */
	bool insertPartitionInfo(int partNum, int64_t start, int64_t length,
		const std::string& desc, const std::string& fsType);

	/**
	 * @brief Count rows in the files table
	 * @return number of file records, or -1 on error
	 */
	int getFileCount();

	/**
	 * @brief Get the raw SQLite database connection
	 * @return sqlite3* Pointer to SQLite connection
	 */
	sqlite3* getDb() const { return db_; }

	/**
	 * @brief Get the database file path
	 * @return const std::string& Path to database
	 */
	const std::string& getDbPath() const { return dbPath_; }

private:
	std::string dbPath_;
	sqlite3* db_;

	bool createTables();
	bool executeSQL(const std::string& sql);
	void checkAndMigrate();

	// insertFileRecord keeps its INSERT prepared across calls (re-preparing
	// the 16-parameter statement per row is pure CPU overhead) and batches
	// rows into one transaction per kInsertBatchRows rows.
	std::mutex insertMutex_;
	sqlite3_stmt* insertFileStmt_ = nullptr;
	int uncommittedInserts_ = 0;
	static constexpr int kInsertBatchRows = 2000;
};

#endif // DATABASE_MANAGER_H
