// LnkParser.h
// Windows Shortcut (.lnk) file parser
// Based on MS-SHLLINK Shell Link Binary File Format specification

#pragma once
#ifndef LNK_PARSER_H
#define LNK_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include <fstream>
#include <ctime>

// LNK file signature
constexpr uint32_t LNK_SIGNATURE = 0x0000004C;  // 'L' (0x4C) + 3 null bytes
constexpr uint32_t LNK_HEADER_SIZE = 0x4C;      // 76 bytes (0x4C in hex)

// GUID for Shell Link (CLSID_ShellLink)
constexpr char SHELL_LINK_GUID[] = "\x01\x14\x02\x00\x00\x00\x00\x00"
                                     "\xC0\x00\x00\x00\x00\x00\x00\x46";

// ============================================================================
// Shell Link Header Structure (76 bytes)
// ============================================================================

#pragma pack(push, 1)

struct LnkHeader {
    uint32_t headerSize;           // Size of header (0x0000004C)
    uint32_t linkCLSID;            // GUID (first 8 bytes)
    uint64_t linkCLSID2;           // GUID (last 8 bytes)
    uint32_t linkFlags;            // LinkFlags
    uint32_t fileAttributes;       // File attributes
    uint64_t creationTime;         // Creation time (FILETIME)
    uint64_t accessTime;           // Access time (FILETIME)
    uint64_t writeTime;            // Write time (FILETIME)
    uint32_t fileSize;             // File size
    uint32_t iconIndex;            // Icon index
    uint32_t showCommand;          // Show command (SW_*)
    uint16_t hotKey;               // Hot key
    uint16_t reserved1;            // Reserved
    uint32_t reserved2;            // Reserved
    uint32_t reserved3;            // Reserved
};

// Link Flags (bit flags)
enum LnkLinkFlags : uint32_t {
    HasLinkTargetIDList    = 0x00000001,
    HasLinkInfo            = 0x00000002,
    HasName                = 0x00000004,
    HasRelativePath        = 0x00000008,
    HasWorkingDir          = 0x00000010,
    HasArguments           = 0x00000020,
    HasIconLocation        = 0x00000040,
    IsUnicode              = 0x00000080,
    ForceNoLinkInfo        = 0x00000100,
    HasExpString           = 0x00000200,
    RunInSeparateProcess   = 0x00000400,
    HasLogoID              = 0x00000800,  // Deprecated
    HasDarwinID            = 0x00001000,  // Deprecated
    RunAsUser              = 0x00002000,
    HasExpIcon             = 0x00004000,
    NoPidlAlias            = 0x00008000,
    RunWithShimLayer       = 0x00010000,
    ForceNoLinkTrack       = 0x00020000,
    ForceNoLinkTrackInfo   = 0x00040000,
    RunInSeparateDesktop   = 0x00080000,
    RunAsAdmin             = 0x00100000
};

// File Attributes
enum LnkFileAttributes : uint32_t {
    FILE_ATTRIBUTE_READONLY     = 0x00000001,
    FILE_ATTRIBUTE_HIDDEN       = 0x00000002,
    FILE_ATTRIBUTE_SYSTEM       = 0x00000004,
    FILE_ATTRIBUTE_DIRECTORY    = 0x00000010,
    FILE_ATTRIBUTE_ARCHIVE      = 0x00000020,
    FILE_ATTRIBUTE_DEVICE       = 0x00000040,
    FILE_ATTRIBUTE_NORMAL       = 0x00000080,
    FILE_ATTRIBUTE_TEMPORARY    = 0x00000100,
    FILE_ATTRIBUTE_SPARSE_FILE  = 0x00000200,
    FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400,
    FILE_ATTRIBUTE_COMPRESSED   = 0x00000800,
    FILE_ATTRIBUTE_OFFLINE      = 0x00001000,
    FILE_ATTRIBUTE_NOT_CONTENT_INDEXED = 0x00002000,
    FILE_ATTRIBUTE_ENCRYPTED    = 0x00004000
};

// Show Command values
enum LnkShowCommand : uint32_t {
    SW_SHOWNORMAL   = 1,
    SW_SHOWMAXIMIZED = 3,
    SW_SHOWMINIMIZED = 2
};

#pragma pack(pop)

// ============================================================================
// Helper Functions
// ============================================================================

namespace LnkHelpers {

/**
 * Convert Windows FILETIME to Unix timestamp
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
 * Check if file is a valid LNK file
 */
bool isValidLnkFile(const std::string& filepath);

/**
 * Parse FILETIME to readable string
 */
std::string filetimeToString(uint64_t filetime);

/**
 * Format file attributes to readable string
 */
std::string fileAttributesToString(uint32_t attributes);

/**
 * Format show command to readable string
 */
std::string showCommandToString(uint32_t showCommand);

} // namespace LnkHelpers

// ============================================================================
// Main Parser Class
// ============================================================================

class LnkParser {
public:
    explicit LnkParser(const std::string& filepath);
    ~LnkParser() = default;

    // Parse the LNK file
    bool parse();

    // Get parsed information
    std::string getTargetPath() const { return targetPath_; }
    std::string getWorkingDirectory() const { return workingDirectory_; }
    std::string getArguments() const { return arguments_; }
    std::string getDescription() const { return description_; }
    std::string getIconLocation() const { return iconLocation_; }
    std::string getRelativePath() const { return relativePath_; }

    int64_t getCreationTime() const { return creationTime_; }
    int64_t getAccessTime() const { return accessTime_; }
    int64_t getWriteTime() const { return writeTime_; }
    uint32_t getFileSize() const { return fileSize_; }
    uint32_t getFileAttributes() const { return fileAttributes_; }
    uint32_t getShowCommand() const { return showCommand_; }
    uint16_t getHotKey() const { return hotKey_; }
    std::string getDriveType() const { return driveType_; }
    std::string getVolumeSerial() const { return volumeSerial_; }
    std::string getNetBiosName() const { return netBiosName_; }

    // Error handling
    std::string getLastError() const { return lastError_; }
    bool isValid() const { return valid_; }

private:
    // Parsing methods
    bool parseHeader();
    bool parseLinkTargetIDList();
    bool parseLinkInfo();
    bool parseStringData();

    // LinkInfo parsing methods
    bool parseLinkInfoHeader(uint32_t& linkInfoSize, uint32_t& linkInfoHeaderSize,
                            uint32_t& flags, uint32_t& volumeIDOffset,
                            uint32_t& localBasePathOffset,
                            uint32_t& networkVolumeTableOffset,
                            uint32_t& basePathOffset);
    bool parseVolumeID(uint32_t offset, std::string& driveType, std::string& serial);
    bool parseNetworkVolumeTable(uint32_t offset, std::string& netBiosName);

    // String data parsing methods
    bool parseString(uint32_t& offset, const std::string& name, std::string& result);
    bool parseStringsWithCount();

    // Helper methods
    bool seekToOffset(uint32_t offset);
    bool readData(char* buffer, size_t size);
    std::string readNullTerminatedString(uint32_t maxLength);
    std::string readLengthPrefixedString(uint16_t isUnicode);

    // File data
    std::string filepath_;
    std::ifstream file_;
    bool valid_;
    std::string lastError_;

    // Parsed data
    LnkHeader header_;
    uint32_t linkFlags_;

    // Timestamps (Unix time)
    int64_t creationTime_;
    int64_t accessTime_;
    int64_t writeTime_;

    // Target information
    std::string targetPath_;
    std::string workingDirectory_;
    std::string arguments_;
    std::string description_;
    std::string iconLocation_;
    std::string relativePath_;

    // File information
    uint32_t fileSize_;
    uint32_t fileAttributes_;
    uint32_t showCommand_;
    uint16_t hotKey_;

    // Drive/Volume information
    std::string driveType_;
    std::string volumeSerial_;
    std::string netBiosName_;

    // Offsets
    uint32_t linkTargetIDListOffset_;
    uint32_t linkInfoOffset_;
    uint32_t stringDataOffset_;
};

#endif // LNK_PARSER_H
