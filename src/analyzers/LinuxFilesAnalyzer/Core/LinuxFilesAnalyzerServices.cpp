// LinuxFilesAnalyzerServices.cpp
// Service-log analysis methods of LinuxFilesAnalyzer
// (Package manager, database, email/VPN, firewall/security product logs)

#include "LinuxFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"

#include <fstream>
#include <iterator>
#include <sstream>

// Package manager log parser (Phase 9)
#include "Parsers/PackageManager/PackageManagerLogParser.h"

// Phase 11: Database, Email, VPN, Firewall, Security Product logs
#include "Parsers/Database/DatabaseLogParser.h"
#include "Parsers/EmailVPN/EmailVPNLogParser.h"
#include "Parsers/FirewallSecurity/FirewallSecurityLogParser.h"

// Database query helper
#include "Database/LinuxQueryBuilder.h"

using forensics::linux::PackageManagerLogParser;
using forensics::linux::DatabaseLogParser;
using forensics::linux::EmailVPNLogParser;
using forensics::linux::FirewallSecurityLogParser;

// ============================================================================
// Package Manager Log Analysis Implementation (Phase 9)
// ============================================================================

void LinuxFilesAnalyzer::analyzePackageManagerLogs() {
    std::cout << "Analyzing package manager logs..." << std::endl;

    if (!linuxDb_) {
        std::cerr << "  Error: Linux analysis database not initialized" << std::endl;
        return;
    }

    size_t totalPkgLogs = 0;
    size_t totalSuspicious = 0;

    // Helper to read file content
    auto readFile = [](const std::string& path) -> std::string {
        std::ifstream f(path);
        if (!f.is_open()) return "";
        return std::string((std::istreambuf_iterator<char>(f)),
                           std::istreambuf_iterator<char>());
    };

    // List of package manager log files to analyze
    std::vector<std::pair<std::string, std::string>> pkgLogPaths = {
        // APT logs
        {"/var/log/apt/history.log", "apt-history"},
        {"/var/log/apt/term.log", "apt-term"},
        {"/var/log/dpkg.log", "dpkg"},
        // YUM/DNF logs
        {"/var/log/yum.log", "yum"},
        {"/var/log/dnf.log", "dnf"},
        {"/var/log/dnf.rpm.log", "dnf"},
        // Zypper
        {"/var/log/zypper.log", "zypper"},
        // Pacman
        {"/var/log/pacman.log", "pacman"},
    };

    for (const auto& [logPath, expectedType] : pkgLogPaths) {
        std::string fullPath = extractDir_ + logPath;
        std::ifstream file(fullPath);
        if (!file.is_open()) continue;

        std::string content((std::istreambuf_iterator<char>(file)),
                            std::istreambuf_iterator<char>());
        file.close();

        if (content.empty()) continue;

        auto entries = PackageManagerLogParser::parsePackageManagerLog(content, logPath);
        if (!entries.empty()) {
            if (linuxDb_->insertPackageLogs(entries)) {
                totalPkgLogs += entries.size();
                std::cout << "  Parsed " << entries.size() << " entries from " << logPath << std::endl;
            }
        }
    }

    // Look for rotated logs
    std::string rotatedCmd = "ls " + extractDir_ + "/var/log/apt/history.log.* "
                             + extractDir_ + "/var/log/dpkg.log.* "
                             + extractDir_ + "/var/log/yum.log.* "
                             + extractDir_ + "/var/log/dnf.log.* "
                             + extractDir_ + "/var/log/pacman.log.* "
                             + "2>/dev/null";
    FILE* rotatedPipe = popen(rotatedCmd.c_str(), "r");
    if (rotatedPipe) {
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), rotatedPipe)) {
            std::string filePath(buffer);
            while (!filePath.empty() && (filePath.back() == '\n' || filePath.back() == '\r')) {
                filePath.pop_back();
            }
            if (filePath.empty()) continue;

            // Skip compressed files (handled separately)
            if (filePath.find(".gz") != std::string::npos ||
                filePath.find(".xz") != std::string::npos ||
                filePath.find(".bz2") != std::string::npos ||
                filePath.find(".zst") != std::string::npos) {
                continue;
            }

            std::string content = readFile(filePath);
            if (content.empty()) continue;

            // Convert absolute path to relative
            std::string relativePath = filePath;
            if (relativePath.find(extractDir_) == 0) {
                relativePath = relativePath.substr(extractDir_.length());
            }

            auto entries = PackageManagerLogParser::parsePackageManagerLog(content, relativePath);
            if (!entries.empty()) {
                if (linuxDb_->insertPackageLogs(entries)) {
                    totalPkgLogs += entries.size();
                    std::cout << "  Parsed " << entries.size() << " entries from " << relativePath << std::endl;
                }
            }
        }
        pclose(rotatedPipe);
    }

    // Now analyze all parsed entries for suspicious packages
    // Query all package logs from database
    LinuxAnalysis::QueryBuilder qb;
    auto allEntries = linuxDb_->queryPackageLogsSafe(qb);
    if (!allEntries.empty()) {
        auto suspiciousFindings = PackageManagerLogParser::analyzeSuspiciousPackages(allEntries);
        if (!suspiciousFindings.empty()) {
            if (linuxDb_->insertSuspiciousPackageFindings(suspiciousFindings)) {
                totalSuspicious = suspiciousFindings.size();
                std::cout << "  Found " << totalSuspicious << " suspicious package findings" << std::endl;

                for (const auto& finding : suspiciousFindings) {
                    if (finding.severity == "critical") {
                        std::cout << "    [CRITICAL] " << finding.findingType
                                  << ": " << finding.description << std::endl;
                    }
                }
            }
        }
    }

    std::cout << "  Package logs: " << totalPkgLogs
              << ", Suspicious findings: " << totalSuspicious << std::endl;

    AuditLog::instance().log("SYSTEM", "PACKAGE_LOG_COMPLETE",
        "Package manager log analysis: " + std::to_string(totalPkgLogs) + " entries, " +
        std::to_string(totalSuspicious) + " suspicious findings");
}

// ============================================================================
// Database Log Analysis Implementation (Phase 11)
// ============================================================================

void LinuxFilesAnalyzer::analyzeDatabaseLogs() {
    std::cout << "Analyzing database service logs..." << std::endl;

    if (!linuxDb_) {
        std::cerr << "  Error: Linux analysis database not initialized" << std::endl;
        return;
    }

    // Database log locations
    std::vector<std::string> logPatterns = {
        "var/log/mysql/%",
        "var/log/mariadb/%",
        "var/log/postgresql/%",
        "var/log/mongodb/%",
        "var/log/redis/%",
        "var/log/mysql.log%",
        "var/log/mysql/error.log%",
        "var/log/postgresql/postgresql%.log"
    };

    size_t totalEntries = 0;
    size_t totalFindings = 0;

    for (const auto& pattern : logPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string content;
            std::ifstream f(extractDir_ + "/" + file.path);
            if (f.is_open()) {
                content = std::string((std::istreambuf_iterator<char>(f)),
                                      std::istreambuf_iterator<char>());
            }
            if (content.empty()) continue;

            auto entries = DatabaseLogParser::parseAuto(content, file.path);
            if (!entries.empty()) {
                linuxDb_->insertDatabaseLogs(entries);
                totalEntries += entries.size();

                auto findings = DatabaseLogParser::analyzeSecurity(entries);
                if (!findings.empty()) {
                    linuxDb_->insertDatabaseSecurityFindings(findings);
                    totalFindings += findings.size();
                }
            }
        }
    }

    std::cout << "  Database logs: " << totalEntries
              << ", Security findings: " << totalFindings << std::endl;

    AuditLog::instance().log("SYSTEM", "DATABASE_LOG_COMPLETE",
        "Database log analysis: " + std::to_string(totalEntries) + " entries, " +
        std::to_string(totalFindings) + " security findings");
}

// ============================================================================
// Email and VPN Log Analysis Implementation (Phase 11)
// ============================================================================

void LinuxFilesAnalyzer::analyzeEmailVPNLogs() {
    std::cout << "Analyzing email and VPN logs..." << std::endl;

    if (!linuxDb_) {
        std::cerr << "  Error: Linux analysis database not initialized" << std::endl;
        return;
    }

    // Email log locations
    std::vector<std::string> emailPatterns = {
        "var/log/mail.log%",
        "var/log/maillog%",
        "var/log/exim4/%",
        "var/log/exim/%",
        "var/log/dovecot/%",
        "var/log/mail%"
    };

    // VPN log locations
    std::vector<std::string> vpnPatterns = {
        "var/log/openvpn/%",
        "var/log/openvpn.log%",
        "var/log/wireguard/%"
    };

    size_t totalEmailEntries = 0;
    size_t totalEmailFindings = 0;
    size_t totalVPNEntries = 0;
    size_t totalVPNFindings = 0;

    auto readFile = [this](const FileRecord& file) -> std::string {
        std::ifstream f(extractDir_ + "/" + file.path);
        if (!f.is_open()) return "";
        return std::string((std::istreambuf_iterator<char>(f)),
                           std::istreambuf_iterator<char>());
    };

    // Parse email logs
    for (const auto& pattern : emailPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string content = readFile(file);
            if (content.empty()) continue;

            auto entries = EmailVPNLogParser::parseEmailAuto(content, file.path);
            if (!entries.empty()) {
                linuxDb_->insertEmailLogs(entries);
                totalEmailEntries += entries.size();

                auto findings = EmailVPNLogParser::analyzeEmailSecurity(entries);
                if (!findings.empty()) {
                    linuxDb_->insertEmailSecurityFindings(findings);
                    totalEmailFindings += findings.size();
                }
            }
        }
    }

    // Parse VPN logs
    for (const auto& pattern : vpnPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string content = readFile(file);
            if (content.empty()) continue;

            auto entries = EmailVPNLogParser::parseVPNAuto(content, file.path);
            if (!entries.empty()) {
                linuxDb_->insertVPNLogs(entries);
                totalVPNEntries += entries.size();

                auto findings = EmailVPNLogParser::analyzeVPNSecurity(entries);
                if (!findings.empty()) {
                    linuxDb_->insertVPNSecurityFindings(findings);
                    totalVPNFindings += findings.size();
                }
            }
        }
    }

    std::cout << "  Email logs: " << totalEmailEntries
              << ", Email findings: " << totalEmailFindings << std::endl;
    std::cout << "  VPN logs: " << totalVPNEntries
              << ", VPN findings: " << totalVPNFindings << std::endl;

    AuditLog::instance().log("SYSTEM", "EMAIL_VPN_COMPLETE",
        "Email/VPN log analysis: " + std::to_string(totalEmailEntries) + " email entries, " +
        std::to_string(totalVPNEntries) + " VPN entries");
}

// ============================================================================
// Firewall and Security Product Log Analysis Implementation (Phase 11)
// ============================================================================

void LinuxFilesAnalyzer::analyzeFirewallSecurityLogs() {
    std::cout << "Analyzing firewall and security product logs..." << std::endl;

    if (!linuxDb_) {
        std::cerr << "  Error: Linux analysis database not initialized" << std::endl;
        return;
    }

    // Firewall log locations
    std::vector<std::string> firewallPatterns = {
        "var/log/ufw.log%",
        "var/log/ufw%",
        "var/log/firewalld%"
    };

    // Security product log locations
    std::vector<std::string> securityPatterns = {
        "var/log/fail2ban.log%",
        "var/log/fail2ban%",
        "var/log/clamav/%",
        "var/log/freshclam.log%",
        "var/log/rkhunter.log%",
        "var/log/ossec/%",
        "var/log/aide/%",
        "var/log/aide.log%"
    };

    size_t totalFirewallEntries = 0;
    size_t totalFirewallFindings = 0;
    size_t totalSecurityEntries = 0;
    size_t totalSecurityFindings = 0;

    auto readFile = [this](const FileRecord& file) -> std::string {
        std::ifstream f(extractDir_ + "/" + file.path);
        if (!f.is_open()) return "";
        return std::string((std::istreambuf_iterator<char>(f)),
                           std::istreambuf_iterator<char>());
    };

    // Parse firewall logs
    for (const auto& pattern : firewallPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string content = readFile(file);
            if (content.empty()) continue;

            auto entries = FirewallSecurityLogParser::parseFirewallAuto(content, file.path);
            if (!entries.empty()) {
                linuxDb_->insertFirewallLogEntries(entries);
                totalFirewallEntries += entries.size();

                auto findings = FirewallSecurityLogParser::analyzeFirewallSecurity(entries);
                if (!findings.empty()) {
                    linuxDb_->insertSecurityProductFindings(findings);
                    totalFirewallFindings += findings.size();
                }
            }
        }
    }

    // Parse security product logs
    for (const auto& pattern : securityPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string content = readFile(file);
            if (content.empty()) continue;

            auto entries = FirewallSecurityLogParser::parseSecurityAuto(content, file.path);
            if (!entries.empty()) {
                linuxDb_->insertSecurityProductLogs(entries);
                totalSecurityEntries += entries.size();

                auto findings = FirewallSecurityLogParser::analyzeSecurityProduct(entries);
                if (!findings.empty()) {
                    linuxDb_->insertSecurityProductFindings(findings);
                    totalSecurityFindings += findings.size();
                }
            }
        }
    }

    std::cout << "  Firewall logs: " << totalFirewallEntries
              << ", Firewall findings: " << totalFirewallFindings << std::endl;
    std::cout << "  Security product logs: " << totalSecurityEntries
              << ", Security findings: " << totalSecurityFindings << std::endl;

    AuditLog::instance().log("SYSTEM", "FIREWALL_SECURITY_COMPLETE",
        "Firewall/Security log analysis: " + std::to_string(totalFirewallEntries) +
        " firewall entries, " + std::to_string(totalSecurityEntries) + " security entries");
}
