#include "PostgreSQLDaemon.h"
#include "PathManager/PathManager.h"
#include <iostream>
#include <unistd.h>
#include <sys/wait.h>
#include <filesystem>
#include <cstdlib>
#include <signal.h>

namespace fs = std::filesystem;

namespace ForensicAnalyzer {
namespace Database {

PostgreSQLDaemon::PostgreSQLDaemon(const std::string& dataDir) : dataDir_(dataDir) {
    socketDir_ = forensics::PathManager::instance().makeTempPath("pg_sockets_");
    logPath_ = dataDir + "/postgres.log";
}

PostgreSQLDaemon::~PostgreSQLDaemon() {
    stop();
}

bool PostgreSQLDaemon::checkPostgresAvailable() {
    // Usually pg is in /usr/lib/postgresql/XX/bin/postgres or global PATH
    return system("which postgres > /dev/null 2>&1 || ls /usr/lib/postgresql/*/bin/postgres > /dev/null 2>&1") == 0;
}

bool PostgreSQLDaemon::start() {
    if (!checkPostgresAvailable()) {
        lastError_ = "postgres binary not found in PATH or standard directories.";
        return false;
    }

    // Create unique socket directory to avoid colliding with running instances
    fs::create_directories(socketDir_);
    fs::permissions(socketDir_, fs::perms::owner_all);

    pid_t pid = fork();
    if (pid == -1) {
        lastError_ = "Failed to fork postgres process.";
        return false;
    } else if (pid == 0) {
        // Child process
        // Try searching path, otherwise fallback to finding the newest version in /usr/lib
        std::string cmd = "PATH=$PATH:/usr/lib/postgresql/16/bin:/usr/lib/postgresql/15/bin:/usr/lib/postgresql/14/bin "
                          "postgres -D " + dataDir_ + " -p 5433 -k " + socketDir_ + 
                          " -c listen_addresses='' > " + logPath_ + " 2>&1";
        execl("/bin/sh", "sh", "-c", cmd.c_str(), NULL);
        exit(1); 
    } else {
        daemonPid_ = pid;
        // Wait for socket to appear
        bool socketFound = false;
        for (int i = 0; i < 100; i++) {
            for (const auto& entry : fs::directory_iterator(socketDir_)) {
                if (entry.path().string().find(".s.PGSQL") != std::string::npos) {
                    socketFound = true;
                    break;
                }
            }
            if (socketFound) break;
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }

        if (!socketFound) {
            lastError_ = "postgres failed to start or socket not created in time.";
            stop();
            return false;
        }

        // Connect using libpq through socket
        std::string conninfo = "host=" + socketDir_ + " port=5433 dbname=postgres user=postgres";
        conn_ = PQconnectdb(conninfo.c_str());

        if (PQstatus(conn_) != CONNECTION_OK) {
            // some forensic images don't have a default 'postgres' user, maybe 'root' or original system user
            // we skip explicit error failing and let getRecords handle the fallback testing
            lastError_ = PQerrorMessage(conn_);
        } else {
            lastError_ = "";
        }

        isRunning_ = true;
        return true;
    }
}

void PostgreSQLDaemon::stop() {
    if (conn_) {
        PQfinish(conn_);
        conn_ = nullptr;
    }

    if (daemonPid_ != -1) {
        // give it a gentle SIGINT commonly used by postgres fast shutdown
        kill(daemonPid_, SIGINT);
        int status;
        waitpid(daemonPid_, &status, 0);
        daemonPid_ = -1;
    }
    
    // Clean up temporary files
    if (fs::exists(socketDir_)) {
        fs::remove_all(socketDir_);
    }
    isRunning_ = false;
}

} // namespace Database
} // namespace ForensicAnalyzer
