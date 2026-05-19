// TimestampNormalizer.h
// Unified timestamp normalization for Linux forensic analysis

#pragma once
#ifndef TIMESTAMP_NORMALIZER_H
#define TIMESTAMP_NORMALIZER_H

#include <string>
#include <cstdint>
#include "LinuxDataTypes.h"

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Timestamp format types
enum class TimestampFormat {
    UNKNOWN,
    SYSLOG,           // "Jan  5 14:30:00" (no year, no timezone)
    SYSLOG_WITH_YEAR, // "2024 Jan  5 14:30:00"
    DMESG,            // "[12345.678901]" (seconds since boot)
    AUDITD,           // "1700000000.123:456" (epoch.serial)
    JOURNAL_REALTIME, // Microseconds since epoch
    JOURNAL_MONOTONIC,// Microseconds since boot
    UNIX_EPOCH,       // Seconds since epoch (wtmp/btmp)
    RFC3339,          // "2024-01-15T10:30:00Z" (container logs)
    RFC3164,          // "Jan  5 14:30:00 hostname" (BSD syslog)
    APACHE_ACCESS,    // "15/Jan/2024:10:30:00 +0800"
    ISO8601,          // "2024-01-15 10:30:00"
    SYSLOG_ISO,       // "2024-01-15T10:30:00.000+08:00" (rsyslog format)
    SYSTEMD_SHORT     // "Jan 05 14:30:00" (systemd journal short format)
};

// Timezone information source
enum class TimezoneSource {
    NONE,         // No timezone info available
    FILE,         // Timezone from log file content
    SYSTEM,       // Timezone from system config (/etc/timezone, /etc/localtime)
    INFERRED,     // Timezone inferred from context
    UTC           // Explicitly UTC
};

// Main timestamp normalizer class
class TimestampNormalizer {
public:
    // Normalize a syslog timestamp (no year, no timezone)
    // Format: "Jan  5 14:30:00" or "Jan 05 14:30:00"
    static NormalizedTimestamp normalizeSyslog(
        const std::string& timestamp,
        int systemYear = 0,           // System year (from file mtime or boot time)
        const std::string& timezone = "", // System timezone (e.g., "EST", "+0800")
        int64_t bootTime = 0);        // Boot time for year inference

    // Normalize a dmesg timestamp (relative to boot)
    // Format: "[12345.678901]" or "12345.678901"
    static NormalizedTimestamp normalizeDmesg(
        const std::string& timestamp,
        int64_t bootTimeUtc = 0,      // Boot time in UTC (from /proc/stat or journal)
        int64_t uptimeSeconds = 0);   // Current uptime

    // Normalize an auditd timestamp
    // Format: "1700000000.123:456" (epoch.serial)
    static NormalizedTimestamp normalizeAuditd(const std::string& timestamp);

    // Normalize journal realtime timestamp (microseconds since epoch)
    static NormalizedTimestamp normalizeJournalRealtime(int64_t microseconds);

    // Normalize journal monotonic timestamp (microseconds since boot)
    static NormalizedTimestamp normalizeJournalMonotonic(
        int64_t microseconds,
        const std::string& bootId,
        int64_t bootTimeUtc = 0);

    // Normalize Unix epoch timestamp (wtmp/btmp)
    static NormalizedTimestamp normalizeUnixEpoch(int64_t epochSeconds);

    // Normalize RFC3339 timestamp (container logs)
    // Format: "2024-01-15T10:30:00.123456789Z" or "2024-01-15T10:30:00+08:00"
    static NormalizedTimestamp normalizeRFC3339(const std::string& timestamp);

    // Normalize Apache access log timestamp
    // Format: "15/Jan/2024:10:30:00 +0800"
    static NormalizedTimestamp normalizeApacheTimestamp(const std::string& timestamp);

    // Normalize ISO8601 timestamp
    // Format: "2024-01-15 10:30:00" or "2024-01-15T10:30:00"
    static NormalizedTimestamp normalizeISO8601(const std::string& timestamp);

    // Auto-detect format and normalize
    static NormalizedTimestamp normalize(const std::string& timestamp,
        TimestampFormat hint = TimestampFormat::UNKNOWN);

    // Detect timestamp format from string
    static TimestampFormat detectFormat(const std::string& timestamp);

    // Detect clock skew between two consecutive timestamps
    static bool detectClockSkew(int64_t prevTimestamp, int64_t currentTimestamp,
        int64_t maxGapSeconds = 300);  // 5 minutes default

    // Infer year from file modification time
    static int inferYear(int64_t fileMtime);

    // Get system timezone offset in seconds
    static int getSystemTimezoneOffset();

    // Parse timezone string to offset in seconds
    static int parseTimezoneOffset(const std::string& tz);

private:
    // Parse month name to number (1-12)
    static int parseMonth(const std::string& month);

    // Parse syslog timestamp components
    static bool parseSyslogComponents(const std::string& timestamp,
        int& month, int& day, int& hour, int& minute, int& second);

    // Convert date components to Unix timestamp
    static int64_t dateToEpoch(int year, int month, int day,
        int hour, int minute, int second, int tzOffset = 0);

    // Check if year is a leap year
    static bool isLeapYear(int year);
};

} // namespace linux
} // namespace forensics

#endif // TIMESTAMP_NORMALIZER_H
