// test_linux_security_parsers_gtest.cpp
// Comprehensive GTest-based unit tests for Linux security posture parsers
// Tests: SetuidAnalyzer, CapabilityAnalyzer, SELinuxAnalyzer, AppArmorParser

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <sstream>
#include <fstream>

// Include the security parser headers
#include "LinuxFilesAnalyzer/Parsers/Security/SetuidAnalyzer.h"
#include "LinuxFilesAnalyzer/Parsers/Security/CapabilityAnalyzer.h"
#include "LinuxFilesAnalyzer/Parsers/Security/SELinuxAnalyzer.h"
#include "LinuxFilesAnalyzer/Parsers/Security/AppArmorParser.h"

using namespace LinuxAnalysis;
using ::testing::HasSubstr;
using ::testing::Eq;
using ::testing::Contains;
using ::testing::Not;

// ============================================================================
// SetuidAnalyzer Tests
// ============================================================================

class SetuidAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {}
    void TearDown() override {}
};

TEST_F(SetuidAnalyzerTest, ParseFindOutput_ValidSetuidFiles) {
    std::string findOutput = R"(
12345 -rwsr-xr-x root root 45000 Jan 1 12:00 /usr/bin/sudo
12346 -rwsr-xr-x root root 35000 Jan 1 12:00 /bin/ping
12347 -rwxr-xr-x root root 40000 Jan 1 12:00 /usr/bin/ls
)";

    auto result = SetuidAnalyzer::parseFindOutput(findOutput);

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.setuidFiles.size(), 2);
    EXPECT_EQ(result.setgidFiles.size(), 0);

    // Check sudo file
    EXPECT_EQ(result.setuidFiles[0].filePath, "/usr/bin/sudo");
    EXPECT_TRUE(result.setuidFiles[0].isSetuid);
    EXPECT_FALSE(result.setuidFiles[0].isSetgid);
    EXPECT_EQ(result.setuidFiles[0].owner, "root");
}

TEST_F(SetuidAnalyzerTest, ParseFindOutput_SetgidFiles) {
    std::string findOutput = R"(
12345 -rwxr-sr-x root root 45000 Jan 1 12:00 /usr/bin/write
)";

    auto result = SetuidAnalyzer::parseFindOutput(findOutput);

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.setgidFiles.size(), 1);
    EXPECT_TRUE(result.setgidFiles[0].isSetgid);
    EXPECT_FALSE(result.setgidFiles[0].isSetuid);
}

TEST_F(SetuidAnalyzerTest, FlagSuspiciousFiles_TemporaryDirectory) {
    std::vector<SetuidFileInfo> files;
    SetuidFileInfo file;
    file.filePath = "/tmp/malicious";
    file.owner = "root";
    files.push_back(file);

    auto suspicious = SetuidAnalyzer::flagSuspiciousFiles(files);

    EXPECT_EQ(suspicious.size(), 1);
    EXPECT_TRUE(suspicious[0].isSuspicious);
    EXPECT_THAT(suspicious[0].suspiciousReason, HasSubstr("temporary directory"));
}

TEST_F(SetuidAnalyzerTest, FlagSuspiciousFiles_NonRootOwner) {
    std::vector<SetuidFileInfo> files;
    SetuidFileInfo file;
    file.filePath = "/usr/bin/backdoor";
    file.owner = "hacker";
    files.push_back(file);

    auto suspicious = SetuidAnalyzer::flagSuspiciousFiles(files);

    EXPECT_EQ(suspicious.size(), 1);
    EXPECT_TRUE(suspicious[0].isSuspicious);
    EXPECT_THAT(suspicious[0].suspiciousReason, HasSubstr("Non-root owner"));
}

TEST_F(SetuidAnalyzerTest, KnownGoodFile_Whitelist) {
    EXPECT_TRUE(SetuidAnalyzer::isKnownGoodFile("/usr/bin/sudo"));
    EXPECT_TRUE(SetuidAnalyzer::isKnownGoodFile("/bin/ping"));
    EXPECT_FALSE(SetuidAnalyzer::isKnownGoodFile("/tmp/malicious"));
}

TEST_F(SetuidAnalyzerTest, ParseFindOutput_InvalidLine) {
    std::string findOutput = "invalid line format\n";

    auto result = SetuidAnalyzer::parseFindOutput(findOutput);

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.setuidFiles.size(), 0);
}

// ============================================================================
// CapabilityAnalyzer Tests
// ============================================================================

class CapabilityAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {}
    void TearDown() override {}
};

TEST_F(CapabilityAnalyzerTest, ParseFileCapabilities_ValidOutput) {
    std::string getcapOutput = R"(
/usr/bin/ping = cap_net_raw+ep
/usr/sbin/tcpdump = cap_net_raw+ep
)";

    auto result = CapabilityAnalyzer::parseFileCapabilities(getcapOutput);

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.capabilities.size(), 2);
    EXPECT_EQ(result.capabilities[0].filePath, "/usr/bin/ping");
}

TEST_F(CapabilityAnalyzerTest, ParseFileCapabilities_MultipleCapabilities) {
    std::string getcapOutput = "/usr/sbin/tcpdump = cap_net_raw,cap_net_admin+ep";

    auto result = CapabilityAnalyzer::parseFileCapabilities(getcapOutput);

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.capabilities.size(), 1);
    EXPECT_EQ(result.capabilities[0].capabilities.size(), 2);
}

TEST_F(CapabilityAnalyzerTest, FlagDangerousCapabilities_Setuid) {
    std::vector<FileCapability> caps;
    FileCapability cap;
    cap.filePath = "/usr/bin/suspicious";
    cap.capabilities.push_back("cap_setuid");
    caps.push_back(cap);

    auto dangerous = CapabilityAnalyzer::flagDangerousCapabilities(caps);

    EXPECT_EQ(dangerous.size(), 1);
    EXPECT_TRUE(dangerous[0].isSuspicious);
}

TEST_F(CapabilityAnalyzerTest, FlagDangerousCapabilities_SysAdmin) {
    std::vector<FileCapability> caps;
    FileCapability cap;
    cap.filePath = "/usr/bin/tool";
    cap.capabilities.push_back("cap_sys_admin");
    caps.push_back(cap);

    auto dangerous = CapabilityAnalyzer::flagDangerousCapabilities(caps);

    EXPECT_EQ(dangerous.size(), 1);
}

TEST_F(CapabilityAnalyzerTest, IsDangerousCapability) {
    EXPECT_TRUE(CapabilityAnalyzer::isDangerousCapability("cap_setuid"));
    EXPECT_TRUE(CapabilityAnalyzer::isDangerousCapability("cap_net_raw"));
    EXPECT_FALSE(CapabilityAnalyzer::isDangerousCapability("cap_chown"));
}

TEST_F(CapabilityAnalyzerTest, ParseCapabilityFlags) {
    std::string getcapOutput = "/usr/bin/test = cap_net_admin+eip";

    auto result = CapabilityAnalyzer::parseFileCapabilities(getcapOutput);

    EXPECT_TRUE(result.success);
    EXPECT_TRUE(result.capabilities[0].isInherited);
}

// ============================================================================
// SELinuxAnalyzer Tests
// ============================================================================

class SELinuxAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {}
    void TearDown() override {}
};

TEST_F(SELinuxAnalyzerTest, ParseStatus_EnforcingMode) {
    std::string config = R"(
SELINUX=enforcing
SELINUXTYPE=targeted
)";

    auto result = SELinuxAnalyzer::parseStatusFromContent(config);

    EXPECT_TRUE(result.success);
    EXPECT_TRUE(SELinuxAnalyzer::isEnabled(result.status));
    EXPECT_TRUE(SELinuxAnalyzer::isEnforcing(result.status));
    EXPECT_EQ(result.status.mode, "enforcing");
    EXPECT_EQ(result.status.policyName, "targeted");
}

TEST_F(SELinuxAnalyzerTest, ParseStatus_PermissiveMode) {
    std::string config = "SELINUX=permissive\n";

    auto result = SELinuxAnalyzer::parseStatusFromContent(config);

    EXPECT_TRUE(result.success);
    EXPECT_TRUE(SELinuxAnalyzer::isEnabled(result.status));
    EXPECT_FALSE(SELinuxAnalyzer::isEnforcing(result.status));
    EXPECT_EQ(result.status.mode, "permissive");
}

TEST_F(SELinuxAnalyzerTest, ParseStatus_Disabled) {
    std::string config = "SELINUX=disabled\n";

    auto result = SELinuxAnalyzer::parseStatusFromContent(config);

    EXPECT_TRUE(result.success);
    EXPECT_FALSE(SELinuxAnalyzer::isEnabled(result.status));
}

TEST_F(SELinuxAnalyzerTest, ExtractAVCDenials_ValidDenial) {
    std::string auditLog = R"(
type=AVC msg=audit(1234567890.123:456): avc: denied { read } for pid=1234 comm="httpd" path="/var/www/html/secret" scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:user_home_t:s0 tclass=file
)";

    auto result = SELinuxAnalyzer::extractAVCDenialsFromContent(auditLog);

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.avcDenials.size(), 1);
    EXPECT_EQ(result.avcDenials[0].permission, "read");
    EXPECT_EQ(result.avcDenials[0].sourceContext, "system_u:system_r:httpd_t:s0");
}

TEST_F(SELinuxAnalyzerTest, ParseAVCDenialLine_Complete) {
    std::string line = R"(type=AVC msg=audit(1234567890.123:456): avc: denied { write } for pid=1234 comm="test" path="/tmp/test" scontext=system_u:system_r:test_t:s0 tcontext=system_u:object_r:tmp_t:s0 tclass=file)";

    auto denial = SELinuxAnalyzer::parseAVCDenialLine(line);

    EXPECT_EQ(denial.permission, "write");
    EXPECT_EQ(denial.executablePath, "/tmp/test");
}

TEST_F(SELinuxAnalyzerTest, ParseAVCDenialLine_ExecutableFromComm) {
    std::string line = R"(type=AVC msg=audit(1234567890.123:456): avc: denied { read } for pid=1234 comm="httpd" scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:etc_t:s0 tclass=file)";

    auto denial = SELinuxAnalyzer::parseAVCDenialLine(line);

    EXPECT_EQ(denial.executablePath, "httpd");
}

TEST_F(SELinuxAnalyzerTest, ExtractAVCDenials_NoDenials) {
    std::string auditLog = "type=SYSCALL msg=audit(1234567890.123:456): arch=c000003e\n";

    auto result = SELinuxAnalyzer::extractAVCDenialsFromContent(auditLog);

    EXPECT_TRUE(result.success);
    EXPECT_EQ(result.avcDenials.size(), 0);
}

// ============================================================================
// AppArmorParser Tests
// ============================================================================

class AppArmorParserTest : public ::testing::Test {
protected:
    void SetUp() override {}
    void TearDown() override {}
};

TEST_F(AppArmorParserTest, ParseProfileContent_SimpleProfile) {
    std::string profile = R"(
#include <tunables/global>

profile test_profile {
  #include <abstractions/base>
  /usr/bin/test mr,
  /etc/test/** r,
}
)";

    auto profileResult = AppArmorParser::parseProfileContent(profile, "/etc/apparmor.d/test");

    EXPECT_EQ(profileResult.profileName, "test_profile");
    EXPECT_FALSE(profileResult.allowedPaths.empty());
}

TEST_F(AppArmorParserTest, ParseProfileContent_WithDenyRules) {
    std::string profile = R"(
profile foo {
  /usr/bin/foo mr,
  deny /var/log/** w,
}
)";

    auto profileResult = AppArmorParser::parseProfileContent(profile, "/etc/apparmor.d/foo");

    EXPECT_EQ(profileResult.profileName, "foo");
    EXPECT_FALSE(profileResult.deniedPaths.empty());
}

TEST_F(AppArmorParserTest, ParseViolationLine_Complete) {
    std::string line = R"(Jan  1 12:00:00 hostname kernel: [1234.56] apparmor="DENIED" operation="open" profile="/usr/bin/foo" name="/var/log/syslog" pid=1234 comm="foo" requested_mask="w" denied_mask="w")";

    auto violation = AppArmorParser::parseViolationLine(line);

    EXPECT_EQ(violation.profile, "/usr/bin/foo");
    EXPECT_EQ(violation.operation, "open");
    EXPECT_EQ(violation.targetPath, "/var/log/syslog");
    EXPECT_EQ(violation.executable, "foo");
    EXPECT_EQ(violation.status, "DENIED");
}

TEST_F(AppArmorParserTest, ParseViolationLine_Minimal) {
    std::string line = R"(apparmor="DENIED" operation="open" profile="test" name="/tmp/test")";

    auto violation = AppArmorParser::parseViolationLine(line);

    EXPECT_EQ(violation.profile, "test");
    EXPECT_EQ(violation.operation, "open");
    EXPECT_EQ(violation.targetPath, "/tmp/test");
}

TEST_F(AppArmorParserTest, ParseProfileDeclaration_WithFlags) {
    std::string declaration = "profile test_profile flags=(attach_disconnected) {";

    auto name = AppArmorParser::parseProfileDeclaration(declaration);

    EXPECT_EQ(name, "test_profile");
}

TEST_F(AppArmorParserTest, ParseFileRule_AllowRule) {
    AppArmorProfile profile;
    std::string rule = "/usr/bin/test mr,";

    AppArmorParser::parseFileRule(rule, profile);

    EXPECT_THAT(profile.allowedPaths, Contains("/usr/bin/test"));
    EXPECT_TRUE(profile.deniedPaths.empty());
}

TEST_F(AppArmorParserTest, ParseFileRule_DenyRule) {
    AppArmorProfile profile;
    std::string rule = "deny /var/log/** w,";

    AppArmorParser::parseFileRule(rule, profile);

    EXPECT_THAT(profile.deniedPaths, Contains("/var/log/**"));
    EXPECT_TRUE(profile.allowedPaths.empty());
}

// ============================================================================
// Integration Tests
// ============================================================================

class SecurityParsersIntegrationTest : public ::testing::Test {
protected:
    void SetUp() override {}
    void TearDown() override {}
};

TEST_F(SecurityParsersIntegrationTest, SetuidAndCapabilityAnalysis) {
    // Test combined analysis of setuid and capabilities
    std::string findOutput = "12345 -rwsr-xr-x root root 45000 Jan 1 12:00 /usr/bin/sudo\n";
    std::string getcapOutput = "/usr/bin/sudo = cap_setuid+ep\n";

    auto setuidResult = SetuidAnalyzer::parseFindOutput(findOutput);
    auto capResult = CapabilityAnalyzer::parseFileCapabilities(getcapOutput);

    EXPECT_TRUE(setuidResult.success);
    EXPECT_TRUE(capResult.success);
    EXPECT_EQ(setuidResult.setuidFiles.size(), 1);
    EXPECT_EQ(capResult.capabilities.size(), 1);
}

TEST_F(SecurityParsersIntegrationTest, SELinuxAndAppArmor) {
    // Test that both SELinux and AppArmor parsers work correctly
    std::string selinuxConfig = "SELINUX=enforcing\n";
    std::string apparmorProfile = "profile test { /usr/bin/test mr, }\n";

    auto selinuxResult = SELinuxAnalyzer::parseStatusFromContent(selinuxConfig);
    auto apparmorResult = AppArmorParser::parseProfileContent(apparmorProfile, "/etc/apparmor.d/test");

    EXPECT_TRUE(selinuxResult.success);
    EXPECT_TRUE(SELinuxAnalyzer::isEnabled(selinuxResult.status));
    EXPECT_FALSE(apparmorResult.profileName.empty());
}

// Main function for GTest
int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
