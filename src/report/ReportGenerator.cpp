// ReportGenerator.cpp
// Implementation of the Markdown forensic report generator.
// Reads linux_* tables from files.db and events from events.db.
// No AI/LLM dependency — purely structured data extraction.

#include "ReportGenerator.h"
#include <sqlite3.h>
#include <fstream>
#include <iostream>
#include <ctime>
#include <sstream>
#include <iomanip>
#include <set>
#include <vector>

namespace forensics {

ReportGenerator::ReportGenerator(const std::string& filesDbPath, const std::string& eventDbPath)
    : filesDbPath_(filesDbPath), eventDbPath_(eventDbPath) {
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

bool ReportGenerator::tableExists(sqlite3* db, const std::string& table) {
    sqlite3_stmt* stmt = nullptr;
    std::string sql = "SELECT name FROM sqlite_master WHERE type='table' AND name=?";
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return false;
    }
    sqlite3_bind_text(stmt, 1, table.c_str(), -1, SQLITE_TRANSIENT);
    bool found = (sqlite3_step(stmt) == SQLITE_ROW);
    sqlite3_finalize(stmt);
    return found;
}

int ReportGenerator::tableRowCount(sqlite3* db, const std::string& table) {
    if (!tableExists(db, table)) return -1;  // table missing
    sqlite3_stmt* stmt = nullptr;
    std::string sql = "SELECT COUNT(*) FROM \"" + table + "\"";
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return -1;
    }
    int count = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        count = sqlite3_column_int(stmt, 0);
    }
    sqlite3_finalize(stmt);
    return count;
}

// Format a unix timestamp as "YYYY-MM-DD HH:MM:SS"
static std::string formatTimestamp(int64_t ts) {
    if (ts <= 0) return "N/A";
    std::time_t t = static_cast<std::time_t>(ts);
    std::tm tm{};
    localtime_r(&t, &tm);
    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
    return oss.str();
}

static std::string currentTimeString() {
    std::time_t now = std::time(nullptr);
    std::tm tm{};
    localtime_r(&now, &tm);
    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
    return oss.str();
}

// Escape pipe characters for Markdown table cells
static std::string mdEscape(const std::string& s) {
    std::string out;
    out.reserve(s.size());
    for (char c : s) {
        if (c == '|') out += "\\|";
        else if (c == '\n' || c == '\r') out += ' ';
        else out += c;
    }
    return out;
}

// Get text column from a prepared statement as std::string
static std::string colText(sqlite3_stmt* stmt, int col) {
    const unsigned char* text = sqlite3_column_text(stmt, col);
    return text ? reinterpret_cast<const char*>(text) : "";
}

// ---------------------------------------------------------------------------
// Main entry
// ---------------------------------------------------------------------------

bool ReportGenerator::writeMarkdown(const std::string& imagePath, const std::string& outputPath) {
    std::ofstream out(outputPath);
    if (!out.is_open()) {
        std::cerr << "Error: Cannot create report file: " << outputPath << std::endl;
        return false;
    }

    writeHeader(out, imagePath);
    writeSummary(out);

    // Linux artifact sections
    writeUsers(out);
    writeShellHistory(out);
    writeCronJobs(out);
    writeNetworkConnections(out);
    writeLogHighlights(out);
    writeSecurityFindings(out);
    writeTimeline(out);

    out << "\n*This report was generated from structured analysis data and does not "
        << "require AI/LLM processing.*\n";

    return true;
}

// ---------------------------------------------------------------------------
// Chapter implementations
// ---------------------------------------------------------------------------

void ReportGenerator::writeHeader(std::ofstream& out, const std::string& imagePath) {
    out << "# Forensic Analysis Report\n\n";
    out << "| Field | Value |\n";
    out << "|-------|-------|\n";
    out << "| **Source Image** | `" << mdEscape(imagePath) << "` |\n";
    out << "| **Files DB** | `" << mdEscape(filesDbPath_) << "` |\n";
    if (!eventDbPath_.empty()) {
        out << "| **Events DB** | `" << mdEscape(eventDbPath_) << "` |\n";
    }
    out << "| **Generated At** | " << currentTimeString() << " |\n\n";
    out << "---\n\n";
}

void ReportGenerator::writeSummary(std::ofstream& out) {
    sqlite3* db = nullptr;
    if (sqlite3_open(filesDbPath_.c_str(), &db) != SQLITE_OK) {
        out << "## Data Summary\n\n> Cannot open files.db\n\n";
        if (db) sqlite3_close(db);
        return;
    }

    // Linux tables to summarize
    struct TableEntry { const char* table; const char* label; };
    TableEntry linuxTables[] = {
        {"linux_users",               "User Accounts"},
        {"linux_groups",              "Groups"},
        {"linux_login_records",       "Login Records"},
        {"linux_shell_history",       "Shell History"},
        {"linux_cron_jobs",           "Cron Jobs"},
        {"linux_ssh_keys",            "SSH Keys"},
        {"linux_packages",            "Installed Packages"},
        {"linux_network_connections", "Network Connections"},
        {"linux_systemd_services",    "Systemd Services"},
        {"linux_log_entries",         "Log Entries"},
        {"linux_audit_logs",          "Audit Logs"},
        {"linux_anomalies",           "Detected Anomalies"},
        {"linux_tampering_findings",  "Log Tampering Findings"},
        {"linux_timeline_events",     "Timeline Events"},
    };

    out << "## Data Summary\n\n";
    out << "| Data Category | Records |\n";
    out << "|--------------|--------:|\n";
    for (const auto& e : linuxTables) {
        int count = tableRowCount(db, e.table);
        if (count >= 0) {
            out << "| " << e.label << " | " << count << " |\n";
        }
    }
    out << "\n---\n\n";

    sqlite3_close(db);
}

void ReportGenerator::writeUsers(std::ofstream& out) {
    sqlite3* db = nullptr;
    if (sqlite3_open(filesDbPath_.c_str(), &db) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }
    if (!tableExists(db, "linux_users")) { sqlite3_close(db); return; }

    sqlite3_stmt* stmt = nullptr;
    const char* sql =
        "SELECT username, uid, gid, shell, home_directory, "
        "       is_locked, is_system_account "
        "FROM linux_users ORDER BY uid";
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return;
    }

    out << "## User Accounts\n\n";
    out << "| Username | UID | GID | Shell | Home Directory | Locked? | System? |\n";
    out << "|----------|----:|----:|-------|---------------|:-------:|:-------:|\n";

    int rowCount = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::string username = colText(stmt, 0);
        int uid = sqlite3_column_int(stmt, 1);
        int gid = sqlite3_column_int(stmt, 2);
        std::string shell = colText(stmt, 3);
        std::string home = colText(stmt, 4);
        int locked = sqlite3_column_int(stmt, 5);
        int sysacct = sqlite3_column_int(stmt, 6);

        out << "| " << mdEscape(username) << " | " << uid << " | " << gid
            << " | `" << mdEscape(shell) << "` | `" << mdEscape(home) << "`"
            << " | " << (locked ? "🔒 Yes" : "No")
            << " | " << (sysacct ? "Yes" : "No") << " |\n";
        ++rowCount;
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rowCount == 0) {
        out << "*No user accounts found.*\n";
    }
    out << "\n---\n\n";
}

void ReportGenerator::writeShellHistory(std::ofstream& out) {
    sqlite3* db = nullptr;
    if (sqlite3_open(filesDbPath_.c_str(), &db) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }
    if (!tableExists(db, "linux_shell_history")) { sqlite3_close(db); return; }

    // Get distinct usernames
    sqlite3_stmt* userStmt = nullptr;
    if (sqlite3_prepare_v2(db, "SELECT DISTINCT username FROM linux_shell_history ORDER BY username",
                           -1, &userStmt, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return;
    }

    out << "## Shell History\n\n";
    std::set<std::string> users;
    while (sqlite3_step(userStmt) == SQLITE_ROW) {
        users.insert(colText(userStmt, 0));
    }
    sqlite3_finalize(userStmt);

    if (users.empty()) {
        out << "*No shell history found.*\n\n---\n\n";
        sqlite3_close(db);
        return;
    }

    for (const auto& user : users) {
        sqlite3_stmt* stmt = nullptr;
        std::string sql =
            "SELECT command, line_number FROM linux_shell_history "
            "WHERE username=? ORDER BY line_number";
        if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) continue;
        sqlite3_bind_text(stmt, 1, user.c_str(), -1, SQLITE_TRANSIENT);

        // Collect commands
        std::vector<std::pair<int, std::string>> cmds;
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            int lineNum = sqlite3_column_int(stmt, 1);
            cmds.emplace_back(lineNum, colText(stmt, 0));
        }
        sqlite3_finalize(stmt);

        if (cmds.empty()) continue;
        out << "### " << mdEscape(user) << " (" << cmds.size() << " commands)\n\n";
        out << "```\n";
        for (const auto& [lineNum, cmd] : cmds) {
            if (lineNum > 0)
                out << "  " << lineNum << "  " << cmd << "\n";
            else
                out << "  " << cmd << "\n";
        }
        out << "```\n\n";
    }

    sqlite3_close(db);
    out << "---\n\n";
}

void ReportGenerator::writeCronJobs(std::ofstream& out) {
    sqlite3* db = nullptr;
    if (sqlite3_open(filesDbPath_.c_str(), &db) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }
    if (!tableExists(db, "linux_cron_jobs")) { sqlite3_close(db); return; }

    sqlite3_stmt* stmt = nullptr;
    const char* sql =
        "SELECT username, minute, hour, day_of_month, month, day_of_week, "
        "       command, cron_file, cron_type "
        "FROM linux_cron_jobs ORDER BY cron_file";
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return;
    }

    out << "## Cron Jobs\n\n";
    int rowCount = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::string user    = colText(stmt, 0);
        std::string minute  = colText(stmt, 1);
        std::string hour    = colText(stmt, 2);
        std::string dom     = colText(stmt, 3);
        std::string month   = colText(stmt, 4);
        std::string dow     = colText(stmt, 5);
        std::string command = colText(stmt, 6);
        std::string file    = colText(stmt, 7);
        std::string type    = colText(stmt, 8);

        out << "**Schedule:** `" << minute << " " << hour << " " << dom << " "
            << month << " " << dow << "` ";
        out << "| **User:** " << mdEscape(user) << " ";
        out << "| **Type:** " << mdEscape(type) << "\n";
        out << "- **Command:** `" << mdEscape(command) << "`\n";
        out << "- **File:** `" << mdEscape(file) << "`\n\n";
        ++rowCount;
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rowCount == 0) {
        out << "*No cron jobs found.*\n\n";
    }
    out << "---\n\n";
}

void ReportGenerator::writeNetworkConnections(std::ofstream& out) {
    sqlite3* db = nullptr;
    if (sqlite3_open(filesDbPath_.c_str(), &db) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }
    if (!tableExists(db, "linux_network_connections")) { sqlite3_close(db); return; }

    sqlite3_stmt* stmt = nullptr;
    const char* sql =
        "SELECT protocol, local_address, local_port, remote_address, remote_port, "
        "       state, process, pid FROM linux_network_connections";
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return;
    }

    out << "## Network Connections\n\n";
    out << "| Protocol | Local Address:Port | Remote Address:Port | State | Process (PID) |\n";
    out << "|----------|-------------------|---------------------|-------|----------------|\n";

    int rowCount = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::string proto   = colText(stmt, 0);
        std::string laddr   = colText(stmt, 1);
        int lport           = sqlite3_column_int(stmt, 2);
        std::string raddr   = colText(stmt, 3);
        int rport           = sqlite3_column_int(stmt, 4);
        std::string state   = colText(stmt, 5);
        std::string process = colText(stmt, 6);
        int pid             = sqlite3_column_int(stmt, 7);

        out << "| " << mdEscape(proto)
            << " | " << mdEscape(laddr) << ":" << lport
            << " | " << mdEscape(raddr) << ":" << rport
            << " | " << mdEscape(state)
            << " | " << mdEscape(process) << " (" << pid << ") |\n";
        ++rowCount;
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rowCount == 0) {
        out << "*No network connections found.*\n";
    }
    out << "\n---\n\n";
}

void ReportGenerator::writeLogHighlights(std::ofstream& out) {
    sqlite3* db = nullptr;
    if (sqlite3_open(filesDbPath_.c_str(), &db) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }
    if (!tableExists(db, "linux_log_entries")) { sqlite3_close(db); return; }

    // Total count
    int total = tableRowCount(db, "linux_log_entries");

    // Non-INFO entries (WARN, ERROR, CRITICAL, etc.)
    sqlite3_stmt* stmt = nullptr;
    const char* sql =
        "SELECT timestamp, hostname, process, pid, message, level, log_file "
        "FROM linux_log_entries "
        "WHERE level IS NOT NULL AND UPPER(level) NOT IN ('INFO', 'DEBUG', '') "
        "ORDER BY unix_timestamp LIMIT 200";
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return;
    }

    out << "## Log Highlights\n\n";
    out << "*Showing non-INFO entries (WARN/ERROR/CRITICAL). Total log entries: "
        << total << ".*\n\n";

    out << "| Timestamp | Level | Process | Message |\n";
    out << "|-----------|-------|---------|---------|\n";

    int rowCount = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::string ts      = colText(stmt, 0);
        std::string host    = colText(stmt, 1);
        std::string proc    = colText(stmt, 2);
        int pid             = sqlite3_column_int(stmt, 3);
        std::string msg     = colText(stmt, 4);
        std::string level   = colText(stmt, 5);

        // Truncate long messages
        if (msg.size() > 120) msg = msg.substr(0, 117) + "...";

        out << "| " << mdEscape(ts) << " | " << mdEscape(level)
            << " | " << mdEscape(proc) << " (" << pid << ")"
            << " | " << mdEscape(msg) << " |\n";
        ++rowCount;
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rowCount == 0) {
        out << "*No warning/error log entries found (all entries are INFO level).*\n";
    }
    out << "\n---\n\n";
}

void ReportGenerator::writeSecurityFindings(std::ofstream& out) {
    sqlite3* db = nullptr;
    if (sqlite3_open(filesDbPath_.c_str(), &db) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }

    // --- Anomalies ---
    if (tableExists(db, "linux_anomalies")) {
        sqlite3_stmt* stmt = nullptr;
        const char* sql =
            "SELECT anomaly_type, description, severity, anomaly_subtype "
            "FROM linux_anomalies ORDER BY severity DESC";
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            out << "## Security Findings\n\n";
            out << "### Detected Anomalies\n\n";
            out << "| Severity | Type | Subtype | Description |\n";
            out << "|:--------:|------|---------|-------------|\n";

            int rowCount = 0;
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                std::string type    = colText(stmt, 0);
                std::string desc    = colText(stmt, 1);
                int severity        = sqlite3_column_int(stmt, 2);
                std::string subtype = colText(stmt, 3);

                std::string sevLabel;
                switch (severity) {
                    case 4: sevLabel = "🔴 CRITICAL"; break;
                    case 3: sevLabel = "🟠 HIGH"; break;
                    case 2: sevLabel = "🟡 MEDIUM"; break;
                    case 1: sevLabel = "🔵 LOW"; break;
                    default: sevLabel = "ℹ️ INFO"; break;
                }

                out << "| " << sevLabel << " | " << mdEscape(type)
                    << " | " << mdEscape(subtype)
                    << " | " << mdEscape(desc) << " |\n";
                ++rowCount;
            }
            if (rowCount == 0) {
                out << "*No anomalies detected.*\n";
            }
            out << "\n";
            sqlite3_finalize(stmt);
        }
    }

    // --- Tampering Findings ---
    if (tableExists(db, "linux_tampering_findings")) {
        sqlite3_stmt* stmt = nullptr;
        const char* sql =
            "SELECT tampering_type, severity, description, log_source "
            "FROM linux_tampering_findings ORDER BY severity DESC";
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
            out << "### Log Tampering Indicators\n\n";
            out << "| Severity | Type | Source | Description |\n";
            out << "|:--------:|------|--------|-------------|\n";

            int rowCount = 0;
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                std::string type = colText(stmt, 0);
                int severity     = sqlite3_column_int(stmt, 1);
                std::string desc = colText(stmt, 2);
                std::string src  = colText(stmt, 3);

                std::string sevLabel;
                if (severity >= 3) sevLabel = "🔴 HIGH";
                else if (severity >= 2) sevLabel = "🟡 MEDIUM";
                else if (severity >= 1) sevLabel = "🔵 LOW";
                else sevLabel = "ℹ️ INFO";

                out << "| " << sevLabel << " | " << mdEscape(type)
                    << " | " << mdEscape(src)
                    << " | " << mdEscape(desc) << " |\n";
                ++rowCount;
            }
            if (rowCount == 0) {
                out << "*No tampering indicators found.*\n";
            }
            out << "\n";
            sqlite3_finalize(stmt);
        }
    }

    if (!tableExists(db, "linux_anomalies") && !tableExists(db, "linux_tampering_findings")) {
        out << "## Security Findings\n\n*No security tables found.*\n\n";
    }

    sqlite3_close(db);
    out << "---\n\n";
}

void ReportGenerator::writeTimeline(std::ofstream& out) {
    if (eventDbPath_.empty()) return;

    sqlite3* db = nullptr;
    if (sqlite3_open(eventDbPath_.c_str(), &db) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }
    if (!tableExists(db, "events")) { sqlite3_close(db); return; }

    sqlite3_stmt* stmt = nullptr;
    const char* sql =
        "SELECT timestamp, event_type, file_path, description, severity "
        "FROM events ORDER BY timestamp LIMIT 100";
    if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return;
    }

    out << "## Timeline (Top 100 Events)\n\n";
    out << "| Timestamp | Type | Path | Description | Severity |\n";
    out << "|-----------|------|------|-------------|----------|\n";

    int rowCount = 0;
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t ts     = sqlite3_column_int64(stmt, 0);
        std::string type = colText(stmt, 1);
        std::string path = colText(stmt, 2);
        std::string desc = colText(stmt, 3);
        std::string sev  = colText(stmt, 4);

        if (path.size() > 50) path = "..." + path.substr(path.size() - 47);

        out << "| " << formatTimestamp(ts) << " | " << mdEscape(type)
            << " | `" << mdEscape(path) << "`"
            << " | " << mdEscape(desc) << " | " << mdEscape(sev) << " |\n";
        ++rowCount;
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rowCount == 0) {
        out << "*No timeline events found.*\n";
    }
    out << "\n---\n\n";
}

} // namespace forensics
