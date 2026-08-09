#pragma once

class AndroidAnalysisDatabase;
class MiuiBackupExtractor;

// Persists WeChat (com.tencent.mm) artifacts found in a MIUI backup. Like the
// QQNT counterpart, proprietary binary formats (MMKV, SQLCipher EnMicroMsg.db)
// are inventoried as recognized evidence rather than being misreported as
// decoded data; only validated structured sources (shared-prefs XML, plaintext
// SQLite tables) contribute recovered records.
bool persistWechatBackupAnalysis(MiuiBackupExtractor& src, AndroidAnalysisDatabase& db);
