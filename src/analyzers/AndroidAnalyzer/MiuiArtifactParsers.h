#pragma once

#include <string>

class AndroidAnalysisDatabase;
class MiuiBackupExtractor;

// Returns true for a primary WeChat SQLCipher database stored in a MIUI
// backup's r/MicroMsg or db subtree. Sidecars are intentionally excluded.
bool isMiuiWeChatDatabaseMember(const std::string& memberName);

// Writes the backup manifest row and one installed_apps row per manifest package.
bool writeMiuiManifest(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);

// Inventories every SQLite database entry under apps/<package>/db/.
// Each readable database produces one row per user table; unreadable or
// encrypted-looking sources produce a failure row instead of being omitted.
bool writeAppDbInventory(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);

// Persists MIUI manifest and database inventory in one transaction so an
// initialization failure cannot leave a partial, apparently complete result.
bool persistMiuiBackupAnalysis(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);

// Adds QQ/QQNT evidence inventory and validated structured artifacts.
bool persistQqntBackupAnalysis(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);
