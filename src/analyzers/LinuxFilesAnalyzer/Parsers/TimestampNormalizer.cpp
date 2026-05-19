// TimestampNormalizer.cpp
// Implementation of unified timestamp normalization

#ifdef linux
#undef linux
#endif

#include "TimestampNormalizer.h"
#include <sstream>
#include <iomanip>
#include <cstring>
#include <ctime>
#include <regex>
#include <algorithm>

#ifdef __linux__
#include <sys/time.h>
#endif

namespace forensics {
namespace linux {

// ============================================================================
// Month name parsing
// ============================================================================

int TimestampNormalizer::parseMonth(const std::string& month) {
    static const char* months[] = {
        "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
    };
    for (int i = 0; i < 12; i++) {
        if (month == months[i]) return i + 1;
    }
    return 0;
}

bool TimestampNormalizer::isLeapYear(int year) {
    return (year % 4 == 0 && year % 100 != 0) || (year % 400 == 0);
}

int64_t TimestampNormalizer::dateToEpoch(int year, int month, int day,
    int hour, int minute, int second, int tzOffset) {

    // Days per month (non-leap year)
    static const int daysInMonth[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};

    // Calculate days since epoch (1970-01-01)
    int64_t days = 0;

    // Years
    for (int y = 1970; y < year; y++) {
        days += isLeapYear(y) ? 366 : 365;
    }

    // Months
    for (int m = 1; m < month; m++) {
        days += daysInMonth[m - 1];
        if (m == 2 && isLeapYear(year)) days++;
    }

    // Days
    days += day - 1;

    int64_t epoch = days * 86400LL + hour * 3600LL + minute * 60LL + second;
    epoch -= tzOffset; // Apply timezone offset

    return epoch;
}

// ============================================================================
// Syslog timestamp parsing
// ============================================================================

bool TimestampNormalizer::parseSyslogComponents(const std::string& timestamp,
    int& month, int& day, int& hour, int& minute, int& second) {

    // Format: "Jan  5 14:30:00" or "Jan 05 14:30:00"
    std::istringstream ss(timestamp);
    std::string monthStr;
    ss >> monthStr >> day;

    month = parseMonth(monthStr);
    if (month == 0) return false;

    char colon1, colon2;
    ss >> hour >> colon1 >> minute >> colon2 >> second;

    return colon1 == ':' && colon2 == ':' &&
           hour >= 0 && hour < 24 &&
           minute >= 0 && minute < 60 &&
           second >= 0 && second < 60;
}

NormalizedTimestamp TimestampNormalizer::normalizeSyslog(
    const std::string& timestamp,
    int systemYear,
    const std::string& timezone,
    int64_t bootTime) {

    NormalizedTimestamp result;
    result.originalTimestamp = timestamp;
    result.timezoneSource = "inferred";

    int month, day, hour, minute, second;
    if (!parseSyslogComponents(timestamp, month, day, hour, minute, second)) {
        result.timestampConfidence = 0;
        return result;
    }

    // Infer year if not provided
    int year = systemYear;
    if (year <= 0) {
        // Use current year as fallback
        time_t now = time(nullptr);
        struct tm* tm = gmtime(&now);
        year = tm->tm_year + 1900;
        result.inferredYear = year;
        result.timestampConfidence = 70; // Lower confidence for inferred year
    } else {
        result.inferredYear = year;
        result.timestampConfidence = 85;
    }

    // Parse timezone offset
    int tzOffset = 0;
    if (!timezone.empty()) {
        tzOffset = parseTimezoneOffset(timezone);
        result.timezoneSource = "file";
        result.timestampConfidence = 90;
    } else {
        // Try to get system timezone
        tzOffset = getSystemTimezoneOffset();
        result.timezoneSource = "system";
    }

    result.normalizedUtcTimestamp = dateToEpoch(year, month, day, hour, minute, second, tzOffset);

    // Clock skew detection against boot time
    if (bootTime > 0) {
        int64_t diff = result.normalizedUtcTimestamp - bootTime;
        if (diff < -86400 || diff > 86400 * 365 * 2) { // More than 1 day before boot or 2 years after
            result.clockSkewFlag = true;
        }
    }

    return result;
}

// ============================================================================
// dmesg timestamp parsing
// ============================================================================

NormalizedTimestamp TimestampNormalizer::normalizeDmesg(
    const std::string& timestamp,
    int64_t bootTimeUtc,
    int64_t uptimeSeconds) {

    NormalizedTimestamp result;
    result.originalTimestamp = timestamp;
    result.timezoneSource = "utc";

    // Parse seconds since boot
    // Format: "[12345.678901]" or "12345.678901"
    std::string clean = timestamp;
    if (!clean.empty() && clean.front() == '[') clean = clean.substr(1);
    if (!clean.empty() && clean.back() == ']') clean.pop_back();

    double secondsSinceBoot = 0;
    try {
        secondsSinceBoot = std::stod(clean);
    } catch (...) {
        result.timestampConfidence = 0;
        return result;
    }

    result.monotonicTimestamp = static_cast<int64_t>(secondsSinceBoot * 1000000LL);

    if (bootTimeUtc > 0) {
        result.normalizedUtcTimestamp = bootTimeUtc + static_cast<int64_t>(secondsSinceBoot);
        result.timestampConfidence = 80; // dmesg has no year, boot time might be estimated
    } else {
        // Can't normalize without boot time
        result.normalizedUtcTimestamp = static_cast<int64_t>(secondsSinceBoot);
        result.timestampConfidence = 30;
    }

    return result;
}

// ============================================================================
// Auditd timestamp parsing
// ============================================================================

NormalizedTimestamp TimestampNormalizer::normalizeAuditd(const std::string& timestamp) {
    NormalizedTimestamp result;
    result.originalTimestamp = timestamp;
    result.timezoneSource = "utc";
    result.timestampConfidence = 95;

    // Format: "1700000000.123:456"
    size_t colonPos = timestamp.find(':');
    std::string epochStr = (colonPos != std::string::npos) ?
        timestamp.substr(0, colonPos) : timestamp;

    try {
        double epoch = std::stod(epochStr);
        result.normalizedUtcTimestamp = static_cast<int64_t>(epoch);
    } catch (...) {
        result.timestampConfidence = 0;
    }

    return result;
}

// ============================================================================
// Journal timestamp normalization
// ============================================================================

NormalizedTimestamp TimestampNormalizer::normalizeJournalRealtime(int64_t microseconds) {
    NormalizedTimestamp result;
    result.timezoneSource = "utc";
    result.timestampConfidence = 100;
    result.normalizedUtcTimestamp = microseconds / 1000000LL;
    result.originalTimestamp = std::to_string(microseconds);
    return result;
}

NormalizedTimestamp TimestampNormalizer::normalizeJournalMonotonic(
    int64_t microseconds,
    const std::string& bootId,
    int64_t bootTimeUtc) {

    NormalizedTimestamp result;
    result.originalTimestamp = std::to_string(microseconds);
    result.monotonicTimestamp = microseconds;
    result.bootId = bootId;

    if (bootTimeUtc > 0) {
        result.normalizedUtcTimestamp = bootTimeUtc + (microseconds / 1000000LL);
        result.timestampConfidence = 90;
    } else {
        result.normalizedUtcTimestamp = microseconds / 1000000LL;
        result.timestampConfidence = 30;
    }

    return result;
}

// ============================================================================
// Unix epoch normalization (wtmp/btmp)
// ============================================================================

NormalizedTimestamp TimestampNormalizer::normalizeUnixEpoch(int64_t epochSeconds) {
    NormalizedTimestamp result;
    result.originalTimestamp = std::to_string(epochSeconds);
    result.normalizedUtcTimestamp = epochSeconds;
    result.timezoneSource = "utc";
    result.timestampConfidence = 95;
    return result;
}

// ============================================================================
// RFC3339 normalization (container logs)
// ============================================================================

NormalizedTimestamp TimestampNormalizer::normalizeRFC3339(const std::string& timestamp) {
    NormalizedTimestamp result;
    result.originalTimestamp = timestamp;
    result.timestampConfidence = 100;

    // Format: "2024-01-15T10:30:00.123456789Z" or "2024-01-15T10:30:00+08:00"
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;
    int tzSign = 0, tzHour = 0, tzMinute = 0;

    // Try regex for RFC3339
    std::regex rfc3339_re(
        R"((\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?([Zz]|[+-]\d{2}:?\d{2}))");
    std::smatch match;

    if (std::regex_match(timestamp, match, rfc3339_re)) {
        year = std::stoi(match[1]);
        month = std::stoi(match[2]);
        day = std::stoi(match[3]);
        hour = std::stoi(match[4]);
        minute = std::stoi(match[5]);
        second = std::stoi(match[6]);

        std::string tzStr = match[8];
        if (tzStr == "Z" || tzStr == "z") {
            result.timezoneSource = "utc";
        } else {
            // Remove colon if present: +08:00 → +0800
            if (tzStr.size() == 6 && tzStr[3] == ':') {
                tzStr.erase(3, 1);
            }
            tzSign = (tzStr[0] == '+') ? 1 : -1;
            tzHour = std::stoi(tzStr.substr(1, 2));
            tzMinute = std::stoi(tzStr.substr(3, 2));
            int tzOffset = tzSign * (tzHour * 3600 + tzMinute * 60);
            result.timezoneSource = "file";
            result.normalizedUtcTimestamp = dateToEpoch(year, month, day, hour, minute, second, tzOffset);
            return result;
        }
    } else {
        // Try simpler ISO8601 without timezone
        std::regex iso_re(
            R"((\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2}))");
        if (std::regex_match(timestamp, match, iso_re)) {
            year = std::stoi(match[1]);
            month = std::stoi(match[2]);
            day = std::stoi(match[3]);
            hour = std::stoi(match[4]);
            minute = std::stoi(match[5]);
            second = std::stoi(match[6]);
            result.timezoneSource = "inferred";
        } else {
            result.timestampConfidence = 0;
            return result;
        }
    }

    result.normalizedUtcTimestamp = dateToEpoch(year, month, day, hour, minute, second);
    return result;
}

// ============================================================================
// Apache timestamp normalization
// ============================================================================

NormalizedTimestamp TimestampNormalizer::normalizeApacheTimestamp(const std::string& timestamp) {
    NormalizedTimestamp result;
    result.originalTimestamp = timestamp;
    result.timestampConfidence = 100;

    // Format: "15/Jan/2024:10:30:00 +0800"
    std::regex apache_re(R"((\d{2})/(\w{3})/(\d{4}):(\d{2}):(\d{2}):(\d{2}) ([+-]\d{4}))");
    std::smatch match;

    if (!std::regex_match(timestamp, match, apache_re)) {
        result.timestampConfidence = 0;
        return result;
    }

    int day = std::stoi(match[1]);
    int month = parseMonth(match[2]);
    int year = std::stoi(match[3]);
    int hour = std::stoi(match[4]);
    int minute = std::stoi(match[5]);
    int second = std::stoi(match[6]);
    int tzOffset = parseTimezoneOffset(match[7]);

    if (month == 0) {
        result.timestampConfidence = 0;
        return result;
    }

    result.normalizedUtcTimestamp = dateToEpoch(year, month, day, hour, minute, second, tzOffset);
    result.timezoneSource = "file";
    return result;
}

// ============================================================================
// ISO8601 normalization
// ============================================================================

NormalizedTimestamp TimestampNormalizer::normalizeISO8601(const std::string& timestamp) {
    // ISO8601 is essentially RFC3339 without strict requirements
    return normalizeRFC3339(timestamp);
}

// ============================================================================
// Auto-detection and normalization
// ============================================================================

TimestampFormat TimestampNormalizer::detectFormat(const std::string& timestamp) {
    if (timestamp.empty()) return TimestampFormat::UNKNOWN;

    // Check for dmesg format: [12345.678]
    if (timestamp.front() == '[' && timestamp.find('.') != std::string::npos) {
        return TimestampFormat::DMESG;
    }

    // Check for auditd format: digits.digits:digits
    if (std::regex_match(timestamp, std::regex(R"(\d+\.\d+:\d+)"))) {
        return TimestampFormat::AUDITD;
    }

    // Check for RFC3339/ISO8601: 2024-01-15T10:30:00
    if (std::regex_match(timestamp, std::regex(R"(\d{4}-\d{2}-\d{2}[T ].*)"))) {
        return TimestampFormat::RFC3339;
    }

    // Check for Apache: 15/Jan/2024:10:30:00
    if (std::regex_match(timestamp, std::regex(R"(\d{2}/\w{3}/\d{4}:.*)"))) {
        return TimestampFormat::APACHE_ACCESS;
    }

    // Check for syslog with year: 2024 Jan  5 14:30:00
    if (std::regex_match(timestamp, std::regex(R"(\d{4} \w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})"))) {
        return TimestampFormat::SYSLOG_WITH_YEAR;
    }

    // Check for syslog: Jan  5 14:30:00
    if (std::regex_match(timestamp, std::regex(R"(\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2})"))) {
        return TimestampFormat::SYSLOG;
    }

    // Check for Unix epoch (pure digits)
    if (std::regex_match(timestamp, std::regex(R"(\d{9,10})"))) {
        return TimestampFormat::UNIX_EPOCH;
    }

    return TimestampFormat::UNKNOWN;
}

NormalizedTimestamp TimestampNormalizer::normalize(const std::string& timestamp,
    TimestampFormat hint) {

    TimestampFormat format = (hint == TimestampFormat::UNKNOWN) ?
        detectFormat(timestamp) : hint;

    switch (format) {
        case TimestampFormat::SYSLOG:
            return normalizeSyslog(timestamp);
        case TimestampFormat::SYSLOG_WITH_YEAR: {
            // Extract year from "2024 Jan  5 14:30:00"
            std::istringstream ss(timestamp);
            int year;
            ss >> year;
            std::string rest;
            std::getline(ss, rest);
            auto result = normalizeSyslog(rest);
            result.inferredYear = year;
            result.timestampConfidence = 90;
            return result;
        }
        case TimestampFormat::DMESG:
            return normalizeDmesg(timestamp);
        case TimestampFormat::AUDITD:
            return normalizeAuditd(timestamp);
        case TimestampFormat::RFC3339:
        case TimestampFormat::ISO8601:
            return normalizeRFC3339(timestamp);
        case TimestampFormat::APACHE_ACCESS:
            return normalizeApacheTimestamp(timestamp);
        case TimestampFormat::UNIX_EPOCH:
            try {
                return normalizeUnixEpoch(std::stoll(timestamp));
            } catch (...) {
                NormalizedTimestamp result;
                result.originalTimestamp = timestamp;
                result.timestampConfidence = 0;
                return result;
            }
        default: {
            NormalizedTimestamp result;
            result.originalTimestamp = timestamp;
            result.timestampConfidence = 0;
            return result;
        }
    }
}

// ============================================================================
// Clock skew detection
// ============================================================================

bool TimestampNormalizer::detectClockSkew(int64_t prevTimestamp, int64_t currentTimestamp,
    int64_t maxGapSeconds) {

    if (prevTimestamp <= 0 || currentTimestamp <= 0) return false;

    // Time went backwards by more than a small tolerance
    if (currentTimestamp < prevTimestamp - 1) {
        return true;
    }

    // Large forward jump might indicate clock adjustment
    int64_t diff = currentTimestamp - prevTimestamp;
    if (diff > maxGapSeconds) {
        return true;
    }

    return false;
}

// ============================================================================
// Year inference
// ============================================================================

int TimestampNormalizer::inferYear(int64_t fileMtime) {
    if (fileMtime <= 0) {
        time_t now = time(nullptr);
        return gmtime(&now)->tm_year + 1900;
    }
    struct tm* tm = gmtime(&fileMtime);
    return tm->tm_year + 1900;
}

// ============================================================================
// Timezone utilities
// ============================================================================

int TimestampNormalizer::getSystemTimezoneOffset() {
#ifdef __linux__
    time_t now = time(nullptr);
    struct tm local_tm;
    localtime_r(&now, &local_tm);
    // tm_gmtoff contains the UTC offset in seconds
    return -static_cast<int>(local_tm.tm_gmtoff);
#else
    return 0;
#endif
}

int TimestampNormalizer::parseTimezoneOffset(const std::string& tz) {
    if (tz.empty()) return 0;

    // UTC/Z
    if (tz == "Z" || tz == "z" || tz == "UTC" || tz == "GMT") return 0;

    // Numeric offset: +0800, -0500, +08:00
    if (tz[0] == '+' || tz[0] == '-') {
        int sign = (tz[0] == '+') ? -1 : 1; // Negative because we subtract offset
        std::string digits;
        for (char c : tz) {
            if (isdigit(c)) digits += c;
        }
        if (digits.size() >= 4) {
            int hours = std::stoi(digits.substr(0, 2));
            int minutes = std::stoi(digits.substr(2, 2));
            return sign * (hours * 3600 + minutes * 60);
        }
    }

    // Named timezones
    static const std::map<std::string, int> tzMap = {
        {"EST", 5 * 3600}, {"EDT", 4 * 3600},
        {"CST", 6 * 3600}, {"CDT", 5 * 3600},
        {"MST", 7 * 3600}, {"MDT", 6 * 3600},
        {"PST", 8 * 3600}, {"PDT", 7 * 3600},
        {"CET", -1 * 3600}, {"CEST", -2 * 3600},
        {"JST", -9 * 3600}, {"KST", -9 * 3600},
        {"IST", -5 * 3600 - 1800},
        {"AEST", -10 * 3600}, {"AEDT", -11 * 3600},
    };

    auto it = tzMap.find(tz);
    if (it != tzMap.end()) return it->second;

    return 0;
}

} // namespace linux
} // namespace forensics
