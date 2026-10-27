#pragma once
#include <filesystem>
class HarmonyBackupExtractor;
class AndroidAnalysisDatabase;
class IndexedMobileSource;
bool analyzeMobileSource(IndexedMobileSource&, AndroidAnalysisDatabase&, const std::filesystem::path&);
// Writes into the existing task-owned mobile result database.
bool analyzeHarmonyBackup(HarmonyBackupExtractor&, AndroidAnalysisDatabase&,
                          const std::filesystem::path& temporaryRoot);
