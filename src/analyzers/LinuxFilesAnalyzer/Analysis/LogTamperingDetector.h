// LogTamperingDetector.h
// Detects log tampering, clearing, truncation, and inconsistencies

#pragma once
#ifndef LOG_TAMPERING_DETECTOR_H
#define LOG_TAMPERING_DETECTOR_H

#include <string>
#include <vector>
#include <cstdint>
#include "LinuxDataTypes.h"

// linux is a predefined macro on Linux systems, must undef to use as namespace
#ifdef linux
#undef linux
#endif

namespace forensics {
namespace linux {

// Forward declarations for types from other parsers
struct RotatedLogFile;
struct JournalEntry;
struct AggregatedAuditEvent;

// Types of log tampering
enum class TamperingType {
    LOG_CLEARED,           // Log file was cleared/truncated
    ROTATION_GAP,          // Missing rotated log files
    TIME_REVERSAL,         // Timestamps go backwards
    TIME_WINDOW_GAP,       // Large gap in log timeline
    CROSS_LOG_INCONSISTENCY, // Different logs contradict each other
    JOURNAL_MISSING,       // Journal entries missing for time period
    AUDITD_INTERRUPTED,    // Audit log has unexpected stop
    DUPLICATE_TIMESTAMPS,  // Suspicious duplicate timestamps
    TIMESTAMP_ANOMALY,     // Timestamps don't match expected pattern
    LOG_PATTERN_BREAK      // Log format suddenly changes
};

// Severity levels
enum class TamperingSeverity {
    INFO = 0,
    LOW = 1,
    MEDIUM = 2,
    HIGH = 3,
    CRITICAL = 4
};

// A single tampering detection result
struct TamperingFinding {
    TamperingType type;
    TamperingSeverity severity;
    std::string description;          // Human-readable description
    std::string logSource;            // Which log file(s) involved
    int64_t timestampStart = 0;       // Start of affected period
    int64_t timestampEnd = 0;         // End of affected period
    std::string evidence;             // Supporting evidence
    std::vector<std::string> relatedFiles;  // Related log files
    NormalizedTimestamp normalizedTime;
    EvidenceProvenance provenance;
};

// Main detector class
class LogTamperingDetector {
public:
    // Run all tampering detection checks
    static std::vector<TamperingFinding> detectAll(
        const std::string& dbPath);

    // Individual detection methods

    // Detect log clearing/truncation (file size drops, content resets)
    static std::vector<TamperingFinding> detectLogClearing(
        const std::vector<LinuxLogEntry>& entries,
        const std::string& logSource);

    // Detect gaps in rotated logs (missing auth.log.2, etc.)
    static std::vector<TamperingFinding> detectRotationGaps(
        const std::vector<RotatedLogFile>& rotatedFiles);

    // Detect time reversals within a single log
    static std::vector<TamperingFinding> detectTimeReversals(
        const std::vector<LinuxLogEntry>& entries,
        const std::string& logSource);

    // Detect large time windows with no log activity
    static std::vector<TamperingFinding> detectTimeWindowGaps(
        const std::vector<LinuxLogEntry>& entries,
        const std::string& logSource,
        int64_t gapThresholdSeconds = 3600);  // 1 hour default

    // Detect cross-log inconsistencies (wtmp vs auth.log)
    static std::vector<TamperingFinding> detectCrossLogInconsistencies(
        const std::vector<LinuxLoginRecord>& loginRecords,
        const std::vector<LinuxLogEntry>& authEntries);

    // Detect missing journal entries
    static std::vector<TamperingFinding> detectJournalMissing(
        const std::vector<JournalEntry>& entries,
        int64_t gapThresholdSeconds = 3600);

    // Detect auditd log interruptions
    static std::vector<TamperingFinding> detectAuditdInterruptions(
        const std::vector<AggregatedAuditEvent>& events,
        int64_t gapThresholdSeconds = 300);  // 5 minutes default

    // Detect suspicious duplicate timestamps
    static std::vector<TamperingFinding> detectDuplicateTimestamps(
        const std::vector<LinuxLogEntry>& entries,
        const std::string& logSource,
        int minDuplicates = 10);  // Flag if N+ entries share same timestamp

    // Detect log format pattern breaks
    static std::vector<TamperingFinding> detectPatternBreaks(
        const std::vector<LinuxLogEntry>& entries,
        const std::string& logSource);

private:
    // Calculate severity based on gap duration and context
    static TamperingSeverity calculateGapSeverity(int64_t gapSeconds);

    // Check if a timestamp looks suspicious
    static bool isSuspiciousTimestamp(int64_t timestamp, int64_t prevTimestamp);
};

} // namespace linux
} // namespace forensics

#endif // LOG_TAMPERING_DETECTOR_H
