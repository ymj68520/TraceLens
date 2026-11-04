/**
 * @file IosArtifactParsers.h
 * @brief Parses iOS backup artifacts into the shared android.db schema.
 *
 * The schema is shared with the Android analyzer on purpose: every downstream
 * reader (artifact cards, coverage, result sets, report evidence) keys off the
 * same tables, so an iOS task needs no separate query layer.
 *
 * Only plaintext, unencrypted backups are handled. Encrypted backups fail in
 * IosBackupExtractor::initialize() with IOS_BACKUP_ENCRYPTED rather than
 * silently reporting empty artifact tables.
 */

#pragma once
#ifndef IOS_ARTIFACT_PARSERS_H
#define IOS_ARTIFACT_PARSERS_H

#include <string>

class AndroidAnalysisDatabase;
class IosBackupExtractor;

namespace ios_artifacts {

/** Apple's reference date (2001-01-01T00:00:00Z) in Unix seconds. */
inline constexpr long long kAppleEpochOffset = 978307200LL;

/**
 * @brief Convert an Apple-epoch timestamp to Unix seconds.
 *
 * iOS stores Core Data times as nanoseconds since 2001-01-01, so a 2023
 * message reads about 7.15e17. Some stores use seconds instead (~7.15e8).
 * Magnitude decides which; values already in Unix range pass through.
 */
long long toUnixSeconds(long long raw);

/** Classify a raw iOS timestamp: apple_ns, apple_s or unix_s. */
std::string classifyTimestamp(long long raw);

struct IosParseResult {
    int sms = 0;
    int contacts = 0;
    int notes = 0;
    int calendar = 0;
    int callLogs = 0;
    int safariHistory = 0;
    int installedApps = 0;
    int failures = 0;
};

/**
 * @brief Parse every supported artifact from an initialized backup.
 *
 * Each artifact is independent: a missing or malformed source records a
 * coverage row and continues, so one bad database cannot abort the task.
 */
IosParseResult analyzeIosBackup(IosBackupExtractor& extractor,
                                AndroidAnalysisDatabase& database,
                                const std::string& secureTempRoot);

}  // namespace ios_artifacts

#endif  // IOS_ARTIFACT_PARSERS_H
