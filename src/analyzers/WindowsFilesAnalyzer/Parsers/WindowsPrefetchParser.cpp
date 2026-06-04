// PrefetchParser.cpp
// Implementation of Windows Prefetch (.pf) file parser

#include "WindowsPrefetchParser.h"
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cstring>

// ============================================================================
// PrefetchHelpers Implementation
// ============================================================================

namespace PrefetchHelpers {

PrefetchVersion detectVersion(const char* header) {
    if (std::memcmp(header, "MAM", 3) == 0) {
        // Check for version 30+ (MAM\x04)
        if (header[3] == 0x04) {
            uint32_t version = *reinterpret_cast<const uint32_t*>(header + 4);
            if (version == 30) return PrefetchVersion::VERSION_30;
            if (version == 31) return PrefetchVersion::VERSION_31;
            return PrefetchVersion::VERSION_30; // Assume version 30 for unknown
        }
        // Older compressed format
        uint32_t version = *reinterpret_cast<const uint32_t*>(header + 8);
        if (version == 23) return PrefetchVersion::VERSION_23;
        if (version == 26) return PrefetchVersion::VERSION_26;
        return PrefetchVersion::VERSION_23; // Assume version 23
    }

    if (std::memcmp(header, "SCCA", 4) == 0) {
        return PrefetchVersion::VERSION_17; // Windows XP/2003
    }

    return PrefetchVersion::UNKNOWN;
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

uint16_t readUInt16LE(const char* data) {
    return static_cast<uint16_t>(
        static_cast<unsigned char>(data[0]) |
        (static_cast<unsigned char>(data[1]) << 8)
    );
}

uint32_t readUInt32LE(const char* data) {
    return static_cast<uint32_t>(
        static_cast<unsigned char>(data[0]) |
        (static_cast<unsigned char>(data[1]) << 8) |
        (static_cast<unsigned char>(data[2]) << 16) |
        (static_cast<unsigned char>(data[3]) << 24)
    );
}

uint64_t readUInt64LE(const char* data) {
    return static_cast<uint64_t>(
        static_cast<uint64_t>(static_cast<unsigned char>(data[0])) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[1])) << 8) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[2])) << 16) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[3])) << 24) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[4])) << 32) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[5])) << 40) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[6])) << 48) |
        (static_cast<uint64_t>(static_cast<unsigned char>(data[7])) << 56)
    );
}

std::string extractExecutableNameFromFilename(const std::string& filename) {
    // Extract base filename without path
    size_t lastSlash = filename.find_last_of("/\\");
    std::string basename = (lastSlash != std::string::npos) ?
        filename.substr(lastSlash + 1) : filename;

    // Remove .pf extension
    size_t dotPos = basename.find_last_of('.');
    if (dotPos != std::string::npos) {
        basename = basename.substr(0, dotPos);
    }

    // Extract executable name (before hash)
    // Format: EXENAME-HASH or EXENAME-HASH-DEL
    size_t dashPos = basename.find('-');
    if (dashPos != std::string::npos) {
        return basename.substr(0, dashPos);
    }

    return basename;
}

std::string extractHashFromFilename(const std::string& filename) {
    size_t lastSlash = filename.find_last_of("/\\");
    std::string basename = (lastSlash != std::string::npos) ?
        filename.substr(lastSlash + 1) : filename;

    size_t dotPos = basename.find_last_of('.');
    if (dotPos != std::string::npos) {
        basename = basename.substr(0, dotPos);
    }

    size_t firstDash = basename.find('-');
    if (firstDash != std::string::npos) {
        size_t secondDash = basename.find('-', firstDash + 1);
        if (secondDash != std::string::npos) {
            // EXENAME-HASH-DEL format
            return basename.substr(firstDash + 1, secondDash - firstDash - 1);
        }
        // EXENAME-HASH format
        return basename.substr(firstDash + 1);
    }

    return "";
}

bool isValidPrefetchFile(const std::string& filepath) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file) return false;

    char header[4];
    file.read(header, 4);
    if (file.gcount() < 4) return false;

    // Check for valid signatures
    if (std::memcmp(header, "MAM", 3) == 0 || std::memcmp(header, "SCCA", 4) == 0) {
        return true;
    }

    return false;
}

std::string calculatePrefetchHash(const std::string& executableName) {
    // This is a simplified placeholder
    // The real prefetch hash algorithm is more complex and involves:
    // 1. Converting executable name to uppercase
    // 2. Normalizing the path
    // 3. Computing a checksum/hash
    // For now, return a placeholder based on string length
    std::ostringstream oss;
    oss << std::hex << std::setw(8) << std::setfill('0')
        << (std::hash<std::string>{}(executableName) & 0xFFFFFFFF);
    return oss.str();
}

} // namespace PrefetchHelpers

// ============================================================================
// PrefetchParser Implementation
// ============================================================================

PrefetchParser::PrefetchParser(const std::string& filepath)
    : filepath_(filepath),
      valid_(false),
      version_(PrefetchVersion::UNKNOWN),
      runCount_(0),
      lastRunTime_(0),
      creationTime_(0),
      fileSize_(0) {
}

bool PrefetchParser::parse() {
    valid_ = false;
    lastError_.clear();

    // Open file
    file_.open(filepath_, std::ios::binary);
    if (!file_) {
        lastError_ = "Cannot open file: " + filepath_;
        return false;
    }

    // Read and validate header
    if (!parseHeader()) {
        return false;
    }

    // Parse file information
    if (!parseFileInformation()) {
        return false;
    }

    // Parse run timestamps
    if (!parseRunTimes()) {
        // Not critical, continue
    }

    // Parse executable path
    if (!parseExecutablePath()) {
        // Not critical, continue
    }

    // Parse referenced files (version-dependent)
    if (version_ >= PrefetchVersion::VERSION_23) {
        if (!parseReferencedFiles()) {
            // Not critical, continue
        }
    }

    // Parse referenced directories (version-dependent)
    if (version_ >= PrefetchVersion::VERSION_26) {
        if (!parseReferencedDirectories()) {
            // Not critical, continue
        }
    }

    // Extract executable name and hash from filename if not found in file
    if (executableName_.empty()) {
        executableName_ = PrefetchHelpers::extractExecutableNameFromFilename(filepath_);
    }
    if (prefetchHash_.empty()) {
        prefetchHash_ = PrefetchHelpers::extractHashFromFilename(filepath_);
    }

    // Get file creation time from filesystem
    // This is a fallback; real implementation should use file metadata
    creationTime_ = lastRunTime_; // Use last run time as approximation

    valid_ = true;
    return true;
}

bool PrefetchParser::parseHeader() {
    // Read first 1024 bytes (minimum header size)
    file_.read(headerData_, sizeof(headerData_));
    if (file_.gcount() < 16) {
        lastError_ = "File too small to be a valid Prefetch file";
        return false;
    }

    // Detect version
    version_ = PrefetchHelpers::detectVersion(headerData_);
    if (version_ == PrefetchVersion::UNKNOWN) {
        lastError_ = "Unknown Prefetch format version";
        return false;
    }

    // Parse basic header fields based on version
    // Note: Structure varies by version, this is a simplified approach

    if (version_ >= PrefetchVersion::VERSION_30) {
        // Version 30/31 header structure
        // Based on Windows Prefetch file format specification

        // Run count at offset 0x98 (v30) or 0x98 (v31)
        runCount_ = PrefetchHelpers::readUInt32LE(headerData_ + 0x98);

        // Last run time at offset 0x80 (v30) or 0x80 (v31)
        // There are up to 8 run times, each 8 bytes
        uint64_t lastRunTimeRaw = PrefetchHelpers::readUInt64LE(headerData_ + 0x80);
        lastRunTime_ = PrefetchHelpers::filetimeToUnixTime(lastRunTimeRaw);

        // Read additional run times (up to 8)
        for (int i = 0; i < 8; ++i) {
            uint64_t runTimeRaw = PrefetchHelpers::readUInt64LE(headerData_ + 0x80 + (i * 8));
            if (runTimeRaw > 0) {
                int64_t runTime = PrefetchHelpers::filetimeToUnixTime(runTimeRaw);
                if (runTime > 0) {
                    allRunTimes_.push_back(runTime);
                }
            }
        }

        // Read file size
        file_.seekg(0, std::ios::end);
        fileSize_ = static_cast<uint32_t>(file_.tellg());
        file_.seekg(0, std::ios::beg);

    } else if (version_ >= PrefetchVersion::VERSION_23) {
        // Version 23/26 header structure
        // Based on Windows Prefetch file format specification

        // Run count at offset 0x90 (v23) or 0x90 (v26)
        runCount_ = PrefetchHelpers::readUInt32LE(headerData_ + 0x90);

        // Last run time at offset 0x78 (v23) or 0x80 (v26)
        // There are up to 8 run times, each 8 bytes
        uint64_t lastRunTimeRaw = PrefetchHelpers::readUInt64LE(headerData_ + 0x78);
        lastRunTime_ = PrefetchHelpers::filetimeToUnixTime(lastRunTimeRaw);

        // Read additional run times (up to 8)
        for (int i = 0; i < 8; ++i) {
            uint64_t runTimeRaw = PrefetchHelpers::readUInt64LE(headerData_ + 0x78 + (i * 8));
            if (runTimeRaw > 0) {
                int64_t runTime = PrefetchHelpers::filetimeToUnixTime(runTimeRaw);
                if (runTime > 0) {
                    allRunTimes_.push_back(runTime);
                }
            }
        }

        // Read file size
        file_.seekg(0, std::ios::end);
        fileSize_ = static_cast<uint32_t>(file_.tellg());
        file_.seekg(0, std::ios::beg);

    } else {
        // Version 17 (Windows XP/2003)
        // Simplified parsing for older format
        runCount_ = PrefetchHelpers::readUInt32LE(headerData_ + 8);
        uint64_t lastRunTimeRaw = PrefetchHelpers::readUInt64LE(headerData_ + 12);
        lastRunTime_ = PrefetchHelpers::filetimeToUnixTime(lastRunTimeRaw);

        file_.seekg(0, std::ios::end);
        fileSize_ = static_cast<uint32_t>(file_.tellg());
        file_.seekg(0, std::ios::beg);
    }

    // Set default values if parsing failed
    if (runCount_ == 0) runCount_ = 1;
    if (lastRunTime_ == 0) lastRunTime_ = 0;

    return true;
}

bool PrefetchParser::parseFileInformation() {
    // This method would parse detailed file information
    // For now, we've already extracted the basic info in parseHeader()
    return true;
}

bool PrefetchParser::parseRunTimes() {
    // Parse multiple run timestamps (if available)
    // Location varies by version

    if (version_ >= PrefetchVersion::VERSION_30) {
        // Version 30+ typically stores timestamps in a specific section
        // For simplicity, we'll just use the last run time
        allRunTimes_.push_back(lastRunTime_);
        return true;
    }

    // For older versions, try to find timestamp arrays
    // This is a simplified implementation
    allRunTimes_.push_back(lastRunTime_);

    return true;
}

bool PrefetchParser::parseExecutablePath() {
    // Parse the full executable path from the file
    // Location varies by version

    // Try to find executable name string in header
    // Look for common executable paths and extensions
    const char* extensions[] = {".exe", ".EXE", ".dll", ".DLL"};
    const size_t searchSize = std::min(sizeof(headerData_), size_t(512));

    for (const char* ext : extensions) {
        size_t extLen = std::strlen(ext);
        for (size_t i = 0; i < searchSize - extLen; i++) {
            if (std::memcmp(headerData_ + i, ext, extLen) == 0) {
                // Found extension, now find the start of the path
                size_t start = i;
                while (start > 0 && headerData_[start - 1] >= 32 &&
                       headerData_[start - 1] != 0) {
                    start--;
                }

                // Extract string
                std::string path(headerData_ + start, i - start + extLen);
                if (!path.empty() && path.find('\\') != std::string::npos) {
                    executablePath_ = path;
                    return true;
                }
            }
        }
    }

    // Fallback: construct path from executable name
    if (!executableName_.empty()) {
        executablePath_ = "C:\\Windows\\System32\\" + executableName_ + ".exe";
    }

    return !executablePath_.empty();
}

bool PrefetchParser::parseReferencedFiles() {
    // Parse list of files loaded by the executable
    // Prefetch file structure (v23+):
    // - Header: 84 bytes (v30/31) or 80 bytes (v23/26)
    // - Filename section: UTF-16LE executable filename
    // - File information section: metrics for each referenced file
    // - File paths section: actual file paths as UTF-16LE strings

    if (version_ < PrefetchVersion::VERSION_23) {
        return true; // Old versions don't have this
    }

    // Add the executable itself as a referenced file
    if (!executablePath_.empty()) {
        referencedFiles_.push_back(executablePath_);
    }

    // Parse the file information section
    // For v30/31: File info starts at offset 0xD0 (208)
    // For v23/26: File info starts at offset 0x64 (100)
    uint32_t fileInfoOffset = 0;
    uint32_t fileInfoSize = 0;
    uint32_t fileInfoEntrySize = 0;
    uint32_t numberOfFileEntries = 0;
    uint32_t filenameStringsOffset = 0;
    uint32_t filenameStringsSize = 0;

    if (version_ >= PrefetchVersion::VERSION_30) {
        // v30/31 offsets
        fileInfoOffset = PrefetchHelpers::readUInt32LE(headerData_ + 0x64);
        fileInfoSize = PrefetchHelpers::readUInt32LE(headerData_ + 0x68);
        filenameStringsOffset = PrefetchHelpers::readUInt32LE(headerData_ + 0x6C);
        filenameStringsSize = PrefetchHelpers::readUInt32LE(headerData_ + 0x70);
    } else {
        // v23/26 offsets
        fileInfoOffset = PrefetchHelpers::readUInt32LE(headerData_ + 0x50);
        fileInfoSize = PrefetchHelpers::readUInt32LE(headerData_ + 0x54);
        filenameStringsOffset = PrefetchHelpers::readUInt32LE(headerData_ + 0x58);
        filenameStringsSize = PrefetchHelpers::readUInt32LE(headerData_ + 0x5C);
    }

    if (fileInfoOffset == 0 || fileInfoSize == 0) {
        return true; // No file info section
    }

    // Read the file info section header
    if (!seekToOffset(fileInfoOffset)) {
        return true;
    }

    // First 4 bytes: number of file entries
    char entryCountBuf[4];
    if (!readData(entryCountBuf, 4)) {
        return true;
    }
    numberOfFileEntries = PrefetchHelpers::readUInt32LE(entryCountBuf);

    // Skip 4 bytes of padding/unknown
    char skipBuf[4];
    readData(skipBuf, 4);

    // Each entry is 32 bytes for v30/31, 28 bytes for v23/26
    fileInfoEntrySize = (version_ >= PrefetchVersion::VERSION_30) ? 32 : 28;

    // Read file entries
    for (uint32_t i = 0; i < numberOfFileEntries && i < 1000; ++i) {
        char entryBuf[32];
        if (!readData(entryBuf, fileInfoEntrySize)) {
            break;
        }

        // First 4 bytes: filename offset (relative to filenameStringsOffset)
        uint32_t filenameOffset = PrefetchHelpers::readUInt32LE(entryBuf);
        // Next 4 bytes: filename length in bytes
        uint16_t filenameLength = PrefetchHelpers::readUInt16LE(entryBuf + 4);

        if (filenameOffset > 0 && filenameLength > 0 && filenameLength < 1024) {
            // Read the filename from the filename strings section
            uint32_t absoluteOffset = filenameStringsOffset + filenameOffset;
            std::string filename = readStringAtOffset(absoluteOffset, filenameLength);

            if (!filename.empty()) {
                referencedFiles_.push_back(filename);
            }
        }
    }

    return !referencedFiles_.empty();
}

bool PrefetchParser::parseReferencedDirectories() {
    // Parse list of directories accessed by the executable
    // For v30/31: Directory strings section offset is at header offset 0x78
    // For v23/26: Directory strings section offset is at header offset 0x60

    if (version_ < PrefetchVersion::VERSION_23) {
        return true; // Older versions don't have this
    }

    // Extract directories from referenced files
    for (const auto& file : referencedFiles_) {
        size_t lastBackslash = file.find_last_of('\\');
        if (lastBackslash != std::string::npos) {
            std::string dir = file.substr(0, lastBackslash);
            // Avoid duplicates
            bool found = false;
            for (const auto& existing : referencedDirectories_) {
                if (existing == dir) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                referencedDirectories_.push_back(dir);
            }
        }
    }

    // Add the executable's directory
    if (!executablePath_.empty()) {
        size_t lastBackslash = executablePath_.find_last_of('\\');
        if (lastBackslash != std::string::npos) {
            std::string dir = executablePath_.substr(0, lastBackslash);
            bool found = false;
            for (const auto& existing : referencedDirectories_) {
                if (existing == dir) {
                    found = true;
                    break;
                }
            }
            if (!found) {
                referencedDirectories_.push_back(dir);
            }
        }
    }

    // Also try to parse the directory strings section if available
    uint32_t dirStringsOffset = 0;
    uint32_t dirStringsSize = 0;

    if (version_ >= PrefetchVersion::VERSION_30) {
        dirStringsOffset = PrefetchHelpers::readUInt32LE(headerData_ + 0x78);
        dirStringsSize = PrefetchHelpers::readUInt32LE(headerData_ + 0x7C);
    } else {
        dirStringsOffset = PrefetchHelpers::readUInt32LE(headerData_ + 0x60);
        dirStringsSize = PrefetchHelpers::readUInt32LE(headerData_ + 0x64);
    }

    if (dirStringsOffset > 0 && dirStringsSize > 0 && dirStringsSize < 65536) {
        // Parse directory strings (UTF-16LE, null-terminated)
        if (seekToOffset(dirStringsOffset)) {
            std::vector<char> dirBuffer(dirStringsSize);
            if (readData(dirBuffer.data(), dirStringsSize)) {
                // Parse UTF-16LE strings
                size_t pos = 0;
                while (pos < dirStringsSize - 1) {
                    // Find the end of this string (two null bytes)
                    size_t strEnd = pos;
                    while (strEnd < dirStringsSize - 1) {
                        if (dirBuffer[strEnd] == 0 && dirBuffer[strEnd + 1] == 0) {
                            break;
                        }
                        strEnd += 2;
                    }

                    if (strEnd > pos) {
                        // Convert UTF-16LE to ASCII (simplified)
                        std::string dirName;
                        for (size_t j = pos; j < strEnd; j += 2) {
                            char c = dirBuffer[j];
                            if (c >= 32 && c < 127) {
                                dirName += c;
                            }
                        }

                        if (!dirName.empty()) {
                            bool found = false;
                            for (const auto& existing : referencedDirectories_) {
                                if (existing == dirName) {
                                    found = true;
                                    break;
                                }
                            }
                            if (!found) {
                                referencedDirectories_.push_back(dirName);
                            }
                        }
                    }

                    pos = strEnd + 2; // Skip past the null terminator
                }
            }
        }
    }

    return !referencedDirectories_.empty();
}

bool PrefetchParser::seekToOffset(uint32_t offset) {
    if (offset >= fileSize_) {
        lastError_ = "Invalid offset";
        return false;
    }
    file_.seekg(offset, std::ios::beg);
    return true;
}

bool PrefetchParser::readData(char* buffer, size_t size) {
    file_.read(buffer, size);
    return file_.gcount() == static_cast<std::streamsize>(size);
}

std::string PrefetchParser::readStringAtOffset(uint32_t offset, uint32_t maxLength) {
    if (!seekToOffset(offset)) {
        return "";
    }

    std::vector<char> buffer(maxLength + 1);
    file_.read(buffer.data(), maxLength);
    size_t bytesRead = file_.gcount();

    // Find null terminator
    size_t length = 0;
    for (size_t i = 0; i < bytesRead; i++) {
        if (buffer[i] == 0) {
            length = i;
            break;
        }
    }

    if (length == 0) {
        length = bytesRead;
    }

    return std::string(buffer.data(), length);
}
