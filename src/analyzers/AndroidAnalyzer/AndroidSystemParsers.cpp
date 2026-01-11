#include "AndroidAnalyzer.h"
#include <iostream>
#include <sstream>
#include <algorithm>
#include <cstring>
#include <regex>
#include "fileSystem.h"

// Android System Parsers Implementation

bool AndroidAnalyzer::parseWifiConfig(const std::string& configPath) {
    std::string tempPath = "/tmp/wifi_config_" + std::to_string(std::time(nullptr));
    if (!fileExtractor_->extractFileByPath(configPath, tempPath)) return false;

    std::ifstream file(tempPath);
    std::string line;
    std::string ssid, psk, keyMgmt;

    bool isXml = (configPath.find(".xml") != std::string::npos);

    if (isXml) {
        // Simple XML scraping for WifiConfigStore.xml
        while (std::getline(file, line)) {
            if (line.find("name=\"SSID\"") != std::string::npos) {
                size_t start = line.find(">");
                size_t end = line.find("</");
                if (start != std::string::npos && end != std::string::npos) {
                    ssid = line.substr(start + 1, end - start - 1);
                    // Remove extra quotes if present (&quot;)
                    if (ssid.find("&quot;") != std::string::npos) {
                        ssid = std::regex_replace(ssid, std::regex("&quot;"), "");
                    }
                }
            } else if (line.find("name=\"PreSharedKey\"") != std::string::npos) {
                size_t start = line.find(">");
                size_t end = line.find("</");
                if (start != std::string::npos && end != std::string::npos) {
                    psk = line.substr(start + 1, end - start - 1);
                    if (psk.find("&quot;") != std::string::npos) {
                        psk = std::regex_replace(psk, std::regex("&quot;"), "");
                    }
                }
            } else if (line.find("name=\"KeyMgmt\"") != std::string::npos) {
                size_t start = line.find(">");
                size_t end = line.find("</");
                if (start != std::string::npos && end != std::string::npos) {
                    keyMgmt = line.substr(start + 1, end - start - 1);
                }
            }

            if (!ssid.empty() && (!psk.empty() || !keyMgmt.empty())) {
                WifiNetwork net{ssid, psk, keyMgmt};
                androidDb_->insertWifiNetwork(net);
                ssid = ""; psk = ""; keyMgmt = "";
            }
        }
    } else {
        // wpa_supplicant.conf parser
        while (std::getline(file, line)) {
            if (line.find("ssid=") != std::string::npos) {
                ssid = line.substr(line.find("=") + 1);
                if (ssid.size() >= 2 && ssid.front() == '"' && ssid.back() == '"') {
                    ssid = ssid.substr(1, ssid.size() - 2);
                }
            } else if (line.find("psk=") != std::string::npos) {
                psk = line.substr(line.find("=") + 1);
            } else if (line.find("key_mgmt=") != std::string::npos) {
                keyMgmt = line.substr(line.find("=") + 1);
            } else if (line.find("}") != std::string::npos) {
                if (!ssid.empty()) {
                    WifiNetwork net{ssid, psk, keyMgmt};
                    androidDb_->insertWifiNetwork(net);
                    ssid = ""; psk = ""; keyMgmt = "";
                }
            }
        }
    }
    std::filesystem::remove(tempPath);
    return true;
}

void AndroidAnalyzer::parseInstalledPackages(const std::string& xmlPath) {
    std::string tempPath = "/tmp/packages_" + std::to_string(std::time(nullptr)) + ".xml";
    if (!fileExtractor_->extractFileByPath(xmlPath, tempPath)) return;

    std::ifstream file(tempPath);
    std::string line;
    while (std::getline(file, line)) {
        // Very basic XML scraping - look for <package name="..." ...>
        if (line.find("<package") != std::string::npos) {
            auto extractAttr = [&](const std::string& attr) -> std::string {
                size_t pos = line.find(attr + "=\"");
                if (pos == std::string::npos) return "";
                size_t end = line.find("\"", pos + attr.length() + 2);
                return line.substr(pos + attr.length() + 2, end - (pos + attr.length() + 2));
            };

            InstalledPackageInfo pkg;
            pkg.packageName = extractAttr("name");
            pkg.codePath = extractAttr("codePath");
            pkg.version = extractAttr("version");
            pkg.installer = extractAttr("installer");

            if (!pkg.packageName.empty()) {
                androidDb_->insertInstalledPackage(pkg);
            }
        }
    }
    std::filesystem::remove(tempPath);
}

void AndroidAnalyzer::parseUsageStats(const std::string& usageStatsPath) {
    std::string tempDir = "/tmp/usagestats_" + std::to_string(std::time(nullptr));
    fs::create_directories(tempDir);

    // Extract simplified usage stats file (simulated as "1001" for daily)
    std::string targetFile = usageStatsPath + "/1001";
    std::string tempFile = tempDir + "/1001";

    if (fileExtractor_->extractFileByPath(targetFile, tempFile)) {
        std::ifstream file(tempFile);
        std::string line;
        while (std::getline(file, line)) {
            if (line.find("<package") != std::string::npos) {
                auto extractAttr = [&](const std::string& attr) -> std::string {
                    size_t pos = line.find(attr + "=\"");
                    if (pos == std::string::npos) return "";
                    size_t end = line.find("\"", pos + attr.length() + 2);
                    return line.substr(pos + attr.length() + 2, end - (pos + attr.length() + 2));
                };

                UsageStatRecord stat;
                stat.packageName = extractAttr("name");
                try { stat.totalTimeInForeground = std::stoll(extractAttr("timeActive")); } catch (...) { stat.totalTimeInForeground = 0; }
                try { stat.lastTimeUsed = std::stoll(extractAttr("lastTimeActive")); } catch (...) { stat.lastTimeUsed = 0; }
                stat.firstTimeStamp = 0;

                if (!stat.packageName.empty()) {
                    androidDb_->insertUsageStat(stat);
                }
            }
        }
    }
    fs::remove_all(tempDir);
}

void AndroidAnalyzer::analyzeSystemDirectory(const std::string& systemPath) {
    std::cout << "Starting system directory analysis..." << std::endl;

    // Create temp directory for extracted system files
    std::string tempSystemDir = "/tmp/system_analysis_" + std::to_string(std::time(nullptr));
    fs::create_directories(tempSystemDir);

    try {
        // Extract and analyze build.prop
        std::string buildPropTemp = tempSystemDir + "/build.prop";
        if (fileExtractor_->extractFileByPath("system/build.prop", buildPropTemp)) {
            analyzeBuildProperties(buildPropTemp);
        } else {
            std::cout << "Build properties file not found in image: system/build.prop" << std::endl;
        }

        // Extract and scan system apps
        extractAndScanSystemApps("system/app", tempSystemDir + "/app");
        extractAndScanSystemApps("system/priv-app", tempSystemDir + "/priv-app");

        // Extract and scan framework files
        extractAndScanFramework("system/framework", tempSystemDir + "/framework");

    } catch (const std::exception& e) {
        std::cerr << "Error during system directory analysis: " << e.what() << std::endl;
    }

    // Clean up temp directory
    fs::remove_all(tempSystemDir);

    std::cout << "System directory analysis completed." << std::endl;
}

void AndroidAnalyzer::scanSystemApps(const std::string& appDirPath) {
    if (!fs::exists(appDirPath) || !fs::is_directory(appDirPath)) {
        std::cout << "System app directory not found: " << appDirPath << std::endl;
        return;
    }

    bool isPrivileged = (appDirPath.find("priv-app") != std::string::npos);

    for (const auto& entry : fs::recursive_directory_iterator(appDirPath)) {
        if (entry.is_regular_file() && entry.path().extension() == ".apk") {
            std::string apkPath = entry.path().string();
            SystemAppInfo appInfo = analyzeSystemApk(apkPath, isPrivileged);
            if (!appInfo.packageName.empty()) {
                std::cout << "System App: " << appInfo.packageName << " at " << apkPath << std::endl;
                // Store or process appInfo as needed
            }
        }
    }
}

SystemAppInfo AndroidAnalyzer::analyzeSystemApk(const std::string& apkPath, bool isPrivileged) {
    SystemAppInfo info;
    info.apkPath = apkPath;
    info.isSystemApp = true;
    info.isPrivileged = isPrivileged;

    // Extract package name from APK (simplified - in real implementation, parse AndroidManifest.xml)
    // For now, use filename as package name approximation
    std::string filename = fs::path(apkPath).stem().string();
    info.packageName = filename;

    // Analyze signature
    info.signatureInfo = analyzeApk(apkPath);

    // Version info would require parsing APK manifest - placeholder
    info.versionName = "Unknown";
    info.versionCode = "Unknown";

    return info;
}

void AndroidAnalyzer::analyzeBuildProperties(const std::string& buildPropPath) {
    if (!fs::exists(buildPropPath)) {
        std::cout << "Build properties file not found: " << buildPropPath << std::endl;
        return;
    }

    std::ifstream file(buildPropPath);
    std::string line;
    std::cout << "Build Properties:" << std::endl;
    while (std::getline(file, line)) {
        if (!line.empty() && line[0] != '#') {
            std::cout << line << std::endl;

            // Parse key=value format
            size_t equalsPos = line.find('=');
            if (equalsPos != std::string::npos) {
                std::string key = line.substr(0, equalsPos);
                std::string value = line.substr(equalsPos + 1);

                // Store in database
                SystemBuildProperty prop{key, value};
                if (!androidDb_->insertBuildProperty(prop)) {
                    std::cerr << "Failed to insert build property: " << key << std::endl;
                }
            }
        }
    }
}

void AndroidAnalyzer::scanFrameworkDirectory(const std::string& frameworkPath) {
    if (!fs::exists(frameworkPath) || !fs::is_directory(frameworkPath)) {
        std::cout << "Framework directory not found: " << frameworkPath << std::endl;
        return;
    }

    std::cout << "Framework files:" << std::endl;
    for (const auto& entry : fs::directory_iterator(frameworkPath)) {
        if (entry.is_regular_file()) {
            std::string ext = entry.path().extension().string();
            if (ext == ".jar" || ext == ".dex" || ext == ".so") {
                std::cout << entry.path().filename().string() << std::endl;
            }
        }
    }
}

ApkSignatureInfo AndroidAnalyzer::analyzeApk(const std::string& apkPath) {
    ApkSignatureInfo info;
    info.apkPath = apkPath;
    info.hasSignature = false; // Simplified - in real implementation, check for signature
    info.signerName = "Unknown";
    info.certificateFingerprint = "Unknown";
    // TODO: Implement actual APK signature analysis
    return info;
}

void AndroidAnalyzer::extractAndScanSystemApps(const std::string& imageAppDir, const std::string& tempAppDir) {
    // For now, we'll extract known system APK files
    // In a full implementation, we would scan the directory first
    std::vector<std::string> knownSystemApks = {
        "system/app/SystemUI.apk",
        "system/priv-app/Settings.apk"
    };

    fs::create_directories(tempAppDir);

    for (const auto& apkPath : knownSystemApks) {
        std::string tempApkPath = tempAppDir + "/" + fs::path(apkPath).filename().string();
        if (fileExtractor_->extractFileByPath(apkPath, tempApkPath)) {
            bool isPrivileged = (apkPath.find("priv-app") != std::string::npos);
            SystemAppInfo appInfo = analyzeSystemApk(tempApkPath, isPrivileged);
            if (!appInfo.packageName.empty()) {
                std::cout << "System App: " << appInfo.packageName << " at " << apkPath << std::endl;

                // Store in database
                SystemAppRecord appRecord{
                    appInfo.packageName,
                    apkPath,
                    appInfo.versionName,
                    appInfo.versionCode,
                    appInfo.isSystemApp,
                    appInfo.isPrivileged
                };
                if (!androidDb_->insertSystemApp(appRecord)) {
                    std::cerr << "Failed to insert system app: " << appInfo.packageName << std::endl;
                }
            }
        } else {
            std::cout << "System APK not found: " << apkPath << std::endl;
        }
    }
}

void AndroidAnalyzer::extractAndScanFramework(const std::string& imageFrameworkDir, const std::string& tempFrameworkDir) {
    // Extract known framework files
    std::vector<std::string> knownFrameworkFiles = {
        "system/framework/framework.jar",
        "system/framework/framework.dex",
        "system/framework/framework.so"
    };

    fs::create_directories(tempFrameworkDir);
    std::cout << "Framework files:" << std::endl;

    for (const auto& frameworkFile : knownFrameworkFiles) {
        std::string tempFilePath = tempFrameworkDir + "/" + fs::path(frameworkFile).filename().string();
        if (fileExtractor_->extractFileByPath(frameworkFile, tempFilePath)) {
            std::string fileName = fs::path(frameworkFile).filename().string();
            std::cout << "Framework file: " << fileName << std::endl;

            // Get file size
            int64_t fileSize = 0;
            if (fs::exists(tempFilePath)) {
                fileSize = fs::file_size(tempFilePath);
            }

            // Determine file type
            std::string fileType;
            if (fileName.find(".jar") != std::string::npos) {
                fileType = "jar";
            } else if (fileName.find(".dex") != std::string::npos) {
                fileType = "dex";
            } else if (fileName.find(".so") != std::string::npos) {
                fileType = "so";
            } else {
                fileType = "unknown";
            }

            // Store in database
            FrameworkFileRecord fileRecord{fileName, frameworkFile, fileType, fileSize};
            if (!androidDb_->insertFrameworkFile(fileRecord)) {
                std::cerr << "Failed to insert framework file: " << fileName << std::endl;
            }
        }
    }
}
