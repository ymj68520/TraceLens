// AccountSSHAnalyzer_SSH.cpp
// SSH security: sshd_config / authorized_keys / known_hosts / private-key analysis
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

