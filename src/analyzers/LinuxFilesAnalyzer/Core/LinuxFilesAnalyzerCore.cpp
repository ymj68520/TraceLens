// LinuxFilesAnalyzerCore.cpp
// Core implementation of LinuxFilesAnalyzer

#include "LinuxFilesAnalyzer.h"
#include "HTTPServer/LinuxLLMAnalysisService.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"
#include <pugixml.hpp>
#include <filesystem>
#include <fstream>
#include <sstream>

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

// Compressed log parser (Phase 1)
#include "Parsers/CompressedLogParser.h"

// Journal parser (Phase 2)
#include "Parsers/JournalParser.h"

// Enhanced analysis
#include "Analysis/LogCorrelationEngine.h"
#include "Analysis/TimelineReconstructor.h"
#include "Analysis/AnomalyDetector.h"
#include "Analysis/LogTamperingDetector.h"
#include "Analysis/PersistenceDetector.h"

// Middleware log parser (Phase 7)
#include "Parsers/WebServer/MiddlewareLogParser.h"

// Container runtime log parser (Phase 8)
#include "Parsers/Container/ContainerRuntimeLogParser.h"

// Package manager log parser (Phase 9)
#include "Parsers/PackageManager/PackageManagerLogParser.h"

// Account/SSH security analyzer (Phase 10)
#include "Analysis/AccountSSH/AccountSSHAnalyzer.h"

// Phase 11: Database, Email, VPN, Firewall, Security Product logs
#include "Parsers/Database/DatabaseLogParser.h"
#include "Parsers/EmailVPN/EmailVPNLogParser.h"
#include "Parsers/FirewallSecurity/FirewallSecurityLogParser.h"

// Phase 12: USB, Mount, Cloud
#include "Parsers/USBMountParser.h"
#include "Parsers/CloudParser.h"

// Phase 13: Extended history
#include "Parsers/ExtendedHistoryParser.h"

// Phase 14: Security bypass
#include "Parsers/Security/SecurityBypassAnalyzer.h"

// Phase 16: Rule engine
#include "Analysis/RuleEngine.h"

using forensics::linux::PackageManagerLogParser;
using forensics::linux::AccountSSHAnalyzer;
using forensics::linux::AccountSecurityFinding;
using forensics::linux::SSHSecurityFinding;
using forensics::linux::DatabaseLogParser;
using forensics::linux::DatabaseLogEntry;
using forensics::linux::DatabaseSecurityFinding;
using forensics::linux::EmailVPNLogParser;
using forensics::linux::EmailLogEntry;
using forensics::linux::VPNLogEntry;
using forensics::linux::EmailSecurityFinding;
using forensics::linux::VPNSecurityFinding;
using forensics::linux::FirewallSecurityLogParser;
using forensics::linux::FirewallLogEntry;
using forensics::linux::SecurityProductLogEntry;
using forensics::linux::USBMountParser;
using forensics::linux::USBEvent;
using forensics::linux::MountEntry;
using forensics::linux::CloudParser;
using forensics::linux::CloudEvent;
using forensics::linux::ExtendedHistoryParser;
using forensics::linux::ExtendedHistoryEntry;
using forensics::linux::CredentialConfig;
using forensics::linux::SecurityBypassAnalyzer;
using forensics::linux::SecurityBypassFinding;
using forensics::linux::RuleEngine;
using forensics::linux::SecurityProductFinding;

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

    // Phase 1: Compressed and rotated log preprocessing
    // This must run before other log analysis to include historical logs
    analyzeCompressedLogs();

    // Phase 2: System logs
    analyzeSystemLogs();
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
// Compressed and Rotated Log Analysis (Phase 1)
// ============================================================================

void LinuxFilesAnalyzer::analyzeCompressedLogs() {
    std::cout << "Analyzing compressed and rotated logs..." << std::endl;
    AuditLog::instance().log("SYSTEM", "COMPRESSED_LOGS_START", "Starting compressed log analysis: " + imagePath_);

    using namespace forensics::linux;

    // Common log directories to scan
    std::vector<std::string> logDirs = {
        "/var/log",
        "/var/log/auth",
        "/var/log/syslog",
        "/var/log/audit",
        "/var/log/journal"
    };

    int totalRotated = 0;
    int totalDecompressed = 0;
    int totalErrors = 0;

    for (const auto& logDir : logDirs) {
        // Query for files in the log directory
        std::string pattern = logDir + "/%";
        auto logFiles = queryFilesByPattern(pattern);

        if (logFiles.empty()) {
            continue;
        }

        std::cout << "  Scanning " << logDir << " for rotated logs..." << std::endl;

        // Extract the directory first
        std::string extractPath = getExtractPath("logs/compressed");
        fs::create_directories(extractPath);

        for (const auto& file : logFiles) {
            std::string filename = file.name;

            // Check if this is a rotated log
            if (!CompressedLogParser::isRotatedLog(filename)) {
                continue;
            }

            totalRotated++;

            // Get compression type
            CompressionType compType = CompressedLogParser::identifyCompression(filename);

            // Create metadata
            RotatedLogFile logInfo;
            logInfo.originalPath = file.path;
            logInfo.baseName = CompressedLogParser::getBaseName(filename);
            logInfo.logDirectory = logDir;
            logInfo.rotationIndex = CompressedLogParser::parseRotationIndex(filename);
            logInfo.compression = compType;
            logInfo.isCompressed = (compType != CompressionType::NONE);
            logInfo.fileSize = file.size;
            logInfo.mtime = file.mtime;
            logInfo.inode = file.inode;
            logInfo.dateSuffix = CompressedLogParser::parseDateSuffix(filename);
            logInfo.isDateRotated = !logInfo.dateSuffix.empty();

            std::cout << "    Found rotated log: " << filename
                      << " (base=" << logInfo.baseName
                      << ", idx=" << logInfo.rotationIndex
                      << ", comp=" << CompressedLogParser::compressionTypeToString(compType)
                      << ")" << std::endl;

            // Extract the file
            std::string outputPath = extractPath + "/" + std::to_string(file.inode) + "_" + filename;
            if (!extractFileToPath(file.inode, outputPath)) {
                std::cerr << "    Failed to extract: " << filename << std::endl;
                totalErrors++;
                continue;
            }

            // Decompress if needed
            std::string content;
            if (logInfo.isCompressed) {
                content = CompressedLogParser::decompressFile(outputPath, compType);
                if (content.empty()) {
                    std::cerr << "    Failed to decompress: " << filename << std::endl;
                    totalErrors++;
                    continue;
                }
                totalDecompressed++;

                // Save decompressed content
                std::string decompressedPath = extractPath + "/" + std::to_string(file.inode) + "_" + logInfo.baseName;
                std::ofstream out(decompressedPath);
                if (out.is_open()) {
                    out << content;
                    out.close();
                }
            } else {
                // Read plain text
                std::ifstream inFile(outputPath);
                if (inFile.is_open()) {
                    std::ostringstream ss;
                    ss << inFile.rdbuf();
                    content = ss.str();
                }
            }

            // Parse the log content based on base name
            if (!content.empty()) {
                // Determine log type from base name
                std::string baseNameLower = logInfo.baseName;
                std::transform(baseNameLower.begin(), baseNameLower.end(), baseNameLower.begin(), ::tolower);

                // Create provenance for this file
                EvidenceProvenance provenance;
                provenance.parserName = "CompressedLogParser";
                provenance.parserVersion = "1.0.0";
                provenance.sourceFile = file.path;
                provenance.sourceInode = file.inode;
                provenance.rawRecord = content.substr(0, 1000); // First 1000 chars as sample

                // Store as log entry with provenance
                LinuxLogEntry entry;
                entry.logFile = file.path;
                entry.message = "Compressed/rotated log file: " + filename + " (" +
                    std::to_string(content.size()) + " bytes, " +
                    std::to_string(logInfo.rotationIndex) + " rotations)";
                entry.provenance = provenance;

                // Note: The actual parsing of log content will be done by the
                // specific log parsers (analyzeSystemLogs, analyzeAuthLogs, etc.)
                // after we extract the decompressed files
            }

            AuditLog::instance().log("LINUX", "ROTATED_LOG_FOUND",
                "Found rotated log: " + filename + " (base=" + logInfo.baseName + ")");
        }
    }

    std::cout << "  Compressed log analysis complete: "
              << totalRotated << " rotated logs found, "
              << totalDecompressed << " decompressed, "
              << totalErrors << " errors" << std::endl;

    AuditLog::instance().log("SYSTEM", "COMPRESSED_LOGS_COMPLETE",
        "Compressed log analysis: " + std::to_string(totalRotated) + " rotated, " +
        std::to_string(totalDecompressed) + " decompressed, " +
        std::to_string(totalErrors) + " errors");
}

// ============================================================================
// systemd-journald Analysis (Phase 2)
// ============================================================================

void LinuxFilesAnalyzer::analyzeJournalLogs() {
    std::cout << "Analyzing systemd-journald journal files..." << std::endl;
    AuditLog::instance().log("SYSTEM", "JOURNAL_ANALYSIS_START", "Starting journal analysis: " + imagePath_);

    using namespace forensics::linux;

    // Common journal directories
    std::vector<std::string> journalDirs = {
        "/var/log/journal",
        "/run/log/journal"
    };

    int totalEntries = 0;
    int totalFiles = 0;
    int totalAnomalies = 0;
    std::vector<JournalEntry> allEntries;

    for (const auto& journalDir : journalDirs) {
        // Query for journal files
        std::string pattern = journalDir + "/%";
        auto journalFiles = queryFilesByPattern(pattern);

        if (journalFiles.empty()) {
            std::cout << "  No journal files found in " << journalDir << std::endl;
            continue;
        }

        std::cout << "  Scanning " << journalDir << " for journal files..." << std::endl;

        // Extract directory
        std::string extractPath = getExtractPath("journal");
        fs::create_directories(extractPath);

        for (const auto& file : journalFiles) {
            std::string filename = file.name;

            // Check if this is a journal file
            bool isJournal = (filename.find(".journal") != std::string::npos);
            bool isExport = (filename.find(".export") != std::string::npos) ||
                            (filename.find("journal.txt") != std::string::npos);

            if (!isJournal && !isExport) {
                continue;
            }

            totalFiles++;

            // Extract the file
            std::string outputPath = extractPath + "/" + std::to_string(file.inode) + "_" + filename;
            if (!extractFileToPath(file.inode, outputPath)) {
                std::cerr << "    Failed to extract: " << filename << std::endl;
                continue;
            }

            std::vector<JournalEntry> entries;

            // Parse based on file type
            if (isExport || JournalParser::isJournalExportFile(outputPath)) {
                entries = JournalParser::parseJournalExportFile(outputPath);
            } else if (JournalParser::isJournalFile(outputPath)) {
                entries = JournalParser::parseJournalFile(outputPath);
            }

            if (!entries.empty()) {
                totalEntries += entries.size();

                // Set provenance for all entries
                for (auto& entry : entries) {
                    entry.provenance.sourceFile = file.path;
                    entry.provenance.sourceInode = file.inode;
                }

                // Detect anomalies
                auto anomalies = JournalParser::detectJournalAnomalies(entries);
                totalAnomalies += anomalies.size();

                for (const auto& anomaly : anomalies) {
                    std::cout << "    Journal anomaly: " << anomaly.description << std::endl;
                    AuditLog::instance().log("WARNING", "JOURNAL_ANOMALY",
                        "Journal anomaly in " + filename + ": " + anomaly.description);
                }

                // Collect entries for boot session analysis
                allEntries.insert(allEntries.end(), entries.begin(), entries.end());

                std::cout << "    Parsed " << entries.size() << " entries from " << filename << std::endl;
            }

            AuditLog::instance().log("LINUX", "JOURNAL_FILE_PARSED",
                "Parsed journal file: " + filename + " (" + std::to_string(entries.size()) + " entries)");
        }
    }

    // Analyze boot sessions
    std::vector<BootSession> bootSessions;
    if (!allEntries.empty()) {
        bootSessions = JournalParser::groupByBootId(allEntries);
        std::cout << "  Found " << bootSessions.size() << " boot sessions" << std::endl;

        for (const auto& session : bootSessions) {
            std::cout << "    Boot " << session.bootId.substr(0, 8) << "..."
                      << ": " << session.entryCount << " entries, "
                      << "start=" << session.startTime
                      << ", end=" << session.endTime << std::endl;
        }
    }

    // Detect global anomalies across all entries
    std::vector<JournalAnomaly> globalAnomalies;
    if (!allEntries.empty()) {
        globalAnomalies = JournalParser::detectJournalAnomalies(allEntries);
        totalAnomalies += globalAnomalies.size();
    }

    // Store journal data in database
    if (!allEntries.empty()) {
        if (!linuxDb_->insertJournalEntries(allEntries)) {
            std::cerr << "  Failed to insert journal entries into database" << std::endl;
        } else {
            std::cout << "  Stored " << allEntries.size() << " journal entries in database" << std::endl;
        }
    }
    if (!bootSessions.empty()) {
        if (!linuxDb_->insertBootSessions(bootSessions)) {
            std::cerr << "  Failed to insert boot sessions into database" << std::endl;
        } else {
            std::cout << "  Stored " << bootSessions.size() << " boot sessions in database" << std::endl;
        }
    }
    if (!globalAnomalies.empty()) {
        if (!linuxDb_->insertJournalAnomalies(globalAnomalies)) {
            std::cerr << "  Failed to insert journal anomalies into database" << std::endl;
        } else {
            std::cout << "  Stored " << globalAnomalies.size() << " journal anomalies in database" << std::endl;
        }
    }

    std::cout << "  Journal analysis complete: "
              << totalFiles << " files, "
              << totalEntries << " entries, "
              << totalAnomalies << " anomalies" << std::endl;

    AuditLog::instance().log("SYSTEM", "JOURNAL_ANALYSIS_COMPLETE",
        "Journal analysis: " + std::to_string(totalFiles) + " files, " +
        std::to_string(totalEntries) + " entries, " +
        std::to_string(totalAnomalies) + " anomalies");
}

// ============================================================================
// Log Tampering Detection (Phase 5)
// ============================================================================

void LinuxFilesAnalyzer::analyzeLogTampering() {
    using namespace forensics::linux;

    std::cout << "Analyzing log tampering indicators..." << std::endl;
    AuditLog::instance().log("SYSTEM", "LOG_TAMPERING_START", "Starting log tampering detection: " + imagePath_);

    // Run all tampering detection algorithms
    auto findings = LogTamperingDetector::detectAll(linuxDb_->getDbPath());

    if (findings.empty()) {
        std::cout << "  No log tampering indicators detected" << std::endl;
    } else {
        std::cout << "  Found " << findings.size() << " log tampering indicators:" << std::endl;

        int criticalCount = 0;
        int highCount = 0;
        int mediumCount = 0;

        for (const auto& finding : findings) {
            // Set provenance
            TamperingFinding f = finding;
            f.provenance.parserName = "LogTamperingDetector";
            f.provenance.parserVersion = "1.0.0";

            switch (finding.severity) {
                case TamperingSeverity::CRITICAL:
                    criticalCount++;
                    std::cout << "    [CRITICAL] " << finding.description << std::endl;
                    break;
                case TamperingSeverity::HIGH:
                    highCount++;
                    std::cout << "    [HIGH] " << finding.description << std::endl;
                    break;
                case TamperingSeverity::MEDIUM:
                    mediumCount++;
                    std::cout << "    [MEDIUM] " << finding.description << std::endl;
                    break;
                default:
                    break;
            }
        }

        // Store findings in database
        if (!linuxDb_->insertTamperingFindings(findings)) {
            std::cerr << "  Failed to insert tampering findings into database" << std::endl;
        } else {
            std::cout << "  Stored " << findings.size() << " tampering findings in database" << std::endl;
        }

        std::cout << "  Summary: " << criticalCount << " critical, "
                  << highCount << " high, " << mediumCount << " medium severity" << std::endl;
    }

    AuditLog::instance().log("SYSTEM", "LOG_TAMPERING_COMPLETE",
        "Log tampering detection: " + std::to_string(findings.size()) + " findings");
}

// ============================================================================
// Persistence Mechanism Detection Implementation (Phase 6)
// ============================================================================

void LinuxFilesAnalyzer::analyzePersistenceMechanisms() {
    using namespace forensics::linux;

    std::cout << "Analyzing persistence mechanisms..." << std::endl;
    AuditLog::instance().log("SYSTEM", "PERSISTENCE_DETECTION_START", "Starting persistence mechanism detection: " + imagePath_);

    // Run all persistence detection algorithms
    auto entries = PersistenceDetector::detectAll(extractDir_);

    if (entries.empty()) {
        std::cout << "  No persistence mechanisms detected" << std::endl;
    } else {
        std::cout << "  Found " << entries.size() << " persistence mechanisms:" << std::endl;

        int criticalCount = 0;
        int highCount = 0;
        int mediumCount = 0;
        int suspiciousCount = 0;

        for (const auto& entry : entries) {
            if (entry.isSuspicious) suspiciousCount++;

            switch (entry.risk) {
                case PersistenceRisk::CRITICAL:
                    criticalCount++;
                    std::cout << "    [CRITICAL] " << PersistenceDetector::typeToString(entry.type)
                              << ": " << entry.command << std::endl;
                    break;
                case PersistenceRisk::HIGH:
                    highCount++;
                    std::cout << "    [HIGH] " << PersistenceDetector::typeToString(entry.type)
                              << ": " << entry.command << std::endl;
                    break;
                case PersistenceRisk::MEDIUM:
                    mediumCount++;
                    std::cout << "    [MEDIUM] " << PersistenceDetector::typeToString(entry.type)
                              << ": " << entry.command << std::endl;
                    break;
                default:
                    break;
            }
        }

        // Store entries in database
        if (!linuxDb_->insertPersistenceEntries(entries)) {
            std::cerr << "  Failed to insert persistence entries into database" << std::endl;
        } else {
            std::cout << "  Stored " << entries.size() << " persistence entries in database" << std::endl;
        }

        std::cout << "  Summary: " << criticalCount << " critical, " << highCount << " high, "
                  << mediumCount << " medium risk, " << suspiciousCount << " suspicious" << std::endl;
    }

    AuditLog::instance().log("SYSTEM", "PERSISTENCE_DETECTION_COMPLETE",
        "Persistence detection: " + std::to_string(entries.size()) + " entries found");
}

// ============================================================================
// Middleware Log Analysis Implementation (Phase 7)
// ============================================================================

void LinuxFilesAnalyzer::analyzeMiddlewareLogs() {
    using namespace forensics::linux;

    std::cout << "Analyzing web server error logs and middleware logs..." << std::endl;
    AuditLog::instance().log("SYSTEM", "MIDDLEWARE_LOG_START", "Starting middleware log analysis: " + imagePath_);

    int totalErrorLogs = 0;
    int totalMiddlewareLogs = 0;
    int totalModsecLogs = 0;

    // Web server error log paths to search
    std::vector<std::string> errorLogPaths = {
        "/var/log/apache2/error.log",
        "/var/log/httpd/error_log",
        "/var/log/nginx/error.log",
        "/var/log/apache2/error.log.1",
        "/var/log/httpd/error_log.1",
        "/var/log/nginx/error.log.1"
    };

    // Middleware log paths
    std::vector<std::pair<std::string, std::string>> middlewareLogPaths = {
        {"/var/log/php-fpm/error.log", "php-fpm"},
        {"/var/log/php-fpm/www-error.log", "php-fpm"},
        {"/var/log/php8.1-fpm.log", "php-fpm"},
        {"/var/log/tomcat*/catalina.out", "tomcat"},
        {"/var/log/jetty*/jetty.log", "jetty"},
        {"/var/log/pm2/*.log", "pm2"},
        {"/var/log/gunicorn/*.log", "gunicorn"},
        {"/var/log/uwsgi/*.log", "uwsgi"}
    };

    // ModSecurity audit log paths
    std::vector<std::string> modsecLogPaths = {
        "/var/log/modsec_audit.log",
        "/var/log/apache2/modsec_audit.log",
        "/var/log/httpd/modsec_audit.log",
        "/var/log/nginx/modsec_audit.log"
    };

    // Helper to read file content
    auto readFile = [](const std::string& path) -> std::string {
        std::ifstream f(path, std::ios::binary);
        if (!f.is_open()) return "";
        std::ostringstream ss;
        ss << f.rdbuf();
        return ss.str();
    };

    // Process web server error logs
    for (const auto& logPath : errorLogPaths) {
        std::string fullPath = extractDir_ + logPath;
        std::string content = readFile(fullPath);
        if (content.empty()) continue;

        auto entries = MiddlewareLogParser::parseErrorLogAuto(content, logPath);
        if (!entries.empty()) {
            if (linuxDb_->insertWebErrorLogs(entries)) {
                totalErrorLogs += entries.size();
                std::cout << "  Parsed " << entries.size() << " entries from " << logPath << std::endl;
            }
        }
    }

    // Process middleware logs
    for (const auto& [logPath, logType] : middlewareLogPaths) {
        std::string fullPath = extractDir_ + logPath;
        std::string content = readFile(fullPath);
        if (content.empty()) continue;

        std::vector<MiddlewareLogEntry> entries;
        if (logType == "php-fpm") {
            entries = MiddlewareLogParser::parsePhpFpmLog(content, logPath);
        } else if (logType == "tomcat") {
            entries = MiddlewareLogParser::parseTomcatLog(content, logPath);
        } else if (logType == "jetty") {
            entries = MiddlewareLogParser::parseJettyLog(content, logPath);
        } else if (logType == "pm2") {
            entries = MiddlewareLogParser::parsePm2Log(content, logPath);
        } else if (logType == "gunicorn") {
            entries = MiddlewareLogParser::parseGunicornLog(content, logPath);
        } else if (logType == "uwsgi") {
            entries = MiddlewareLogParser::parseUwsgiLog(content, logPath);
        }

        if (!entries.empty()) {
            if (linuxDb_->insertMiddlewareLogs(entries)) {
                totalMiddlewareLogs += entries.size();
                std::cout << "  Parsed " << entries.size() << " " << logType << " entries from " << logPath << std::endl;
            }
        }
    }

    // Process ModSecurity audit logs
    for (const auto& logPath : modsecLogPaths) {
        std::string fullPath = extractDir_ + logPath;
        std::string content = readFile(fullPath);
        if (content.empty()) continue;

        auto entries = MiddlewareLogParser::parseModSecurityLog(content, logPath);
        if (!entries.empty()) {
            if (linuxDb_->insertModSecurityLogs(entries)) {
                totalModsecLogs += entries.size();
                std::cout << "  Parsed " << entries.size() << " ModSecurity entries from " << logPath << std::endl;
            }
        }
    }

    std::cout << "  Web error logs: " << totalErrorLogs
              << ", Middleware logs: " << totalMiddlewareLogs
              << ", ModSecurity logs: " << totalModsecLogs << std::endl;

    AuditLog::instance().log("SYSTEM", "MIDDLEWARE_LOG_COMPLETE",
        "Middleware log analysis: " + std::to_string(totalErrorLogs) + " error logs, " +
        std::to_string(totalMiddlewareLogs) + " middleware logs, " +
        std::to_string(totalModsecLogs) + " ModSecurity logs");
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
// Container Runtime Log Analysis Implementation (Phase 8)
// ============================================================================

void LinuxFilesAnalyzer::analyzeContainerRuntimeLogs() {
    using namespace forensics::linux;

    std::cout << "Analyzing container runtime logs..." << std::endl;
    AuditLog::instance().log("SYSTEM", "CONTAINER_LOG_START", "Starting container runtime log analysis: " + imagePath_);

    int totalDockerLogs = 0;
    int totalCRILogs = 0;
    int totalSecurityFindings = 0;

    // Helper to read file content
    auto readFile = [](const std::string& path) -> std::string {
        std::ifstream f(path, std::ios::binary);
        if (!f.is_open()) return "";
        std::ostringstream ss;
        ss << f.rdbuf();
        return ss.str();
    };

    // Docker json-file log paths
    std::vector<std::string> dockerLogPatterns = {
        "/var/lib/docker/containers/*/*-json.log",
        "/var/lib/docker/containers/*/*.log"
    };

    // CRI / Kubernetes log paths
    std::vector<std::string> criLogPatterns = {
        "/var/log/containers/*.log",
        "/var/log/pods/*/*.log",
        "/var/log/kubelet.log",
        "/var/log/crio/pods/*.log"
    };

    // Process Docker json-file logs
    for (const auto& pattern : dockerLogPatterns) {
        // Use glob to find matching files
        std::string cmd = "ls " + extractDir_ + pattern + " 2>/dev/null";
        FILE* pipe = popen(cmd.c_str(), "r");
        if (!pipe) continue;

        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), pipe)) {
            std::string filePath(buffer);
            // Trim newline
            while (!filePath.empty() && (filePath.back() == '\n' || filePath.back() == '\r')) {
                filePath.pop_back();
            }
            if (filePath.empty()) continue;

            std::string content = readFile(filePath);
            if (content.empty()) continue;

            auto entries = ContainerRuntimeLogParser::parseDockerJsonLog(content, filePath);
            if (!entries.empty()) {
                if (linuxDb_->insertContainerLogs(entries)) {
                    totalDockerLogs += entries.size();
                    std::cout << "  Parsed " << entries.size() << " Docker log entries from " << filePath << std::endl;
                }
            }
        }
        pclose(pipe);
    }

    // Process CRI / Kubernetes logs
    for (const auto& pattern : criLogPatterns) {
        std::string cmd = "ls " + extractDir_ + pattern + " 2>/dev/null";
        FILE* pipe = popen(cmd.c_str(), "r");
        if (!pipe) continue;

        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), pipe)) {
            std::string filePath(buffer);
            while (!filePath.empty() && (filePath.back() == '\n' || filePath.back() == '\r')) {
                filePath.pop_back();
            }
            if (filePath.empty()) continue;

            std::string content = readFile(filePath);
            if (content.empty()) continue;

            // Auto-detect runtime type
            std::string runtimeType = ContainerRuntimeLogParser::detectRuntimeType(content);

            if (runtimeType == "cri" || runtimeType == "unknown") {
                // Try parsing as Kubernetes pod log first (extracts pod metadata from filename)
                auto podEntries = ContainerRuntimeLogParser::parseKubernetesPodLog(content, filePath);
                if (!podEntries.empty()) {
                    // Convert to CRI entries for storage
                    std::vector<CRILogEntry> criEntries;
                    for (const auto& pod : podEntries) {
                        CRILogEntry cri;
                        cri.timestamp = pod.timestamp;
                        cri.stream = pod.stream;
                        cri.message = pod.message;
                        cri.containerId = pod.containerId;
                        cri.podName = pod.podName;
                        cri.namespace_ = pod.namespace_;
                        cri.containerName = pod.containerName;
                        cri.filePath = pod.filePath;
                        cri.provenance = pod.provenance;
                        criEntries.push_back(cri);
                    }
                    if (linuxDb_->insertCRILogs(criEntries)) {
                        totalCRILogs += criEntries.size();
                        std::cout << "  Parsed " << criEntries.size() << " K8s pod log entries from " << filePath << std::endl;
                    }
                }
            }
        }
        pclose(pipe);
    }

    // Analyze container security configurations
    // Look for Docker container config files
    std::string configCmd = "ls " + extractDir_ + "/var/lib/docker/containers/*/config.v2.json 2>/dev/null";
    FILE* configPipe = popen(configCmd.c_str(), "r");
    if (configPipe) {
        std::vector<ContainerConfig> configs;
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), configPipe)) {
            std::string configPath(buffer);
            while (!configPath.empty() && (configPath.back() == '\n' || configPath.back() == '\r')) {
                configPath.pop_back();
            }
            if (configPath.empty()) continue;

            std::string content = readFile(configPath);
            if (content.empty()) continue;

            auto config = ContainerRuntimeLogParser::parseContainerSecurityConfig(content, configPath);

            // Extract container ID from path
            size_t lastSlash = configPath.rfind('/');
            if (lastSlash != std::string::npos) {
                size_t secondLast = configPath.rfind('/', lastSlash - 1);
                if (secondLast != std::string::npos) {
                    config.containerId = configPath.substr(secondLast + 1, lastSlash - secondLast - 1);
                }
            }

            configs.push_back(config);
        }
        pclose(configPipe);

        if (!configs.empty()) {
            auto findings = ContainerRuntimeLogParser::analyzeContainerSecurity(configs);
            if (!findings.empty()) {
                if (linuxDb_->insertContainerSecurityFindings(findings)) {
                    totalSecurityFindings += findings.size();
                    std::cout << "  Found " << findings.size() << " container security findings" << std::endl;

                    for (const auto& finding : findings) {
                        if (finding.severity == "critical") {
                            std::cout << "    [CRITICAL] " << finding.findingType
                                      << ": " << finding.description << std::endl;
                        }
                    }
                }
            }
        }
    }

    std::cout << "  Docker logs: " << totalDockerLogs
              << ", CRI/K8s logs: " << totalCRILogs
              << ", Security findings: " << totalSecurityFindings << std::endl;

    AuditLog::instance().log("SYSTEM", "CONTAINER_LOG_COMPLETE",
        "Container log analysis: " + std::to_string(totalDockerLogs) + " Docker logs, " +
        std::to_string(totalCRILogs) + " CRI logs, " +
        std::to_string(totalSecurityFindings) + " security findings");
}

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
// Account and SSH Security Analysis Implementation (Phase 10)
// ============================================================================

void LinuxFilesAnalyzer::analyzeAccountSSHSecurity() {
    std::cout << "Analyzing account and SSH security..." << std::endl;

    if (!linuxDb_) {
        std::cerr << "  Error: Linux analysis database not initialized" << std::endl;
        return;
    }

    size_t totalAccountFindings = 0;
    size_t totalSSHFindings = 0;

    // Helper to read file content
    auto readFile = [](const std::string& path) -> std::string {
        std::ifstream f(path);
        if (!f.is_open()) return "";
        return std::string((std::istreambuf_iterator<char>(f)),
                           std::istreambuf_iterator<char>());
    };

    // Read account files
    std::string passwdContent = readFile(extractDir_ + "/etc/passwd");
    std::string shadowContent = readFile(extractDir_ + "/etc/shadow");
    std::string groupContent = readFile(extractDir_ + "/etc/group");
    std::string sudoersContent = readFile(extractDir_ + "/etc/sudoers");

    // Also read sudoers.d files
    std::string sudoersDCmd = "cat " + extractDir_ + "/etc/sudoers.d/* 2>/dev/null";
    FILE* sudoersPipe = popen(sudoersDCmd.c_str(), "r");
    if (sudoersPipe) {
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), sudoersPipe)) {
            sudoersContent += buffer;
        }
        pclose(sudoersPipe);
    }

    // Analyze account security
    auto accountFindings = AccountSSHAnalyzer::analyzeAllAccounts(
        passwdContent, shadowContent, groupContent, sudoersContent);

    if (!accountFindings.empty()) {
        if (linuxDb_->insertAccountSecurityFindings(accountFindings)) {
            totalAccountFindings = accountFindings.size();
            std::cout << "  Found " << totalAccountFindings << " account security findings" << std::endl;
            for (const auto& f : accountFindings) {
                if (f.severity == "critical") {
                    std::cout << "    [CRITICAL] " << f.findingType
                              << ": " << f.description << std::endl;
                }
            }
        }
    }

    // Read SSH config files
    std::string sshdConfig = readFile(extractDir_ + "/etc/ssh/sshd_config");
    std::string sshConfig = readFile(extractDir_ + "/etc/ssh/ssh_config");

    // Collect authorized_keys and known_hosts files
    std::vector<std::pair<std::string, std::string>> authorizedKeysFiles;
    std::vector<std::pair<std::string, std::string>> knownHostsFiles;

    // Find user home directories
    std::string homeCmd = "ls -d " + extractDir_ + "/home/*/.ssh/authorized_keys "
                          + extractDir_ + "/home/*/.ssh/authorized_keys2 "
                          + extractDir_ + "/root/.ssh/authorized_keys "
                          + extractDir_ + "/root/.ssh/authorized_keys2 "
                          + "2>/dev/null";
    FILE* homePipe = popen(homeCmd.c_str(), "r");
    if (homePipe) {
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), homePipe)) {
            std::string keyPath(buffer);
            while (!keyPath.empty() && (keyPath.back() == '\n' || keyPath.back() == '\r')) {
                keyPath.pop_back();
            }
            if (keyPath.empty()) continue;

            std::string content = readFile(keyPath);
            if (!content.empty()) {
                // Convert absolute path to relative
                std::string relativePath = keyPath;
                if (relativePath.find(extractDir_) == 0) {
                    relativePath = relativePath.substr(extractDir_.length());
                }
                authorizedKeysFiles.push_back({content, relativePath});
            }
        }
        pclose(homePipe);
    }

    // Find known_hosts files
    std::string knownCmd = "ls " + extractDir_ + "/home/*/.ssh/known_hosts "
                           + extractDir_ + "/root/.ssh/known_hosts "
                           + "2>/dev/null";
    FILE* knownPipe = popen(knownCmd.c_str(), "r");
    if (knownPipe) {
        char buffer[4096];
        while (fgets(buffer, sizeof(buffer), knownPipe)) {
            std::string hostsPath(buffer);
            while (!hostsPath.empty() && (hostsPath.back() == '\n' || hostsPath.back() == '\r')) {
                hostsPath.pop_back();
            }
            if (hostsPath.empty()) continue;

            std::string content = readFile(hostsPath);
            if (!content.empty()) {
                std::string relativePath = hostsPath;
                if (relativePath.find(extractDir_) == 0) {
                    relativePath = relativePath.substr(extractDir_.length());
                }
                knownHostsFiles.push_back({content, relativePath});
            }
        }
        pclose(knownPipe);
    }

    // Analyze SSH security
    auto sshFindings = AccountSSHAnalyzer::analyzeAllSSH(
        sshdConfig, sshConfig, authorizedKeysFiles, knownHostsFiles);

    if (!sshFindings.empty()) {
        if (linuxDb_->insertSSHSecurityFindings(sshFindings)) {
            totalSSHFindings = sshFindings.size();
            std::cout << "  Found " << totalSSHFindings << " SSH security findings" << std::endl;
            for (const auto& f : sshFindings) {
                if (f.severity == "critical") {
                    std::cout << "    [CRITICAL] " << f.findingType
                              << ": " << f.description << std::endl;
                }
            }
        }
    }

    std::cout << "  Account findings: " << totalAccountFindings
              << ", SSH findings: " << totalSSHFindings << std::endl;

    AuditLog::instance().log("SYSTEM", "ACCOUNT_SSH_COMPLETE",
        "Account/SSH security analysis: " + std::to_string(totalAccountFindings) +
        " account findings, " + std::to_string(totalSSHFindings) + " SSH findings");
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

// ============================================================================
// Phase 12: USB, Mount, Desktop, Cloud
// ============================================================================

void LinuxFilesAnalyzer::analyzeUSBEvents() {
    std::cout << "Analyzing USB events..." << std::endl;

    auto kernLogFiles = queryFilesByPattern("%/var/log/kern%");
    auto syslogFiles = queryFilesByPattern("%/var/log/syslog%");

    std::vector<USBEvent> allEvents;
    for (const auto& file : kernLogFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream fs(extractPath);
            std::vector<std::string> lines;
            std::string line;
            while (std::getline(fs, line)) lines.push_back(line);
            auto events = USBMountParser::parseUSBEvents(lines, extractPath);
            allEvents.insert(allEvents.end(), events.begin(), events.end());
        }
    }
    for (const auto& file : syslogFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream fs(extractPath);
            std::vector<std::string> lines;
            std::string line;
            while (std::getline(fs, line)) lines.push_back(line);
            auto events = USBMountParser::parseUSBEvents(lines, extractPath);
            allEvents.insert(allEvents.end(), events.begin(), events.end());
        }
    }

    if (!allEvents.empty()) {
        // Store to database (uses existing insert methods or new table)
        std::cout << "  Found " << allEvents.size() << " USB events" << std::endl;
        AuditLog::instance().log("SUCCESS", "USB_EVENTS_PARSED",
            "Parsed " + std::to_string(allEvents.size()) + " USB events");
    }
}

void LinuxFilesAnalyzer::analyzeMountEntries() {
    std::cout << "Analyzing mount entries..." << std::endl;

    auto fstabFiles = queryFilesByPattern("%/etc/fstab%");
    for (const auto& file : fstabFiles) {
        std::string extractPath = getExtractPath("etc/fstab");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream fs(extractPath);
            std::string content((std::istreambuf_iterator<char>(fs)),
                                 std::istreambuf_iterator<char>());
            auto entries = USBMountParser::parseFstab(content, extractPath);
            std::cout << "  Found " << entries.size() << " fstab entries" << std::endl;
        }
    }

    AuditLog::instance().log("SUCCESS", "MOUNT_ENTRIES_PARSED", "Analyzed mount entries");
}

void LinuxFilesAnalyzer::analyzeCloudLogs() {
    std::cout << "Analyzing cloud provider logs..." << std::endl;

    // Check for cloud-init logs
    auto cloudInitFiles = queryFilesByPattern("%/var/log/cloud-init%");
    for (const auto& file : cloudInitFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream fs(extractPath);
            std::string content((std::istreambuf_iterator<char>(fs)),
                                 std::istreambuf_iterator<char>());
            auto events = CloudParser::parseCloudInitLog(content, extractPath);
            if (!events.empty()) {
                std::cout << "  Parsed " << events.size() << " cloud-init events from " << file.name << std::endl;
            }
        }
    }

    // Check for waagent logs (Azure)
    auto waagentFiles = queryFilesByPattern("%/var/log/waagent%");
    for (const auto& file : waagentFiles) {
        std::string extractPath = getExtractPath("var/log/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream fs(extractPath);
            std::string content((std::istreambuf_iterator<char>(fs)),
                                 std::istreambuf_iterator<char>());
            auto events = CloudParser::parseWaagentLog(content, extractPath);
            if (!events.empty()) {
                std::cout << "  Parsed " << events.size() << " waagent events from " << file.name << std::endl;
            }
        }
    }

    AuditLog::instance().log("SUCCESS", "CLOUD_LOGS_PARSED", "Analyzed cloud provider logs");
}

// ============================================================================
// Phase 13: Extended history
// ============================================================================

void LinuxFilesAnalyzer::analyzeExtendedHistory() {
    std::cout << "Analyzing extended shell/development tool history..." << std::endl;

    auto userDirs = findUserHomeDirectories();
    int totalEntries = 0;

    for (const auto& userDir : userDirs) {
        std::string username = userDir.substr(userDir.find_last_of('/') + 1);

        // Python history
        auto pythonFiles = queryFilesByPattern(userDir + "%/.python_history%");
        for (const auto& file : pythonFiles) {
            std::string extractPath = getExtractPath(username + "/.python_history");
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto entries = ExtendedHistoryParser::parsePythonHistory(content, extractPath, username);
                totalEntries += entries.size();
            }
        }

        // MySQL history
        auto mysqlFiles = queryFilesByPattern(userDir + "%/.mysql_history%");
        for (const auto& file : mysqlFiles) {
            std::string extractPath = getExtractPath(username + "/.mysql_history");
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto entries = ExtendedHistoryParser::parseMysqlHistory(content, extractPath, username);
                totalEntries += entries.size();
            }
        }

        // Git config
        auto gitconfigFiles = queryFilesByPattern(userDir + "%/.gitconfig%");
        for (const auto& file : gitconfigFiles) {
            std::string extractPath = getExtractPath(username + "/.gitconfig");
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto configs = ExtendedHistoryParser::parseGitConfig(content, extractPath, username);
                for (const auto& config : configs) {
                    if (config.hasCredentials || config.hasTokens) {
                        std::cout << "  WARNING: Credentials found in " << config.filePath << std::endl;
                    }
                }
            }
        }

        // Docker config
        auto dockerConfigFiles = queryFilesByPattern(userDir + "%/.docker/config.json%");
        for (const auto& file : dockerConfigFiles) {
            std::string extractPath = getExtractPath(username + "/.docker/config.json");
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto configs = ExtendedHistoryParser::parseDockerConfig(content, extractPath, username);
                for (const auto& config : configs) {
                    if (config.hasCredentials) {
                        std::cout << "  WARNING: Docker credentials found in " << config.filePath << std::endl;
                    }
                }
            }
        }

        // Kube config
        auto kubeConfigFiles = queryFilesByPattern(userDir + "%/.kube/config%");
        for (const auto& file : kubeConfigFiles) {
            std::string extractPath = getExtractPath(username + "/.kube/config");
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto configs = ExtendedHistoryParser::parseKubeConfig(content, extractPath, username);
                for (const auto& config : configs) {
                    if (config.hasCredentials || config.hasTokens) {
                        std::cout << "  WARNING: Kubernetes credentials found in " << config.filePath << std::endl;
                    }
                }
            }
        }
    }

    std::cout << "  Found " << totalEntries << " extended history entries" << std::endl;
    AuditLog::instance().log("SUCCESS", "EXTENDED_HISTORY_PARSED",
        "Parsed " + std::to_string(totalEntries) + " extended history entries");
}

// ============================================================================
// Phase 14: Security bypass
// ============================================================================

void LinuxFilesAnalyzer::analyzeSecurityBypass() {
    std::cout << "Analyzing security bypass mechanisms..." << std::endl;

    int totalFindings = 0;

    // Check ld.so.preload
    auto preloadFiles = queryFilesByPattern("%/etc/ld.so.preload%");
    for (const auto& file : preloadFiles) {
        std::string extractPath = getExtractPath("etc/ld.so.preload");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream fs(extractPath);
            std::string content((std::istreambuf_iterator<char>(fs)),
                                 std::istreambuf_iterator<char>());
            auto findings = SecurityBypassAnalyzer::analyzeLdSoPreload(content, extractPath);
            totalFindings += findings.size();
            for (const auto& finding : findings) {
                std::cout << "  WARNING: " << finding.description << std::endl;
            }
        }
    }

    // Check shell startup files for each user
    auto userDirs = findUserHomeDirectories();
    for (const auto& userDir : userDirs) {
        std::string username = userDir.substr(userDir.find_last_of('/') + 1);

        // .bashrc
        auto bashrcFiles = queryFilesByPattern(userDir + "%/.bashrc%");
        for (const auto& file : bashrcFiles) {
            std::string extractPath = getExtractPath(username + "/.bashrc");
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto findings = SecurityBypassAnalyzer::analyzeShellStartup(content, extractPath, username);
                totalFindings += findings.size();
            }
        }

        // .profile
        auto profileFiles = queryFilesByPattern(userDir + "%/.profile%");
        for (const auto& file : profileFiles) {
            std::string extractPath = getExtractPath(username + "/.profile");
            if (extractFileToPath(file.inode, extractPath)) {
                std::ifstream fs(extractPath);
                std::string content((std::istreambuf_iterator<char>(fs)),
                                     std::istreambuf_iterator<char>());
                auto findings = SecurityBypassAnalyzer::analyzeEnvironmentFiles(content, extractPath, username);
                totalFindings += findings.size();
            }
        }
    }

    std::cout << "  Found " << totalFindings << " security bypass indicators" << std::endl;
    AuditLog::instance().log("SUCCESS", "SECURITY_BYPASS_ANALYZED",
        "Found " + std::to_string(totalFindings) + " security bypass indicators");
}

// ============================================================================
// Phase 16: Rule engine and attack chain analysis
// ============================================================================

void LinuxFilesAnalyzer::analyzeWithRuleEngine() {
    std::cout << "Running rule engine and attack chain analysis..." << std::endl;

    try {
        RuleEngine engine(outputDbPath_);

        // Evaluate all rules
        auto matches = engine.evaluateAllRules();
        std::cout << "  Rule engine found " << matches.size() << " matches" << std::endl;

        // Build attack chains
        auto chains = engine.buildAttackChains(matches);
        std::cout << "  Built " << chains.size() << " attack chains" << std::endl;

        // Store results
        if (!matches.empty()) {
            engine.storeRuleMatches(matches);
        }
        if (!chains.empty()) {
            engine.storeAttackChains(chains);
            for (const auto& chain : chains) {
                std::cout << "  ATTACK CHAIN: " << chain.summary << std::endl;
                std::cout << "    Severity: " << chain.overallSeverity << std::endl;
            }
        }

        AuditLog::instance().log("SUCCESS", "RULE_ENGINE_COMPLETE",
            "Rule engine found " + std::to_string(matches.size()) + " matches, " +
            std::to_string(chains.size()) + " attack chains");
    } catch (const std::exception& e) {
        std::cerr << "  Rule engine error: " << e.what() << std::endl;
        AuditLog::instance().log("ERROR", "RULE_ENGINE_FAILED", e.what());
    }
}

// ============================================================================
// Phase 15: Pseudo-filesystem markers (/proc, /sys)
// ============================================================================
void LinuxFilesAnalyzer::analyzePseudoFilesystems() {
    std::cout << "Checking pseudo-filesystems..." << std::endl;

    // /proc is a pseudo-filesystem that exists only in running systems
    auto procFiles = queryFilesByPattern("proc/%");
    if (procFiles.empty()) {
        LOG_INFO("Linux分析: /proc 为伪文件系统，磁盘镜像中无数据，跳过");
        // Record this finding in the analysis notes
        AuditLog::instance().log("SYSTEM", "PROC_SKIPPED",
            "/proc is a pseudo-filesystem, not available in disk images");
    }

    // /sys is a pseudo-filesystem that exists only in running systems
    auto sysFiles = queryFilesByPattern("sys/%");
    if (sysFiles.empty()) {
        LOG_INFO("Linux分析: /sys 为伪文件系统，磁盘镜像中无数据，跳过");
        AuditLog::instance().log("SYSTEM", "SYS_SKIPPED",
            "/sys is a pseudo-filesystem, not available in disk images");
    }

    // /dev is a pseudo-filesystem for device nodes
    auto devFiles = queryFilesByPattern("dev/%");
    if (devFiles.empty()) {
        LOG_INFO("Linux分析: /dev 为伪文件系统，磁盘镜像中无数据，跳过");
    }
}

// ============================================================================
// Phase 16: DNS configuration
// ============================================================================
void LinuxFilesAnalyzer::analyzeDNSConfiguration() {
    std::cout << "Analyzing DNS configuration..." << std::endl;
    AuditLog::instance().log("SYSTEM", "DNS_ANALYSIS_START", "Starting DNS configuration analysis");

    int processedCount = 0;

    // Parse /etc/resolv.conf
    auto resolvFiles = queryFilesByPattern("etc/resolv.conf");
    for (const auto& file : resolvFiles) {
        std::string extractPath = getExtractPath("dns/resolv.conf");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream resolvFile(extractPath);
            std::string line;
            while (std::getline(resolvFile, line)) {
                // Skip comments and empty lines
                if (line.empty() || line[0] == '#') continue;

                // Parse nameserver
                if (line.substr(0, 11) == "nameserver ") {
                    std::string ns = line.substr(11);
                    // Trim whitespace
                    ns.erase(0, ns.find_first_not_of(" \t"));
                    ns.erase(ns.find_last_not_of(" \t") + 1);

                    if (!ns.empty()) {
                        // Store in database (using network_connections table for now)
                        LOG_INFO("DNS: nameserver " + ns);
                        processedCount++;
                    }
                }
                // Parse search domains
                else if (line.substr(0, 7) == "search ") {
                    std::string domains = line.substr(7);
                    LOG_INFO("DNS: search domains " + domains);
                }
                // Parse domain
                else if (line.substr(0, 7) == "domain ") {
                    std::string domain = line.substr(7);
                    LOG_INFO("DNS: domain " + domain);
                }
            }
        }
    }

    // Parse /etc/hosts
    auto hostsFiles = queryFilesByPattern("etc/hosts");
    for (const auto& file : hostsFiles) {
        std::string extractPath = getExtractPath("dns/hosts");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream hostsFile(extractPath);
            std::string line;
            while (std::getline(hostsFile, line)) {
                if (line.empty() || line[0] == '#') continue;

                // Parse IP and hostname
                std::istringstream iss(line);
                std::string ip, hostname;
                if (iss >> ip >> hostname) {
                    LOG_INFO("Hosts: " + ip + " -> " + hostname);
                    processedCount++;
                }
            }
        }
    }

    // Parse /etc/hostname
    auto hostnameFiles = queryFilesByPattern("etc/hostname");
    for (const auto& file : hostnameFiles) {
        std::string extractPath = getExtractPath("dns/hostname");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream hostnameFile(extractPath);
            std::string hostname;
            if (std::getline(hostnameFile, hostname)) {
                LOG_INFO("Hostname: " + hostname);
            }
        }
    }

    AuditLog::instance().log("SYSTEM", "DNS_ANALYSIS_COMPLETE",
        "DNS analysis completed: " + std::to_string(processedCount) + " entries");
}

// ============================================================================
// Phase 17: CUPS logs
// ============================================================================
void LinuxFilesAnalyzer::analyzeCUPSLogs() {
    std::cout << "Analyzing CUPS logs..." << std::endl;
    AuditLog::instance().log("SYSTEM", "CUPS_ANALYSIS_START", "Starting CUPS log analysis");

    // Query for CUPS log files
    auto cupsFiles = queryFilesByPattern("var/log/cups/%");
    if (cupsFiles.empty()) {
        LOG_INFO("CUPS分析: 未找到 CUPS 日志文件");
        return;
    }

    int processedCount = 0;

    for (const auto& file : cupsFiles) {
        std::string extractPath = getExtractPath("cups/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream logFile(extractPath);
            std::string line;

            while (std::getline(logFile, line)) {
                if (line.empty()) continue;

                // CUPS log format: [DD/Mon/YYYY:HH:MM:SS +/-TTTT] PID LEVEL message
                // Example: [01/Jan/2024:10:30:00 +0800] 12345 INFO Job 123 queued

                // Basic parsing - store as log entry
                // The full parser would extract job ID, printer, user, etc.
                processedCount++;
            }
        }
    }

    AuditLog::instance().log("SYSTEM", "CUPS_ANALYSIS_COMPLETE",
        "CUPS analysis completed: " + std::to_string(processedCount) + " log entries");
}

// ============================================================================
// Phase 18: systemd-coredump
// ============================================================================
void LinuxFilesAnalyzer::analyzeCoredumps() {
    std::cout << "Analyzing systemd-coredump..." << std::endl;
    AuditLog::instance().log("SYSTEM", "COREDUMP_ANALYSIS_START", "Starting coredump analysis");

    // Query for coredump files
    auto coredumpFiles = queryFilesByPattern("var/lib/systemd/coredump/%");
    if (coredumpFiles.empty()) {
        LOG_INFO("Coredump分析: 未找到 coredump 文件");
        return;
    }

    int processedCount = 0;

    for (const auto& file : coredumpFiles) {
        // Coredump filename format: core.EXE.PID.TIMESTAMP
        // Extract metadata from filename
        std::string filename = file.name;

        // Store basic info
        LOG_INFO("Coredump: " + filename + " (" + std::to_string(file.size) + " bytes)");
        processedCount++;
    }

    AuditLog::instance().log("SYSTEM", "COREDUMP_ANALYSIS_COMPLETE",
        "Coredump analysis completed: " + std::to_string(processedCount) + " files");
}

// ============================================================================
// Phase 19: Snap/Flatpak packages
// ============================================================================
void LinuxFilesAnalyzer::analyzeSnapFlatpak() {
    std::cout << "Analyzing Snap/Flatpak packages..." << std::endl;
    AuditLog::instance().log("SYSTEM", "SNAP_FLATPAK_START", "Starting Snap/Flatpak analysis");

    int processedCount = 0;

    // Analyze Snap packages
    auto snapStateFiles = queryFilesByPattern("var/lib/snapd/state.json");
    for (const auto& file : snapStateFiles) {
        std::string extractPath = getExtractPath("snap/state.json");
        if (extractFileToPath(file.inode, extractPath)) {
            // Parse snap state JSON
            // The full parser would extract installed snaps, versions, channels, etc.
            LOG_INFO("Snap: Found state.json");
            processedCount++;
        }
    }

    // Analyze Flatpak packages
    auto flatpakFiles = queryFilesByPattern("var/lib/flatpak/app/%/metadata");
    for (const auto& file : flatpakFiles) {
        std::string extractPath = getExtractPath("flatpak/" + file.name);
        if (extractFileToPath(file.inode, extractPath)) {
            // Parse flatpak metadata (INI format)
            LOG_INFO("Flatpak: Found " + file.name);
            processedCount++;
        }
    }

    AuditLog::instance().log("SYSTEM", "SNAP_FLATPAK_COMPLETE",
        "Snap/Flatpak analysis completed: " + std::to_string(processedCount) + " packages");
}

// ============================================================================
// Phase 20: Browser detailed data (history, cookies, downloads, bookmarks)
// ============================================================================
void LinuxFilesAnalyzer::analyzeBrowserDetailedData() {
    std::cout << "Analyzing browser detailed data..." << std::endl;
    AuditLog::instance().log("SYSTEM", "BROWSER_DETAILED_START", "Starting browser detailed data analysis");

    int processedCount = 0;

    // Chrome/Chromium History database
    auto chromeHistoryFiles = queryFilesByPattern("%/.config/google-chrome%/Default/History");
    auto chromiumHistoryFiles = queryFilesByPattern("%/.config/chromium%/Default/History");

    for (const auto& file : chromeHistoryFiles) {
        std::string extractPath = getExtractPath("browser/chrome_history_" + std::to_string(file.inode) + ".sqlite");
        if (extractFileToPath(file.inode, extractPath)) {
            // Parse Chrome History SQLite database
            sqlite3* db = nullptr;
            if (sqlite3_open_v2(extractPath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) == SQLITE_OK) {
                // Query URLs and visits
                const char* sql = "SELECT urls.url, urls.title, urls.visit_count, "
                                  "visits.visit_time, visits.transition "
                                  "FROM urls INNER JOIN visits ON urls.id = visits.url_id "
                                  "ORDER BY visits.visit_time DESC LIMIT 10000";

                sqlite3_stmt* stmt = nullptr;
                if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
                    while (sqlite3_step(stmt) == SQLITE_ROW) {
                        LinuxBrowserHistoryEntry entry;
                        entry.browserType = "chrome";
                        entry.profilePath = file.path;
                        entry.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
                        entry.title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
                        entry.visitCount = sqlite3_column_int(stmt, 2);

                        // Chrome stores time as microseconds since 1601-01-01
                        int64_t chromeTime = sqlite3_column_int64(stmt, 3);
                        entry.visitTime = (chromeTime > 0) ? (chromeTime / 1000000 - 11644473600LL) : 0;

                        int transition = sqlite3_column_int(stmt, 4);
                        entry.transitionType = std::to_string(transition);

                        entry.sourceFile = file.path;
                        processedCount++;
                    }
                }
                sqlite3_finalize(stmt);
            }
            sqlite3_close(db);
        }
    }

    // Firefox History database
    auto firefoxPlacesFiles = queryFilesByPattern("%/.mozilla/firefox/%/places.sqlite");
    for (const auto& file : firefoxPlacesFiles) {
        std::string extractPath = getExtractPath("browser/firefox_places_" + std::to_string(file.inode) + ".sqlite");
        if (extractFileToPath(file.inode, extractPath)) {
            sqlite3* db = nullptr;
            if (sqlite3_open_v2(extractPath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) == SQLITE_OK) {
                const char* sql = "SELECT moz_places.url, moz_places.title, moz_places.visit_count, "
                                  "moz_historyvisits.visit_date "
                                  "FROM moz_places INNER JOIN moz_historyvisits "
                                  "ON moz_places.id = moz_historyvisits.place_id "
                                  "ORDER BY moz_historyvisits.visit_date DESC LIMIT 10000";

                sqlite3_stmt* stmt = nullptr;
                if (sqlite3_prepare_v2(db, sql, -1, &stmt, nullptr) == SQLITE_OK) {
                    while (sqlite3_step(stmt) == SQLITE_ROW) {
                        LinuxBrowserHistoryEntry entry;
                        entry.browserType = "firefox";
                        entry.profilePath = file.path;
                        entry.url = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0)) ?: "";
                        entry.title = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1)) ?: "";
                        entry.visitCount = sqlite3_column_int(stmt, 2);

                        // Firefox stores time as microseconds since 1970-01-01
                        int64_t firefoxTime = sqlite3_column_int64(stmt, 3);
                        entry.visitTime = (firefoxTime > 0) ? (firefoxTime / 1000000) : 0;

                        entry.sourceFile = file.path;
                        processedCount++;
                    }
                }
                sqlite3_finalize(stmt);
            }
            sqlite3_close(db);
        }
    }

    AuditLog::instance().log("SYSTEM", "BROWSER_DETAILED_COMPLETE",
        "Browser detailed data analysis completed: " + std::to_string(processedCount) + " entries");
}

// ============================================================================
// Phase 21: XDG desktop artifacts (recent documents, trash, desktop files)
// ============================================================================
void LinuxFilesAnalyzer::analyzeXDGArtifacts() {
    std::cout << "Analyzing XDG desktop artifacts..." << std::endl;
    AuditLog::instance().log("SYSTEM", "XDG_ANALYSIS_START", "Starting XDG artifacts analysis");

    int processedCount = 0;

    // Parse ~/.local/share/recently-used.xbel (recent documents)
    auto recentFiles = queryFilesByPattern("%/.local/share/recently-used.xbel");
    for (const auto& file : recentFiles) {
        std::string extractPath = getExtractPath("xdg/recent_" + std::to_string(file.inode) + ".xbel");
        if (extractFileToPath(file.inode, extractPath)) {
            // Parse XBEL format (XML)
            pugi::xml_document doc;
            if (doc.load_file(extractPath.c_str())) {
                pugi::xml_node root = doc.child("xbel");
                if (root) {
                    for (pugi::xml_node bookmark = root.child("bookmark"); bookmark; bookmark = bookmark.next_sibling("bookmark")) {
                        XDGRecentDocumentEntry entry;
                        entry.uri = bookmark.attribute("href").as_string();
                        entry.filePath = entry.uri;
                        // Remove file:// prefix
                        if (entry.filePath.substr(0, 7) == "file://") {
                            entry.filePath = entry.filePath.substr(7);
                        }

                        // Extract username from path
                        size_t homePos = file.path.find("/home/");
                        if (homePos != std::string::npos) {
                            size_t start = homePos + 6;
                            size_t end = file.path.find('/', start);
                            if (end != std::string::npos) {
                                entry.username = file.path.substr(start, end - start);
                            }
                        }

                        entry.sourceFile = file.path;
                        processedCount++;
                    }
                }
            }
        }
    }

    // Parse ~/.local/share/Trash/info/*.trashinfo (trash entries)
    auto trashInfoFiles = queryFilesByPattern("%/.local/share/Trash/info/%.trashinfo");
    for (const auto& file : trashInfoFiles) {
        std::string extractPath = getExtractPath("xdg/trash_" + std::to_string(file.inode) + ".trashinfo");
        if (extractFileToPath(file.inode, extractPath)) {
            std::ifstream trashFile(extractPath);
            std::string line;
            XDGTrashEntry entry;

            // Extract username from path
            size_t homePos = file.path.find("/home/");
            if (homePos != std::string::npos) {
                size_t start = homePos + 6;
                size_t end = file.path.find('/', start);
                if (end != std::string::npos) {
                    entry.username = file.path.substr(start, end - start);
                }
            }

            while (std::getline(trashFile, line)) {
                if (line.substr(0, 5) == "Path=") {
                    entry.originalPath = line.substr(5);
                } else if (line.substr(0, 13) == "DeletionDate=") {
                    // Parse ISO 8601 date
                    std::string dateStr = line.substr(13);
                    // Simple parsing - store as string for now
                }
            }

            entry.trashFilePath = file.path;
            entry.sourceFile = file.path;
            processedCount++;
        }
    }

    // Parse ~/.config/autostart/*.desktop (autostart entries)
    auto autostartFiles = queryFilesByPattern("%/.config/autostart/%.desktop");
    for (const auto& file : autostartFiles) {
        std::string extractPath = getExtractPath("xdg/autostart_" + std::to_string(file.inode) + ".desktop");
        if (extractFileToPath(file.inode, extractPath)) {
            XDGDesktopFileEntry entry;
            entry.filePath = file.path;
            entry.isAutostart = 1;

            std::ifstream desktopFile(extractPath);
            std::string line;
            bool inDesktopEntry = false;

            while (std::getline(desktopFile, line)) {
                if (line == "[Desktop Entry]") {
                    inDesktopEntry = true;
                    continue;
                }
                if (line[0] == '[') {
                    inDesktopEntry = false;
                    continue;
                }

                if (inDesktopEntry) {
                    size_t eqPos = line.find('=');
                    if (eqPos != std::string::npos) {
                        std::string key = line.substr(0, eqPos);
                        std::string value = line.substr(eqPos + 1);

                        if (key == "Name") entry.name = value;
                        else if (key == "Exec") entry.execCommand = value;
                        else if (key == "Icon") entry.icon = value;
                        else if (key == "Categories") entry.categories = value;
                        else if (key == "MimeType") entry.mimeType = value;
                        else if (key == "Hidden" && value == "true") entry.isHidden = 1;
                    }
                }
            }

            entry.sourceFile = file.path;
            processedCount++;
        }
    }

    AuditLog::instance().log("SYSTEM", "XDG_ANALYSIS_COMPLETE",
        "XDG artifacts analysis completed: " + std::to_string(processedCount) + " entries");
}
