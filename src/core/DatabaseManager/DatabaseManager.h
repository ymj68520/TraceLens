#pragma once
#ifndef DATABASE_MANAGER_H
#define DATABASE_MANAGER_H

#include <string>
#include <sqlite3.h>
#include <memory>
#include <vector>
#include <tsk/libtsk.h>

#include "DatabaseManagerDataTypes.h"

class DatabaseManager {
public:
	explicit DatabaseManager(const std::string& dbPath);
	~DatabaseManager();

	bool initialize();
	bool insertFileRecord(const FileRecord& record);
	bool insertEventRecord(const EventRecord& record);
	bool insertPartitionInfo(int partNum, int64_t start, int64_t length,
		const std::string& desc, const std::string& fsType);

	sqlite3* getDb() const { return db_; }
	const std::string& getDbPath() const { return dbPath_; }

private:
	std::string dbPath_;
	sqlite3* db_;

	bool createTables();
	bool executeSQL(const std::string& sql);
};

#endif // DATABASE_MANAGER_H
