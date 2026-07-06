// ReportGenerator.h
// Generates a human-readable Markdown forensic report from the analysis
// databases (files.db + events.db). Does NOT require AI/LLM — reads only
// the structured analysis tables populated by the platform analyzers.
//
// Currently covers Linux artifacts (linux_* tables). Windows and Android
// sections can be added later by extending the writer methods.

#pragma once

#include <string>
#include <fstream>
#include <sqlite3.h>

namespace forensics {

class ReportGenerator {
public:
    // filesDbPath:  path to the _files.db (linux_*/windows/android tables)
    // eventDbPath:  path to the _events.db (timeline events)
    ReportGenerator(const std::string& filesDbPath, const std::string& eventDbPath);

    // Write a Markdown report to outputPath.
    // imagePath is shown in the report header.
    // Returns true on success.
    bool writeMarkdown(const std::string& imagePath, const std::string& outputPath);

private:
    std::string filesDbPath_;
    std::string eventDbPath_;

    // --- Chapter writers (each opens its own sqlite3 connection) ---
    void writeHeader(std::ofstream& out, const std::string& imagePath);
    void writeSummary(std::ofstream& out);                // per-table row counts
    void writeUsers(std::ofstream& out);                  // linux_users
    void writeShellHistory(std::ofstream& out);           // linux_shell_history
    void writeCronJobs(std::ofstream& out);               // linux_cron_jobs
    void writeNetworkConnections(std::ofstream& out);     // linux_network_connections
    void writeLogHighlights(std::ofstream& out);          // linux_log_entries (non-INFO)
    void writeSecurityFindings(std::ofstream& out);       // linux_anomalies + tampering
    void writeTimeline(std::ofstream& out);               // events table (top entries)

    // --- Helpers ---
    int tableRowCount(sqlite3* db, const std::string& table);
    bool tableExists(sqlite3* db, const std::string& table);
};

} // namespace forensics
