// LogTamperingDetector.cpp
// Implementation of log tampering detection

#ifdef linux
#undef linux
#endif

#include "LogTamperingDetector.h"
#include "Database/LinuxAnalysisDatabase.h"
#include "Parsers/CompressedLogParser.h"
#include "Parsers/TimestampNormalizer.h"
#include "Parsers/JournalParser.h"
#include "Parsers/AuditdAggregator.h"
#include <sqlite3.h>
#include <algorithm>
#include <map>
#include <set>
#include <cmath>

namespace forensics {
namespace linux {

// ============================================================================
// Main detection entry point
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectAll(const std::string& dbPath) {
    std::vector<TamperingFinding> allFindings;

    // Open database for queries
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        return allFindings;
    }

    // 1. Detect time reversals in system logs
    {
        std::vector<LinuxLogEntry> entries;
        const char* query = "SELECT unix_timestamp, message, log_file FROM linux_log_entries "
                           "ORDER BY unix_timestamp";
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                LinuxLogEntry entry;
                entry.unixTimestamp = sqlite3_column_int64(stmt, 0);
                entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
                entry.logFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
                entries.push_back(entry);
            }
            sqlite3_finalize(stmt);
        }

        auto reversals = detectTimeReversals(entries, "system_logs");
        allFindings.insert(allFindings.end(), reversals.begin(), reversals.end());

        auto gaps = detectTimeWindowGaps(entries, "system_logs");
        allFindings.insert(allFindings.end(), gaps.begin(), gaps.end());

        auto duplicates = detectDuplicateTimestamps(entries, "system_logs");
        allFindings.insert(allFindings.end(), duplicates.begin(), duplicates.end());
    }

    // 2. Detect time reversals in auth logs
    {
        std::vector<LinuxLogEntry> entries;
        const char* query = "SELECT unix_timestamp, message, log_file FROM linux_log_entries "
                           "WHERE log_file LIKE '%auth%' OR log_file LIKE '%secure%' "
                           "ORDER BY unix_timestamp";
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                LinuxLogEntry entry;
                entry.unixTimestamp = sqlite3_column_int64(stmt, 0);
                entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
                entry.logFile = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
                entries.push_back(entry);
            }
            sqlite3_finalize(stmt);
        }

        auto gaps = detectTimeWindowGaps(entries, "auth_logs");
        allFindings.insert(allFindings.end(), gaps.begin(), gaps.end());
    }

    // 3. Detect auditd interruptions
    {
        std::vector<AggregatedAuditEvent> events;
        const char* query = "SELECT timestamp, event_id, event_type FROM linux_audit_events "
                           "ORDER BY timestamp";
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                AggregatedAuditEvent event;
                event.timestamp = sqlite3_column_int64(stmt, 0);
                event.eventId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
                event.eventType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
                events.push_back(event);
            }
            sqlite3_finalize(stmt);
        }

        auto interruptions = detectAuditdInterruptions(events);
        allFindings.insert(allFindings.end(), interruptions.begin(), interruptions.end());
    }

    // 4. Detect journal gaps
    {
        std::vector<JournalEntry> entries;
        const char* query = "SELECT realtime_timestamp, message, boot_id FROM linux_journal_entries "
                           "ORDER BY realtime_timestamp";
        sqlite3_stmt* stmt;
        if (sqlite3_prepare_v2(db, query, -1, &stmt, nullptr) == SQLITE_OK) {
            while (sqlite3_step(stmt) == SQLITE_ROW) {
                JournalEntry entry;
                entry.realtimeTimestamp = sqlite3_column_int64(stmt, 0);
                entry.message = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 1) ?: (const unsigned char*)"");
                entry.bootId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2) ?: (const unsigned char*)"");
                entries.push_back(entry);
            }
            sqlite3_finalize(stmt);
        }

        auto journalGaps = detectJournalMissing(entries);
        allFindings.insert(allFindings.end(), journalGaps.begin(), journalGaps.end());
    }

    sqlite3_close(db);

    // Sort by severity (highest first)
    std::sort(allFindings.begin(), allFindings.end(),
        [](const TamperingFinding& a, const TamperingFinding& b) {
            return static_cast<int>(a.severity) > static_cast<int>(b.severity);
        });

    return allFindings;
}

// ============================================================================
// Log clearing/truncation detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectLogClearing(
    const std::vector<LinuxLogEntry>& entries,
    const std::string& logSource) {

    std::vector<TamperingFinding> findings;

    // Look for patterns indicating log clearing:
    // 1. Sudden drop in timestamp (log was cleared and restarted)
    // 2. Very first entry has a recent timestamp (old logs wiped)
    // 3. Gap followed by entries with different format

    if (entries.size() < 2) return findings;

    // Check if the first entry is suspiciously recent
    // (might indicate previous logs were cleared)
    int64_t firstTimestamp = entries[0].unixTimestamp;
    int64_t lastTimestamp = entries.back().unixTimestamp;

    // If the log spans less than 1 hour but the file suggests it should have more
    // This is a heuristic - real implementation would check file metadata
    if (lastTimestamp - firstTimestamp < 3600 && entries.size() < 100) {
        TamperingFinding finding;
        finding.type = TamperingType::LOG_CLEARED;
        finding.severity = TamperingSeverity::HIGH;
        finding.description = "Log file appears truncated or recently cleared - "
                             "only " + std::to_string(entries.size()) + " entries covering " +
                             std::to_string(lastTimestamp - firstTimestamp) + " seconds";
        finding.logSource = logSource;
        finding.timestampStart = firstTimestamp;
        finding.timestampEnd = lastTimestamp;
        finding.normalizedTime = TimestampNormalizer::normalizeUnixEpoch(firstTimestamp);
        findings.push_back(finding);
    }

    // Check for sudden timestamp resets (log rotated/cleared mid-timeline)
    for (size_t i = 1; i < entries.size(); i++) {
        int64_t prev = entries[i-1].unixTimestamp;
        int64_t curr = entries[i].unixTimestamp;

        // If timestamp drops by more than 1 hour, log might have been cleared
        if (prev > 0 && curr > 0 && curr < prev - 3600) {
            TamperingFinding finding;
            finding.type = TamperingType::LOG_CLEARED;
            finding.severity = TamperingSeverity::HIGH;
            finding.description = "Timestamp reset detected - log may have been cleared "
                                 "at " + std::to_string(curr) +
                                 " (previous: " + std::to_string(prev) + ")";
            finding.logSource = logSource;
            finding.timestampStart = curr;
            finding.timestampEnd = prev;
            findings.push_back(finding);
        }
    }

    return findings;
}

// ============================================================================
// Rotation gap detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectRotationGaps(
    const std::vector<RotatedLogFile>& rotatedFiles) {

    std::vector<TamperingFinding> findings;

    // Group by base name
    std::map<std::string, std::vector<int>> groups;
    for (const auto& file : rotatedFiles) {
        groups[file.baseName].push_back(file.rotationIndex);
    }

    // Check for gaps in rotation sequence
    for (const auto& [baseName, indices] : groups) {
        if (indices.size() < 2) continue;

        std::vector<int> sorted = indices;
        std::sort(sorted.begin(), sorted.end());

        for (size_t i = 1; i < sorted.size(); i++) {
            int expected = sorted[i-1] + 1;
            if (sorted[i] != expected) {
                TamperingFinding finding;
                finding.type = TamperingType::ROTATION_GAP;
                finding.severity = TamperingSeverity::MEDIUM;
                finding.description = "Missing rotated log: " + baseName +
                                     " - expected index " + std::to_string(expected) +
                                     " but found " + std::to_string(sorted[i]);
                finding.logSource = baseName;
                finding.evidence = "Present indices: ";
                for (size_t j = 0; j < sorted.size(); j++) {
                    if (j > 0) finding.evidence += ", ";
                    finding.evidence += std::to_string(sorted[j]);
                }
                findings.push_back(finding);
            }
        }
    }

    return findings;
}

// ============================================================================
// Time reversal detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectTimeReversals(
    const std::vector<LinuxLogEntry>& entries,
    const std::string& logSource) {

    std::vector<TamperingFinding> findings;

    for (size_t i = 1; i < entries.size(); i++) {
        int64_t prev = entries[i-1].unixTimestamp;
        int64_t curr = entries[i].unixTimestamp;

        if (prev <= 0 || curr <= 0) continue;

        // Allow small tolerance (1 second) for near-simultaneous events
        if (curr < prev - 1) {
            TamperingFinding finding;
            finding.type = TamperingType::TIME_REVERSAL;
            finding.severity = TamperingSeverity::MEDIUM;
            finding.description = "Time reversal detected: " +
                                 std::to_string(prev - curr) + " seconds backwards";
            finding.logSource = logSource;
            finding.timestampStart = curr;
            finding.timestampEnd = prev;
            finding.normalizedTime = TimestampNormalizer::normalizeUnixEpoch(curr);
            findings.push_back(finding);
        }
    }

    return findings;
}

// ============================================================================
// Time window gap detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectTimeWindowGaps(
    const std::vector<LinuxLogEntry>& entries,
    const std::string& logSource,
    int64_t gapThresholdSeconds) {

    std::vector<TamperingFinding> findings;

    for (size_t i = 1; i < entries.size(); i++) {
        int64_t prev = entries[i-1].unixTimestamp;
        int64_t curr = entries[i].unixTimestamp;

        if (prev <= 0 || curr <= 0) continue;

        int64_t gap = curr - prev;
        if (gap > gapThresholdSeconds) {
            TamperingFinding finding;
            finding.type = TamperingType::TIME_WINDOW_GAP;
            finding.severity = calculateGapSeverity(gap);
            finding.description = "Gap of " + std::to_string(gap) +
                                 " seconds in " + logSource + " logs";
            finding.logSource = logSource;
            finding.timestampStart = prev;
            finding.timestampEnd = curr;
            finding.normalizedTime = TimestampNormalizer::normalizeUnixEpoch(prev);
            findings.push_back(finding);
        }
    }

    return findings;
}

// ============================================================================
// Cross-log inconsistency detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectCrossLogInconsistencies(
    const std::vector<LinuxLoginRecord>& loginRecords,
    const std::vector<LinuxLogEntry>& authEntries) {

    std::vector<TamperingFinding> findings;

    // Build sets of login timestamps from each source
    std::set<int64_t> wtmpLogins;
    for (const auto& record : loginRecords) {
        if (record.isSuccess && record.loginTime > 0) {
            wtmpLogins.insert(record.loginTime / 60); // Minute granularity
        }
    }

    std::set<int64_t> authLogins;
    for (const auto& entry : authEntries) {
        if (entry.unixTimestamp > 0 &&
            (entry.message.find("Accepted") != std::string::npos ||
             entry.message.find("session opened") != std::string::npos)) {
            authLogins.insert(entry.unixTimestamp / 60);
        }
    }

    // Check for logins in wtmp but not in auth.log
    for (int64_t wtmpTime : wtmpLogins) {
        bool found = false;
        // Check within +/- 2 minute window
        for (int64_t t = wtmpTime - 2; t <= wtmpTime + 2; t++) {
            if (authLogins.find(t) != authLogins.end()) {
                found = true;
                break;
            }
        }

        if (!found) {
            TamperingFinding finding;
            finding.type = TamperingType::CROSS_LOG_INCONSISTENCY;
            finding.severity = TamperingSeverity::HIGH;
            finding.description = "Login recorded in wtmp but not in auth.log - "
                                 "possible auth log tampering";
            finding.logSource = "wtmp vs auth.log";
            finding.timestampStart = wtmpTime * 60;
            finding.normalizedTime = TimestampNormalizer::normalizeUnixEpoch(wtmpTime * 60);
            findings.push_back(finding);
        }
    }

    return findings;
}

// ============================================================================
// Journal missing detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectJournalMissing(
    const std::vector<JournalEntry>& entries,
    int64_t gapThresholdSeconds) {

    std::vector<TamperingFinding> findings;

    if (entries.size() < 2) return findings;

    // Check for gaps in journal entries
    for (size_t i = 1; i < entries.size(); i++) {
        int64_t prev = entries[i-1].realtimeTimestamp;
        int64_t curr = entries[i].realtimeTimestamp;

        if (prev <= 0 || curr <= 0) continue;

        int64_t gapSeconds = (curr - prev) / 1000000LL; // Convert from microseconds
        if (gapSeconds > gapThresholdSeconds) {
            TamperingFinding finding;
            finding.type = TamperingType::JOURNAL_MISSING;
            finding.severity = calculateGapSeverity(gapSeconds);
            finding.description = "Journal gap of " + std::to_string(gapSeconds) +
                                 " seconds - possible journal vacuum or tampering";
            finding.logSource = "journal";
            finding.timestampStart = prev / 1000000LL;
            finding.timestampEnd = curr / 1000000LL;
            finding.normalizedTime = TimestampNormalizer::normalizeJournalRealtime(prev);
            findings.push_back(finding);
        }
    }

    // Check for boot session gaps
    std::map<std::string, int64_t> bootFirstEntry;
    std::map<std::string, int64_t> bootLastEntry;
    for (const auto& entry : entries) {
        if (entry.bootId.empty()) continue;
        if (bootFirstEntry.find(entry.bootId) == bootFirstEntry.end()) {
            bootFirstEntry[entry.bootId] = entry.realtimeTimestamp;
        }
        bootLastEntry[entry.bootId] = entry.realtimeTimestamp;
    }

    // Sort boots by first entry time
    std::vector<std::pair<int64_t, std::string>> sortedBoots;
    for (const auto& [bootId, firstTime] : bootFirstEntry) {
        sortedBoots.push_back({firstTime, bootId});
    }
    std::sort(sortedBoots.begin(), sortedBoots.end());

    // Check for gaps between boot sessions
    for (size_t i = 1; i < sortedBoots.size(); i++) {
        int64_t prevBootEnd = bootLastEntry[sortedBoots[i-1].second];
        int64_t currBootStart = sortedBoots[i].first;
        int64_t gapSeconds = (currBootStart - prevBootEnd) / 1000000LL;

        if (gapSeconds > 86400) { // More than 1 day between boots
            TamperingFinding finding;
            finding.type = TamperingType::JOURNAL_MISSING;
            finding.severity = TamperingSeverity::MEDIUM;
            finding.description = "Gap of " + std::to_string(gapSeconds / 86400) +
                                 " days between boot sessions - possible journal vacuum";
            finding.logSource = "journal";
            finding.timestampStart = prevBootEnd / 1000000LL;
            finding.timestampEnd = currBootStart / 1000000LL;
            findings.push_back(finding);
        }
    }

    return findings;
}

// ============================================================================
// Auditd interruption detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectAuditdInterruptions(
    const std::vector<AggregatedAuditEvent>& events,
    int64_t gapThresholdSeconds) {

    std::vector<TamperingFinding> findings;

    if (events.size() < 2) return findings;

    for (size_t i = 1; i < events.size(); i++) {
        int64_t prev = events[i-1].timestamp;
        int64_t curr = events[i].timestamp;

        if (prev <= 0 || curr <= 0) continue;

        int64_t gap = curr - prev;
        if (gap > gapThresholdSeconds) {
            TamperingFinding finding;
            finding.type = TamperingType::AUDITD_INTERRUPTED;
            finding.severity = calculateGapSeverity(gap);
            finding.description = "Audit log gap of " + std::to_string(gap) +
                                 " seconds - auditd may have been stopped or tampered";
            finding.logSource = "audit.log";
            finding.timestampStart = prev;
            finding.timestampEnd = curr;
            finding.normalizedTime = TimestampNormalizer::normalizeUnixEpoch(prev);
            findings.push_back(finding);
        }
    }

    return findings;
}

// ============================================================================
// Duplicate timestamp detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectDuplicateTimestamps(
    const std::vector<LinuxLogEntry>& entries,
    const std::string& logSource,
    int minDuplicates) {

    std::vector<TamperingFinding> findings;

    // Count entries per timestamp
    std::map<int64_t, int> timestampCounts;
    for (const auto& entry : entries) {
        if (entry.unixTimestamp > 0) {
            timestampCounts[entry.unixTimestamp]++;
        }
    }

    // Flag timestamps with excessive duplicates
    for (const auto& [timestamp, count] : timestampCounts) {
        if (count >= minDuplicates) {
            TamperingFinding finding;
            finding.type = TamperingType::DUPLICATE_TIMESTAMPS;
            finding.severity = TamperingSeverity::LOW;
            finding.description = std::to_string(count) +
                                 " entries share the same timestamp in " + logSource +
                                 " - possible log injection or clock issue";
            finding.logSource = logSource;
            finding.timestampStart = timestamp;
            finding.timestampEnd = timestamp;
            finding.normalizedTime = TimestampNormalizer::normalizeUnixEpoch(timestamp);
            findings.push_back(finding);
        }
    }

    return findings;
}

// ============================================================================
// Pattern break detection
// ============================================================================

std::vector<TamperingFinding> LogTamperingDetector::detectPatternBreaks(
    const std::vector<LinuxLogEntry>& entries,
    const std::string& logSource) {

    std::vector<TamperingFinding> findings;

    if (entries.size() < 10) return findings;

    // Analyze the first N entries to establish baseline format
    // Then look for entries that deviate
    // This is a simplified heuristic - real implementation would be more sophisticated

    // Check if process names suddenly change (might indicate log injection)
    std::map<std::string, int> processCounts;
    for (size_t i = 0; i < std::min(entries.size(), size_t(100)); i++) {
        if (!entries[i].process.empty()) {
            processCounts[entries[i].process]++;
        }
    }

    // Find the dominant process
    std::string dominantProcess;
    int maxCount = 0;
    for (const auto& [process, count] : processCounts) {
        if (count > maxCount) {
            maxCount = count;
            dominantProcess = process;
        }
    }

    // Look for sudden format changes
    // (This is a placeholder for more sophisticated pattern analysis)

    return findings;
}

// ============================================================================
// Helper methods
// ============================================================================

TamperingSeverity LogTamperingDetector::calculateGapSeverity(int64_t gapSeconds) {
    if (gapSeconds > 86400 * 7) {       // > 1 week
        return TamperingSeverity::CRITICAL;
    } else if (gapSeconds > 86400) {     // > 1 day
        return TamperingSeverity::HIGH;
    } else if (gapSeconds > 3600) {      // > 1 hour
        return TamperingSeverity::MEDIUM;
    } else if (gapSeconds > 300) {       // > 5 minutes
        return TamperingSeverity::LOW;
    }
    return TamperingSeverity::INFO;
}

bool LogTamperingDetector::isSuspiciousTimestamp(int64_t timestamp, int64_t prevTimestamp) {
    if (timestamp <= 0) return true;
    if (prevTimestamp > 0 && timestamp < prevTimestamp - 1) return true;
    return false;
}

} // namespace linux
} // namespace forensics
