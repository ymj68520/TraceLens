// WindowsEventLogParser.cpp
// Implementation of Event Log (EVTX) parsing logic using libevtx

#include "WindowsFilesAnalyzer.h"
#include "WindowsEventLogParser.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <cstring>
#include <ctime>
#include <sstream>
#include <iomanip>
#include <algorithm>

// ============================================================================
// EvtxFileHandle Implementation
// ============================================================================

EvtxFileHandle::EvtxFileHandle(const std::string& path) : file_(nullptr) {
    if (libevtx_file_initialize(&file_, nullptr) != 1) {
        AuditLog::instance().log("ERROR", "EVTX_INIT_FAILED",
            "Failed to initialize libevtx file for: " + path);
        return;
    }

    // Open file with read-only access
    if (libevtx_file_open(file_, path.c_str(), LIBEVTX_OPEN_READ, nullptr) != 1) {
        AuditLog::instance().log("ERROR", "EVTX_OPEN_FAILED",
            "Failed to open EVTX file: " + path);
        libevtx_file_free(&file_, nullptr);
        file_ = nullptr;
        return;
    }
}

EvtxFileHandle::~EvtxFileHandle() {
    if (file_) {
        libevtx_file_close(file_, nullptr);
        libevtx_file_free(&file_, nullptr);
        file_ = nullptr;
    }
}

EvtxFileHandle::EvtxFileHandle(EvtxFileHandle&& other) noexcept
    : file_(other.file_) {
    other.file_ = nullptr;
}

EvtxFileHandle& EvtxFileHandle::operator=(EvtxFileHandle&& other) noexcept {
    if (this != &other) {
        if (file_) {
            libevtx_file_close(file_, nullptr);
            libevtx_file_free(&file_, nullptr);
        }
        file_ = other.file_;
        other.file_ = nullptr;
    }
    return *this;
}

// ============================================================================
// EvtxRecordHandle Implementation
// ============================================================================

EvtxRecordHandle::EvtxRecordHandle(libevtx_record_t* record)
    : record_(record) {
}

EvtxRecordHandle::~EvtxRecordHandle() {
    if (record_) {
        libevtx_record_free(&record_, nullptr);
        record_ = nullptr;
    }
}

EvtxRecordHandle::EvtxRecordHandle(EvtxRecordHandle&& other) noexcept
    : record_(other.record_) {
    other.record_ = nullptr;
}

EvtxRecordHandle& EvtxRecordHandle::operator=(EvtxRecordHandle&& other) noexcept {
    if (this != &other) {
        if (record_) {
            libevtx_record_free(&record_, nullptr);
        }
        record_ = other.record_;
        other.record_ = nullptr;
    }
    return *this;
}

libevtx_record_t* EvtxRecordHandle::release() {
    auto* tmp = record_;
    record_ = nullptr;
    return tmp;
}

// ============================================================================
// EvtxHelpers Implementation
// ============================================================================

namespace EvtxHelpers {

std::string eventLevelToString(uint8_t level) {
    switch (level) {
        case 1: return "Critical";
        case 2: return "Error";
        case 3: return "Warning";
        case 4: return "Information";
        case 5: return "Verbose";
        default: return "Unknown";
    }
}

int64_t filetimeToUnixTime(uint64_t filetime) {
    if (filetime == 0) return 0;

    // Windows FILETIME: 100-nanosecond intervals since January 1, 1601 UTC
    // Unix timestamp: seconds since January 1, 1970 UTC
    // Difference: 11,644,473,600 seconds (369 years)
    const uint64_t TICKS_PER_SECOND = 10000000;
    const uint64_t EPOCH_DIFFERENCE = 11644473600ULL;

    return static_cast<int64_t>((filetime / TICKS_PER_SECOND) - EPOCH_DIFFERENCE);
}

std::string extractUserDataFromXML(const std::string& xmlString) {
    // Extract user SID from XML if present
    // Look for common XML patterns with user data
    const std::vector<std::string> patterns = {
        "<Data Name='SubjectUserName'>",
        "<Data Name=\"SubjectUserName\">",
        "<Data Name='UserId'>",
        "<Data Name=\"UserId\">",
        "<Data Name='UserName'>",
        "<Data Name=\"UserName\">",
        "<Data Name='SubjectUserSid'>",
        "<Data Name=\"SubjectUserSid\">"
    };

    for (const auto& pattern : patterns) {
        size_t pos = xmlString.find(pattern);
        if (pos != std::string::npos) {
            size_t start = pos + pattern.length();
            size_t end = xmlString.find("</Data>", start);
            if (end != std::string::npos) {
                std::string userData = xmlString.substr(start, end - start);
                // Trim whitespace
                userData.erase(0, userData.find_first_not_of(" \t\n\r"));
                userData.erase(userData.find_last_not_of(" \t\n\r") + 1);
                if (!userData.empty()) {
                    return userData;
                }
            }
        }
    }

    return "S-1-0-0"; // Default: Nobody/NULL SID
}

std::string getLogSourceFromPath(const std::string& logPath) {
    // Extract log type from filename
    // e.g., "/path/to/System.evtx" -> "System"

    size_t lastSlash = logPath.find_last_of("/\\");
    if (lastSlash == std::string::npos) {
        lastSlash = 0;
    } else {
        lastSlash++;
    }

    size_t dotPos = logPath.find_last_of('.');
    if (dotPos == std::string::npos || dotPos <= lastSlash) {
        return "Unknown";
    }

    std::string filename = logPath.substr(lastSlash, dotPos - lastSlash);

    // Common log types - return as-is (they're already capitalized correctly)
    if (filename == "Security" || filename == "System" ||
        filename == "Application" || filename == "Setup") {
        return filename;
    }

    // Capitalize first letter for others
    if (!filename.empty()) {
        filename[0] = std::toupper(filename[0]);
    }

    return filename;
}

} // namespace EvtxHelpers

// ============================================================================
// WindowsFilesAnalyzer::analyzeEventLogs
// ============================================================================

void WindowsFilesAnalyzer::analyzeEventLogs() {
    std::cout << "Analyzing Event Logs..." << std::endl;
    AuditLog::instance().log("SYSTEM", "EVTX_ANALYSIS_START",
        "Starting Windows Event Log analysis");

    // Search for EVTX files in System32/winevt/Logs
    std::vector<FileRecord> logFiles = queryFilesByPattern("%/System32/winevt/Logs/%.evtx");

    int processedCount = 0;
    int totalRecords = 0;
    int recoveredRecords = 0;

    for (const auto& logFile : logFiles) {
        // Skip small files (likely empty or corrupted)
        if (logFile.size < 4096) {
            AuditLog::instance().log("INFO", "EVTX_SKIPPED_SMALL",
                "Skipping small EVTX file: " + logFile.name +
                " (size: " + std::to_string(logFile.size) + ")");
            continue;
        }

        std::string extractPath = getExtractPath("eventlogs/" + logFile.name);

        if (extractFileToPath(logFile.inode, extractPath, logFile.partitionNum)) {
            auto [entries, recovered] = parseEventLogWithRecovery(extractPath);

            if (!entries.empty()) {
                windowsDb_->insertEventLogEntries(entries);
                processedCount++;
                totalRecords += entries.size();
                recoveredRecords += recovered;

                std::cout << "  Processed: " << logFile.name
                         << " (" << entries.size() << " records";
                if (recovered > 0) {
                    std::cout << ", " << recovered << " recovered";
                }
                std::cout << ")" << std::endl;
            }
        } else {
            AuditLog::instance().log("ERROR", "EVTX_EXTRACT_FAILED",
                "Failed to extract EVTX file: " + logFile.path);
        }
    }

    std::cout << "  Processed " << processedCount << " event log files"
             << " with " << totalRecords << " total records";
    if (recoveredRecords > 0) {
        std::cout << " (" << recoveredRecords << " recovered from corruption)";
    }
    std::cout << "." << std::endl;

    AuditLog::instance().log("SYSTEM", "EVTX_ANALYSIS_COMPLETE",
        "Completed EVTX analysis: " + std::to_string(processedCount) +
        " files, " + std::to_string(totalRecords) + " records, " +
        std::to_string(recoveredRecords) + " recovered");
}

// ============================================================================
// WindowsFilesAnalyzer::parseEventLog
// ============================================================================

std::vector<EventLogEntry> WindowsFilesAnalyzer::parseEventLog(const std::string& logPath) {
    auto [entries, recovered] = parseEventLogWithRecovery(logPath);
    return entries; // For backward compatibility
}

// ============================================================================
// WindowsFilesAnalyzer::parseEventLogWithRecovery
// ============================================================================

std::pair<std::vector<EventLogEntry>, int> WindowsFilesAnalyzer::parseEventLogWithRecovery(const std::string& logPath) {
    std::vector<EventLogEntry> entries;
    int recoveredCount = 0;

    // Verify file exists and has valid header
    std::ifstream file(logPath, std::ios::binary);
    if (!file) {
        AuditLog::instance().log("ERROR", "EVTX_FILE_NOT_FOUND",
            "Cannot open EVTX file for reading: " + logPath);
        return {entries, 0};
    }

    // Check header ("ElfFile\0")
    char header[8];
    file.read(header, 8);
    if (std::strncmp(header, "ElfFile", 7) != 0) {
        AuditLog::instance().log("ERROR", "EVTX_INVALID_HEADER",
            "Invalid EVTX header in: " + logPath);
        return {entries, 0};
    }
    file.close();

    // Open EVTX file using libevtx
    EvtxFileHandle evtxFile(logPath);
    if (!evtxFile.isValid()) {
        AuditLog::instance().log("ERROR", "EVTX_OPEN_FAILED",
            "Failed to open EVTX file with libevtx: " + logPath);
        return {entries, 0};
    }

    // Get number of records
    int numberOfRecords = 0;
    if (libevtx_file_get_number_of_records(evtxFile, &numberOfRecords, nullptr) != 1) {
        AuditLog::instance().log("WARNING", "EVTX_RECORD_COUNT_FAILED",
            "Could not get record count for: " + logPath);
        numberOfRecords = 0;
    }

    // Get number of recovered records
    int numberOfRecoveredRecords = 0;
    if (libevtx_file_get_number_of_recovered_records(evtxFile, &numberOfRecoveredRecords, nullptr) != 1) {
        numberOfRecoveredRecords = 0;
    }

    std::string logSource = EvtxHelpers::getLogSourceFromPath(logPath);

    // Pre-allocate vector for efficiency
    int totalExpected = numberOfRecords + numberOfRecoveredRecords;
    if (totalExpected > 0) {
        entries.reserve(std::min(totalExpected, 100000)); // Cap at 100k to avoid excessive memory
    }

    // Process normal records
    for (int i = 0; i < numberOfRecords; i++) {
        libevtx_record_t* recordPtr = nullptr;

        if (libevtx_file_get_record_by_index(evtxFile, i, &recordPtr, nullptr) != 1) {
            AuditLog::instance().log("WARNING", "EVTX_RECORD_READ_FAILED",
                "Failed to read record at index " + std::to_string(i) +
                " from " + logPath);
            continue;
        }

        EvtxRecordHandle record(recordPtr);
        if (!record.isValid()) {
            continue;
        }

        EventLogEntry entry = extractEventLogEntry(record.get(), logSource, logPath, false);
        if (entry.recordId >= 0) { // Valid entry
            entries.push_back(entry);
        }
    }

    // Process recovered records (corrupted/deleted)
    for (int i = 0; i < numberOfRecoveredRecords; i++) {
        libevtx_record_t* recordPtr = nullptr;

        if (libevtx_file_get_recovered_record_by_index(evtxFile, i, &recordPtr, nullptr) != 1) {
            continue;
        }

        EvtxRecordHandle record(recordPtr);
        if (!record.isValid()) {
            continue;
        }

        EventLogEntry entry = extractEventLogEntry(record.get(), logSource, logPath, true);
        if (entry.recordId >= 0) {
            entries.push_back(entry);
            recoveredCount++;
        }
    }

    AuditLog::instance().log("INFO", "EVTX_PARSE_SUCCESS",
        "Successfully parsed " + logPath + ": " +
        std::to_string(entries.size()) + " records, " +
        std::to_string(recoveredCount) + " recovered");

    return {entries, recoveredCount};
}

// ============================================================================
// WindowsFilesAnalyzer::extractEventLogEntry
// ============================================================================

EventLogEntry WindowsFilesAnalyzer::extractEventLogEntry(
    libevtx_record_t* record,
    const std::string& logSource,
    const std::string& logPath,
    bool isRecovered) {

    EventLogEntry entry;
    entry.recordId = -1; // Sentinel for invalid entries

    if (!record) {
        return entry;
    }

    // Get Record ID
    uint64_t recordNumber = 0;
    if (libevtx_record_get_identifier(record, &recordNumber, nullptr) == 1) {
        entry.recordId = static_cast<int64_t>(recordNumber);
    }

    // Get Event ID
    uint32_t eventIdentifier = 0;
    if (libevtx_record_get_event_identifier(record, &eventIdentifier, nullptr) == 1) {
        entry.eventId = eventIdentifier;
    }

    // Get Event Level
    uint8_t eventLevel = 0;
    if (libevtx_record_get_event_level(record, &eventLevel, nullptr) == 1) {
        entry.level = EvtxHelpers::eventLevelToString(eventLevel);
    } else {
        entry.level = "Information"; // Default
    }

    // Get Timestamp (written time)
    uint64_t filetime = 0;
    if (libevtx_record_get_written_time(record, &filetime, nullptr) != 1) {
        filetime = 0; // No timestamp available
    }
    entry.timestamp = EvtxHelpers::filetimeToUnixTime(filetime);

    // Get Source Name
    size_t sourceNameSize = 0;
    if (libevtx_record_get_utf8_source_name_size(record, &sourceNameSize, nullptr) == 1) {
        char* sourceName = new char[sourceNameSize + 1];
        if (libevtx_record_get_utf8_source_name(record, (uint8_t*)sourceName, sourceNameSize, nullptr) == 1) {
            sourceName[sourceNameSize] = '\0';
            entry.source = std::string(sourceName);
        }
        delete[] sourceName;
    }
    if (entry.source.empty()) {
        entry.source = logSource; // Fallback to log source
    }

    // Get Computer Name
    size_t computerNameSize = 0;
    if (libevtx_record_get_utf8_computer_name_size(record, &computerNameSize, nullptr) == 1) {
        char* computerName = new char[computerNameSize + 1];
        if (libevtx_record_get_utf8_computer_name(record, (uint8_t*)computerName, computerNameSize, nullptr) == 1) {
            computerName[computerNameSize] = '\0';
            entry.computerName = std::string(computerName);
        }
        delete[] computerName;
    }
    if (entry.computerName.empty()) {
        entry.computerName = "UNKNOWN";
    }

    // Get Channel Name (use logSource as fallback since channel_name API doesn't exist)
    entry.channel = logSource;

    // Get XML String (contains full event data)
    size_t xmlStringSize = 0;
    if (libevtx_record_get_utf8_xml_string_size(record, &xmlStringSize, nullptr) == 1) {
        char* xmlString = new char[xmlStringSize + 1];
        if (libevtx_record_get_utf8_xml_string(record, (uint8_t*)xmlString, xmlStringSize, nullptr) == 1) {
            xmlString[xmlStringSize] = '\0';
            entry.message = std::string(xmlString);

            // Extract user SID from XML if present
            entry.userSid = EvtxHelpers::extractUserDataFromXML(entry.message);
        }
        delete[] xmlString;
    }

    if (entry.message.empty()) {
        entry.message = "<No XML data available>";
    }

    // Set log source
    entry.logSource = logSource;

    return entry;
}
