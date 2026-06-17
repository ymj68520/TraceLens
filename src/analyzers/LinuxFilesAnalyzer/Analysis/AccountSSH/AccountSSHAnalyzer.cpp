// AccountSSHAnalyzer.cpp
// Implementation of account, permission, and SSH security analyzer
// Phase 10: Account, Permission, and SSH Enhancement
//
// This file holds the two aggregator entry points (analyzeAllAccounts,
// analyzeAllSSH). The per-area implementations live in sibling files:
//   - AccountSSHAnalyzer_Accounts.cpp  passwd/shadow/group/sudoers
//   - AccountSSHAnalyzer_SSH.cpp       sshd_config/keys/known_hosts

#ifdef linux
#undef linux
#endif

#include "AccountSSHAnalyzer.h"
#include <sstream>
#include <regex>
#include <algorithm>
#include <set>
#include <ctime>

using namespace forensics::linux;

std::vector<AccountSecurityFinding> AccountSSHAnalyzer::analyzeAllAccounts(
    const std::string& passwdContent,
    const std::string& shadowContent,
    const std::string& groupContent,
    const std::string& sudoersContent) {
    std::vector<AccountSecurityFinding> findings;

    auto passwdFindings = analyzePasswdFile(passwdContent);
    findings.insert(findings.end(), passwdFindings.begin(), passwdFindings.end());

    auto shadowFindings = analyzeShadowFile(shadowContent);
    findings.insert(findings.end(), shadowFindings.begin(), shadowFindings.end());

    auto groupFindings = analyzeGroupFile(groupContent);
    findings.insert(findings.end(), groupFindings.begin(), groupFindings.end());

    auto sudoersFindings = analyzeSudoersFile(sudoersContent);
    findings.insert(findings.end(), sudoersFindings.begin(), sudoersFindings.end());

    return findings;
}

std::vector<SSHSecurityFinding> AccountSSHAnalyzer::analyzeAllSSH(
    const std::string& sshdConfigContent,
    const std::string& sshConfigContent,
    const std::vector<std::pair<std::string, std::string>>& authorizedKeysFiles,
    const std::vector<std::pair<std::string, std::string>>& knownHostsFiles) {
    std::vector<SSHSecurityFinding> findings;

    auto sshdFindings = analyzeSSHConfig(sshdConfigContent, "/etc/ssh/sshd_config");
    findings.insert(findings.end(), sshdFindings.begin(), sshdFindings.end());

    auto sshFindings = analyzeSSHConfig(sshConfigContent, "/etc/ssh/ssh_config");
    findings.insert(findings.end(), sshFindings.begin(), sshFindings.end());

    for (const auto& [content, path] : authorizedKeysFiles) {
        // Extract username from path (~/.ssh/authorized_keys -> username from home dir)
        std::string username;
        size_t homePos = path.find("/home/");
        if (homePos != std::string::npos) {
            size_t userStart = homePos + 6;
            size_t userEnd = path.find('/', userStart);
            if (userEnd != std::string::npos) {
                username = path.substr(userStart, userEnd - userStart);
            }
        } else if (path.find("/root/") != std::string::npos) {
            username = "root";
        }

        auto keyFindings = analyzeAuthorizedKeys(content, path, username);
        findings.insert(findings.end(), keyFindings.begin(), keyFindings.end());
    }

    for (const auto& [content, path] : knownHostsFiles) {
        std::string username;
        size_t homePos = path.find("/home/");
        if (homePos != std::string::npos) {
            size_t userStart = homePos + 6;
            size_t userEnd = path.find('/', userStart);
            if (userEnd != std::string::npos) {
                username = path.substr(userStart, userEnd - userStart);
            }
        } else if (path.find("/root/") != std::string::npos) {
            username = "root";
        }

        auto hostFindings = analyzeKnownHosts(content, path, username);
        findings.insert(findings.end(), hostFindings.begin(), hostFindings.end());
    }

    return findings;
}

