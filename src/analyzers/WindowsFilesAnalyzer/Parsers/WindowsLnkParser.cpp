// LnkParser.cpp
// Implementation of Windows Shortcut (.lnk) file parser

#include "WindowsLnkParser.h"
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cstring>

// ============================================================================
// LnkHelpers Implementation
// ============================================================================

namespace LnkHelpers {

int64_t filetimeToUnixTime(uint64_t filetime) {
    if (filetime == 0) return 0;

    // Windows FILETIME: 100-nanosecond intervals since January 1, 1601 UTC
    // Unix timestamp: seconds since January 1, 1970 UTC
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

bool isValidLnkFile(const std::string& filepath) {
    std::ifstream file(filepath, std::ios::binary);
    if (!file) return false;

    char header[4];
    file.read(header, 4);
    if (file.gcount() < 4) return false;

    uint32_t signature = LnkHelpers::readUInt32LE(header);
    return signature == LNK_SIGNATURE;
}

std::string filetimeToString(uint64_t filetime) {
    if (filetime == 0) return "1970-01-01 00:00:00";

    int64_t unixTime = filetimeToUnixTime(filetime);
    std::time_t time = static_cast<std::time_t>(unixTime);
    char buffer[80];
    std::strftime(buffer, sizeof(buffer), "%Y-%m-%d %H:%M:%S", std::localtime(&time));
    return std::string(buffer);
}

std::string fileAttributesToString(uint32_t attributes) {
    std::vector<std::string> attrs;

    if (attributes & FILE_ATTRIBUTE_READONLY) attrs.push_back("READONLY");
    if (attributes & FILE_ATTRIBUTE_HIDDEN) attrs.push_back("HIDDEN");
    if (attributes & FILE_ATTRIBUTE_SYSTEM) attrs.push_back("SYSTEM");
    if (attributes & FILE_ATTRIBUTE_DIRECTORY) attrs.push_back("DIRECTORY");
    if (attributes & FILE_ATTRIBUTE_ARCHIVE) attrs.push_back("ARCHIVE");
    if (attributes & FILE_ATTRIBUTE_COMPRESSED) attrs.push_back("COMPRESSED");
    if (attributes & FILE_ATTRIBUTE_ENCRYPTED) attrs.push_back("ENCRYPTED");

    if (attrs.empty()) return "NORMAL";

    std::string result;
    for (size_t i = 0; i < attrs.size(); i++) {
        if (i > 0) result += ", ";
        result += attrs[i];
    }
    return result;
}

std::string showCommandToString(uint32_t showCommand) {
    switch (showCommand) {
        case SW_SHOWNORMAL: return "Normal";
        case SW_SHOWMAXIMIZED: return "Maximized";
        case SW_SHOWMINIMIZED: return "Minimized";
        default: return "Unknown (" + std::to_string(showCommand) + ")";
    }
}

} // namespace LnkHelpers

// ============================================================================
// LnkParser Implementation
// ============================================================================

LnkParser::LnkParser(const std::string& filepath)
    : filepath_(filepath),
      valid_(false),
      linkFlags_(0),
      creationTime_(0),
      accessTime_(0),
      writeTime_(0),
      fileSize_(0),
      fileAttributes_(0),
      showCommand_(0),
      hotKey_(0),
      linkTargetIDListOffset_(0),
      linkInfoOffset_(0),
      stringDataOffset_(0) {
}

bool LnkParser::parse() {
    valid_ = false;
    lastError_.clear();

    // Open file
    file_.open(filepath_, std::ios::binary);
    if (!file_) {
        lastError_ = "Cannot open file: " + filepath_;
        return false;
    }

    // Validate file
    if (!LnkHelpers::isValidLnkFile(filepath_)) {
        lastError_ = "Invalid LNK file signature";
        return false;
    }

    // Parse header
    if (!parseHeader()) {
        return false;
    }

    // Parse LinkTargetIDList
    if (linkFlags_ & HasLinkTargetIDList) {
        if (!parseLinkTargetIDList()) {
            // Not critical, continue
        }
    }

    // Parse LinkInfo
    if (linkFlags_ & HasLinkInfo) {
        if (!parseLinkInfo()) {
            // Not critical, continue
        }
    }

    // Parse StringData
    if (!parseStringData()) {
        // Not critical, continue
    }

    valid_ = true;
    return true;
}

bool LnkParser::parseHeader() {
    char headerData[76];
    if (!readData(headerData, sizeof(headerData))) {
        lastError_ = "Failed to read header";
        return false;
    }

    // Parse header fields
    header_.headerSize = LnkHelpers::readUInt32LE(headerData);
    if (header_.headerSize != LNK_HEADER_SIZE) {
        lastError_ = "Invalid header size";
        return false;
    }

    header_.linkCLSID = LnkHelpers::readUInt32LE(headerData + 4);
    header_.linkCLSID2 = LnkHelpers::readUInt64LE(headerData + 8);

    // Check GUID (should be CLSID_ShellLink)
    if (std::memcmp(headerData + 4, SHELL_LINK_GUID, 16) != 0) {
        lastError_ = "Invalid Shell Link GUID";
        return false;
    }

    linkFlags_ = LnkHelpers::readUInt32LE(headerData + 20);
    header_.fileAttributes = LnkHelpers::readUInt32LE(headerData + 24);
    header_.creationTime = LnkHelpers::readUInt64LE(headerData + 28);
    header_.accessTime = LnkHelpers::readUInt64LE(headerData + 36);
    header_.writeTime = LnkHelpers::readUInt64LE(headerData + 44);
    header_.fileSize = LnkHelpers::readUInt32LE(headerData + 52);
    header_.iconIndex = LnkHelpers::readUInt32LE(headerData + 56);
    header_.showCommand = LnkHelpers::readUInt32LE(headerData + 60);
    header_.hotKey = LnkHelpers::readUInt16LE(headerData + 64);
    header_.reserved1 = LnkHelpers::readUInt16LE(headerData + 66);
    header_.reserved2 = LnkHelpers::readUInt32LE(headerData + 68);
    header_.reserved3 = LnkHelpers::readUInt32LE(headerData + 72);

    // Convert timestamps
    creationTime_ = LnkHelpers::filetimeToUnixTime(header_.creationTime);
    accessTime_ = LnkHelpers::filetimeToUnixTime(header_.accessTime);
    writeTime_ = LnkHelpers::filetimeToUnixTime(header_.writeTime);

    // Copy other fields
    fileSize_ = header_.fileSize;
    fileAttributes_ = header_.fileAttributes;
    showCommand_ = header_.showCommand;
    hotKey_ = header_.hotKey;

    // Calculate offsets
    linkTargetIDListOffset_ = LNK_HEADER_SIZE;
    linkInfoOffset_ = linkTargetIDListOffset_;
    stringDataOffset_ = linkTargetIDListOffset_;

    return true;
}

bool LnkParser::parseLinkTargetIDList() {
    // Seek to LinkTargetIDList
    if (!seekToOffset(linkTargetIDListOffset_)) {
        return false;
    }

    // Read size (2 bytes)
    char sizeData[2];
    if (!readData(sizeData, 2)) {
        return false;
    }
    uint16_t idListSize = LnkHelpers::readUInt16LE(sizeData);

    // Skip IDList (we don't parse it fully in this implementation)
    if (idListSize > 2) {
        file_.seekg(idListSize - 2, std::ios::cur);
    }

    linkInfoOffset_ = linkTargetIDListOffset_ + idListSize;
    stringDataOffset_ = linkInfoOffset_;

    return true;
}

bool LnkParser::parseLinkInfo() {
    uint32_t linkInfoSize, linkInfoHeaderSize, flags;
    uint32_t volumeIDOffset, localBasePathOffset;
    uint32_t networkVolumeTableOffset, basePathOffset;

    if (!parseLinkInfoHeader(linkInfoSize, linkInfoHeaderSize, flags,
                            volumeIDOffset, localBasePathOffset,
                            networkVolumeTableOffset, basePathOffset)) {
        return false;
    }

    // Parse VolumeID if present
    if (flags & 0x01 && volumeIDOffset != 0) {
        uint32_t absOffset = linkInfoOffset_ + volumeIDOffset;
        if (!parseVolumeID(absOffset, driveType_, volumeSerial_)) {
            // Not critical
        }
    }

    // Parse NetworkVolumeTable if present
    if (flags & 0x02 && networkVolumeTableOffset != 0) {
        uint32_t absOffset = linkInfoOffset_ + networkVolumeTableOffset;
        if (!parseNetworkVolumeTable(absOffset, netBiosName_)) {
            // Not critical
        }
    }

    // Parse LocalBasePath if present
    if (flags & 0x04 && localBasePathOffset != 0) {
        uint32_t absOffset = linkInfoOffset_ + localBasePathOffset;
        if (!seekToOffset(absOffset)) {
            return false;
        }
        std::string localPath = readNullTerminatedString(260);
        if (!localPath.empty() && targetPath_.empty()) {
            targetPath_ = localPath;
        }
    }

    // Parse BasePath if present
    if (flags & 0x08 && basePathOffset != 0) {
        uint32_t absOffset = linkInfoOffset_ + basePathOffset;
        if (!seekToOffset(absOffset)) {
            return false;
        }
        std::string basePath = readNullTerminatedString(260);
        if (!basePath.empty() && targetPath_.empty()) {
            targetPath_ = basePath;
        }
    }

    // Update stringDataOffset
    stringDataOffset_ = linkInfoOffset_ + linkInfoSize;

    return true;
}

bool LnkParser::parseLinkInfoHeader(uint32_t& linkInfoSize, uint32_t& linkInfoHeaderSize,
                                    uint32_t& flags, uint32_t& volumeIDOffset,
                                    uint32_t& localBasePathOffset,
                                    uint32_t& networkVolumeTableOffset,
                                    uint32_t& basePathOffset) {
    if (!seekToOffset(linkInfoOffset_)) {
        return false;
    }

    char headerData[32];
    if (!readData(headerData, sizeof(headerData))) {
        return false;
    }

    linkInfoSize = LnkHelpers::readUInt32LE(headerData);
    linkInfoHeaderSize = LnkHelpers::readUInt32LE(headerData + 4);
    flags = LnkHelpers::readUInt32LE(headerData + 8);
    volumeIDOffset = LnkHelpers::readUInt32LE(headerData + 12);
    localBasePathOffset = LnkHelpers::readUInt32LE(headerData + 16);
    networkVolumeTableOffset = LnkHelpers::readUInt32LE(headerData + 20);
    basePathOffset = LnkHelpers::readUInt32LE(headerData + 24);

    return true;
}

bool LnkParser::parseVolumeID(uint32_t offset, std::string& driveType, std::string& serial) {
    if (!seekToOffset(offset)) {
        return false;
    }

    char headerData[8];
    if (!readData(headerData, sizeof(headerData))) {
        return false;
    }

    uint32_t volumeIDSize = LnkHelpers::readUInt32LE(headerData);
    uint32_t driveTypeEnum = LnkHelpers::readUInt32LE(headerData + 4);

    // Convert drive type to string
    switch (driveTypeEnum) {
        case 0: driveType = "Unknown"; break;
        case 1: driveType = "No root directory"; break;
        case 2: driveType = "Removable"; break;
        case 3: driveType = "Fixed"; break;
        case 4: driveType = "Remote"; break;
        case 5: driveType = "CD-ROM"; break;
        case 6: driveType = "RAM disk"; break;
        default: driveType = "Unknown"; break;
    }

    // Read volume serial number (4 bytes)
    char serialData[4];
    if (!readData(serialData, 4)) {
        return false;
    }
    uint32_t serialNum = LnkHelpers::readUInt32LE(serialData);

    // Format serial as hex
    std::ostringstream oss;
    oss << std::hex << std::setw(4) << std::setfill('0') << ((serialNum >> 16) & 0xFFFF)
       << "-"
       << std::hex << std::setw(4) << std::setfill('0') << (serialNum & 0xFFFF);
    serial = oss.str();

    return true;
}

bool LnkParser::parseNetworkVolumeTable(uint32_t offset, std::string& netBiosName) {
    if (!seekToOffset(offset)) {
        return false;
    }

    char headerData[8];
    if (!readData(headerData, sizeof(headerData))) {
        return false;
    }

    uint32_t tableSize = LnkHelpers::readUInt32LE(headerData);
    uint32_t netNameOffset = LnkHelpers::readUInt32LE(headerData + 4);

    if (netNameOffset > 0) {
        uint32_t absOffset = offset + netNameOffset;
        if (!seekToOffset(absOffset)) {
            return false;
        }
        netBiosName = readNullTerminatedString(16);
    }

    return true;
}

bool LnkParser::parseStringData() {
    uint32_t offset = stringDataOffset_;

    // Check if IsUnicode flag is set
    bool isUnicode = (linkFlags_ & IsUnicode) != 0;

    // Parse NAME_STRING
    if (linkFlags_ & HasName) {
        if (!parseString(offset, "NAME", description_)) {
            return false;
        }
    }

    // Parse RELATIVE_PATH
    if (linkFlags_ & HasRelativePath) {
        if (!parseString(offset, "RELATIVE_PATH", relativePath_)) {
            return false;
        }
    }

    // Parse WORKING_DIR
    if (linkFlags_ & HasWorkingDir) {
        if (!parseString(offset, "WORKING_DIR", workingDirectory_)) {
            return false;
        }
    }

    // Parse ARGUMENTS
    if (linkFlags_ & HasArguments) {
        if (!parseString(offset, "ARGUMENTS", arguments_)) {
            return false;
        }
    }

    // Parse ICON_LOCATION
    if (linkFlags_ & HasIconLocation) {
        if (!parseString(offset, "ICON_LOCATION", iconLocation_)) {
            return false;
        }
    }

    return true;
}

bool LnkParser::parseString(uint32_t& offset, const std::string& name, std::string& result) {
    if (!seekToOffset(offset)) {
        return false;
    }

    // Read string size (2 bytes)
    char sizeData[2];
    if (!readData(sizeData, 2)) {
        return false;
    }
    uint16_t size = LnkHelpers::readUInt16LE(sizeData);

    if (size == 0) {
        offset += 2;
        return true; // Empty string is OK
    }

    // Read string data
    std::vector<char> buffer(size);
    if (!readData(buffer.data(), size)) {
        return false;
    }

    // Check if unicode (null bytes between characters)
    bool isUnicode = false;
    if (size >= 2) {
        isUnicode = (buffer[1] == 0);
    }

    if (isUnicode) {
        // Convert UTF-16LE to string
        std::wstring wideStr;
        for (size_t i = 0; i < size - 1; i += 2) {
            wchar_t c = static_cast<wchar_t>(
                static_cast<unsigned char>(buffer[i]) |
                (static_cast<unsigned char>(buffer[i+1]) << 8)
            );
            if (c == 0) break;
            wideStr += c;
        }
        // Simple conversion (narrowing to char)
        for (wchar_t c : wideStr) {
            if (c < 128) {
                result += static_cast<char>(c);
            } else {
                result += '?'; // Replace non-ASCII
            }
        }
    } else {
        result = std::string(buffer.data(), size);
    }

    offset += 2 + size;
    return true;
}

bool LnkParser::parseStringsWithCount() {
    // This is an alternative format where strings are stored with count
    // Not implemented in this version
    return true;
}

bool LnkParser::seekToOffset(uint32_t offset) {
    file_.seekg(offset, std::ios::beg);
    if (!file_) {
        lastError_ = "Failed to seek to offset " + std::to_string(offset);
        return false;
    }
    return true;
}

bool LnkParser::readData(char* buffer, size_t size) {
    file_.read(buffer, size);
    if (file_.gcount() != static_cast<std::streamsize>(size)) {
        lastError_ = "Failed to read " + std::to_string(size) + " bytes";
        return false;
    }
    return true;
}

std::string LnkParser::readNullTerminatedString(uint32_t maxLength) {
    std::vector<char> buffer(maxLength);
    file_.read(buffer.data(), maxLength);

    size_t length = 0;
    for (size_t i = 0; i < maxLength && i < static_cast<size_t>(file_.gcount()); i++) {
        if (buffer[i] == 0) {
            length = i;
            break;
        }
    }

    if (length == 0 && file_.gcount() > 0) {
        length = static_cast<size_t>(file_.gcount());
    }

    return std::string(buffer.data(), length);
}

std::string LnkParser::readLengthPrefixedString(uint16_t isUnicode) {
    // Read length (2 bytes)
    char sizeData[2];
    if (!readData(sizeData, 2)) {
        return "";
    }
    uint16_t size = LnkHelpers::readUInt16LE(sizeData);

    if (size == 0) return "";

    // Read string
    std::vector<char> buffer(size);
    if (!readData(buffer.data(), size)) {
        return "";
    }

    if (isUnicode) {
        // Convert UTF-16LE to ASCII (simplified)
        std::string result;
        for (size_t i = 0; i < size - 1; i += 2) {
            char c = buffer[i];
            if (c == 0) break;
            result += c;
        }
        return result;
    } else {
        return std::string(buffer.data(), size);
    }
}
