// AmcacheParser.h
// Windows Amcache.hve file parser
// Amcache.hve stores application execution history and file association information

#pragma once
#ifndef AMCACHE_PARSER_H
#define AMCACHE_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include <memory>
#include "WindowsDataTypes.h"  // For AmcacheEntry structure

// Forward declarations for hivex
typedef struct hive_h hive_h;
typedef hive_h hive_h_t;
typedef uint64_t hive_node_h;
typedef uint64_t hive_value_h;

// ============================================================================
// Helper Functions
// ============================================================================

namespace AmcacheHelpers {

/**
 * Convert Windows FILETIME to Unix timestamp
 */
int64_t filetimeToUnixTime(uint64_t filetime);

/**
 * Read little-endian 32-bit integer
 */
uint32_t readUInt32LE(const char* data);

/**
 * Read little-endian 64-bit integer
 */
uint64_t readUInt64LE(const char* data);

/**
 * Format SHA-1 hash to hex string
 */
std::string formatHash(const uint8_t* hash, size_t length);

/**
 * Extract file name from full path
 */
std::string extractFileName(const std::string& filePath);

/**
 * Validate SHA-1 hash string
 */
bool isValidSHA1Hash(const std::string& hash);

} // namespace AmcacheHelpers

// ============================================================================
// Main Parser Class
// ============================================================================

class AmcacheParser {
public:
    explicit AmcacheParser(const std::string& hivePath);
    ~AmcacheParser();

    // Parse the Amcache hive file
    bool parse();

    // Get parsed entries
    std::vector<AmcacheEntry> getEntries() const { return entries_; }

    // Error handling
    std::string getLastError() const { return lastError_; }
    bool isValid() const { return valid_; }

private:
    // Parsing methods
    bool parseInventoryApplicationFile();
    bool parseInventoryApplicationObject();
    bool parseApplicationKey(hive_node_h node, hive_h* hive);

    // Registry helper methods
    bool openHive();
    void closeHive();
    hive_node_h openKey(const std::string& path);
    size_t getNumberOfSubKeys(hive_node_h node);
    hive_node_h getSubKey(hive_node_h parent, size_t index);

    // Value reading methods
    std::string readStringValue(hive_node_h node, const std::string& valueName);
    std::vector<uint8_t> readBinaryValue(hive_node_h node, const std::string& valueName);
    uint32_t readUInt32Value(hive_node_h node, const std::string& valueName);
    uint64_t readUInt64Value(hive_node_h node, const std::string& valueName);

    // File data
    std::string hivePath_;
    hive_h* hiveFile_;
    bool valid_;
    std::string lastError_;

    // Parsed data
    std::vector<AmcacheEntry> entries_;

    // Statistics
    int totalKeys_;
    int parsedKeys_;
};

#endif // AMCACHE_PARSER_H
