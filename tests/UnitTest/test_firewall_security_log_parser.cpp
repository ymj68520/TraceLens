// test_firewall_security_log_parser.cpp
// Unit tests for FirewallSecurityLogParser - Phase 11

#include <gtest/gtest.h>
#include "Parsers/FirewallSecurity/FirewallSecurityLogParser.h"

using namespace forensics::linux;

class FirewallSecurityLogParserTest : public ::testing::Test {
protected:
    FirewallSecurityLogParser parser;
};

// ============================================================================
// UFW Log Parsing Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, ParseUFWBlock) {
    std::string content =
        "Jan 15 10:30:00 hostname kernel: [UFW BLOCK] IN=eth0 OUT= MAC=00:11:22:33:44:55 SRC=192.168.1.100 DST=10.0.0.1 LEN=60 TTL=64 PROTO=TCP SPT=12345 DPT=22\n";

    auto entries = parser.parseUFWLog(content, "/var/log/ufw.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].toolType, SecurityToolType::UFW);
    EXPECT_EQ(entries[0].action, "BLOCK");
    EXPECT_EQ(entries[0].srcAddr, "192.168.1.100");
    EXPECT_EQ(entries[0].dstAddr, "10.0.0.1");
    EXPECT_EQ(entries[0].protocol, "TCP");
    EXPECT_EQ(entries[0].dstPort, 22);
}

TEST_F(FirewallSecurityLogParserTest, ParseUFWAllow) {
    std::string content =
        "Jan 15 10:30:00 hostname kernel: [UFW ALLOW] IN=eth0 OUT= MAC=00:11:22:33:44:55 SRC=192.168.1.100 DST=10.0.0.1 LEN=60 TTL=64 PROTO=TCP SPT=12345 DPT=443\n";

    auto entries = parser.parseUFWLog(content, "/var/log/ufw.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].action, "ALLOW");
}

TEST_F(FirewallSecurityLogParserTest, ParseUFWInterface) {
    std::string content =
        "Jan 15 10:30:00 hostname kernel: [UFW BLOCK] IN=eth0 OUT= SRC=192.168.1.100 DST=10.0.0.1 PROTO=TCP DPT=22\n";

    auto entries = parser.parseUFWLog(content, "/var/log/ufw.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].interface, "eth0");
}

// ============================================================================
// Firewalld Log Parsing Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, ParseFirewalldReject) {
    std::string content =
        "Jan 15 10:30:00 hostname firewalld: REJECT zone=public interface=eth0 source=192.168.1.100 destination=10.0.0.1 port=22 protocol=tcp\n";

    auto entries = parser.parseFirewalldLog(content, "/var/log/firewalld.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].toolType, SecurityToolType::Firewalld);
    EXPECT_EQ(entries[0].action, "REJECT");
    EXPECT_EQ(entries[0].interface, "eth0");
}

TEST_F(FirewallSecurityLogParserTest, ParseFirewalldAccept) {
    std::string content =
        "Jan 15 10:30:00 hostname firewalld: ACCEPT zone=public interface=eth0 source=192.168.1.100 port=443 protocol=tcp\n";

    auto entries = parser.parseFirewalldLog(content, "/var/log/firewalld.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].action, "ALLOW");
}

// ============================================================================
// Fail2Ban Log Parsing Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, ParseFail2BanBan) {
    std::string content =
        "2024-01-15 10:30:00,123 fail2ban.actions [12345]: NOTICE [sshd] Ban 192.168.1.100\n";

    auto entries = parser.parseFail2BanLog(content, "/var/log/fail2ban.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].toolType, SecurityToolType::Fail2Ban);
    EXPECT_EQ(entries[0].result, "banned");
    EXPECT_EQ(entries[0].severity, "high");
}

TEST_F(FirewallSecurityLogParserTest, ParseFail2BanUnban) {
    std::string content =
        "2024-01-15 10:30:00,123 fail2ban.actions [12345]: NOTICE [sshd] Unban 192.168.1.100\n";

    auto entries = parser.parseFail2BanLog(content, "/var/log/fail2ban.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].result, "unbanned");
    EXPECT_EQ(entries[0].severity, "info");
}

TEST_F(FirewallSecurityLogParserTest, ParseFail2BanFound) {
    std::string content =
        "2024-01-15 10:30:00,123 fail2ban.filter [12345]: INFO [sshd] Found 192.168.1.100\n";

    auto entries = parser.parseFail2BanLog(content, "/var/log/fail2ban.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].result, "found");
    EXPECT_EQ(entries[0].severity, "medium");
}

// ============================================================================
// ClamAV Log Parsing Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, ParseClamAVClean) {
    std::string content =
        "/home/user/document.pdf: OK\n"
        "/home/user/image.jpg: OK\n";

    auto entries = parser.parseClamAVLog(content, "/var/log/clamav/clamav.log");

    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].toolType, SecurityToolType::ClamAV);
    EXPECT_EQ(entries[0].result, "clean");
    EXPECT_EQ(entries[0].severity, "info");
}

TEST_F(FirewallSecurityLogParserTest, ParseClamAVInfected) {
    std::string content =
        "/home/user/malware.exe: Win.Trojan.Generic FOUND\n";

    auto entries = parser.parseClamAVLog(content, "/var/log/clamav/clamav.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].result, "infected");
    EXPECT_EQ(entries[0].severity, "critical");
}

TEST_F(FirewallSecurityLogParserTest, ParseClamAVError) {
    std::string content =
        "/home/user/corrupted.zip: ERROR\n";

    auto entries = parser.parseClamAVLog(content, "/var/log/clamav/clamav.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].result, "error");
    EXPECT_EQ(entries[0].severity, "error");
}

TEST_F(FirewallSecurityLogParserTest, ParseFreshclamUpdate) {
    std::string content =
        "Mon Jan 15 10:30:00 2024 -> ClamAV update process started\n"
        "Mon Jan 15 10:30:01 2024 -> daily.cvd updated (version: 27123)\n";

    auto entries = parser.parseClamAVLog(content, "/var/log/freshclam.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].eventType, "update");
}

// ============================================================================
// RKHunter Log Parsing Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, ParseRKHunterOK) {
    std::string content =
        "[10:30:00] Checking 'file properties'... [ OK ]\n"
        "[10:30:01] Checking 'passwd file'... [ OK ]\n";

    auto entries = parser.parseRKHunterLog(content, "/var/log/rkhunter.log");

    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].toolType, SecurityToolType::RKHunter);
    EXPECT_EQ(entries[0].result, "ok");
    EXPECT_EQ(entries[0].severity, "info");
}

TEST_F(FirewallSecurityLogParserTest, ParseRKHunterWarning) {
    std::string content =
        "[10:30:00] Checking 'file properties'... [ Warning ]\n";

    auto entries = parser.parseRKHunterLog(content, "/var/log/rkhunter.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].result, "warning");
    EXPECT_EQ(entries[0].severity, "high");
}

TEST_F(FirewallSecurityLogParserTest, ParseRKHunterAlert) {
    std::string content =
        "[10:30:00] Warning: Possible rootkit detected\n";

    auto entries = parser.parseRKHunterLog(content, "/var/log/rkhunter.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].severity, "high");
}

// ============================================================================
// OSSEC Log Parsing Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, ParseOSSECAlert) {
    std::string content =
        "2024/01/15 10:30:00 ossec: Alert Level: 3; Rule: 1001 - Alert generated\n";

    auto entries = parser.parseOSSECLog(content, "/var/log/ossec/ossec.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].toolType, SecurityToolType::OSSEC);
    EXPECT_EQ(entries[0].eventType, "alert");
    EXPECT_EQ(entries[0].severity, "low");
}

TEST_F(FirewallSecurityLogParserTest, ParseOSSECCriticalAlert) {
    std::string content =
        "2024/01/15 10:30:00 ossec: Alert Level: 12; Rule: 5502 - Rootkit detected\n";

    auto entries = parser.parseOSSECLog(content, "/var/log/ossec/ossec.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].severity, "critical");
}

TEST_F(FirewallSecurityLogParserTest, ParseOSSECSyscheck) {
    std::string content =
        "2024/01/15 10:30:00 ossec-syscheck: Integrity checksum changed for '/etc/passwd'\n";

    auto entries = parser.parseOSSECLog(content, "/var/log/ossec/ossec.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].eventType, "integrity_check");
    EXPECT_EQ(entries[0].result, "modified");
}

// ============================================================================
// AIDE Log Parsing Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, ParseAIDEAdded) {
    std::string content =
        "AIDE found differences between database and filesystem\n"
        "Added: /home/user/newfile.txt\n";

    auto entries = parser.parseAIDELog(content, "/var/log/aide/aide.log");

    ASSERT_GE(entries.size(), 1);
    bool foundAdded = false;
    for (const auto& e : entries) {
        if (e.result == "added") {
            foundAdded = true;
            EXPECT_EQ(e.severity, "high");
        }
    }
    EXPECT_TRUE(foundAdded);
}

TEST_F(FirewallSecurityLogParserTest, ParseAIDERemoved) {
    std::string content =
        "Removed: /home/user/deleted.txt\n";

    auto entries = parser.parseAIDELog(content, "/var/log/aide/aide.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].result, "removed");
    EXPECT_EQ(entries[0].severity, "high");
}

TEST_F(FirewallSecurityLogParserTest, ParseAIDEChanged) {
    std::string content =
        "Changed: /etc/passwd\n";

    auto entries = parser.parseAIDELog(content, "/var/log/aide/aide.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].result, "modified");
    EXPECT_EQ(entries[0].severity, "high");
}

// ============================================================================
// Auto-detection Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, DetectUFWType) {
    EXPECT_EQ(parser.detectToolType("/var/log/ufw.log"), SecurityToolType::UFW);
}

TEST_F(FirewallSecurityLogParserTest, DetectFirewalldType) {
    EXPECT_EQ(parser.detectToolType("/var/log/firewalld.log"), SecurityToolType::Firewalld);
}

TEST_F(FirewallSecurityLogParserTest, DetectFail2BanType) {
    EXPECT_EQ(parser.detectToolType("/var/log/fail2ban.log"), SecurityToolType::Fail2Ban);
}

TEST_F(FirewallSecurityLogParserTest, DetectClamAVType) {
    EXPECT_EQ(parser.detectToolType("/var/log/clamav/clamav.log"), SecurityToolType::ClamAV);
    EXPECT_EQ(parser.detectToolType("/var/log/freshclam.log"), SecurityToolType::ClamAV);
}

TEST_F(FirewallSecurityLogParserTest, DetectRKHunterType) {
    EXPECT_EQ(parser.detectToolType("/var/log/rkhunter.log"), SecurityToolType::RKHunter);
}

TEST_F(FirewallSecurityLogParserTest, DetectOSSECType) {
    EXPECT_EQ(parser.detectToolType("/var/log/ossec/ossec.log"), SecurityToolType::OSSEC);
}

TEST_F(FirewallSecurityLogParserTest, DetectAIDEType) {
    EXPECT_EQ(parser.detectToolType("/var/log/aide/aide.log"), SecurityToolType::AIDE);
}

// ============================================================================
// Security Analysis Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, AnalyzePortScan) {
    // Generate blocks hitting many different ports from same IP
    std::string content;
    for (int port = 20; port < 35; port++) {
        content += "Jan 15 10:30:00 hostname kernel: [UFW BLOCK] IN=eth0 SRC=192.168.1.100 DST=10.0.0.1 PROTO=TCP DPT=" + std::to_string(port) + "\n";
    }

    auto entries = parser.parseUFWLog(content, "/var/log/ufw.log");
    auto findings = parser.analyzeFirewallSecurity(entries);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "port_scan") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(FirewallSecurityLogParserTest, AnalyzeHighBlockCount) {
    // Generate 60 blocks from same IP
    std::string content;
    for (int i = 0; i < 60; i++) {
        content += "Jan 15 10:30:00 hostname kernel: [UFW BLOCK] IN=eth0 SRC=192.168.1.100 DST=10.0.0.1 PROTO=TCP DPT=22\n";
    }

    auto entries = parser.parseUFWLog(content, "/var/log/ufw.log");
    auto findings = parser.analyzeFirewallSecurity(entries);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "high_block_count") {
            found = true;
            EXPECT_EQ(f.severity, "medium");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(FirewallSecurityLogParserTest, AnalyzeMalwareDetection) {
    std::string content =
        "/home/user/malware.exe: Win.Trojan.Generic FOUND\n";

    auto entries = parser.parseClamAVLog(content, "/var/log/clamav/clamav.log");
    auto findings = parser.analyzeSecurityProduct(entries);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "malware_detected") {
            found = true;
            EXPECT_EQ(f.severity, "critical");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(FirewallSecurityLogParserTest, AnalyzeIntegrityViolation) {
    std::string content =
        "Changed: /etc/passwd\n";

    auto entries = parser.parseAIDELog(content, "/var/log/aide/aide.log");
    auto findings = parser.analyzeSecurityProduct(entries);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "integrity_violation") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(FirewallSecurityLogParserTest, AnalyzeRootkitIndicator) {
    std::string content =
        "[10:30:00] Checking 'file properties'... [ Warning ]\n";

    auto entries = parser.parseRKHunterLog(content, "/var/log/rkhunter.log");
    auto findings = parser.analyzeSecurityProduct(entries);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "rootkit_indicator") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(FirewallSecurityLogParserTest, AnalyzeFail2BanBan) {
    std::string content =
        "2024-01-15 10:30:00,123 fail2ban.actions [12345]: NOTICE [sshd] Ban 192.168.1.100\n";

    auto entries = parser.parseFail2BanLog(content, "/var/log/fail2ban.log");
    auto findings = parser.analyzeSecurityProduct(entries);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "ban_action") {
            found = true;
            break;
        }
    }
    EXPECT_TRUE(found);
}

// ============================================================================
// Provenance Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, FirewallProvenanceSet) {
    std::string content =
        "Jan 15 10:30:00 hostname kernel: [UFW BLOCK] IN=eth0 SRC=192.168.1.100 DST=10.0.0.1 PROTO=TCP DPT=22\n";

    auto entries = parser.parseUFWLog(content, "/var/log/ufw.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].provenance.parserName, "FirewallSecurityLogParser");
    EXPECT_FALSE(entries[0].provenance.sourceFile.empty());
}

TEST_F(FirewallSecurityLogParserTest, SecurityProvenanceSet) {
    std::string content =
        "2024-01-15 10:30:00,123 fail2ban.actions [12345]: NOTICE [sshd] Ban 192.168.1.100\n";

    auto entries = parser.parseFail2BanLog(content, "/var/log/fail2ban.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].provenance.parserName, "FirewallSecurityLogParser");
}

// ============================================================================
// Edge Case Tests
// ============================================================================

TEST_F(FirewallSecurityLogParserTest, ParseEmptyContent) {
    EXPECT_EQ(parser.parseUFWLog("", "").size(), 0);
    EXPECT_EQ(parser.parseFirewalldLog("", "").size(), 0);
    EXPECT_EQ(parser.parseFail2BanLog("", "").size(), 0);
    EXPECT_EQ(parser.parseClamAVLog("", "").size(), 0);
    EXPECT_EQ(parser.parseRKHunterLog("", "").size(), 0);
    EXPECT_EQ(parser.parseOSSECLog("", "").size(), 0);
    EXPECT_EQ(parser.parseAIDELog("", "").size(), 0);
}

TEST_F(FirewallSecurityLogParserTest, ParseInvalidLines) {
    std::string content = "This is not a valid log line\n";
    EXPECT_EQ(parser.parseUFWLog(content, "").size(), 0);
    EXPECT_EQ(parser.parseFail2BanLog(content, "").size(), 0);
}

TEST_F(FirewallSecurityLogParserTest, AnalyzeEmptyFirewallEntries) {
    std::vector<FirewallLogEntry> entries;
    EXPECT_EQ(parser.analyzeFirewallSecurity(entries).size(), 0);
}

TEST_F(FirewallSecurityLogParserTest, AnalyzeEmptySecurityEntries) {
    std::vector<SecurityProductLogEntry> entries;
    EXPECT_EQ(parser.analyzeSecurityProduct(entries).size(), 0);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
