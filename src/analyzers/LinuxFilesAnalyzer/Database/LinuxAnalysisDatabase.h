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

// Include headers for types used in function signatures
#include "Parsers/JournalParser.h"
#include "Parsers/AuditdAggregator.h"
#include "Analysis/LogTamperingDetector.h"
#include "Parsers/WebServer/MiddlewareLogParser.h"
#include "Parsers/Container/ContainerRuntimeLogParser.h"
#include "Parsers/PackageManager/PackageManagerLogParser.h"
#include "Analysis/AccountSSH/AccountSSHAnalyzer.h"
#include "Parsers/Database/DatabaseLogParser.h"
#include "Parsers/EmailVPN/EmailVPNLogParser.h"
#include "Parsers/FirewallSecurity/FirewallSecurityLogParser.h"

using forensics::linux::JournalEntry;
using forensics::linux::BootSession;
using forensics::linux::JournalAnomaly;
using forensics::linux::AggregatedAuditEvent;
using forensics::linux::TamperingFinding;
using forensics::linux::WebErrorLogEntry;
using forensics::linux::MiddlewareLogEntry;
using forensics::linux::ModSecurityAuditEntry;
using forensics::linux::DockerLogEntry;
using forensics::linux::CRILogEntry;
using forensics::linux::KubernetesPodLogEntry;
using forensics::linux::ContainerSecurityFinding;
using forensics::linux::PackageLogEntry;
using forensics::linux::SuspiciousPackageFinding;
using forensics::linux::AccountSecurityFinding;
using forensics::linux::SSHSecurityFinding;
using forensics::linux::DatabaseLogEntry;
using forensics::linux::DatabaseSecurityFinding;
using forensics::linux::EmailLogEntry;
using forensics::linux::VPNLogEntry;
using forensics::linux::EmailSecurityFinding;
using forensics::linux::VPNSecurityFinding;
using forensics::linux::FirewallLogEntry;
using forensics::linux::SecurityProductLogEntry;
using forensics::linux::SecurityProductFinding;

class LinuxAnalysisDatabase {
public:
    explicit LinuxAnalysisDatabase(const std::string& dbPath, bool integratedMode = false);
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

    // Aggregated audit events (multi-line events grouped by serial)
    bool insertAuditEvent(const AggregatedAuditEvent& event);
    bool insertAuditEvents(const std::vector<AggregatedAuditEvent>& events);

    // Tampering findings
    bool insertTamperingFinding(const TamperingFinding& finding);
    bool insertTamperingFindings(const std::vector<TamperingFinding>& findings);

    // ========================================================================
    // Browser profile operations
    // ========================================================================
    bool insertBrowserProfile(const LinuxBrowserProfile& profile);

    std::vector<LinuxBrowserProfile> queryBrowserProfilesSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryBrowserProfilesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<LinuxBrowserProfile> queryBrowserProfiles(const std::string& whereClause = "");

    // ========================================================================
    // Docker container operations
    // ========================================================================
    bool insertDockerContainer(const DockerContainerInfo& container);
    bool insertDockerContainers(const std::vector<DockerContainerInfo>& containers);

    std::vector<DockerContainerInfo> queryDockerContainersSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryDockerContainersSafe with QueryBuilder for SQL injection protection")]]
    std::vector<DockerContainerInfo> queryDockerContainers(const std::string& whereClause = "");

    // ========================================================================
    // Docker image operations
    // ========================================================================
    bool insertDockerImage(const DockerImageInfo& image);
    bool insertDockerImages(const std::vector<DockerImageInfo>& images);

    std::vector<DockerImageInfo> queryDockerImagesSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryDockerImagesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<DockerImageInfo> queryDockerImages(const std::string& whereClause = "");

    // ========================================================================
    // Docker volume operations
    // ========================================================================
    bool insertDockerVolume(const DockerVolumeInfo& volume);
    bool insertDockerVolumes(const std::vector<DockerVolumeInfo>& volumes);

    std::vector<DockerVolumeInfo> queryDockerVolumesSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryDockerVolumesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<DockerVolumeInfo> queryDockerVolumes(const std::string& whereClause = "");

    // ========================================================================
    // Podman container operations
    // ========================================================================
    bool insertPodmanContainer(const PodmanContainerInfo& container);
    bool insertPodmanContainers(const std::vector<PodmanContainerInfo>& containers);

    std::vector<PodmanContainerInfo> queryPodmanContainersSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryPodmanContainersSafe with QueryBuilder for SQL injection protection")]]
    std::vector<PodmanContainerInfo> queryPodmanContainers(const std::string& whereClause = "");

    // ========================================================================
    // Podman pod operations
    // ========================================================================
    bool insertPodmanPod(const PodmanPodInfo& pod);
    bool insertPodmanPods(const std::vector<PodmanPodInfo>& pods);

    std::vector<PodmanPodInfo> queryPodmanPodsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryPodmanPodsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<PodmanPodInfo> queryPodmanPods(const std::string& whereClause = "");

    // ========================================================================
    // Apache access log operations
    // ========================================================================
    bool insertApacheAccessLog(const ApacheAccessLogEntry& entry);
    bool insertApacheAccessLogs(const std::vector<ApacheAccessLogEntry>& entries);

    std::vector<ApacheAccessLogEntry> queryApacheAccessLogsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryApacheAccessLogsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<ApacheAccessLogEntry> queryApacheAccessLogs(const std::string& whereClause = "");

    // ========================================================================
    // Apache virtual host operations
    // ========================================================================
    bool insertApacheVHost(const ApacheVHostConfig& vhost);
    bool insertApacheVHosts(const std::vector<ApacheVHostConfig>& vhosts);

    std::vector<ApacheVHostConfig> queryApacheVHostsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryApacheVHostsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<ApacheVHostConfig> queryApacheVHosts(const std::string& whereClause = "");

    // ========================================================================
    // Nginx access log operations
    // ========================================================================
    bool insertNginxAccessLog(const NginxAccessLogEntry& entry);
    bool insertNginxAccessLogs(const std::vector<NginxAccessLogEntry>& entries);

    std::vector<NginxAccessLogEntry> queryNginxAccessLogsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryNginxAccessLogsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<NginxAccessLogEntry> queryNginxAccessLogs(const std::string& whereClause = "");

    // ========================================================================
    // Nginx server block operations
    // ========================================================================
    bool insertNginxServerBlock(const NginxServerBlock& block);
    bool insertNginxServerBlocks(const std::vector<NginxServerBlock>& blocks);

    std::vector<NginxServerBlock> queryNginxServerBlocksSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryNginxServerBlocksSafe with QueryBuilder for SQL injection protection")]]
    std::vector<NginxServerBlock> queryNginxServerBlocks(const std::string& whereClause = "");

    // ========================================================================
    // Setuid file operations
    // ========================================================================
    bool insertSetuidFile(const SetuidFileInfo& file);
    bool insertSetuidFiles(const std::vector<SetuidFileInfo>& files);

    std::vector<SetuidFileInfo> querySetuidFilesSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use querySetuidFilesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<SetuidFileInfo> querySetuidFiles(const std::string& whereClause = "");

    // ========================================================================
    // File capability operations
    // ========================================================================
    bool insertFileCapability(const FileCapability& capability);
    bool insertFileCapabilities(const std::vector<FileCapability>& capabilities);

    std::vector<FileCapability> queryFileCapabilitiesSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryFileCapabilitiesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<FileCapability> queryFileCapabilities(const std::string& whereClause = "");

    // ========================================================================
    // SELinux status operations
    // ========================================================================
    bool insertSELinuxStatus(const SELinuxStatus& status);

    std::vector<SELinuxStatus> querySELinuxStatusSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use querySELinuxStatusSafe with QueryBuilder for SQL injection protection")]]
    std::vector<SELinuxStatus> querySELinuxStatus(const std::string& whereClause = "");

    // ========================================================================
    // SELinux AVC denial operations
    // ========================================================================
    bool insertSELinuxAVCDenial(const SELinuxAVCDenial& denial);
    bool insertSELinuxAVCDenials(const std::vector<SELinuxAVCDenial>& denials);

    std::vector<SELinuxAVCDenial> querySELinuxAVCDenialsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use querySELinuxAVCDenialsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<SELinuxAVCDenial> querySELinuxAVCDenials(const std::string& whereClause = "");

    // ========================================================================
    // AppArmor profile operations
    // ========================================================================
    bool insertAppArmorProfile(const AppArmorProfile& profile);
    bool insertAppArmorProfiles(const std::vector<AppArmorProfile>& profiles);

    std::vector<AppArmorProfile> queryAppArmorProfilesSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryAppArmorProfilesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<AppArmorProfile> queryAppArmorProfiles(const std::string& whereClause = "");

    // ========================================================================
    // AppArmor violation operations
    // ========================================================================
    bool insertAppArmorViolation(const AppArmorViolation& violation);
    bool insertAppArmorViolations(const std::vector<AppArmorViolation>& violations);

    std::vector<AppArmorViolation> queryAppArmorViolationsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryAppArmorViolationsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<AppArmorViolation> queryAppArmorViolations(const std::string& whereClause = "");

    // ========================================================================
    // Correlated event operations
    // ========================================================================
    bool insertCorrelatedEvent(const CorrelatedEvent& event);
    bool insertCorrelatedEvents(const std::vector<CorrelatedEvent>& events);

    std::vector<CorrelatedEvent> queryCorrelatedEventsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryCorrelatedEventsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<CorrelatedEvent> queryCorrelatedEvents(const std::string& whereClause = "");

    // ========================================================================
    // Attack chain operations
    // ========================================================================
    bool insertAttackChain(const AttackChain& chain);
    bool insertAttackChains(const std::vector<AttackChain>& chains);

    std::vector<AttackChain> queryAttackChainsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryAttackChainsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<AttackChain> queryAttackChains(const std::string& whereClause = "");

    // ========================================================================
    // Timeline event operations
    // ========================================================================
    bool insertTimelineEvent(const LinuxTimelineEvent& event);
    bool insertTimelineEvents(const std::vector<LinuxTimelineEvent>& events);

    std::vector<LinuxTimelineEvent> queryTimelineEventsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryTimelineEventsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<LinuxTimelineEvent> queryTimelineEvents(const std::string& whereClause = "");

    // ========================================================================
    // Timeline gap operations
    // ========================================================================
    bool insertTimelineGap(const TimelineGap& gap);
    bool insertTimelineGaps(const std::vector<TimelineGap>& gaps);

    std::vector<TimelineGap> queryTimelineGapsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryTimelineGapsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<TimelineGap> queryTimelineGaps(const std::string& whereClause = "");

    // ========================================================================
    // Anomaly operations
    // ========================================================================
    bool insertAnomaly(const Anomaly& anomaly);
    bool insertAnomalies(const std::vector<Anomaly>& anomalies);

    std::vector<Anomaly> queryAnomaliesSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryAnomaliesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<Anomaly> queryAnomalies(const std::string& whereClause = "");

    // ========================================================================
    // Journal entry operations (Phase 2)
    // ========================================================================
    bool insertJournalEntry(const JournalEntry& entry);
    bool insertJournalEntries(const std::vector<JournalEntry>& entries);

    std::vector<JournalEntry> queryJournalEntriesSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryJournalEntriesSafe with QueryBuilder for SQL injection protection")]]
    std::vector<JournalEntry> queryJournalEntries(const std::string& whereClause = "");

    // ========================================================================
    // Boot session operations (Phase 2)
    // ========================================================================
    bool insertBootSession(const BootSession& session);
    bool insertBootSessions(const std::vector<BootSession>& sessions);

    std::vector<BootSession> queryBootSessionsSafe(const LinuxAnalysis::QueryBuilder& qb);

    [[deprecated("Use queryBootSessionsSafe with QueryBuilder for SQL injection protection")]]
    std::vector<BootSession> queryBootSessions(const std::string& whereClause = "");

    // ========================================================================
    // Journal anomaly operations (Phase 2)
    // ========================================================================
    bool insertJournalAnomaly(const JournalAnomaly& anomaly);
    bool insertJournalAnomalies(const std::vector<JournalAnomaly>& anomalies);

    std::vector<JournalAnomaly> queryJournalAnomaliesSafe(const LinuxAnalysis::QueryBuilder& qb);

    // ========================================================================
    // Persistence entry operations (Phase 6)
    // ========================================================================
    bool insertPersistenceEntry(const PersistenceEntry& entry);
    bool insertPersistenceEntries(const std::vector<PersistenceEntry>& entries);

    std::vector<PersistenceEntry> queryPersistenceEntriesSafe(const LinuxAnalysis::QueryBuilder& qb);

    // ========================================================================
    // Web error log operations (Phase 7)
    // ========================================================================
    bool insertWebErrorLog(const WebErrorLogEntry& entry);
    bool insertWebErrorLogs(const std::vector<WebErrorLogEntry>& entries);

    std::vector<WebErrorLogEntry> queryWebErrorLogsSafe(const LinuxAnalysis::QueryBuilder& qb);

    // ========================================================================
    // Middleware log operations (Phase 7)
    // ========================================================================
    bool insertMiddlewareLog(const MiddlewareLogEntry& entry);
    bool insertMiddlewareLogs(const std::vector<MiddlewareLogEntry>& entries);

    std::vector<MiddlewareLogEntry> queryMiddlewareLogsSafe(const LinuxAnalysis::QueryBuilder& qb);

    // ========================================================================
    // ModSecurity audit log operations (Phase 7)
    // ========================================================================
    bool insertModSecurityLog(const ModSecurityAuditEntry& entry);
    bool insertModSecurityLogs(const std::vector<ModSecurityAuditEntry>& entries);

    std::vector<ModSecurityAuditEntry> queryModSecurityLogsSafe(const LinuxAnalysis::QueryBuilder& qb);

    // ========================================================================
    // Container runtime log operations (Phase 8)
    // ========================================================================
    bool insertContainerLog(const DockerLogEntry& entry);
    bool insertContainerLogs(const std::vector<DockerLogEntry>& entries);
    bool insertCRILog(const CRILogEntry& entry);
    bool insertCRILogs(const std::vector<CRILogEntry>& entries);

    // ========================================================================
    // Container security finding operations (Phase 8)
    // ========================================================================
    bool insertContainerSecurityFinding(const ContainerSecurityFinding& finding);
    bool insertContainerSecurityFindings(const std::vector<ContainerSecurityFinding>& findings);

    // ========================================================================
    // Package manager log operations (Phase 9)
    // ========================================================================
    bool insertPackageLog(const PackageLogEntry& entry);
    bool insertPackageLogs(const std::vector<PackageLogEntry>& entries);

    // Suspicious package finding operations (Phase 9)
    bool insertSuspiciousPackageFinding(const SuspiciousPackageFinding& finding);
    bool insertSuspiciousPackageFindings(const std::vector<SuspiciousPackageFinding>& findings);
    std::vector<PackageLogEntry> queryPackageLogsSafe(const LinuxAnalysis::QueryBuilder& qb);

    // ========================================================================
    // Account security finding operations (Phase 10)
    // ========================================================================
    bool insertAccountSecurityFinding(const AccountSecurityFinding& finding);
    bool insertAccountSecurityFindings(const std::vector<AccountSecurityFinding>& findings);

    // SSH security finding operations (Phase 10)
    bool insertSSHSecurityFinding(const SSHSecurityFinding& finding);
    bool insertSSHSecurityFindings(const std::vector<SSHSecurityFinding>& findings);

    // ========================================================================
    // Database service log operations (Phase 11)
    // ========================================================================
    bool insertDatabaseLog(const DatabaseLogEntry& entry);
    bool insertDatabaseLogs(const std::vector<DatabaseLogEntry>& entries);

    // Database security finding operations
    bool insertDatabaseSecurityFinding(const DatabaseSecurityFinding& finding);
    bool insertDatabaseSecurityFindings(const std::vector<DatabaseSecurityFinding>& findings);

    // ========================================================================
    // Email service log operations (Phase 11)
    // ========================================================================
    bool insertEmailLog(const EmailLogEntry& entry);
    bool insertEmailLogs(const std::vector<EmailLogEntry>& entries);

    // Email security finding operations
    bool insertEmailSecurityFinding(const EmailSecurityFinding& finding);
    bool insertEmailSecurityFindings(const std::vector<EmailSecurityFinding>& findings);

    // ========================================================================
    // VPN service log operations (Phase 11)
    // ========================================================================
    bool insertVPNLog(const VPNLogEntry& entry);
    bool insertVPNLogs(const std::vector<VPNLogEntry>& entries);

    // VPN security finding operations
    bool insertVPNSecurityFinding(const VPNSecurityFinding& finding);
    bool insertVPNSecurityFindings(const std::vector<VPNSecurityFinding>& findings);

    // ========================================================================
    // Firewall log operations (Phase 11)
    // ========================================================================
    bool insertFirewallLogEntry(const FirewallLogEntry& entry);
    bool insertFirewallLogEntries(const std::vector<FirewallLogEntry>& entries);

    // ========================================================================
    // Security product log operations (Phase 11)
    // ========================================================================
    bool insertSecurityProductLog(const SecurityProductLogEntry& entry);
    bool insertSecurityProductLogs(const std::vector<SecurityProductLogEntry>& entries);

    // Security product finding operations
    bool insertSecurityProductFinding(const SecurityProductFinding& finding);
    bool insertSecurityProductFindings(const std::vector<SecurityProductFinding>& findings);

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
    bool integratedMode_;
    mutable std::mutex mutex_;  // For thread safety
    LinuxAnalysis::LinuxAnalyzerError lastError_;

    bool createTables();
    bool createArtifactsTable();
    bool executeSQL(const std::string& sql);
    
    // Set error state
    void setError(LinuxAnalysis::ErrorCode code, const std::string& details = "");
    void setError(const LinuxAnalysis::LinuxAnalyzerError& error);
    
    // Get SQLite error as LinuxAnalyzerError
    LinuxAnalysis::LinuxAnalyzerError getSQLiteError(LinuxAnalysis::ErrorCode code) const;
};

#endif // LINUX_ANALYSIS_DATABASE_H
