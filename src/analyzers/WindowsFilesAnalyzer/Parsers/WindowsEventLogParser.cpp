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
            windowsDb_->recordParserOutcome(logFile.path,"libevtx","error","EVTX_TRUNCATED_HEADER");
            AuditLog::instance().log("INFO", "EVTX_SKIPPED_SMALL",
                "Skipping small EVTX file: " + logFile.name +
                " (size: " + std::to_string(logFile.size) + ")");
            continue;
        }

        std::string extractPath = getExtractPath("eventlogs/" + std::to_string(logFile.partitionNum) + "_" + std::to_string(logFile.inode) + "_" + logFile.name);

        if (extractFileToPath(logFile.inode, extractPath, logFile.partitionNum)) {
            auto [entries, recovered] = parseEventLogWithRecovery(extractPath);
            for(auto& entry:entries)entry.sourcePath=logFile.path;

            if (!entries.empty()) {
                if (!windowsDb_->insertEventLogEntries(entries)) throw std::runtime_error("EVTX_DATABASE_WRITE_FAILED");
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
            windowsDb_->recordParserOutcome(logFile.path,"libevtx","error","EVTX_EXTRACT_FAILED");
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
    auto outcome = [this, &logPath](const std::string& status, const std::string& code,
            std::optional<int64_t> count = std::nullopt, int64_t recovered = 0) {
        if (windowsDb_ && !windowsDb_->recordParserOutcome(logPath,"libevtx",status,code,count,recovered))
            throw std::runtime_error("EVTX_OUTCOME_WRITE_FAILED");
    };

    // Verify file exists and has valid header
    std::ifstream file(logPath, std::ios::binary);
    if (!file) {
        outcome("error","EVTX_FILE_NOT_FOUND");
        AuditLog::instance().log("ERROR", "EVTX_FILE_NOT_FOUND",
            "Cannot open EVTX file for reading: " + logPath);
        return {entries, 0};
    }

    // Check header ("ElfFile\0")
    char header[8]{};
    file.read(header, 8);
    if (file.gcount()!=8 || std::memcmp(header, "ElfFile\0", 8) != 0) {
        outcome("error","EVTX_INVALID_HEADER");
        AuditLog::instance().log("ERROR", "EVTX_INVALID_HEADER",
            "Invalid EVTX header in: " + logPath);
        return {entries, 0};
    }
    file.close();

    // Open EVTX file using libevtx
    EvtxFileHandle evtxFile(logPath);
    if (!evtxFile.isValid()) {
        outcome("error","EVTX_OPEN_FAILED");
        AuditLog::instance().log("ERROR", "EVTX_OPEN_FAILED",
            "Failed to open EVTX file with libevtx: " + logPath);
        return {entries, 0};
    }

    // Get number of records
    bool countsKnown = true;
    int numberOfRecords = 0;
    if (libevtx_file_get_number_of_records(evtxFile, &numberOfRecords, nullptr) != 1) {
        AuditLog::instance().log("WARNING", "EVTX_RECORD_COUNT_FAILED",
            "Could not get record count for: " + logPath);
        numberOfRecords = 0;
        countsKnown = false;
    }

    // Get number of recovered records
    int numberOfRecoveredRecords = 0;
    if (libevtx_file_get_number_of_recovered_records(evtxFile, &numberOfRecoveredRecords, nullptr) != 1) {
        numberOfRecoveredRecords = 0;
        countsKnown = false;
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

    const bool complete=countsKnown && entries.size()==static_cast<size_t>(numberOfRecords+numberOfRecoveredRecords);
    const bool fieldsKnown=std::all_of(entries.begin(),entries.end(),[](const auto& e){return e.parseStatus=="ok";});
    outcome(complete ? (entries.empty()?"metadata_only":(fieldsKnown?"ok":"partial")) : (entries.empty()?"error":"partial"),
            complete ? (fieldsKnown?"":"EVTX_FIELDS_UNKNOWN") : "EVTX_RECORDS_UNREADABLE",
            complete || !entries.empty() ? std::optional<int64_t>(entries.size()) : std::nullopt, recoveredCount);
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
    entry.isRecovered = isRecovered;
    entry.sourcePath = logPath;
    entry.parserVersion = libevtx_get_version();
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
        entry.level = "Unknown"; // Missing is not informational.
    }

    // Get Timestamp (written time)
    uint64_t filetime = 0;
    if (libevtx_record_get_written_time(record, &filetime, nullptr) != 1) {
        filetime = 0; // No timestamp available
    }
    entry.timestampKnown = filetime > 0 && filetime <= 2650467743999999999ULL;
    if (filetime) entry.rawTimestamp = std::to_string(filetime);
    if (entry.timestampKnown) entry.timestamp = EvtxHelpers::filetimeToUnixTime(filetime);

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
    entry.channel.clear(); // Only the XML Channel field can establish the channel.

    // Get XML String (contains full event data)
    size_t xmlStringSize = 0;
    if (libevtx_record_get_utf8_xml_string_size(record, &xmlStringSize, nullptr) == 1) {
        char* xmlString = new char[xmlStringSize + 1];
        if (libevtx_record_get_utf8_xml_string(record, (uint8_t*)xmlString, xmlStringSize, nullptr) == 1) {
            xmlString[xmlStringSize] = '\0';
            entry.message = std::string(xmlString);

            // Extract user SID from XML if present
            entry.userSid = EvtxHelpers::extractUserDataFromXML(entry.message);
            entry.channel = EvtxHelpers::extractChannelFromXML(entry.message);
        }
        delete[] xmlString;
    }

    entry.parseStatus = entry.message.empty() ? "metadata_only" : "ok";
    if (entry.message.empty()) entry.parseError = "EVTX_XML_UNAVAILABLE";
    else if (!entry.timestampKnown || entry.eventId < 0 || entry.level == "Unknown") {
        entry.parseStatus = "partial";
        entry.parseError = "EVTX_FIELDS_UNKNOWN";
    }

    // Set log source
    entry.logSource = logSource;

    return entry;
}
