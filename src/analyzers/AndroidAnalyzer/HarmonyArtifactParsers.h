#pragma once
#include <filesystem>
class HarmonyBackupExtractor;
class AndroidAnalysisDatabase;
// Writes into the existing task-owned mobile result database.
bool analyzeHarmonyBackup(HarmonyBackupExtractor&, AndroidAnalysisDatabase&,
                          const std::filesystem::path& temporaryRoot);
