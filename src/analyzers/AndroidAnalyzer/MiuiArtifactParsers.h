#pragma once

class AndroidAnalysisDatabase;
class MiuiBackupExtractor;

// Writes the backup manifest row and one installed_apps row per manifest package.
bool writeMiuiManifest(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);

// Inventories every SQLite database entry under apps/<package>/db/.
// Each readable database produces one row per user table; unreadable or
// encrypted-looking sources produce a failure row instead of being omitted.
bool writeAppDbInventory(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);
