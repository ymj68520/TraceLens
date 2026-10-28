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
    if (ts <= 0) return "未记录";
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

    out << "\n*本报告根据结构化解析数据生成，"
        << "不依赖人工智能模型处理。*\n";

    return true;
}

// ---------------------------------------------------------------------------
// Chapter implementations
// ---------------------------------------------------------------------------

void ReportGenerator::writeHeader(std::ofstream& out, const std::string& imagePath) {
    out << "# 取证分析报告\n\n";
    out << "| 项目 | 内容 |\n";
    out << "|-------|-------|\n";
    out << "| **检材来源** | `" << mdEscape(imagePath) << "` |\n";
    out << "| **文件数据库** | `" << mdEscape(filesDbPath_) << "` |\n";
    if (!eventDbPath_.empty()) {
        out << "| **事件数据库** | `" << mdEscape(eventDbPath_) << "` |\n";
    }
    out << "| **生成时间** | " << currentTimeString() << " |\n\n";
    out << "---\n\n";
}

void ReportGenerator::writeSummary(std::ofstream& out) {
    sqlite3* db = nullptr;
    if (sqlite3_open(filesDbPath_.c_str(), &db) != SQLITE_OK) {
        out << "## 数据摘要\n\n> 无法打开文件数据库\n\n";
        if (db) sqlite3_close(db);
        return;
    }

    out << "## 数据摘要\n\n";
    out << "| 数据类别 | 记录数 |\n";
    out << "|--------------|--------:|\n";

    auto appendRowsForPrefix = [&](const std::string& prefix,
                                   const std::string& categoryPrefix) {
        bool any = false;
        sqlite3_stmt* stmt = nullptr;
        const char* sql =
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "AND name GLOB ? ORDER BY name";
        if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) != SQLITE_OK) {
            return;
        }
        std::string pattern = prefix + "*";
        sqlite3_bind_text(stmt, 1, pattern.c_str(), -1, SQLITE_TRANSIENT);
        while (sqlite3_step(stmt) == SQLITE_ROW) {
            const char* table = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
            int count = tableRowCount(db, table);
            if (count >= 0) {
                any = true;
                std::string label = categoryPrefix;
                label += "解析记录（" + std::string(table) + "）";
                out << "| " << mdEscape(label) << " | " << count << " |\n";
            }
        }
        sqlite3_finalize(stmt);
        if (!any) {
            out << "| " << mdEscape(categoryPrefix + "解析记录") << " | — |\n";
        }
    };

    appendRowsForPrefix("linux_", "Linux ");
    appendRowsForPrefix("windows_", "Windows ");
    appendRowsForPrefix("android_", "Android ");
    for (const auto& [table, label] : std::vector<std::pair<std::string, std::string>>{
            {"files", "已分类文件"}, {"mobile_artifacts", "手机备份记录"},
            {"sms_messages", "短信"}, {"contacts", "联系人"}, {"call_logs", "通话记录"},
            {"installed_packages", "安装包信息"}, {"wifi_networks", "无线网络"}}) {
        const int count = tableRowCount(db, table);
        if (count >= 0) out << "| " << label << " | " << count << " |\n";
    }

    if (!eventDbPath_.empty()) {
        sqlite3* ev = nullptr;
        if (sqlite3_open(eventDbPath_.c_str(), &ev) == SQLITE_OK) {
            int total = tableRowCount(ev, "events");
            if (total >= 0) {
                out << "| 时间线事件 | " << total << " |\n";
            }
            sqlite3_close(ev);
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

    out << "## 用户账户\n\n";
    out << "| 用户名 | 用户编号 | 组编号 | 命令解释器 | 主目录 | 已锁定 | 系统账户 |\n";
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
            << " | " << (locked ? "🔒 Yes" : "否")
            << " | " << (sysacct ? "是" : "否") << " |\n";
        ++rowCount;
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rowCount == 0) {
        out << "*未发现用户账户。*\n";
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

    out << "## 命令历史\n\n";
    std::set<std::string> users;
    while (sqlite3_step(userStmt) == SQLITE_ROW) {
        users.insert(colText(userStmt, 0));
    }
    sqlite3_finalize(userStmt);

    if (users.empty()) {
        out << "*未发现命令历史。*\n\n---\n\n";
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
        out << "### " << mdEscape(user) << " (" << cmds.size() << " 条命令)\n\n";
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

    out << "## 定时任务\n\n";
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

        out << "**计划：** `" << minute << " " << hour << " " << dom << " "
            << month << " " << dow << "` ";
        out << "| **用户：** " << mdEscape(user) << " ";
        out << "| **类型：** " << mdEscape(type) << "\n";
        out << "- **命令：** `" << mdEscape(command) << "`\n";
        out << "- **文件：** `" << mdEscape(file) << "`\n\n";
        ++rowCount;
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);

    if (rowCount == 0) {
        out << "*未发现定时任务。*\n\n";
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

    out << "## 网络连接\n\n";
    out << "| 协议 | 本地地址及端口 | 远程地址及端口 | 状态 | 进程及编号 |\n";
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
        out << "*未发现网络连接。*\n";
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

    out << "## 重要日志\n\n";
    out << "*展示警告、错误及严重级别日志。日志总数："
        << total << ".*\n\n";

    out << "| 时间 | 级别 | 进程 | 日志内容 |\n";
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
        out << "*未发现警告或错误日志（记录均为信息级别）。*\n";
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
            out << "## 安全分析结果\n\n";
            out << "### 检测到的异常\n\n";
            out << "| 严重程度 | 类型 | 子类型 | 说明 |\n";
            out << "|:--------:|------|---------|-------------|\n";

            int rowCount = 0;
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                std::string type    = colText(stmt, 0);
                std::string desc    = colText(stmt, 1);
                int severity        = sqlite3_column_int(stmt, 2);
                std::string subtype = colText(stmt, 3);

                std::string sevLabel;
                switch (severity) {
                    case 4: sevLabel = "🔴 严重"; break;
                    case 3: sevLabel = "🟠 高"; break;
                    case 2: sevLabel = "🟡 中"; break;
                    case 1: sevLabel = "🔵 低"; break;
                    default: sevLabel = "ℹ️ 信息"; break;
                }

                out << "| " << sevLabel << " | " << mdEscape(type)
                    << " | " << mdEscape(subtype)
                    << " | " << mdEscape(desc) << " |\n";
                ++rowCount;
            }
            if (rowCount == 0) {
                out << "*未检测到异常。*\n";
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
            out << "### 日志篡改迹象\n\n";
            out << "| 严重程度 | 类型 | 来源 | 说明 |\n";
            out << "|:--------:|------|--------|-------------|\n";

            int rowCount = 0;
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                std::string type = colText(stmt, 0);
                int severity     = sqlite3_column_int(stmt, 1);
                std::string desc = colText(stmt, 2);
                std::string src  = colText(stmt, 3);

                std::string sevLabel;
                if (severity >= 3) sevLabel = "🔴 高";
                else if (severity >= 2) sevLabel = "🟡 中";
                else if (severity >= 1) sevLabel = "🔵 低";
                else sevLabel = "ℹ️ 信息";

                out << "| " << sevLabel << " | " << mdEscape(type)
                    << " | " << mdEscape(src)
                    << " | " << mdEscape(desc) << " |\n";
                ++rowCount;
            }
            if (rowCount == 0) {
                out << "*未发现篡改迹象。*\n";
            }
            out << "\n";
            sqlite3_finalize(stmt);
        }
    }

    if (!tableExists(db, "linux_anomalies") && !tableExists(db, "linux_tampering_findings")) {
        out << "## 安全分析结果\n\n*没有可用的安全分析数据表。*\n\n";
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

    out << "## 时间线（前 100 条事件）\n\n";
    out << "| 时间 | 类型 | 路径 | 说明 | 严重程度 |\n";
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
        out << "*未发现时间线事件。*\n";
    }
    out << "\n---\n\n";
}

} // namespace forensics
