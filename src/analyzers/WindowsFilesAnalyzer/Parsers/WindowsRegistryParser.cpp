// WindowsRegistryParser.cpp
// Implementation of Registry parsing logic using hivex library.
//
// This file holds the top-level hive analysis (analyzeRegistryHives) and the
// generic recursive hive walker (parseRegistryHive). The per-artifact parsers
// (SAM users / USB / services / WiFi / RDP / shimcache / UserAssist) live in
// WindowsRegistryArtifacts.cpp. Shared hive helpers are in
// WindowsRegistryHelpers.h (inline, namespace WindowsRegistry).

#include "WindowsFilesAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include <fstream>
#include <cstring>
#include <sstream>
#include <iomanip>
#include <iostream>
#include <vector>
#include <functional>

// hivex library
#include <hivex.h>

#include "WindowsRegistryHelpers.h"

// Bring shared hive helpers into scope (defined inline in WindowsRegistryHelpers.h)
using namespace WindowsRegistry;

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

