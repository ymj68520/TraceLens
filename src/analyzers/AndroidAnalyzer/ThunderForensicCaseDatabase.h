#pragma once

#include <cstddef>
#include <filesystem>
#include <map>
#include <set>
#include <string>

class AndroidAnalysisDatabase;

// ThunderForensic project folders also carry the case database the tool
// builds while parsing: `data/evidence_<n>_<kind>` SQLite files, one table
// each, with the artifacts already flattened into rows (SMS, call logs,
// contacts, WiFi, IM messages, file inventory, ...).
//
// The tar's PhoneData members do not always cover them — the vivo sample has
// no PhoneData/smss.json but 2079 SMS rows in data/evidence_1_sms — so the
// generic adapter reads both layers. Each case row names the container member
// it was parsed from (`src_file_path`); rows whose member the container layer
// already produced are skipped so the same extraction is never counted twice.
// Columns are matched by name with a small alias set; anything unrecognized
// still lands in mobile_artifacts with its full row JSON.
//
// `projectRoot` is the ThunderForensic project directory (not the tar).
struct ThunderForensicCaseStats {
    std::size_t databases = 0;
    std::size_t rows = 0;
    std::size_t skippedDuplicateRows = 0;
    std::size_t truncatedDatabases = 0;
    bool found = false;
};

/// `coveredMembers` maps a mobile_artifacts kind to the container member paths
/// the tar layer already parsed with at least one row.
ThunderForensicCaseStats analyzeThunderForensicCaseDatabases(
    const std::filesystem::path& projectRoot, AndroidAnalysisDatabase& output,
    const std::map<std::string, std::set<std::string>>& coveredMembers,
    std::size_t maxRowsPerDatabase = 50000);
