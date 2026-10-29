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
    // True when the row was synthesized from an on-disk .bak that descript.xml
    // omitted. Such rows carry no manifest-declared size/state fields.
    bool discoveredOnDisk = false;
};

struct BackupMeta {
    std::string device;            // e.g. "cepheus"
    std::string miuiVersion;       // e.g. "V12.5.6.0.RFACNXM"
    uint64_t date = 0;             // epoch ms
    uint64_t totalSize = 0;
    std::vector<BackupPackage> packages;
    std::string sourceFolder;
    // True when at least one package was recovered from disk because
    // descript.xml did not list it.
    bool recoveredMissingPackages = false;
};

// Parse <backupFolder>/descript.xml. Returns false if the file is missing/malformed.
bool parseMiuiManifest(const std::string& backupFolder, BackupMeta& out);

// Physical layout of a MIUI acquisition. A full export is usually two sibling
// trees - miui_backup/ (descript.xml + *.bak) and sdcard/ (external storage) -
// so the folder a caller selects may be the parent of the manifest, not the
// manifest's own directory.
struct MiuiBackupLayout {
    std::string backupRoot;    // directory holding descript.xml and the .bak files
    std::string externalRoot;  // sibling sdcard tree; empty when absent
    bool nested = false;       // backupRoot sits below the requested directory
};

// Resolve a user-selected path (parent folder, miui_backup folder, or a folder
// that itself holds descript.xml) to the concrete layout. Returns false when no
// descript.xml is reachable.
bool resolveMiuiBackupLayout(const std::string& requestedPath, MiuiBackupLayout& out);

// Append one package row per .bak file in backupFolder that the manifest does
// not already reference. A directory-only manifest (one that lists a single
// package while dozens of .bak files sit beside it) otherwise hides almost the
// whole acquisition. Package names come from the "<display>(<package>).bak"
// filename convention, falling back to the "MIUI BACKUP" header. Returns true
// when the folder can be enumerated; an unmatched .bak stays in the result with
// an empty packageName so the caller can report it instead of dropping it.
bool recoverUnlistedBackupPackages(const std::string& backupFolder, BackupMeta& manifest);
