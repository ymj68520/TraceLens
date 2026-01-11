// SrumParser.h
// Parser for Windows SRUM (System Resource Usage Monitor) ESE database

#pragma once
#ifndef SRUM_PARSER_H
#define SRUM_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include "WindowsDataTypes.h"
#include <libesedb.h>

/**
 * @brief Parser for Windows SRUM database (SRUDB.dat)
 *
 * SRUM is an ESE (Extensible Storage Engine) database that tracks:
 * - Application resource usage (CPU, network, memory)
 * - Network usage per application
 * - Application foreground/background time
 * - User activity patterns
 *
 * Location: C:\Windows\System32\sru\SRUDB.dat
 */
class SrumParser {
public:
    /**
     * @brief Construct SRUM parser
     * @param dbPath Path to SRUDB.dat file
     */
    explicit SrumParser(const std::string& dbPath);

    /**
     * @brief Destructor - closes database
     */
    ~SrumParser();

    /**
     * @brief Parse SRUM database and extract all entries
     * @return true if parsing succeeded, false otherwise
     */
    bool parse();

    /**
     * @brief Get all parsed SRUM entries
     * @return Vector of SRUM entries
     */
    std::vector<SrumEntry> getEntries() const { return entries_; }

    /**
     * @brief Get last error message
     * @return Error description string
     */
    std::string getLastError() const { return lastError_; }

    /**
     * @brief Get total number of entries parsed
     * @return Number of entries
     */
    size_t getEntryCount() const { return entries_.size(); }

private:
    std::string dbPath_;
    std::vector<SrumEntry> entries_;
    std::string lastError_;
    libesedb_file_t* esedbFile_;

    /**
     * @brief Open ESE database file
     * @return true if successful
     */
    bool openDatabase();

    /**
     * @brief Close ESE database file
     */
    void closeDatabase();

    /**
     * @brief Parse network usage table
     * @param table ESE database table
     * @return true if successful
     */
    bool parseNetworkUsageTableFromTable(libesedb_table_t* table);

    /**
     * @brief Parse application resource usage table
     * @param table ESE database table
     * @return true if successful
     */
    bool parseApplicationResourceUsageTableFromTable(libesedb_table_t* table);

    /**
     * @brief Convert Windows FILETIME to Unix timestamp
     * @param filetime Windows FILETIME value
     * @return Unix timestamp
     */
    int64_t filetimeToUnixTime(uint64_t filetime) const;

    /**
     * @brief Extract string value from ESE column
     * @param value Column value data
     * @param size Column value size
     * @return Extracted string
     */
    std::string extractString(const void* value, size_t size) const;

    /**
     * @brief Extract int64 value from ESE column
     * @param value Column value data
     * @return Extracted int64 value
     */
    int64_t extractInt64(const void* value) const;

    /**
     * @brief Set error message
     * @param error Error description
     */
    void setError(const std::string& error) { lastError_ = error; }
};

#endif // SRUM_PARSER_H
