#include "MySQLDaemon.h"
#include <iostream>
#include <unistd.h>
#include <sys/wait.h>
#include <filesystem>
#include <cstdlib>
#include <signal.h>

namespace fs = std::filesystem;

namespace ForensicAnalyzer {
namespace Database {

MySQLDaemon::MySQLDaemon(const std::string& dataDir) : dataDir_(dataDir) {
    socketPath_ = dataDir + "/mysql.sock";
    logPath_ = dataDir + "/mysqld.log";
}

MySQLDaemon::~MySQLDaemon() {
    stop();
}

bool MySQLDaemon::checkMySqlAvailable() {
    return system("which mysqld > /dev/null 2>&1") == 0;
}

bool MySQLDaemon::start() {
    if (!checkMySqlAvailable()) {
        lastError_ = "mysqld binary not found in PATH.";
        return false;
    }

    pid_t pid = fork();
    if (pid == -1) {
        lastError_ = "Failed to fork mysqld process.";
        return false;
    } else if (pid == 0) {
        // Child process
        std::string cmd = "mysqld --skip-grant-tables --skip-networking --socket=" + socketPath_ +
                          " --datadir=" + dataDir_ + " --log-error=" + logPath_;
        execl("/bin/sh", "sh", "-c", cmd.c_str(), NULL);
        exit(1); // Exits if execl fails
    } else {
        daemonPid_ = pid;
        // Wait for socket to appear (max 10 seconds)
        for (int i = 0; i < 100; i++) {
            if (fs::exists(socketPath_)) {
                break;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }

        if (!fs::exists(socketPath_)) {
            lastError_ = "mysqld failed to start or socket not created in time.";
            stop();
            return false;
        }

        conn_ = mysql_init(NULL);
        if (conn_ == NULL) {
            lastError_ = "mysql_init() failed.";
            stop();
            return false;
        }

        // Connect using the local socket
        if (mysql_real_connect(conn_, "localhost", "root", "", NULL, 0, socketPath_.c_str(), 0) == NULL) {
            lastError_ = std::string("mysql_real_connect() failed: ") + mysql_error(conn_);
            stop();
            return false;
        }

        isRunning_ = true;
        return true;
    }
}

void MySQLDaemon::stop() {
    if (conn_) {
        mysql_close(conn_);
        conn_ = nullptr;
    }

    if (daemonPid_ != -1) {
        kill(daemonPid_, SIGTERM);
        waitpid(daemonPid_, NULL, 0);
        daemonPid_ = -1;
    }
    
    // Clean up temporary files
    if (fs::exists(socketPath_)) {
        fs::remove(socketPath_);
    }
    isRunning_ = false;
}

} // namespace Database
} // namespace ForensicAnalyzer
