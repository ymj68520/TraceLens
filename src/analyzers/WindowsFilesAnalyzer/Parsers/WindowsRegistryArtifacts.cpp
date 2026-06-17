// WindowsRegistryArtifacts.cpp
// Per-artifact Windows registry parsers, extracted from WindowsRegistryParser.cpp.
//
// Contains the domain-specific parse* methods of WindowsFilesAnalyzer that read
// specific registry hives (SAM user accounts, USB devices, services, WiFi
// profiles, RDP connections, shimcache/AppCompatCache, UserAssist). Shared hive
// helpers come from WindowsRegistryHelpers.h (namespace WindowsRegistry).

#include "WindowsFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include <cstring>
#include <sstream>
#include <string>
#include <vector>

// hivex library
#include <hivex.h>

#include "WindowsRegistryHelpers.h"

// Bring shared hive helpers into scope (defined inline in WindowsRegistryHelpers.h)
using namespace WindowsRegistry;

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

// WiFi Profile parsing from SOFTWARE registry hive
std::vector<WiFiProfileInfo> WindowsFilesAnalyzer::parseWiFiProfilesFromRegistry(const std::string& softwarePath) {
    std::vector<WiFiProfileInfo> profiles;

    HiveHandle hive(softwarePath);
    if (!hive.isValid()) return profiles;

    hive_node_h root = hivex_root(hive);
    if (root == 0) return profiles;

    // Navigate to NetworkList\Profiles
    hive_node_h profilesNode = navigateToPath(hive, root,
        "Microsoft\\Windows NT\\CurrentVersion\\NetworkList\\Profiles");
    if (profilesNode == 0) return profiles;

    // Enumerate profile GUIDs
    hive_node_h* profileNodes = hivex_node_children(hive, profilesNode);
    if (!profileNodes) return profiles;

    for (int i = 0; profileNodes[i] != 0; i++) {
        WiFiProfileInfo profile;
        char* guidName = hivex_node_name(hive, profileNodes[i]);
        if (guidName) {
            profile.sourceHive = softwarePath;
            free(guidName);
        }

        // Read profile properties
        profile.profileName = readStringValue(hive, profileNodes[i], "ProfileName");
        profile.connectionType = readStringValue(hive, profileNodes[i], "ConnectionType");

        // Read connection mode (DWORD)
        int32_t connMode = readDwordValue(hive, profileNodes[i], "ConnectionMode");
        if (connMode >= 0) {
            profile.connectionMode = (connMode == 0) ? "Auto" : "Manual";
        }

        // Read timestamps (binary FILETIME)
        hive_value_h dateCreatedVal = hivex_node_get_value(hive, profileNodes[i], "DateCreated");
        if (dateCreatedVal != 0) {
            hive_type type;
            size_t len;
            char* data = hivex_value_value(hive, dateCreatedVal, &type, &len);
            if (data && type == hive_t_REG_BINARY && len >= 8) {
                profile.firstConnected = *reinterpret_cast<uint64_t*>(data);
            }
            if (data) free(data);
        }

        hive_value_h dateLastConnVal = hivex_node_get_value(hive, profileNodes[i], "DateLastConnected");
        if (dateLastConnVal != 0) {
            hive_type type;
            size_t len;
            char* data = hivex_value_value(hive, dateLastConnVal, &type, &len);
            if (data && type == hive_t_REG_BINARY && len >= 8) {
                profile.lastConnected = *reinterpret_cast<uint64_t*>(data);
            }
            if (data) free(data);
        }

        if (!profile.profileName.empty()) {
            profiles.push_back(profile);
        }
    }
    free(profileNodes);

    return profiles;
}

// RDP Connection parsing from NTUSER.DAT registry hive
std::vector<RDPConnectionInfo> WindowsFilesAnalyzer::parseRDPConnectionsFromRegistry(const std::string& ntuserPath) {
    std::vector<RDPConnectionInfo> connections;

    HiveHandle hive(ntuserPath);
    if (!hive.isValid()) return connections;

    hive_node_h root = hivex_root(hive);
    if (root == 0) return connections;

    // Navigate to Terminal Server Client\Default
    hive_node_h defaultNode = navigateToPath(hive, root,
        "Software\\Microsoft\\Terminal Server Client\\Default");
    if (defaultNode != 0) {
        // Read MRU values (MR0, MR1, MR2, ...)
        hive_node_h* values = hivex_node_values(hive, defaultNode);
        if (values) {
            for (int i = 0; values[i] != 0; i++) {
                char* valueName = hivex_value_key(hive, values[i]);
                if (valueName && std::string(valueName).substr(0, 2) == "MR") {
                    hive_type type;
                    size_t len;
                    char* data = hivex_value_value(hive, values[i], &type, &len);
                    if (data && (type == hive_t_REG_SZ || type == hive_t_REG_EXPAND_SZ)) {
                        RDPConnectionInfo conn;
                        conn.serverAddress = convertUTF16LEToUTF8(data, len);
                        conn.entryType = "MRU";
                        conn.sourceHive = ntuserPath;
                        connections.push_back(conn);
                    }
                    if (data) free(data);
                }
                if (valueName) free(valueName);
            }
            free(values);
        }
    }

    // Navigate to Terminal Server Client\Servers for detailed info
    hive_node_h serversNode = navigateToPath(hive, root,
        "Software\\Microsoft\\Terminal Server Client\\Servers");
    if (serversNode != 0) {
        hive_node_h* serverNodes = hivex_node_children(hive, serversNode);
        if (serverNodes) {
            for (int i = 0; serverNodes[i] != 0; i++) {
                char* serverName = hivex_node_name(hive, serverNodes[i]);
                if (!serverName) continue;

                RDPConnectionInfo conn;
                conn.serverAddress = serverName;
                conn.usernameHint = readStringValue(hive, serverNodes[i], "UsernameHint");
                conn.entryType = "Default";
                conn.sourceHive = ntuserPath;

                // Check if this server already exists in connections
                bool exists = false;
                for (const auto& existing : connections) {
                    if (existing.serverAddress == conn.serverAddress) {
                        exists = true;
                        break;
                    }
                }

                if (!exists) {
                    connections.push_back(conn);
                }

                free(serverName);
            }
            free(serverNodes);
        }
    }

    return connections;
}

// Shimcache (AppCompatCache) parsing from SYSTEM registry hive
std::vector<ShimcacheEntryInfo> WindowsFilesAnalyzer::parseShimcacheFromRegistry(const std::string& systemPath) {
    std::vector<ShimcacheEntryInfo> entries;

    HiveHandle hive(systemPath);
    if (!hive.isValid()) return entries;

    hive_node_h root = hivex_root(hive);
    if (root == 0) return entries;

    // Navigate to ControlSet001\Control\Session Manager\AppCompatCache
    hive_node_h appCompatNode = navigateToPath(hive, root,
        "ControlSet001\\Control\\Session Manager\\AppCompatCache");
    if (appCompatNode == 0) return entries;

    // Read the AppCompatCache value (binary)
    hive_value_h cacheValue = hivex_node_get_value(hive, appCompatNode, "AppCompatCache");
    if (cacheValue == 0) return entries;

    hive_type type;
    size_t len;
    char* data = hivex_value_value(hive, cacheValue, &type, &len);
    if (!data || type != hive_t_REG_BINARY || len < 48) {
        if (data) free(data);
        return entries;
    }

    // Parse the AppCompatCache header
    // Signature varies by Windows version:
    // - 0x00000000 (XP)
    // - 0xBADC0FFE (Win7)
    // - 0x80 (Win8+)
    uint32_t signature = *reinterpret_cast<uint32_t*>(data);

    // Number of entries
    uint32_t numberOfEntries = *reinterpret_cast<uint32_t*>(data + 4);

    // Limit to reasonable number
    if (numberOfEntries > 10000) {
        free(data);
        return entries;
    }

    // Parse entries (simplified - actual format varies by Windows version)
    // Each entry typically contains:
    // - 2 bytes: path length
    // - variable: path (UTF-16LE)
    // - 8 bytes: last modified time (FILETIME)
    // - 4 bytes: file size

    const char* pos = data + 48; // Skip header
    const char* end = data + len;

    for (uint32_t i = 0; i < numberOfEntries && pos + 14 < end; ++i) {
        ShimcacheEntryInfo entry;
        entry.sourceHive = systemPath;
        entry.dataSource = "AppCompatCache";

        // Read path length (2 bytes)
        uint16_t pathLen = *reinterpret_cast<const uint16_t*>(pos);
        pos += 2;

        if (pathLen > 0 && pathLen < 1024 && pos + pathLen + 12 <= end) {
            // Read path (UTF-16LE)
            entry.entryPath = convertUTF16LEToUTF8(pos, pathLen);
            pos += pathLen;

            // Read last modified time (8 bytes FILETIME)
            entry.lastModifiedTime = *reinterpret_cast<const uint64_t*>(pos);
            pos += 8;

            // Read file size (4 bytes)
            entry.entrySize = *reinterpret_cast<const uint32_t*>(pos);
            pos += 4;

            // Execution flag (1 byte, if available)
            if (pos < end) {
                entry.executionFlag = *reinterpret_cast<const uint8_t*>(pos);
                pos += 1;
            }

            if (!entry.entryPath.empty()) {
                entries.push_back(entry);
            }
        } else {
            // Skip this entry if path length is invalid
            break;
        }
    }

    free(data);
    return entries;
}

// UserAssist parsing from NTUSER.DAT registry hive
std::vector<UserAssistEntryInfo> WindowsFilesAnalyzer::parseUserAssistFromRegistry(const std::string& ntuserPath) {
    std::vector<UserAssistEntryInfo> entries;

    HiveHandle hive(ntuserPath);
    if (!hive.isValid()) return entries;

    hive_node_h root = hivex_root(hive);
    if (root == 0) return entries;

    // Navigate to UserAssist key
    hive_node_h userAssistNode = navigateToPath(hive, root,
        "Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\UserAssist");
    if (userAssistNode == 0) return entries;

    // Enumerate GUID subkeys
    hive_node_h* guidNodes = hivex_node_children(hive, userAssistNode);
    if (!guidNodes) return entries;

    for (int i = 0; guidNodes[i] != 0; i++) {
        char* guidName = hivex_node_name(hive, guidNodes[i]);
        if (!guidName) continue;

        std::string guid = guidName;
        free(guidName);

        // Navigate to Count subkey
        hive_node_h countNode = 0;
        hive_node_h* subNodes = hivex_node_children(hive, guidNodes[i]);
        if (subNodes) {
            for (int j = 0; subNodes[j] != 0; j++) {
                char* subName = hivex_node_name(hive, subNodes[j]);
                if (subName && std::string(subName) == "Count") {
                    countNode = subNodes[j];
                    free(subName);
                    break;
                }
                if (subName) free(subName);
            }
            free(subNodes);
        }

        if (countNode == 0) continue;

        // Enumerate values in Count (each value is a ROT13 encoded path)
        hive_node_h* values = hivex_node_values(hive, countNode);
        if (!values) continue;

        for (int j = 0; values[j] != 0; j++) {
            char* valueName = hivex_value_key(hive, values[j]);
            if (!valueName) continue;

            UserAssistEntryInfo entry;
            entry.userSid = "Unknown"; // Would need to extract from NTUSER.DAT path
            entry.entryGuid = guid;
            entry.rot13Path = valueName;
            entry.sourceHive = ntuserPath;

            // Decode ROT13
            entry.decodedPath = entry.rot13Path;
            for (char& c : entry.decodedPath) {
                if (c >= 'A' && c <= 'Z') {
                    c = 'A' + (c - 'A' + 13) % 26;
                } else if (c >= 'a' && c <= 'z') {
                    c = 'a' + (c - 'a' + 13) % 26;
                }
            }

            // Read value data (72 bytes for UserAssist entries)
            hive_type type;
            size_t len;
            char* data = hivex_value_value(hive, values[j], &type, &len);
            if (data && type == hive_t_REG_BINARY && len >= 72) {
                // Parse the 72-byte structure
                // Offset 4: focus time (uint32)
                entry.focusTime = *reinterpret_cast<uint32_t*>(data + 4);
                // Offset 12: run count (uint32)
                entry.runCount = *reinterpret_cast<uint32_t*>(data + 12);
                // Offset 60: last run time (FILETIME)
                entry.lastRunTime = *reinterpret_cast<uint64_t*>(data + 60);
            }
            if (data) free(data);

            entries.push_back(entry);
            free(valueName);
        }
        free(values);
    }
    free(guidNodes);

    return entries;
}
