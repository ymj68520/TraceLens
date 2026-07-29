// MiuiBackupManifest.h
// Parse a MIUI backup's descript.xml into a structured manifest.

#pragma once
#include <string>
#include <vector>
#include <cstdint>

struct BackupPackage {
    std::string packageName;
    std::string bakFile;     // UTF-8 filename, e.g. "短信设置(com.android.mms).bak"
    int bakType = 0;
    int error = 0;
    int state = 0;
    uint64_t pkgSize = 0;
    uint64_t sdSize = 0;
};

struct BackupMeta {
    std::string device;            // e.g. "cepheus"
    std::string miuiVersion;       // e.g. "V12.5.6.0.RFACNXM"
    uint64_t date = 0;             // epoch ms
    uint64_t totalSize = 0;
    std::vector<BackupPackage> packages;
    std::string sourceFolder;
};

// Parse <backupFolder>/descript.xml. Returns false if the file is missing/malformed.
bool parseMiuiManifest(const std::string& backupFolder, BackupMeta& out);
