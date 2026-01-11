// LinuxArtifactsParsers.cpp
// Implementation of various Linux artifact parsers

#include "LinuxFilesAnalyzer.h"
#include "LinuxLogParser.h"
#include "LinuxUserParser.h"
#include "LinuxHistoryParser.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>
#include <filesystem>
#include <regex>

namespace fs = std::filesystem;

// ============================================================================
// System Log Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeSystemLogs() {
    std::cout << "Analyzing system logs (syslog, messages)..." << std::endl;

    // Find syslog files
    auto syslogFiles = queryFilesByPattern("%/var/log/syslog%");
    auto messagesFiles = queryFilesByPattern("%/var/log/messages%");

    for (const auto& file : syslogFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "syslog");
            linuxDb_->insertLogEntries(entries);
            AuditLog::instance().log("SYSTEM", "LINUX_SYSLOG_PARSED", 
                                      "Parsed " + std::to_string(entries.size()) + " syslog entries");
        }
    }

    for (const auto& file : messagesFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "messages");
            linuxDb_->insertLogEntries(entries);
        }
    }
}

void LinuxFilesAnalyzer::analyzeAuthLogs() {
    std::cout << "Analyzing authentication logs (auth.log, secure)..." << std::endl;

    auto authFiles = queryFilesByPattern("%/var/log/auth.log%");
    auto secureFiles = queryFilesByPattern("%/var/log/secure%");

    for (const auto& file : authFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "auth");
            linuxDb_->insertLogEntries(entries);
            AuditLog::instance().log("SYSTEM", "LINUX_AUTH_PARSED", 
                                      "Parsed " + std::to_string(entries.size()) + " auth.log entries");
        }
    }

    for (const auto& file : secureFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "secure");
            linuxDb_->insertLogEntries(entries);
        }
    }
}

void LinuxFilesAnalyzer::analyzeKernelLogs() {
    std::cout << "Analyzing kernel logs..." << std::endl;

    auto kernFiles = queryFilesByPattern("%/var/log/kern.log%");
    auto dmesgFiles = queryFilesByPattern("%/var/log/dmesg%");

    for (const auto& file : kernFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "kern");
            linuxDb_->insertLogEntries(entries);
        }
    }

    for (const auto& file : dmesgFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "dmesg");
            linuxDb_->insertLogEntries(entries);
        }
    }
}

void LinuxFilesAnalyzer::analyzeApplicationLogs() {
    std::cout << "Analyzing application logs..." << std::endl;

    // dpkg logs for package installations
    auto dpkgFiles = queryFilesByPattern("%/var/log/dpkg.log%");
    for (const auto& file : dpkgFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "dpkg");
            linuxDb_->insertLogEntries(entries);
        }
    }

    // apt history
    auto aptFiles = queryFilesByPattern("%/var/log/apt/history.log%");
    for (const auto& file : aptFiles) {
        std::string extractPath = getExtractPath("var/log/apt/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto entries = parseLogFile(extractPath, "apt");
            linuxDb_->insertLogEntries(entries);
        }
    }
}

std::vector<LinuxLogEntry> LinuxFilesAnalyzer::parseLogFile(const std::string& logPath,
                                                             const std::string& logType) {
    std::vector<LinuxLogEntry> entries;

    std::ifstream file(logPath);
    if (!file.is_open()) {
        return entries;
    }

    std::string line;
    while (std::getline(file, line)) {
        if (line.empty()) continue;

        LinuxLogEntry entry;
        if (logType == "kern" || logType == "dmesg") {
            entry = LinuxLogParser::parseKernelLogLine(line, logPath);
        } else if (logType == "dpkg") {
            entry = LinuxLogParser::parseDpkgLogLine(line, logPath);
        } else if (logType == "apt") {
            entry = LinuxLogParser::parseAptHistoryLine(line, logPath);
        } else {
            entry = LinuxLogParser::parseSyslogLine(line, logPath);
        }

        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// User and Authentication Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeUserAccounts() {
    std::cout << "Analyzing user accounts..." << std::endl;

    // Find and parse /etc/passwd
    auto passwdFiles = queryFilesByPattern("%/etc/passwd");
    std::vector<LinuxUserInfo> users;

    for (const auto& file : passwdFiles) {
        std::string extractPath = getExtractPath("etc/passwd");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::stringstream buffer;
                buffer << f.rdbuf();
                users = LinuxUserParser::parsePasswdFile(buffer.str());
            }
        }
        break; // Only one passwd file
    }

    // Find and parse /etc/shadow (if accessible)
    auto shadowFiles = queryFilesByPattern("%/etc/shadow");
    for (const auto& file : shadowFiles) {
        std::string extractPath = getExtractPath("etc/shadow");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::stringstream buffer;
                buffer << f.rdbuf();
                LinuxUserParser::parseShadowFile(buffer.str(), users);
            }
        }
        break;
    }

    // Save users to database
    linuxDb_->insertUserInfos(users);
    AuditLog::instance().log("SYSTEM", "LINUX_USERS_PARSED", 
                              "Parsed " + std::to_string(users.size()) + " user accounts");

    // Find and parse /etc/group
    auto groupFiles = queryFilesByPattern("%/etc/group");
    for (const auto& file : groupFiles) {
        std::string extractPath = getExtractPath("etc/group");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::stringstream buffer;
                buffer << f.rdbuf();
                auto groups = LinuxUserParser::parseGroupFile(buffer.str());
                for (const auto& group : groups) {
                    linuxDb_->insertGroupInfo(group);
                }
            }
        }
        break;
    }
}

void LinuxFilesAnalyzer::analyzeLoginHistory() {
    std::cout << "Analyzing login history (wtmp, btmp)..." << std::endl;

    // Parse wtmp (successful logins)
    auto wtmpFiles = queryFilesByPattern("%/var/log/wtmp%");
    for (const auto& file : wtmpFiles) {
        std::string extractPath = getExtractPath("var/log/wtmp");
        if (extractFileToPath(file.inode, extractPath)) {
            auto records = LinuxUserParser::parseWtmpFile(extractPath);
            linuxDb_->insertLoginRecords(records);
            AuditLog::instance().log("SYSTEM", "LINUX_WTMP_PARSED", 
                                      "Parsed " + std::to_string(records.size()) + " login records from wtmp");
        }
    }

    // Parse btmp (failed logins)
    auto btmpFiles = queryFilesByPattern("%/var/log/btmp%");
    for (const auto& file : btmpFiles) {
        std::string extractPath = getExtractPath("var/log/btmp");
        if (extractFileToPath(file.inode, extractPath)) {
            auto records = LinuxUserParser::parseBtmpFile(extractPath);
            linuxDb_->insertLoginRecords(records);
            AuditLog::instance().log("SYSTEM", "LINUX_BTMP_PARSED", 
                                      "Parsed " + std::to_string(records.size()) + " failed login records from btmp");
        }
    }
}

void LinuxFilesAnalyzer::analyzeSSHArtifacts() {
    std::cout << "Analyzing SSH artifacts..." << std::endl;

    // Find authorized_keys files
    auto authKeysFiles = queryFilesByPattern("%/.ssh/authorized_keys");
    for (const auto& file : authKeysFiles) {
        std::string extractPath = getExtractPath("ssh/" + std::to_string(file.inode) + "_authorized_keys");
        if (extractFileToPath(file.inode, extractPath)) {
            // Extract username from path
            std::string username = "unknown";
            size_t homePos = file.path.find("/home/");
            size_t rootPos = file.path.find("/root/");
            
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    username = file.path.substr(start, end - start);
                }
            } else if (rootPos != std::string::npos) {
                username = "root";
            }

            auto keys = parseAuthorizedKeys(extractPath, username);
            linuxDb_->insertSSHKeys(keys);
        }
    }

    // Find known_hosts files
    auto knownHostsFiles = queryFilesByPattern("%/.ssh/known_hosts");
    for (const auto& file : knownHostsFiles) {
        std::string extractPath = getExtractPath("ssh/" + std::to_string(file.inode) + "_known_hosts");
        if (extractFileToPath(file.inode, extractPath)) {
            // Extract username from path
            std::string username = "unknown";
            size_t homePos = file.path.find("/home/");
            size_t rootPos = file.path.find("/root/");
            
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    username = file.path.substr(start, end - start);
                }
            } else if (rootPos != std::string::npos) {
                username = "root";
            }

            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::string line;
                while (std::getline(f, line)) {
                    if (line.empty() || line[0] == '#') continue;

                    SSHKnownHost host;
                    host.username = username;

                    std::istringstream ss(line);
                    std::string hostname, keyType, publicKey;

                    ss >> hostname >> keyType >> publicKey;

                    // Check for hashed hostname format: |1|salt|hash
                    if (hostname.find("|1|") == 0) {
                        host.isHashed = true;
                        host.hostname = hostname; // Keep the hash
                    } else {
                        host.isHashed = false;
                        // Hostname can be comma-separated list
                        host.hostname = hostname;
                    }

                    host.keyType = keyType;
                    host.publicKey = publicKey;

                    linuxDb_->insertSSHKnownHost(host);
                }

                AuditLog::instance().log("SYSTEM", "LINUX_SSH_KNOWN_HOSTS_PARSED",
                                          "Parsed known_hosts for user " + username);
            }
        }
    }
}

std::vector<SSHKeyInfo> LinuxFilesAnalyzer::parseAuthorizedKeys(const std::string& keysPath,
                                                                  const std::string& username) {
    std::vector<SSHKeyInfo> keys;

    std::ifstream file(keysPath);
    if (!file.is_open()) {
        return keys;
    }

    std::string line;
    while (std::getline(file, line)) {
        if (line.empty() || line[0] == '#') {
            continue;
        }

        SSHKeyInfo key;
        key.username = username;
        key.keyPath = keysPath;

        // Format: [options] key-type base64-key [comment]
        // Common key types: ssh-rsa, ssh-ed25519, ecdsa-sha2-nistp256

        std::istringstream ss(line);
        std::string token;
        std::vector<std::string> tokens;

        while (ss >> token) {
            tokens.push_back(token);
        }

        if (tokens.empty()) continue;

        size_t keyTypeIdx = 0;

        // Check if first token is options (doesn't start with ssh- or ecdsa-)
        if (!tokens[0].empty() && 
            tokens[0].find("ssh-") != 0 && 
            tokens[0].find("ecdsa-") != 0) {
            key.options = tokens[0];
            keyTypeIdx = 1;
        }

        if (keyTypeIdx < tokens.size()) {
            key.keyType = tokens[keyTypeIdx];
        }

        if (keyTypeIdx + 1 < tokens.size()) {
            key.publicKey = tokens[keyTypeIdx + 1];
        }

        // Rest is comment
        if (keyTypeIdx + 2 < tokens.size()) {
            key.comment = tokens[keyTypeIdx + 2];
            for (size_t i = keyTypeIdx + 3; i < tokens.size(); ++i) {
                key.comment += " " + tokens[i];
            }
        }

        keys.push_back(key);
    }

    return keys;
}

// ============================================================================
// Shell History Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeShellHistory() {
    std::cout << "Analyzing shell history..." << std::endl;

    // Find bash history files
    auto bashHistoryFiles = queryFilesByPattern("%/.bash_history");
    for (const auto& file : bashHistoryFiles) {
        std::string extractPath = getExtractPath("history/" + std::to_string(file.inode) + "_bash_history");
        if (extractFileToPath(file.inode, extractPath)) {
            // Extract username from path
            std::string username = "unknown";
            size_t homePos = file.path.find("/home/");
            size_t rootPos = file.path.find("/root/");
            
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    username = file.path.substr(start, end - start);
                }
            } else if (rootPos != std::string::npos) {
                username = "root";
            }

            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::stringstream buffer;
                buffer << f.rdbuf();
                auto entries = LinuxHistoryParser::parseBashHistory(buffer.str(), username, file.path);
                linuxDb_->insertShellHistories(entries);
                AuditLog::instance().log("SYSTEM", "LINUX_BASH_HISTORY_PARSED", 
                                          "Parsed " + std::to_string(entries.size()) + 
                                          " commands from " + username + "'s bash history");
            }
        }
    }

    // Find zsh history files
    auto zshHistoryFiles = queryFilesByPattern("%/.zsh_history");
    for (const auto& file : zshHistoryFiles) {
        std::string extractPath = getExtractPath("history/" + std::to_string(file.inode) + "_zsh_history");
        if (extractFileToPath(file.inode, extractPath)) {
            std::string username = "unknown";
            size_t homePos = file.path.find("/home/");
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    username = file.path.substr(start, end - start);
                }
            }

            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::stringstream buffer;
                buffer << f.rdbuf();
                auto entries = LinuxHistoryParser::parseZshHistory(buffer.str(), username, file.path);
                linuxDb_->insertShellHistories(entries);
            }
        }
    }
}

std::vector<ShellHistoryEntry> LinuxFilesAnalyzer::parseHistoryFile(const std::string& historyPath,
                                                                      const std::string& username,
                                                                      const std::string& shellType) {
    std::ifstream file(historyPath);
    if (!file.is_open()) {
        return {};
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    return LinuxHistoryParser::parseHistoryFile(buffer.str(), username, historyPath, shellType);
}

// ============================================================================
// System Configuration Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeCronJobs() {
    std::cout << "Analyzing cron jobs..." << std::endl;

    // System crontab
    auto crontabFiles = queryFilesByPattern("%/etc/crontab");
    for (const auto& file : crontabFiles) {
        std::string extractPath = getExtractPath("etc/crontab");
        if (extractFileToPath(file.inode, extractPath)) {
            auto jobs = parseCronFile(extractPath, "root");
            linuxDb_->insertCronJobs(jobs);
        }
    }

    // User crontabs
    auto userCrontabs = queryFilesByPattern("%/var/spool/cron/crontabs/%");
    for (const auto& file : userCrontabs) {
        std::string extractPath = getExtractPath("cron/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto jobs = parseCronFile(extractPath, file.name);
            linuxDb_->insertCronJobs(jobs);
        }
    }

    // cron.d directory
    auto cronDFiles = queryFilesByPattern("%/etc/cron.d/%");
    for (const auto& file : cronDFiles) {
        std::string extractPath = getExtractPath("cron.d/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            auto jobs = parseCronFile(extractPath, "root");
            linuxDb_->insertCronJobs(jobs);
        }
    }
}

std::vector<CronJobEntry> LinuxFilesAnalyzer::parseCronFile(const std::string& cronPath,
                                                              const std::string& username) {
    std::vector<CronJobEntry> jobs;

    std::ifstream file(cronPath);
    if (!file.is_open()) {
        return jobs;
    }

    std::string line;
    while (std::getline(file, line)) {
        // Skip empty lines and comments
        if (line.empty() || line[0] == '#') {
            continue;
        }

        // Skip variable assignments
        if (line.find('=') != std::string::npos && line.find(' ') > line.find('=')) {
            continue;
        }

        // Parse cron line
        std::istringstream ss(line);
        std::string minute, hour, dayOfMonth, month, dayOfWeek, user, command;

        ss >> minute >> hour >> dayOfMonth >> month >> dayOfWeek;

        // Check if this is system crontab format (has username field)
        std::string rest;
        std::getline(ss >> std::ws, rest);

        if (cronPath.find("/etc/crontab") != std::string::npos ||
            cronPath.find("/etc/cron.d/") != std::string::npos) {
            // System format: min hour dom mon dow user command
            size_t firstSpace = rest.find(' ');
            if (firstSpace != std::string::npos) {
                user = rest.substr(0, firstSpace);
                command = rest.substr(firstSpace + 1);
            }
        } else {
            // User crontab format: min hour dom mon dow command
            user = username;
            command = rest;
        }

        if (!command.empty()) {
            CronJobEntry job;
            job.username = user.empty() ? username : user;
            job.minute = minute;
            job.hour = hour;
            job.dayOfMonth = dayOfMonth;
            job.month = month;
            job.dayOfWeek = dayOfWeek;
            job.command = command;
            job.cronFile = cronPath;
            job.cronType = cronPath.find("cron.d") != std::string::npos ? "cron.d" :
                          cronPath.find("crontab") != std::string::npos ? "system" : "user";

            jobs.push_back(job);
        }
    }

    return jobs;
}

void LinuxFilesAnalyzer::analyzeSystemdServices() {
    std::cout << "Analyzing systemd services..." << std::endl;

    // Find systemd service unit files
    std::vector<std::string> systemdPaths = {
        "%/etc/systemd/system/%.service",
        "%/lib/systemd/system/%.service",
        "%/usr/lib/systemd/system/%.service"
    };

    std::vector<SystemdServiceInfo> allServices;

    for (const auto& pattern : systemdPaths) {
        auto serviceFiles = queryFilesByPattern(pattern);
        for (const auto& file : serviceFiles) {
            // Skip symlinks and directories in the result
            if (file.name.empty() || file.name[0] == '.') {
                continue;
            }

            std::string extractPath = getExtractPath("systemd/" + file.name);
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream f(extractPath);
                if (f.is_open()) {
                    SystemdServiceInfo service;
                    service.serviceName = file.name;
                    service.unitFile = file.path;
                    service.loadState = "loaded";
                    service.activeState = "unknown"; // Can't determine from static file
                    service.subState = "unknown";
                    service.isEnabled = false;

                    std::string line;
                    std::string currentSection;

                    while (std::getline(f, line)) {
                        // Trim whitespace
                        size_t start = line.find_first_not_of(" \t");
                        if (start == std::string::npos) continue;
                        line = line.substr(start);

                        // Skip comments
                        if (line.empty() || line[0] == '#' || line[0] == ';') {
                            continue;
                        }

                        // Check for section header
                        if (line[0] == '[' && line.back() == ']') {
                            currentSection = line.substr(1, line.length() - 2);
                            continue;
                        }

                        // Parse key=value
                        size_t eqPos = line.find('=');
                        if (eqPos == std::string::npos) continue;

                        std::string key = line.substr(0, eqPos);
                        std::string value = line.substr(eqPos + 1);

                        // Trim key and value
                        while (!key.empty() && (key.back() == ' ' || key.back() == '\t')) {
                            key.pop_back();
                        }
                        size_t valStart = value.find_first_not_of(" \t");
                        if (valStart != std::string::npos) {
                            value = value.substr(valStart);
                        }

                        // Extract relevant fields
                        if (currentSection == "Unit") {
                            if (key == "Description") {
                                service.description = value;
                            }
                        } else if (currentSection == "Service") {
                            if (key == "ExecStart") {
                                service.execStart = value;
                            } else if (key == "User") {
                                service.user = value;
                            }
                        } else if (currentSection == "Install") {
                            if (key == "WantedBy" || key == "RequiredBy") {
                                // If WantedBy exists, service can be enabled
                                service.isEnabled = true; // Approximation
                            }
                        }
                    }

                    allServices.push_back(service);
                }
            }
        }
    }

    // Insert all services to database
    for (const auto& service : allServices) {
        linuxDb_->insertSystemdService(service);
    }

    AuditLog::instance().log("SYSTEM", "LINUX_SYSTEMD_PARSED",
                              "Parsed " + std::to_string(allServices.size()) + " systemd services");
}

void LinuxFilesAnalyzer::analyzeInstalledPackages() {
    std::cout << "Analyzing installed packages..." << std::endl;

    // dpkg status file (Debian-based)
    auto dpkgStatus = queryFilesByPattern("%/var/lib/dpkg/status");
    for (const auto& file : dpkgStatus) {
        std::string extractPath = getExtractPath("dpkg/status");
        if (extractFileToPath(file.inode, extractPath)) {
            auto packages = parseDpkgStatus(extractPath);
            linuxDb_->insertPackageInfos(packages);
            AuditLog::instance().log("SYSTEM", "LINUX_PACKAGES_PARSED", 
                                      "Parsed " + std::to_string(packages.size()) + " installed packages");
        }
    }
}

std::vector<PackageInfo> LinuxFilesAnalyzer::parseDpkgStatus(const std::string& statusPath) {
    std::vector<PackageInfo> packages;

    std::ifstream file(statusPath);
    if (!file.is_open()) {
        return packages;
    }

    PackageInfo currentPkg;
    currentPkg.packageManager = "dpkg";
    bool hasPackage = false;

    std::string line;
    while (std::getline(file, line)) {
        if (line.empty()) {
            // End of package entry
            if (hasPackage && !currentPkg.name.empty()) {
                packages.push_back(currentPkg);
            }
            currentPkg = PackageInfo();
            currentPkg.packageManager = "dpkg";
            hasPackage = false;
            continue;
        }

        if (line.find("Package:") == 0) {
            currentPkg.name = line.substr(9);
            hasPackage = true;
        } else if (line.find("Version:") == 0) {
            currentPkg.version = line.substr(9);
        } else if (line.find("Architecture:") == 0) {
            currentPkg.architecture = line.substr(14);
        } else if (line.find("Status:") == 0) {
            currentPkg.status = line.substr(8);
        } else if (line.find("Description:") == 0) {
            currentPkg.description = line.substr(13);
        } else if (line.find("Maintainer:") == 0) {
            currentPkg.maintainer = line.substr(12);
        }
    }

    // Save last package
    if (hasPackage && !currentPkg.name.empty()) {
        packages.push_back(currentPkg);
    }

    return packages;
}

void LinuxFilesAnalyzer::analyzeNetworkConfiguration() {
    std::cout << "Analyzing network configuration..." << std::endl;

    // Parse /etc/network/interfaces (Debian-based systems)
    auto interfacesFiles = queryFilesByPattern("%/etc/network/interfaces");
    for (const auto& file : interfacesFiles) {
        std::string extractPath = getExtractPath("network/interfaces");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::string line;
                NetworkConnection conn;
                std::string currentInterface;

                while (std::getline(f, line)) {
                    // Trim
                    size_t start = line.find_first_not_of(" \t");
                    if (start == std::string::npos) continue;
                    line = line.substr(start);
                    
                    if (line.empty() || line[0] == '#') continue;

                    std::istringstream ss(line);
                    std::string keyword;
                    ss >> keyword;

                    if (keyword == "iface") {
                        // iface eth0 inet static
                        std::string iface, family, method;
                        ss >> iface >> family >> method;
                        currentInterface = iface;
                    } else if (keyword == "address" && !currentInterface.empty()) {
                        std::string addr;
                        ss >> addr;
                        conn.localAddress = addr;
                        conn.protocol = "interface:" + currentInterface;
                        conn.state = "configured";
                        linuxDb_->insertNetworkConnection(conn);
                    }
                }
            }
        }
    }

    // Parse /etc/resolv.conf for DNS configuration
    auto resolvFiles = queryFilesByPattern("%/etc/resolv.conf");
    for (const auto& file : resolvFiles) {
        std::string extractPath = getExtractPath("network/resolv.conf");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::string line;
                while (std::getline(f, line)) {
                    size_t start = line.find_first_not_of(" \t");
                    if (start == std::string::npos) continue;
                    line = line.substr(start);
                    
                    if (line.empty() || line[0] == '#') continue;

                    std::istringstream ss(line);
                    std::string keyword;
                    ss >> keyword;

                    if (keyword == "nameserver") {
                        std::string dns;
                        ss >> dns;
                        NetworkConnection conn;
                        conn.protocol = "dns";
                        conn.remoteAddress = dns;
                        conn.remotePort = 53;
                        conn.state = "configured";
                        linuxDb_->insertNetworkConnection(conn);
                    }
                }
            }
        }
    }

    // Parse /etc/hosts for static host mappings
    auto hostsFiles = queryFilesByPattern("%/etc/hosts");
    for (const auto& file : hostsFiles) {
        std::string extractPath = getExtractPath("network/hosts");
        if (extractFileToPath(file.inode, extractPath)) {
            // Just log that we found hosts file; detailed parsing could be added
            AuditLog::instance().log("SYSTEM", "LINUX_HOSTS_FOUND",
                                      "Found /etc/hosts file at " + file.path);
        }
    }

    AuditLog::instance().log("SYSTEM", "LINUX_NETWORK_CONFIG_PARSED",
                              "Analyzed network configuration files");
}

// ============================================================================
// Security Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeFirewallRules() {
    std::cout << "Analyzing firewall rules..." << std::endl;

    // Common locations for iptables rules
    std::vector<std::string> iptablesPaths = {
        "%/etc/iptables/rules.v4",
        "%/etc/iptables/rules.v6",
        "%/etc/iptables.rules",
        "%/etc/sysconfig/iptables",
        "%/etc/ufw/user.rules",
        "%/etc/ufw/user6.rules"
    };

    std::vector<FirewallRule> allRules;

    for (const auto& pattern : iptablesPaths) {
        auto ruleFiles = queryFilesByPattern(pattern);
        for (const auto& file : ruleFiles) {
            std::string extractPath = getExtractPath("firewall/" + file.name);
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream f(extractPath);
                if (f.is_open()) {
                    std::string line;
                    std::string currentTable = "filter"; // Default table
                    std::string currentChain;

                    while (std::getline(f, line)) {
                        // Trim
                        size_t start = line.find_first_not_of(" \t");
                        if (start == std::string::npos) continue;
                        line = line.substr(start);

                        if (line.empty() || line[0] == '#') continue;

                        // Table header: *filter, *nat, *mangle
                        if (line[0] == '*') {
                            currentTable = line.substr(1);
                            continue;
                        }

                        // COMMIT - end of table
                        if (line == "COMMIT") {
                            continue;
                        }

                        // Chain definition: :INPUT ACCEPT [0:0]
                        if (line[0] == ':') {
                            size_t spacePos = line.find(' ');
                            if (spacePos != std::string::npos) {
                                currentChain = line.substr(1, spacePos - 1);
                            }
                            continue;
                        }

                        // Rule: -A INPUT -p tcp --dport 22 -j ACCEPT
                        if (line.find("-A ") == 0 || line.find("-I ") == 0) {
                            FirewallRule rule;
                            rule.table = currentTable;
                            rule.ruleSpec = line;

                            std::istringstream ss(line);
                            std::string token;

                            while (ss >> token) {
                                if (token == "-A" || token == "-I") {
                                    ss >> rule.chain;
                                } else if (token == "-p") {
                                    ss >> rule.protocol;
                                } else if (token == "-s") {
                                    ss >> rule.source;
                                } else if (token == "-d") {
                                    ss >> rule.destination;
                                } else if (token == "--sport") {
                                    std::string port;
                                    ss >> port;
                                    try { rule.sourcePort = std::stoi(port); } 
                                    catch (...) { rule.sourcePort = -1; }
                                } else if (token == "--dport") {
                                    std::string port;
                                    ss >> port;
                                    try { rule.destinationPort = std::stoi(port); } 
                                    catch (...) { rule.destinationPort = -1; }
                                } else if (token == "-j") {
                                    ss >> rule.action;
                                }
                            }

                            allRules.push_back(rule);
                        }
                    }
                }
            }
        }
    }

    // Insert all rules to database
    for (const auto& rule : allRules) {
        linuxDb_->insertFirewallRule(rule);
    }

    AuditLog::instance().log("SYSTEM", "LINUX_FIREWALL_PARSED",
                              "Parsed " + std::to_string(allRules.size()) + " firewall rules");
}

void LinuxFilesAnalyzer::analyzeAuditLogs() {
    std::cout << "Analyzing audit logs..." << std::endl;

    auto auditFiles = queryFilesByPattern("%/var/log/audit/audit.log%");
    std::vector<LinuxAuditLogEntry> allEntries;

    for (const auto& file : auditFiles) {
        std::string extractPath = getExtractPath("audit/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::string line;
                
                // auditd format: type=TYPE msg=audit(TIMESTAMP:SERIAL): key=value ...
                std::regex auditPattern(R"(type=(\w+)\s+msg=audit\((\d+)\.(\d+):(\d+)\):(.*))");;

                while (std::getline(f, line)) {
                    if (line.empty()) continue;

                    std::smatch match;
                    if (std::regex_search(line, match, auditPattern)) {
                        LinuxAuditLogEntry entry;
                        entry.type = match[1].str();
                        
                        // Parse timestamp (seconds.milliseconds)
                        try {
                            entry.timestamp = std::stoll(match[2].str());
                        } catch (...) {
                            entry.timestamp = 0;
                        }
                        
                        // Parse serial number
                        try {
                            entry.serialNumber = std::stoi(match[4].str());
                        } catch (...) {
                            entry.serialNumber = 0;
                        }
                        
                        entry.message = line;
                        
                        // Extract additional fields from the message part
                        std::string msgPart = match[5].str();
                        
                        // Look for common fields
                        size_t resultPos = msgPart.find("res=");
                        if (resultPos != std::string::npos) {
                            size_t start = resultPos + 4;
                            size_t end = msgPart.find(' ', start);
                            entry.result = msgPart.substr(start, end - start);
                        }
                        
                        size_t uidPos = msgPart.find("auid=");
                        if (uidPos != std::string::npos) {
                            size_t start = uidPos + 5;
                            size_t end = msgPart.find(' ', start);
                            entry.subject = "auid=" + msgPart.substr(start, end - start);
                        }
                        
                        size_t exePos = msgPart.find("exe=\"");
                        if (exePos != std::string::npos) {
                            size_t start = exePos + 5;
                            size_t end = msgPart.find('"', start);
                            if (end != std::string::npos) {
                                entry.object = msgPart.substr(start, end - start);
                            }
                        }
                        
                        // Determine action from type
                        if (entry.type.find("SYSCALL") != std::string::npos) {
                            entry.action = "syscall";
                        } else if (entry.type.find("USER_") != std::string::npos) {
                            entry.action = "user_action";
                        } else if (entry.type.find("LOGIN") != std::string::npos) {
                            entry.action = "login";
                        } else {
                            entry.action = "audit";
                        }
                        
                        allEntries.push_back(entry);
                    }
                }
            }
        }
    }

    // Insert all entries to database
    linuxDb_->insertAuditLogs(allEntries);

    AuditLog::instance().log("SYSTEM", "LINUX_AUDIT_LOGS_PARSED",
                              "Parsed " + std::to_string(allEntries.size()) + " audit log entries");
}

// ============================================================================
// Browser Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeBrowserData() {
    std::cout << "Analyzing browser data..." << std::endl;

    // Chrome/Chromium profiles
    auto chromeProfiles = queryFilesByPattern("%/.config/google-chrome/%");
    auto chromiumProfiles = queryFilesByPattern("%/.config/chromium/%");

    // Firefox profiles
    auto firefoxProfiles = queryFilesByPattern("%/.mozilla/firefox/%");

    // Placeholder - actual browser parsing would use similar logic to Windows browser parser
    // but with Linux-appropriate paths

    for (const auto& file : chromeProfiles) {
        if (file.path.find("Default") != std::string::npos ||
            file.path.find("Profile") != std::string::npos) {
            LinuxBrowserProfile profile;
            profile.browserType = LinuxBrowserType::CHROME;
            profile.browserName = "Google Chrome";
            profile.profilePath = file.path;
            
            // Extract username from path
            size_t homePos = file.path.find("/home/");
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    profile.username = file.path.substr(start, end - start);
                }
            }
            
            linuxDb_->insertBrowserProfile(profile);
        }
    }

    for (const auto& file : firefoxProfiles) {
        if (file.name.find(".default") != std::string::npos) {
            LinuxBrowserProfile profile;
            profile.browserType = LinuxBrowserType::FIREFOX;
            profile.browserName = "Firefox";
            profile.profilePath = file.path;
            profile.profileName = file.name;
            
            size_t homePos = file.path.find("/home/");
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    profile.username = file.path.substr(start, end - start);
                }
            }
            
            linuxDb_->insertBrowserProfile(profile);
        }
    }
}

// ============================================================================
// User Parsing Wrappers
// ============================================================================

std::vector<LinuxUserInfo> LinuxFilesAnalyzer::parsePasswdFile(const std::string& passwdPath) {
    std::ifstream file(passwdPath);
    if (!file.is_open()) {
        return {};
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    return LinuxUserParser::parsePasswdFile(buffer.str());
}

std::vector<LinuxUserInfo> LinuxFilesAnalyzer::parseShadowFile(const std::string& shadowPath,
                                                                 std::vector<LinuxUserInfo>& users) {
    std::ifstream file(shadowPath);
    if (!file.is_open()) {
        return users;
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    LinuxUserParser::parseShadowFile(buffer.str(), users);
    return users;
}

std::vector<LinuxGroupInfo> LinuxFilesAnalyzer::parseGroupFile(const std::string& groupPath) {
    std::ifstream file(groupPath);
    if (!file.is_open()) {
        return {};
    }

    std::stringstream buffer;
    buffer << file.rdbuf();
    return LinuxUserParser::parseGroupFile(buffer.str());
}

std::vector<LinuxLoginRecord> LinuxFilesAnalyzer::parseWtmpFile(const std::string& wtmpPath) {
    return LinuxUserParser::parseWtmpFile(wtmpPath);
}

std::vector<LinuxLoginRecord> LinuxFilesAnalyzer::parseBtmpFile(const std::string& btmpPath) {
    return LinuxUserParser::parseBtmpFile(btmpPath);
}

// ============================================================================
// RPM Package Manager Support
// ============================================================================

std::string LinuxFilesAnalyzer::detectLinuxDistribution() {
    // Try to detect Linux distribution type
    std::string distro = "unknown";
    
    // Check for /etc/os-release (modern standard)
    auto osReleaseFiles = queryFilesByPattern("%/etc/os-release");
    for (const auto& file : osReleaseFiles) {
        std::string extractPath = getExtractPath("etc/os-release");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream f(extractPath);
            if (f.is_open()) {
                std::string line;
                while (std::getline(f, line)) {
                    if (line.find("ID=") == 0) {
                        distro = line.substr(3);
                        // Remove quotes if present
                        if (!distro.empty() && distro[0] == '"') {
                            distro = distro.substr(1, distro.length() - 2);
                        }
                        break;
                    }
                }
            }
        }
        break;
    }
    
    // Fallback: check for distro-specific files
    if (distro == "unknown") {
        auto debianFiles = queryFilesByPattern("%/etc/debian_version");
        if (!debianFiles.empty()) {
            distro = "debian";
        }
        
        auto redhatFiles = queryFilesByPattern("%/etc/redhat-release");
        if (!redhatFiles.empty()) {
            distro = "rhel";
        }
        
        auto fedoraFiles = queryFilesByPattern("%/etc/fedora-release");
        if (!fedoraFiles.empty()) {
            distro = "fedora";
        }
        
        auto centosFiles = queryFilesByPattern("%/etc/centos-release");
        if (!centosFiles.empty()) {
            distro = "centos";
        }
    }
    
    return distro;
}

bool LinuxFilesAnalyzer::isRpmBasedDistro() {
    std::string distro = detectLinuxDistribution();
    
    // Common RPM-based distributions
    static const std::vector<std::string> rpmDistros = {
        "rhel", "centos", "fedora", "rocky", "alma", "ol", "amzn",
        "suse", "opensuse", "opensuse-leap", "opensuse-tumbleweed"
    };
    
    for (const auto& d : rpmDistros) {
        if (distro.find(d) != std::string::npos) {
            return true;
        }
    }
    
    // Also check for RPM database presence
    auto rpmDbFiles = queryFilesByPattern("%/var/lib/rpm/Packages");
    if (!rpmDbFiles.empty()) {
        return true;
    }
    
    auto rpmDbNewFiles = queryFilesByPattern("%/var/lib/rpm/rpmdb.sqlite");
    return !rpmDbNewFiles.empty();
}

bool LinuxFilesAnalyzer::isDpkgBasedDistro() {
    std::string distro = detectLinuxDistribution();
    
    // Common DPKG-based distributions
    static const std::vector<std::string> dpkgDistros = {
        "debian", "ubuntu", "mint", "pop", "elementary", "kali", "raspbian"
    };
    
    for (const auto& d : dpkgDistros) {
        if (distro.find(d) != std::string::npos) {
            return true;
        }
    }
    
    // Also check for dpkg database presence
    auto dpkgFiles = queryFilesByPattern("%/var/lib/dpkg/status");
    return !dpkgFiles.empty();
}

std::vector<PackageInfo> LinuxFilesAnalyzer::parseRpmDatabase(const std::string& rpmDbPath) {
    std::vector<PackageInfo> packages;
    
    // The RPM database can be in different formats:
    // - Legacy BerkeleyDB format (/var/lib/rpm/Packages)
    // - Modern SQLite format (/var/lib/rpm/rpmdb.sqlite)
    // - Plain text from rpm -qa --queryformat output
    
    // For forensic purposes, we'll try to parse what we can
    // The safest approach is to try the SQLite format first (newer RPM versions)
    
    std::ifstream file(rpmDbPath);
    if (!file.is_open()) {
        return packages;
    }
    
    // Check if it's a SQLite database (starts with "SQLite format 3")
    char header[16] = {0};
    file.read(header, 16);
    file.seekg(0);
    
    if (std::string(header, 16).find("SQLite format 3") != std::string::npos) {
        // SQLite format - open with sqlite3
        sqlite3* rpmDb = nullptr;
        if (sqlite3_open_v2(rpmDbPath.c_str(), &rpmDb, SQLITE_OPEN_READONLY, nullptr) == SQLITE_OK) {
            // Query package information
            const char* sql = "SELECT name, version, release, arch FROM Packages";
            sqlite3_stmt* stmt;
            
            if (sqlite3_prepare_v2(rpmDb, sql, -1, &stmt, nullptr) == SQLITE_OK) {
                while (sqlite3_step(stmt) == SQLITE_ROW) {
                    PackageInfo pkg;
                    pkg.packageManager = "rpm";
                    
                    const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
                    const char* version = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
                    const char* release = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
                    const char* arch = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
                    
                    pkg.name = name ? name : "";
                    pkg.version = version ? version : "";
                    if (release) {
                        pkg.version += "-" + std::string(release);
                    }
                    pkg.architecture = arch ? arch : "";
                    pkg.status = "installed";
                    
                    packages.push_back(pkg);
                }
                sqlite3_finalize(stmt);
            }
            sqlite3_close(rpmDb);
        }
    } else {
        // Try to read as plain text (output from rpm -qa)
        // Format: name-version-release.arch
        file.close();
        std::ifstream textFile(rpmDbPath);
        std::string line;
        
        while (std::getline(textFile, line)) {
            if (line.empty()) continue;
            
            PackageInfo pkg;
            pkg.packageManager = "rpm";
            pkg.status = "installed";
            
            // Parse RPM NEVRA format: name-epoch:version-release.arch
            // Simpler format: name-version-release.arch
            
            size_t archPos = line.rfind('.');
            if (archPos != std::string::npos) {
                pkg.architecture = line.substr(archPos + 1);
                line = line.substr(0, archPos);
            }
            
            size_t releasePos = line.rfind('-');
            if (releasePos != std::string::npos) {
                std::string release = line.substr(releasePos + 1);
                line = line.substr(0, releasePos);
                
                size_t versionPos = line.rfind('-');
                if (versionPos != std::string::npos) {
                    std::string version = line.substr(versionPos + 1);
                    pkg.name = line.substr(0, versionPos);
                    pkg.version = version + "-" + release;
                } else {
                    pkg.name = line;
                    pkg.version = release;
                }
            } else {
                pkg.name = line;
            }
            
            if (!pkg.name.empty()) {
                packages.push_back(pkg);
            }
        }
    }
    
    return packages;
}

void LinuxFilesAnalyzer::analyzeRpmPackages() {
    std::cout << "Analyzing RPM packages..." << std::endl;
    
    // Try modern SQLite-based RPM database first
    auto rpmSqliteDb = queryFilesByPattern("%/var/lib/rpm/rpmdb.sqlite");
    for (const auto& file : rpmSqliteDb) {
        std::string extractPath = getExtractPath("rpm/rpmdb.sqlite");
        if (extractFileToPath(file.inode, extractPath)) {
            auto packages = parseRpmDatabase(extractPath);
            linuxDb_->insertPackageInfos(packages);
            AuditLog::instance().log("SYSTEM", "LINUX_RPM_PACKAGES_PARSED", 
                                      "Parsed " + std::to_string(packages.size()) + " RPM packages from SQLite DB");
            return; // Found and parsed
        }
    }
    
    // Try legacy BerkeleyDB format
    // Note: For proper BerkeleyDB parsing, we'd need libdb, but we can try 
    // to extract package names from the raw database file
    auto rpmLegacyDb = queryFilesByPattern("%/var/lib/rpm/Packages");
    for (const auto& file : rpmLegacyDb) {
        std::string extractPath = getExtractPath("rpm/Packages");
        if (extractFileToPath(file.inode, extractPath)) {
            // BerkeleyDB is complex; log that we found it but can't fully parse
            AuditLog::instance().log("SYSTEM", "LINUX_RPM_DATABASE_FOUND", 
                                      "Found legacy BerkeleyDB RPM database at " + file.path);
            // In a full implementation, we'd use libdb to read this
        }
    }
}

