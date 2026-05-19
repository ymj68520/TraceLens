// test_package_manager_log_parser.cpp
// Unit tests for PackageManagerLogParser - Phase 9

#include <gtest/gtest.h>
#include "Parsers/PackageManager/PackageManagerLogParser.h"

using namespace forensics::linux;

class PackageManagerLogParserTest : public ::testing::Test {
protected:
    PackageManagerLogParser parser;
};

// ============================================================================
// APT history.log Parsing Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, ParseAptHistoryLogBasic) {
    std::string content =
        "Start-Date: 2023-10-06  10:23:45\n"
        "Commandline: apt-get install nginx\n"
        "Install: nginx:amd64 (1.18.0-6ubuntu14.4, automatic)\n"
        "Requested-By: user (1000)\n"
        "End-Date: 2023-10-06  10:23:50\n";

    auto entries = parser.parseAptHistoryLog(content, "/var/log/apt/history.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[0].packageManager, "apt");
    EXPECT_EQ(entries[0].operation, PackageOperation::INSTALL);
    EXPECT_GT(entries[0].timestamp, 0);
}

TEST_F(PackageManagerLogParserTest, ParseAptHistoryLogMultiplePackages) {
    std::string content =
        "Start-Date: 2023-10-06  10:23:45\n"
        "Commandline: apt-get install vim git\n"
        "Install: vim:amd64 (2:8.2.3995-1ubuntu2.11)\n"
        "Install: git:amd64 (1:2.34.1-1ubuntu1.10)\n"
        "End-Date: 2023-10-06  10:23:50\n"
        "\n"
        "Start-Date: 2023-10-06  11:00:00\n"
        "Commandline: apt-get remove vim\n"
        "Remove: vim:amd64 (2:8.2.3995-1ubuntu2.11)\n"
        "End-Date: 2023-10-06  11:00:05\n";

    auto entries = parser.parseAptHistoryLog(content, "/var/log/apt/history.log");

    ASSERT_GE(entries.size(), 2);
    EXPECT_EQ(entries[0].packageName, "vim");
    EXPECT_EQ(entries[0].operation, PackageOperation::INSTALL);
}

TEST_F(PackageManagerLogParserTest, ParseAptHistoryLogRemove) {
    std::string content =
        "Start-Date: 2023-10-06  10:23:45\n"
        "Commandline: apt-get remove nmap\n"
        "Remove: nmap:amd64 (7.80+dfsg1-6)\n"
        "End-Date: 2023-10-06  10:23:50\n";

    auto entries = parser.parseAptHistoryLog(content, "/var/log/apt/history.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nmap");
    EXPECT_EQ(entries[0].operation, PackageOperation::REMOVE);
}

TEST_F(PackageManagerLogParserTest, ParseAptHistoryLogUpgrade) {
    std::string content =
        "Start-Date: 2023-10-06  10:23:45\n"
        "Commandline: apt-get upgrade\n"
        "Upgrade: openssl:amd64 (3.0.2-0ubuntu1, 3.0.2-0ubuntu1.10)\n"
        "End-Date: 2023-10-06  10:23:50\n";

    auto entries = parser.parseAptHistoryLog(content, "/var/log/apt/history.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "openssl");
    EXPECT_EQ(entries[0].operation, PackageOperation::UPGRADE);
}

TEST_F(PackageManagerLogParserTest, ParseAptHistoryLogPurge) {
    std::string content =
        "Start-Date: 2023-10-06  10:23:45\n"
        "Commandline: apt-get purge apache2\n"
        "Purge: apache2:amd64 (2.4.52-1ubuntu4.6)\n"
        "End-Date: 2023-10-06  10:23:50\n";

    auto entries = parser.parseAptHistoryLog(content, "/var/log/apt/history.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "apache2");
    EXPECT_EQ(entries[0].operation, PackageOperation::PURGE);
}

// ============================================================================
// APT term.log Parsing Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, ParseAptTermLogBasic) {
    std::string content =
        "Log started: 2023-10-06  10:23:45\n"
        "(Reading database ... 50000 files and directories currently installed.)\n"
        "Preparing to unpack .../nginx_1.18.0-6ubuntu14.4_amd64.deb ...\n"
        "Unpacking nginx (1.18.0-6ubuntu14.4) ...\n";

    auto entries = parser.parseAptTermLog(content, "/var/log/apt/term.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[0].operation, PackageOperation::INSTALL);
}

TEST_F(PackageManagerLogParserTest, ParseAptTermLogRemove) {
    std::string content =
        "Log started: 2023-10-06  10:23:45\n"
        "(Reading database ... 50000 files and directories currently installed.)\n"
        "Removing nginx (1.18.0-6ubuntu14.4) ...\n";

    auto entries = parser.parseAptTermLog(content, "/var/log/apt/term.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[0].operation, PackageOperation::REMOVE);
}

// ============================================================================
// dpkg.log Parsing Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, ParseDpkgLogBasic) {
    std::string content =
        "2023-10-06 10:23:45 install nginx:amd64 <none> 1.18.0-6ubuntu14.4\n"
        "2023-10-06 10:23:50 status installed nginx:amd64 1.18.0-6ubuntu14.4\n";

    auto entries = parser.parseDpkgLog(content, "/var/log/dpkg.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[0].architecture, "amd64");
    EXPECT_EQ(entries[0].packageManager, "dpkg");
    EXPECT_EQ(entries[0].operation, PackageOperation::INSTALL);
}

TEST_F(PackageManagerLogParserTest, ParseDpkgLogRemove) {
    std::string content = "2023-10-06 10:23:45 remove nginx:amd64 1.18.0-6ubuntu14.4\n";

    auto entries = parser.parseDpkgLog(content, "/var/log/dpkg.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].operation, PackageOperation::REMOVE);
}

TEST_F(PackageManagerLogParserTest, ParseDpkgLogConfigure) {
    std::string content = "2023-10-06 10:23:45 configure nginx:amd64 1.18.0-6ubuntu14.4\n";

    auto entries = parser.parseDpkgLog(content, "/var/log/dpkg.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].operation, PackageOperation::CONFIGURE);
}

TEST_F(PackageManagerLogParserTest, ParseDpkgLogTimestamp) {
    std::string content = "2023-10-06 10:23:45 install test:amd64 <none> 1.0\n";

    auto entries = parser.parseDpkgLog(content, "/var/log/dpkg.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_GT(entries[0].timestamp, 0);
}

// ============================================================================
// yum.log Parsing Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, ParseYumLogBasic) {
    std::string content = "Oct 06 10:23:45 Installed: nginx-1.20.1-10.el9.x86_64\n";

    auto entries = parser.parseYumLog(content, "/var/log/yum.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[0].packageVersion, "1.20.1-10.el9");
    EXPECT_EQ(entries[0].architecture, "x86_64");
    EXPECT_EQ(entries[0].packageManager, "yum");
    EXPECT_EQ(entries[0].operation, PackageOperation::INSTALL);
}

TEST_F(PackageManagerLogParserTest, ParseYumLogRemove) {
    std::string content = "Oct 06 10:23:45 Erased: nginx-1.20.1-10.el9.x86_64\n";

    auto entries = parser.parseYumLog(content, "/var/log/yum.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].operation, PackageOperation::REMOVE);
}

TEST_F(PackageManagerLogParserTest, ParseYumLogUpdated) {
    std::string content = "Oct 06 10:23:45 Updated: openssl-3.0.7-18.el9.x86_64\n";

    auto entries = parser.parseYumLog(content, "/var/log/yum.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].operation, PackageOperation::UPGRADE);
}

TEST_F(PackageManagerLogParserTest, ParseYumLogMultiple) {
    std::string content =
        "Oct 06 10:23:45 Installed: nginx-1.20.1-10.el9.x86_64\n"
        "Oct 06 10:24:00 Installed: vim-enhanced-8.2.2637-20.el9.x86_64\n";

    auto entries = parser.parseYumLog(content, "/var/log/yum.log");

    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[1].packageName, "vim-enhanced");
}

// ============================================================================
// dnf.log Parsing Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, ParseDnfLogBasic) {
    std::string content = "2023-10-06T10:23:45+0000 INSTALL nginx-1.20.1-10.el9.x86_64\n";

    auto entries = parser.parseDnfLog(content, "/var/log/dnf.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nginx-1.20.1-10.el9.x86_64");
    EXPECT_EQ(entries[0].packageManager, "dnf");
}

// ============================================================================
// zypper.log Parsing Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, ParseZypperLogBasic) {
    std::string content = "2023-10-06 10:23:45 <1> install_package-1.0-1.x86_64(package)\n";

    auto entries = parser.parseZypperLog(content, "/var/log/zypper.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "package");
    EXPECT_EQ(entries[0].packageManager, "zypper");
}

// ============================================================================
// pacman.log Parsing Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, ParsePacmanLogBasic) {
    std::string content = "[2023-10-06T10:23:45+0000] [ALPM] installed nginx (1.24.0-1)\n";

    auto entries = parser.parsePacmanLog(content, "/var/log/pacman.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[0].packageVersion, "1.24.0-1");
    EXPECT_EQ(entries[0].packageManager, "pacman");
    EXPECT_EQ(entries[0].operation, PackageOperation::INSTALL);
}

TEST_F(PackageManagerLogParserTest, ParsePacmanLogRemoved) {
    std::string content = "[2023-10-06T10:23:45+0000] [ALPM] removed nginx (1.24.0-1)\n";

    auto entries = parser.parsePacmanLog(content, "/var/log/pacman.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].operation, PackageOperation::REMOVE);
}

TEST_F(PackageManagerLogParserTest, ParsePacmanLogUpgraded) {
    std::string content = "[2023-10-06T10:23:45+0000] [ALPM] upgraded nginx (1.24.0-1 -> 1.24.0-2)\n";

    auto entries = parser.parsePacmanLog(content, "/var/log/pacman.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].operation, PackageOperation::UPGRADE);
}

TEST_F(PackageManagerLogParserTest, ParsePacmanLogMultiple) {
    std::string content =
        "[2023-10-06T10:23:45+0000] [ALPM] installed nginx (1.24.0-1)\n"
        "[2023-10-06T10:24:00+0000] [ALPM] installed vim (9.0.1-1)\n";

    auto entries = parser.parsePacmanLog(content, "/var/log/pacman.log");

    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[1].packageName, "vim");
}

// ============================================================================
// Auto-detection Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, DetectAptHistory) {
    EXPECT_EQ(parser.detectPackageManagerType("Start-Date:", ""), "apt-history");
}

TEST_F(PackageManagerLogParserTest, DetectAptTerm) {
    EXPECT_EQ(parser.detectPackageManagerType("Log started:", ""), "apt-term");
}

TEST_F(PackageManagerLogParserTest, DetectDpkg) {
    EXPECT_EQ(parser.detectPackageManagerType("status installed", ""), "dpkg");
}

TEST_F(PackageManagerLogParserTest, DetectYum) {
    EXPECT_EQ(parser.detectPackageManagerType("Installed: package", ""), "yum");
}

TEST_F(PackageManagerLogParserTest, DetectPacman) {
    EXPECT_EQ(parser.detectPackageManagerType("[ALPM] installed", ""), "pacman");
}

TEST_F(PackageManagerLogParserTest, DetectByFilePath) {
    EXPECT_EQ(parser.detectPackageManagerType("", "/var/log/apt/history.log"), "apt-history");
    EXPECT_EQ(parser.detectPackageManagerType("", "/var/log/dpkg.log"), "dpkg");
    EXPECT_EQ(parser.detectPackageManagerType("", "/var/log/yum.log"), "yum");
    EXPECT_EQ(parser.detectPackageManagerType("", "/var/log/pacman.log"), "pacman");
}

// ============================================================================
// Security Analysis Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, AnalyzeAttackToolInstall) {
    std::vector<PackageLogEntry> entries;
    PackageLogEntry entry;
    entry.packageName = "nmap";
    entry.packageVersion = "7.80+dfsg1-6";
    entry.operation = PackageOperation::INSTALL;
    entries.push_back(entry);

    auto findings = parser.analyzeSuspiciousPackages(entries);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].findingType, "network_scanner");
    EXPECT_EQ(findings[0].severity, "high");
}

TEST_F(PackageManagerLogParserTest, AnalyzeCriticalAttackTool) {
    std::vector<PackageLogEntry> entries;
    PackageLogEntry entry;
    entry.packageName = "metasploit-framework";
    entry.operation = PackageOperation::INSTALL;
    entries.push_back(entry);

    auto findings = parser.analyzeSuspiciousPackages(entries);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].severity, "critical");
}

TEST_F(PackageManagerLogParserTest, AnalyzeSecurityToolRemoval) {
    std::vector<PackageLogEntry> entries;
    PackageLogEntry entry;
    entry.packageName = "fail2ban";
    entry.operation = PackageOperation::REMOVE;
    entries.push_back(entry);

    auto findings = parser.analyzeSuspiciousPackages(entries);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].findingType, "security_removal");
    EXPECT_EQ(findings[0].severity, "critical");
}

TEST_F(PackageManagerLogParserTest, AnalyzeSecurityToolPurge) {
    std::vector<PackageLogEntry> entries;
    PackageLogEntry entry;
    entry.packageName = "selinux";
    entry.operation = PackageOperation::PURGE;
    entries.push_back(entry);

    auto findings = parser.analyzeSuspiciousPackages(entries);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].findingType, "security_removal");
}

TEST_F(PackageManagerLogParserTest, AnalyzeSafePackage) {
    std::vector<PackageLogEntry> entries;
    PackageLogEntry entry;
    entry.packageName = "vim";
    entry.operation = PackageOperation::INSTALL;
    entries.push_back(entry);

    auto findings = parser.analyzeSuspiciousPackages(entries);

    // vim is not an attack tool
    EXPECT_EQ(findings.size(), 0);
}

TEST_F(PackageManagerLogParserTest, AnalyzeMultiplePackages) {
    std::vector<PackageLogEntry> entries;

    PackageLogEntry entry1;
    entry1.packageName = "nmap";
    entry1.operation = PackageOperation::INSTALL;
    entries.push_back(entry1);

    PackageLogEntry entry2;
    entry2.packageName = "fail2ban";
    entry2.operation = PackageOperation::REMOVE;
    entries.push_back(entry2);

    PackageLogEntry entry3;
    entry3.packageName = "vim";
    entry3.operation = PackageOperation::INSTALL;
    entries.push_back(entry3);

    auto findings = parser.analyzeSuspiciousPackages(entries);

    // nmap install + fail2ban removal = 2 findings
    EXPECT_GE(findings.size(), 2);
}

// ============================================================================
// Provenance Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, AptHistoryProvenance) {
    std::string content =
        "Start-Date: 2023-10-06  10:23:45\n"
        "Commandline: apt-get install nginx\n"
        "Install: nginx:amd64 (1.18.0-6ubuntu14.4)\n"
        "End-Date: 2023-10-06  10:23:50\n";

    auto entries = parser.parseAptHistoryLog(content, "/var/log/apt/history.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_FALSE(entries[0].provenance.parserName.empty());
    EXPECT_FALSE(entries[0].provenance.sourceFile.empty());
}

TEST_F(PackageManagerLogParserTest, DpkgLogProvenance) {
    std::string content = "2023-10-06 10:23:45 install nginx:amd64 <none> 1.0\n";

    auto entries = parser.parseDpkgLog(content, "/var/log/dpkg.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_FALSE(entries[0].provenance.parserName.empty());
}

TEST_F(PackageManagerLogParserTest, SuspiciousFindingProvenance) {
    std::vector<PackageLogEntry> entries;
    PackageLogEntry entry;
    entry.packageName = "nmap";
    entry.operation = PackageOperation::INSTALL;
    entry.provenance.parserName = "PackageManagerLogParser";
    entries.push_back(entry);

    auto findings = parser.analyzeSuspiciousPackages(entries);

    ASSERT_GE(findings.size(), 1);
    EXPECT_FALSE(findings[0].provenance.parserName.empty());
}

// ============================================================================
// Edge Case Tests
// ============================================================================

TEST_F(PackageManagerLogParserTest, ParseEmptyContent) {
    EXPECT_EQ(parser.parseAptHistoryLog("", "").size(), 0);
    EXPECT_EQ(parser.parseDpkgLog("", "").size(), 0);
    EXPECT_EQ(parser.parseYumLog("", "").size(), 0);
    EXPECT_EQ(parser.parsePacmanLog("", "").size(), 0);
}

TEST_F(PackageManagerLogParserTest, ParseWhitespaceOnly) {
    EXPECT_EQ(parser.parseAptHistoryLog("   \n  \n  ", "").size(), 0);
    EXPECT_EQ(parser.parseDpkgLog("   \n  \n  ", "").size(), 0);
}

TEST_F(PackageManagerLogParserTest, ParseDpkgLogComments) {
    std::string content =
        "# This is a comment\n"
        "2023-10-06 10:23:45 install nginx:amd64 <none> 1.0\n";

    auto entries = parser.parseDpkgLog(content, "/var/log/dpkg.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].packageName, "nginx");
    EXPECT_EQ(entries[0].architecture, "amd64");
}

TEST_F(PackageManagerLogParserTest, AnalyzeEmptyEntries) {
    std::vector<PackageLogEntry> entries;
    auto findings = parser.analyzeSuspiciousPackages(entries);
    EXPECT_EQ(findings.size(), 0);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
