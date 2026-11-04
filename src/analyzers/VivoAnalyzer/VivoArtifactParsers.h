/**
 * @file VivoArtifactParsers.h
 * @brief Persists vivo backup index facts into the shared android.db schema.
 *
 * The index proves which files the backup holds (original path, size, mtime,
 * content hash). It does not prove the payload bytes are readable: a backup may
 * declare ``xor_obfuscated``. This parser therefore writes:
 *
 *  - the device/backup identity into ``mobile_backup_manifest``;
 *  - one ``installed_packages`` row per app the backup captured;
 *  - a ``mobile_artifacts`` row per indexed file whose kind is not otherwise
 *    modelled, so every entry stays individually addressable and citable;
 *  - one ``android_source_coverage`` row per category, with status
 *    ``locked_or_unsupported`` when the payload is obfuscated.
 *
 * It never writes a row into ``sms_messages`` / ``contacts`` from a category
 * count. A count is not evidence.
 */

#pragma once
#ifndef VIVO_ARTIFACT_PARSERS_H
#define VIVO_ARTIFACT_PARSERS_H

#include <string>

class AndroidAnalysisDatabase;
class VivoBackupExtractor;

namespace vivo_artifacts {

struct VivoParseResult {
    int applications = 0;
    int fileRecords = 0;
    int categories = 0;
    int failures = 0;
};

VivoParseResult analyzeVivoBackup(VivoBackupExtractor& extractor,
                                  AndroidAnalysisDatabase& database);

}  // namespace vivo_artifacts

#endif  // VIVO_ARTIFACT_PARSERS_H
