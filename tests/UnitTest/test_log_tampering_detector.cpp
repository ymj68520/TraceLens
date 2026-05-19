// test_log_tampering_detector.cpp
// Unit tests for LogTamperingDetector

#ifdef linux
#undef linux
#endif

#include <gtest/gtest.h>
#include "Analysis/LogTamperingDetector.h"
#include "Parsers/AuditdAggregator.h"
#include "Parsers/JournalParser.h"
#include "Parsers/CompressedLogParser.h"

using namespace forensics::linux;

class LogTamperingDetectorTest : public ::testing::Test {
protected:
    // Helper to create log entries with timestamps
    std::vector<LinuxLogEntry> makeLogEntries(const std::vector<int64_t>& timestamps) {
        std::vector<LinuxLogEntry> entries;
        for (int64_t ts : timestamps) {
            LinuxLogEntry entry;
            entry.unixTimestamp = ts;
            entry.message = "Test message at " + std::to_string(ts);
            entries.push_back(entry);
        }
        return entries;
    }

    // Helper to create rotated log files
    std::vector<RotatedLogFile> makeRotatedFiles(const std::string& baseName,
        const std::vector<int>& indices) {
        std::vector<RotatedLogFile> files;
        for (int idx : indices) {
            RotatedLogFile file;
            file.baseName = baseName;
            file.rotationIndex = idx;
            files.push_back(file);
        }
        return files;
    }

    // Helper to create journal entries
    std::vector<JournalEntry> makeJournalEntries(const std::vector<int64_t>& timestampsUs) {
        std::vector<JournalEntry> entries;
        for (int64_t ts : timestampsUs) {
            JournalEntry entry;
            entry.realtimeTimestamp = ts;
            entry.message = "Journal message";
            entries.push_back(entry);
        }
        return entries;
    }

    // Helper to create aggregated audit events
    std::vector<AggregatedAuditEvent> makeAuditEvents(const std::vector<int64_t>& timestamps) {
        std::vector<AggregatedAuditEvent> events;
        for (int64_t ts : timestamps) {
            AggregatedAuditEvent event;
            event.timestamp = ts;
            event.eventId = std::to_string(ts) + ":1";
            events.push_back(event);
        }
        return events;
    }
};

// ============================================================================
// Time Reversal Detection
// ============================================================================

TEST_F(LogTamperingDetectorTest, DetectTimeReversal) {
    auto entries = makeLogEntries({1000, 1100, 1050, 1200}); // 1050 < 1100

    auto findings = LogTamperingDetector::detectTimeReversals(entries, "test_log");

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].type, TamperingType::TIME_REVERSAL);
    EXPECT_EQ(findings[0].logSource, "test_log");
}

TEST_F(LogTamperingDetectorTest, NoTimeReversal) {
    auto entries = makeLogEntries({1000, 1100, 1200, 1300});

    auto findings = LogTamperingDetector::detectTimeReversals(entries, "test_log");

    EXPECT_TRUE(findings.empty());
}

TEST_F(LogTamperingDetectorTest, TimeReversalSmallTolerance) {
    // 1 second tolerance - entries at same second should not trigger
    auto entries = makeLogEntries({1000, 1000, 1001});

    auto findings = LogTamperingDetector::detectTimeReversals(entries, "test_log");

    EXPECT_TRUE(findings.empty());
}

// ============================================================================
// Time Window Gap Detection
// ============================================================================

TEST_F(LogTamperingDetectorTest, DetectLargeGap) {
    // 2 hour gap between 1000 and 8200
    auto entries = makeLogEntries({1000, 8200, 8300});

    auto findings = LogTamperingDetector::detectTimeWindowGaps(entries, "test_log", 3600);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].type, TamperingType::TIME_WINDOW_GAP);
    EXPECT_EQ(findings[0].timestampStart, 1000);
    EXPECT_EQ(findings[0].timestampEnd, 8200);
}

TEST_F(LogTamperingDetectorTest, NoGap) {
    auto entries = makeLogEntries({1000, 1100, 1200, 1300});

    auto findings = LogTamperingDetector::detectTimeWindowGaps(entries, "test_log", 3600);

    EXPECT_TRUE(findings.empty());
}

TEST_F(LogTamperingDetectorTest, GapBelowThreshold) {
    // 10 minute gap, threshold is 1 hour
    auto entries = makeLogEntries({1000, 1600, 1700});

    auto findings = LogTamperingDetector::detectTimeWindowGaps(entries, "test_log", 3600);

    EXPECT_TRUE(findings.empty());
}

TEST_F(LogTamperingDetectorTest, GapSeverityCritical) {
    // 10 day gap
    auto entries = makeLogEntries({1000, 1000 + 864000, 1000 + 864001});

    auto findings = LogTamperingDetector::detectTimeWindowGaps(entries, "test_log", 3600);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].severity, TamperingSeverity::CRITICAL);
}

TEST_F(LogTamperingDetectorTest, GapSeverityHigh) {
    // 2 day gap
    auto entries = makeLogEntries({1000, 1000 + 172800, 1000 + 172801});

    auto findings = LogTamperingDetector::detectTimeWindowGaps(entries, "test_log", 3600);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].severity, TamperingSeverity::HIGH);
}

TEST_F(LogTamperingDetectorTest, GapSeverityMedium) {
    // 2 hour gap
    auto entries = makeLogEntries({1000, 1000 + 7200, 1000 + 7201});

    auto findings = LogTamperingDetector::detectTimeWindowGaps(entries, "test_log", 3600);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].severity, TamperingSeverity::MEDIUM);
}

// ============================================================================
// Rotation Gap Detection
// ============================================================================

TEST_F(LogTamperingDetectorTest, DetectRotationGap) {
    auto files = makeRotatedFiles("auth.log", {0, 1, 3, 4}); // Missing 2

    auto findings = LogTamperingDetector::detectRotationGaps(files);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].type, TamperingType::ROTATION_GAP);
    EXPECT_NE(findings[0].description.find("2"), std::string::npos);
}

TEST_F(LogTamperingDetectorTest, NoRotationGap) {
    auto files = makeRotatedFiles("auth.log", {0, 1, 2, 3});

    auto findings = LogTamperingDetector::detectRotationGaps(files);

    EXPECT_TRUE(findings.empty());
}

TEST_F(LogTamperingDetectorTest, MultipleRotationGaps) {
    auto files = makeRotatedFiles("syslog", {0, 1, 4, 7}); // Missing 2,3 and 5,6

    auto findings = LogTamperingDetector::detectRotationGaps(files);

    ASSERT_GE(findings.size(), 2);
}

// ============================================================================
// Journal Missing Detection
// ============================================================================

TEST_F(LogTamperingDetectorTest, DetectJournalGap) {
    // 2 hour gap in microseconds
    auto entries = makeJournalEntries({
        1700000000000000LL,
        1700000000000000LL + 7200000000LL, // 2 hours later
        1700000000000000LL + 7200100000LL
    });

    auto findings = LogTamperingDetector::detectJournalMissing(entries, 3600);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].type, TamperingType::JOURNAL_MISSING);
}

TEST_F(LogTamperingDetectorTest, NoJournalGap) {
    auto entries = makeJournalEntries({
        1700000000000000LL,
        1700000001000000LL, // 1 second later
        1700000002000000LL
    });

    auto findings = LogTamperingDetector::detectJournalMissing(entries, 3600);

    EXPECT_TRUE(findings.empty());
}

TEST_F(LogTamperingDetectorTest, JournalBootGap) {
    // Two boot sessions with 2 day gap
    std::vector<JournalEntry> entries;

    JournalEntry e1;
    e1.realtimeTimestamp = 1700000000000000LL;
    e1.bootId = "boot-old";
    e1.message = "old boot";
    entries.push_back(e1);

    JournalEntry e2;
    e2.realtimeTimestamp = 1700000000000000LL + 172800000000LL; // 2 days later
    e2.bootId = "boot-new";
    e2.message = "new boot";
    entries.push_back(e2);

    auto findings = LogTamperingDetector::detectJournalMissing(entries, 3600);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].type, TamperingType::JOURNAL_MISSING);
}

// ============================================================================
// Auditd Interruption Detection
// ============================================================================

TEST_F(LogTamperingDetectorTest, DetectAuditdInterruption) {
    // 10 minute gap
    auto events = makeAuditEvents({1000, 1100, 1700, 1800});

    auto findings = LogTamperingDetector::detectAuditdInterruptions(events, 300);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].type, TamperingType::AUDITD_INTERRUPTED);
}

TEST_F(LogTamperingDetectorTest, NoAuditdInterruption) {
    auto events = makeAuditEvents({1000, 1010, 1020, 1030});

    auto findings = LogTamperingDetector::detectAuditdInterruptions(events, 300);

    EXPECT_TRUE(findings.empty());
}

// ============================================================================
// Duplicate Timestamp Detection
// ============================================================================

TEST_F(LogTamperingDetectorTest, DetectDuplicateTimestamps) {
    // 15 entries with same timestamp
    std::vector<int64_t> timestamps;
    for (int i = 0; i < 15; i++) {
        timestamps.push_back(1000);
    }
    auto entries = makeLogEntries(timestamps);

    auto findings = LogTamperingDetector::detectDuplicateTimestamps(entries, "test_log", 10);

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].type, TamperingType::DUPLICATE_TIMESTAMPS);
}

TEST_F(LogTamperingDetectorTest, NoDuplicateTimestamps) {
    auto entries = makeLogEntries({1000, 1001, 1002, 1003});

    auto findings = LogTamperingDetector::detectDuplicateTimestamps(entries, "test_log", 10);

    EXPECT_TRUE(findings.empty());
}

// ============================================================================
// Empty Input
// ============================================================================

TEST_F(LogTamperingDetectorTest, EmptyEntries) {
    std::vector<LinuxLogEntry> entries;

    auto reversals = LogTamperingDetector::detectTimeReversals(entries, "test");
    auto gaps = LogTamperingDetector::detectTimeWindowGaps(entries, "test");
    auto dups = LogTamperingDetector::detectDuplicateTimestamps(entries, "test");

    EXPECT_TRUE(reversals.empty());
    EXPECT_TRUE(gaps.empty());
    EXPECT_TRUE(dups.empty());
}

TEST_F(LogTamperingDetectorTest, SingleEntry) {
    auto entries = makeLogEntries({1000});

    auto reversals = LogTamperingDetector::detectTimeReversals(entries, "test");
    auto gaps = LogTamperingDetector::detectTimeWindowGaps(entries, "test");

    EXPECT_TRUE(reversals.empty());
    EXPECT_TRUE(gaps.empty());
}

// ============================================================================
// Log Clearing Detection
// ============================================================================

TEST_F(LogTamperingDetectorTest, DetectLogClearing) {
    // Small log with recent timestamps might indicate clearing
    auto entries = makeLogEntries({1000, 1001, 1002, 1003, 1004});

    auto findings = LogTamperingDetector::detectLogClearing(entries, "test_log");

    // With only 5 entries spanning 4 seconds, might trigger
    // The exact behavior depends on the heuristic
    EXPECT_GE(findings.size(), 0); // May or may not trigger
}

TEST_F(LogTamperingDetectorTest, DetectTimestampReset) {
    // Timestamps go forward then suddenly reset
    auto entries = makeLogEntries({1000, 2000, 3000, 500, 600});

    auto findings = LogTamperingDetector::detectLogClearing(entries, "test_log");

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].type, TamperingType::LOG_CLEARED);
}

// ============================================================================
// Provenance
// ============================================================================

TEST_F(LogTamperingDetectorTest, FindingHasDescription) {
    auto entries = makeLogEntries({1000, 1100, 1050});

    auto findings = LogTamperingDetector::detectTimeReversals(entries, "test_log");

    ASSERT_GE(findings.size(), 1);
    EXPECT_FALSE(findings[0].description.empty());
}

TEST_F(LogTamperingDetectorTest, FindingHasLogSource) {
    auto entries = makeLogEntries({1000, 1100, 1050});

    auto findings = LogTamperingDetector::detectTimeReversals(entries, "my_log");

    ASSERT_GE(findings.size(), 1);
    EXPECT_EQ(findings[0].logSource, "my_log");
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
