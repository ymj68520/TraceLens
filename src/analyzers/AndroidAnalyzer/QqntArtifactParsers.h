#pragma once

class AndroidAnalysisDatabase;
class MiuiBackupExtractor;

// Persists QQ/QQNT artifacts found in a MIUI backup. Unknown binary formats are
// inventoried as recognized evidence instead of being misreported as decoded data.
bool persistQqntBackupAnalysis(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);
