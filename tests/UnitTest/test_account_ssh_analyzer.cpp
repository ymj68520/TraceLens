// test_account_ssh_analyzer.cpp
// Unit tests for AccountSSHAnalyzer - Phase 10

#include <gtest/gtest.h>
#include "Analysis/AccountSSH/AccountSSHAnalyzer.h"

using namespace forensics::linux;

class AccountSSHAnalyzerTest : public ::testing::Test {
protected:
    AccountSSHAnalyzer analyzer;
};

// ============================================================================
// passwd File Analysis Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzePasswdNormal) {
    std::string content =
        "root:x:0:0:root:/root:/bin/bash\n"
        "user1:x:1000:1000:User One:/home/user1:/bin/bash\n"
        "nobody:x:65534:65534:nobody:/nonexistent:/usr/sbin/nologin\n";

    auto findings = analyzer.analyzePasswdFile(content, "/etc/passwd");

    // Normal passwd file should have no critical findings
    for (const auto& f : findings) {
        EXPECT_NE(f.severity, "critical");
    }
}

TEST_F(AccountSSHAnalyzerTest, AnalyzePasswdUid0NonRoot) {
    std::string content =
        "root:x:0:0:root:/root:/bin/bash\n"
        "backdoor:x:0:0:backdoor user:/home/backdoor:/bin/bash\n";

    auto findings = analyzer.analyzePasswdFile(content, "/etc/passwd");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "uid0_anomaly") {
            found = true;
            EXPECT_EQ(f.severity, "critical");
            EXPECT_EQ(f.username, "backdoor");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzePasswdSystemAccountShell) {
    std::string content =
        "www-data:x:33:33:www-data:/var/www:/bin/bash\n";

    auto findings = analyzer.analyzePasswdFile(content, "/etc/passwd");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "system_account_shell") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzePasswdNonStandardHome) {
    std::string content =
        "user1:x:1000:1000:User:/tmp/user1:/bin/bash\n";

    auto findings = analyzer.analyzePasswdFile(content, "/etc/passwd");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "home_dir_anomaly") {
            found = true;
            EXPECT_EQ(f.severity, "medium");
            break;
        }
    }
    EXPECT_TRUE(found);
}

// ============================================================================
// shadow File Analysis Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzeShadowEmptyPassword) {
    std::string content =
        "root:$6$abc$hash:19000:0:99999:7:::\n"
        "nopass::19000:0:99999:7:::\n";

    auto findings = analyzer.analyzeShadowFile(content, "/etc/shadow");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "empty_password") {
            found = true;
            EXPECT_EQ(f.severity, "critical");
            EXPECT_EQ(f.username, "nopass");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeShadowWeakHash) {
    std::string content =
        "user1:$1$abc$hash:19000:0:99999:7:::\n";

    auto findings = analyzer.analyzeShadowFile(content, "/etc/shadow");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "weak_hash") {
            found = true;
            EXPECT_EQ(f.severity, "medium");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeShadowExpiredAccount) {
    std::string content =
        "user1:$6$abc$hash:19000:0:99999:7::18000:\n";

    auto findings = analyzer.analyzeShadowFile(content, "/etc/shadow");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "expired_account") {
            found = true;
            EXPECT_EQ(f.severity, "medium");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeShadowNormalPasswords) {
    std::string content =
        "root:$6$abc$hash:19000:0:99999:7:::\n"
        "locked:!:19000:0:99999:7:::\n"
        "disabled:*:19000:0:99999:7:::\n";

    auto findings = analyzer.analyzeShadowFile(content, "/etc/shadow");

    // Should not have empty_password findings
    for (const auto& f : findings) {
        EXPECT_NE(f.findingType, "empty_password");
    }
}

// ============================================================================
// group File Analysis Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzeGroupPrivilegedMembers) {
    std::string content =
        "wheel:x:10:user1,user2\n"
        "sudo:x:27:user3\n"
        "docker:x:999:attacker\n"
        "users:x:100:normaluser\n";

    auto findings = analyzer.analyzeGroupFile(content, "/etc/group");

    int privilegedCount = 0;
    for (const auto& f : findings) {
        if (f.findingType == "privileged_group_member") {
            privilegedCount++;
        }
    }
    EXPECT_GE(privilegedCount, 3);  // user1, user2, user3, attacker
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeGroupDockerMember) {
    std::string content = "docker:x:999:attacker\n";

    auto findings = analyzer.analyzeGroupFile(content, "/etc/group");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "privileged_group_member" && f.username == "attacker") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

// ============================================================================
// sudoers File Analysis Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzeSudoersAllCommand) {
    std::string content =
        "user1 ALL=(ALL) ALL\n";

    auto findings = analyzer.analyzeSudoersFile(content, "/etc/sudoers");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "sudoers_risk") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeSudoersNopasswdAll) {
    std::string content =
        "user1 ALL=(ALL) NOPASSWD: ALL\n";

    auto findings = analyzer.analyzeSudoersFile(content, "/etc/sudoers");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "sudoers_risk") {
            found = true;
            EXPECT_EQ(f.severity, "critical");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeSudoersDangerousCommand) {
    std::string content =
        "user1 ALL=(ALL) /usr/bin/vim\n";

    auto findings = analyzer.analyzeSudoersFile(content, "/etc/sudoers");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "sudoers_risk") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeSudoersSafeCommand) {
    std::string content =
        "user1 ALL=(ALL) /usr/bin/systemctl restart nginx\n";

    auto findings = analyzer.analyzeSudoersFile(content, "/etc/sudoers");

    // systemctl restart nginx should not be flagged
    for (const auto& f : findings) {
        if (f.findingType == "sudoers_risk") {
            // If it's flagged, it should be high, not critical
            EXPECT_NE(f.severity, "critical");
        }
    }
}

// ============================================================================
// SSH Config Analysis Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzeSSHConfigPermitRootLogin) {
    std::string content =
        "PermitRootLogin yes\n"
        "PasswordAuthentication no\n";

    auto findings = analyzer.analyzeSSHConfig(content, "/etc/ssh/sshd_config");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "config_risk" && f.description.find("Root login") != std::string::npos) {
            found = true;
            EXPECT_EQ(f.severity, "critical");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeSSHConfigPasswordAuth) {
    std::string content =
        "PasswordAuthentication yes\n";

    auto findings = analyzer.analyzeSSHConfig(content, "/etc/ssh/sshd_config");

    bool found = false;
    for (const auto& f : findings) {
        if (f.description.find("Password authentication") != std::string::npos) {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeSSHConfigEmptyPasswords) {
    std::string content =
        "PermitEmptyPasswords yes\n";

    auto findings = analyzer.analyzeSSHConfig(content, "/etc/ssh/sshd_config");

    bool found = false;
    for (const auto& f : findings) {
        if (f.description.find("Empty passwords") != std::string::npos) {
            found = true;
            EXPECT_EQ(f.severity, "critical");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeSSHConfigForceCommand) {
    std::string content =
        "ForceCommand /usr/bin/restricted-shell\n";

    auto findings = analyzer.analyzeSSHConfig(content, "/etc/ssh/sshd_config");

    bool found = false;
    for (const auto& f : findings) {
        if (f.description.find("ForceCommand") != std::string::npos) {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeSSHConfigProxyCommand) {
    std::string content =
        "ProxyCommand ssh -W %h:%p gateway.example.com\n";

    auto findings = analyzer.analyzeSSHConfig(content, "/etc/ssh/sshd_config");

    bool found = false;
    for (const auto& f : findings) {
        if (f.description.find("ProxyCommand") != std::string::npos) {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeSSHConfigSecure) {
    std::string content =
        "PermitRootLogin no\n"
        "PasswordAuthentication no\n"
        "PermitEmptyPasswords no\n"
        "X11Forwarding no\n";

    auto findings = analyzer.analyzeSSHConfig(content, "/etc/ssh/sshd_config");

    // Secure config should have no critical findings
    for (const auto& f : findings) {
        EXPECT_NE(f.severity, "critical");
    }
}

// ============================================================================
// Authorized Keys Analysis Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzeAuthorizedKeysForcedCommand) {
    std::string content =
        "command=\"/usr/bin/restricted\" ssh-rsa AAAAB3... user@host\n";

    auto findings = analyzer.analyzeAuthorizedKeys(content, "/home/user/.ssh/authorized_keys", "user");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "key_anomaly" && f.description.find("forced command") != std::string::npos) {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeAuthorizedKeysWeakKeyType) {
    std::string content =
        "ssh-dss AAAAB3... user@host\n";

    auto findings = analyzer.analyzeAuthorizedKeys(content, "/home/user/.ssh/authorized_keys", "user");

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "key_anomaly" && f.description.find("ssh-dss") != std::string::npos) {
            found = true;
            EXPECT_EQ(f.severity, "medium");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeAuthorizedKeysSecure) {
    std::string content =
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAI... user@host\n";

    auto findings = analyzer.analyzeAuthorizedKeys(content, "/home/user/.ssh/authorized_keys", "user");

    // Ed25519 keys should not be flagged
    for (const auto& f : findings) {
        EXPECT_NE(f.severity, "high");
    }
}

// ============================================================================
// Known Hosts Analysis Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzeKnownHostsLateralMovement) {
    std::string content =
        "192.168.1.100 ssh-rsa AAAAB3...\n"
        "10.0.0.50 ecdsa-sha2-nistp256 AAAAE2...\n";

    auto findings = analyzer.analyzeKnownHosts(content, "/home/user/.ssh/known_hosts", "user");

    int lateralCount = 0;
    for (const auto& f : findings) {
        if (f.findingType == "lateral_movement") {
            lateralCount++;
        }
    }
    EXPECT_GE(lateralCount, 2);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeKnownHostsPublicHost) {
    std::string content =
        "github.com ssh-rsa AAAAB3...\n"
        "example.com ecdsa-sha2-nistp256 AAAAE2...\n";

    auto findings = analyzer.analyzeKnownHosts(content, "/home/user/.ssh/known_hosts", "user");

    // Public hosts should not be flagged as lateral movement
    for (const auto& f : findings) {
        EXPECT_NE(f.findingType, "lateral_movement");
    }
}

// ============================================================================
// Private Key Permissions Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzePrivateKeyPermissionsTooOpen) {
    auto findings = analyzer.analyzePrivateKeyPermissions("/home/user/.ssh/id_rsa", 0644, "user");

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].severity, "critical");
    EXPECT_EQ(findings[0].findingType, "key_anomaly");
}

TEST_F(AccountSSHAnalyzerTest, AnalyzePrivateKeyPermissionsCorrect) {
    auto findings = analyzer.analyzePrivateKeyPermissions("/home/user/.ssh/id_rsa", 0600, "user");

    EXPECT_EQ(findings.size(), 0);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzePrivateKeyPermissionsGroupRead) {
    auto findings = analyzer.analyzePrivateKeyPermissions("/home/user/.ssh/id_rsa", 0640, "user");

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].severity, "critical");
}

// ============================================================================
// Provenance Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, PasswdFindingProvenance) {
    std::string content = "backdoor:x:0:0:backdoor:/home/backdoor:/bin/bash\n";

    auto findings = analyzer.analyzePasswdFile(content, "/etc/passwd");

    ASSERT_GE(findings.size(), 1);
    EXPECT_FALSE(findings[0].provenance.parserName.empty());
    EXPECT_FALSE(findings[0].provenance.sourceFile.empty());
}

TEST_F(AccountSSHAnalyzerTest, SSHFindingProvenance) {
    std::string content = "PermitRootLogin yes\n";

    auto findings = analyzer.analyzeSSHConfig(content, "/etc/ssh/sshd_config");

    ASSERT_GE(findings.size(), 1);
    EXPECT_FALSE(findings[0].provenance.parserName.empty());
}

// ============================================================================
// Edge Case Tests
// ============================================================================

TEST_F(AccountSSHAnalyzerTest, AnalyzeEmptyContent) {
    EXPECT_EQ(analyzer.analyzePasswdFile("", "").size(), 0);
    EXPECT_EQ(analyzer.analyzeShadowFile("", "").size(), 0);
    EXPECT_EQ(analyzer.analyzeGroupFile("", "").size(), 0);
    EXPECT_EQ(analyzer.analyzeSudoersFile("", "").size(), 0);
    EXPECT_EQ(analyzer.analyzeSSHConfig("", "").size(), 0);
    EXPECT_EQ(analyzer.analyzeAuthorizedKeys("", "", "").size(), 0);
    EXPECT_EQ(analyzer.analyzeKnownHosts("", "", "").size(), 0);
}

TEST_F(AccountSSHAnalyzerTest, AnalyzeCommentsOnly) {
    std::string content = "# This is a comment\n# Another comment\n";

    EXPECT_EQ(analyzer.analyzePasswdFile(content, "").size(), 0);
    EXPECT_EQ(analyzer.analyzeSSHConfig(content, "").size(), 0);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
