// SrumParser.cpp
// Implementation of SRUM parser using libesedb

#include "WindowsSrumParser.h"
#include <cstring>
#include <ctime>
#include <algorithm>

// Constructor
SrumParser::SrumParser(const std::string& dbPath)
    : dbPath_(dbPath), esedbFile_(nullptr) {
}

// Destructor
SrumParser::~SrumParser() {
    closeDatabase();
}

// Open the ESE database
bool SrumParser::openDatabase() {
    if (esedbFile_ != nullptr) {
        setError("Database already open");
        return false;
    }

    int result = libesedb_file_initialize(&esedbFile_, nullptr);
    if (result != 1) {
        setError("Failed to initialize ESE database file");
        return false;
    }

    result = libesedb_file_open(esedbFile_, dbPath_.c_str(), LIBESEDB_OPEN_READ, nullptr);
    if (result != 1) {
        setError("Failed to open SRUM database: " + dbPath_);
        libesedb_file_free(&esedbFile_, nullptr);
        esedbFile_ = nullptr;
        return false;
    }

    return true;
}

// Close the ESE database
void SrumParser::closeDatabase() {
    if (esedbFile_ != nullptr) {
        libesedb_file_close(esedbFile_, nullptr);
        libesedb_file_free(&esedbFile_, nullptr);
        esedbFile_ = nullptr;
    }
}

// Main parse function
bool SrumParser::parse() {
    entries_.clear();
    lastError_.clear();

    if (!openDatabase()) {
        return false;
    }

    // Get number of tables in the database
    int numberOfTables = 0;
    int result = libesedb_file_get_number_of_tables(esedbFile_, &numberOfTables, nullptr);

    if (result != 1) {
        setError("Failed to get number of tables");
        closeDatabase();
        return false;
    }

    // Parse relevant SRUM tables
    // Main tables of interest:
    // - {D10CA2FE-36FC-4B4F-9B86-FDD4F2C89565} - Network usage
    // - {5C8A1E66-C0AD-42CB-9792-DC0D6A7C8D3E} - Application resource usage
    // - {3C2B07E8-AB6F-4476-9ED7-6A2B85E3A449} - Network usage (per app)

    for (int i = 0; i < numberOfTables; i++) {
        libesedb_table_t* table = nullptr;
        result = libesedb_file_get_table(esedbFile_, i, &table, nullptr);

        if (result != 1) {
            continue;
        }

        // Get table name
        char* tableName = nullptr;
        size_t tableNameSize = 0;

        result = libesedb_table_get_utf8_name_size(table, &tableNameSize, nullptr);
        if (result == 1 && tableNameSize > 0) {
            tableName = new char[tableNameSize];
            result = libesedb_table_get_utf8_name(table, (uint8_t*)tableName, tableNameSize, nullptr);

            if (result == 1) {
                std::string tableNameStr(tableName);

                // Parse network usage table
                if (tableNameStr.find("D10CA2FE-36FC-4B4F-9B86-FDD4F2C89565") != std::string::npos ||
                    tableNameStr.find("3C2B07E8-AB6F-4476-9ED7-6A2B85E3A449") != std::string::npos) {
                    // Parse network usage data from this table
                    parseNetworkUsageTableFromTable(table);
                }
                // Parse application resource usage table
                else if (tableNameStr.find("5C8A1E66-C0AD-42CB-9792-DC0D6A7C8D3E") != std::string::npos) {
                    parseApplicationResourceUsageTableFromTable(table);
                }
            }

            delete[] tableName;
        }

        libesedb_table_free(&table, nullptr);
    }

    closeDatabase();

    if (entries_.empty()) {
        setError("No SRUM entries found in database");
        return false;
    }

    return true;
}

// Parse network usage table
bool SrumParser::parseNetworkUsageTableFromTable(libesedb_table_t* table) {
    if (table == nullptr) {
        return false;
    }

    int numberOfRecords = 0;
    int result = libesedb_table_get_number_of_records(table, &numberOfRecords, nullptr);

    if (result != 1 || numberOfRecords == 0) {
        return false;
    }

    // Iterate through records
    for (int i = 0; i < numberOfRecords; i++) {
        libesedb_record_t* record = nullptr;
        result = libesedb_table_get_record(table, i, &record, nullptr);

        if (result != 1) {
            continue;
        }

        SrumEntry entry;
        bool hasValidData = false;

        // Get number of values in record
        int numberOfValues = 0;
        result = libesedb_record_get_number_of_values(record, &numberOfValues, nullptr);

        if (result == 1) {
            // Iterate through columns to extract data
            for (int j = 0; j < numberOfValues; j++) {
                size_t valueSize = 0;
                uint32_t valueFlags = 0;
                uint32_t columnType = 0;

                result = libesedb_record_get_column_type(record, j, &columnType, nullptr);
                if (result != 1) continue;

                // Get column and value size
                result = libesedb_record_get_value_data_size(record, j, &valueSize, nullptr);
                if (result != 1 || valueSize == 0) continue;

                // Read value data
                std::vector<uint8_t> valueData(valueSize);
                result = libesedb_record_get_value_data(record, j, valueData.data(), valueSize, nullptr);
                if (result != 1) continue;

                // Extract data based on column index (common SRUM schema)
                // Note: Column indices may vary by Windows version
                switch (j) {
                    case 1: // Application path/name
                    case 2:
                        entry.appName = extractString(valueData.data(), valueSize);
                        hasValidData = !entry.appName.empty();
                        break;

                    case 3: // User SID
                    case 4:
                        entry.userName = extractString(valueData.data(), valueSize);
                        break;

                    case 5: // Timestamp
                    case 6:
                        if (valueSize == 8) {
                            entry.timestamp = extractInt64(valueData.data());
                            entry.timestamp = filetimeToUnixTime(entry.timestamp);
                        }
                        break;

                    case 7: // Bytes received
                    case 8:
                        if (valueSize == 8) {
                            entry.bytesReceived = extractInt64(valueData.data());
                        }
                        break;

                    case 9: // Bytes sent
                    case 10:
                        if (valueSize == 8) {
                            entry.bytesSent = extractInt64(valueData.data());
                        }
                        break;
                }
            }

            // Only add entries with valid application name
            if (hasValidData && !entry.appName.empty()) {
                entries_.push_back(entry);
            }
        }

        libesedb_record_free(&record, nullptr);
    }

    return true;
}

// Parse application resource usage table
bool SrumParser::parseApplicationResourceUsageTableFromTable(libesedb_table_t* table) {
    if (table == nullptr) {
        return false;
    }

    int numberOfRecords = 0;
    int result = libesedb_table_get_number_of_records(table, &numberOfRecords, nullptr);

    if (result != 1 || numberOfRecords == 0) {
        return false;
    }

    for (int i = 0; i < numberOfRecords; i++) {
        libesedb_record_t* record = nullptr;
        result = libesedb_table_get_record(table, i, &record, nullptr);

        if (result != 1) {
            continue;
        }

        SrumEntry entry;
        bool hasValidData = false;

        int numberOfValues = 0;
        result = libesedb_record_get_number_of_values(record, &numberOfValues, nullptr);

        if (result == 1) {
            for (int j = 0; j < numberOfValues; j++) {
                size_t valueSize = 0;

                result = libesedb_record_get_value_data_size(record, j, &valueSize, nullptr);
                if (result != 1 || valueSize == 0) continue;

                std::vector<uint8_t> valueData(valueSize);
                result = libesedb_record_get_value_data(record, j, valueData.data(), valueSize, nullptr);
                if (result != 1) continue;

                // Extract application resource usage data
                switch (j) {
                    case 1: // Application path/name
                    case 2:
                        entry.appName = extractString(valueData.data(), valueSize);
                        hasValidData = !entry.appName.empty();
                        break;

                    case 3: // User SID
                    case 4:
                        entry.userName = extractString(valueData.data(), valueSize);
                        break;

                    case 5: // Timestamp
                    case 6:
                        if (valueSize == 8) {
                            entry.timestamp = extractInt64(valueData.data());
                            entry.timestamp = filetimeToUnixTime(entry.timestamp);
                        }
                        break;

                    case 7: // Foreground duration (ms)
                    case 8:
                        if (valueSize == 8) {
                            entry.foregroundDuration = extractInt64(valueData.data());
                        }
                        break;

                    case 9: // Background duration (ms)
                    case 10:
                        if (valueSize == 8) {
                            entry.backgroundDuration = extractInt64(valueData.data());
                        }
                        break;

                    case 11: // CPU time (ms)
                    case 12:
                        if (valueSize == 8) {
                            entry.cpuTimeMs = extractInt64(valueData.data());
                        }
                        break;
                }
            }

            if (hasValidData && !entry.appName.empty()) {
                entries_.push_back(entry);
            }
        }

        libesedb_record_free(&record, nullptr);
    }

    return true;
}

// Convert Windows FILETIME to Unix timestamp
int64_t SrumParser::filetimeToUnixTime(uint64_t filetime) const {
    // Windows FILETIME is 100-nanosecond intervals since Jan 1, 1601
    // Unix time is seconds since Jan 1, 1970
    const uint64_t UNIX_TIME_START = 0x019DB1DED53E8000ULL; // Jan 1, 1970 in FILETIME
    const uint64_t TICKS_PER_SECOND = 10000000ULL;

    if (filetime < UNIX_TIME_START) {
        return 0;
    }

    return static_cast<int64_t>((filetime - UNIX_TIME_START) / TICKS_PER_SECOND);
}

// Extract string value
std::string SrumParser::extractString(const void* value, size_t size) const {
    if (value == nullptr || size == 0) {
        return "";
    }

    // Try UTF-16 first (Windows standard)
    if (size >= 2) {
        const uint16_t* utf16 = static_cast<const uint16_t*>(value);
        size_t charCount = size / 2;

        // Check for null terminator
        size_t len = 0;
        for (size_t i = 0; i < charCount; i++) {
            if (utf16[i] == 0) {
                len = i;
                break;
            }
            if (i == charCount - 1) {
                len = charCount;
            }
        }

        if (len > 0) {
            std::string result;
            result.reserve(len);

            for (size_t i = 0; i < len; i++) {
                uint16_t c = utf16[i];
                if (c < 0x80) {
                    result += static_cast<char>(c);
                } else if (c < 0x800) {
                    result += static_cast<char>(0xC0 | (c >> 6));
                    result += static_cast<char>(0x80 | (c & 0x3F));
                } else {
                    result += static_cast<char>(0xE0 | (c >> 12));
                    result += static_cast<char>(0x80 | ((c >> 6) & 0x3F));
                    result += static_cast<char>(0x80 | (c & 0x3F));
                }
            }
            return result;
        }
    }

    // Try ASCII/UTF-8
    const char* str = static_cast<const char*>(value);
    size_t len = 0;
    for (size_t i = 0; i < size; i++) {
        if (str[i] == 0) {
            len = i;
            break;
        }
        if (i == size - 1) {
            len = size;
        }
    }

    return std::string(str, len);
}

// Extract int64 value
int64_t SrumParser::extractInt64(const void* value) const {
    if (value == nullptr) {
        return 0;
    }

    // Little-endian (Windows standard)
    const uint8_t* bytes = static_cast<const uint8_t*>(value);
    int64_t result = 0;

    for (int i = 0; i < 8; i++) {
        result |= static_cast<int64_t>(bytes[i]) << (i * 8);
    }

    return result;
}
