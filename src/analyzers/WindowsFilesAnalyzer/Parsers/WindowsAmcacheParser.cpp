// AmcacheParser.cpp
// Implementation of Windows Amcache.hve file parser

#include "WindowsAmcacheParser.h"
#include "AuditLog/AuditLog.h"
#include <hivex.h>
#include <cstring>
#include <sstream>
#include <iomanip>
#include <algorithm>

// ============================================================================
// AmcacheHelpers Implementation
// ============================================================================

namespace AmcacheHelpers {

int64_t filetimeToUnixTime(uint64_t filetime) {
    if (filetime == 0) return 0;

    // Windows FILETIME: 100-nanosecond intervals since January 1, 1601 UTC
    // Unix timestamp: seconds since January 1, 1970 UTC
    const uint64_t TICKS_PER_SECOND = 10000000;
    const uint64_t EPOCH_DIFFERENCE = 11644473600ULL;

    return static_cast<int64_t>((filetime / TICKS_PER_SECOND) - EPOCH_DIFFERENCE);
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

std::string formatHash(const uint8_t* hash, size_t length) {
    std::ostringstream oss;
    for (size_t i = 0; i < length && i < 20; i++) {
        oss << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(hash[i]);
    }
    return oss.str();
}

std::string extractFileName(const std::string& filePath) {
    size_t lastBackslash = filePath.find_last_of("\\/");
    if (lastBackslash != std::string::npos) {
        return filePath.substr(lastBackslash + 1);
    }
    return filePath;
}

bool isValidSHA1Hash(const std::string& hash) {
    if (hash.length() != 40) return false;
    for (char c : hash) {
        if (!std::isxdigit(c)) return false;
    }
    return true;
}

} // namespace AmcacheHelpers

// ============================================================================
// AmcacheParser Implementation
// ============================================================================

AmcacheParser::AmcacheParser(const std::string& hivePath)
    : hivePath_(hivePath),
      hiveFile_(nullptr),
      valid_(false),
      totalKeys_(0),
      parsedKeys_(0) {
}

AmcacheParser::~AmcacheParser() {
    closeHive();
}

bool AmcacheParser::parse() {
    valid_ = false;
    lastError_.clear();
    totalKeys_ = 0;
    parsedKeys_ = 0;

    AuditLog::instance().log("SYSTEM", "AMCACHE_PARSE_START",
        "Starting Amcache.hve parsing: " + hivePath_);

    // Open the hive file
    if (!openHive()) {
        return false;
    }

    // Parse InventoryApplicationFile (main application execution data)
    if (!parseInventoryApplicationFile()) {
        AuditLog::instance().log("WARNING", "AMCACHE_APPFILE_PARSE_FAILED",
            "Failed to parse InventoryApplicationFile");
        // Continue anyway
    }

    // Parse InventoryApplicationObject (optional application objects)
    if (!parseInventoryApplicationObject()) {
        AuditLog::instance().log("INFO", "AMCACHE_APPOBJECT_PARSE_FAILED",
            "No InventoryApplicationObject data found");
    }

    AuditLog::instance().log("SYSTEM", "AMCACHE_PARSE_COMPLETE",
        "Successfully parsed Amcache.hve: " + hivePath_ +
        " - Parsed " + std::to_string(entries_.size()) + " entries");

    valid_ = true;
    return true;
}

bool AmcacheParser::parseInventoryApplicationFile() {
    // Open Root\InventoryApplicationFile key
    hive_node_h rootKey = openKey("Root\\InventoryApplicationFile");
    if (rootKey == 0) {
        lastError_ = "Failed to open InventoryApplicationFile key";
        return false;
    }

    size_t numSubKeys = getNumberOfSubKeys(rootKey);
    AuditLog::instance().log("INFO", "AMCACHE_APPFILE_KEYS",
        "Found " + std::to_string(numSubKeys) + " application entries");

    // Iterate through all subkeys (each subkey is a SHA-1 hash)
    for (size_t i = 0; i < numSubKeys; i++) {
        hive_node_h appKey = getSubKey(rootKey, i);
        if (appKey == 0) continue;

        // Parse this application key
        if (parseApplicationKey(appKey, hiveFile_)) {
            parsedKeys_++;
        }

        totalKeys_++;
    }

    return true;
}

bool AmcacheParser::parseInventoryApplicationObject() {
    // Open Root\InventoryApplicationObject key
    hive_node_h rootKey = openKey("Root\\InventoryApplicationObject");
    if (rootKey == 0) {
        return false; // This key may not exist in all versions
    }

    size_t numSubKeys = getNumberOfSubKeys(rootKey);

    // Iterate through application objects
    for (size_t i = 0; i < numSubKeys; i++) {
        hive_node_h objKey = getSubKey(rootKey, i);
        if (objKey == 0) continue;

        // Parse this object key (similar structure to InventoryApplicationFile)
        parseApplicationKey(objKey, hiveFile_);
    }

    return true;
}

bool AmcacheParser::parseApplicationKey(hive_node_h node, hive_h* hive) {
    AmcacheEntry entry;

    // Get key name (should be SHA-1 hash)
    char* keyName = hivex_node_name(hive, node);
    if (!keyName) {
        return false;
    }

    entry.fileHash = std::string(keyName);
    free(keyName);

    if (!AmcacheHelpers::isValidSHA1Hash(entry.fileHash)) {
        return false; // Skip invalid hashes
    }

    // Read registry values
    entry.filePath = readStringValue(node, "15"); // Value 15 contains file path

    // If value 15 doesn't exist, try value 1
    if (entry.filePath.empty()) {
        entry.filePath = readStringValue(node, "1");
    }

    // If still empty, try "0" value
    if (entry.filePath.empty()) {
        entry.filePath = readStringValue(node, "0");
    }

    // Skip if no file path
    if (entry.filePath.empty()) {
        return false;
    }

    entry.fileName = AmcacheHelpers::extractFileName(entry.filePath);

    // Read other values
    entry.companyName = readStringValue(node, "100"); // Company name
    entry.productName = readStringValue(node, "101"); // Product name
    entry.productVersion = readStringValue(node, "102"); // Product version
    entry.fileDescription = readStringValue(node, "103"); // File description
    entry.language = readStringValue(node, "104"); // Language

    // Read file size (value 16)
    std::vector<uint8_t> sizeData = readBinaryValue(node, "16");
    if (sizeData.size() >= 8) {
        entry.fileSize = static_cast<int64_t>(AmcacheHelpers::readUInt64LE(
            reinterpret_cast<const char*>(sizeData.data())));
    } else {
        entry.fileSize = 0;
    }

    // Read link time (value 17) - FILETIME format
    std::vector<uint8_t> linkTimeData = readBinaryValue(node, "17");
    if (linkTimeData.size() >= 8) {
        uint64_t filetime = AmcacheHelpers::readUInt64LE(
            reinterpret_cast<const char*>(linkTimeData.data()));
        entry.linkTime = AmcacheHelpers::filetimeToUnixTime(filetime);
    } else {
        entry.linkTime = 0;
    }

    // Read last modified time (value 18) - FILETIME format
    std::vector<uint8_t> modTimeData = readBinaryValue(node, "18");
    if (modTimeData.size() >= 8) {
        uint64_t filetime = AmcacheHelpers::readUInt64LE(
            reinterpret_cast<const char*>(modTimeData.data()));
        entry.lastModified = AmcacheHelpers::filetimeToUnixTime(filetime);
    } else {
        entry.lastModified = 0;
    }

    entries_.push_back(entry);
    return true;
}

// ============================================================================
// Registry Helper Methods
// ============================================================================

bool AmcacheParser::openHive() {
    hiveFile_ = hivex_open(hivePath_.c_str(), 0);  // 0 = default flags (read-only)
    if (!hiveFile_) {
        lastError_ = "Failed to open Amcache hive file";
        return false;
    }
    return true;
}

void AmcacheParser::closeHive() {
    if (hiveFile_) {
        hivex_close(hiveFile_);
        hiveFile_ = nullptr;
    }
}

hive_node_h AmcacheParser::openKey(const std::string& path) {
    if (!hiveFile_) {
        return 0;
    }

    // Start at root
    hive_node_h currentNode = hivex_root(hiveFile_);
    if (currentNode == 0) {
        return 0;
    }

    // Split path by backslash and traverse
    std::string::size_type start = 0;
    std::string::size_type end = path.find('\\');

    while (true) {
        std::string componentName;

        if (end == std::string::npos) {
            componentName = path.substr(start);
        } else {
            componentName = path.substr(start, end - start);
        }

        if (!componentName.empty()) {
            currentNode = hivex_node_get_child(hiveFile_, currentNode, componentName.c_str());
            if (currentNode == 0) {
                return 0;
            }
        }

        if (end == std::string::npos) {
            break;
        }

        start = end + 1;
        end = path.find('\\', start);
    }

    return currentNode;
}

size_t AmcacheParser::getNumberOfSubKeys(hive_node_h node) {
    return hivex_node_nr_children(hiveFile_, node);
}

hive_node_h AmcacheParser::getSubKey(hive_node_h parent, size_t index) {
    hive_node_h* children = hivex_node_children(hiveFile_, parent);
    if (!children) {
        return 0;
    }

    // Get the child at index
    size_t numChildren = hivex_node_nr_children(hiveFile_, parent);
    if (index >= numChildren) {
        free(children);
        return 0;
    }

    hive_node_h result = children[index];
    free(children);
    return result;
}

std::string AmcacheParser::readStringValue(hive_node_h node, const std::string& valueName) {
    if (!hiveFile_) {
        return "";
    }

    hive_value_h value = hivex_node_get_value(hiveFile_, node, valueName.c_str());
    if (value == 0) {
        return "";
    }

    // Get the string value
    char* str = hivex_value_string(hiveFile_, value);
    std::string result;

    if (str) {
        result = std::string(str);
        free(str);
    }

    return result;
}

std::vector<uint8_t> AmcacheParser::readBinaryValue(hive_node_h node, const std::string& valueName) {
    if (!hiveFile_) {
        return {};
    }

    hive_value_h value = hivex_node_get_value(hiveFile_, node, valueName.c_str());
    if (value == 0) {
        return {};
    }

    // Get the value data
    hive_type t;
    size_t len;
    char* data = hivex_value_value(hiveFile_, value, &t, &len);

    if (!data) {
        return {};
    }

    // Copy data to vector
    std::vector<uint8_t> result(data, data + len);
    free(data);

    return result;
}

uint32_t AmcacheParser::readUInt32Value(hive_node_h node, const std::string& valueName) {
    std::vector<uint8_t> data = readBinaryValue(node, valueName);
    if (data.size() < 4) {
        return 0;
    }
    return AmcacheHelpers::readUInt32LE(reinterpret_cast<const char*>(data.data()));
}

uint64_t AmcacheParser::readUInt64Value(hive_node_h node, const std::string& valueName) {
    std::vector<uint8_t> data = readBinaryValue(node, valueName);
    if (data.size() < 8) {
        return 0;
    }
    return AmcacheHelpers::readUInt64LE(reinterpret_cast<const char*>(data.data()));
}
