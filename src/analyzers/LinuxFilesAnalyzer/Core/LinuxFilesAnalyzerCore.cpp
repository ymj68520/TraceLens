// LinuxFilesAnalyzerCore.cpp
// Core implementation of LinuxFilesAnalyzer

#include "LinuxFilesAnalyzer.h"
#include "HTTPServer/LinuxLLMAnalysisService.h"
#include "AuditLog/AuditLog.h"
#include <filesystem>

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

    // 1. Analyze system logs
    analyzeSystemLogs();
    analyzeAuthLogs();
    analyzeKernelLogs();

    // 2. Analyze user accounts and authentication
    analyzeUserAccounts();
    analyzeLoginHistory();
    analyzeSSHArtifacts();

    // 3. Analyze shell history
    analyzeShellHistory();

    // 4. Analyze system configuration
    analyzeCronJobs();
    analyzeSystemdServices();
    analyzeInstalledPackages();

    // 5. Analyze network configuration
    analyzeNetworkConfiguration();

    // 6. Analyze security artifacts
    analyzeFirewallRules();
    analyzeAuditLogs();

    // 7. Analyze browser data
    analyzeBrowserData();

    // 8. MANDATORY: AI-powered LLM analysis of all Linux artifacts
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
