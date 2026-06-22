// MemoryAnalysisDatabase.cpp
#include "MemoryAnalysisDatabase.h"
#include "DatabaseManager/SQL/memory_analysis_sql.h"
#include <iostream>

MemoryAnalysisDatabase::MemoryAnalysisDatabase(const std::string& dbPath)
    : dbPath_(dbPath) {}

MemoryAnalysisDatabase::~MemoryAnalysisDatabase() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (db_) { sqlite3_close(db_); db_ = nullptr; }
}

bool MemoryAnalysisDatabase::initialize() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (sqlite3_open(dbPath_.c_str(), &db_) != SQLITE_OK) {
        lastError_ = db_ ? sqlite3_errmsg(db_) : "open failed";
        return false;
    }
    char* err = nullptr;
    if (sqlite3_exec(db_, MemoryAnalysisSQL::CREATE_ALL_TABLES, nullptr, nullptr, &err) != SQLITE_OK) {
        lastError_ = err ? err : "create tables failed";
        sqlite3_free(err);
        return false;
    }
    return true;
}

bool MemoryAnalysisDatabase::exec(const std::string& sql) {
    char* err = nullptr;
    int rc = sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &err);
    if (rc != SQLITE_OK) { lastError_ = err ? err : "exec failed"; sqlite3_free(err); return false; }
    return true;
}

bool MemoryAnalysisDatabase::bindAndStep(const std::string& sql, const std::vector<std::string>& vals) {
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        lastError_ = sqlite3_errmsg(db_); return false;
    }
    for (size_t i = 0; i < vals.size(); ++i) {
        sqlite3_bind_text(stmt, static_cast<int>(i + 1), vals[i].c_str(), -1, SQLITE_TRANSIENT);
    }
    bool ok = sqlite3_step(stmt) == SQLITE_DONE;
    if (!ok) lastError_ = sqlite3_errmsg(db_);
    sqlite3_finalize(stmt);
    return ok;
}

bool MemoryAnalysisDatabase::insertProcess(long offset, int pid, int ppid, const std::string& comm,
                                           int uid, int gid, long start_time, int threads, const std::string& state) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_PROCESS,
        {std::to_string(offset), std::to_string(pid), std::to_string(ppid), comm,
         std::to_string(uid), std::to_string(gid), std::to_string(start_time),
         std::to_string(threads), state});
}

bool MemoryAnalysisDatabase::insertNetworkConnection(long offset, int pid, const std::string& comm,
                                                     const std::string& protocol,
                                                     const std::string& local_addr, int local_port,
                                                     const std::string& foreign_addr, int foreign_port,
                                                     const std::string& state) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_NETWORK_CONNECTION,
        {std::to_string(offset), std::to_string(pid), comm, protocol,
         local_addr, std::to_string(local_port), foreign_addr,
         std::to_string(foreign_port), state});
}

bool MemoryAnalysisDatabase::insertSocket(long offset, int pid, const std::string& comm,
                                          const std::string& family, const std::string& type,
                                          const std::string& local_addr, const std::string& remote_addr,
                                          const std::string& state) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_SOCKET,
        {std::to_string(offset), std::to_string(pid), comm, family, type,
         local_addr, remote_addr, state});
}

bool MemoryAnalysisDatabase::insertBashHistory(int pid, const std::string& comm,
                                               const std::string& command, int history_index) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_BASH_HISTORY,
        {std::to_string(pid), comm, command, std::to_string(history_index)});
}

bool MemoryAnalysisDatabase::setBootInfo(const std::string& key, const std::string& value) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::UPSERT_BOOT_INFO, {key, value});
}

bool MemoryAnalysisDatabase::insertCmdline(int pid, const std::string& comm, const std::string& args) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_CMDLINE,
        {std::to_string(pid), comm, args});
}

bool MemoryAnalysisDatabase::setMeta(const std::string& key, const std::string& value) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::UPSERT_ANALYSIS_META, {key, value});
}

std::vector<std::vector<std::string>> MemoryAnalysisDatabase::query(const std::string& sql) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::vector<std::string>> rows;
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        lastError_ = sqlite3_errmsg(db_); return rows;
    }
    int n = sqlite3_column_count(stmt);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::vector<std::string> row(n);
        for (int i = 0; i < n; ++i) {
            const unsigned char* t = sqlite3_column_text(stmt, i);
            row[i] = t ? reinterpret_cast<const char*>(t) : "";
        }
        rows.push_back(std::move(row));
    }
    sqlite3_finalize(stmt);
    return rows;
}
