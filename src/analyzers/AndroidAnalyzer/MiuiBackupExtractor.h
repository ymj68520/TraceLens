#pragma once
#ifndef MIUI_BACKUP_EXTRACTOR_H
#define MIUI_BACKUP_EXTRACTOR_H

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>

#include "IFileExtractor.h"
#include "MiuiBackupManifest.h"
#include "TarIndex.h"

/**
 * @brief IFileExtractor backend for an offline MIUI backup directory.
 *
 * The directory must contain descript.xml and the .bak files referenced by its
 * package entries. Each supported, unencrypted Android Backup payload is
 * indexed once, then individual application artifacts are copied on demand.
 */
class MiuiBackupExtractor : public IFileExtractor {
public:
    explicit MiuiBackupExtractor(const std::string& backupFolder);

    // Stored for Phase 2 AES support. Phase 1 rejects encrypted payloads.
    void setBackupPassword(const std::string& password);

    bool initialize() override;
    bool extractFileByPath(const std::string& imageRelPath,
                           const std::string& outPath) override;

    const BackupMeta& manifest() const { return manifest_; }

private:
    std::string folder_;
    std::string password_;
    BackupMeta manifest_;
    std::vector<std::unique_ptr<TarIndex>> indexes_;
    std::unordered_map<std::string, TarIndex*> entryOwner_;
    bool initialized_ = false;
};

#endif  // MIUI_BACKUP_EXTRACTOR_H
