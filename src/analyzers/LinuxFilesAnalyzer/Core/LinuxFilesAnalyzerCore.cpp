// LinuxFilesAnalyzerCore.cpp
// Core implementation of LinuxFilesAnalyzer
//
// This file holds the class lifecycle (constructors, initialize), the top-level
// analysis orchestration (analyzeLinuxData), the LLM analysis bridge, and the
// shared query/extract/path helper methods.
//
// The per-phase analyzeXxx() member implementations live in sibling files,
// all part of the same LinuxFilesAnalyzer class declared in LinuxFilesAnalyzer.h:
//   - LinuxFilesAnalyzerLogs.cpp        (compressed/journal/tampering/middleware)
//   - LinuxFilesAnalyzerContainers.cpp  (docker/podman/runtime logs)
//   - LinuxFilesAnalyzerSecurity.cpp    (persistence/account-ssh/bypass/setuid/...)
//   - LinuxFilesAnalyzerServices.cpp    (pkg-manager/db/email-vpn/firewall logs)
//   - LinuxFilesAnalyzerArtifacts.cpp   (usb/mount/cloud/history/dns/cups/xdg/...)
//   - LinuxFilesAnalyzerEnhanced.cpp    (apache/nginx/correlation/timeline/rules)

#include "LinuxFilesAnalyzer.h"
#include "HTTPServer/LinuxLLMAnalysisService.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"
#include "ConfigManager/ConfigManager.h"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <set>

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

    // Initialize Linux analysis database path first (extractDir derives from it)
    if (outputDbPath_.empty()) {
        outputDbPath_ = imagePath_ + "_linux.db";
    }

    // Set default extract directory if not set: place it next to outputDbPath_
    // so extracted files live alongside the analysis database, not the process CWD.
    if (extractDir_.empty()) {
        namespace fs = std::filesystem;
        fs::path dbPath(outputDbPath_);
        fs::path dbParent = dbPath.parent_path();
        std::string stem = dbPath.stem().string();  // e.g. "linux_test_files"
        // Strip "_files" suffix to recover the image base name
        if (stem.size() > 6 && stem.substr(stem.size() - 6) == "_files") {
            stem = stem.substr(0, stem.size() - 6);
        }
        extractDir_ = (dbParent / (stem + "_extracted_files")).string();
        fs::create_directories(extractDir_);
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
    std::cout << "  Extract directory: " << extractDir_ << std::endl;
    AuditLog::instance().log("SYSTEM", "LINUX_ANALYSIS_START", "Starting Linux analysis: " + imagePath_);

    // Phase 1: Compressed and rotated log preprocessing
    // This must run before other log analysis to include historical logs
    try {
        analyzeCompressedLogs();
    } catch (const std::exception& e) {
        std::cerr << "  Compressed log analysis error: " << e.what() << std::endl;
        AuditLog::instance().log("ERROR", "COMPRESSED_LOGS_FAILED", e.what());
    }

    // Phase 2: System logs
    try {
        analyzeSystemLogs();
    } catch (const std::exception& e) {
        std::cerr << "  System log analysis error: " << e.what() << std::endl;
        AuditLog::instance().log("ERROR", "LINUX_SYSTEM_LOG_FAILED", e.what());
    }
    analyzeAuthLogs();
    analyzeKernelLogs();

    // Phase 2.5: systemd-journald analysis
    analyzeJournalLogs();

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

    // Phase 5.5: Log tampering detection
    analyzeLogTampering();

    // Phase 5.6: Persistence mechanism detection
    analyzePersistenceMechanisms();

    // Phase 6: Browser data
    analyzeBrowserData();

    // Phase 7: Container Analysis
    analyzeDockerContainers();
    analyzeDockerImages();
    analyzeDockerVolumes();
    analyzePodmanContainers();

    // Phase 8: Container Runtime Log Analysis
    analyzeContainerRuntimeLogs();

    // Phase 8.5: Web Server Analysis
    analyzeApacheServers();
    analyzeNginxServers();

    // Phase 8.5: Middleware and Error Log Analysis (Phase 7)
    analyzeMiddlewareLogs();

    // Phase 9: Package Manager Log Analysis
    analyzePackageManagerLogs();

    // Phase 10: Account and SSH Security Analysis
    analyzeAccountSSHSecurity();

    // Phase 11: Database, Email, VPN, Firewall, Security Product Logs
    analyzeDatabaseLogs();
    analyzeEmailVPNLogs();
    analyzeFirewallSecurityLogs();

    // Phase 12: USB, Mount, Desktop, Cloud
    analyzeUSBEvents();
    analyzeMountEntries();
    analyzeCloudLogs();

    // Phase 13: Extended history (Python, MySQL, Git, Docker, Kube, Cloud credentials)
    analyzeExtendedHistory();

    // Phase 14: Security bypass (LD_PRELOAD, PATH manipulation, dynamic linker hijack)
    analyzeSecurityBypass();

    // Phase 15: Pseudo-filesystem markers (/proc, /sys)
    analyzePseudoFilesystems();

    // Phase 16: DNS configuration
    analyzeDNSConfiguration();

    // Phase 17: CUPS logs
    analyzeCUPSLogs();

    // Phase 18: systemd-coredump
    analyzeCoredumps();

    // Phase 19: Snap/Flatpak packages
    analyzeSnapFlatpak();

    // Phase 20: Browser detailed data (history, cookies, downloads, bookmarks)
    analyzeBrowserDetailedData();

    // Phase 21: XDG desktop artifacts (recent documents, trash, desktop files)
    analyzeXDGArtifacts();

    // Security Posture Analysis
    analyzeSetuidFiles();
    analyzeCapabilities();
    analyzeSELinux();
    analyzeAppArmor();

    // Enhanced Analysis
    correlateEvents();
    reconstructTimeline();
    detectAnomalies();

    // Phase 16: Rule engine and attack chain analysis
    analyzeWithRuleEngine();

    // Phase 11: MANDATORY: AI-powered LLM analysis of all Linux artifacts
    // This is NOT optional - all Linux system files MUST be analyzed by AI
    std::cout << "Running AI analysis on Linux artifacts..." << std::endl;
    AuditLog::instance().log("SYSTEM", "LINUX_LLM_ANALYSIS_START", "Starting LLM analysis for Linux artifacts: " + imagePath_);
    analyzeWithLLM();

    std::cout << "Linux forensic analysis completed." << std::endl;
    AuditLog::instance().log("SYSTEM", "LINUX_ANALYSIS_COMPLETE", "Linux analysis completed for: " + imagePath_);
}

void LinuxFilesAnalyzer::analyzeServerCloudArtifacts() {
    std::cout << "Starting Server/Cloud forensic analysis..." << std::endl;
    AuditLog::instance().log("SYSTEM", "SERVER_CLOUD_ANALYSIS_START",
        "Starting Server/Cloud analysis: " + imagePath_);

    // The server/cloud scenario reuses the full Linux analysis pipeline,
    // which already covers containers, web servers, cloud logs, network
    // configuration, security posture, and all other server-relevant artifacts.
    analyzeLinuxData();

    std::cout << "Server/Cloud forensic analysis completed." << std::endl;
    AuditLog::instance().log("SYSTEM", "SERVER_CLOUD_ANALYSIS_COMPLETE",
        "Server/Cloud analysis completed for: " + imagePath_);
}

void LinuxFilesAnalyzer::analyzeWithLLM() {
    // Skip condition 1: user explicitly requested --no-ai
    if (skipAI_) {
        std::cout << "AI analysis skipped (--no-ai)." << std::endl;
        AuditLog::instance().log("SYSTEM", "LINUX_LLM_SKIPPED", "AI analysis skipped via --no-ai flag");
        return;
    }

    // Skip condition 2: no LLM endpoint configured → auto-skip. The local LLM
    // servers (LM Studio / Ollama / vLLM) the C++ LLMClient targets do not
    // require an API key (no Authorization header is sent), so the gate is the
    // base URL rather than the key.
    try {
        auto& configManager = forensics::ConfigManager::instance();
        if (!configManager.isLoaded()) {
            configManager.load();
        }
        if (configManager.getTextBaseUrl().empty() && configManager.getLLMBaseUrl().empty()) {
            std::cout << "AI analysis skipped (no LLM_BASE_URL configured). "
                      << "Structured analysis results in linux_* tables are unaffected." << std::endl;
            AuditLog::instance().log("SYSTEM", "LINUX_LLM_SKIPPED",
                "No LLM_BASE_URL configured, skipping LLM analysis");
            return;
        }
    } catch (const std::exception& e) {
        std::cout << "AI analysis skipped (config read failed: " << e.what() << ")." << std::endl;
        AuditLog::instance().log("SYSTEM", "LINUX_LLM_SKIPPED",
            "Config read failed, skipping LLM analysis: " + std::string(e.what()));
        return;
    }

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

    // TSK paths are persisted with a leading '/'. Older Linux artifact rules
    // use relative patterns ("etc/...", "var/log/..."). Normalize at this
    // single query boundary so all existing rules see real image files.
    std::string normalizedPattern = pathPattern;
    if (!normalizedPattern.empty() && normalizedPattern.front() != '/' &&
        normalizedPattern.front() != '%' && normalizedPattern.front() != '_') {
        normalizedPattern.insert(normalizedPattern.begin(), '/');
    }
    // For wildcard-leading patterns, insert the slash after the wildcard so
    // `%/var/log/%` remains compatible with stored absolute image paths.
    if (!normalizedPattern.empty() &&
        (normalizedPattern.front() == '%' || normalizedPattern.front() == '_') &&
        normalizedPattern.size() > 1 && normalizedPattern[1] != '/') {
        normalizedPattern.insert(1, 1, '/');
    }

    std::vector<FileRecord> results;
    sqlite3* db = dbManager_->getDb();
    if (!db) return results;

    const char* query = "SELECT inode, name, path, size, mtime, atime, crtime, type, is_deleted, md5, "
                        "COALESCE(partition_num, 0) "
                        "FROM files WHERE path LIKE ? AND is_deleted=0";
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(db) << std::endl;
        return results;
    }

    sqlite3_bind_text(stmt, 1, normalizedPattern.c_str(), -1, SQLITE_TRANSIENT);

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
        record.partitionNum = sqlite3_column_int(stmt, 10);

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

    const char* query = "SELECT inode, name, path, size, mtime, atime, crtime, type, is_deleted, md5, "
                        "COALESCE(partition_num, 0) "
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
        record.partitionNum = sqlite3_column_int(stmt, 10);

        results.push_back(record);
    }

    sqlite3_finalize(stmt);
    return results;
}

bool LinuxFilesAnalyzer::extractFileToPath(int64_t inode, const std::string& outputPath, int partitionNum) {
    if (!fileExtractor_) return false;
    return fileExtractor_->extractFileByInode(inode, outputPath, partitionNum);
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
