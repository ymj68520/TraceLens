// WindowsJumpListParser.h
// Jump List file parser for Windows forensics using libolecf

#pragma once
#ifndef WINDOWS_JUMPLIST_PARSER_H
#define WINDOWS_JUMPLIST_PARSER_H

#include <string>
#include <vector>
#include <memory>
#include <libolecf.h>
#include "WindowsDataTypes.h"

// ============================================================================
// JumpListParser Class
// ============================================================================

/**
 * Parser for Windows Jump List files (.automaticDestinations-ms, .customDestinations-ms)
 * 
 * Jump Lists are OLE Compound File (CFBF) format containers that store:
 * - AutomaticDestinations: Recent/frequent items accessed by applications
 * - CustomDestinations: User-pinned items (different format, less complex)
 * 
 * Each stream within an AutomaticDestinations file is an embedded LNK file.
 */
class JumpListParser {
public:
    explicit JumpListParser(const std::string& filepath);
    ~JumpListParser();

    // Main parse method
    bool parse();

    // Get parsed entries
    const std::vector<JumpListEntry>& getEntries() const { return entries_; }

    // Get last error message
    const std::string& getLastError() const { return lastError_; }

    // Check if parsing was successful
    bool isValid() const { return valid_; }

    // Get App ID (extracted from filename)
    const std::string& getAppId() const { return appId_; }

    // Get statistics
    size_t getStreamCount() const { return streamCount_; }
    size_t getParsedCount() const { return parsedCount_; }

private:
    // Parse AutomaticDestinations format (OLE compound file with LNK streams)
    bool parseAutomaticDestinations();

    // Parse CustomDestinations format (binary-serialized LNK collection)
    bool parseCustomDestinations();

    // Parse a single LNK stream from the OLE file
    bool parseLnkStream(libolecf_item_t* stream, const std::string& streamName);

    // Extract App ID from filename
    void extractAppId();

    // Helper to read all data from an OLE stream
    std::vector<uint8_t> readStreamData(libolecf_item_t* stream);

    // Set error message
    void setError(const std::string& error) { lastError_ = error; }

    // Member variables
    std::string filepath_;
    std::string appId_;
    std::string lastError_;
    bool valid_;

    libolecf_file_t* olecfFile_;

    std::vector<JumpListEntry> entries_;
    size_t streamCount_;
    size_t parsedCount_;
};

// ============================================================================
// JumpListHelpers Namespace
// ============================================================================

namespace JumpListHelpers {

/**
 * Determine if a file is an AutomaticDestinations Jump List
 */
bool isAutomaticDestinations(const std::string& filepath);

/**
 * Determine if a file is a CustomDestinations Jump List
 */
bool isCustomDestinations(const std::string& filepath);

/**
 * Extract App ID from Jump List filename
 * Format: {AppID}.automaticDestinations-ms or {AppID}.customDestinations-ms
 */
std::string extractAppIdFromFilename(const std::string& filepath);

/**
 * Get application name from known App ID
 * Returns empty string if unknown
 */
std::string getAppNameFromId(const std::string& appId);

/**
 * Convert FILETIME to Unix timestamp
 */
int64_t filetimeToUnixTime(uint64_t filetime);

} // namespace JumpListHelpers

#endif // WINDOWS_JUMPLIST_PARSER_H
