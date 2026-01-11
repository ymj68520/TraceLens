#include <iostream>
#include <fstream>
#include <sstream>
#include <vector>
#include <string>
#include <map>
#include <algorithm>
#include <ctime>
#include <iomanip>

// 复制必要的数据结构定义
struct BuildPropEntry {
    std::string key;
    std::string value;
    std::string category;
    std::string description;
    std::string securityImplication;
    bool isIdentified;
};

struct DeviceInfo {
    std::string manufacturer;
    std::string brand;
    std::string model;
    std::string device;
    std::string product;
    std::string fingerprint;
    std::string securityPatchLevel;
    std::string buildVersion;
    int sdkVersion;
    std::string buildDate;
};

struct SecurityConfig {
    bool adbEnabled;
    bool debugEnabled;
    bool mockLocationDisabled;
    bool secureEnabled;
    bool otaEncrypted;
    std::vector<std::string> securityFlags;
};

struct SystemConfig {
    std::string cpuArch;
    std::vector<std::string> cpuAbilist;
    int screenDensity;
    std::string locale;
    std::vector<std::string> supportedGps;
    bool blurSupported;
    std::string openglVersion;
};

struct ForensicAnalysis {
    std::string deviceIdentifier;
    std::string extractionDate;
    std::vector<std::string> securityConcerns;
    std::vector<std::string> unusualConfigurations;
    std::vector<std::string> carrierCustomizations;
    std::vector<std::string> vendorModifications;
    std::string riskAssessment;
};

struct BuildPropAnalysisResult {
    DeviceInfo deviceInfo;
    SecurityConfig securityConfig;
    SystemConfig systemConfig;
    ForensicAnalysis forensicAnalysis;
    std::vector<BuildPropEntry> allEntries;
    std::vector<BuildPropEntry> unrecognizedEntries;
    std::vector<BuildPropEntry> securityRelevantEntries;
};

struct PropertyDefinition {
    std::string category;
    std::string description;
    std::string securityImplication;
};

// 复制属性定义数据库
static const std::map<std::string, PropertyDefinition> KNOWN_PROPERTIES = {
    // Device Information
    {"ro.product.manufacturer", {"Device", "Device manufacturer", "Low"}},
    {"ro.product.brand", {"Device", "Product brand", "Low"}},
    {"ro.product.model", {"Device", "Product model", "Low"}},
    {"ro.product.device", {"Device", "Product device name", "Low"}},
    {"ro.product.name", {"Device", "Product name", "Low"}},
    {"ro.product.mod_device", {"Device", "Mod device identifier", "Low"}},
    {"ro.miui.cust_device", {"Device", "MIUI custom device", "Low"}},

    // Build Information
    {"ro.build.id", {"Build", "Build identifier", "Low"}},
    {"ro.build.version.release", {"Build", "Android version", "Low"}},
    {"ro.build.version.sdk", {"Build", "Android SDK version", "Low"}},
    {"ro.build.version.security_patch", {"Build", "Security patch level", "High"}},
    {"ro.build.date", {"Build", "Build date", "Medium"}},
    {"ro.build.date.utc", {"Build", "Build date (UTC)", "Medium"}},
    {"ro.build.type", {"Build", "Build type (user/debug)", "High"}},
    {"ro.build.tags", {"Build", "Build tags", "Medium"}},
    {"ro.build.fingerprint", {"Build", "Build fingerprint for verification", "High"}},
    {"ro.build.version.incremental", {"Build", "Incremental build number", "Low"}},
    {"ro.build.keys", {"Build", "Release keys", "High"}},

    // Security Configuration
    {"ro.secure", {"Security", "Secure mode enabled", "Critical"}},
    {"ro.adb.secure", {"Security", "ADB secure mode", "Critical"}},
    {"ro.allow.mock.location", {"Security", "Mock location permission", "High"}},
    {"ro.debuggable", {"Security", "Debug mode enabled", "Critical"}},
    {"security.perf_harden", {"Security", "Performance hardening", "Medium"}},
    {"ro.secureboot.devicelock", {"Security", "Secure boot device lock", "High"}},

    // System Configuration
    {"ro.sf.lcd_density", {"System", "Screen density", "Low"}},
    {"ro.product.cpu.abi", {"System", "Primary CPU ABI", "Low"}},
    {"ro.product.cpu.abilist", {"System", "CPU ABI list", "Low"}},
    {"ro.product.cpu.abilist32", {"System", "32-bit CPU ABI list", "Low"}},
    {"ro.product.cpu.abilist64", {"System", "64-bit CPU ABI list", "Low"}},
    {"ro.opengles.version", {"System", "OpenGL version", "Low"}},
    {"ro.product.locale", {"System", "Default locale", "Medium"}},
    {"persist.sys.timezone", {"System", "System timezone", "Medium"}},

    // MIUI/Xiaomi Specific
    {"ro.miui.ui.version.code", {"MIUI", "MIUI version code", "Low"}},
    {"ro.miui.ui.version.name", {"MIUI", "MIUI version name", "Low"}},
    {"ro.miui.restrict_imei", {"MIUI", "IMEI restriction", "High"}},
    {"ro.miui.has_cust_partition", {"MIUI", "Custom partition present", "Medium"}},
    {"ro.miui.has_security_keyboard", {"MIUI", "Security keyboard present", "Medium"}},
    {"ro.miui.support_miui_ime_bottom", {"MIUI", "Bottom IME support", "Low"}},
    {"ro.miui.ui.fonttype", {"MIUI", "MIUI font type", "Low"}},
    {"ro.miui.remove_uri_80_flag", {"MIUI", "URI 80 flag removal", "Medium"}},
    {"ro.mi.development", {"MIUI", "Development mode", "High"}},
    {"ro.rom.zone", {"MIUI", "ROM zone (regional)", "Medium"}}
};

// 工具函数
std::vector<std::string> splitString(const std::string& str, char delimiter) {
    std::vector<std::string> tokens;
    std::string token;
    std::istringstream tokenStream(str);
    while (std::getline(tokenStream, token, delimiter)) {
        tokens.push_back(token);
    }
    return tokens;
}

// Build.prop分析器类
class SimpleBuildPropAnalyzer {
public:
    BuildPropAnalysisResult analyzeBuildPropFile(const std::string& buildPropPath);
    void generateBuildPropReport(const BuildPropAnalysisResult& result, const std::string& outputPath);

private:
    BuildPropEntry parseBuildPropEntry(const std::string& line);
    DeviceInfo extractDeviceInfo(const std::vector<BuildPropEntry>& entries);
    SecurityConfig extractSecurityConfig(const std::vector<BuildPropEntry>& entries);
    SystemConfig extractSystemConfig(const std::vector<BuildPropEntry>& entries);
    ForensicAnalysis performForensicAnalysis(const std::vector<BuildPropEntry>& entries, const DeviceInfo& deviceInfo);
};

BuildPropEntry SimpleBuildPropAnalyzer::parseBuildPropEntry(const std::string& line) {
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
    if (!entry.value.empty() && entry.value.front() == '"' && entry.value.back() == '"') {
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

DeviceInfo SimpleBuildPropAnalyzer::extractDeviceInfo(const std::vector<BuildPropEntry>& entries) {
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

SecurityConfig SimpleBuildPropAnalyzer::extractSecurityConfig(const std::vector<BuildPropEntry>& entries) {
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

SystemConfig SimpleBuildPropAnalyzer::extractSystemConfig(const std::vector<BuildPropEntry>& entries) {
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

ForensicAnalysis SimpleBuildPropAnalyzer::performForensicAnalysis(const std::vector<BuildPropEntry>& entries, const DeviceInfo& deviceInfo) {
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

BuildPropAnalysisResult SimpleBuildPropAnalyzer::analyzeBuildPropFile(const std::string& buildPropPath) {
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

void SimpleBuildPropAnalyzer::generateBuildPropReport(const BuildPropAnalysisResult& result, const std::string& outputPath) {
    std::ofstream report(outputPath);
    if (!report.is_open()) {
        std::cerr << "Error: Cannot create report file: " << outputPath << std::endl;
        return;
    }

    // Generate comprehensive forensic report
    report << "========================================\n";
    report << "ANDROID BUILD.PROP FORENSIC ANALYSIS REPORT\n";
    report << "========================================\n\n";

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
    report << "Background Blur: " << (result.systemConfig.blurSupported ? "SUPPORTED" : "NOT SUPPORTED") << "\n\n";

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

// 测试函数
void displayAnalysisResults(const BuildPropAnalysisResult& result) {
    std::cout << "\n========================================\n";
    std::cout << "BUILD.PROP ANALYSIS TEST RESULTS\n";
    std::cout << "========================================\n\n";

    // Device Information
    std::cout << "DEVICE INFORMATION:\n";
    std::cout << "  Manufacturer: " << result.deviceInfo.manufacturer << "\n";
    std::cout << "  Brand: " << result.deviceInfo.brand << "\n";
    std::cout << "  Model: " << result.deviceInfo.model << "\n";
    std::cout << "  Device: " << result.deviceInfo.device << "\n";
    std::cout << "  Android Version: " << result.deviceInfo.buildVersion << "\n";
    std::cout << "  SDK Version: " << result.deviceInfo.sdkVersion << "\n";
    std::cout << "  Build Date: " << result.deviceInfo.buildDate << "\n";
    std::cout << "  Security Patch: " << result.deviceInfo.securityPatchLevel << "\n\n";

    // Security Configuration
    std::cout << "SECURITY CONFIGURATION:\n";
    std::cout << "  ADB Enabled: " << (result.securityConfig.adbEnabled ? "YES" : "NO") << "\n";
    std::cout << "  Debug Mode: " << (result.securityConfig.debugEnabled ? "ENABLED" : "DISABLED") << "\n";
    std::cout << "  Mock Location: " << (result.securityConfig.mockLocationDisabled ? "DISABLED" : "ENABLED") << "\n";
    std::cout << "  Secure Mode: " << (result.securityConfig.secureEnabled ? "ENABLED" : "DISABLED") << "\n\n";

    // System Configuration
    std::cout << "SYSTEM CONFIGURATION:\n";
    std::cout << "  CPU Architecture: " << result.systemConfig.cpuArch << "\n";
    std::cout << "  Screen Density: " << result.systemConfig.screenDensity << "\n";
    std::cout << "  Default Locale: " << result.systemConfig.locale << "\n";
    std::cout << "  OpenGL Version: " << result.systemConfig.openglVersion << "\n";
    std::cout << "  Background Blur: " << (result.systemConfig.blurSupported ? "SUPPORTED" : "NOT SUPPORTED") << "\n\n";

    // Forensic Analysis
    std::cout << "FORENSIC ANALYSIS:\n";
    std::cout << "  Device Identifier: " << result.forensicAnalysis.deviceIdentifier << "\n";
    std::cout << "  Extraction Date: " << result.forensicAnalysis.extractionDate << "\n";
    std::cout << "  Risk Assessment: " << result.forensicAnalysis.riskAssessment << "\n";

    if (!result.forensicAnalysis.securityConcerns.empty()) {
        std::cout << "  Security Concerns (" << result.forensicAnalysis.securityConcerns.size() << "):\n";
        for (const auto& concern : result.forensicAnalysis.securityConcerns) {
            std::cout << "    [!] " << concern << "\n";
        }
    }

    if (!result.forensicAnalysis.unusualConfigurations.empty()) {
        std::cout << "  Unusual Configurations (" << result.forensicAnalysis.unusualConfigurations.size() << "):\n";
        for (const auto& config : result.forensicAnalysis.unusualConfigurations) {
            std::cout << "    [?] " << config << "\n";
        }
    }

    if (!result.forensicAnalysis.carrierCustomizations.empty()) {
        std::cout << "  Carrier Customizations (" << result.forensicAnalysis.carrierCustomizations.size() << "):\n";
        for (const auto& custom : result.forensicAnalysis.carrierCustomizations) {
            std::cout << "    [*] " << custom << "\n";
        }
    }

    if (!result.forensicAnalysis.vendorModifications.empty()) {
        std::cout << "  Vendor Modifications (" << result.forensicAnalysis.vendorModifications.size() << "):\n";
        for (const auto& vendor : result.forensicAnalysis.vendorModifications) {
            std::cout << "    [V] " << vendor << "\n";
        }
    }
    std::cout << "\n";

    // Statistics
    std::cout << "ANALYSIS STATISTICS:\n";
    std::cout << "  Total Properties: " << result.allEntries.size() << "\n";
    std::cout << "  Identified Properties: " << (result.allEntries.size() - result.unrecognizedEntries.size()) << "\n";
    std::cout << "  Unrecognized Properties: " << result.unrecognizedEntries.size() << "\n";
    std::cout << "  Security-Relevant Properties: " << result.securityRelevantEntries.size() << "\n";
    std::cout << "  Recognition Rate: "
              << std::fixed << std::setprecision(1)
              << (100.0 * (result.allEntries.size() - result.unrecognizedEntries.size()) / result.allEntries.size())
              << "%\n\n";

    // Show some unrecognized properties if any
    if (!result.unrecognizedEntries.empty()) {
        std::cout << "SAMPLE UNRECOGNIZED PROPERTIES (first 10):\n";
        int count = 0;
        for (const auto& entry : result.unrecognizedEntries) {
            if (count >= 10) break;
            std::cout << "  " << entry.key << " = " << entry.value << "\n";
            count++;
        }
        if (result.unrecognizedEntries.size() > 10) {
            std::cout << "  ... and " << (result.unrecognizedEntries.size() - 10) << " more\n";
        }
        std::cout << "\n";
    }

    // Show security-relevant properties
    if (!result.securityRelevantEntries.empty()) {
        std::cout << "SECURITY-RELEVANT PROPERTIES:\n";
        for (const auto& entry : result.securityRelevantEntries) {
            std::cout << "  [" << entry.securityImplication << "] " << entry.key << " = " << entry.value << "\n";
            std::cout << "      Category: " << entry.category << " | " << entry.description << "\n";
        }
        std::cout << "\n";
    }
}

int main() {
    try {
        std::cout << "Android Build.prop Analyzer Test\n";
        std::cout << "===============================\n";

        SimpleBuildPropAnalyzer analyzer;

        std::string buildPropPath = "tests/system/build.prop";
        std::cout << "Analyzing build.prop file: " << buildPropPath << "\n";

        // Perform analysis
        BuildPropAnalysisResult result = analyzer.analyzeBuildPropFile(buildPropPath);

        if (result.allEntries.empty()) {
            std::cerr << "ERROR: No entries were parsed from the build.prop file\n";
            return 1;
        }

        // Display results
        displayAnalysisResults(result);

        // Generate reports
        std::string mainReport = "build_prop_analysis_report.txt";
        analyzer.generateBuildPropReport(result, mainReport);

        std::cout << "Report generated: " << mainReport << "\n";
        std::cout << "\nBuild.prop analysis test completed successfully!\n";

        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Error during testing: " << e.what() << std::endl;
        return 1;
    } catch (...) {
        std::cerr << "Unknown error during testing" << std::endl;
        return 1;
    }
}