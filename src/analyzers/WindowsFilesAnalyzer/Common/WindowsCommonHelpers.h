// WindowsCommonHelpers.h
// Common helper functions for Windows forensic analysis
// Consolidates utility functions used across multiple parsers

#pragma once
#ifndef WINDOWS_COMMON_HELPERS_H
#define WINDOWS_COMMON_HELPERS_H

#include <cstdint>
#include <string>
#include <sstream>
#include <iomanip>

namespace WindowsHelpers {

// ============================================================================
// Time Conversion Functions
// ============================================================================

/**
 * Convert Windows FILETIME to Unix timestamp
 * Windows FILETIME: 100-nanosecond intervals since January 1, 1601 UTC
 * Unix timestamp: seconds since January 1, 1970 UTC
 * 
 * @param filetime Windows FILETIME value
 * @return Unix timestamp (seconds since epoch), 0 if invalid
 */
inline int64_t filetimeToUnixTime(uint64_t filetime) {
    if (filetime == 0 || filetime == 0x7FFFFFFFFFFFFFFF) return 0;
    
    const uint64_t TICKS_PER_SECOND = 10000000ULL;
    const uint64_t EPOCH_DIFFERENCE = 11644473600ULL;
    
    // Check for underflow
    if (filetime / TICKS_PER_SECOND < EPOCH_DIFFERENCE) return 0;
    
    return static_cast<int64_t>((filetime / TICKS_PER_SECOND) - EPOCH_DIFFERENCE);
}

/**
 * Convert Chrome timestamp to Unix timestamp
 * Chrome uses WebKit time (microseconds since January 1, 1601)
 * 
 * @param chromeTime Chrome/WebKit timestamp
 * @return Unix timestamp (seconds since epoch)
 */
inline int64_t chromeTimeToUnixTime(int64_t chromeTime) {
    if (chromeTime == 0) return 0;
    
    // Chrome/WebKit time is microseconds since 1601-01-01
    const int64_t EPOCH_DIFFERENCE_MICROSECONDS = 11644473600000000LL;
    
    if (chromeTime < EPOCH_DIFFERENCE_MICROSECONDS) return 0;
    
    return (chromeTime - EPOCH_DIFFERENCE_MICROSECONDS) / 1000000;
}

/**
 * Convert Firefox timestamp to Unix timestamp  
 * Firefox uses microseconds since Unix epoch
 * 
 * @param firefoxTime Firefox timestamp (microseconds)
 * @return Unix timestamp (seconds since epoch)
 */
inline int64_t firefoxTimeToUnixTime(int64_t firefoxTime) {
    if (firefoxTime == 0) return 0;
    return firefoxTime / 1000000;
}

// ============================================================================
// Binary Reading Functions (Little Endian)
// ============================================================================

/**
 * Read 16-bit unsigned integer from little-endian bytes
 */
inline uint16_t readUInt16LE(const char* data) {
    return static_cast<uint16_t>(
        static_cast<unsigned char>(data[0]) |
        (static_cast<unsigned char>(data[1]) << 8)
    );
}

inline uint16_t readUInt16LE(const uint8_t* data) {
    return static_cast<uint16_t>(data[0] | (data[1] << 8));
}

/**
 * Read 32-bit unsigned integer from little-endian bytes
 */
inline uint32_t readUInt32LE(const char* data) {
    return static_cast<uint32_t>(
        static_cast<unsigned char>(data[0]) |
        (static_cast<unsigned char>(data[1]) << 8) |
        (static_cast<unsigned char>(data[2]) << 16) |
        (static_cast<unsigned char>(data[3]) << 24)
    );
}

inline uint32_t readUInt32LE(const uint8_t* data) {
    return static_cast<uint32_t>(
        data[0] | (data[1] << 8) | (data[2] << 16) | (data[3] << 24)
    );
}

/**
 * Read 64-bit unsigned integer from little-endian bytes
 */
inline uint64_t readUInt64LE(const char* data) {
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

inline uint64_t readUInt64LE(const uint8_t* data) {
    return static_cast<uint64_t>(
        static_cast<uint64_t>(data[0]) |
        (static_cast<uint64_t>(data[1]) << 8) |
        (static_cast<uint64_t>(data[2]) << 16) |
        (static_cast<uint64_t>(data[3]) << 24) |
        (static_cast<uint64_t>(data[4]) << 32) |
        (static_cast<uint64_t>(data[5]) << 40) |
        (static_cast<uint64_t>(data[6]) << 48) |
        (static_cast<uint64_t>(data[7]) << 56)
    );
}

// ============================================================================
// String Conversion Functions
// ============================================================================

/**
 * Convert UTF-16LE bytes to UTF-8 string
 * This is commonly needed for Windows registry values and file paths
 * 
 * @param data Pointer to UTF-16LE data
 * @param len Length of data in bytes
 * @return UTF-8 encoded string
 */
inline std::string convertUTF16LEToUTF8(const char* data, size_t len) {
    if (!data || len < 2) return "";
    
    std::string result;
    result.reserve(len);
    
    for (size_t i = 0; i + 1 < len; i += 2) {
        uint16_t ch = static_cast<uint8_t>(data[i]) | 
                      (static_cast<uint8_t>(data[i + 1]) << 8);
        
        if (ch == 0) break;  // Null terminator
        
        if (ch < 0x80) {
            // ASCII
            result.push_back(static_cast<char>(ch));
        } else if (ch < 0x800) {
            // 2-byte UTF-8
            result.push_back(static_cast<char>(0xC0 | (ch >> 6)));
            result.push_back(static_cast<char>(0x80 | (ch & 0x3F)));
        } else {
            // 3-byte UTF-8
            result.push_back(static_cast<char>(0xE0 | (ch >> 12)));
            result.push_back(static_cast<char>(0x80 | ((ch >> 6) & 0x3F)));
            result.push_back(static_cast<char>(0x80 | (ch & 0x3F)));
        }
    }
    
    return result;
}

/**
 * Read null-terminated ASCII/UTF-8 string
 * 
 * @param data Pointer to string data
 * @param maxLen Maximum length to read
 * @return String value
 */
inline std::string readNullTerminatedString(const char* data, size_t maxLen) {
    size_t len = 0;
    while (len < maxLen && data[len] != 0) {
        len++;
    }
    return std::string(data, len);
}

/**
 * Read null-terminated UTF-16LE string
 * 
 * @param data Pointer to UTF-16LE data
 * @param maxLen Maximum length in bytes
 * @return UTF-8 encoded string
 */
inline std::string readUTF16LEString(const char* data, size_t maxLen) {
    std::string result;
    for (size_t i = 0; i + 1 < maxLen; i += 2) {
        char c = data[i];
        if (c == 0 && data[i+1] == 0) break; // null terminator
        
        if (data[i+1] == 0 && c > 0 && c < 127) {
            result += c;
        } else {
            result += '?'; // Replace non-ASCII with ?
        }
    }
    return result;
}

// ============================================================================
// Formatting Functions
// ============================================================================

/**
 * Format bytes as hex string
 * 
 * @param data Pointer to binary data
 * @param len Length of data
 * @param maxDisplay Maximum bytes to display (truncate with "..." if longer)
 * @return Hex string representation
 */
inline std::string formatAsHex(const uint8_t* data, size_t len, size_t maxDisplay = 64) {
    std::ostringstream oss;
    oss << std::hex << std::setfill('0');
    
    size_t displayLen = (len < maxDisplay) ? len : maxDisplay;
    for (size_t i = 0; i < displayLen; i++) {
        oss << std::setw(2) << static_cast<int>(data[i]);
        if (i < displayLen - 1) oss << " ";
    }
    
    if (len > maxDisplay) oss << "...";
    
    return oss.str();
}

/**
 * Format SHA-1 hash bytes as string
 */
inline std::string formatSHA1Hash(const uint8_t* hash, size_t length = 20) {
    std::ostringstream oss;
    size_t displayLen = (length < 20) ? length : 20;
    for (size_t i = 0; i < displayLen; i++) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(hash[i]);
    }
    return oss.str();
}

// ============================================================================
// Path Utility Functions
// ============================================================================

/**
 * Extract filename from path
 */
inline std::string extractFileName(const std::string& path) {
    size_t lastSlash = path.find_last_of("\\/");
    if (lastSlash != std::string::npos) {
        return path.substr(lastSlash + 1);
    }
    return path;
}

/**
 * Extract directory from path
 */
inline std::string extractDirectory(const std::string& path) {
    size_t lastSlash = path.find_last_of("\\/");
    if (lastSlash != std::string::npos) {
        return path.substr(0, lastSlash);
    }
    return "";
}

/**
 * Normalize Windows path (replace backslash with forward slash)
 */
inline std::string normalizeWindowsPath(const std::string& path) {
    std::string normalized = path;
    
    // Replace backslashes with forward slashes
    for (char& c : normalized) {
        if (c == '\\') c = '/';
    }
    
    // Remove drive letter if present (e.g., "C:/" -> "/")
    if (normalized.length() >= 2 && std::isalpha(normalized[0]) && normalized[1] == ':') {
        normalized = normalized.substr(2);
    }
    
    // Ensure path starts with forward slash
    if (!normalized.empty() && normalized[0] != '/') {
        normalized = "/" + normalized;
    }
    
    return normalized;
}

} // namespace WindowsHelpers

#endif // WINDOWS_COMMON_HELPERS_H
