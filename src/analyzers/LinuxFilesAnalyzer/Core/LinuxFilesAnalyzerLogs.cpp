// LinuxFilesAnalyzerLogs.cpp
// Log-related analysis methods of LinuxFilesAnalyzer
// (Compressed/rotated logs, journald, log tampering, middleware logs)

#include "LinuxFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"

#include <filesystem>
#include <fstream>
#include <sstream>

// Compressed log parser (Phase 1)
#include "Parsers/CompressedLogParser.h"

// Journal parser (Phase 2)
#include "Parsers/JournalParser.h"

// Enhanced analysis
#include "Analysis/LogTamperingDetector.h"

// Middleware log parser (Phase 7)
#include "Parsers/WebServer/MiddlewareLogParser.h"

using forensics::linux::CompressedLogParser;
using forensics::linux::CompressionType;
using forensics::linux::RotatedLogFile;
using forensics::linux::JournalParser;
using forensics::linux::JournalEntry;
using forensics::linux::JournalAnomaly;
using forensics::linux::BootSession;
using forensics::linux::TamperingFinding;
using forensics::linux::TamperingSeverity;
using forensics::linux::LogTamperingDetector;
using forensics::linux::MiddlewareLogEntry;
using forensics::linux::MiddlewareLogParser;

namespace fs = std::filesystem;

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
            if (!extractFileToPath(file.inode, outputPath, file.partitionNum)) {
                std::cerr << "    Failed to extract: " << filename << std::endl;
                totalErrors++;
                continue;
            }

            // Decompress if needed
            std::string content;
            try {
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
            } catch (const std::exception& e) {
                std::cerr << "    Log handling error for " << filename << ": " << e.what() << std::endl;
                AuditLog::instance().log("ERROR", "ROTATED_LOG_HANDLING_FAILED",
                                         filename + " -> " + e.what());
                totalErrors++;
                continue;
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
            if (!extractFileToPath(file.inode, outputPath, file.partitionNum)) {
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
