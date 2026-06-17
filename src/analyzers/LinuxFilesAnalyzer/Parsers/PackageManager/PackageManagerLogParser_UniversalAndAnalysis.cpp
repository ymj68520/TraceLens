// PackageManagerLogParser_UniversalAndAnalysis.cpp
// Universal package managers (Snap, Flatpak) + suspicious-pattern matching
// Part of PackageManagerLogParser implementation; methods belong to
// forensics::linux::PackageManagerLogParser declared in PackageManagerLogParser.h.
// Split from PackageManagerLogParser.cpp for maintainability.

#ifdef linux
#undef linux
#endif

#include "PackageManagerLogParser.h"
#include <sstream>
#include <regex>
#include <algorithm>
#include <ctime>

using namespace forensics::linux;

std::vector<PackageLogEntry> PackageManagerLogParser::parseSnapLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        // snap changes output: ID  Status  Spawn  Ready  Summary
        // or snap log format with timestamps
        std::regex snapRegex("(\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}[+-]\\d{2}:?\\d{2})\\s+.*?\\s+(install|remove|refresh|revert)\\s+\"?(\\S+?)\"?\\s");
        std::smatch match;

        if (std::regex_search(line, match, snapRegex)) {
            PackageLogEntry entry;
            struct tm tm = {};
            std::string tsStr = match[1].str();
            if (strptime(tsStr.c_str(), "%Y-%m-%dT%H:%M:%S", &tm)) {
                entry.timestamp = static_cast<int64_t>(timegm(&tm));
            }
            entry.packageManager = "snap";
            std::string op = match[2].str();
            if (op == "install") entry.operation = PackageOperation::INSTALL;
            else if (op == "remove") entry.operation = PackageOperation::REMOVE;
            else if (op == "refresh") entry.operation = PackageOperation::UPGRADE;
            else if (op == "revert") entry.operation = PackageOperation::DOWNGRADE;
            else entry.operation = PackageOperation::UNKNOWN;
            entry.operationDetail = op;
            entry.packageName = match[3].str();
            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;
            entries.push_back(entry);
        }
    }

    return entries;
}

std::vector<PackageLogEntry> PackageManagerLogParser::parseFlatpakLog(
    const std::string& content, const std::string& filePath) {
    std::vector<PackageLogEntry> entries;
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        if (line.empty()) continue;

        // flatpak log: similar to "Installing app/org.app/x86_64/stable from remote"
        std::regex flatpakRegex("(Installing|Uninstalling|Updating)\\s+(\\S+)");
        std::smatch match;

        if (std::regex_search(line, match, flatpakRegex)) {
            PackageLogEntry entry;
            entry.packageManager = "flatpak";
            std::string op = match[1].str();
            if (op == "Installing") entry.operation = PackageOperation::INSTALL;
            else if (op == "Uninstalling") entry.operation = PackageOperation::REMOVE;
            else if (op == "Updating") entry.operation = PackageOperation::UPGRADE;
            else entry.operation = PackageOperation::UNKNOWN;
            entry.operationDetail = op;
            entry.packageName = match[2].str();
            entry.filePath = filePath;
            entry.provenance.parserName = "PackageManagerLogParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.rawRecord = line;
            entries.push_back(entry);
        }
    }

    return entries;
}

std::vector<PackagePattern> PackageManagerLogParser::getAttackToolPatterns() {
    return {
        {"nmap", "network_scanner", "high", "Network port scanner used for reconnaissance"},
        {"masscan", "network_scanner", "high", "Fast network port scanner"},
        {"hydra", "password_cracker", "critical", "Password brute-force tool"},
        {"john", "password_cracker", "critical", "John the Ripper password cracker"},
        {"hashcat", "password_cracker", "critical", "GPU-based password cracker"},
        {"aircrack-ng", "wireless_attack", "critical", "WiFi network cracking tool"},
        {"metasploit", "exploit_framework", "critical", "Metasploit penetration testing framework"},
        {"msfconsole", "exploit_framework", "critical", "Metasploit console"},
        {"sqlmap", "web_attack", "critical", "SQL injection automation tool"},
        {"burpsuite", "web_attack", "high", "Web application security testing"},
        {"nikto", "web_scanner", "high", "Web server vulnerability scanner"},
        {"dirb", "web_scanner", "medium", "Web content directory scanner"},
        {"gobuster", "web_scanner", "medium", "Directory/file brute-forcer"},
        {"wfuzz", "web_fuzzer", "medium", "Web application fuzzer"},
        {"responder", "network_attack", "critical", "LLMNR/NBT-NS/MDNS poisoner"},
        {"impacket", "network_attack", "high", "Network protocol tools collection"},
        {"mimikatz", "credential_theft", "critical", "Windows credential extraction"},
        {"bloodhound", "ad_attack", "high", "Active Directory attack path analysis"},
        {"empire", "c2_framework", "critical", "PowerShell/Python post-exploitation framework"},
        {"cobalt-strike", "c2_framework", "critical", "Commercial penetration testing tool"},
        {"linpeas", "privilege_escalation", "high", "Linux privilege escalation enumeration"},
        {"winpeas", "privilege_escalation", "high", "Windows privilege escalation enumeration"},
        {"pspy", "process_monitor", "medium", "Process monitor for privilege escalation"},
        {"chisel", "tunneling", "high", "TCP/UDP tunnel over HTTP"},
        {"socat", "tunneling", "medium", "Multipurpose relay tool"},
        {"netcat", "network_tool", "medium", "Network utility (nc/ncat)"},
        {"ncat", "network_tool", "medium", "Nmap's netcat implementation"},
        {"socat", "network_tool", "medium", "Socket relay tool"},
        {"proxychains", "proxy", "high", "Force TCP connections through proxy"},
        {"tor", "anonymization", "medium", "Anonymity network client"},
        {"wireshark", "packet_capture", "medium", "Network protocol analyzer"},
        {"tcpdump", "packet_capture", "medium", "Command-line packet analyzer"},
        {"ettercap", "mitm", "high", "MITM attack framework"},
        {"bettercap", "mitm", "high", "Network attack and monitoring framework"},
        {"beef", "web_attack", "high", "Browser exploitation framework"},
        {"set", "social_engineering", "high", "Social Engineering Toolkit"},
        {"veil", "evasion", "high", "Payload generator for AV evasion"},
        {"shellter", "evasion", "high", "Dynamic shellcode injection"},
        {"reverse-shell", "backdoor", "critical", "Reverse shell handler"},
        {"weevely", "web_backdoor", "critical", "Web shell generator"},
        {"webshell", "web_backdoor", "critical", "Web shell for remote access"},
    };
}

std::vector<PackagePattern> PackageManagerLogParser::getSecurityToolPatterns() {
    return {
        {"selinux", "security_framework", "high", "SELinux security framework"},
        {"apparmor", "security_framework", "high", "AppArmor security framework"},
        {"fail2ban", "intrusion_prevention", "high", "Intrusion prevention tool"},
        {"aide", "file_integrity", "high", "Advanced Intrusion Detection Environment"},
        {"tripwire", "file_integrity", "high", "File integrity monitoring"},
        {"ossec", "ids", "high", "Host-based intrusion detection"},
        {"snort", "ids", "high", "Network intrusion detection"},
        {"suricata", "ids", "high", "Network threat detection engine"},
        {"clamav", "antivirus", "high", "Open-source antivirus engine"},
        {"rkhunter", "rootkit_detection", "high", "Rootkit scanner"},
        {"chkrootkit", "rootkit_detection", "high", "Rootkit detector"},
        {"lynis", "security_audit", "medium", "Security auditing tool"},
        {"ufw", "firewall", "high", "Uncomplicated Firewall"},
        {"iptables", "firewall", "high", "Linux firewall administration"},
        {"nftables", "firewall", "high", "Netfilter tables"},
        {"auditd", "audit", "high", "Linux audit daemon"},
    };
}

std::vector<SuspiciousPackageFinding> PackageManagerLogParser::analyzeSuspiciousPackages(
    const std::vector<PackageLogEntry>& entries) {
    std::vector<SuspiciousPackageFinding> findings;

    auto attackPatterns = getAttackToolPatterns();
    auto securityPatterns = getSecurityToolPatterns();

    for (const auto& entry : entries) {
        // Check for attack tools
        for (const auto& pattern : attackPatterns) {
            if (entry.packageName.find(pattern.packageName) != std::string::npos) {
                SuspiciousPackageFinding finding;
                finding.findingType = pattern.category;
                finding.severity = pattern.severity;
                finding.packageName = entry.packageName;
                finding.packageVersion = entry.packageVersion;
                finding.description = pattern.description;
                finding.evidence = "Package operation: " + operationToString(entry.operation) +
                                   " " + entry.packageName;
                finding.filePath = entry.filePath;
                finding.provenance = entry.provenance;
                findings.push_back(finding);
                break; // Only one match per entry
            }
        }

        // Check for security tool removals
        if (entry.operation == PackageOperation::REMOVE ||
            entry.operation == PackageOperation::PURGE) {
            for (const auto& pattern : securityPatterns) {
                if (entry.packageName.find(pattern.packageName) != std::string::npos) {
                    SuspiciousPackageFinding finding;
                    finding.findingType = "security_removal";
                    finding.severity = "critical";
                    finding.packageName = entry.packageName;
                    finding.packageVersion = entry.packageVersion;
                    finding.description = "Security tool removed: " + pattern.description;
                    finding.evidence = "Removed: " + entry.packageName;
                    finding.filePath = entry.filePath;
                    finding.provenance = entry.provenance;
                    findings.push_back(finding);
                    break;
                }
            }
        }
    }

    return findings;
}

