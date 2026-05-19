// AccountSSHAnalyzer.cpp
// Implementation of account, permission, and SSH security analyzer
// Phase 10: Account, Permission, and SSH Enhancement

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

// ============================================================================
// Helper Functions
// ============================================================================

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

// ============================================================================
// passwd File Analysis
// ============================================================================

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

// ============================================================================
// shadow File Analysis
// ============================================================================

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

// ============================================================================
// group File Analysis
// ============================================================================

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

// ============================================================================
// sudoers File Analysis
// ============================================================================

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

// ============================================================================
// SSH Config Analysis
// ============================================================================

SSHConfigDirective AccountSSHAnalyzer::parseSSHConfigLine(const std::string& line, int lineNum, const std::string& filePath) {
    SSHConfigDirective directive;
    directive.lineNumber = lineNum;
    directive.filePath = filePath;

    // Trim whitespace
    std::string trimmed = line;
    trimmed.erase(0, trimmed.find_first_not_of(" \t"));
    trimmed.erase(trimmed.find_last_not_of(" \t") + 1);

    if (trimmed.empty() || trimmed[0] == '#') return directive;

    // Parse directive value
    size_t spacePos = trimmed.find_first_of(" \t");
    if (spacePos != std::string::npos) {
        directive.directive = trimmed.substr(0, spacePos);
        std::string value = trimmed.substr(spacePos + 1);
        value.erase(0, value.find_first_not_of(" \t"));
        directive.value = value;
    }

    return directive;
}

bool AccountSSHAnalyzer::isWeakSSHConfig(const SSHConfigDirective& directive) {
    std::string lower = directive.directive;
    std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

    if (lower == "permitrootlogin" && directive.value == "yes") return true;
    if (lower == "passwordauthentication" && directive.value == "yes") return true;
    if (lower == "permitemptypasswords" && directive.value == "yes") return true;
    if (lower == "authorizedkeyscommand" && !directive.value.empty()) return true;
    if (lower == "forcecommand" && !directive.value.empty()) return true;
    if (lower == "proxycommand" && !directive.value.empty()) return true;
    if (lower == "x11forwarding" && directive.value == "yes") return true;
    if (lower == "allowtcpforwarding" && directive.value == "yes") return true;
    if (lower == "challengeResponseAuthentication" && directive.value == "yes") return true;
    if (lower == "hostbasedauthentication" && directive.value == "yes") return true;

    return false;
}

std::vector<SSHSecurityFinding> AccountSSHAnalyzer::analyzeSSHConfig(
    const std::string& content, const std::string& filePath) {
    std::vector<SSHSecurityFinding> findings;
    std::istringstream stream(content);
    std::string line;
    int lineNum = 0;
    std::string currentContext = "global";
    std::string currentContextValue;

    while (std::getline(stream, line)) {
        lineNum++;

        // Track Match/Host blocks
        std::string trimmed = line;
        trimmed.erase(0, trimmed.find_first_not_of(" \t"));
        if (trimmed.find("Match ") == 0) {
            currentContext = "Match";
            currentContextValue = trimmed.substr(6);
        } else if (trimmed.find("Host ") == 0) {
            currentContext = "Host";
            currentContextValue = trimmed.substr(5);
        }

        auto directive = parseSSHConfigLine(line, lineNum, filePath);
        if (directive.directive.empty()) continue;

        directive.context = currentContext;
        directive.contextValue = currentContextValue;

        if (isWeakSSHConfig(directive)) {
            SSHSecurityFinding f;
            f.findingType = "config_risk";

            std::string lower = directive.directive;
            std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);

            if (lower == "permitrootlogin") {
                f.severity = "critical";
                f.description = "Root login is permitted via SSH";
            } else if (lower == "passwordauthentication") {
                f.severity = "high";
                f.description = "Password authentication is enabled (prefer key-based)";
            } else if (lower == "permitemptypasswords") {
                f.severity = "critical";
                f.description = "Empty passwords are permitted";
            } else if (lower == "authorizedkeyscommand") {
                f.severity = "high";
                f.description = "AuthorizedKeysCommand configured (may be used for backdoor)";
            } else if (lower == "forcecommand") {
                f.severity = "high";
                f.description = "ForceCommand configured (restricts user commands)";
            } else if (lower == "proxycommand") {
                f.severity = "high";
                f.description = "ProxyCommand configured (may be used for tunneling)";
            } else if (lower == "x11forwarding") {
                f.severity = "low";
                f.description = "X11 forwarding is enabled";
            } else if (lower == "allowtcpforwarding") {
                f.severity = "medium";
                f.description = "TCP forwarding is enabled";
            } else if (lower == "challengeResponseAuthentication") {
                f.severity = "medium";
                f.description = "Challenge-response authentication is enabled";
            } else if (lower == "hostbasedauthentication") {
                f.severity = "high";
                f.description = "Host-based authentication is enabled";
            } else {
                f.severity = "medium";
                f.description = "Weak SSH configuration: " + directive.directive;
            }

            f.evidence = directive.directive + " " + directive.value;
            f.filePath = filePath;
            f.provenance.parserName = "AccountSSHAnalyzer";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = filePath;
            findings.push_back(f);
        }
    }

    return findings;
}

// ============================================================================
// Authorized Keys Analysis
// ============================================================================

std::vector<SSHSecurityFinding> AccountSSHAnalyzer::analyzeAuthorizedKeys(
    const std::string& content, const std::string& filePath, const std::string& username) {
    std::vector<SSHSecurityFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        // Parse authorized_keys line: [options] keytype base64-key [comment]
        std::istringstream lineStream(line);
        std::string token;
        std::vector<std::string> tokens;
        while (lineStream >> token) {
            tokens.push_back(token);
        }

        if (tokens.size() < 2) continue;

        std::string keyType;
        std::string options;

        // Check if first token is an option (contains = or starts with known options)
        if (tokens[0].find('=') != std::string::npos ||
            tokens[0].find("command=") == 0 ||
            tokens[0].find("from=") == 0 ||
            tokens[0].find("no-") == 0 ||
            tokens[0].find("permitopen=") == 0 ||
            tokens[0].find("principals=") == 0) {
            options = tokens[0];
            if (tokens.size() >= 3) keyType = tokens[1];
        } else {
            keyType = tokens[0];
        }

        // Check for command= option (forced command)
        if (options.find("command=") == 0) {
            SSHSecurityFinding f;
            f.findingType = "key_anomaly";
            f.severity = "high";
            f.description = "Authorized key has forced command (may be used for restricted access or backdoor)";
            f.evidence = "Options: " + options;
            f.filePath = filePath;
            f.username = username;
            f.provenance.parserName = "AccountSSHAnalyzer";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = filePath;
            findings.push_back(f);
        }

        // Check for from= restriction
        if (options.find("from=") == 0) {
            // This is actually a security feature, but worth noting
        }

        // Check for weak key types
        if (keyType == "ssh-dss" || keyType == "ssh-rsa") {
            SSHSecurityFinding f;
            f.findingType = "key_anomaly";
            f.severity = "medium";
            f.description = "Authorized key uses " + keyType + " (consider upgrading to ed25519 or ecdsa)";
            f.evidence = "Key type: " + keyType;
            f.filePath = filePath;
            f.username = username;
            f.keyType = keyType;
            f.provenance.parserName = "AccountSSHAnalyzer";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = filePath;
            findings.push_back(f);
        }
    }

    return findings;
}

// ============================================================================
// Known Hosts Analysis
// ============================================================================

KnownHostsEntry AccountSSHAnalyzer::parseKnownHostsLine(const std::string& line,
    const std::string& filePath, const std::string& username) {
    KnownHostsEntry entry;
    entry.filePath = filePath;
    entry.username = username;

    // Format: [marker] hostname keytype base64-key
    // or: @revoked hostname keytype base64-key
    // or: @cert-authority hostname keytype base64-key

    std::istringstream stream(line);
    std::string token;
    std::vector<std::string> tokens;
    while (stream >> token) {
        tokens.push_back(token);
    }

    if (tokens.size() < 3) return entry;

    int offset = 0;
    if (tokens[0][0] == '@') offset = 1;  // skip marker

    // hostname can be comma-separated
    std::string hosts = tokens[offset];
    size_t commaPos = hosts.find(',');
    if (commaPos != std::string::npos) {
        entry.hostname = hosts.substr(0, commaPos);
        entry.ip = hosts.substr(commaPos + 1);
    } else {
        entry.hostname = hosts;
    }

    entry.keyType = tokens[offset + 1];

    return entry;
}

bool AccountSSHAnalyzer::isLateralMovementIndicator(const KnownHostsEntry& entry) {
    // Check for private IP ranges that might indicate lateral movement
    static const std::vector<std::string> privateRanges = {
        "10.", "172.16.", "172.17.", "172.18.", "172.19.",
        "172.20.", "172.21.", "172.22.", "172.23.", "172.24.",
        "172.25.", "172.26.", "172.27.", "172.28.", "172.29.",
        "172.30.", "172.31.", "192.168."
    };

    // If hostname is an IP in private range, it might indicate lateral movement
    for (const auto& range : privateRanges) {
        if (entry.hostname.find(range) == 0 || entry.ip.find(range) == 0) {
            return true;
        }
    }

    return false;
}

std::vector<SSHSecurityFinding> AccountSSHAnalyzer::analyzeKnownHosts(
    const std::string& content, const std::string& filePath, const std::string& username) {
    std::vector<SSHSecurityFinding> findings;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty() || line[0] == '#') continue;

        auto entry = parseKnownHostsLine(line, filePath, username);
        if (entry.hostname.empty()) continue;

        // Check for lateral movement indicators
        if (isLateralMovementIndicator(entry)) {
            SSHSecurityFinding f;
            f.findingType = "lateral_movement";
            f.severity = "medium";
            f.description = "Known host is on private network (potential lateral movement target)";
            f.evidence = "Host: " + entry.hostname + ", IP: " + entry.ip;
            f.filePath = filePath;
            f.username = username;
            f.hostname = entry.hostname;
            f.provenance.parserName = "AccountSSHAnalyzer";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = filePath;
            findings.push_back(f);
        }

        // Check for weak key types in known_hosts
        if (entry.keyType == "ssh-dss") {
            SSHSecurityFinding f;
            f.findingType = "key_anomaly";
            f.severity = "low";
            f.description = "Known host uses weak key type (ssh-dss)";
            f.evidence = "Host: " + entry.hostname + ", Key type: " + entry.keyType;
            f.filePath = filePath;
            f.username = username;
            f.hostname = entry.hostname;
            f.keyType = entry.keyType;
            f.provenance.parserName = "AccountSSHAnalyzer";
            f.provenance.parserVersion = "1.0.0";
            f.provenance.sourceFile = filePath;
            findings.push_back(f);
        }
    }

    return findings;
}

// ============================================================================
// Private Key Permissions Analysis
// ============================================================================

std::vector<SSHSecurityFinding> AccountSSHAnalyzer::analyzePrivateKeyPermissions(
    const std::string& keyPath, int filePermissions, const std::string& username) {
    std::vector<SSHSecurityFinding> findings;

    // Private keys should be 0600 (owner read/write only)
    if (filePermissions & 0044) {  // group or other read
        SSHSecurityFinding f;
        f.findingType = "key_anomaly";
        f.severity = "critical";
        f.description = "SSH private key has too permissive file permissions";
        f.evidence = "Path: " + keyPath + ", Permissions: " + std::to_string(filePermissions) +
                     " (should be 0600)";
        f.filePath = keyPath;
        f.username = username;
        f.provenance.parserName = "AccountSSHAnalyzer";
        f.provenance.parserVersion = "1.0.0";
        f.provenance.sourceFile = keyPath;
        findings.push_back(f);
    }

    return findings;
}

// ============================================================================
// Combined Analysis
// ============================================================================

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
