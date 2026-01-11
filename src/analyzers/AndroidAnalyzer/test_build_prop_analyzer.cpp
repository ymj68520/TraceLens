#include "AndroidAnalyzer.h"
#include <iostream>
#include <iomanip>

// Test function to display analysis results
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
    std::cout << "  Secure Mode: " << (result.securityConfig.secureEnabled ? "ENABLED" : "DISABLED") << "\n";

    if (!result.securityConfig.securityFlags.empty()) {
        std::cout << "  Security Flags (" << result.securityConfig.securityFlags.size() << "):\n";
        for (const auto& flag : result.securityConfig.securityFlags) {
            std::cout << "    - " << flag << "\n";
        }
    }
    std::cout << "\n";

    // System Configuration
    std::cout << "SYSTEM CONFIGURATION:\n";
    std::cout << "  CPU Architecture: " << result.systemConfig.cpuArch << "\n";
    std::cout << "  Screen Density: " << result.systemConfig.screenDensity << "\n";
    std::cout << "  Default Locale: " << result.systemConfig.locale << "\n";
    std::cout << "  OpenGL Version: " << result.systemConfig.openglVersion << "\n";
    std::cout << "  Background Blur: " << (result.systemConfig.blurSupported ? "SUPPORTED" : "NOT SUPPORTED") << "\n";

    if (!result.systemConfig.cpuAbilist.empty()) {
        std::cout << "  CPU ABI List: ";
        for (size_t i = 0; i < result.systemConfig.cpuAbilist.size(); ++i) {
            if (i > 0) std::cout << ", ";
            std::cout << result.systemConfig.cpuAbilist[i];
        }
        std::cout << "\n";
    }

    if (!result.systemConfig.supportedGps.empty()) {
        std::cout << "  Supported GPS: ";
        for (size_t i = 0; i < result.systemConfig.supportedGps.size(); ++i) {
            if (i > 0) std::cout << ", ";
            std::cout << result.systemConfig.supportedGps[i];
        }
        std::cout << "\n";
    }
    std::cout << "\n";

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

void testBuildPropAnalysis() {
    std::cout << "Android Build.prop Analyzer Test\n";
    std::cout << "===============================\n";

    AndroidAnalyzer analyzer;

    std::string buildPropPath = "tests/system/build.prop";
    std::cout << "Analyzing build.prop file: " << buildPropPath << "\n";

    // Perform analysis
    BuildPropAnalysisResult result = analyzer.analyzeBuildPropFile(buildPropPath);

    if (result.allEntries.empty()) {
        std::cerr << "ERROR: No entries were parsed from the build.prop file\n";
        return;
    }

    // Display results
    displayAnalysisResults(result);

    // Generate reports
    std::string mainReport = "build_prop_analysis_report.txt";
    std::string unrecognizedReport = "unrecognized_properties_report.txt";

    analyzer.generateBuildPropReport(result, mainReport);
    analyzer.generateUnrecognizedPropertiesReport(result.unrecognizedEntries, unrecognizedReport);

    std::cout << "Reports generated:\n";
    std::cout << "  - Main analysis report: " << mainReport << "\n";
    std::cout << "  - Unrecognized properties report: " << unrecognizedReport << "\n\n";

    // Test completion message
    std::cout << "Build.prop analysis test completed successfully!\n";
}

int main() {
    try {
        testBuildPropAnalysis();
        return 0;
    } catch (const std::exception& e) {
        std::cerr << "Error during testing: " << e.what() << std::endl;
        return 1;
    } catch (...) {
        std::cerr << "Unknown error during testing" << std::endl;
        return 1;
    }
}