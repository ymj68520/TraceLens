// WindowsFilesAnalyzerCore.cpp
// Core implementation of WindowsFilesAnalyzer

#include "WindowsFilesAnalyzer.h"
#include "HTTPServer/WindowsLLMAnalysisService.h"
#include "AuditLog/AuditLog.h"
#include "ConfigManager/ConfigManager.h"
#include <filesystem>

namespace fs = std::filesystem;

WindowsFilesAnalyzer::WindowsFilesAnalyzer()
    : dbManager_(nullptr) {
}

WindowsFilesAnalyzer::WindowsFilesAnalyzer(const std::string& imagePath, DatabaseManager* dbManager)
    : imagePath_(imagePath), dbManager_(dbManager) {
}

WindowsFilesAnalyzer::~WindowsFilesAnalyzer() {
}

bool WindowsFilesAnalyzer::initialize() {
    // initialize file extractor
    fileExtractor_ = std::make_unique<FileExtractor>(imagePath_, dbManager_->getDbPath());
    if (!fileExtractor_->initialize()) {
        std::cerr << "Failed to initialize FileExtractor for Windows analysis" << std::endl;
        AuditLog::instance().log("SYSTEM", "WINDOWS_INIT_FAILED", "Failed to initialize FileExtractor for: " + imagePath_);
        return false;
    }

    // Initialize windows analysis database path first (extractDir derives from it)
    if (outputDbPath_.empty()) {
        outputDbPath_ = imagePath_ + "_windows.db";
    }

    // Set default extract directory if not set: place it next to outputDbPath_
    // so extracted files live alongside the analysis database, not the process CWD.
    if (extractDir_.empty()) {
        namespace fs = std::filesystem;
        fs::path dbPath(outputDbPath_);
        fs::path dbParent = dbPath.parent_path();
        std::string stem = dbPath.stem().string();  // e.g. "win10_files"
        // Strip "_files" suffix to recover the image base name
        if (stem.size() > 6 && stem.substr(stem.size() - 6) == "_files") {
            stem = stem.substr(0, stem.size() - 6);
        }
        extractDir_ = (dbParent / (stem + "_extracted_files")).string();
        fs::create_directories(extractDir_);
    }

    windowsDb_ = std::make_unique<WindowsAnalysisDatabase>(outputDbPath_);
    if (!windowsDb_->initialize()) {
        std::cerr << "Failed to initialize WindowsAnalysisDatabase" << std::endl;
        AuditLog::instance().log("SYSTEM", "WINDOWS_DB_INIT_FAILED", "Failed to initialize Windows database: " + outputDbPath_);
        return false;
    }

    AuditLog::instance().log("SYSTEM", "WINDOWS_INIT", "Windows analyzer initialized for: " + imagePath_);
    return true;
}

void WindowsFilesAnalyzer::analyzeWindowsData() {
    std::cout << "Starting Windows forensic analysis..." << std::endl;
    std::cout << "  Extract directory: " << extractDir_ << std::endl;
    AuditLog::instance().log("SYSTEM", "WINDOWS_ANALYSIS_START", "Starting Windows analysis: " + imagePath_);

    // 1. Extract and analyze Registry Hives
    analyzeRegistryHives();

    // 2. Extract and analyze Event Logs
    analyzeEventLogs();

    // 3. Extract and analyze Prefetch files
    analyzePrefetchFiles();

    // 4. Extract and analyze LNK files
    analyzeLnkFiles();

    // 5. Extract and analyze Jump Lists
    analyzeJumpLists();

    // 6. Extract and analyze Recycle Bin
    analyzeRecycleBin();

    // 7. Extract and analyze NTFS Metadata (MFT)
    analyzeNTFSMetadata();

    // 8. Analyze User Profiles
    analyzeUserProfiles();

    // 9. Analyze Browser Artifacts
    analyzeBrowserData();

    // 10. Analyze System Configuration
    analyzeWindowsServices();
    analyzeScheduledTasks();
    analyzeAmcache();
    analyzeSRUM();

    // 11. MANDATORY: AI-powered LLM analysis of all Windows artifacts
    // This is NOT optional - all Windows system files MUST be analyzed by AI
    std::cout << "Running AI analysis on Windows artifacts..." << std::endl;
    AuditLog::instance().log("SYSTEM", "WINDOWS_LLM_ANALYSIS_START", "Starting LLM analysis for Windows artifacts: " + imagePath_);
    analyzeWithLLM();

    std::cout << "Windows forensic analysis completed." << std::endl;
    AuditLog::instance().log("SYSTEM", "WINDOWS_ANALYSIS_COMPLETE", "Windows analysis completed for: " + imagePath_);
}

void WindowsFilesAnalyzer::analyzeWithLLM() {
    // Skip condition 1: user explicitly requested --no-ai
    if (skipAI_) {
        std::cout << "AI analysis skipped (--no-ai)." << std::endl;
        AuditLog::instance().log("SYSTEM", "WINDOWS_LLM_SKIPPED", "AI analysis skipped via --no-ai flag");
        return;
    }

    // Skip condition 2: no API key configured → auto-skip (for offline/no-key environments)
    try {
        auto& configManager = forensics::ConfigManager::instance();
        if (!configManager.isLoaded()) {
            configManager.load();
        }
        if (configManager.getLLMApiKey().empty()) {
            std::cout << "AI analysis skipped (no LLM_API_KEY configured). "
                      << "Structured analysis results in windows_* tables are unaffected." << std::endl;
            AuditLog::instance().log("SYSTEM", "WINDOWS_LLM_SKIPPED",
                "No LLM_API_KEY configured, skipping LLM analysis");
            return;
        }
    } catch (const std::exception& e) {
        std::cout << "AI analysis skipped (config read failed: " << e.what() << ")." << std::endl;
        AuditLog::instance().log("SYSTEM", "WINDOWS_LLM_SKIPPED",
            "Config read failed, skipping LLM analysis: " + std::string(e.what()));
        return;
    }

    try {
        forensics::WindowsLLMAnalysisService llmService;
        if (!llmService.initialize()) {
            std::cerr << "Warning: Failed to initialize Windows LLM analysis service" << std::endl;
            AuditLog::instance().log("SYSTEM", "WINDOWS_LLM_INIT_FAILED", "Failed to initialize LLM service for: " + imagePath_);
            return;
        }

        // Configure analysis options for comprehensive coverage
        forensics::WindowsLLMAnalysisService::AnalysisOptions options;
        options.maxArtifacts = 10000;  // Analyze all artifacts
        options.includeRegistry = true;
        options.includeEventLogs = true;
        options.includePrefetch = true;
        options.includeLnk = true;
        options.includeJumpLists = true;
        options.includeBrowser = true;
        options.includeSystem = true;
        options.includeMFT = false;  // MFT can be very large, analyze selectively if needed

        // Progress callback for monitoring
        auto progressCallback = [](const std::string& artifactType, int current, int total, const std::string& details) {
            std::cout << "  [" << artifactType << "] " << current << "/" << total << " - " << details << std::endl;
        };

        int analyzed = llmService.analyzeWindowsArtifacts(outputDbPath_, options, progressCallback);
        std::cout << "AI analysis completed for " << analyzed << " Windows artifacts." << std::endl;
        AuditLog::instance().log("SYSTEM", "WINDOWS_LLM_ANALYSIS_COMPLETE",
            "LLM analysis completed for " + std::to_string(analyzed) + " artifacts from: " + imagePath_);

    } catch (const std::exception& e) {
        std::cerr << "Error during Windows LLM analysis: " << e.what() << std::endl;
        AuditLog::instance().log("SYSTEM", "WINDOWS_LLM_ANALYSIS_ERROR",
            "LLM analysis error for " + imagePath_ + ": " + e.what());
    }
}

bool WindowsFilesAnalyzer::extractWindowsSystemFiles(const std::string& outputDir) {
    // This method is a helper to extract key system files if needed in bulk
    // For now we implement on-demand extraction in specific analysis methods
    return true;
}

std::vector<FileRecord> WindowsFilesAnalyzer::queryWindowsSystemFiles() {
    // Helper to query all relevant system files
    if (!dbManager_) return {};
    return {}; 
}

std::vector<FileRecord> WindowsFilesAnalyzer::queryFilesByPattern(const std::string& pathPattern) {
    if (!dbManager_) return {};
    
    std::vector<FileRecord> results;
    sqlite3* db = dbManager_->getDb();
    if (!db) return results;
    
    // Use parameterized query to prevent SQL injection
    const char* query = "SELECT inode, name, path, size, mtime, atime, crtime, type, is_deleted, md5, "
                        "COALESCE(partition_num, 0) "
                        "FROM files WHERE path LIKE ? AND is_deleted=0";
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(db) << std::endl;
        return results;
    }

    // Bind the pattern parameter (index 1)
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
        record.partitionNum = sqlite3_column_int(stmt, 10);

        results.push_back(record);
    }

    sqlite3_finalize(stmt);
    return results;
}

std::vector<FileRecord> WindowsFilesAnalyzer::queryFilesByCategory(const std::string& category) {
    if (!dbManager_) return {};

    std::vector<FileRecord> results;
    sqlite3* db = dbManager_->getDb();
    if (!db) return results;

    // Use parameterized query to prevent SQL injection
    const char* query = "SELECT inode, name, path, size, mtime, atime, crtime, type, is_deleted, md5, "
                        "COALESCE(partition_num, 0) "
                        "FROM files WHERE category = ?";
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Error preparing query: " << sqlite3_errmsg(db) << std::endl;
        return results;
    }

    // Bind the category parameter (index 1)
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

bool WindowsFilesAnalyzer::extractFileToPath(int64_t inode, const std::string& outputPath, int partitionNum) {
    if (!fileExtractor_) return false;
    return fileExtractor_->extractFileByInode(inode, outputPath, partitionNum);
}

std::string WindowsFilesAnalyzer::getExtractPath(const std::string& relativePath) {
    fs::path p(extractDir_);
    p /= relativePath;
    
    // Create parent directory if needed
    if (!p.parent_path().empty()) {
        fs::create_directories(p.parent_path());
    }
    
    return p.string();
}

// Utility implementations

bool WindowsFilesAnalyzer::isWindowsPath(const std::string& path) {
    // Simple check if path looks like a Windows path structure
    // e.g., Windows/System32, Users/, Program Files
    std::string lowerPath = path;
    std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(), ::tolower);
    
    if (lowerPath.find("windows/") != std::string::npos || 
        lowerPath.find("users/") != std::string::npos ||
        lowerPath.find("program files") != std::string::npos ||
        lowerPath.find("programdata") != std::string::npos) {
        return true;
    }
    return false;
}

std::string WindowsFilesAnalyzer::normalizeWindowsPath(const std::string& path) {
    // Convert Windows-style paths to Unix-style for consistency
    std::string normalized = path;
    
    // Replace backslashes with forward slashes
    std::replace(normalized.begin(), normalized.end(), '\\', '/');
    
    // Remove drive letter if present (e.g., "C:/" -> "/")
    if (normalized.length() >= 2 && std::isalpha(normalized[0]) && normalized[1] == ':') {
        normalized = normalized.substr(2);
    }
    
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

uint16_t WindowsFilesAnalyzer::readUInt16LE(const char* data) {
    return *reinterpret_cast<const uint16_t*>(data);
}

uint32_t WindowsFilesAnalyzer::readUInt32LE(const char* data) {
    return *reinterpret_cast<const uint32_t*>(data);
}

uint64_t WindowsFilesAnalyzer::readUInt64LE(const char* data) {
    return *reinterpret_cast<const uint64_t*>(data);
}

// Convert Windows FILETIME (100-nanosecond intervals since January 1, 1601 UTC)
// to Unix Timestamp (seconds since January 1, 1970 UTC)
int64_t WindowsFilesAnalyzer::filetimeToUnixTime(uint64_t filetime) {
    if (filetime == 0) return 0;
    
    // Windows filetime starts at 1601-01-01
    // Unix epoch starts at 1970-01-01
    // Difference is 11644473600 seconds
    const uint64_t TICKS_PER_SECOND = 10000000;
    const uint64_t EPOCH_DIFFERENCE = 11644473600ULL;
    
    return (filetime / TICKS_PER_SECOND) - EPOCH_DIFFERENCE;
}

std::string WindowsFilesAnalyzer::readNullTerminatedString(const char* data, size_t maxLen) {
    size_t len = 0;
    while (len < maxLen && data[len] != 0) {
        len++;
    }
    return std::string(data, len);
}

std::string WindowsFilesAnalyzer::readUTF16LEString(const char* data, size_t maxLen) {
    // This is a simplified conversion that assumes ASCII compatible chars
    // For proper Unicode support in C++, we would need <codecvt> or external lib
    // but <codecvt> is deprecated in C++17.
    // For forensic purposes, capturing the ASCII part is often sufficient for system paths
    
    std::string result;
    for (size_t i = 0; i < maxLen; i += 2) {
        char c = data[i];
        if (c == 0 && data[i+1] == 0) break; // null terminator
        
        if (data[i+1] == 0 && c > 0 && c < 127) {
            result += c;
        } else {
            result += '?'; // Replace non-ASCII with ?
        }
    }
    return result;
}
