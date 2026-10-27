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
    // MAM stores the uncompressed size here, not the Prefetch version.
    if (std::memcmp(header + 4, "SCCA", 4) != 0) return PrefetchVersion::UNKNOWN;
    switch (readUInt32LE(header)) {
        case 17: return PrefetchVersion::VERSION_17;
        case 23: return PrefetchVersion::VERSION_23;
        case 26: return PrefetchVersion::VERSION_26;
        case 30: return PrefetchVersion::VERSION_30;
        case 31: return PrefetchVersion::VERSION_31;
        default: return PrefetchVersion::UNKNOWN;
    }
}

int64_t filetimeToUnixTime(uint64_t filetime) {
    if (filetime == 0) return 0;

    // Windows FILETIME: 100-nanosecond intervals since January 1, 1601 UTC
    // Unix timestamp: seconds since January 1, 1970 UTC
    // Difference: 11,644,473,600 seconds (369 years)
    const uint64_t TICKS_PER_SECOND = 10000000;
    const uint64_t EPOCH_DIFFERENCE = 11644473600ULL;

    return (static_cast<int64_t>(filetime / TICKS_PER_SECOND) - static_cast<int64_t>(EPOCH_DIFFERENCE));
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
    return PrefetchParser(filepath).parse();
}
} // namespace PrefetchHelpers
