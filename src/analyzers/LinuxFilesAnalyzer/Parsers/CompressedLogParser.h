// CompressedLogParser.h
// Parser for compressed and rotated log files (.gz, .xz, .bz2, .zst)

#pragma once
#ifndef COMPRESSED_LOG_PARSER_H
#define COMPRESSED_LOG_PARSER_H

#include <string>
#include <vector>
#include <cstdint>
#include <regex>

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Compression type enumeration
enum class CompressionType {
    NONE,       // No compression (plain text)
    GZIP,       // .gz
    XZ,         // .xz
    BZIP2,      // .bz2
    ZSTD,       // .zst
    UNKNOWN     // Unknown or unsupported
};

// Rotated log file metadata
struct RotatedLogFile {
    std::string originalPath;      // Original path (e.g., /var/log/auth.log.2.gz)
    std::string baseName;          // Base name (e.g., auth.log)
    std::string logDirectory;      // Directory containing the file
    int rotationIndex = 0;         // Rotation index (0 = current, 1 = first rotated, etc.)
    CompressionType compression = CompressionType::NONE;
    int64_t fileSize = 0;          // File size in bytes
    int64_t mtime = 0;             // Modification time
    int64_t ctime = 0;             // Change time
    int64_t inode = 0;             // inode number
    bool isCompressed = false;
    bool isDateRotated = false;    // Date-based rotation (e.g., messages-20240101)
    std::string dateSuffix;        // Date suffix if date-rotated
};

// Compressed and rotated log parser
class CompressedLogParser {
public:
    // Enumerate rotated log files in a directory
    static std::vector<RotatedLogFile> enumerateRotatedLogs(const std::string& logDir);

    // Enumerate rotated log files matching a base name pattern
    static std::vector<RotatedLogFile> enumerateRotatedLogsForBase(
        const std::string& logDir, const std::string& baseName);

    // Decompress file and return content
    static std::string decompressFile(const std::string& filePath, CompressionType type);

    // Decompress file and return content (auto-detect compression)
    static std::string decompressFileAuto(const std::string& filePath);

    // Identify compression type from file extension
    static CompressionType identifyCompression(const std::string& filePath);

    // Identify compression type from magic bytes
    static CompressionType identifyCompressionFromMagic(const std::string& filePath);

    // Get file metadata
    static RotatedLogFile getFileMetadata(const std::string& filePath);

    // Get compression type name string
    static std::string compressionTypeToString(CompressionType type);

    // Parse rotation index from filename
    static int parseRotationIndex(const std::string& filename);

    // Parse date suffix from filename (e.g., "20240101" from "messages-20240101")
    static std::string parseDateSuffix(const std::string& filename);

    // Check if file is a rotated log
    static bool isRotatedLog(const std::string& filename);

    // Get base name from rotated log filename
    static std::string getBaseName(const std::string& filename);

private:
    // Decompression implementations
    static std::string decompressGzip(const std::string& filePath);
    static std::string decompressXz(const std::string& filePath);
    static std::string decompressBzip2(const std::string& filePath);
    static std::string decompressZstd(const std::string& filePath);

    // Read entire file into string
    static std::string readFileContents(const std::string& filePath);

    // Rotated log filename patterns
    static const std::vector<std::regex> ROTATION_PATTERNS;
};

} // namespace linux
} // namespace forensics

#endif // COMPRESSED_LOG_PARSER_H
