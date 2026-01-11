// WindowsRegistryParser.cpp
// Implementation of Registry parsing logic using hivex library

#include "WindowsFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <cstring>
#include <sstream>
#include <iomanip>
#include <regex>
#include <iostream>
#include <strings.h> // for strcasecmp
#include <vector>
#include <functional>

// hivex library
#include <hivex.h>

namespace {

// RAII Wrapper for hive_h
class HiveHandle {
public:
    HiveHandle(const std::string& path, int flags = 0) {
        handle_ = hivex_open(path.c_str(), flags);
    }
    
    ~HiveHandle() {
        if (handle_) {
            hivex_close(handle_);
        }
    }
    
    // Prevent copying
    HiveHandle(const HiveHandle&) = delete;
    HiveHandle& operator=(const HiveHandle&) = delete;
    
    // Allow moving
    HiveHandle(HiveHandle&& other) noexcept : handle_(other.handle_) {
        other.handle_ = nullptr;
    }
    
    HiveHandle& operator=(HiveHandle&& other) noexcept {
        if (this != &other) {
            if (handle_) hivex_close(handle_);
            handle_ = other.handle_;
            other.handle_ = nullptr;
        }
        return *this;
    }
    
    bool isValid() const { return handle_ != nullptr; }
    
    hive_h* get() const { return handle_; }
    
    // Implicit conversion to hive_h* for easier usage with existing helper functions
    operator hive_h*() const { return handle_; }

private:
    hive_h* handle_ = nullptr;
};

// Helper: Convert UTF-16LE to UTF-8
std::string convertUTF16LEToUTF8(const char* data, size_t len) {
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

// Helper: Get value type name
std::string getValueTypeName(hive_type type) {
    switch (type) {
        case hive_t_REG_NONE:       return "REG_NONE";
        case hive_t_REG_SZ:         return "REG_SZ";
        case hive_t_REG_EXPAND_SZ:  return "REG_EXPAND_SZ";
        case hive_t_REG_BINARY:     return "REG_BINARY";
        case hive_t_REG_DWORD:      return "REG_DWORD";
        case hive_t_REG_DWORD_BIG_ENDIAN: return "REG_DWORD_BE";
        case hive_t_REG_LINK:       return "REG_LINK";
        case hive_t_REG_MULTI_SZ:   return "REG_MULTI_SZ";
        case hive_t_REG_RESOURCE_LIST: return "REG_RESOURCE_LIST";
        case hive_t_REG_FULL_RESOURCE_DESCRIPTOR: return "REG_FULL_RESOURCE_DESCRIPTOR";
        case hive_t_REG_RESOURCE_REQUIREMENTS_LIST: return "REG_RESOURCE_REQUIREMENTS_LIST";
        case hive_t_REG_QWORD:      return "REG_QWORD";
        default:                    return "REG_UNKNOWN";
    }
}

// Helper: Convert value data to string representation
std::string convertValueData(const char* data, size_t len, hive_type type) {
    if (!data || len == 0) return "";
    
    switch (type) {
        case hive_t_REG_SZ:
        case hive_t_REG_EXPAND_SZ:
        case hive_t_REG_LINK:
            return convertUTF16LEToUTF8(data, len);
        
        case hive_t_REG_MULTI_SZ: {
            std::string result;
            size_t start = 0;
            for (size_t i = 0; i + 1 < len; i += 2) {
                uint16_t ch = static_cast<uint8_t>(data[i]) | 
                              (static_cast<uint8_t>(data[i + 1]) << 8);
                if (ch == 0) {
                    if (i > start) {
                        if (!result.empty()) result += "|";
                        result += convertUTF16LEToUTF8(data + start, i - start);
                    }
                    start = i + 2;
                }
            }
            return result;
        }
        
        case hive_t_REG_DWORD:
            if (len >= 4) {
                uint32_t value = *reinterpret_cast<const uint32_t*>(data);
                return std::to_string(value);
            }
            break;
        
        case hive_t_REG_QWORD:
            if (len >= 8) {
                uint64_t value = *reinterpret_cast<const uint64_t*>(data);
                return std::to_string(value);
            }
            break;
        
        case hive_t_REG_BINARY:
        default: {
            std::ostringstream oss;
            oss << std::hex << std::setfill('0');
            for (size_t i = 0; i < len && i < 64; i++) {
                oss << std::setw(2) << static_cast<int>(static_cast<uint8_t>(data[i]));
                if (i < len - 1) oss << " ";
            }
            if (len > 64) oss << "...";
            return oss.str();
        }
    }
    return "";
}

// Helper: Determine forensic importance
std::string determineForensicImportance(const std::string& keyPath, const std::string& valueName) {
    static const std::vector<std::string> highImportancePaths = {
        "Run", "RunOnce", "Services", "USBSTOR", "MountedDevices", 
        "NetworkList", "TypedURLs", "RecentDocs", "UserAssist", "ShellBags", "MuiCache",
        "SAM\\Domains\\Account\\Users"
    };
    
    for (const auto& keyword : highImportancePaths) {
        if (keyPath.find(keyword) != std::string::npos) {
            return "HIGH";
        }
    }
    
    static const std::vector<std::string> mediumImportancePaths = {
        "Software\\Microsoft", "CurrentVersion", "Policies", "Explorer"
    };
    
    for (const auto& keyword : mediumImportancePaths) {
        if (keyPath.find(keyword) != std::string::npos) {
            return "MEDIUM";
        }
    }
    
    return "LOW";
}

// Helper: Convert FILETIME to Unix Timestamp
int64_t filetimeToUnixTime(uint64_t filetime) {
    if (filetime == 0 || filetime == 0x7FFFFFFFFFFFFFFF) return 0;
    const uint64_t EPOCH_DIFF = 116444736000000000ULL;
    if (filetime < EPOCH_DIFF) return 0;
    return static_cast<int64_t>((filetime - EPOCH_DIFF) / 10000000ULL);
}

// Helper: Navigate to path
hive_node_h navigateToPath(hive_h* hive, hive_node_h start, const std::string& path) {
    hive_node_h current = start;
    std::string segment;
    std::istringstream ss(path);
    
    while (std::getline(ss, segment, '\\')) {
        if (segment.empty()) continue;
        
        hive_node_h* children = hivex_node_children(hive, current);
        if (!children) return 0;
        
        bool found = false;
        for (int i = 0; children[i] != 0; i++) {
            char* name = hivex_node_name(hive, children[i]);
            if (name) {
                if (strcasecmp(name, segment.c_str()) == 0) {
                    current = children[i];
                    found = true;
                }
                free(name);
                if (found) break;
            }
        }
        free(children);
        if (!found) return 0;
    }
    return current;
}

// Helper: Read string value
std::string readStringValue(hive_h* hive, hive_node_h node, const std::string& valueName) {
    hive_value_h value = hivex_node_get_value(hive, node, valueName.c_str());
    if (value == 0) return "";
    
    hive_type type;
    size_t len;
    char* data = hivex_value_value(hive, value, &type, &len);
    
    std::string result;
    if (data) {
        if (type == hive_t_REG_SZ || type == hive_t_REG_EXPAND_SZ) {
            result = convertUTF16LEToUTF8(data, len);
        } else if (type == hive_t_REG_DWORD && len >= 4) {
            result = std::to_string(*reinterpret_cast<uint32_t*>(data));
        }
        free(data);
    }
    return result;
}

// Helper: Read DWORD value
int32_t readDwordValue(hive_h* hive, hive_node_h node, const std::string& valueName) {
    hive_value_h value = hivex_node_get_value(hive, node, valueName.c_str());
    if (value == 0) return -1;
    
    hive_type type;
    size_t len;
    char* data = hivex_value_value(hive, value, &type, &len);
    
    int32_t result = -1;
    if (data && type == hive_t_REG_DWORD && len >= 4) {
        result = *reinterpret_cast<int32_t*>(data);
    }
    if (data) free(data);
    return result;
}

// Helper: Parse device type name
void parseDeviceTypeName(const std::string& name, USBDeviceInfo& info) {
    std::regex vendorRegex("Ven_([^&]+)");
    std::regex productRegex("Prod_([^&]+)");
    
    std::smatch match;
    if (std::regex_search(name, match, vendorRegex)) {
        info.vendorId = match[1].str();
    }
    if (std::regex_search(name, match, productRegex)) {
        info.productId = match[1].str();
    }
}

// Helper: Convert start type
std::string convertStartType(int32_t startType) {
    switch (startType) {
        case 0: return "Boot";
        case 1: return "System";
        case 2: return "Auto";
        case 3: return "Manual";
        case 4: return "Disabled";
        default: return "Unknown";
    }
}

// Helper: Convert service type
std::string convertServiceType(int32_t serviceType) {
    if (serviceType & 0x01) return "KernelDriver";
    if (serviceType & 0x02) return "FileSystemDriver";
    if (serviceType & 0x10) return "OwnProcess";
    if (serviceType & 0x20) return "ShareProcess";
    return "Unknown";
}

// Helper: Parse account flags
std::string parseAccountFlags(uint16_t flags) {
    std::vector<std::string> flagList;
    if (flags & 0x0001) flagList.push_back("Disabled");
    if (flags & 0x0004) flagList.push_back("PasswordNotRequired");
    if (flags & 0x0010) flagList.push_back("NormalAccount");
    if (flags & 0x0200) flagList.push_back("PasswordNeverExpires");
    if (flags & 0x0400) flagList.push_back("AutoLocked");
    
    std::string result;
    for (size_t i = 0; i < flagList.size(); i++) {
        if (i > 0) result += ",";
        result += flagList[i];
    }
    return result.empty() ? "None" : result;
}

// Helper: Parse user F Value
void parseUserFValue(hive_h* hive, hive_node_h userNode, WindowsUserInfo& user) {
    hive_value_h fValue = hivex_node_get_value(hive, userNode, "F");
    if (fValue == 0) return;
    
    hive_type type;
    size_t len;
    char* data = hivex_value_value(hive, fValue, &type, &len);
    
    if (data && len >= 0x38) {
        uint64_t lastLogonFT = *reinterpret_cast<uint64_t*>(data + 0x08);
        user.lastLogin = filetimeToUnixTime(lastLogonFT);
        
        uint64_t pwdLastSetFT = *reinterpret_cast<uint64_t*>(data + 0x18);
        user.passwordLastSet = filetimeToUnixTime(pwdLastSetFT);
        
        uint64_t accountExpiresFT = *reinterpret_cast<uint64_t*>(data + 0x20);
        user.accountExpires = filetimeToUnixTime(accountExpiresFT);
        
        if (len >= 0x3A) {
            uint16_t flags = *reinterpret_cast<uint16_t*>(data + 0x38);
            user.accountFlags = parseAccountFlags(flags);
        }
    }
    if (data) free(data);
}

// Helper: Parse user V Value
void parseUserVValue(hive_h* hive, hive_node_h userNode, WindowsUserInfo& user) {
    hive_value_h vValue = hivex_node_get_value(hive, userNode, "V");
    if (vValue == 0) return;
    
    hive_type type;
    size_t len;
    char* data = hivex_value_value(hive, vValue, &type, &len);
    
    if (data && len > 0xCC) {
        uint32_t fullNameOffset = *reinterpret_cast<uint32_t*>(data + 0x0C) + 0xCC;
        uint32_t fullNameLen = *reinterpret_cast<uint32_t*>(data + 0x10);
        
        if (fullNameOffset + fullNameLen <= len && fullNameLen > 0) {
            user.fullName = convertUTF16LEToUTF8(data + fullNameOffset, fullNameLen);
        }
        
        uint32_t commentOffset = *reinterpret_cast<uint32_t*>(data + 0x18) + 0xCC;
        uint32_t commentLen = *reinterpret_cast<uint32_t*>(data + 0x1C);
        
        if (commentOffset + commentLen <= len && commentLen > 0) {
            user.comment = convertUTF16LEToUTF8(data + commentOffset, commentLen);
        }
    }
    if (data) free(data);
}

} // namespace


void WindowsFilesAnalyzer::analyzeRegistryHives() {
    std::cout << "Analyzing Registry Hives..." << std::endl;
    
    // 1. Analyze SYSTEM Hive
    // System hive is usually at Windows/System32/config/SYSTEM
    std::vector<FileRecord> systemHives = queryFilesByPattern("%/System32/config/SYSTEM");
    for (const auto& hive : systemHives) {
        std::string extractPath = getExtractPath("registry/" + std::to_string(hive.inode) + "_SYSTEM");
        std::cout << "  Found SYSTEM hive: " << hive.path << std::endl;
        
        if (extractFileToPath(hive.inode, extractPath)) {
            auto values = parseRegistryHive(extractPath, "SYSTEM");
            windowsDb_->insertRegistryValues(values);
            
            // Also parse specific artifacts from SYSTEM
            auto usbDevices = parseUSBDevicesFromRegistry(extractPath);
            for (const auto& usb : usbDevices) {
                windowsDb_->insertUSBDevice(usb);
            }
            
            auto services = parseServicesFromRegistry(extractPath);
            for (const auto& svc : services) {
                windowsDb_->insertWindowsService(svc);
            }
        }
    }
    
    // 2. Analyze SAM Hive
    // SAM hive is usually at Windows/System32/config/SAM
    std::vector<FileRecord> samHives = queryFilesByPattern("%/System32/config/SAM");
    for (const auto& hive : samHives) {
        std::string extractPath = getExtractPath("registry/" + std::to_string(hive.inode) + "_SAM");
        std::cout << "  Found SAM hive: " << hive.path << std::endl;
        
        if (extractFileToPath(hive.inode, extractPath)) {
            auto values = parseRegistryHive(extractPath, "SAM");
            windowsDb_->insertRegistryValues(values);
            
            auto users = parseUserAccountsFromSAM(extractPath);
            for (const auto& user : users) {
                windowsDb_->insertUserInfo(user);
            }
        }
    }
    
    // 3. Analyze SOFTWARE Hive
    std::vector<FileRecord> softwareHives = queryFilesByPattern("%/System32/config/SOFTWARE");
    for (const auto& hive : softwareHives) {
        std::string extractPath = getExtractPath("registry/" + std::to_string(hive.inode) + "_SOFTWARE");
        
        if (extractFileToPath(hive.inode, extractPath)) {
            auto values = parseRegistryHive(extractPath, "SOFTWARE");
            windowsDb_->insertRegistryValues(values);
        }
    }
    
    // 4. Analyze NTUSER.DAT (User Registry)
    // Located in Users/<Username>/NTUSER.DAT
    std::vector<FileRecord> userHives = queryFilesByPattern("%/Users/%/NTUSER.DAT");
    for (const auto& hive : userHives) {
        std::string extractPath = getExtractPath("registry/users/" + std::to_string(hive.inode) + "_NTUSER.DAT");
        std::cout << "  Found User hive: " << hive.path << std::endl;
        
        if (extractFileToPath(hive.inode, extractPath)) {
            auto values = parseRegistryHive(extractPath, "NTUSER");
            windowsDb_->insertRegistryValues(values);
        }
    }
}

std::vector<RegistryValue> WindowsFilesAnalyzer::parseRegistryHive(const std::string& hivePath, 
                                              const std::string& hiveType) {
    std::vector<RegistryValue> values;
    
    HiveHandle hive(hivePath);
    if (!hive.isValid()) {
        std::cerr << "Failed to open hive: " << hivePath << std::endl;
        return values;
    }
    
    hive_node_h root = hivex_root(hive);
    if (root == 0) {
        return values;
    }
    
    // Recursive traversal function
    std::function<void(hive_node_h, const std::string&)> traverseNode;
    traverseNode = [&](hive_node_h node, const std::string& currentPath) {
        char* nodeNameStr = hivex_node_name(hive, node);
        std::string nodeName = nodeNameStr ? nodeNameStr : "";
        if (nodeNameStr) free(nodeNameStr);
        
        std::string path = currentPath.empty() ? 
            nodeName : 
            currentPath + "\\" + nodeName;
        
        // Get values
        hive_value_h* nodeValues = hivex_node_values(hive, node);
        if (nodeValues) {
            for (int i = 0; nodeValues[i] != 0; i++) {
                RegistryValue regVal;
                regVal.hivePath = hivePath;
                regVal.hiveType = hiveType;
                regVal.keyPath = path;
                
                char* valueNameStr = hivex_value_key(hive, nodeValues[i]);
                regVal.valueName = valueNameStr ? valueNameStr : "(Default)";
                if (valueNameStr) free(valueNameStr);
                
                hive_type valueType;
                size_t dataLen;
                char* data = hivex_value_value(hive, nodeValues[i], &valueType, &dataLen);
                
                regVal.valueType = getValueTypeName(valueType);
                regVal.valueData = convertValueData(data, dataLen, valueType);
                if (data) free(data);
                
                regVal.forensicImportance = determineForensicImportance(path, regVal.valueName);
                regVal.lastModified = hivex_node_timestamp(hive, node); // Node timestamp applies to the key
                
                values.push_back(regVal);
            }
            free(nodeValues);
        }
        
        // Recurse children
        hive_node_h* children = hivex_node_children(hive, node);
        if (children) {
            for (int i = 0; children[i] != 0; i++) {
                traverseNode(children[i], path);
            }
            free(children);
        }
    };
    
    traverseNode(root, "");
    return values;
}

std::vector<WindowsUserInfo> WindowsFilesAnalyzer::parseUserAccountsFromSAM(const std::string& samPath) {
    std::vector<WindowsUserInfo> users;
    
    HiveHandle hive(samPath);
    if (!hive.isValid()) return users;
    
    hive_node_h root = hivex_root(hive);
    if (root == 0) {
        return users;
    }
    
    hive_node_h namesNode = navigateToPath(hive, root, "SAM\\Domains\\Account\\Users\\Names");
    hive_node_h usersNode = navigateToPath(hive, root, "SAM\\Domains\\Account\\Users");
    
    if (namesNode == 0 || usersNode == 0) {
        return users;
    }
    
    hive_node_h* nameNodes = hivex_node_children(hive, namesNode);
    if (nameNodes) {
        for (int i = 0; nameNodes[i] != 0; i++) {
            WindowsUserInfo user;
            
            char* username = hivex_node_name(hive, nameNodes[i]);
            user.username = username ? username : "";
            if (username) free(username);
            
            hive_value_h defaultValue = hivex_node_get_value(hive, nameNodes[i], "");
            if (defaultValue != 0) {
                hive_type type;
                size_t len;
                if (hivex_value_type(hive, defaultValue, &type, &len) == 0) {
                    user.rid = static_cast<int>(type);
                }
            }
            
            char ridPath[32];
            snprintf(ridPath, sizeof(ridPath), "%08X", user.rid);
            
            hive_node_h* userChildren = hivex_node_children(hive, usersNode);
            hive_node_h userNode = 0;
            if (userChildren) {
                for (int j = 0; userChildren[j] != 0; j++) {
                    char* nodeName = hivex_node_name(hive, userChildren[j]);
                    if (nodeName && strcasecmp(nodeName, ridPath) == 0) {
                        userNode = userChildren[j];
                    }
                    if (nodeName) free(nodeName);
                    if (userNode != 0) break;
                }
                free(userChildren);
            }
            
            if (userNode != 0) {
                parseUserFValue(hive, userNode, user);
                parseUserVValue(hive, userNode, user);
            }
            
            user.isAdmin = (user.rid == 500);
            users.push_back(user);
        }
        free(nameNodes);
    }
    
    return users;
}

std::vector<USBDeviceInfo> WindowsFilesAnalyzer::parseUSBDevicesFromRegistry(const std::string& systemPath) {
    std::vector<USBDeviceInfo> devices;
    
    HiveHandle hive(systemPath);
    if (!hive.isValid()) return devices;
    
    hive_node_h root = hivex_root(hive);
    if (root == 0) {
        return devices;
    }
    
    hive_node_h usbstorNode = navigateToPath(hive, root, "ControlSet001\\Enum\\USBSTOR");
    if (usbstorNode == 0) {
        return devices;
    }
    
    hive_node_h* deviceTypes = hivex_node_children(hive, usbstorNode);
    if (deviceTypes) {
        for (int i = 0; deviceTypes[i] != 0; i++) {
            char* deviceTypeName = hivex_node_name(hive, deviceTypes[i]);
            
            USBDeviceInfo baseInfo;
            if (deviceTypeName) {
                parseDeviceTypeName(deviceTypeName, baseInfo);
            }
            
            hive_node_h* instances = hivex_node_children(hive, deviceTypes[i]);
            if (instances) {
                for (int j = 0; instances[j] != 0; j++) {
                    USBDeviceInfo device = baseInfo;
                    
                    char* serialNum = hivex_node_name(hive, instances[j]);
                    device.serialNumber = serialNum ? serialNum : "";
                    if (serialNum) free(serialNum);
                    
                    device.friendlyName = readStringValue(hive, instances[j], "FriendlyName");
                    device.deviceDescription = readStringValue(hive, instances[j], "DeviceDesc");
                    device.deviceClass = readStringValue(hive, instances[j], "Class");
                    if (device.deviceClass.empty()) {
                        device.deviceClass = "Storage";
                    }
                    
                    devices.push_back(device);
                }
                free(instances);
            }
             if (deviceTypeName) free(deviceTypeName);
        }
        free(deviceTypes);
    }
    
    return devices;
}

std::vector<WindowsServiceInfo> WindowsFilesAnalyzer::parseServicesFromRegistry(const std::string& systemPath) {
    std::vector<WindowsServiceInfo> services;
    
    HiveHandle hive(systemPath);
    if (!hive.isValid()) return services;
    
    hive_node_h root = hivex_root(hive);
    if (root == 0) {
        return services;
    }
    
    hive_node_h servicesNode = navigateToPath(hive, root, "ControlSet001\\Services");
    if (servicesNode == 0) {
        return services;
    }
    
    hive_node_h* serviceNodes = hivex_node_children(hive, servicesNode);
    if (serviceNodes) {
        for (int i = 0; serviceNodes[i] != 0; i++) {
            WindowsServiceInfo svc;
            
            char* serviceName = hivex_node_name(hive, serviceNodes[i]);
            svc.serviceName = serviceName ? serviceName : "";
            if (serviceName) free(serviceName);
            
            svc.displayName = readStringValue(hive, serviceNodes[i], "DisplayName");
            svc.imagePath = readStringValue(hive, serviceNodes[i], "ImagePath");
            svc.description = readStringValue(hive, serviceNodes[i], "Description");
            svc.accountName = readStringValue(hive, serviceNodes[i], "ObjectName");
            
            int32_t startType = readDwordValue(hive, serviceNodes[i], "Start");
            svc.startType = convertStartType(startType);
            
            int32_t serviceType = readDwordValue(hive, serviceNodes[i], "Type");
            svc.serviceType = convertServiceType(serviceType);
            
            svc.isRunning = false; // Cannot determine from registry
            
            if (!svc.serviceName.empty()) {
                services.push_back(svc);
            }
        }
        free(serviceNodes);
    }
    
    return services;
}
