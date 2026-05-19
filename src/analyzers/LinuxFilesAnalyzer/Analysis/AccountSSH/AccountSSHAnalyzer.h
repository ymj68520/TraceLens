// AccountSSHAnalyzer.h
// Analyzer for account, permission, and SSH security anomalies
// Phase 10: Account, Permission, and SSH Enhancement

#pragma once
#ifndef ACCOUNT_SSH_ANALYZER_H
#define ACCOUNT_SSH_ANALYZER_H

#include <string>
#include <vector>
#include "Common/LinuxDataTypes.h"

#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Account security finding
struct AccountSecurityFinding {
    std::string findingType;        // uid0_anomaly, empty_password, sudoers_risk, group_anomaly, etc.
    std::string severity;           // critical, high, medium, low
    std::string username;
    std::string description;
    std::string evidence;
    std::string filePath;
    EvidenceProvenance provenance;
};

// SSH security finding
struct SSHSecurityFinding {
    std::string findingType;        // config_risk, key_anomaly, lateral_movement, auth_weakness
    std::string severity;           // critical, high, medium, low
    std::string description;
    std::string evidence;
    std::string filePath;
    std::string username;
    std::string hostname;
    std::string keyType;
    EvidenceProvenance provenance;
};

// SSH config directive
struct SSHConfigDirective {
    std::string directive;          // PermitRootLogin, PasswordAuthentication, etc.
    std::string value;
    std::string context;            // global, Match, Host
    std::string contextValue;       // Match user/host value
    int lineNumber = 0;
    std::string filePath;
};

// Sudoers rule
struct SudoersRule {
    std::string userOrGroup;
    std::string host;
    std::string command;
    std::string options;            // NOPASSWD, etc.
    bool is危险 = false;
    std::string riskReason;
    int lineNumber = 0;
    std::string filePath;
};

// known_hosts entry
struct KnownHostsEntry {
    std::string hostname;
    std::string ip;
    std::string keyType;
    std::string fingerprint;
    std::string filePath;
    std::string username;           // owner of the known_hosts file
};

class AccountSSHAnalyzer {
public:
    // Account security analysis
    static std::vector<AccountSecurityFinding> analyzePasswdFile(
        const std::string& content, const std::string& filePath = "");
    static std::vector<AccountSecurityFinding> analyzeShadowFile(
        const std::string& content, const std::string& filePath = "");
    static std::vector<AccountSecurityFinding> analyzeGroupFile(
        const std::string& content, const std::string& filePath = "");
    static std::vector<AccountSecurityFinding> analyzeSudoersFile(
        const std::string& content, const std::string& filePath = "");

    // SSH security analysis
    static std::vector<SSHSecurityFinding> analyzeSSHConfig(
        const std::string& content, const std::string& filePath = "");
    static std::vector<SSHSecurityFinding> analyzeAuthorizedKeys(
        const std::string& content, const std::string& filePath = "",
        const std::string& username = "");
    static std::vector<SSHSecurityFinding> analyzeKnownHosts(
        const std::string& content, const std::string& filePath = "",
        const std::string& username = "");
    static std::vector<SSHSecurityFinding> analyzePrivateKeyPermissions(
        const std::string& keyPath, int filePermissions,
        const std::string& username = "");

    // Combined analysis
    static std::vector<AccountSecurityFinding> analyzeAllAccounts(
        const std::string& passwdContent,
        const std::string& shadowContent,
        const std::string& groupContent,
        const std::string& sudoersContent);

    static std::vector<SSHSecurityFinding> analyzeAllSSH(
        const std::string& sshdConfigContent,
        const std::string& sshConfigContent,
        const std::vector<std::pair<std::string, std::string>>& authorizedKeysFiles,
        const std::vector<std::pair<std::string, std::string>>& knownHostsFiles);

private:
    // passwd parsing helpers
    struct PasswdEntry {
        std::string username;
        std::string password;       // usually 'x'
        int uid = 0;
        int gid = 0;
        std::string gecos;
        std::string homeDir;
        std::string shell;
    };

    // shadow parsing helpers
    struct ShadowEntry {
        std::string username;
        std::string passwordHash;
        int lastChange = 0;         // days since epoch
        int minDays = 0;
        int maxDays = 0;
        int warnDays = 0;
        int inactiveDays = 0;
        int expireDate = 0;         // days since epoch
        std::string reserved;
    };

    // group parsing helpers
    struct GroupEntry {
        std::string groupName;
        std::string password;
        int gid = 0;
        std::vector<std::string> members;
    };

    static PasswdEntry parsePasswdLine(const std::string& line);
    static ShadowEntry parseShadowLine(const std::string& line);
    static GroupEntry parseGroupLine(const std::string& line);
    static SudoersRule parseSudoersLine(const std::string& line, int lineNum, const std::string& filePath);
    static SSHConfigDirective parseSSHConfigLine(const std::string& line, int lineNum, const std::string& filePath);
    static KnownHostsEntry parseKnownHostsLine(const std::string& line, const std::string& filePath, const std::string& username);

    // Security checks
    static bool isDangerousShell(const std::string& shell);
    static bool isPrivilegedGroup(const std::string& groupName);
    static bool isDangerousSudoersCommand(const std::string& command);
    static bool isWeakSSHConfig(const SSHConfigDirective& directive);
    static bool isLateralMovementIndicator(const KnownHostsEntry& entry);

    // Sensitive groups
    static std::vector<std::string> getPrivilegedGroups();
};

} // namespace linux
} // namespace forensics

#endif // ACCOUNT_SSH_ANALYZER_H
