// AccountSSHAnalyzer_Accounts.cpp
// Account security: passwd / shadow / group / sudoers parsing & analysis
// Part of AccountSSHAnalyzer implementation; methods belong to
// forensics::linux::AccountSSHAnalyzer declared in AccountSSHAnalyzer.h.
// Split from AccountSSHAnalyzer.cpp for maintainability.

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

bool AccountSSHAnalyzer::isDangerousShell(const std::string& shell) {
    // Shells that allow interactive login
    static const std::vector<std::string> dangerousShells = {
        "/bin/bash", "/bin/sh", "/bin/zsh", "/bin/csh", "/bin/tcsh",
        "/bin/ksh", "/bin/fish", "/usr/bin/bash", "/usr/bin/sh",
        "/usr/bin/zsh", "/usr/bin/fish", "/usr/bin/ksh"
    };

    for (const auto& s : dangerousShells) {
        if (shell == s) return true;
    }
    return false;
}

AccountSSHAnalyzer::PasswdEntry AccountSSHAnalyzer::parsePasswdLine(const std::string& line) {
    PasswdEntry entry;
    std::istringstream stream(line);
    std::string token;
    int field = 0;

    while (std::getline(stream, token, ':')) {
        switch (field) {
            case 0: entry.username = token; break;
            case 1: entry.password = token; break;
            case 2: try { entry.uid = std::stoi(token); } catch (...) {} break;
            case 3: try { entry.gid = std::stoi(token); } catch (...) {} break;
            case 4: entry.gecos = token; break;
            case 5: entry.homeDir = token; break;
            case 6: entry.shell = token; break;
        }
        field++;
    }
    return entry;
}

std::vector<AccountSecurityFinding> AccountSSHAnalyzer::analyzePasswdFile(
    const std::string& content, const std::string& filePath) {
    std::vector<AccountSecurityFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        auto entry = parsePasswdLine(line);
        if (entry.username.empty()) continue;

        auto makeFinding = [&](const std::string& type, const std::string& severity,
                               const std::string& desc, const std::string& evidence) {
            AccountSecurityFinding f;
            f.findingType = type;
            f.severity = severity;
            f.username = entry.username;
            f.description = desc;
            f.evidence = evidence;
            f.filePath = filePath;
            f.provenance.parserName = "AccountSSHAnalyzer";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = filePath;
            findings.push_back(f);
        };

        // Check 1: UID 0 non-root users
        if (entry.uid == 0 && entry.username != "root") {
            makeFinding("uid0_anomaly", "critical",
                "Non-root user with UID 0 (root privileges)",
                "User '" + entry.username + "' has UID 0");
        }

        // Check 2: Login shells for system accounts
        if (entry.uid < 1000 && entry.uid != 0 && isDangerousShell(entry.shell)) {
            makeFinding("system_account_shell", "high",
                "System account with login shell",
                "UID " + std::to_string(entry.uid) + " has shell: " + entry.shell);
        }

        // Check 3: Home directory anomalies
        if (entry.homeDir.find("/home/") != 0 && entry.uid >= 1000 &&
            entry.homeDir != "/nonexistent" && entry.homeDir != "/dev/null") {
            makeFinding("home_dir_anomaly", "medium",
                "Regular user with non-standard home directory",
                "Home: " + entry.homeDir);
        }

        // Check 4: nologin/false shell for interactive users
        if (entry.uid >= 1000 && (entry.shell == "/sbin/nologin" || entry.shell == "/bin/false")) {
            makeFinding("disabled_account", "low",
                "User account has no login shell (may be disabled)",
                "Shell: " + entry.shell);
        }
    }

    return findings;
}

AccountSSHAnalyzer::ShadowEntry AccountSSHAnalyzer::parseShadowLine(const std::string& line) {
    ShadowEntry entry;
    std::istringstream stream(line);
    std::string token;
    int field = 0;

    while (std::getline(stream, token, ':')) {
        switch (field) {
            case 0: entry.username = token; break;
            case 1: entry.passwordHash = token; break;
            case 2: try { entry.lastChange = std::stoi(token); } catch (...) {} break;
            case 3: try { entry.minDays = std::stoi(token); } catch (...) {} break;
            case 4: try { entry.maxDays = std::stoi(token); } catch (...) {} break;
            case 5: try { entry.warnDays = std::stoi(token); } catch (...) {} break;
            case 6: try { entry.inactiveDays = std::stoi(token); } catch (...) {} break;
            case 7: try { entry.expireDate = std::stoi(token); } catch (...) {} break;
        }
        field++;
    }
    return entry;
}

std::vector<AccountSecurityFinding> AccountSSHAnalyzer::analyzeShadowFile(
    const std::string& content, const std::string& filePath) {
    std::vector<AccountSecurityFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        auto entry = parseShadowLine(line);
        if (entry.username.empty()) continue;

        auto makeFinding = [&](const std::string& type, const std::string& severity,
                               const std::string& desc, const std::string& evidence) {
            AccountSecurityFinding f;
            f.findingType = type;
            f.severity = severity;
            f.username = entry.username;
            f.description = desc;
            f.evidence = evidence;
            f.filePath = filePath;
            f.provenance.parserName = "AccountSSHAnalyzer";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = filePath;
            findings.push_back(f);
        };

        // Check 1: Empty password
        if (entry.passwordHash.empty() || entry.passwordHash == "!!" || entry.passwordHash == "!") {
            // Locked or no password - but empty hash means no password required
            if (entry.passwordHash.empty()) {
                makeFinding("empty_password", "critical",
                    "Account has empty password (no password required)",
                    "Password hash is empty");
            }
        }

        // Check 2: Password hash indicates disabled/locked
        if (entry.passwordHash == "*" || entry.passwordHash == "!*" || entry.passwordHash == "!!") {
            // These are normal for locked accounts
        }

        // Check 3: Weak hash algorithms
        if (entry.passwordHash.find("$1$") == 0) {
            makeFinding("weak_hash", "medium",
                "Password uses MD5 hashing (weak)",
                "Hash starts with $1$ (MD5)");
        } else if (entry.passwordHash.find("$2") == 0) {
            // bcrypt - OK
        } else if (entry.passwordHash.find("$5$") == 0) {
            // SHA-256 - OK
        } else if (entry.passwordHash.find("$6$") == 0) {
            // SHA-512 - OK
        } else if (!entry.passwordHash.empty() && entry.passwordHash[0] != '!' &&
                   entry.passwordHash[0] != '*' && entry.passwordHash != "!!") {
            // Unknown or old hash format
            makeFinding("weak_hash", "medium",
                "Password uses unknown or weak hash algorithm",
                "Hash prefix: " + entry.passwordHash.substr(0, 3));
        }

        // Check 4: Account expiration
        if (entry.expireDate > 0) {
            time_t now = time(nullptr);
            int currentDays = static_cast<int>(now / 86400);
            if (entry.expireDate < currentDays) {
                makeFinding("expired_account", "medium",
                    "Account has expired",
                    "Expired on day " + std::to_string(entry.expireDate));
            }
        }
    }

    return findings;
}

AccountSSHAnalyzer::GroupEntry AccountSSHAnalyzer::parseGroupLine(const std::string& line) {
    GroupEntry entry;
    std::istringstream stream(line);
    std::string token;
    int field = 0;

    while (std::getline(stream, token, ':')) {
        switch (field) {
            case 0: entry.groupName = token; break;
            case 1: entry.password = token; break;
            case 2: try { entry.gid = std::stoi(token); } catch (...) {} break;
            case 3: {
                std::istringstream memberStream(token);
                std::string member;
                while (std::getline(memberStream, member, ',')) {
                    if (!member.empty()) {
                        entry.members.push_back(member);
                    }
                }
                break;
            }
        }
        field++;
    }
    return entry;
}

std::vector<std::string> AccountSSHAnalyzer::getPrivilegedGroups() {
    return {"wheel", "sudo", "docker", "lxd", "lxc", "adm", "disk", "shadow",
            "video", "audio", "plugdev", "netdev", "kvm", "render"};
}

bool AccountSSHAnalyzer::isPrivilegedGroup(const std::string& groupName) {
    auto groups = getPrivilegedGroups();
    return std::find(groups.begin(), groups.end(), groupName) != groups.end();
}

std::vector<AccountSecurityFinding> AccountSSHAnalyzer::analyzeGroupFile(
    const std::string& content, const std::string& filePath) {
    std::vector<AccountSecurityFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        auto entry = parseGroupLine(line);
        if (entry.groupName.empty()) continue;

        // Check privileged group membership
        if (isPrivilegedGroup(entry.groupName) && !entry.members.empty()) {
            for (const auto& member : entry.members) {
                AccountSecurityFinding f;
                f.findingType = "privileged_group_member";
                f.severity = (entry.groupName == "docker" || entry.groupName == "lxd") ? "high" : "medium";
                f.username = member;
                f.description = "User is member of privileged group '" + entry.groupName + "'";
                f.evidence = "Group: " + entry.groupName + ", Member: " + member;
                f.filePath = filePath;
                f.provenance.parserName = "AccountSSHAnalyzer";
                f.provenance.parserVersion = "1.0.0";
                f.provenance.sourceFile = filePath;
                findings.push_back(f);
            }
        }
    }

    return findings;
}

bool AccountSSHAnalyzer::isDangerousSudoersCommand(const std::string& command) {
    // Commands that can lead to privilege escalation
    static const std::vector<std::string> dangerous = {
        "/bin/bash", "/bin/sh", "/bin/zsh", "/usr/bin/bash", "/usr/bin/sh",
        "/usr/bin/sudo", "/usr/bin/su",
        "/usr/bin/find", "/usr/bin/vim", "/usr/bin/vi", "/usr/bin/nano",
        "/usr/bin/less", "/usr/bin/more", "/usr/bin/man",
        "/usr/bin/python", "/usr/bin/python3", "/usr/bin/perl", "/usr/bin/ruby",
        "/usr/bin/env", "/usr/bin/awk", "/usr/bin/sed",
        "/usr/bin/chmod", "/usr/bin/chown",
        "/usr/bin/docker", "/usr/bin/lxc",
        "/usr/sbin/visudo", "/usr/bin/passwd",
        "/usr/bin/cp", "/usr/bin/mv", "/usr/bin/dd",
        "/usr/bin/nmap", "/usr/bin/nc", "/usr/bin/ncat", "/usr/bin/socat",
        "/usr/bin/curl", "/usr/bin/wget",
        "/usr/bin/ssh", "/usr/bin/scp", "/usr/bin/rsync",
        "/usr/bin/iptables", "/usr/bin/nft",
        "/usr/bin/systemctl", "/usr/bin/journalctl",
        "ALL", "NOPASSWD: ALL"
    };

    for (const auto& d : dangerous) {
        if (command.find(d) != std::string::npos) return true;
    }
    return false;
}

SudoersRule AccountSSHAnalyzer::parseSudoersLine(const std::string& line, int lineNum, const std::string& filePath) {
    SudoersRule rule;
    rule.lineNumber = lineNum;
    rule.filePath = filePath;

    // Skip comments and empty lines
    if (line.empty() || line[0] == '#') return rule;

    // Simple parsing: user host = (runas) command
    std::regex sudoersRegex("^([^\\s]+)\\s+([^\\s]+)\\s*=\\s*(?:\\(([^)]*)\\)\\s*)?(.+)$");
    std::smatch match;

    if (std::regex_match(line, match, sudoersRegex)) {
        rule.userOrGroup = match[1].str();
        rule.host = match[2].str();
        rule.command = match[4].str();

        // Check for NOPASSWD
        if (rule.command.find("NOPASSWD:") != std::string::npos) {
            rule.options = "NOPASSWD";
        }

        // Check for dangerous commands
        if (isDangerousSudoersCommand(rule.command)) {
            rule.is危险 = true;
            rule.riskReason = "Allows execution of potentially dangerous command";
        }

        // Check for ALL
        if (rule.command == "ALL" || rule.command.find("NOPASSWD: ALL") != std::string::npos) {
            rule.is危险 = true;
            rule.riskReason = std::string("Allows execution of any command") +
                              (rule.options == "NOPASSWD" ? " without password" : "");
        }
    }

    return rule;
}

std::vector<AccountSecurityFinding> AccountSSHAnalyzer::analyzeSudoersFile(
    const std::string& content, const std::string& filePath) {
    std::vector<AccountSecurityFinding> findings;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;

    while (std::getline(stream, line)) {
        lineNum++;
        if (line.empty() || line[0] == '#') continue;

        auto rule = parseSudoersLine(line, lineNum, filePath);
        if (rule.userOrGroup.empty()) continue;

        if (rule.is危险) {
            AccountSecurityFinding f;
            f.findingType = "sudoers_risk";
            f.severity = rule.options == "NOPASSWD" ? "critical" : "high";
            f.username = rule.userOrGroup;
            f.description = rule.riskReason;
            f.evidence = "Line " + std::to_string(rule.lineNumber) + ": " + line;
            f.filePath = filePath;
            f.provenance.parserName = "AccountSSHAnalyzer";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = filePath;
            findings.push_back(f);
        }
    }

    return findings;
}

