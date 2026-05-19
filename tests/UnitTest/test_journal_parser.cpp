// test_journal_parser.cpp
// Unit tests for JournalParser

#ifdef linux
#undef linux
#endif

#include <gtest/gtest.h>
#include <fstream>
#include <filesystem>
#include "Parsers/JournalParser.h"

using namespace forensics::linux;
namespace fs = std::filesystem;

class JournalParserTest : public ::testing::Test {
protected:
    std::string testDir;

    void SetUp() override {
        testDir = fs::temp_directory_path() / "journal_parser_test";
        fs::create_directories(testDir);
    }

    void TearDown() override {
        fs::remove_all(testDir);
    }

    void writeFile(const std::string& name, const std::string& content) {
        std::ofstream out(testDir + "/" + name);
        out << content;
    }

    void writeBinaryFile(const std::string& name, const char* data, size_t size) {
        std::ofstream out(testDir + "/" + name, std::ios::binary);
        out.write(data, size);
    }
};

// ============================================================================
// Journal Export Format Parsing
// ============================================================================

TEST_F(JournalParserTest, ParseSingleExportEntry) {
    std::string content =
        "__CURSOR=s=abc123;i=1;b=bootid0123456789abcdef;t=1234567890;x=deadbeef\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "__MONOTONIC_TIMESTAMP=1000000\n"
        "_BOOT_ID=bootid0123456789abcdef\n"
        "_PID=1234\n"
        "_UID=0\n"
        "_GID=0\n"
        "_COMM=sshd\n"
        "_EXE=/usr/sbin/sshd\n"
        "_TRANSPORT=syslog\n"
        "SYSLOG_IDENTIFIER=sshd\n"
        "PRIORITY=6\n"
        "MESSAGE=Accepted publickey for user from 192.168.1.1\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);

    const auto& e = entries[0];
    EXPECT_EQ(e.cursor, "s=abc123;i=1;b=bootid0123456789abcdef;t=1234567890;x=deadbeef");
    EXPECT_EQ(e.realtimeTimestamp, 1700000000000000LL);
    EXPECT_EQ(e.monotonicTimestamp, 1000000LL);
    EXPECT_EQ(e.bootId, "bootid0123456789abcdef");
    EXPECT_EQ(e.pid, 1234);
    EXPECT_EQ(e.uid, 0);
    EXPECT_EQ(e.gid, 0);
    EXPECT_EQ(e.comm, "sshd");
    EXPECT_EQ(e.exe, "/usr/sbin/sshd");
    EXPECT_EQ(e.transport, "syslog");
    EXPECT_EQ(e.syslogIdentifier, "sshd");
    EXPECT_EQ(e.priority, "6");
    EXPECT_EQ(e.message, "Accepted publickey for user from 192.168.1.1");
}

TEST_F(JournalParserTest, ParseMultipleExportEntries) {
    std::string content =
        "__CURSOR=s=entry1\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "MESSAGE=First message\n"
        "\n"
        "__CURSOR=s=entry2\n"
        "__REALTIME_TIMESTAMP=1700000001000000\n"
        "MESSAGE=Second message\n"
        "\n"
        "__CURSOR=s=entry3\n"
        "__REALTIME_TIMESTAMP=1700000002000000\n"
        "MESSAGE=Third message\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 3);

    EXPECT_EQ(entries[0].message, "First message");
    EXPECT_EQ(entries[1].message, "Second message");
    EXPECT_EQ(entries[2].message, "Third message");

    EXPECT_EQ(entries[0].cursor, "s=entry1");
    EXPECT_EQ(entries[1].cursor, "s=entry2");
    EXPECT_EQ(entries[2].cursor, "s=entry3");
}

TEST_F(JournalParserTest, ParseExportWithSystemdUnit) {
    std::string content =
        "__CURSOR=s=test\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "_SYSTEMD_UNIT=sshd.service\n"
        "_USER_UNIT=bash.service\n"
        "MESSAGE=Test message\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].systemdUnit, "sshd.service");
    EXPECT_EQ(entries[0].userUnit, "bash.service");
}

TEST_F(JournalParserTest, ParseExportWithExtraFields) {
    std::string content =
        "__CURSOR=s=test\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "MESSAGE=Test\n"
        "CUSTOM_FIELD=custom_value\n"
        "_CUSTOM_BINARY=value\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].extraFields["CUSTOM_FIELD"], "custom_value");
    EXPECT_EQ(entries[0].extraFields["_CUSTOM_BINARY"], "value");
}

TEST_F(JournalParserTest, ParseExportWithMessageId) {
    std::string content =
        "__CURSOR=s=test\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "MESSAGE_ID=ae8f7b81e6a64c19924b4d75da089898\n"
        "MESSAGE=Test\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].messageId, "ae8f7b81e6a64c19924b4d75da089898");
}

TEST_F(JournalParserTest, ParseExportWithCmdline) {
    std::string content =
        "__CURSOR=s=test\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "_CMDLINE=/usr/sbin/sshd -D\n"
        "MESSAGE=Test\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].cmdline, "/usr/sbin/sshd -D");
}

TEST_F(JournalParserTest, ParseEmptyExport) {
    auto entries = JournalParser::parseJournalExport("");
    EXPECT_TRUE(entries.empty());
}

TEST_F(JournalParserTest, ParseExportWithCarriageReturn) {
    std::string content =
        "__CURSOR=s=test\r\n"
        "__REALTIME_TIMESTAMP=1700000000000000\r\n"
        "MESSAGE=Windows line endings\r\n"
        "\r\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message, "Windows line endings");
}

// ============================================================================
// Journal Export File Operations
// ============================================================================

TEST_F(JournalParserTest, ParseJournalExportFile) {
    std::string content =
        "__CURSOR=s=filetest\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "MESSAGE=File test\n"
        "\n";

    writeFile("test.export", content);

    auto entries = JournalParser::parseJournalExportFile(testDir + "/test.export");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message, "File test");
    EXPECT_EQ(entries[0].provenance.parserName, "JournalParser");
    EXPECT_EQ(entries[0].provenance.parserVersion, "1.0.0");
}

TEST_F(JournalParserTest, IsJournalExportFile) {
    std::string content =
        "__CURSOR=s=test\n"
        "MESSAGE=Test\n"
        "\n";

    writeFile("valid.export", content);
    writeFile("invalid.txt", "This is not a journal export\n");

    EXPECT_TRUE(JournalParser::isJournalExportFile(testDir + "/valid.export"));
    EXPECT_FALSE(JournalParser::isJournalExportFile(testDir + "/invalid.txt"));
    EXPECT_FALSE(JournalParser::isJournalExportFile(testDir + "/nonexistent.export"));
}

// ============================================================================
// Binary Journal File Detection
// ============================================================================

TEST_F(JournalParserTest, IsJournalFileWithValidMagic) {
    // Create a minimal file with valid magic
    char data[256] = {0};
    memcpy(data, "LPKSHHRH", 8);

    writeBinaryFile("test.journal", data, sizeof(data));
    EXPECT_TRUE(JournalParser::isJournalFile(testDir + "/test.journal"));
}

TEST_F(JournalParserTest, IsJournalFileWithInvalidMagic) {
    char data[256] = {0};
    memcpy(data, "INVALID!", 8);

    writeBinaryFile("bad.journal", data, sizeof(data));
    EXPECT_FALSE(JournalParser::isJournalFile(testDir + "/bad.journal"));
}

TEST_F(JournalParserTest, IsJournalFileNonexistent) {
    EXPECT_FALSE(JournalParser::isJournalFile(testDir + "/nonexistent.journal"));
}

// ============================================================================
// Boot Session Grouping
// ============================================================================

TEST_F(JournalParserTest, GroupByBootIdSingleBoot) {
    std::vector<JournalEntry> entries;
    JournalEntry e1;
    e1.bootId = "boot-aaaa";
    e1.realtimeTimestamp = 1700000000000000LL;
    entries.push_back(e1);

    JournalEntry e2;
    e2.bootId = "boot-aaaa";
    e2.realtimeTimestamp = 1700000100000000LL;
    entries.push_back(e2);

    auto sessions = JournalParser::groupByBootId(entries);
    ASSERT_EQ(sessions.size(), 1);
    EXPECT_EQ(sessions[0].bootId, "boot-aaaa");
    EXPECT_EQ(sessions[0].entryCount, 2);
    EXPECT_EQ(sessions[0].startTime, 1700000000000000LL);
    EXPECT_EQ(sessions[0].endTime, 1700000100000000LL);
}

TEST_F(JournalParserTest, GroupByBootIdMultipleBoots) {
    std::vector<JournalEntry> entries;

    JournalEntry e1;
    e1.bootId = "boot-aaaa";
    e1.realtimeTimestamp = 1700000000000000LL;
    entries.push_back(e1);

    JournalEntry e2;
    e2.bootId = "boot-bbbb";
    e2.realtimeTimestamp = 1700100000000000LL;
    entries.push_back(e2);

    JournalEntry e3;
    e3.bootId = "boot-aaaa";
    e3.realtimeTimestamp = 1700000050000000LL;
    entries.push_back(e3);

    auto sessions = JournalParser::groupByBootId(entries);
    ASSERT_EQ(sessions.size(), 2);

    // Sessions are sorted by start time
    EXPECT_EQ(sessions[0].bootId, "boot-aaaa");
    EXPECT_EQ(sessions[0].entryCount, 2);
    EXPECT_EQ(sessions[1].bootId, "boot-bbbb");
    EXPECT_EQ(sessions[1].entryCount, 1);
}

TEST_F(JournalParserTest, GroupByBootIdEmptyBootId) {
    std::vector<JournalEntry> entries;
    JournalEntry e1;
    e1.bootId = "";
    e1.realtimeTimestamp = 1700000000000000LL;
    entries.push_back(e1);

    auto sessions = JournalParser::groupByBootId(entries);
    ASSERT_EQ(sessions.size(), 1);
    EXPECT_EQ(sessions[0].bootId, "unknown");
}

TEST_F(JournalParserTest, GroupByBootIdEmpty) {
    std::vector<JournalEntry> entries;
    auto sessions = JournalParser::groupByBootId(entries);
    EXPECT_TRUE(sessions.empty());
}

// ============================================================================
// Anomaly Detection
// ============================================================================

TEST_F(JournalParserTest, DetectTimeJumpBackwards) {
    std::vector<JournalEntry> entries;

    JournalEntry e1;
    e1.realtimeTimestamp = 1700000100000000LL;
    e1.message = "First";
    entries.push_back(e1);

    JournalEntry e2;
    e2.realtimeTimestamp = 1700000000000000LL; // 100 seconds earlier
    e2.message = "Backwards";
    entries.push_back(e2);

    auto anomalies = JournalParser::detectJournalAnomalies(entries);
    ASSERT_GE(anomalies.size(), 1);
    EXPECT_EQ(anomalies[0].type, JournalAnomalyType::TIME_JUMP_DETECTED);
    EXPECT_NE(anomalies[0].description.find("backwards"), std::string::npos);
}

TEST_F(JournalParserTest, DetectLargeGap) {
    std::vector<JournalEntry> entries;

    JournalEntry e1;
    e1.realtimeTimestamp = 1700000000000000LL;
    e1.message = "Before gap";
    entries.push_back(e1);

    JournalEntry e2;
    e2.realtimeTimestamp = 1700000000000000LL + 7200000000LL; // 2 hours later
    e2.message = "After gap";
    entries.push_back(e2);

    auto anomalies = JournalParser::detectJournalAnomalies(entries);
    ASSERT_GE(anomalies.size(), 1);

    bool foundGap = false;
    for (const auto& a : anomalies) {
        if (a.type == JournalAnomalyType::GAP_DETECTED) {
            foundGap = true;
            break;
        }
    }
    EXPECT_TRUE(foundGap);
}

TEST_F(JournalParserTest, DetectMissingBoot) {
    std::vector<JournalEntry> entries;

    JournalEntry e1;
    e1.bootId = "boot-old";
    e1.realtimeTimestamp = 1700000000000000LL; // Nov 2023
    e1.message = "Old boot";
    entries.push_back(e1);

    JournalEntry e2;
    e2.bootId = "boot-new";
    e2.realtimeTimestamp = 1700000000000000LL + 172800000000000LL; // 2 days later
    e2.message = "New boot";
    entries.push_back(e2);

    auto anomalies = JournalParser::detectJournalAnomalies(entries);
    ASSERT_GE(anomalies.size(), 1);

    bool foundMissingBoot = false;
    for (const auto& a : anomalies) {
        if (a.type == JournalAnomalyType::MISSING_BOOT) {
            foundMissingBoot = true;
            break;
        }
    }
    EXPECT_TRUE(foundMissingBoot);
}

TEST_F(JournalParserTest, DetectCorruptedEntry) {
    std::vector<JournalEntry> entries;

    JournalEntry e1;
    e1.realtimeTimestamp = 1700000000000000LL;
    e1.message = "Normal entry";
    entries.push_back(e1);

    JournalEntry e2;
    e2.realtimeTimestamp = 1700000001000000LL;
    e2.message = ""; // Empty message with timestamp
    entries.push_back(e2);

    auto anomalies = JournalParser::detectJournalAnomalies(entries);
    ASSERT_GE(anomalies.size(), 1);

    bool foundCorrupted = false;
    for (const auto& a : anomalies) {
        if (a.type == JournalAnomalyType::CORRUPTED_ENTRY) {
            foundCorrupted = true;
            break;
        }
    }
    EXPECT_TRUE(foundCorrupted);
}

TEST_F(JournalParserTest, NoAnomaliesInNormalData) {
    std::vector<JournalEntry> entries;

    for (int i = 0; i < 10; i++) {
        JournalEntry e;
        e.realtimeTimestamp = 1700000000000000LL + (i * 1000000LL); // 1 second apart
        e.message = "Entry " + std::to_string(i);
        e.bootId = "boot-test";
        entries.push_back(e);
    }

    auto anomalies = JournalParser::detectJournalAnomalies(entries);
    EXPECT_TRUE(anomalies.empty());
}

TEST_F(JournalParserTest, DetectAnomaliesEmpty) {
    std::vector<JournalEntry> entries;
    auto anomalies = JournalParser::detectJournalAnomalies(entries);
    EXPECT_TRUE(anomalies.empty());
}

// ============================================================================
// Binary Format Helpers
// ============================================================================

TEST_F(JournalParserTest, ParseJournalExportTimestampParsing) {
    std::string content =
        "__CURSOR=s=test\n"
        "__REALTIME_TIMESTAMP=0\n"
        "__MONOTONIC_TIMESTAMP=0\n"
        "MESSAGE=Zero timestamps\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].realtimeTimestamp, 0);
    EXPECT_EQ(entries[0].monotonicTimestamp, 0);
}

TEST_F(JournalParserTest, ParseExportWithLargeTimestamp) {
    std::string content =
        "__CURSOR=s=test\n"
        "__REALTIME_TIMESTAMP=1700000000999999\n"
        "MESSAGE=Microsecond precision\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].realtimeTimestamp, 1700000000999999LL);
}

TEST_F(JournalParserTest, ParseExportInvalidNumericFields) {
    std::string content =
        "__CURSOR=s=test\n"
        "__REALTIME_TIMESTAMP=not_a_number\n"
        "__MONOTONIC_TIMESTAMP=also_not_a_number\n"
        "_PID=bad\n"
        "_UID=bad\n"
        "_GID=bad\n"
        "MESSAGE=Invalid numeric fields\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    // Should not crash, values remain at defaults
    EXPECT_EQ(entries[0].realtimeTimestamp, 0);
    EXPECT_EQ(entries[0].monotonicTimestamp, 0);
    EXPECT_EQ(entries[0].pid, -1);
    EXPECT_EQ(entries[0].uid, -1);
    EXPECT_EQ(entries[0].gid, -1);
    EXPECT_EQ(entries[0].message, "Invalid numeric fields");
}

// ============================================================================
// Edge Cases
// ============================================================================

TEST_F(JournalParserTest, ParseExportTruncatedEntry) {
    // Entry without trailing newline (last entry in file)
    std::string content =
        "__CURSOR=s=truncated\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "MESSAGE=No trailing newline";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message, "No trailing newline");
}

TEST_F(JournalParserTest, ParseExportFieldsWithoutEntry) {
    // Fields before any __CURSOR line should be ignored
    std::string content =
        "MESSAGE=Orphan message\n"
        "__CURSOR=s=real\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "MESSAGE=Real message\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message, "Real message");
}

TEST_F(JournalParserTest, ParseExportMessageWithEquals) {
    std::string content =
        "__CURSOR=s=test\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "MESSAGE=key=value in message\n"
        "\n";

    auto entries = JournalParser::parseJournalExport(content);
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].message, "key=value in message");
}

// ============================================================================
// Provenance
// ============================================================================

TEST_F(JournalParserTest, ProvenanceSetOnFileParse) {
    std::string content =
        "__CURSOR=s=provtest\n"
        "__REALTIME_TIMESTAMP=1700000000000000\n"
        "MESSAGE=Provenance test\n"
        "\n";

    writeFile("provenance.export", content);

    auto entries = JournalParser::parseJournalExportFile(testDir + "/provenance.export");
    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].provenance.parserName, "JournalParser");
    EXPECT_EQ(entries[0].provenance.parserVersion, "1.0.0");
    EXPECT_EQ(entries[0].provenance.sourceFile, testDir + "/provenance.export");
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
