#pragma once

#include <filesystem>

class OppoBackupExtractor;
class AndroidAnalysisDatabase;

// Parses a ThunderForensic (雷电手机快取) OPPO/Android extraction container and
// persists every PhoneData artifact into the vendor-neutral mobile backup
// tables plus the standard Android artifact tables (installed_apps, wifi,
// contacts, call_logs, sms_messages, device_identifiers).
bool analyzeOppoBackup(OppoBackupExtractor& source, AndroidAnalysisDatabase& output);
