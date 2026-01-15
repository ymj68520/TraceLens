// test_android_analyzer_gtest.cpp
// GTest-based unit tests for AndroidAnalyzer module
// Tests: data types, BuildPropAnalyzer structures

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <filesystem>

#include "AndroidAnalyzer/AndroidDataTypes.h"
#include "DatabaseManager/DatabaseManagerDataTypes.h"

using ::testing::Eq;
using ::testing::IsEmpty;

namespace fs = std::filesystem;

// ============================================================================
// AppData Structure Tests
// ============================================================================

class AppDataTest : public ::testing::Test {};

TEST_F(AppDataTest, DefaultValues) {
    AppData data;
    EXPECT_TRUE(data.packageName.empty());
    EXPECT_TRUE(data.installPath.empty());
    EXPECT_TRUE(data.dbFiles.empty());
}

TEST_F(AppDataTest, PopulatedValues) {
    AppData data;
    data.packageName = "com.example.app";
    data.installPath = "/data/app/com.example.app";
    
    // 使用 FileRecord 替代简单字符串，包含完整路径信息
    FileRecord db1;
    db1.name = "database1.db";
    db1.path = "/data/data/com.example.app/databases/database1.db";
    
    FileRecord db2;
    db2.name = "database2.db";
    db2.path = "/data/data/com.example.app/databases/database2.db";
    
    data.dbFiles = {db1, db2};
    
    EXPECT_EQ(data.packageName, "com.example.app");
    EXPECT_EQ(data.dbFiles.size(), 2u);
    EXPECT_EQ(data.dbFiles[0].name, "database1.db");
    EXPECT_EQ(data.dbFiles[0].path, "/data/data/com.example.app/databases/database1.db");
}

// ============================================================================
// ChatMessage Structure Tests
// ============================================================================

class ChatMessageTest : public ::testing::Test {};

TEST_F(ChatMessageTest, DefaultValues) {
    ChatMessage msg;
    EXPECT_TRUE(msg.sender.empty());
    EXPECT_TRUE(msg.receiver.empty());
    EXPECT_TRUE(msg.content.empty());
    EXPECT_TRUE(msg.timestamp.empty());
    EXPECT_TRUE(msg.appName.empty());
}

TEST_F(ChatMessageTest, PopulatedValues) {
    ChatMessage msg;
    msg.sender = "Alice";
    msg.receiver = "Bob";
    msg.content = "Hello, World!";
    msg.timestamp = "2024-01-01 12:00:00";
    msg.appName = "WhatsApp";
    
    EXPECT_EQ(msg.sender, "Alice");
    EXPECT_EQ(msg.content, "Hello, World!");
}

// ============================================================================
// DeviceInfo Structure Tests
// ============================================================================

class DeviceInfoTest : public ::testing::Test {};

TEST_F(DeviceInfoTest, DefaultValues) {
    DeviceInfo info{};
    EXPECT_TRUE(info.manufacturer.empty());
    EXPECT_TRUE(info.brand.empty());
    EXPECT_TRUE(info.model.empty());
    EXPECT_EQ(info.sdkVersion, 0);
}

TEST_F(DeviceInfoTest, PopulatedValues) {
    DeviceInfo info;
    info.manufacturer = "Samsung";
    info.brand = "Samsung";
    info.model = "Galaxy S21";
    info.device = "o1s";
    info.product = "o1sxxx";
    info.fingerprint = "samsung/o1sxxx/o1s:12/SP1A.210812.016/G991BXXU5CVJA:user/release-keys";
    info.securityPatchLevel = "2024-01-01";
    info.buildVersion = "12";
    info.sdkVersion = 31;
    
    EXPECT_EQ(info.manufacturer, "Samsung");
    EXPECT_EQ(info.sdkVersion, 31);
    EXPECT_FALSE(info.fingerprint.empty());
}

// ============================================================================
// SecurityConfig Structure Tests
// ============================================================================

class SecurityConfigTest : public ::testing::Test {};

TEST_F(SecurityConfigTest, DefaultValues) {
    SecurityConfig config{};
    EXPECT_FALSE(config.adbEnabled);
    EXPECT_FALSE(config.debugEnabled);
    EXPECT_TRUE(config.securityFlags.empty());
}

TEST_F(SecurityConfigTest, SecureDevice) {
    SecurityConfig config{};
    config.adbEnabled = false;
    config.debugEnabled = false;
    config.mockLocationDisabled = true;
    config.secureEnabled = true;
    config.otaEncrypted = true;
    
    EXPECT_FALSE(config.adbEnabled);
    EXPECT_TRUE(config.secureEnabled);
}

TEST_F(SecurityConfigTest, DebugDevice) {
    SecurityConfig config{};
    config.adbEnabled = true;
    config.debugEnabled = true;
    config.securityFlags = {"userdebug", "test-keys"};
    
    EXPECT_TRUE(config.adbEnabled);
    EXPECT_EQ(config.securityFlags.size(), 2u);
}

// ============================================================================
// SystemConfig Structure Tests
// ============================================================================

class SystemConfigTest : public ::testing::Test {};

TEST_F(SystemConfigTest, DefaultValues) {
    SystemConfig config{};
    EXPECT_TRUE(config.cpuArch.empty());
    EXPECT_TRUE(config.cpuAbilist.empty());
    EXPECT_EQ(config.screenDensity, 0);
}

TEST_F(SystemConfigTest, Arm64Device) {
    SystemConfig config;
    config.cpuArch = "arm64-v8a";
    config.cpuAbilist = {"arm64-v8a", "armeabi-v7a", "armeabi"};
    config.screenDensity = 420;
    config.locale = "en-US";
    config.openglVersion = "3.2";
    
    EXPECT_EQ(config.cpuArch, "arm64-v8a");
    EXPECT_EQ(config.cpuAbilist.size(), 3u);
}

// ============================================================================
// BuildPropEntry Structure Tests
// ============================================================================

class BuildPropEntryTest : public ::testing::Test {};

TEST_F(BuildPropEntryTest, DefaultValues) {
    BuildPropEntry entry{};
    EXPECT_TRUE(entry.key.empty());
    EXPECT_TRUE(entry.value.empty());
    EXPECT_FALSE(entry.isIdentified);
}

TEST_F(BuildPropEntryTest, IdentifiedEntry) {
    BuildPropEntry entry;
    entry.key = "ro.build.version.sdk";
    entry.value = "31";
    entry.category = "Build";
    entry.description = "Android SDK version";
    entry.securityImplication = "";
    entry.isIdentified = true;
    
    EXPECT_EQ(entry.key, "ro.build.version.sdk");
    EXPECT_TRUE(entry.isIdentified);
}

TEST_F(BuildPropEntryTest, SecurityRelevantEntry) {
    BuildPropEntry entry;
    entry.key = "ro.debuggable";
    entry.value = "1";
    entry.category = "Security";
    entry.description = "Device is debuggable";
    entry.securityImplication = "Device allows debugging, potential security risk";
    entry.isIdentified = true;
    
    EXPECT_FALSE(entry.securityImplication.empty());
}

// ============================================================================
// ForensicAnalysis Structure Tests
// ============================================================================

class ForensicAnalysisTest : public ::testing::Test {};

TEST_F(ForensicAnalysisTest, DefaultValues) {
    ForensicAnalysis analysis{};
    EXPECT_TRUE(analysis.deviceIdentifier.empty());
    EXPECT_TRUE(analysis.securityConcerns.empty());
    EXPECT_TRUE(analysis.riskAssessment.empty());
}

TEST_F(ForensicAnalysisTest, PopulatedAnalysis) {
    ForensicAnalysis analysis;
    analysis.deviceIdentifier = "ABC123DEF456";
    analysis.extractionDate = "2024-01-15";
    analysis.securityConcerns = {"USB debugging enabled", "Unknown sources allowed"};
    analysis.unusualConfigurations = {"Custom ROM detected"};
    analysis.riskAssessment = "Medium";
    
    EXPECT_EQ(analysis.securityConcerns.size(), 2u);
    EXPECT_EQ(analysis.riskAssessment, "Medium");
}

// ============================================================================
// BuildPropAnalysisResult Structure Tests
// ============================================================================

class BuildPropAnalysisResultTest : public ::testing::Test {};

TEST_F(BuildPropAnalysisResultTest, DefaultValues) {
    BuildPropAnalysisResult result{};
    EXPECT_TRUE(result.allEntries.empty());
    EXPECT_TRUE(result.unrecognizedEntries.empty());
    EXPECT_TRUE(result.securityRelevantEntries.empty());
}

TEST_F(BuildPropAnalysisResultTest, ContainsNestedStructures) {
    BuildPropAnalysisResult result;
    
    // Fill device info
    result.deviceInfo.manufacturer = "Google";
    result.deviceInfo.model = "Pixel 6";
    result.deviceInfo.sdkVersion = 33;
    
    // Fill security config
    result.securityConfig.adbEnabled = false;
    result.securityConfig.secureEnabled = true;
    
    // Add entries
    BuildPropEntry entry;
    entry.key = "ro.product.model";
    entry.value = "Pixel 6";
    result.allEntries.push_back(entry);
    
    EXPECT_EQ(result.deviceInfo.manufacturer, "Google");
    EXPECT_EQ(result.allEntries.size(), 1u);
}

// ============================================================================
// InstalledPackageInfo Structure Tests
// ============================================================================

class InstalledPackageInfoTest : public ::testing::Test {};

TEST_F(InstalledPackageInfoTest, DefaultValues) {
    InstalledPackageInfo info{};
    EXPECT_TRUE(info.packageName.empty());
    EXPECT_EQ(info.firstInstallTime, 0);
    EXPECT_EQ(info.lastUpdateTime, 0);
}

TEST_F(InstalledPackageInfoTest, PopulatedValues) {
    InstalledPackageInfo info;
    info.packageName = "com.google.android.apps.maps";
    info.codePath = "/data/app/com.google.android.apps.maps";
    info.nativeLibraryPath = "/data/app/com.google.android.apps.maps/lib/arm64";
    info.firstInstallTime = 1609459200000;  // Jan 1, 2021
    info.lastUpdateTime = 1704067200000;    // Jan 1, 2024
    info.version = "11.58.0703";
    info.installer = "com.android.vending";
    
    EXPECT_EQ(info.packageName, "com.google.android.apps.maps");
    EXPECT_GT(info.lastUpdateTime, info.firstInstallTime);
}

// ============================================================================
// WifiNetwork Structure Tests
// ============================================================================

class WifiNetworkTest : public ::testing::Test {};

TEST_F(WifiNetworkTest, DefaultValues) {
    WifiNetwork network{};
    EXPECT_TRUE(network.ssid.empty());
    EXPECT_TRUE(network.preSharedKey.empty());
    EXPECT_TRUE(network.keyMgmt.empty());
}

TEST_F(WifiNetworkTest, WPA2Network) {
    WifiNetwork network;
    network.ssid = "HomeNetwork";
    network.preSharedKey = "***hidden***";
    network.keyMgmt = "WPA-PSK";
    
    EXPECT_EQ(network.ssid, "HomeNetwork");
    EXPECT_EQ(network.keyMgmt, "WPA-PSK");
}

// ============================================================================
// ChromeHistoryItem Structure Tests
// ============================================================================

class ChromeHistoryItemTest : public ::testing::Test {};

TEST_F(ChromeHistoryItemTest, DefaultValues) {
    ChromeHistoryItem item{};
    EXPECT_TRUE(item.url.empty());
    EXPECT_TRUE(item.title.empty());
    EXPECT_EQ(item.visitCount, 0);
    EXPECT_EQ(item.lastVisitTime, 0);
}

TEST_F(ChromeHistoryItemTest, PopulatedValues) {
    ChromeHistoryItem item;
    item.url = "https://www.google.com";
    item.title = "Google";
    item.visitCount = 100;
    item.lastVisitTime = 1704067200000;
    
    EXPECT_EQ(item.url, "https://www.google.com");
    EXPECT_EQ(item.visitCount, 100);
}

// ============================================================================
// UsageStatRecord Structure Tests
// ============================================================================

class UsageStatRecordTest : public ::testing::Test {};

TEST_F(UsageStatRecordTest, DefaultValues) {
    UsageStatRecord record{};
    EXPECT_TRUE(record.packageName.empty());
    EXPECT_EQ(record.totalTimeInForeground, 0);
    EXPECT_EQ(record.lastTimeUsed, 0);
}

TEST_F(UsageStatRecordTest, ActiveApp) {
    UsageStatRecord record;
    record.packageName = "com.whatsapp";
    record.totalTimeInForeground = 3600000;  // 1 hour in ms
    record.lastTimeUsed = 1704067200000;
    record.firstTimeStamp = 1609459200000;
    
    EXPECT_EQ(record.packageName, "com.whatsapp");
    EXPECT_EQ(record.totalTimeInForeground, 3600000);
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
