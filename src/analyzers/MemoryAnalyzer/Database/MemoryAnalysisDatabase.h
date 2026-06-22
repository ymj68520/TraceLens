// MemoryAnalysisDatabase.h
// SQLite wrapper for the MemoryAnalyzer _memory.db

#pragma once
#include <string>
#include <vector>
#include <mutex>
#include <sqlite3.h>

class MemoryAnalysisDatabase {
public:
    explicit MemoryAnalysisDatabase(const std::string& dbPath);
    ~MemoryAnalysisDatabase();

    MemoryAnalysisDatabase(const MemoryAnalysisDatabase&) = delete;
    MemoryAnalysisDatabase& operator=(const MemoryAnalysisDatabase&) = delete;

    // Open the DB and run CREATE_ALL_TABLES. Returns false on failure.
    bool initialize();

    // ---- Typed inserts (return false on SQL error) ----
    bool insertProcess(long offset, int pid, int ppid, const std::string& comm,
                       int uid, int gid, long start_time, int threads, const std::string& state);
    bool insertNetworkConnection(long offset, int pid, const std::string& comm,
                                 const std::string& protocol,
                                 const std::string& local_addr, int local_port,
                                 const std::string& foreign_addr, int foreign_port,
                                 const std::string& state);
    bool insertSocket(long offset, int pid, const std::string& comm,
                      const std::string& family, const std::string& type,
                      const std::string& local_addr, const std::string& remote_addr,
                      const std::string& state);
    bool insertBashHistory(int pid, const std::string& comm,
                           const std::string& command, int history_index);
    bool setBootInfo(const std::string& key, const std::string& value);
    bool insertCmdline(int pid, const std::string& comm, const std::string& args);
    bool setMeta(const std::string& key, const std::string& value);

    // Generic query used by route handlers. Each row is a vector of column strings.
    std::vector<std::vector<std::string>> query(const std::string& sql);

    const std::string& lastError() const { return lastError_; }

private:
    bool exec(const std::string& sql);
    bool bindAndStep(const std::string& sql, const std::vector<std::string>& vals);

    std::string dbPath_;
    sqlite3* db_ = nullptr;
    std::mutex mutex_;
    std::string lastError_;
};
