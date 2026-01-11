// WindowsJumpListParser.cpp
// Jump List file parser implementation using libolecf

#include "WindowsJumpListParser.h"
#include "WindowsLnkParser.h"
#include "WindowsCommonHelpers.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <cstring>
#include <algorithm>
#include <filesystem>
#include <map>

namespace fs = std::filesystem;

// ============================================================================
// Known Application IDs (common Windows applications)
// ============================================================================

static const std::map<std::string, std::string> KNOWN_APP_IDS = {
    {"1b4dd67f29cb1962", "Windows Explorer"},
    {"5d696d521de238c3", "Google Chrome"},
    {"9b9cdc69c1c24e2b", "Notepad"},
    {"918e0ecb43d17e23", "Notepad++ (64-bit)"},
    {"adecfb853d77462a", "Microsoft Word 2016"},
    {"a7bd71699cd38d1c", "Microsoft Excel 2016"},
    {"d64d36b238c843a3", "Microsoft PowerPoint 2016"},
    {"f01b4d95cf55d32a", "Windows Media Player"},
    {"fb3b0dbfee58fac8", "Microsoft Paint"},
    {"7494a606a9eef18e", "VLC Media Player"},
    {"1bc392b8e104a00e", "Remote Desktop Connection"},
    {"290532160612e071", "Windows Computer Management"},
    {"3dc02b55e44d6697", "7-Zip File Manager"},
    {"c7a4093872176c74", "FileZilla FTP Client"},
    {"be71009ff8bb02a2", "Adobe Acrobat Reader"},
    {"28c8b86deab549a1", "Internet Explorer 8/9/10/11"},
    {"16ec093b8f51508f", "VirtualBox"},
    {"e6ee34ac9913c0a9", "Visual Studio Code"},
    {"b74736c2bd8cc8a5", "WinRAR"},
    {"1cf97c38a5881255", "PuTTY"},
};

// ============================================================================
// JumpListHelpers Implementation
// ============================================================================

namespace JumpListHelpers {

bool isAutomaticDestinations(const std::string& filepath) {
    return filepath.find(".automaticDestinations-ms") != std::string::npos;
}

bool isCustomDestinations(const std::string& filepath) {
    return filepath.find(".customDestinations-ms") != std::string::npos;
}

std::string extractAppIdFromFilename(const std::string& filepath) {
    fs::path path(filepath);
    std::string filename = path.filename().string();
    
    // Find the App ID (before .automaticDestinations-ms or .customDestinations-ms)
    size_t dotPos = filename.find('.');
    if (dotPos != std::string::npos && dotPos > 0) {
        return filename.substr(0, dotPos);
    }
    return filename;
}

std::string getAppNameFromId(const std::string& appId) {
    auto it = KNOWN_APP_IDS.find(appId);
    if (it != KNOWN_APP_IDS.end()) {
        return it->second;
    }
    return "";
}

int64_t filetimeToUnixTime(uint64_t filetime) {
    return WindowsHelpers::filetimeToUnixTime(filetime);
}

} // namespace JumpListHelpers

// ============================================================================
// JumpListParser Implementation
// ============================================================================

JumpListParser::JumpListParser(const std::string& filepath)
    : filepath_(filepath),
      valid_(false),
      olecfFile_(nullptr),
      streamCount_(0),
      parsedCount_(0) {
    extractAppId();
}

JumpListParser::~JumpListParser() {
    if (olecfFile_) {
        libolecf_file_close(olecfFile_, nullptr);
        libolecf_file_free(&olecfFile_, nullptr);
        olecfFile_ = nullptr;
    }
}

void JumpListParser::extractAppId() {
    appId_ = JumpListHelpers::extractAppIdFromFilename(filepath_);
}

bool JumpListParser::parse() {
    valid_ = false;
    entries_.clear();
    lastError_.clear();
    streamCount_ = 0;
    parsedCount_ = 0;

    // Check which type of Jump List this is
    if (JumpListHelpers::isAutomaticDestinations(filepath_)) {
        return parseAutomaticDestinations();
    } else if (JumpListHelpers::isCustomDestinations(filepath_)) {
        return parseCustomDestinations();
    } else {
        setError("Unknown Jump List format");
        return false;
    }
}

bool JumpListParser::parseAutomaticDestinations() {
    AuditLog::instance().log("INFO", "JUMPLIST_PARSE_START",
        "Starting AutomaticDestinations parsing: " + filepath_);

    // Initialize libolecf file
    int result = libolecf_file_initialize(&olecfFile_, nullptr);
    if (result != 1) {
        setError("Failed to initialize libolecf file");
        return false;
    }

    // Open the OLE compound file
    result = libolecf_file_open(olecfFile_, filepath_.c_str(), LIBOLECF_OPEN_READ, nullptr);
    if (result != 1) {
        setError("Failed to open Jump List file as OLE compound file: " + filepath_);
        libolecf_file_free(&olecfFile_, nullptr);
        olecfFile_ = nullptr;
        return false;
    }

    // Get the root item
    libolecf_item_t* rootItem = nullptr;
    result = libolecf_file_get_root_item(olecfFile_, &rootItem, nullptr);
    if (result != 1 || !rootItem) {
        setError("Failed to get root item from OLE file");
        return false;
    }

    // Get number of sub-items (streams)
    int numberOfSubItems = 0;
    result = libolecf_item_get_number_of_sub_items(rootItem, &numberOfSubItems, nullptr);
    if (result != 1) {
        libolecf_item_free(&rootItem, nullptr);
        setError("Failed to get number of streams");
        return false;
    }

    streamCount_ = static_cast<size_t>(numberOfSubItems);

    // Iterate through each stream
    for (int i = 0; i < numberOfSubItems; i++) {
        libolecf_item_t* subItem = nullptr;
        result = libolecf_item_get_sub_item(rootItem, i, &subItem, nullptr);
        if (result != 1 || !subItem) {
            continue;
        }

        // Get stream name
        size_t nameSize = 0;
        result = libolecf_item_get_utf8_name_size(subItem, &nameSize, nullptr);
        
        std::string streamName = "Unknown";
        if (result == 1 && nameSize > 0) {
            std::vector<char> nameBuffer(nameSize + 1);
            result = libolecf_item_get_utf8_name(subItem, 
                reinterpret_cast<uint8_t*>(nameBuffer.data()), nameSize, nullptr);
            if (result == 1) {
                streamName = std::string(nameBuffer.data());
            }
        }

        // Skip special streams (DestList, etc.)
        if (streamName == "DestList" || streamName.empty()) {
            libolecf_item_free(&subItem, nullptr);
            continue;
        }

        // Parse this stream as an LNK file
        if (parseLnkStream(subItem, streamName)) {
            parsedCount_++;
        }

        libolecf_item_free(&subItem, nullptr);
    }

    libolecf_item_free(&rootItem, nullptr);

    valid_ = !entries_.empty();

    AuditLog::instance().log("INFO", "JUMPLIST_PARSE_COMPLETE",
        "Parsed Jump List: " + filepath_ + " - " + 
        std::to_string(parsedCount_) + "/" + std::to_string(streamCount_) + " streams");

    return valid_;
}

bool JumpListParser::parseCustomDestinations() {
    AuditLog::instance().log("INFO", "JUMPLIST_CUSTOM_START",
        "Starting CustomDestinations parsing: " + filepath_);

    // CustomDestinations files contain a series of LNK structures
    // They are NOT OLE compound files, but binary-serialized LNK collections
    
    std::ifstream file(filepath_, std::ios::binary);
    if (!file) {
        setError("Failed to open CustomDestinations file: " + filepath_);
        return false;
    }

    // Get file size
    file.seekg(0, std::ios::end);
    size_t fileSize = static_cast<size_t>(file.tellg());
    file.seekg(0, std::ios::beg);

    if (fileSize < 32) {
        setError("CustomDestinations file too small");
        return false;
    }

    // Read entire file
    std::vector<uint8_t> buffer(fileSize);
    file.read(reinterpret_cast<char*>(buffer.data()), fileSize);
    file.close();

    // Search for LNK signatures (0x0000004C at offset 0 of each LNK)
    const uint32_t LNK_SIGNATURE = 0x0000004CL;
    size_t offset = 0;
    
    while (offset + 76 < fileSize) {  // 76 = minimum LNK header size
        uint32_t signature = WindowsHelpers::readUInt32LE(buffer.data() + offset);
        
        if (signature == LNK_SIGNATURE) {
            // Found a potential LNK file
            JumpListEntry entry;
            entry.appId = appId_;
            entry.isPinned = true;  // CustomDestinations are pinned items
            entry.accessCount = 1;
            
            // Parse basic LNK header to extract what we can
            // Timestamps are at offsets 28, 36, 44 (creation, access, write)
            if (offset + 52 <= fileSize) {
                uint64_t creationTime = WindowsHelpers::readUInt64LE(buffer.data() + offset + 28);
                uint64_t accessTime = WindowsHelpers::readUInt64LE(buffer.data() + offset + 36);
                
                entry.creationTime = WindowsHelpers::filetimeToUnixTime(creationTime);
                entry.accessTime = WindowsHelpers::filetimeToUnixTime(accessTime);
            }

            entry.entryName = "Custom Destination Entry";
            entry.entryPath = "Embedded LNK at offset " + std::to_string(offset);
            
            entries_.push_back(entry);
            parsedCount_++;
            
            // Move to next potential LNK (skip at least 76 bytes)
            offset += 76;
        } else {
            offset += 4;  // Search in 4-byte increments
        }
    }

    streamCount_ = parsedCount_;
    valid_ = !entries_.empty();

    AuditLog::instance().log("INFO", "JUMPLIST_CUSTOM_COMPLETE",
        "Parsed CustomDestinations: " + filepath_ + " - found " + 
        std::to_string(parsedCount_) + " embedded LNK files");

    return valid_;
}

bool JumpListParser::parseLnkStream(libolecf_item_t* stream, const std::string& streamName) {
    // Read stream data
    std::vector<uint8_t> data = readStreamData(stream);
    if (data.size() < 76) {
        return false;  // Too small to be a valid LNK
    }

    // Verify LNK signature
    uint32_t signature = WindowsHelpers::readUInt32LE(data.data());
    if (signature != 0x0000004C) {
        return false;  // Not a valid LNK file
    }

    // Create JumpListEntry from LNK data
    JumpListEntry entry;
    entry.appId = appId_;
    entry.entryName = streamName;
    entry.isPinned = false;  // AutomaticDestinations are not pinned

    // Extract timestamps from LNK header
    // Creation time at offset 28, Access time at offset 36
    if (data.size() >= 52) {
        uint64_t creationTime = WindowsHelpers::readUInt64LE(data.data() + 28);
        uint64_t accessTime = WindowsHelpers::readUInt64LE(data.data() + 36);
        
        entry.creationTime = WindowsHelpers::filetimeToUnixTime(creationTime);
        entry.accessTime = WindowsHelpers::filetimeToUnixTime(accessTime);
    }

    // Try to extract target path from LNK data
    // This requires more complex parsing - for now use stream name
    entry.entryPath = "Stream: " + streamName;

    // Check link flags at offset 20 to determine available data
    if (data.size() >= 24) {
        uint32_t linkFlags = WindowsHelpers::readUInt32LE(data.data() + 20);
        
        // If HasLinkInfo flag is set (bit 1), we might be able to get path
        if (linkFlags & 0x02) {
            // LinkInfo structure follows after LinkTargetIDList
            // This is complex to parse inline, so we just note the flag
        }
    }

    entry.accessCount = 1;  // Default access count

    entries_.push_back(entry);
    return true;
}

std::vector<uint8_t> JumpListParser::readStreamData(libolecf_item_t* stream) {
    std::vector<uint8_t> data;
    
    // Get stream size (use uint32_t as expected by the API)
    uint32_t streamSize = 0;
    int result = libolecf_item_get_size(stream, &streamSize, nullptr);
    if (result != 1 || streamSize == 0) {
        return data;
    }

    // Cap size to prevent memory issues
    if (streamSize > 1024 * 1024) {  // 1 MB max
        streamSize = 1024 * 1024;
    }

    data.resize(static_cast<size_t>(streamSize));

    // Read stream data using libolecf_stream_read_buffer
    // Note: libolecf_stream_read_buffer takes libolecf_item_t* as first param
    ssize_t bytesRead = libolecf_stream_read_buffer(
        stream, 
        data.data(), 
        static_cast<size_t>(streamSize), 
        nullptr);
    
    if (bytesRead <= 0) {
        data.clear();
        return data;
    }

    data.resize(static_cast<size_t>(bytesRead));
    return data;
}
