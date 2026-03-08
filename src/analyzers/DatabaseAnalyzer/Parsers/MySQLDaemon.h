#pragma once
#include <string>
#include <atomic>
#include <thread>
#include <mysql/mysql.h>

namespace ForensicAnalyzer {
namespace Database {

class MySQLDaemon {
public:
    MySQLDaemon(const std::string& dataDir);
    ~MySQLDaemon();

    bool start();
    void stop();
    bool isRunning() const { return isRunning_; }
    MYSQL* getConnection() const { return conn_; }
    std::string getLastError() const { return lastError_; }

private:
    std::string dataDir_;
    std::string socketPath_;
    std::string logPath_;
    std::string lastError_;
    pid_t daemonPid_ = -1;
    std::atomic<bool> isRunning_{false};
    MYSQL* conn_ = nullptr;
    
    bool checkMySqlAvailable();
    bool createSocketDir();
};

} // namespace Database
} // namespace ForensicAnalyzer
