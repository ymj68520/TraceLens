// LinuxAnalysisDatabase.h
// Database manager for storing Linux forensic analysis results

#pragma once
#ifndef LINUX_ANALYSIS_DATABASE_H
#define LINUX_ANALYSIS_DATABASE_H

#include <string>
#include <vector>
#include <mutex>
#include <sqlite3.h>
#include "LinuxDataTypes.h"
#include "LinuxQueryBuilder.h"
#include "Common/LinuxAnalyzerErrors.h"

// Forward declaration
namespace LinuxAnalysis {
    class QueryBuilder;
}

class LinuxAnalysisDatabase {
public:
    explicit LinuxAnalysisDatabase(const std::string& dbPath);
    ~LinuxAnalysisDatabase();

    // Initialize database and create tables
    bool initialize();

    // ========================================================================
    // Error handling
    // ========================================================================
    
    // Get last error that occurred
    const LinuxAnalysis::LinuxAnalyzerError& getLastError() const { return lastError_; }
    
    // Check if last operation succeeded
    bool hasError() const { return lastError_.isError(); }
    
    // Clear last error
    void clearError() { lastError_ = LinuxAnalysis::LinuxAnalyzerError(); }

    // ========================================================================
    // Log entry operations
    // ========================================================================
    bool insertLogEntry(const LinuxLogEntry& entry);
    bool insertLogEntries(const std::vector<LinuxLogEntry>& entries);
    
    // Type-safe query with QueryBuilder (recommended)
    std::vector<LinuxLogEntry> queryLogEntriesSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    // Legacy query method (deprecated - use queryLogEntriesSafe instead)
    [[deprecated("Use queryLogEntriesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<LinuxLogEntry> queryLogEntries(const std::string& whereClause = "");

    // ========================================================================
    // User account operations
    // ========================================================================
    bool insertUserInfo(const LinuxUserInfo& user);
    bool insertUserInfos(const std::vector<LinuxUserInfo>& users);
    
    std::vector<LinuxUserInfo> queryUserAccountsSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryUserAccountsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<LinuxUserInfo> queryUserAccounts(const std::string& whereClause = "");

    // ========================================================================
    // Group operations
    // ========================================================================
    bool insertGroupInfo(const LinuxGroupInfo& group);
    
    std::vector<LinuxGroupInfo> queryGroupsSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryGroupsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<LinuxGroupInfo> queryGroups(const std::string& whereClause = "");

    // ========================================================================
    // Login record operations
    // ========================================================================
    bool insertLoginRecord(const LinuxLoginRecord& record);
    bool insertLoginRecords(const std::vector<LinuxLoginRecord>& records);
    
    std::vector<LinuxLoginRecord> queryLoginRecordsSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryLoginRecordsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<LinuxLoginRecord> queryLoginRecords(const std::string& whereClause = "");

    // ========================================================================
    // Shell history operations
    // ========================================================================
    bool insertShellHistory(const ShellHistoryEntry& entry);
    bool insertShellHistories(const std::vector<ShellHistoryEntry>& entries);
    
    std::vector<ShellHistoryEntry> queryShellHistorySafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryShellHistorySafe with QueryBuilder for SQL injection protection")]]
    std::vector<ShellHistoryEntry> queryShellHistory(const std::string& whereClause = "");

    // ========================================================================
    // Cron job operations
    // ========================================================================
    bool insertCronJob(const CronJobEntry& job);
    bool insertCronJobs(const std::vector<CronJobEntry>& jobs);
    
    std::vector<CronJobEntry> queryCronJobsSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryCronJobsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<CronJobEntry> queryCronJobs(const std::string& whereClause = "");

    // ========================================================================
    // SSH key operations
    // ========================================================================
    bool insertSSHKey(const SSHKeyInfo& key);
    bool insertSSHKeys(const std::vector<SSHKeyInfo>& keys);
    
    std::vector<SSHKeyInfo> querySSHKeysSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use querySSHKeysSafe with QueryBuilder for SQL injection protection")]]
    std::vector<SSHKeyInfo> querySSHKeys(const std::string& whereClause = "");

    // ========================================================================
    // SSH known host operations
    // ========================================================================
    bool insertSSHKnownHost(const SSHKnownHost& host);
    
    std::vector<SSHKnownHost> querySSHKnownHostsSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use querySSHKnownHostsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<SSHKnownHost> querySSHKnownHosts(const std::string& whereClause = "");

    // ========================================================================
    // Package info operations
    // ========================================================================
    bool insertPackageInfo(const PackageInfo& pkg);
    bool insertPackageInfos(const std::vector<PackageInfo>& pkgs);
    
    std::vector<PackageInfo> queryPackagesSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryPackagesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<PackageInfo> queryPackages(const std::string& whereClause = "");

    // ========================================================================
    // Network connection operations
    // ========================================================================
    bool insertNetworkConnection(const NetworkConnection& conn);
    
    std::vector<NetworkConnection> queryNetworkConnectionsSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryNetworkConnectionsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<NetworkConnection> queryNetworkConnections(const std::string& whereClause = "");

    // ========================================================================
    // Systemd service operations
    // ========================================================================
    bool insertSystemdService(const SystemdServiceInfo& service);
    
    std::vector<SystemdServiceInfo> querySystemdServicesSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use querySystemdServicesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<SystemdServiceInfo> querySystemdServices(const std::string& whereClause = "");

    // ========================================================================
    // Kernel module operations
    // ========================================================================
    bool insertKernelModule(const KernelModuleInfo& module);
    
    std::vector<KernelModuleInfo> queryKernelModulesSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryKernelModulesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<KernelModuleInfo> queryKernelModules(const std::string& whereClause = "");

    // ========================================================================
    // Firewall rule operations
    // ========================================================================
    bool insertFirewallRule(const FirewallRule& rule);
    
    std::vector<FirewallRule> queryFirewallRulesSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryFirewallRulesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<FirewallRule> queryFirewallRules(const std::string& whereClause = "");

    // ========================================================================
    // Audit log operations
    // ========================================================================
    bool insertAuditLog(const LinuxAuditLogEntry& entry);
    bool insertAuditLogs(const std::vector<LinuxAuditLogEntry>& entries);
    
    std::vector<LinuxAuditLogEntry> queryAuditLogsSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryAuditLogsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<LinuxAuditLogEntry> queryAuditLogs(const std::string& whereClause = "");

    // ========================================================================
    // Browser profile operations
    // ========================================================================
    bool insertBrowserProfile(const LinuxBrowserProfile& profile);
    
    std::vector<LinuxBrowserProfile> queryBrowserProfilesSafe(const LinuxAnalysis::QueryBuilder& qb);
    
    [[deprecated("Use queryBrowserProfilesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<LinuxBrowserProfile> queryBrowserProfiles(const std::string& whereClause = "");

    // ========================================================================
    // Transaction management
    // ========================================================================
    bool beginTransaction();
    bool commitTransaction();
    bool rollbackTransaction();

    // Get database handle
    sqlite3* getDb() const { return db_; }
    const std::string& getDbPath() const { return dbPath_; }

private:
    std::string dbPath_;
    sqlite3* db_;
    mutable std::mutex mutex_;  // For thread safety
    LinuxAnalysis::LinuxAnalyzerError lastError_;

    bool createTables();
    bool executeSQL(const std::string& sql);
    
    // Set error state
    void setError(LinuxAnalysis::ErrorCode code, const std::string& details = "");
    void setError(const LinuxAnalysis::LinuxAnalyzerError& error);
    
    // Get SQLite error as LinuxAnalyzerError
    LinuxAnalysis::LinuxAnalyzerError getSQLiteError(LinuxAnalysis::ErrorCode code) const;
};

#endif // LINUX_ANALYSIS_DATABASE_H
