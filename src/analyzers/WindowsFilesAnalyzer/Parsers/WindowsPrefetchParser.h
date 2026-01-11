// PrefetchParser.h
// Windows Prefetch (.pf) file parser
// Supports Windows XP through Windows 11 (versions 17, 23, 26, 30, 31)

#pragma once
#ifndef PREFETCH_PARSER_H
#define PREFETCH_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include <fstream>

// Prefetch file format constants
constexpr size_t PREFETCH_MAGIC_SIZE = 4;
constexpr size_t PREFETCH_HEADER_SIZE_MIN = 1024; // Minimum header size

// Prefetch file signatures
constexpr char PREFETCH_SIGNATURE_MAM[] = "MAM";  // Compressed format
constexpr char PREFETCH_SIGNATURE_SCCA[] = "SCCA"; // Uncompressed format (older)

// Prefetch versions
enum class PrefetchVersion : uint32_t {
    VERSION_17 = 17,  // Windows XP/2003
    VERSION_23 = 23,  // Windows Vista/7/8
    VERSION_26 = 26,  // Windows 10 (early builds)
    VERSION_30 = 30,  // Windows 10 (1803+)
    VERSION_31 = 31,  // Windows 11 (2024+)
    UNKNOWN = 0
};

// ============================================================================
// Prefetch File Header Structures
// ============================================================================

#pragma pack(push, 1)

// Main file header (first part)
struct PrefetchFileHeader {
    char signature[4];          // "MAM" or "SCCA" (or "MAM\x04" for v30+)
    uint32_t version;           // Version number (17, 23, 26, 30, 31)
    uint32_t unknown1;          // Unknown/Reserved
    uint32_t fileSize;          // File size
    uint32_t executableNameOffset;  // Offset to executable name
    uint32_t executableNameLength; // Length of executable name
    uint32_t prefetchHash;      // Prefetch hash
    uint32_t unknown2;          // Unknown/Reserved
};

// File information structure (offsets and sizes)
struct PrefetchFileInfo {
    uint32_t runCount;          // Number of times executed
    uint64_t lastRunTime;       // Last execution time (FILETIME)
    std::vector<uint64_t> runTimes; // All execution timestamps
    uint32_t executablePathOffset;   // Offset to executable path
    uint32_t executablePathLength;   // Length of executable path
    std::vector<std::string> referencedFiles;     // Files loaded by executable
    std::vector<std::string> referencedDirectories; // Directories accessed
};

#pragma pack(pop)

// ============================================================================
// Helper Functions
// ============================================================================

namespace PrefetchHelpers {

/**
 * Detect Prefetch file version from header
 * @param header First 16 bytes of file
 * @return Detected version
 */
PrefetchVersion detectVersion(const char* header);

/**
 * Convert Windows FILETIME to Unix timestamp
 * @param filetime Windows FILETIME (100-nanosecond intervals since Jan 1, 1601)
 * @return Unix timestamp (seconds since Jan 1, 1970)
 */
int64_t filetimeToUnixTime(uint64_t filetime);

/**
 * Read little-endian 16-bit integer
 */
uint16_t readUInt16LE(const char* data);

/**
 * Read little-endian 32-bit integer
 */
uint32_t readUInt32LE(const char* data);

/**
 * Read little-endian 64-bit integer
 */
uint64_t readUInt64LE(const char* data);

/**
 * Extract executable name from prefetch filename
 * Filename format: EXENAME-HASH.pf or EXENAME-HASH-DEL.pf (deleted)
 */
std::string extractExecutableNameFromFilename(const std::string& filename);

/**
 * Extract prefetch hash from filename
 */
std::string extractHashFromFilename(const std::string& filename);

/**
 * Check if file is a valid Prefetch file
 */
bool isValidPrefetchFile(const std::string& filepath);

/**
 * Calculate Prefetch hash from executable name (for verification)
 * Note: This is a simplified version; the real algorithm is more complex
 */
std::string calculatePrefetchHash(const std::string& executableName);

} // namespace PrefetchHelpers

// ============================================================================
// Main Parser Class
// ============================================================================

class PrefetchParser {
public:
    explicit PrefetchParser(const std::string& filepath);
    ~PrefetchParser() = default;

    // Parse the prefetch file
    bool parse();

    // Get parsed information
    PrefetchVersion getVersion() const { return version_; }
    uint32_t getRunCount() const { return runCount_; }
    int64_t getLastRunTime() const { return lastRunTime_; }
    int64_t getCreationTime() const { return creationTime_; }
    std::string getExecutableName() const { return executableName_; }
    std::string getExecutablePath() const { return executablePath_; }
    std::string getPrefetchHash() const { return prefetchHash_; }
    std::vector<int64_t> getAllRunTimes() const { return allRunTimes_; }
    std::vector<std::string> getReferencedFiles() const { return referencedFiles_; }
    std::vector<std::string> getReferencedDirectories() const { return referencedDirectories_; }

    // Error handling
    std::string getLastError() const { return lastError_; }
    bool isValid() const { return valid_; }

private:
    // Parsing methods
    bool parseHeader();
    bool parseFileInformation();
    bool parseRunTimes();
    bool parseExecutablePath();
    bool parseReferencedFiles();
    bool parseReferencedDirectories();

    // Helper methods
    bool seekToOffset(uint32_t offset);
    bool readData(char* buffer, size_t size);
    std::string readStringAtOffset(uint32_t offset, uint32_t maxLength);

    // File data
    std::string filepath_;
    std::ifstream file_;
    bool valid_;
    std::string lastError_;

    // Parsed data
    PrefetchVersion version_;
    uint32_t runCount_;
    int64_t lastRunTime_;
    int64_t creationTime_;
    std::string executableName_;
    std::string executablePath_;
    std::string prefetchHash_;
    std::vector<int64_t> allRunTimes_;
    std::vector<std::string> referencedFiles_;
    std::vector<std::string> referencedDirectories_;

    // Header data
    char headerData_[1024]; // Raw header data
    uint32_t fileSize_;
};

#endif // PREFETCH_PARSER_H
