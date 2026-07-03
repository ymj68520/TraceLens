// test_timestamp_normalizer.cpp
// Unit tests for TimestampNormalizer

#ifdef linux
#undef linux
#endif

#include <gtest/gtest.h>
#include <ctime>
#include "Parsers/TimestampNormalizer.h"

using namespace forensics::linux;

class TimestampNormalizerTest : public ::testing::Test {
protected:
    // A known boot time: 2024-01-15 10:00:00 UTC
    static constexpr int64_t KNOWN_BOOT_TIME = 1705312800LL;
};

// ============================================================================
// Syslog Timestamp Normalization
// ============================================================================

TEST_F(TimestampNormalizerTest, SyslogBasicFormat) {
    // "Jan  5 14:30:00" with year 2024
    auto result = TimestampNormalizer::normalizeSyslog("Jan  5 14:30:00", 2024, "UTC");

    EXPECT_EQ(result.inferredYear, 2024);
    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_FALSE(result.originalTimestamp.empty());
    EXPECT_EQ(result.timestampConfidence, 90);
}

TEST_F(TimestampNormalizerTest, SyslogWithLeadingSpace) {
    // "Jan  5" (single digit day with space)
    auto result1 = TimestampNormalizer::normalizeSyslog("Jan  5 10:00:00", 2024, "UTC");

    // "Jan 15" (double digit day)
    auto result2 = TimestampNormalizer::normalizeSyslog("Jan 15 10:00:00", 2024, "UTC");

    EXPECT_NE(result1.normalizedUtcTimestamp, result2.normalizedUtcTimestamp);
    EXPECT_GT(result2.normalizedUtcTimestamp, result1.normalizedUtcTimestamp);
}

TEST_F(TimestampNormalizerTest, SyslogAllMonths) {
    const char* months[] = {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    };

    int64_t prevTimestamp = 0;
    for (int i = 0; i < 12; i++) {
        std::string ts = std::string(months[i]) + " 15 12:00:00";
        auto result = TimestampNormalizer::normalizeSyslog(ts, 2024, "UTC");

        EXPECT_GT(result.normalizedUtcTimestamp, 0);
        EXPECT_GT(result.normalizedUtcTimestamp, prevTimestamp);
        prevTimestamp = result.normalizedUtcTimestamp;
    }
}

TEST_F(TimestampNormalizerTest, SyslogYearInference) {
    // Without explicit year, confidence should be lower
    auto result = TimestampNormalizer::normalizeSyslog("Jan  5 14:30:00");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.inferredYear, 2026); // Current year
    EXPECT_EQ(result.timestampConfidence, 70);
}

TEST_F(TimestampNormalizerTest, SyslogTimezoneHandling) {
    // Same timestamp, different timezones should produce different UTC
    auto utc = TimestampNormalizer::normalizeSyslog("Jan  5 12:00:00", 2024, "UTC");
    auto est = TimestampNormalizer::normalizeSyslog("Jan  5 12:00:00", 2024, "EST");
    auto jst = TimestampNormalizer::normalizeSyslog("Jan  5 12:00:00", 2024, "JST");

    // EST is UTC-5, so EST 12:00 = UTC 17:00
    EXPECT_GT(est.normalizedUtcTimestamp, utc.normalizedUtcTimestamp);

    // JST is UTC+9, so JST 12:00 = UTC 03:00
    EXPECT_LT(jst.normalizedUtcTimestamp, utc.normalizedUtcTimestamp);
}

TEST_F(TimestampNormalizerTest, SyslogNumericTimezone) {
    auto result = TimestampNormalizer::normalizeSyslog("Jan  5 12:00:00", 2024, "+0800");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.timezoneSource, "file");
}

TEST_F(TimestampNormalizerTest, SyslogInvalidFormat) {
    auto result = TimestampNormalizer::normalizeSyslog("invalid timestamp");

    EXPECT_EQ(result.timestampConfidence, 0);
}

// ============================================================================
// dmesg Timestamp Normalization
// ============================================================================

TEST_F(TimestampNormalizerTest, DmesgBasicFormat) {
    auto result = TimestampNormalizer::normalizeDmesg("[12345.678901]", KNOWN_BOOT_TIME);

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.monotonicTimestamp, 12345678901LL);
    EXPECT_GT(result.normalizedUtcTimestamp, KNOWN_BOOT_TIME);
}

TEST_F(TimestampNormalizerTest, DmesgWithoutBrackets) {
    auto result = TimestampNormalizer::normalizeDmesg("12345.678901", KNOWN_BOOT_TIME);

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.monotonicTimestamp, 12345678901LL);
}

TEST_F(TimestampNormalizerTest, DmesgZeroTimestamp) {
    auto result = TimestampNormalizer::normalizeDmesg("[0.000000]", KNOWN_BOOT_TIME);

    EXPECT_EQ(result.normalizedUtcTimestamp, KNOWN_BOOT_TIME);
    EXPECT_EQ(result.monotonicTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, DmesgWithoutBootTime) {
    auto result = TimestampNormalizer::normalizeDmesg("[100.500000]");

    EXPECT_EQ(result.normalizedUtcTimestamp, 100); // Falls back to raw seconds
    EXPECT_EQ(result.timestampConfidence, 30);
}

TEST_F(TimestampNormalizerTest, DmesgInvalidFormat) {
    auto result = TimestampNormalizer::normalizeDmesg("[not_a_number]");

    EXPECT_EQ(result.timestampConfidence, 0);
}

// ============================================================================
// Auditd Timestamp Normalization
// ============================================================================

TEST_F(TimestampNormalizerTest, AuditdBasicFormat) {
    auto result = TimestampNormalizer::normalizeAuditd("1700000000.123:456");

    EXPECT_EQ(result.normalizedUtcTimestamp, 1700000000LL);
    EXPECT_EQ(result.timestampConfidence, 95);
}

TEST_F(TimestampNormalizerTest, AuditdDifferentSerials) {
    auto result1 = TimestampNormalizer::normalizeAuditd("1700000000.111:111");
    auto result2 = TimestampNormalizer::normalizeAuditd("1700000000.222:222");

    // Same epoch, different serials - same normalized timestamp
    EXPECT_EQ(result1.normalizedUtcTimestamp, result2.normalizedUtcTimestamp);
}

TEST_F(TimestampNormalizerTest, AuditdDifferentEpochs) {
    auto result1 = TimestampNormalizer::normalizeAuditd("1700000000.000:000");
    auto result2 = TimestampNormalizer::normalizeAuditd("1700000001.000:000");

    EXPECT_EQ(result2.normalizedUtcTimestamp - result1.normalizedUtcTimestamp, 1);
}

// ============================================================================
// Journal Timestamp Normalization
// ============================================================================

TEST_F(TimestampNormalizerTest, JournalRealtimeBasic) {
    // 1700000000 seconds in microseconds
    auto result = TimestampNormalizer::normalizeJournalRealtime(1700000000000000LL);

    EXPECT_EQ(result.normalizedUtcTimestamp, 1700000000LL);
    EXPECT_EQ(result.timestampConfidence, 100);
    EXPECT_EQ(result.timezoneSource, "utc");
}

TEST_F(TimestampNormalizerTest, JournalMonotonicWithBootTime) {
    // 100 seconds after boot
    auto result = TimestampNormalizer::normalizeJournalMonotonic(
        100000000LL, "boot-id-1234", KNOWN_BOOT_TIME);

    EXPECT_EQ(result.normalizedUtcTimestamp, KNOWN_BOOT_TIME + 100);
    EXPECT_EQ(result.monotonicTimestamp, 100000000LL);
    EXPECT_EQ(result.bootId, "boot-id-1234");
    EXPECT_EQ(result.timestampConfidence, 90);
}

TEST_F(TimestampNormalizerTest, JournalMonotonicWithoutBootTime) {
    auto result = TimestampNormalizer::normalizeJournalMonotonic(
        100000000LL, "boot-id-1234");

    EXPECT_EQ(result.timestampConfidence, 30);
}

// ============================================================================
// Unix Epoch Normalization (wtmp/btmp)
// ============================================================================

TEST_F(TimestampNormalizerTest, UnixEpochBasic) {
    auto result = TimestampNormalizer::normalizeUnixEpoch(1700000000LL);

    EXPECT_EQ(result.normalizedUtcTimestamp, 1700000000LL);
    EXPECT_EQ(result.timestampConfidence, 95);
    EXPECT_EQ(result.timezoneSource, "utc");
}

TEST_F(TimestampNormalizerTest, UnixEpochZero) {
    auto result = TimestampNormalizer::normalizeUnixEpoch(0);

    EXPECT_EQ(result.normalizedUtcTimestamp, 0);
}

// ============================================================================
// RFC3339 Normalization (container logs)
// ============================================================================

TEST_F(TimestampNormalizerTest, RFC3339WithZTimezone) {
    auto result = TimestampNormalizer::normalizeRFC3339("2024-01-15T10:30:00Z");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.timestampConfidence, 100);
    EXPECT_EQ(result.timezoneSource, "utc");
}

TEST_F(TimestampNormalizerTest, RFC3339WithPositiveOffset) {
    auto result = TimestampNormalizer::normalizeRFC3339("2024-01-15T10:30:00+08:00");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.timezoneSource, "file");
}

TEST_F(TimestampNormalizerTest, RFC3339WithNegativeOffset) {
    auto result = TimestampNormalizer::normalizeRFC3339("2024-01-15T10:30:00-05:00");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.timezoneSource, "file");
}

TEST_F(TimestampNormalizerTest, RFC3339WithNanoseconds) {
    auto result = TimestampNormalizer::normalizeRFC3339("2024-01-15T10:30:00.123456789Z");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.timestampConfidence, 100);
}

TEST_F(TimestampNormalizerTest, RFC3339SpaceInsteadOfT) {
    auto result = TimestampNormalizer::normalizeRFC3339("2024-01-15 10:30:00Z");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, RFC3339WithoutTimezone) {
    auto result = TimestampNormalizer::normalizeRFC3339("2024-01-15T10:30:00");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.timezoneSource, "inferred");
}

TEST_F(TimestampNormalizerTest, RFC3339InvalidFormat) {
    auto result = TimestampNormalizer::normalizeRFC3339("not a timestamp");

    EXPECT_EQ(result.timestampConfidence, 0);
}

// ============================================================================
// Apache Timestamp Normalization
// ============================================================================

TEST_F(TimestampNormalizerTest, ApacheAccessLogFormat) {
    auto result = TimestampNormalizer::normalizeApacheTimestamp(
        "15/Jan/2024:10:30:00 +0800");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
    EXPECT_EQ(result.timestampConfidence, 100);
    EXPECT_EQ(result.timezoneSource, "file");
}

TEST_F(TimestampNormalizerTest, ApacheAccessLogUTC) {
    auto result = TimestampNormalizer::normalizeApacheTimestamp(
        "15/Jan/2024:10:30:00 +0000");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, ApacheAccessLogInvalid) {
    auto result = TimestampNormalizer::normalizeApacheTimestamp("invalid");

    EXPECT_EQ(result.timestampConfidence, 0);
}

// ============================================================================
// Auto-detection
// ============================================================================

TEST_F(TimestampNormalizerTest, DetectSyslogFormat) {
    EXPECT_EQ(TimestampNormalizer::detectFormat("Jan  5 14:30:00"),
              TimestampFormat::SYSLOG);
}

TEST_F(TimestampNormalizerTest, DetectSyslogWithYearFormat) {
    EXPECT_EQ(TimestampNormalizer::detectFormat("2024 Jan  5 14:30:00"),
              TimestampFormat::SYSLOG_WITH_YEAR);
}

TEST_F(TimestampNormalizerTest, DetectDmesgFormat) {
    EXPECT_EQ(TimestampNormalizer::detectFormat("[12345.678901]"),
              TimestampFormat::DMESG);
}

TEST_F(TimestampNormalizerTest, DetectAuditdFormat) {
    EXPECT_EQ(TimestampNormalizer::detectFormat("1700000000.123:456"),
              TimestampFormat::AUDITD);
}

TEST_F(TimestampNormalizerTest, DetectRFC3339Format) {
    EXPECT_EQ(TimestampNormalizer::detectFormat("2024-01-15T10:30:00Z"),
              TimestampFormat::RFC3339);
}

TEST_F(TimestampNormalizerTest, DetectApacheFormat) {
    EXPECT_EQ(TimestampNormalizer::detectFormat("15/Jan/2024:10:30:00 +0800"),
              TimestampFormat::APACHE_ACCESS);
}

TEST_F(TimestampNormalizerTest, DetectUnixEpochFormat) {
    EXPECT_EQ(TimestampNormalizer::detectFormat("1700000000"),
              TimestampFormat::UNIX_EPOCH);
}

TEST_F(TimestampNormalizerTest, DetectUnknownFormat) {
    EXPECT_EQ(TimestampNormalizer::detectFormat("not a timestamp"),
              TimestampFormat::UNKNOWN);
}

// ============================================================================
// Auto-normalize
// ============================================================================

TEST_F(TimestampNormalizerTest, AutoNormalizeSyslog) {
    auto result = TimestampNormalizer::normalize("Jan  5 14:30:00");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, AutoNormalizeAuditd) {
    auto result = TimestampNormalizer::normalize("1700000000.123:456");

    EXPECT_EQ(result.normalizedUtcTimestamp, 1700000000LL);
}

TEST_F(TimestampNormalizerTest, AutoNormalizeRFC3339) {
    auto result = TimestampNormalizer::normalize("2024-01-15T10:30:00Z");

    EXPECT_GT(result.normalizedUtcTimestamp, 0);
}

TEST_F(TimestampNormalizerTest, AutoNormalizeWithHint) {
    // Hint should override auto-detection
    auto result = TimestampNormalizer::normalize(
        "1700000000", TimestampFormat::UNIX_EPOCH);

    EXPECT_EQ(result.normalizedUtcTimestamp, 1700000000LL);
}

// ============================================================================
// Clock Skew Detection
// ============================================================================

TEST_F(TimestampNormalizerTest, ClockSkewBackwards) {
    // Time went backwards
    EXPECT_TRUE(TimestampNormalizer::detectClockSkew(1700000100, 1700000000));
}

TEST_F(TimestampNormalizerTest, ClockSkewLargeForwardJump) {
    // 10 minute jump (default threshold is 5 minutes)
    EXPECT_TRUE(TimestampNormalizer::detectClockSkew(1700000000, 1700000600));
}

TEST_F(TimestampNormalizerTest, ClockSkewNormalProgression) {
    // Normal 1 second progression
    EXPECT_FALSE(TimestampNormalizer::detectClockSkew(1700000000, 1700000001));
}

TEST_F(TimestampNormalizerTest, ClockSkewSameTimestamp) {
    // Duplicate timestamp (not skew)
    EXPECT_FALSE(TimestampNormalizer::detectClockSkew(1700000000, 1700000000));
}

TEST_F(TimestampNormalizerTest, ClockSkewZeroTimestamps) {
    // Zero timestamps should not be detected as skew
    EXPECT_FALSE(TimestampNormalizer::detectClockSkew(0, 0));
}

// ============================================================================
// Year Inference
// ============================================================================

TEST_F(TimestampNormalizerTest, InferYearFromMtime) {
    // 2024-01-15 00:00:00 UTC
    int64_t mtime = 1705276800LL;
    EXPECT_EQ(TimestampNormalizer::inferYear(mtime), 2024);
}

TEST_F(TimestampNormalizerTest, InferYearFromZero) {
    // Should return current year
    int year = TimestampNormalizer::inferYear(0);
    EXPECT_EQ(year, 2026); // Current year
}

// ============================================================================
// Timezone Parsing
// ============================================================================

TEST_F(TimestampNormalizerTest, ParseTimezoneUTC) {
    EXPECT_EQ(TimestampNormalizer::parseTimezoneOffset("UTC"), 0);
    EXPECT_EQ(TimestampNormalizer::parseTimezoneOffset("Z"), 0);
    EXPECT_EQ(TimestampNormalizer::parseTimezoneOffset("GMT"), 0);
}

// parseTimezoneOffset returns the zone's true UTC offset (east positive), so
// dateToEpoch computes UTC = local - offset. This is required for
// RFC3339AndApacheSameMoment to hold (…02:30Z == 10:30 +0800). The previous
// inverted expectations here encoded the bug those integration tests exposed.
TEST_F(TimestampNormalizerTest, ParseTimezoneNumericPositive) {
    int offset = TimestampNormalizer::parseTimezoneOffset("+0800");
    EXPECT_EQ(offset, 8 * 3600); // UTC+8
}

TEST_F(TimestampNormalizerTest, ParseTimezoneNumericNegative) {
    int offset = TimestampNormalizer::parseTimezoneOffset("-0500");
    EXPECT_EQ(offset, -5 * 3600); // UTC-5
}

TEST_F(TimestampNormalizerTest, ParseTimezoneNumericWithColon) {
    int offset = TimestampNormalizer::parseTimezoneOffset("+05:30");
    EXPECT_EQ(offset, 5 * 3600 + 30 * 60); // UTC+5:30
}

TEST_F(TimestampNormalizerTest, ParseTimezoneNamedEST) {
    int offset = TimestampNormalizer::parseTimezoneOffset("EST");
    EXPECT_EQ(offset, -5 * 3600); // EST is UTC-5
}

TEST_F(TimestampNormalizerTest, ParseTimezoneNamedJST) {
    int offset = TimestampNormalizer::parseTimezoneOffset("JST");
    EXPECT_EQ(offset, 9 * 3600); // JST is UTC+9
}

TEST_F(TimestampNormalizerTest, ParseTimezoneEmpty) {
    EXPECT_EQ(TimestampNormalizer::parseTimezoneOffset(""), 0);
}

TEST_F(TimestampNormalizerTest, ParseTimezoneUnknown) {
    EXPECT_EQ(TimestampNormalizer::parseTimezoneOffset("XYZ"), 0);
}

// ============================================================================
// Consistency Tests
// ============================================================================

TEST_F(TimestampNormalizerTest, SyslogConsistencyAcrossDays) {
    // Verify timestamps are monotonically increasing across days
    int64_t prev = 0;
    for (int day = 1; day <= 28; day++) {
        std::string ts = "Jan " + std::to_string(day) + " 12:00:00";
        auto result = TimestampNormalizer::normalizeSyslog(ts, 2024, "UTC");
        EXPECT_GT(result.normalizedUtcTimestamp, prev);
        prev = result.normalizedUtcTimestamp;
    }
}

TEST_F(TimestampNormalizerTest, RFC3339AndApacheSameMoment) {
    // "2024-01-15T02:30:00Z" and "15/Jan/2024:10:30:00 +0800" should be the same moment
    auto rfc = TimestampNormalizer::normalizeRFC3339("2024-01-15T02:30:00Z");
    auto apache = TimestampNormalizer::normalizeApacheTimestamp("15/Jan/2024:10:30:00 +0800");

    EXPECT_EQ(rfc.normalizedUtcTimestamp, apache.normalizedUtcTimestamp);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
