// JournalParser.h
// Parser for systemd-journald binary journal files

#pragma once
#ifndef JOURNAL_PARSER_H
#define JOURNAL_PARSER_H

#include <string>
#include <vector>
#include <map>
#include <cstdint>
#include "LinuxDataTypes.h"

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Journal file header magic
constexpr char JOURNAL_MAGIC[] = "LPKSHHRH";
constexpr size_t JOURNAL_MAGIC_SIZE = 8;

// Journal object types
enum class JournalObjectType : uint64_t {
    UNUSED = 0,
    DATA = 1,
    FIELD = 2,
    ENTRY = 3,
    DATA_HASH_TABLE = 4,
    FIELD_HASH_TABLE = 5,
    ENTRY_ARRAY = 6,
    TAG = 7
};

// Journal entry flags
enum class JournalEntryFlags : uint64_t {
    COMPRESSED = 1,
    SEALED = 2,
    FINAL = 4
};

// Journal file state
enum class JournalState : uint8_t {
    OFFLINE = 0,
    ONLINE = 1,
    ARCHIVED = 2
};

// Journal file header structure
struct JournalFileHeader {
    char magic[8];                   // "LPKSHHRH"
    uint32_t compatibleFlags;        // Compatible flags
    uint32_t incompatibleFlags;      // Incompatible flags
    uint8_t state;                   // File state
    uint8_t reserved[7];             // Reserved
    uint64_t fileSize;               // File size
    uint64_t arenaSize;              // Arena size
    uint64_t dataHashTableOffset;    // Data hash table offset
    uint64_t dataHashTableSize;      // Data hash table size
    uint64_t fieldHashTableOffset;   // Field hash table offset
    uint64_t fieldHashTableSize;     // Field hash table size
    uint64_t tailObjectOffset;       // Tail object offset
    uint64_t nObjects;               // Number of objects
    uint64_t nEntries;               // Number of entries
    uint64_t tailEntryOffset;        // Tail entry offset
    uint64_t headEntryOffset;        // Head entry offset
    uint64_t entryArrayOffset;       // Entry array offset
    uint64_t headEntrySeqnum;        // Head entry sequence number
    uint64_t tailEntrySeqnum;        // Tail entry sequence number
    uint64_t nData;                  // Number of data objects
    uint64_t nFields;                // Number of field objects
    uint64_t nTags;                  // Number of tags
    uint64_t nEntryArrays;           // Number of entry arrays
    uint64_t dataHashTableType;      // Data hash table type
};

// Journal object header
struct JournalObjectHeader {
    uint64_t objectSize;             // Object size (including header)
    JournalObjectType objectType;    // Object type
};

// Journal entry object
struct JournalEntryObject {
    uint64_t seqnum;                 // Sequence number
    int64_t realtimeTimestamp;       // Realtime timestamp (microseconds)
    int64_t monotonicTimestamp;      // Monotonic timestamp (microseconds)
    uint64_t bootId;                 // Boot ID (16 bytes, stored as uint64_t[2])
    uint64_t xorHash;                // XOR hash
    uint64_t entryOffset;            // Entry array offset
    uint32_t entryArrayOffset;       // Entry array offset
    uint32_t nArrays;                // Number of arrays
};

// Parsed journal entry (user-facing)
struct JournalEntry {
    int64_t realtimeTimestamp = 0;   // _SOURCE_REALTIME_TIMESTAMP
    int64_t monotonicTimestamp = 0;  // __MONOTONIC_TIMESTAMP
    std::string bootId;              // _BOOT_ID
    std::string systemdUnit;         // _SYSTEMD_UNIT
    std::string userUnit;            // _USER_UNIT
    int pid = -1;                    // _PID
    int uid = -1;                    // _UID
    int gid = -1;                    // _GID
    std::string comm;                // _COMM
    std::string exe;                 // _EXE
    std::string cmdline;             // _CMDLINE
    std::string transport;           // _TRANSPORT
    std::string message;             // MESSAGE
    std::string messageId;           // MESSAGE_ID
    std::string syslogIdentifier;    // SYSLOG_IDENTIFIER
    std::string priority;            // PRIORITY
    std::string cursor;              // Journal cursor
    std::map<std::string, std::string> extraFields;
    EvidenceProvenance provenance;
    NormalizedTimestamp normalizedTime;
};

// Boot session information
struct BootSession {
    std::string bootId;
    int64_t startTime = 0;
    int64_t endTime = 0;
    int entryCount = 0;
};

// Journal anomaly types
enum class JournalAnomalyType {
    VACUUM_DETECTED,      // Journal vacuum (entries removed)
    TRUNCATION_DETECTED,  // Journal file truncated
    TIME_JUMP_DETECTED,   // Time jump detected
    MISSING_BOOT,         // Missing boot session
    CORRUPTED_ENTRY,      // Corrupted entry
    GAP_DETECTED          // Gap in journal
};

// Journal anomaly
struct JournalAnomaly {
    JournalAnomalyType type;
    std::string description;
    int64_t timestamp = 0;
    int severity = 0;  // 1-5
};

// Main journal parser class
class JournalParser {
public:
    // Parse a single journal file (binary format)
    static std::vector<JournalEntry> parseJournalFile(const std::string& filePath);

    // Parse journal export format (text-based, easier to test)
    static std::vector<JournalEntry> parseJournalExport(const std::string& content);

    // Parse journal export format from file
    static std::vector<JournalEntry> parseJournalExportFile(const std::string& filePath);

    // Group entries by boot ID
    static std::vector<BootSession> groupByBootId(const std::vector<JournalEntry>& entries);

    // Detect journal anomalies
    static std::vector<JournalAnomaly> detectJournalAnomalies(const std::vector<JournalEntry>& entries);

    // Check if file is a journal file (by magic bytes)
    static bool isJournalFile(const std::string& filePath);

    // Check if file is a journal export file
    static bool isJournalExportFile(const std::string& filePath);

private:
    // Binary format parsing
    static bool parseJournalHeader(const char* data, size_t size, JournalFileHeader& header);
    static JournalObjectHeader parseObjectHeader(const char* data);
    static JournalEntryObject parseEntryObject(const char* data, size_t size);

    // Decompress data object (LZ4, XZ, ZSTD)
    static std::string decompressDataObject(const char* data, size_t size,
        uint64_t uncompressedSize, uint32_t compressionType);

    // Parse field-value pairs from data objects
    static std::map<std::string, std::string> parseDataFields(const char* data, size_t size);

    // Parse a single journal export entry
    static JournalEntry parseJournalExportEntry(const std::string& entryText);

    // Extract boot ID from bytes
    static std::string formatBootId(const uint8_t* bootIdBytes);

    // Validate journal header
    static bool validateHeader(const JournalFileHeader& header);
};

} // namespace linux
} // namespace forensics

#endif // JOURNAL_PARSER_H
