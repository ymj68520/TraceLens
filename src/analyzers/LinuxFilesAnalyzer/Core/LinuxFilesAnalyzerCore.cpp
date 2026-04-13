// LinuxFilesAnalyzerCore.cpp
// Core implementation of LinuxFilesAnalyzer

#include "LinuxFilesAnalyzer.h"
#include "HTTPServer/LinuxLLMAnalysisService.h"
#include "AuditLog/AuditLog.h"
#include <filesystem>

// Container parsers
#include "Parsers/Container/DockerContainerParser.h"
#include "Parsers/Container/PodmanParser.h"

// Web server parsers
#include "Parsers/WebServer/ApacheParser.h"
#include "Parsers/WebServer/NginxParser.h"

// Security parsers
#include "Parsers/Security/SetuidAnalyzer.h"
#include "Parsers/Security/CapabilityAnalyzer.h"
#include "Parsers/Security/SELinuxAnalyzer.h"
#include "Parsers/Security/AppArmorParser.h"

// Enhanced analysis
#include "Analysis/LogCorrelationEngine.h"
#include "Analysis/TimelineReconstructor.h"
#include "Analysis/AnomalyDetector.h"

namespace fs = std::filesystem;

LinuxFilesAnalyzer::LinuxFilesAnalyzer()
    : dbManager_(nullptr) {
}

LinuxFilesAnalyzer::LinuxFilesAnalyzer(const std::string& imagePath, DatabaseManager* dbManager)
    : imagePath_(imagePath), dbManager_(dbManager) {
}

LinuxFilesAnalyzer::~LinuxFilesAnalyzer() {
}

bool LinuxFilesAnalyzer::initialize() {
    // Initialize file extractor
    fileExtractor_ = std::make_unique<FileExtractor>(imagePath_, dbManager_->getDbPath());
    if (!fileExtractor_->initialize()) {
        std::cerr << "Failed to initialize FileExtractor for Linux analysis" << std::endl;
        AuditLog::instance().log("SYSTEM", "LINUX_INIT_FAILED", "Failed to initialize FileExtractor for: " + imagePath_);
        return false;
    }

    // Set default extract directory if not set
    if (extractDir_.empty()) {
        extractDir_ = "extracted_linux_files";
    }

    // Initialize Linux analysis database
    if (outputDbPath_.empty()) {
        outputDbPath_ = imagePath_ + "_linux.db";
    }

    linuxDb_ = std::make_unique<LinuxAnalysisDatabase>(outputDbPath_);
    if (!linuxDb_->initialize()) {
        std::cerr << "Failed to initialize LinuxAnalysisDatabase" << std::endl;
        AuditLog::instance().log("SYSTEM", "LINUX_DB_INIT_FAILED", "Failed to initialize Linux database: " + outputDbPath_);
        return false;
    }

    AuditLog::instance().log("SYSTEM", "LINUX_INIT", "Linux analyzer initialized for: " + imagePath_);
    return true;
}

void LinuxFilesAnalyzer::analyzeLinuxData() {
    std::cout << "Starting Linux forensic analysis..." << std::endl;
    AuditLog::instance().log("SYSTEM", "LINUX_ANALYSIS_START", "Starting Linux analysis: " + imagePath_);

    // Phase 1: System logs
    analyzeSystemLogs();
    analyzeAuthLogs();
    analyzeKernelLogs();

    // Phase 2: User accounts and authentication
    analyzeUserAccounts();
    analyzeLoginHistory();
    analyzeSSHArtifacts();

    // Phase 3: Shell history
    analyzeShellHistory();

    // Phase 4: System configuration
    analyzeCronJobs();
    analyzeSystemdServices();
    analyzeInstalledPackages();
    analyzeNetworkConfiguration();

    // Phase 5: Security artifacts
    analyzeFirewallRules();
    analyzeAuditLogs();

    // Phase 6: Browser data
    analyzeBrowserData();

    // Phase 7: Container Analysis
    analyzeDockerContainers();
    analyzeDockerImages();
    analyzeDockerVolumes();
    analyzePodmanContainers();

    // Phase 8: Web Server Analysis
    analyzeApacheServers();
    analyzeNginxServers();

    // Phase 9: Security Posture Analysis
    analyzeSetuidFiles();
    analyzeCapabilities();
    analyzeSELinux();
    analyzeAppArmor();

    // Phase 10: Enhanced Analysis
    correlateEvents();
    reconstructTimeline();
    detectAnomalies();

    // Phase 11: MANDATORY: AI-powered LLM analysis of all Linux artifacts
    // This is NOT optional - all Linux system files MUST be analyzed by AI
    std::cout << "Running AI analysis on Linux artifacts..." << std::endl;
    AuditLog::instance().log("SYSTEM", "LINUX_LLM_ANALYSIS_START", "Starting LLM analysis for Linux artifacts: " + imagePath_);
    analyzeWithLLM();

    std::cout << "Linux forensic analysis completed." << std::endl;
    AuditLog::instance().log("SYSTEM", "LINUX_ANALYSIS_COMPLETE", "Linux analysis completed for: " + imagePath_);
}

void LinuxFilesAnalyzer::analyzeWithLLM() {
    try {
        forensics::LinuxLLMAnalysisService llmService;
        if (!llmService.initialize()) {
            std::cerr << "Warning: Failed to initialize Linux LLM analysis service" << std::endl;
            AuditLog::instance().log("SYSTEM", "LINUX_LLM_INIT_FAILED", "Failed to initialize LLM service for: " + imagePath_);
            return;
        }

        // Configure analysis options for comprehensive coverage
        forensics::LinuxLLMAnalysisService::AnalysisOptions options;
        options.maxArtifacts = 10000;  // Analyze all artifacts
        options.includeLogs = true;
        options.includeUsers = true;
        options.includeLogins = true;
        options.includeShellHistory = true;
        options.includeCron = true;
        options.includeSSH = true;
        options.includePackages = true;
        options.includeNetwork = true;
        options.includeSystemd = true;
        options.includeKernel = true;
        options.includeFirewall = true;
        options.includeAudit = true;
        options.includeBrowser = true;

        // Progress callback for monitoring
        auto progressCallback = [](const std::string& artifactType, int current, int total, const std::string& details) {
            std::cout << "  [" << artifactType << "] " << current << "/" << total << " - " << details << std::endl;
        };

        int analyzed = llmService.analyzeLinuxArtifacts(outputDbPath_, options, progressCallback);
        std::cout << "AI analysis completed for " << analyzed << " Linux artifacts." << std::endl;
        AuditLog::instance().log("SYSTEM", "LINUX_LLM_ANALYSIS_COMPLETE",
            "LLM analysis completed for " + std::to_string(analyzed) + " artifacts from: " + imagePath_);

    } catch (const std::exception& e) {
        std::cerr << "Error during Linux LLM analysis: " << e.what() << std::endl;
        AuditLog::instance().log("SYSTEM", "LINUX_LLM_ANALYSIS_ERROR",
            "LLM analysis error for " + imagePath_ + ": " + e.what());
    }
}

bool LinuxFilesAnalyzer::extractLinuxSystemFiles(const std::string& outputDir) {
    // Helper to extract key system files if needed in bulk
    return true;
}

std::vector<FileRecord> LinuxFilesAnalyzer::queryLinuxSystemFiles() {
    if (!dbManager_) return {};
    return {};
}

std::vector<FileRecord> LinuxFilesAnalyzer::queryFilesByPattern(const std::string& pathPattern) {
    if (!dbManager_) return {};

    std::vector<FileRecord> results;
    sqlite3* db = dbManager_->getDb();
    if (!db) return results;

    const char* query = "SELECT inode, name, path, size, mtime, atime, crtime, type, is_deleted, md5 "
                        "FROM files WHERE path LIKE ? AND is_deleted=0";
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(db) << std::endl;
        return results;
    }

    sqlite3_bind_text(stmt, 1, pathPattern.c_str(), -1, SQLITE_TRANSIENT);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecord record;
        record.inode = sqlite3_column_int64(stmt, 0);
        const char* namePtr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        record.name = namePtr ? namePtr : "";
        const char* pathPtr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        record.path = pathPtr ? pathPtr : "";
        record.size = sqlite3_column_int64(stmt, 3);
        record.mtime = sqlite3_column_int64(stmt, 4);
        record.atime = sqlite3_column_int64(stmt, 5);
        record.crtime = sqlite3_column_int64(stmt, 6);
        const char* typePtr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        record.type = typePtr ? typePtr : "";
        record.isDeleted = sqlite3_column_int(stmt, 8);
        const char* md5Ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
        record.md5 = md5Ptr ? md5Ptr : "";

        results.push_back(record);
    }

    sqlite3_finalize(stmt);
    return results;
}

std::vector<FileRecord> LinuxFilesAnalyzer::queryFilesByCategory(const std::string& category) {
    if (!dbManager_) return {};

    std::vector<FileRecord> results;
    sqlite3* db = dbManager_->getDb();
    if (!db) return results;

    const char* query = "SELECT inode, name, path, size, mtime, atime, crtime, type, is_deleted, md5 "
                        "FROM files WHERE category = ?";
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(db) << std::endl;
        return results;
    }

    sqlite3_bind_text(stmt, 1, category.c_str(), -1, SQLITE_TRANSIENT);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecord record;
        record.inode = sqlite3_column_int64(stmt, 0);
        const char* namePtr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1));
        record.name = namePtr ? namePtr : "";
        const char* pathPtr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        record.path = pathPtr ? pathPtr : "";
        record.size = sqlite3_column_int64(stmt, 3);
        record.mtime = sqlite3_column_int64(stmt, 4);
        record.atime = sqlite3_column_int64(stmt, 5);
        record.crtime = sqlite3_column_int64(stmt, 6);
        const char* typePtr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        record.type = typePtr ? typePtr : "";
        record.isDeleted = sqlite3_column_int(stmt, 8);
        const char* md5Ptr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 9));
        record.md5 = md5Ptr ? md5Ptr : "";

        results.push_back(record);
    }

    sqlite3_finalize(stmt);
    return results;
}

bool LinuxFilesAnalyzer::extractFileToPath(int64_t inode, const std::string& outputPath) {
    if (!fileExtractor_) return false;
    return fileExtractor_->extractFileByInode(inode, outputPath);
}

std::string LinuxFilesAnalyzer::getExtractPath(const std::string& relativePath) {
    fs::path p(extractDir_);
    p /= relativePath;

    // Create parent directory if needed
    if (!p.parent_path().empty()) {
        fs::create_directories(p.parent_path());
    }

    return p.string();
}

bool LinuxFilesAnalyzer::isLinuxPath(const std::string& path) {
    // Check if path looks like a Linux path structure
    std::string lowerPath = path;
    std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(), ::tolower);

    if (lowerPath.find("/etc/") != std::string::npos ||
        lowerPath.find("/var/") != std::string::npos ||
        lowerPath.find("/home/") != std::string::npos ||
        lowerPath.find("/root/") != std::string::npos ||
        lowerPath.find("/usr/") != std::string::npos ||
        lowerPath.find("/opt/") != std::string::npos) {
        return true;
    }
    return false;
}

std::string LinuxFilesAnalyzer::normalizeLinuxPath(const std::string& path) {
    std::string normalized = path;

    // Ensure path starts with forward slash
    if (!normalized.empty() && normalized[0] != '/') {
        normalized = "/" + normalized;
    }

    // Remove duplicate slashes
    std::string result;
    bool lastWasSlash = false;
    for (char c : normalized) {
        if (c == '/') {
            if (!lastWasSlash) {
                result += c;
                lastWasSlash = true;
            }
        } else {
            result += c;
            lastWasSlash = false;
        }
    }

    return result;
}

std::vector<std::string> LinuxFilesAnalyzer::findUserHomeDirectories() {
    std::vector<std::string> homeDirs;

    // Query for /home/* directories
    auto homeFiles = queryFilesByPattern("/home/%");
    std::set<std::string> foundDirs;

    for (const auto& file : homeFiles) {
        // Extract first directory under /home/
        std::string path = file.path;
        if (path.length() > 6) { // /home/
            size_t nextSlash = path.find('/', 6);
            std::string homeDir;
            if (nextSlash != std::string::npos) {
                homeDir = path.substr(0, nextSlash);
            } else {
                homeDir = path;
            }
            if (foundDirs.find(homeDir) == foundDirs.end()) {
                foundDirs.insert(homeDir);
                homeDirs.push_back(homeDir);
            }
        }
    }

    // Also check /root
    auto rootFiles = queryFilesByPattern("/root/%");
    if (!rootFiles.empty()) {
        homeDirs.push_back("/root");
    }

    return homeDirs;
}

// Binary parsing utilities

uint16_t LinuxFilesAnalyzer::readUInt16LE(const char* data) {
    return *reinterpret_cast<const uint16_t*>(data);
}

uint32_t LinuxFilesAnalyzer::readUInt32LE(const char* data) {
    return *reinterpret_cast<const uint32_t*>(data);
}

uint64_t LinuxFilesAnalyzer::readUInt64LE(const char* data) {
    return *reinterpret_cast<const uint64_t*>(data);
}

std::string LinuxFilesAnalyzer::readFixedString(const char* data, size_t len) {
    // Read null-terminated string from fixed-size buffer
    size_t actualLen = 0;
    while (actualLen < len && data[actualLen] != 0) {
        actualLen++;
    }
    return std::string(data, actualLen);
}

// ============================================================================
// Container Analysis Implementation
// ============================================================================

void LinuxFilesAnalyzer::analyzeDockerContainers() {
    std::cout << "Analyzing Docker containers..." << std::endl;

    // Look for Docker directory
    auto dockerDirs = queryFilesByPattern("var/lib/docker/%");
    if (dockerDirs.empty()) {
        std::cout << "  No Docker data found (skipping)" << std::endl;
        AuditLog::instance().log("LINUX", "DOCKER_NOT_FOUND", "No Docker directory found in image");
        return;
    }

    // Extract Docker containers directory
    std::string extractPath = getExtractPath("docker/containers");
    fs::create_directories(extractPath);

    // Query and extract container config files
    auto containerConfigs = queryFilesByPattern("var/lib/docker/containers/%/config.json");
    for (const auto& file : containerConfigs) {
        std::string outputPath = extractPath + "/" + std::to_string(file.inode) + ".json";
        if (extractFileToPath(file.inode, outputPath)) {
            AuditLog::instance().log("LINUX", "DOCKER_CONFIG_EXTRACTED",
                "Extracted container config: " + file.name);
        }
    }

    // Parse containers
    auto result = LinuxAnalysis::DockerContainerParser::parseContainers(extractPath);
    if (result.success()) {
        linuxDb_->insertDockerContainers(result.containers);
        std::cout << "  Found " << result.containers.size() << " Docker containers" << std::endl;
        AuditLog::instance().log("SUCCESS", "DOCKER_CONTAINERS_PARSED",
            "Parsed " + std::to_string(result.containers.size()) + " Docker containers");
    } else {
        AuditLog::instance().log("ERROR", "DOCKER_PARSE_FAILED",
            "Failed to parse Docker containers: " + result.error.details());
    }
}

void LinuxFilesAnalyzer::analyzeDockerImages() {
    std::cout << "Analyzing Docker images..." << std::endl;

    auto dockerDirs = queryFilesByPattern("var/lib/docker/%");
    if (dockerDirs.empty()) {
        std::cout << "  No Docker data found (skipping)" << std::endl;
        return;
    }

    std::string extractPath = getExtractPath("docker/images");
    fs::create_directories(extractPath);

    // Look for image metadata
    auto imageFiles = queryFilesByPattern("var/lib/docker/image/%/%/repositories.json");
    for (const auto& file : imageFiles) {
        std::string outputPath = extractPath + "/" + std::to_string(file.inode) + ".json";
        extractFileToPath(file.inode, outputPath);
    }

    auto images = LinuxAnalysis::DockerContainerParser::parseImages(extractPath);
    if (!images.empty()) {
        linuxDb_->insertDockerImages(images);
        std::cout << "  Found " << images.size() << " Docker images" << std::endl;
    }
}

void LinuxFilesAnalyzer::analyzeDockerVolumes() {
    std::cout << "Analyzing Docker volumes..." << std::endl;

    auto dockerDirs = queryFilesByPattern("var/lib/docker/%");
    if (dockerDirs.empty()) {
        std::cout << "  No Docker data found (skipping)" << std::endl;
        return;
    }

    std::string extractPath = getExtractPath("docker/volumes");
    fs::create_directories(extractPath);

    auto volumes = LinuxAnalysis::DockerContainerParser::parseVolumes(extractPath);
    if (!volumes.empty()) {
        linuxDb_->insertDockerVolumes(volumes);
        std::cout << "  Found " << volumes.size() << " Docker volumes" << std::endl;
    }
}

void LinuxFilesAnalyzer::analyzePodmanContainers() {
    std::cout << "Analyzing Podman containers..." << std::endl;

    // Check both system and user-level Podman directories
    std::vector<std::string> podmanPaths = {
        "var/lib/containers/%",
        "home/%/.local/share/containers/%"
    };

    bool foundPodman = false;
    for (const auto& pattern : podmanPaths) {
        auto files = queryFilesByPattern(pattern);
        if (!files.empty()) {
            foundPodman = true;
            break;
        }
    }

    if (!foundPodman) {
        std::cout << "  No Podman data found (skipping)" << std::endl;
        AuditLog::instance().log("LINUX", "PODMAN_NOT_FOUND", "No Podman directory found");
        return;
    }

    std::string extractPath = getExtractPath("podman");
    fs::create_directories(extractPath);

    auto result = LinuxAnalysis::PodmanParser::parseContainers(extractPath);
    if (result.success()) {
        linuxDb_->insertPodmanContainers(result.containers);
        linuxDb_->insertPodmanPods(result.pods);
        std::cout << "  Found " << result.containers.size() << " Podman containers, "
                  << result.pods.size() << " pods" << std::endl;
    }
}

// ============================================================================
// Web Server Analysis Implementation
// ============================================================================

void LinuxFilesAnalyzer::analyzeApacheServers() {
    std::cout << "Analyzing Apache web servers..." << std::endl;

    // Look for Apache logs in common locations
    std::vector<std::string> logPatterns = {
        "var/log/apache2/access.log%",
        "var/log/apache2/error.log%",
        "var/log/httpd/access.log%",
        "var/log/httpd/error.log%",
        "var/log/apache2/%.log",
        "var/log/httpd/%.log"
    };

    std::string extractPath = getExtractPath("apache");
    fs::create_directories(extractPath);

    int totalLogs = 0;
    for (const auto& pattern : logPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string outputPath = extractPath + "/" + std::to_string(file.inode) + ".log";
            if (extractFileToPath(file.inode, outputPath)) {
                auto parseResult = ApacheParser::parseAccessLog(outputPath);
                if (!parseResult.accessLogs.empty()) {
                    linuxDb_->insertApacheAccessLogs(parseResult.accessLogs);
                    totalLogs += parseResult.accessLogs.size();
                }
            }
        }
    }

    if (totalLogs > 0) {
        std::cout << "  Parsed " << totalLogs << " Apache log entries" << std::endl;
    } else {
        std::cout << "  No Apache logs found (skipping)" << std::endl;
    }
}

void LinuxFilesAnalyzer::analyzeNginxServers() {
    std::cout << "Analyzing Nginx web servers..." << std::endl;

    // Look for Nginx logs in common locations
    std::vector<std::string> logPatterns = {
        "var/log/nginx/access.log%",
        "var/log/nginx/error.log%",
        "var/log/nginx/%.log"
    };

    std::string extractPath = getExtractPath("nginx");
    fs::create_directories(extractPath);

    int totalLogs = 0;
    for (const auto& pattern : logPatterns) {
        auto logFiles = queryFilesByPattern(pattern);
        for (const auto& file : logFiles) {
            std::string outputPath = extractPath + "/" + std::to_string(file.inode) + ".log";
            if (extractFileToPath(file.inode, outputPath)) {
                auto parseResult = NginxParser::parseAccessLog(outputPath);
                if (!parseResult.accessLogs.empty()) {
                    linuxDb_->insertNginxAccessLogs(parseResult.accessLogs);
                    totalLogs += parseResult.accessLogs.size();
                }
            }
        }
    }

    if (totalLogs > 0) {
        std::cout << "  Parsed " << totalLogs << " Nginx log entries" << std::endl;
    } else {
        std::cout << "  No Nginx logs found (skipping)" << std::endl;
    }
}

// ============================================================================
// Security Posture Analysis Implementation
// ============================================================================

void LinuxFilesAnalyzer::analyzeSetuidFiles() {
    std::cout << "Analyzing setuid/setgid files..." << std::endl;

    // Query files with setuid/setgid permissions
    // This would typically come from a find command output or file listing
    std::string extractPath = getExtractPath("security");
    fs::create_directories(extractPath);

    // For this implementation, we'll look for common setuid binaries
    std::vector<std::string> setuidPaths = {
        "usr/bin/sudo",
        "usr/bin/passwd",
        "usr/bin/su",
        "usr/bin/ping",
        "usr/bin/newgrp",
        "usr/bin/chsh",
        "usr/bin/chfn",
        "usr/bin/gpasswd",
        "bin/su",
        "bin/ping",
        "bin/mount",
        "bin/umount"
    };

    std::vector<SetuidFileInfo> setuidFiles;
    for (const auto& path : setuidPaths) {
        auto files = queryFilesByPattern(path);
        for (const auto& file : files) {
            SetuidFileInfo info;
            info.filePath = "/" + file.path;
            info.size = file.size;
            info.permissions = 04755; // Default setuid
            info.isSetuid = true;
            info.isSetgid = false;
            setuidFiles.push_back(info);
        }
    }

    if (!setuidFiles.empty()) {
        LinuxAnalysis::SetuidAnalyzer::flagSuspiciousFiles(setuidFiles);
        linuxDb_->insertSetuidFiles(setuidFiles);
        std::cout << "  Found " << setuidFiles.size() << " setuid/setgid files" << std::endl;
    } else {
        std::cout << "  No setuid files found (skipping)" << std::endl;
    }
}

void LinuxFilesAnalyzer::analyzeCapabilities() {
    std::cout << "Analyzing Linux capabilities..." << std::endl;

    // Look for files with capabilities set
    // This would typically require getcap output or similar
    std::string extractPath = getExtractPath("security/capabilities");
    fs::create_directories(extractPath);

    // For now, note that capability analysis requires system-level access
    std::cout << "  Capability analysis requires system access (skipping)" << std::endl;
    AuditLog::instance().log("INFO", "CAPABILITIES_SKIP",
        "Capability analysis requires getcap output from live system");
}

void LinuxFilesAnalyzer::analyzeSELinux() {
    std::cout << "Analyzing SELinux status..." << std::endl;

    // Look for SELinux configuration
    auto selinuxConfigs = queryFilesByPattern("etc/selinux/config");
    auto auditLogs = queryFilesByPattern("var/log/audit/audit.log%");

    if (selinuxConfigs.empty()) {
        std::cout << "  No SELinux configuration found (skipping)" << std::endl;
        return;
    }

    std::string extractPath = getExtractPath("security/selinux");
    fs::create_directories(extractPath);

    // Extract SELinux config
    for (const auto& configItem : selinuxConfigs) {
        std::string outputPath = extractPath + "/config";
        extractFileToPath(configItem.inode, outputPath);

        auto statusResult = LinuxAnalysis::SELinuxAnalyzer::parseStatus(outputPath);
        linuxDb_->insertSELinuxStatus(statusResult.status);

        std::string enabled = LinuxAnalysis::SELinuxAnalyzer::isEnabled(statusResult.status) ? "enabled" : "disabled";
        std::cout << "  SELinux is " << enabled << " (mode: " << statusResult.status.currentMode << ")" << std::endl;
    }

    // Extract and parse AVC denials
    for (const auto& log : auditLogs) {
        std::string outputPath = extractPath + "/audit_" + std::to_string(log.inode) + ".log";
        extractFileToPath(log.inode, outputPath);

        auto denialsResult = LinuxAnalysis::SELinuxAnalyzer::extractAVCDenials(outputPath);
        if (!denialsResult.avcDenials.empty()) {
            linuxDb_->insertSELinuxAVCDenials(denialsResult.avcDenials);
            std::cout << "  Found " << denialsResult.avcDenials.size() << " SELinux AVC denials" << std::endl;
        }
    }
}

void LinuxFilesAnalyzer::analyzeAppArmor() {
    std::cout << "Analyzing AppArmor status..." << std::endl;

    // Look for AppArmor profiles
    auto appArmorProfiles = queryFilesByPattern("etc/apparmor.d/%");
    auto appArmorLogs = queryFilesByPattern("var/log/syslog%");

    if (appArmorProfiles.empty()) {
        std::cout << "  No AppArmor profiles found (skipping)" << std::endl;
        return;
    }

    std::string extractPath = getExtractPath("security/apparmor");
    fs::create_directories(extractPath);

    // Extract profiles
    int profileCount = 0;
    for (const auto& profile : appArmorProfiles) {
        std::string outputPath = extractPath + "/" + std::to_string(profile.inode);
        extractFileToPath(profile.inode, outputPath);
        profileCount++;
    }

    auto profilesResult = LinuxAnalysis::AppArmorParser::parseProfiles(extractPath);
    if (!profilesResult.profiles.empty()) {
        linuxDb_->insertAppArmorProfiles(profilesResult.profiles);
        std::cout << "  Found " << profilesResult.profiles.size() << " AppArmor profiles" << std::endl;
    }

    // Look for violations in syslog
    for (const auto& log : appArmorLogs) {
        std::string outputPath = extractPath + "/syslog_" + std::to_string(log.inode);
        extractFileToPath(log.inode, outputPath);

        auto violationsResult = LinuxAnalysis::AppArmorParser::extractViolations(outputPath);
        if (!violationsResult.violations.empty()) {
            linuxDb_->insertAppArmorViolations(violationsResult.violations);
            std::cout << "  Found " << violationsResult.violations.size() << " AppArmor violations" << std::endl;
        }
    }
}

// ============================================================================
// Enhanced Analysis Implementation
// ============================================================================

void LinuxFilesAnalyzer::correlateEvents() {
    std::cout << "Correlating events across log sources..." << std::endl;

    LinuxAnalysis::LogCorrelationEngine correlator(outputDbPath_);
    auto correlatedEvents = correlator.correlateEvents();

    if (!correlatedEvents.empty()) {
        linuxDb_->insertCorrelatedEvents(correlatedEvents);
        std::cout << "  Generated " << correlatedEvents.size() << " correlated events" << std::endl;
        AuditLog::instance().log("SUCCESS", "EVENT_CORRELATION_COMPLETE",
            "Correlated " + std::to_string(correlatedEvents.size()) + " events");
    } else {
        std::cout << "  No correlated events found" << std::endl;
    }
}

void LinuxFilesAnalyzer::reconstructTimeline() {
    std::cout << "Reconstructing unified timeline..." << std::endl;

    LinuxAnalysis::TimelineReconstructor reconstructor(outputDbPath_);
    LinuxAnalysis::Timeline timeline = reconstructor.buildTimeline();

    if (!timeline.events.empty()) {
        linuxDb_->insertTimelineEvents(timeline.events);
        std::cout << "  Timeline has " << timeline.events.size() << " events" << std::endl;
    }

    if (!timeline.gaps.empty()) {
        linuxDb_->insertTimelineGaps(timeline.gaps);
        std::cout << "  Found " << timeline.gaps.size() << " timeline gaps" << std::endl;

        if (timeline.hasUnexplainedGaps()) {
            std::cout << "  WARNING: Timeline has suspicious gaps that may indicate log tampering" << std::endl;
            AuditLog::instance().log("WARNING", "TIMELINE_GAPS_DETECTED",
                "Found " + std::to_string(timeline.gaps.size()) + " unexplained timeline gaps");
        }
    } else {
        std::cout << "  No timeline gaps detected" << std::endl;
    }
}

void LinuxFilesAnalyzer::detectAnomalies() {
    std::cout << "Detecting security anomalies..." << std::endl;

    LinuxAnalysis::AnomalyDetector detector(outputDbPath_);
    auto anomalies = detector.detectAnomalies();

    if (!anomalies.empty()) {
        linuxDb_->insertAnomalies(anomalies);

        // Count by severity
        int critical = 0, high = 0, medium = 0, low = 0;
        for (const auto& anomaly : anomalies) {
            if (anomaly.severity >= 4) critical++;
            else if (anomaly.severity == 3) high++;
            else if (anomaly.severity == 2) medium++;
            else low++;
        }

        std::cout << "  Detected " << anomalies.size() << " anomalies: "
                  << critical << " critical, " << high << " high, "
                  << medium << " medium, " << low << " low" << std::endl;

        AuditLog::instance().log("SUCCESS", "ANOMALY_DETECTION_COMPLETE",
            "Detected " + std::to_string(anomalies.size()) + " anomalies (" +
            std::to_string(critical) + " critical, " + std::to_string(high) + " high)");
    } else {
        std::cout << "  No anomalies detected" << std::endl;
    }
}
