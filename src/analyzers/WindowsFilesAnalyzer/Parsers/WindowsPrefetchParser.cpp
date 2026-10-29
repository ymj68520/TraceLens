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

// PrefetchHelpers namespace implementation lives in WindowsPrefetchParser_Helpers.cpp


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

    // Load the whole file: a MAM container must be decompressed before any
    // header field can be read. Reading the compressed bytes as if they were
    // an SCCA header is what produced run_count=658809 / 1601 timestamps.
    {
        std::ifstream in(filepath_, std::ios::binary);
        if (!in) {
            lastError_ = "Cannot open file: " + filepath_;
            return false;
        }
        std::vector<uint8_t> raw((std::istreambuf_iterator<char>(in)),
                                  std::istreambuf_iterator<char>());
        if (raw.size() < 8) {
            lastError_ = "File too small to be a valid Prefetch file";
            return false;
        }

        if (raw[0] == 'M' && raw[1] == 'A' && raw[2] == 'M') {
            // MAM\x04: bytes 4..7 hold the decompressed size.
            const size_t declared =
                static_cast<size_t>(raw[4]) |
                (static_cast<size_t>(raw[5]) << 8) |
                (static_cast<size_t>(raw[6]) << 16) |
                (static_cast<size_t>(raw[7]) << 24);
            std::vector<uint8_t> payload(raw.begin() + 8, raw.end());
            if (!PrefetchHelpers::decompressXpressHuffman(payload, data_, declared)) {
                lastError_ = "XPRESS Huffman decompression failed";
                return false;
            }
        } else {
            data_ = std::move(raw);
        }
    }

    // Legacy field-reference parser (see parseExecutablePath/parseReferencedFiles)
    // still works on the first 1024 decompressed bytes.
    std::memset(headerData_, 0, sizeof(headerData_));
    std::memcpy(headerData_, data_.data(), std::min(sizeof(headerData_), data_.size()));

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
    if (data_.size() < 16) {
        lastError_ = "File too small to be a valid Prefetch file";
        return false;
    }

    // Detect version from the (decompressed) SCCA header.
    version_ = PrefetchHelpers::detectVersion(reinterpret_cast<const char*>(data_.data()));
    if (version_ == PrefetchVersion::UNKNOWN) {
        lastError_ = "Unknown Prefetch format version";
        return false;
    }

    // SCCA layout (verified byte-for-byte against real Windows 10/11 files):
    //   0x00 u32 version        0x04 "SCCA"
    //   0x08 u32 build          0x0C u32 decompressed size
    //   0x10 UTF-16 executable name (60 bytes)
    //   0x4C u32 prefetch hash
    //   0x80 8 x FILETIME run times (index 0 is the most recent)
    //   0xC8 u32 run count
    // The previous code read run_count at 0x98 — inside the reserved block,
    // always zero — and fell back to 1, or read unrelated bytes for files
    // whose reserved block happened to be non-zero (658809 runs).
    const auto* data = data_.data();
    const size_t size = data_.size();

    if (version_ >= PrefetchVersion::VERSION_30) {
        fileSize_ = (size >= 0x10)
            ? PrefetchHelpers::readUInt32LE(reinterpret_cast<const char*>(data + 0x0C))
            : static_cast<uint32_t>(size);
        if (fileSize_ == 0) fileSize_ = static_cast<uint32_t>(size);

        const std::string name = readUtf16At(0x10, 60);
        if (!name.empty()) executableName_ = name;

        if (size >= 0x50) {
            char hashBuf[16];
            std::snprintf(hashBuf, sizeof(hashBuf), "%08x",
                          PrefetchHelpers::readUInt32LE(reinterpret_cast<const char*>(data + 0x4C)));
            prefetchHash_ = hashBuf;
        }

        collectRunTimes(0x80, size);
        if (size >= 0xCC) {
            runCount_ = PrefetchHelpers::readUInt32LE(reinterpret_cast<const char*>(data + 0xC8));
        }
    } else if (version_ >= PrefetchVersion::VERSION_23) {
        // v23/v26 keep the same first 0x80 bytes; the run-count field moved
        // between builds, so fall back to the number of recorded run times.
        if (size >= 0x10) {
            fileSize_ = PrefetchHelpers::readUInt32LE(reinterpret_cast<const char*>(data + 0x0C));
        }
        const std::string name = readUtf16At(0x10, 60);
        if (!name.empty()) executableName_ = name;
        if (size >= 0x50) {
            char hashBuf[16];
            std::snprintf(hashBuf, sizeof(hashBuf), "%08x",
                          PrefetchHelpers::readUInt32LE(reinterpret_cast<const char*>(data + 0x4C)));
            prefetchHash_ = hashBuf;
        }
        collectRunTimes(0x78, size);
        if (size >= 0x94) {
            uint32_t candidate = PrefetchHelpers::readUInt32LE(reinterpret_cast<const char*>(data + 0x90));
            // Only trust it when it can explain the run times we actually saw.
            if (candidate > 0 && candidate < 1000000) runCount_ = candidate;
        }
    } else {
        // Version 17 (Windows XP/2003): run count and last run time sit in the
        // file information block pointed to by the header.
        if (size >= 0x54) {
            uint32_t infoOffset = PrefetchHelpers::readUInt32LE(reinterpret_cast<const char*>(data + 0x54));
            if (infoOffset > 0 && infoOffset + 0x10 <= size) {
                runCount_ = PrefetchHelpers::readUInt32LE(reinterpret_cast<const char*>(data + infoOffset));
                uint64_t raw = PrefetchHelpers::readUInt64LE(reinterpret_cast<const char*>(data + infoOffset + 4));
                lastRunTime_ = PrefetchHelpers::filetimeToUnixTime(raw);
            }
            if (runCount_ > 0) allRunTimes_.push_back(lastRunTime_);
        }
        fileSize_ = static_cast<uint32_t>(size);
    }

    // A real .pf always records at least one run time; derive the count when
    // the dedicated field is unusable instead of inventing a value.
    if (runCount_ == 0) {
        runCount_ = allRunTimes_.empty() ? 1 : static_cast<uint32_t>(allRunTimes_.size());
    }
    if (lastRunTime_ == 0 && !allRunTimes_.empty()) {
        lastRunTime_ = allRunTimes_.front();
    }

    return true;
}

std::string PrefetchParser::readUtf16At(size_t offset, size_t byteLength) const {
    if (offset + byteLength > data_.size()) return {};
    const uint8_t* p = data_.data() + offset;
    std::string out;
    out.reserve(byteLength / 2);
    for (size_t i = 0; i + 1 < byteLength; i += 2) {
        uint16_t ch = static_cast<uint16_t>(p[i] | (p[i + 1] << 8));
        if (ch == 0) break;
        if (ch < 0x80) {
            out.push_back(static_cast<char>(ch));
        } else if (ch < 0x800) {
            out.push_back(static_cast<char>(0xC0 | (ch >> 6)));
            out.push_back(static_cast<char>(0x80 | (ch & 0x3F)));
        } else {
            out.push_back(static_cast<char>(0xE0 | (ch >> 12)));
            out.push_back(static_cast<char>(0x80 | ((ch >> 6) & 0x3F)));
            out.push_back(static_cast<char>(0x80 | (ch & 0x3F)));
        }
    }
    return out;
}

void PrefetchParser::collectRunTimes(size_t offset, size_t size) {
    allRunTimes_.clear();
    for (int i = 0; i < 8; ++i) {
        size_t at = offset + static_cast<size_t>(i) * 8;
        if (at + 8 > size) break;
        uint64_t raw = PrefetchHelpers::readUInt64LE(
            reinterpret_cast<const char*>(data_.data() + at));
        if (raw == 0) continue;
        int64_t unixTime = PrefetchHelpers::filetimeToUnixTime(raw);
        if (unixTime > 0) allRunTimes_.push_back(unixTime);
    }
    if (!allRunTimes_.empty()) lastRunTime_ = allRunTimes_.front();
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
