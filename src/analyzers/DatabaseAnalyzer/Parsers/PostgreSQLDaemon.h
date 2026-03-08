#pragma once
#include <string>
#include <atomic>
#include <thread>
#include <libpq-fe.h>

namespace ForensicAnalyzer {
namespace Database {

class PostgreSQLDaemon {
public:
    PostgreSQLDaemon(const std::string& dataDir);
    ~PostgreSQLDaemon();

    bool start();
    void stop();
    bool isRunning() const { return isRunning_; }
    PGconn* getConnection() const { return conn_; }
    std::string getLastError() const { return lastError_; }

private:
    std::string dataDir_;
    std::string socketDir_;
    std::string logPath_;
    std::string lastError_;
    pid_t daemonPid_ = -1;
    std::atomic<bool> isRunning_{false};
    PGconn* conn_ = nullptr;
    
    bool checkPostgresAvailable();
};

} // namespace Database
} // namespace ForensicAnalyzer
