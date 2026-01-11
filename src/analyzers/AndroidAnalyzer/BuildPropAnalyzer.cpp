#include "AndroidAnalyzer.h"
#include "AndroidKnowProperties.h"
#include <fstream>
#include <sstream>
#include <regex>
#include <algorithm>
#include <ctime>
#include <iomanip>

// Split string utility function
std::vector<std::string> splitString(const std::string& str, char delimiter) {
    std::vector<std::string> tokens;
    std::string token;
    std::istringstream tokenStream(str);
    while (std::getline(tokenStream, token, delimiter)) {
        tokens.push_back(token);
    }
    return tokens;
}

BuildPropEntry AndroidAnalyzer::parseBuildPropEntry(const std::string& line) {
    BuildPropEntry entry;
    entry.isIdentified = false;

    // Skip comments and empty lines
    if (line.empty() || line[0] == '#' || line.find('=') == std::string::npos) {
        return entry;
    }

    size_t equalPos = line.find('=');
    if (equalPos == std::string::npos) {
        return entry;
    }

    entry.key = line.substr(0, equalPos);
    entry.value = line.substr(equalPos + 1);

    // Remove quotes if present
    if (entry.value.front() == '"' && entry.value.back() == '"') {
        entry.value = entry.value.substr(1, entry.value.length() - 2);
    }

    // Look up in known properties
    auto it = KNOWN_PROPERTIES.find(entry.key);
    if (it != KNOWN_PROPERTIES.end()) {
        entry.category = it->second.category;
        entry.description = it->second.description;
        entry.securityImplication = it->second.securityImplication;
        entry.isIdentified = true;
    } else {
        entry.category = "Unknown";
        entry.description = "Unrecognized property";
        entry.securityImplication = "Unknown";
        entry.isIdentified = false;
    }

    return entry;
}

DeviceInfo AndroidAnalyzer::extractDeviceInfo(const std::vector<BuildPropEntry>& entries) {
    DeviceInfo info;

    for (const auto& entry : entries) {
        if (entry.key == "ro.product.manufacturer") info.manufacturer = entry.value;
        else if (entry.key == "ro.product.brand") info.brand = entry.value;
        else if (entry.key == "ro.product.model") info.model = entry.value;
        else if (entry.key == "ro.product.device") info.device = entry.value;
        else if (entry.key == "ro.product.name") info.product = entry.value;
        else if (entry.key == "ro.build.fingerprint") info.fingerprint = entry.value;
        else if (entry.key == "ro.build.version.security_patch") info.securityPatchLevel = entry.value;
        else if (entry.key == "ro.build.version.release") info.buildVersion = entry.value;
        else if (entry.key == "ro.build.version.sdk") info.sdkVersion = std::stoi(entry.value);
        else if (entry.key == "ro.build.date") info.buildDate = entry.value;
    }

    return info;
}

SecurityConfig AndroidAnalyzer::extractSecurityConfig(const std::vector<BuildPropEntry>& entries) {
    SecurityConfig config;
    config.adbEnabled = true; // Default assumption
    config.debugEnabled = false;
    config.mockLocationDisabled = true;
    config.secureEnabled = true;
    config.otaEncrypted = false;

    for (const auto& entry : entries) {
        if (entry.key == "ro.adb.secure") config.adbEnabled = (entry.value == "1");
        else if (entry.key == "ro.debuggable") config.debugEnabled = (entry.value == "1");
        else if (entry.key == "ro.allow.mock.location") config.mockLocationDisabled = (entry.value == "0");
        else if (entry.key == "ro.secure") config.secureEnabled = (entry.value == "1");

        // Collect security-relevant flags
        if (entry.securityImplication == "High" || entry.securityImplication == "Critical") {
            config.securityFlags.push_back(entry.key + "=" + entry.value);
        }
    }

    return config;
}

SystemConfig AndroidAnalyzer::extractSystemConfig(const std::vector<BuildPropEntry>& entries) {
    SystemConfig config;

    for (const auto& entry : entries) {
        if (entry.key == "ro.product.cpu.abi") config.cpuArch = entry.value;
        else if (entry.key == "ro.product.cpu.abilist") {
            config.cpuAbilist = splitString(entry.value, ',');
        }
        else if (entry.key == "ro.sf.lcd_density") config.screenDensity = std::stoi(entry.value);
        else if (entry.key == "ro.product.locale") config.locale = entry.value;
        else if (entry.key == "ro.config.gnss.support") {
            config.supportedGps = splitString(entry.value, ',');
        }
        else if (entry.key == "ro.surface_flinger.supports_background_blur") {
            config.blurSupported = (entry.value == "1");
        }
        else if (entry.key == "ro.opengles.version") config.openglVersion = entry.value;
    }

    return config;
}

ForensicAnalysis AndroidAnalyzer::performForensicAnalysis(const std::vector<BuildPropEntry>& entries, const DeviceInfo& deviceInfo) {
    ForensicAnalysis analysis;

    // Create unique device identifier
    analysis.deviceIdentifier = deviceInfo.manufacturer + "_" + deviceInfo.model + "_" + deviceInfo.fingerprint.substr(0, 16);

    // Set extraction date
    auto now = std::time(nullptr);
    auto tm = *std::localtime(&now);
    std::ostringstream oss;
    oss << std::put_time(&tm, "%Y-%m-%d %H:%M:%S");
    analysis.extractionDate = oss.str();

    // Analyze security concerns
    for (const auto& entry : entries) {
        if (entry.securityImplication == "Critical") {
            if (entry.key == "ro.debuggable" && entry.value == "1") {
                analysis.securityConcerns.push_back("DEBUG_MODE_ENABLED");
            }
            if (entry.key == "ro.adb.secure" && entry.value == "0") {
                analysis.securityConcerns.push_back("ADB_INSECURE");
            }
            if (entry.key == "ro.allow.mock.location" && entry.value == "1") {
                analysis.securityConcerns.push_back("MOCK_LOCATION_ENABLED");
            }
            if (entry.key == "ro.secure" && entry.value == "0") {
                analysis.securityConcerns.push_back("INSECURE_MODE");
            }
        }
    }

    // Check for unusual configurations
    for (const auto& entry : entries) {
        if (!entry.isIdentified) {
            analysis.unusualConfigurations.push_back("UNKNOWN_PROPERTY: " + entry.key);
        }

        // Check for development/test configurations in production builds
        if (entry.key.find("test") != std::string::npos || entry.key.find("debug") != std::string::npos) {
            if (entry.value != "0" && entry.value != "false") {
                analysis.unusualConfigurations.push_back("TEST_CONFIG_ACTIVE: " + entry.key);
            }
        }
    }

    // Identify carrier customizations
    if (deviceInfo.manufacturer == "Xiaomi") {
        analysis.carrierCustomizations.push_back("MIUI_CUSTOMIZATION");
        if (std::find_if(entries.begin(), entries.end(),
            [](const BuildPropEntry& e) { return e.key.find("miui") != std::string::npos; }) != entries.end()) {
            analysis.carrierCustomizations.push_back("MIUI_FRAMEWORK");
        }
    }

    // Identify vendor modifications
    if (std::find_if(entries.begin(), entries.end(),
        [](const BuildPropEntry& e) { return e.key.find("vendor") != std::string::npos; }) != entries.end()) {
        analysis.vendorModifications.push_back("VENDOR_MODIFICATIONS_PRESENT");
    }

    if (std::find_if(entries.begin(), entries.end(),
        [](const BuildPropEntry& e) { return e.key.find("qcom") != std::string::npos || e.key.find("qualcomm") != std::string::npos; }) != entries.end()) {
        analysis.vendorModifications.push_back("QUALCOMM_VENDOR_SPECIFIC");
    }

    // Risk assessment
    int riskScore = 0;
    if (!analysis.securityConcerns.empty()) riskScore += analysis.securityConcerns.size() * 3;
    if (!analysis.unusualConfigurations.empty()) riskScore += analysis.unusualConfigurations.size();

    if (riskScore >= 10) analysis.riskAssessment = "HIGH_RISK";
    else if (riskScore >= 5) analysis.riskAssessment = "MEDIUM_RISK";
    else if (riskScore >= 1) analysis.riskAssessment = "LOW_RISK";
    else analysis.riskAssessment = "MINIMAL_RISK";

    return analysis;
}

BuildPropAnalysisResult AndroidAnalyzer::analyzeBuildPropFile(const std::string& buildPropPath) {
    BuildPropAnalysisResult result;

    std::ifstream file(buildPropPath);
    if (!file.is_open()) {
        std::cerr << "Error: Cannot open build.prop file: " << buildPropPath << std::endl;
        return result;
    }

    std::string line;
    std::vector<BuildPropEntry> allEntries;

    // Parse all entries
    while (std::getline(file, line)) {
        BuildPropEntry entry = parseBuildPropEntry(line);
        if (!entry.key.empty()) {
            allEntries.push_back(entry);
            result.allEntries.push_back(entry);

            if (entry.isIdentified && (entry.securityImplication == "High" || entry.securityImplication == "Critical")) {
                result.securityRelevantEntries.push_back(entry);
            } else if (!entry.isIdentified) {
                result.unrecognizedEntries.push_back(entry);
            }
        }
    }

    // Extract structured information
    result.deviceInfo = extractDeviceInfo(allEntries);
    result.securityConfig = extractSecurityConfig(allEntries);
    result.systemConfig = extractSystemConfig(allEntries);
    result.forensicAnalysis = performForensicAnalysis(allEntries, result.deviceInfo);

    file.close();
    return result;
}

void AndroidAnalyzer::generateBuildPropReport(const BuildPropAnalysisResult& result, const std::string& outputPath) {
    std::ofstream report(outputPath);
    if (!report.is_open()) {
        std::cerr << "Error: Cannot create report file: " << outputPath << std::endl;
        return;
    }

    // Generate comprehensive forensic report
    report << "===========================================\n";
    report << "ANDROID BUILD.PROP FORENSIC ANALYSIS REPORT\n";
    report << "===========================================\n\n";

    // Device Information Section
    report << "DEVICE INFORMATION\n";
    report << "-------------------\n";
    report << "Manufacturer: " << result.deviceInfo.manufacturer << "\n";
    report << "Brand: " << result.deviceInfo.brand << "\n";
    report << "Model: " << result.deviceInfo.model << "\n";
    report << "Device: " << result.deviceInfo.device << "\n";
    report << "Product: " << result.deviceInfo.product << "\n";
    report << "Android Version: " << result.deviceInfo.buildVersion << "\n";
    report << "SDK Version: " << result.deviceInfo.sdkVersion << "\n";
    report << "Build Date: " << result.deviceInfo.buildDate << "\n";
    report << "Security Patch: " << result.deviceInfo.securityPatchLevel << "\n";
    report << "Build Fingerprint: " << result.deviceInfo.fingerprint << "\n\n";

    // Security Configuration Section
    report << "SECURITY CONFIGURATION\n";
    report << "---------------------\n";
    report << "ADB Enabled: " << (result.securityConfig.adbEnabled ? "YES" : "NO") << "\n";
    report << "Debug Mode: " << (result.securityConfig.debugEnabled ? "ENABLED" : "DISABLED") << "\n";
    report << "Mock Location: " << (result.securityConfig.mockLocationDisabled ? "DISABLED" : "ENABLED") << "\n";
    report << "Secure Mode: " << (result.securityConfig.secureEnabled ? "ENABLED" : "DISABLED") << "\n\n";

    if (!result.securityConfig.securityFlags.empty()) {
        report << "Security-Related Properties:\n";
        for (const auto& flag : result.securityConfig.securityFlags) {
            report << "  - " << flag << "\n";
        }
        report << "\n";
    }

    // System Configuration Section
    report << "SYSTEM CONFIGURATION\n";
    report << "--------------------\n";
    report << "CPU Architecture: " << result.systemConfig.cpuArch << "\n";
    report << "Screen Density: " << result.systemConfig.screenDensity << "\n";
    report << "Default Locale: " << result.systemConfig.locale << "\n";
    report << "OpenGL Version: " << result.systemConfig.openglVersion << "\n";
    report << "Background Blur: " << (result.systemConfig.blurSupported ? "SUPPORTED" : "NOT SUPPORTED") << "\n";

    if (!result.systemConfig.cpuAbilist.empty()) {
        report << "CPU ABI List: ";
        for (size_t i = 0; i < result.systemConfig.cpuAbilist.size(); ++i) {
            if (i > 0) report << ", ";
            report << result.systemConfig.cpuAbilist[i];
        }
        report << "\n";
    }

    if (!result.systemConfig.supportedGps.empty()) {
        report << "Supported GPS Systems: ";
        for (size_t i = 0; i < result.systemConfig.supportedGps.size(); ++i) {
            if (i > 0) report << ", ";
            report << result.systemConfig.supportedGps[i];
        }
        report << "\n";
    }
    report << "\n";

    // Forensic Analysis Section
    report << "FORENSIC ANALYSIS\n";
    report << "-----------------\n";
    report << "Device Identifier: " << result.forensicAnalysis.deviceIdentifier << "\n";
    report << "Extraction Date: " << result.forensicAnalysis.extractionDate << "\n";
    report << "Risk Assessment: " << result.forensicAnalysis.riskAssessment << "\n\n";

    if (!result.forensicAnalysis.securityConcerns.empty()) {
        report << "SECURITY CONCERNS:\n";
        for (const auto& concern : result.forensicAnalysis.securityConcerns) {
            report << "  [!] " << concern << "\n";
        }
        report << "\n";
    }

    if (!result.forensicAnalysis.unusualConfigurations.empty()) {
        report << "UNUSUAL CONFIGURATIONS:\n";
        for (const auto& config : result.forensicAnalysis.unusualConfigurations) {
            report << "  [?] " << config << "\n";
        }
        report << "\n";
    }

    if (!result.forensicAnalysis.carrierCustomizations.empty()) {
        report << "CARRIER CUSTOMIZATIONS:\n";
        for (const auto& custom : result.forensicAnalysis.carrierCustomizations) {
            report << "  [*] " << custom << "\n";
        }
        report << "\n";
    }

    if (!result.forensicAnalysis.vendorModifications.empty()) {
        report << "VENDOR MODIFICATIONS:\n";
        for (const auto& vendor : result.forensicAnalysis.vendorModifications) {
            report << "  [V] " << vendor << "\n";
        }
        report << "\n";
    }

    // Security Relevant Properties
    report << "SECURITY RELEVANT PROPERTIES\n";
    report << "----------------------------\n";
    for (const auto& entry : result.securityRelevantEntries) {
        report << "[" << entry.securityImplication << "] " << entry.key << " = " << entry.value << "\n";
        report << "  Description: " << entry.description << "\n";
        report << "  Category: " << entry.category << "\n\n";
    }

    // Summary Statistics
    report << "ANALYSIS STATISTICS\n";
    report << "------------------\n";
    report << "Total Properties Analyzed: " << result.allEntries.size() << "\n";
    report << "Identified Properties: " << (result.allEntries.size() - result.unrecognizedEntries.size()) << "\n";
    report << "Unrecognized Properties: " << result.unrecognizedEntries.size() << "\n";
    report << "Security-Relevant Properties: " << result.securityRelevantEntries.size() << "\n\n";

    report.close();
    std::cout << "Build.prop analysis report generated: " << outputPath << std::endl;
}

void AndroidAnalyzer::generateUnrecognizedPropertiesReport(const std::vector<BuildPropEntry>& unrecognizedEntries, const std::string& outputPath) {
    std::ofstream report(outputPath);
    if (!report.is_open()) {
        std::cerr << "Error: Cannot create unrecognized properties report: " << outputPath << std::endl;
        return;
    }

    report << "=====================================\n";
    report << "UNRECOGNIZED BUILD.PROPERTIES REPORT\n";
    report << "=====================================\n\n";

    report << "This report contains properties that were not recognized in our analysis database.\n";
    report << "These may be vendor-specific, carrier-specific, or custom modifications.\n\n";

    if (unrecognizedEntries.empty()) {
        report << "No unrecognized properties found. All properties were successfully categorized.\n";
    } else {
        report << "TOTAL UNRECOGNIZED PROPERTIES: " << unrecognizedEntries.size() << "\n\n";

        // Group by category pattern
        std::map<std::string, std::vector<BuildPropEntry>> groupedEntries;
        for (const auto& entry : unrecognizedEntries) {
            std::string category = "Unknown";
            if (entry.key.find("ro.") == 0) category = "Read-Only System";
            else if (entry.key.find("persist.") == 0) category = "Persistent";
            else if (entry.key.find("dalvik.") == 0) category = "Dalvik VM";
            else if (entry.key.find("debug.") == 0) category = "Debug";
            else if (entry.key.find("sys.") == 0) category = "System";
            else if (entry.key.find("vendor.") == 0) category = "Vendor";
            else if (entry.key.find("media.") == 0) category = "Media";
            else if (entry.key.find("ro.") == 0 && entry.key.find("miui") != std::string::npos) category = "MIUI";

            groupedEntries[category].push_back(entry);
        }

        for (const auto& group : groupedEntries) {
            report << "CATEGORY: " << group.first << " (" << group.second.size() << " entries)\n";
            report << std::string(group.first.length() + 10, '-') << "\n";

            for (const auto& entry : group.second) {
                report << "  " << entry.key << " = " << entry.value << "\n";

                // Add contextual analysis
                if (entry.key.find("test") != std::string::npos) {
                    report << "    -> Likely a test configuration\n";
                } else if (entry.key.find("debug") != std::string::npos) {
                    report << "    -> Debug-related configuration\n";
                } else if (entry.key.find("experimental") != std::string::npos) {
                    report << "    -> Experimental feature flag\n";
                } else if (entry.key.find("temp") != std::string::npos) {
                    report << "    -> Temporary configuration\n";
                }
            }
            report << "\n";
        }

        // Security analysis of unrecognized properties
        report << "SECURITY ANALYSIS OF UNRECOGNIZED PROPERTIES\n";
        report << "--------------------------------------------\n";

        std::vector<BuildPropEntry> securityRelevantUnknown;
        for (const auto& entry : unrecognizedEntries) {
            if (entry.key.find("secure") != std::string::npos ||
                entry.key.find("auth") != std::string::npos ||
                entry.key.find("encrypt") != std::string::npos ||
                entry.key.find("key") != std::string::npos ||
                entry.key.find("pass") != std::string::npos ||
                entry.key.find("token") != std::string::npos ||
                entry.key.find("cert") != std::string::npos) {
                securityRelevantUnknown.push_back(entry);
            }
        }

        if (securityRelevantUnknown.empty()) {
            report << "No security-relevant unrecognized properties found.\n";
        } else {
            report << "POTENTIALLY SECURITY-RELEVANT UNKNOWN PROPERTIES:\n";
            for (const auto& entry : securityRelevantUnknown) {
                report << "  [SECURITY] " << entry.key << " = " << entry.value << "\n";
            }
        }
        report << "\n";

        // Recommendations
        report << "RECOMMENDATIONS\n";
        report << "---------------\n";
        report << "1. Review unrecognized properties for potential security implications\n";
        report << "2. Cross-reference with vendor documentation\n";
        report << "3. Consider updating analysis database with new properties\n";
        report << "4. Investigate any test or debug configurations in production builds\n";
        report << "5. Verify that unknown properties don't compromise device security\n";
    }

    report.close();
    std::cout << "Unrecognized properties report generated: " << outputPath << std::endl;
}