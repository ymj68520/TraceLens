// JournalParser.cpp
// Implementation of systemd-journald journal file parser

#ifdef linux
#undef linux
#endif

#include "JournalParser.h"

#include <fstream>
#include <sstream>
#include <cstring>
#include <algorithm>
#include <iostream>
#include <filesystem>
#include <regex>

namespace forensics {
namespace linux {

namespace fs = std::filesystem;

// ============================================================================
// Magic byte detection
// ============================================================================

bool JournalParser::isJournalFile(const std::string& filePath) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) return false;

    char magic[8] = {0};
    file.read(magic, 8);
    file.close();

    return memcmp(magic, JOURNAL_MAGIC, JOURNAL_MAGIC_SIZE) == 0;
}

bool JournalParser::isJournalExportFile(const std::string& filePath) {
    std::ifstream file(filePath);
    if (!file.is_open()) return false;

    std::string firstLine;
    std::getline(file, firstLine);
    file.close();

    // Journal export format starts with __CURSOR=
    return firstLine.find("__CURSOR=") == 0;
}

// ============================================================================
// Journal export format parsing (text-based)
// ============================================================================

std::vector<JournalEntry> JournalParser::parseJournalExport(const std::string& content) {
    std::vector<JournalEntry> entries;

    std::istringstream stream(content);
    std::string line;
    JournalEntry currentEntry;
    bool inEntry = false;

    while (std::getline(stream, line)) {
        // Remove carriage return if present
        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }

        // Empty line separates entries
        if (line.empty()) {
            if (inEntry) {
                entries.push_back(currentEntry);
                currentEntry = JournalEntry();
                inEntry = false;
            }
            continue;
        }

        // Check for entry start (first field of a new entry)
        if (line.find("__CURSOR=") == 0) {
            // If we were already in an entry, save it
            if (inEntry) {
                entries.push_back(currentEntry);
                currentEntry = JournalEntry();
            }
            inEntry = true;
            currentEntry.cursor = line.substr(9); // After "__CURSOR="
            continue;
        }

        if (!inEntry) continue;

        // Parse field=value pairs
        size_t eqPos = line.find('=');
        if (eqPos != std::string::npos) {
            std::string key = line.substr(0, eqPos);
            std::string value = line.substr(eqPos + 1);

            // Handle binary data (fields starting with underscore have binary format)
            // Format: _FIELD_NAME=\x00\x01...
            // We'll skip binary data for now and focus on text fields

            // Map known fields
            if (key == "MESSAGE") {
                currentEntry.message = value;
            } else if (key == "MESSAGE_ID") {
                currentEntry.messageId = value;
            } else if (key == "_PID") {
                try { currentEntry.pid = std::stoi(value); } catch (...) {}
            } else if (key == "_UID") {
                try { currentEntry.uid = std::stoi(value); } catch (...) {}
            } else if (key == "_GID") {
                try { currentEntry.gid = std::stoi(value); } catch (...) {}
            } else if (key == "_COMM") {
                currentEntry.comm = value;
            } else if (key == "_EXE") {
                currentEntry.exe = value;
            } else if (key == "_CMDLINE") {
                currentEntry.cmdline = value;
            } else if (key == "_TRANSPORT") {
                currentEntry.transport = value;
            } else if (key == "_SYSTEMD_UNIT") {
                currentEntry.systemdUnit = value;
            } else if (key == "_USER_UNIT") {
                currentEntry.userUnit = value;
            } else if (key == "SYSLOG_IDENTIFIER") {
                currentEntry.syslogIdentifier = value;
            } else if (key == "PRIORITY") {
                currentEntry.priority = value;
            } else if (key == "_BOOT_ID") {
                currentEntry.bootId = value;
            } else if (key == "__REALTIME_TIMESTAMP") {
                try { currentEntry.realtimeTimestamp = std::stoll(value); } catch (...) {}
            } else if (key == "__MONOTONIC_TIMESTAMP") {
                try { currentEntry.monotonicTimestamp = std::stoll(value); } catch (...) {}
            } else {
                // Store extra fields
                currentEntry.extraFields[key] = value;
            }
        }
    }

    // Don't forget the last entry
    if (inEntry) {
        entries.push_back(currentEntry);
    }

    return entries;
}

std::vector<JournalEntry> JournalParser::parseJournalExportFile(const std::string& filePath) {
    std::ifstream file(filePath);
    if (!file.is_open()) {
        std::cerr << "Failed to open journal export file: " << filePath << std::endl;
        return {};
    }

    std::ostringstream content;
    content << file.rdbuf();
    file.close();

    auto entries = parseJournalExport(content.str());

    // Set provenance for all entries
    for (auto& entry : entries) {
        entry.provenance.parserName = "JournalParser";
        entry.provenance.parserVersion = "1.0.0";
        entry.provenance.sourceFile = filePath;
    }

    return entries;
}

// ============================================================================
// Binary journal format parsing
// ============================================================================

bool JournalParser::parseJournalHeader(const char* data, size_t size, JournalFileHeader& header) {
    if (size < sizeof(JournalFileHeader)) {
        return false;
    }

    memcpy(&header, data, sizeof(JournalFileHeader));

    // Validate magic
    if (memcmp(header.magic, JOURNAL_MAGIC, JOURNAL_MAGIC_SIZE) != 0) {
        return false;
    }

    return validateHeader(header);
}

bool JournalParser::validateHeader(const JournalFileHeader& header) {
    // Check state
    if (header.state > static_cast<uint8_t>(JournalState::ARCHIVED)) {
        return false;
    }

    // Check file size
    if (header.fileSize < sizeof(JournalFileHeader)) {
        return false;
    }

    // Check arena size
    if (header.arenaSize < header.fileSize) {
        return false;
    }

    return true;
}

JournalObjectHeader JournalParser::parseObjectHeader(const char* data) {
    JournalObjectHeader header;
    memcpy(&header, data, sizeof(JournalObjectHeader));
    return header;
}

JournalEntryObject JournalParser::parseEntryObject(const char* data, size_t size) {
    JournalEntryObject entry;
    if (size >= sizeof(JournalEntryObject)) {
        memcpy(&entry, data, sizeof(JournalEntryObject));
    }
    return entry;
}

std::string JournalParser::formatBootId(const uint8_t* bootIdBytes) {
    // Boot ID is 16 bytes (UUID format)
    char hex[33] = {0};
    for (int i = 0; i < 16; i++) {
        snprintf(hex + i * 2, 3, "%02x", bootIdBytes[i]);
    }

    // Format as UUID: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
    std::string uuid(hex);
    uuid.insert(8, "-");
    uuid.insert(13, "-");
    uuid.insert(18, "-");
    uuid.insert(23, "-");

    return uuid;
}

std::vector<JournalEntry> JournalParser::parseJournalFile(const std::string& filePath) {
    std::vector<JournalEntry> entries;

    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "Failed to open journal file: " << filePath << std::endl;
        return entries;
    }

    // Read entire file
    file.seekg(0, std::ios::end);
    size_t fileSize = file.tellg();
    file.seekg(0, std::ios::beg);

    std::vector<char> fileData(fileSize);
    file.read(fileData.data(), fileSize);
    file.close();

    // Parse header
    JournalFileHeader header;
    if (!parseJournalHeader(fileData.data(), fileSize, header)) {
        std::cerr << "Invalid journal file header: " << filePath << std::endl;
        return entries;
    }

    // Basic implementation - read entries sequentially
    // The full binary format is complex with hash tables and compression
    // This implementation handles the basic structure

    size_t offset = sizeof(JournalFileHeader);
    int64_t prevTimestamp = 0;

    while (offset < fileSize - sizeof(JournalObjectHeader)) {
        // Parse object header
        auto objHeader = parseObjectHeader(fileData.data() + offset);

        if (objHeader.objectSize == 0 || objHeader.objectSize > fileSize - offset) {
            break; // Invalid object
        }

        // Handle entry objects
        if (objHeader.objectType == JournalObjectType::ENTRY) {
            JournalEntryObject entryObj = parseEntryObject(
                fileData.data() + offset + sizeof(JournalObjectHeader),
                objHeader.objectSize - sizeof(JournalObjectHeader));

            JournalEntry entry;
            entry.realtimeTimestamp = entryObj.realtimeTimestamp;
            entry.monotonicTimestamp = entryObj.monotonicTimestamp;

            // Format boot ID
            uint8_t bootIdBytes[16];
            memcpy(bootIdBytes, &entryObj.bootId, 8);
            // Note: bootId is actually 16 bytes, stored as two uint64_t
            entry.bootId = formatBootId(bootIdBytes);

            // Set provenance
            entry.provenance.parserName = "JournalParser";
            entry.provenance.parserVersion = "1.0.0";
            entry.provenance.sourceFile = filePath;
            entry.provenance.sourceOffset = offset;

            entries.push_back(entry);

            // Check for time jumps
            if (prevTimestamp > 0 && entry.realtimeTimestamp < prevTimestamp) {
                // Time went backwards - potential anomaly
                entry.normalizedTime.clockSkewFlag = true;
            }
            prevTimestamp = entry.realtimeTimestamp;
        }

        // Move to next object
        offset += objHeader.objectSize;

        // Align to 8 bytes
        offset = (offset + 7) & ~7;
    }

    // Try to parse field data for each entry
    // This is a simplified implementation - full parsing requires following
    // entry array references to field objects

    return entries;
}

// ============================================================================
// Boot session grouping
// ============================================================================

std::vector<BootSession> JournalParser::groupByBootId(const std::vector<JournalEntry>& entries) {
    std::map<std::string, BootSession> sessionMap;

    for (const auto& entry : entries) {
        std::string bootId = entry.bootId.empty() ? "unknown" : entry.bootId;

        auto it = sessionMap.find(bootId);
        if (it == sessionMap.end()) {
            BootSession session;
            session.bootId = bootId;
            session.startTime = entry.realtimeTimestamp;
            session.endTime = entry.realtimeTimestamp;
            session.entryCount = 1;
            sessionMap[bootId] = session;
        } else {
            it->second.entryCount++;
            if (entry.realtimeTimestamp < it->second.startTime) {
                it->second.startTime = entry.realtimeTimestamp;
            }
            if (entry.realtimeTimestamp > it->second.endTime) {
                it->second.endTime = entry.realtimeTimestamp;
            }
        }
    }

    std::vector<BootSession> sessions;
    for (const auto& [id, session] : sessionMap) {
        sessions.push_back(session);
    }

    // Sort by start time
    std::sort(sessions.begin(), sessions.end(),
        [](const BootSession& a, const BootSession& b) {
            return a.startTime < b.startTime;
        });

    return sessions;
}

// ============================================================================
// Anomaly detection
// ============================================================================

std::vector<JournalAnomaly> JournalParser::detectJournalAnomalies(
    const std::vector<JournalEntry>& entries) {

    std::vector<JournalAnomaly> anomalies;

    if (entries.empty()) {
        return anomalies;
    }

    int64_t prevTimestamp = 0;
    int64_t gapThreshold = 3600000000LL; // 1 hour in microseconds

    for (size_t i = 0; i < entries.size(); i++) {
        const auto& entry = entries[i];

        // Check for time jumps
        if (prevTimestamp > 0) {
            int64_t diff = entry.realtimeTimestamp - prevTimestamp;

            // Time went backwards
            if (diff < -1000000) { // More than 1 second backwards
                JournalAnomaly anomaly;
                anomaly.type = JournalAnomalyType::TIME_JUMP_DETECTED;
                anomaly.description = "Time went backwards by " +
                    std::to_string(-diff / 1000000) + " seconds";
                anomaly.timestamp = entry.realtimeTimestamp;
                anomaly.severity = 3;
                anomalies.push_back(anomaly);
            }

            // Large gap
            if (diff > gapThreshold) {
                JournalAnomaly anomaly;
                anomaly.type = JournalAnomalyType::GAP_DETECTED;
                anomaly.description = "Gap of " +
                    std::to_string(diff / 1000000) + " seconds detected";
                anomaly.timestamp = prevTimestamp;
                anomaly.severity = 2;
                anomalies.push_back(anomaly);
            }
        }

        // Check for truncated entries (empty message with timestamp)
        if (entry.message.empty() && entry.realtimeTimestamp > 0) {
            JournalAnomaly anomaly;
            anomaly.type = JournalAnomalyType::CORRUPTED_ENTRY;
            anomaly.description = "Entry at offset " + std::to_string(i) +
                " has timestamp but no message";
            anomaly.timestamp = entry.realtimeTimestamp;
            anomaly.severity = 1;
            anomalies.push_back(anomaly);
        }

        prevTimestamp = entry.realtimeTimestamp;
    }

    // Check for missing boot sessions
    auto sessions = groupByBootId(entries);
    if (sessions.size() > 1) {
        for (size_t i = 1; i < sessions.size(); i++) {
            int64_t gap = sessions[i].startTime - sessions[i-1].endTime;
            if (gap > 86400000000LL) { // More than 1 day
                JournalAnomaly anomaly;
                anomaly.type = JournalAnomalyType::MISSING_BOOT;
                anomaly.description = "Gap of " +
                    std::to_string(gap / 86400000000LL) +
                    " days between boot sessions";
                anomaly.timestamp = sessions[i-1].endTime;
                anomaly.severity = 2;
                anomalies.push_back(anomaly);
            }
        }
    }

    return anomalies;
}

// ============================================================================
// Decompression (placeholder - requires LZ4/XZ/ZSTD integration)
// ============================================================================

std::string JournalParser::decompressDataObject(const char* data, size_t size,
    uint64_t uncompressedSize, uint32_t compressionType) {

    // TODO: Implement decompression for LZ4, XZ, ZSTD
    // Compression types:
    // 0 = NONE
    // 1 = LZ4
    // 2 = XZ
    // 3 = ZSTD

    if (compressionType == 0) {
        // No compression
        return std::string(data, size);
    }

    // For now, return empty string for compressed data
    // Full implementation requires linking to compression libraries
    std::cerr << "Compressed journal data not yet supported (type=" << compressionType << ")" << std::endl;
    return "";
}

std::map<std::string, std::string> JournalParser::parseDataFields(
    const char* data, size_t size) {

    std::map<std::string, std::string> fields;

    // Data objects contain field=value pairs separated by newlines
    std::string content(data, size);
    std::istringstream stream(content);
    std::string line;

    while (std::getline(stream, line)) {
        size_t eqPos = line.find('=');
        if (eqPos != std::string::npos) {
            fields[line.substr(0, eqPos)] = line.substr(eqPos + 1);
        }
    }

    return fields;
}

} // namespace linux
} // namespace forensics
