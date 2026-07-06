// LinuxSystemParser.cpp
// System configuration analysis implementation

#include "../LinuxFilesAnalyzer.h"
#include "LinuxHistoryParser.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <sstream>
#include <filesystem>
#include <sqlite3.h>

namespace fs = std::filesystem;

// ============================================================================
// Shell History Analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeShellHistory() {
    std::cout << "Analyzing shell history..." << std::endl;

    // Find bash history files
    auto bashHistoryFiles = queryFilesByPattern("%/.bash_history");
    for (const auto& file : bashHistoryFiles) {
        std::string extractPath = getExtractPath("history/" + std::to_string(file.inode) + "_bash_history");
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            auto jobs = parseCronFile(extractPath, "root");
            linuxDb_->insertCronJobs(jobs);
        }
    }

    // User crontabs
    auto userCrontabs = queryFilesByPattern("%/var/spool/cron/crontabs/%");
    for (const auto& file : userCrontabs) {
        std::string extractPath = getExtractPath("cron/" + file.name);
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            auto jobs = parseCronFile(extractPath, file.name);
            linuxDb_->insertCronJobs(jobs);
        }
    }

    // cron.d directory
    auto cronDFiles = queryFilesByPattern("%/etc/cron.d/%");
    for (const auto& file : cronDFiles) {
        std::string extractPath = getExtractPath("cron.d/" + file.name);
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
            if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
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
        if (extractFileToPath(file.inode, extractPath, file.partitionNum)) {
            // BerkeleyDB is complex; log that we found it but can't fully parse
            AuditLog::instance().log("SYSTEM", "LINUX_RPM_DATABASE_FOUND",
                                      "Found legacy BerkeleyDB RPM database at " + file.path);
            // In a full implementation, we'd use libdb to read this
        }
    }
}
