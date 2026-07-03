// CompressedLogParser.cpp
// Implementation of compressed and rotated log file parser

#ifdef linux
#undef linux
#endif

#include "CompressedLogParser.h"

#include <fstream>
#include <sstream>
#include <filesystem>
#include <algorithm>
#include <cstring>
#include <iostream>
#include <sys/stat.h>

// Compression library headers
#ifdef HAVE_ZLIB
#include <zlib.h>
#endif

#ifdef HAVE_LIBLZMA
#include <lzma.h>
#endif

#ifdef HAVE_BZIP2
#include <bzlib.h>
#endif

#ifdef HAVE_ZSTD
#include <zstd.h>
#endif

namespace forensics {
namespace linux {

namespace fs = std::filesystem;

// ============================================================================
// Rotated log filename patterns
// ============================================================================

// Common rotation patterns:
// auth.log.1, auth.log.2.gz, auth.log.3.xz
// syslog.1, syslog.2.gz
// messages-20240101, messages-20240101.gz
// audit.log.1, audit.log.2.bz2
// kern.log.1

const std::vector<std::regex> CompressedLogParser::ROTATION_PATTERNS = {
    // Pattern: base.N or base.N.ext (e.g., auth.log.1, auth.log.2.gz)
    std::regex(R"(^(.+)\.(\d+)(\.(gz|xz|bz2|zst))?$)"),
    // Pattern: base-YYYYMMDD or base-YYYYMMDD.ext (e.g., messages-20240101)
    std::regex(R"(^(.+)-(\d{8})(\.(gz|xz|bz2|zst))?$)"),
    // Pattern: base.YYYYMMDD or base.YYYYMMDD.ext
    std::regex(R"(^(.+)\.(\d{8})(\.(gz|xz|bz2|zst))?$)"),
    // Pattern: base.1.ext (e.g., syslog.1.gz)
    std::regex(R"(^(.+)\.(\d+)\.(gz|xz|bz2|zst)$)")
};

// ============================================================================
// Compression type identification
// ============================================================================

CompressionType CompressedLogParser::identifyCompression(const std::string& filePath) {
    // Check by extension first
    std::string ext;
    size_t dotPos = filePath.rfind('.');
    if (dotPos != std::string::npos) {
        ext = filePath.substr(dotPos);
        // Convert to lowercase
        std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    }

    if (ext == ".gz") return CompressionType::GZIP;
    if (ext == ".xz") return CompressionType::XZ;
    if (ext == ".bz2") return CompressionType::BZIP2;
    if (ext == ".zst") return CompressionType::ZSTD;

    // Extensions that ARE compression/archive formats but are unsupported here:
    // report UNKNOWN rather than falling through to a plain-text read.
    if (ext == ".zip" || ext == ".7z" || ext == ".rar" ||
        ext == ".lz4" || ext == ".lzma" || ext == ".z") {
        return CompressionType::UNKNOWN;
    }

    // If no recognized extension, try magic bytes
    return identifyCompressionFromMagic(filePath);
}

CompressionType CompressedLogParser::identifyCompressionFromMagic(const std::string& filePath) {
    std::ifstream file(filePath, std::ios::binary);
    // A file we cannot open has no detectable compression signature; treat it as
    // plain (NONE). Unsupported archive extensions are already mapped to UNKNOWN
    // by identifyCompression() before reaching here.
    if (!file.is_open()) return CompressionType::NONE;

    unsigned char magic[16] = {0};
    file.read(reinterpret_cast<char*>(magic), sizeof(magic));
    size_t bytesRead = file.gcount();
    file.close();

    if (bytesRead < 2) return CompressionType::NONE;

    // gzip magic: 1f 8b
    if (magic[0] == 0x1f && magic[1] == 0x8b) return CompressionType::GZIP;

    // xz magic: fd 37 7a 58 5a 00
    if (bytesRead >= 6 && magic[0] == 0xfd && magic[1] == 0x37 &&
        magic[2] == 0x7a && magic[3] == 0x58 && magic[4] == 0x5a && magic[5] == 0x00) {
        return CompressionType::XZ;
    }

    // bzip2 magic: 42 5a 68 ("BZh")
    if (magic[0] == 0x42 && magic[1] == 0x5a && magic[2] == 0x68) return CompressionType::BZIP2;

    // zstd magic: 28 b5 2f fd
    if (bytesRead >= 4 && magic[0] == 0x28 && magic[1] == 0xb5 &&
        magic[2] == 0x2f && magic[3] == 0xfd) {
        return CompressionType::ZSTD;
    }

    return CompressionType::NONE;
}

std::string CompressedLogParser::compressionTypeToString(CompressionType type) {
    switch (type) {
        case CompressionType::NONE: return "none";
        case CompressionType::GZIP: return "gzip";
        case CompressionType::XZ: return "xz";
        case CompressionType::BZIP2: return "bzip2";
        case CompressionType::ZSTD: return "zstd";
        default: return "unknown";
    }
}

// ============================================================================
// Rotated log detection
// ============================================================================

bool CompressedLogParser::isRotatedLog(const std::string& filename) {
    // Skip . and ..
    if (filename == "." || filename == "..") return false;

    for (const auto& pattern : ROTATION_PATTERNS) {
        if (std::regex_match(filename, pattern)) {
            return true;
        }
    }
    return false;
}

std::string CompressedLogParser::getBaseName(const std::string& filename) {
    // Try each pattern
    std::smatch matches;

    // Pattern: base.N or base.N.ext
    if (std::regex_match(filename, matches, ROTATION_PATTERNS[0])) {
        return matches[1].str();
    }

    // Pattern: base-YYYYMMDD or base-YYYYMMDD.ext
    if (std::regex_match(filename, matches, ROTATION_PATTERNS[1])) {
        return matches[1].str();
    }

    // Pattern: base.YYYYMMDD or base.YYYYMMDD.ext
    if (std::regex_match(filename, matches, ROTATION_PATTERNS[2])) {
        return matches[1].str();
    }

    // Pattern: base.1.ext
    if (std::regex_match(filename, matches, ROTATION_PATTERNS[3])) {
        return matches[1].str();
    }

    return filename;
}

int CompressedLogParser::parseRotationIndex(const std::string& filename) {
    std::smatch matches;

    // Pattern: base.N or base.N.ext
    if (std::regex_match(filename, matches, ROTATION_PATTERNS[0])) {
        try {
            return std::stoi(matches[2].str());
        } catch (...) {
            return -1;
        }
    }

    // Pattern: base.1.ext
    if (std::regex_match(filename, matches, ROTATION_PATTERNS[3])) {
        try {
            return std::stoi(matches[2].str());
        } catch (...) {
            return -1;
        }
    }

    return -1;
}

std::string CompressedLogParser::parseDateSuffix(const std::string& filename) {
    std::smatch matches;

    // Pattern: base-YYYYMMDD or base-YYYYMMDD.ext
    if (std::regex_match(filename, matches, ROTATION_PATTERNS[1])) {
        return matches[2].str();
    }

    // Pattern: base.YYYYMMDD or base.YYYYMMDD.ext
    if (std::regex_match(filename, matches, ROTATION_PATTERNS[2])) {
        return matches[2].str();
    }

    return "";
}

// ============================================================================
// File metadata
// ============================================================================

RotatedLogFile CompressedLogParser::getFileMetadata(const std::string& filePath) {
    RotatedLogFile info;
    info.originalPath = filePath;

    try {
        fs::path path(filePath);
        info.logDirectory = path.parent_path().string();
        std::string filename = path.filename().string();

        // Get base name
        info.baseName = getBaseName(filename);

        // Get compression type
        info.compression = identifyCompression(filePath);
        info.isCompressed = (info.compression != CompressionType::NONE);

        // Get rotation index
        info.rotationIndex = parseRotationIndex(filename);
        if (info.rotationIndex < 0) info.rotationIndex = 0;

        // Get date suffix
        info.dateSuffix = parseDateSuffix(filename);
        info.isDateRotated = !info.dateSuffix.empty();

        // Get file stats
        if (fs::exists(path)) {
            info.fileSize = fs::file_size(path);
            auto lastWrite = fs::last_write_time(path);
            auto sctp = std::chrono::time_point_cast<std::chrono::system_clock::duration>(
                lastWrite - fs::file_time_type::clock::now() + std::chrono::system_clock::now());
            info.mtime = std::chrono::system_clock::to_time_t(sctp);

            // Get inode (POSIX only)
            struct stat st;
            if (stat(filePath.c_str(), &st) == 0) {
                info.inode = st.st_ino;
                info.ctime = st.st_ctime;
            }
        }
    } catch (const std::exception& e) {
        std::cerr << "Error getting file metadata for " << filePath << ": " << e.what() << std::endl;
    }

    return info;
}

// ============================================================================
// Rotated log enumeration
// ============================================================================

std::vector<RotatedLogFile> CompressedLogParser::enumerateRotatedLogs(const std::string& logDir) {
    std::vector<RotatedLogFile> result;

    try {
        if (!fs::exists(logDir) || !fs::is_directory(logDir)) {
            return result;
        }

        for (const auto& entry : fs::directory_iterator(logDir)) {
            if (!entry.is_regular_file()) continue;

            std::string filename = entry.path().filename().string();

            if (isRotatedLog(filename)) {
                RotatedLogFile info = getFileMetadata(entry.path().string());
                result.push_back(info);
            }
        }

        // Sort by base name, then by rotation index (newest first)
        std::sort(result.begin(), result.end(), [](const RotatedLogFile& a, const RotatedLogFile& b) {
            if (a.baseName != b.baseName) return a.baseName < b.baseName;
            return a.rotationIndex < b.rotationIndex;
        });

    } catch (const std::exception& e) {
        std::cerr << "Error enumerating rotated logs in " << logDir << ": " << e.what() << std::endl;
    }

    return result;
}

std::vector<RotatedLogFile> CompressedLogParser::enumerateRotatedLogsForBase(
    const std::string& logDir, const std::string& baseName) {

    auto allLogs = enumerateRotatedLogs(logDir);
    std::vector<RotatedLogFile> result;

    for (const auto& log : allLogs) {
        if (log.baseName == baseName) {
            result.push_back(log);
        }
    }

    return result;
}

// ============================================================================
// Decompression
// ============================================================================

std::string CompressedLogParser::readFileContents(const std::string& filePath) {
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) return "";

    std::ostringstream content;
    content << file.rdbuf();
    return content.str();
}

std::string CompressedLogParser::decompressFileAuto(const std::string& filePath) {
    CompressionType type = identifyCompression(filePath);
    return decompressFile(filePath, type);
}

std::string CompressedLogParser::decompressFile(const std::string& filePath, CompressionType type) {
    switch (type) {
        case CompressionType::NONE:
            return readFileContents(filePath);
        case CompressionType::GZIP:
            return decompressGzip(filePath);
        case CompressionType::XZ:
            return decompressXz(filePath);
        case CompressionType::BZIP2:
            return decompressBzip2(filePath);
        case CompressionType::ZSTD:
            return decompressZstd(filePath);
        default:
            std::cerr << "Unsupported compression type for " << filePath << std::endl;
            return "";
    }
}

// ============================================================================
// gzip decompression
// ============================================================================

std::string CompressedLogParser::decompressGzip(const std::string& filePath) {
#ifdef HAVE_ZLIB
    gzFile gz = gzopen(filePath.c_str(), "rb");
    if (!gz) {
        std::cerr << "Failed to open gzip file: " << filePath << std::endl;
        return "";
    }

    std::string result;
    char buffer[65536];
    int bytesRead;

    while ((bytesRead = gzread(gz, buffer, sizeof(buffer))) > 0) {
        result.append(buffer, bytesRead);
    }

    gzclose(gz);
    return result;
#else
    std::cerr << "gzip support not compiled in" << std::endl;
    return "";
#endif
}

// ============================================================================
// xz decompression
// ============================================================================

std::string CompressedLogParser::decompressXz(const std::string& filePath) {
#ifdef HAVE_LIBLZMA
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "Failed to open xz file: " << filePath << std::endl;
        return "";
    }

    // Read compressed data
    std::ostringstream compressed;
    compressed << file.rdbuf();
    std::string compressedData = compressed.str();

    // Initialize decoder
    lzma_stream strm = LZMA_STREAM_INIT;
    lzma_ret ret = lzma_stream_decoder(&strm, UINT64_MAX, LZMA_CONCATENATED);
    if (ret != LZMA_OK) {
        std::cerr << "Failed to initialize xz decoder" << std::endl;
        return "";
    }

    // Decompress
    std::string result;
    char outBuffer[65536];

    strm.next_in = reinterpret_cast<const uint8_t*>(compressedData.data());
    strm.avail_in = compressedData.size();

    do {
        strm.next_out = reinterpret_cast<uint8_t*>(outBuffer);
        strm.avail_out = sizeof(outBuffer);

        ret = lzma_code(&strm, LZMA_FINISH);

        if (ret != LZMA_OK && ret != LZMA_STREAM_END) {
            std::cerr << "xz decompression error: " << ret << std::endl;
            lzma_end(&strm);
            return "";
        }

        size_t bytesWritten = sizeof(outBuffer) - strm.avail_out;
        result.append(outBuffer, bytesWritten);

    } while (ret != LZMA_STREAM_END);

    lzma_end(&strm);
    return result;
#else
    std::cerr << "xz support not compiled in" << std::endl;
    return "";
#endif
}

// ============================================================================
// bzip2 decompression
// ============================================================================

std::string CompressedLogParser::decompressBzip2(const std::string& filePath) {
#ifdef HAVE_BZIP2
    FILE* f = fopen(filePath.c_str(), "rb");
    if (!f) {
        std::cerr << "Failed to open bzip2 file: " << filePath << std::endl;
        return "";
    }

    int bzError;
    BZFILE* bz = BZ2_bzReadOpen(&bzError, f, 0, 0, nullptr, 0);
    if (bz == nullptr) {
        std::cerr << "Failed to open bzip2 stream: " << bzError << std::endl;
        fclose(f);
        return "";
    }

    std::string result;
    char buffer[65536];
    int bytesRead;

    while ((bytesRead = BZ2_bzRead(&bzError, bz, buffer, sizeof(buffer))) > 0) {
        result.append(buffer, bytesRead);
    }

    BZ2_bzReadClose(&bzError, bz);
    fclose(f);

    if (bzError != BZ_STREAM_END) {
        std::cerr << "bzip2 decompression error: " << bzError << std::endl;
        return "";
    }

    return result;
#else
    std::cerr << "bzip2 support not compiled in" << std::endl;
    return "";
#endif
}

// ============================================================================
// zstd decompression
// ============================================================================

std::string CompressedLogParser::decompressZstd(const std::string& filePath) {
#ifdef HAVE_ZSTD
    std::ifstream file(filePath, std::ios::binary);
    if (!file.is_open()) {
        std::cerr << "Failed to open zstd file: " << filePath << std::endl;
        return "";
    }

    // Read compressed data
    std::ostringstream compressed;
    compressed << file.rdbuf();
    std::string compressedData = compressed.str();

    // Get decompressed size
    unsigned long long const decompressedSize = ZSTD_getFrameContentSize(
        compressedData.data(), compressedData.size());

    if (decompressedSize == ZSTD_CONTENTSIZE_ERROR) {
        std::cerr << "Not a valid zstd file: " << filePath << std::endl;
        return "";
    }

    if (decompressedSize == ZSTD_CONTENTSIZE_UNKNOWN) {
        // Streaming decompression for unknown size
        ZSTD_DStream* dstream = ZSTD_createDStream();
        if (!dstream) return "";

        ZSTD_initDStream(dstream);

        std::string result;
        char outBuffer[65536];

        ZSTD_inBuffer input = {compressedData.data(), compressedData.size(), 0};

        while (input.pos < input.size) {
            ZSTD_outBuffer output = {outBuffer, sizeof(outBuffer), 0};
            size_t ret = ZSTD_decompressStream(dstream, &output, &input);

            if (ZSTD_isError(ret)) {
                std::cerr << "zstd decompression error: " << ZSTD_getErrorName(ret) << std::endl;
                ZSTD_freeDStream(dstream);
                return "";
            }

            result.append(outBuffer, output.pos);
        }

        ZSTD_freeDStream(dstream);
        return result;
    }

    // Known size - single shot decompression
    std::string result(decompressedSize, '\0');
    size_t const actualSize = ZSTD_decompress(
        &result[0], decompressedSize,
        compressedData.data(), compressedData.size());

    if (ZSTD_isError(actualSize)) {
        std::cerr << "zstd decompression error: " << ZSTD_getErrorName(actualSize) << std::endl;
        return "";
    }

    result.resize(actualSize);
    return result;
#else
    std::cerr << "zstd support not compiled in" << std::endl;
    return "";
#endif
}

} // namespace linux
} // namespace forensics
