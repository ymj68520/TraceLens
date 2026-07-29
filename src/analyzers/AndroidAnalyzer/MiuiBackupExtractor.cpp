#include "MiuiBackupExtractor.h"

#include "AndroidBackupHeader.h"
#include "MiuiPathMap.h"

#include <filesystem>
#include <iostream>

namespace fs = std::filesystem;

MiuiBackupExtractor::MiuiBackupExtractor(const std::string& backupFolder)
    : folder_(backupFolder) {
}

void MiuiBackupExtractor::setBackupPassword(const std::string& password) {
    password_ = password;
}

bool MiuiBackupExtractor::initialize() {
    initialized_ = false;
    entryOwner_.clear();
    indexes_.clear();
    manifest_ = BackupMeta{};

    if (!parseMiuiManifest(folder_, manifest_)) {
        std::cerr << "MiuiBackupExtractor: no valid descript.xml in " << folder_ << std::endl;
        return false;
    }

    fs::path backupRoot;
    try {
        backupRoot = fs::canonical(folder_);
    } catch (const fs::filesystem_error& error) {
        std::cerr << "MiuiBackupExtractor: cannot resolve backup folder "
                  << folder_ << ": " << error.what() << std::endl;
        return false;
    }
    if (!fs::is_directory(backupRoot)) {
        std::cerr << "MiuiBackupExtractor: backup folder is not a directory: "
                  << backupRoot << std::endl;
        return false;
    }

    for (const auto& package : manifest_.packages) {
        const fs::path declaredPath(package.bakFile);
        if (declaredPath.empty() || declaredPath.is_absolute() || declaredPath.has_parent_path()) {
            std::cerr << "MiuiBackupExtractor: unsafe backup filename for "
                      << package.packageName << ": " << package.bakFile << std::endl;
            continue;
        }

        const fs::path candidate = backupRoot / declaredPath;
        std::error_code statusError;
        if (fs::is_symlink(fs::symlink_status(candidate, statusError)) || statusError) {
            std::cerr << "MiuiBackupExtractor: symlinked or unreadable backup file for "
                      << package.packageName << ": " << declaredPath << std::endl;
            continue;
        }

        fs::path bakPath;
        try {
            bakPath = fs::canonical(candidate);
        } catch (const fs::filesystem_error&) {
            std::cerr << "MiuiBackupExtractor: backup file not found for "
                      << package.packageName << ": " << declaredPath << std::endl;
            continue;
        }
        if (bakPath.parent_path() != backupRoot || !fs::is_regular_file(bakPath)) {
            std::cerr << "MiuiBackupExtractor: backup path escapes folder for "
                      << package.packageName << ": " << declaredPath << std::endl;
            continue;
        }

        AndroidBackupHeader header;
        if (!parseAndroidBackupHeader(bakPath.string(), header)) {
            std::cerr << "MiuiBackupExtractor: invalid Android Backup stream: "
                      << bakPath << std::endl;
            continue;
        }
        if (header.encryption != BackupEncryption::None) {
            std::cerr << "MiuiBackupExtractor: encrypted backup deferred for "
                      << package.packageName << " (" << header.encMarker << ')' << std::endl;
            continue;
        }
        if (header.compression != 0 && header.compression != 1) {
            std::cerr << "MiuiBackupExtractor: unsupported compression "
                      << header.compression << " for " << package.packageName << std::endl;
            continue;
        }

        auto index = std::make_unique<TarIndex>();
        if (!index->build(bakPath.string(), header.payloadOffset, header.compression == 1)) {
            std::cerr << "MiuiBackupExtractor: failed to index " << bakPath << std::endl;
            continue;
        }

        TarIndex* owner = index.get();
        const std::string expectedPrefix = "apps/" + package.packageName + "/";
        for (const auto& entry : index->entries()) {
            if (entry.first.rfind(expectedPrefix, 0) == 0) {
                entryOwner_.emplace(entry.first, owner);
            }
        }
        indexes_.push_back(std::move(index));
    }

    initialized_ = !indexes_.empty();
    return initialized_;
}

bool MiuiBackupExtractor::extractFileByPath(const std::string& imageRelPath,
                                            const std::string& outPath) {
    if (!initialized_) {
        return false;
    }

    std::string memberName = analyzerPathToTarMember(imageRelPath);
    auto owner = entryOwner_.find(memberName);
    if (owner == entryOwner_.end()) {
        owner = entryOwner_.find(imageRelPath);
    }
    if (owner == entryOwner_.end()) {
        return false;
    }

    const std::string& resolvedMember = entryOwner_.find(memberName) != entryOwner_.end()
        ? memberName
        : imageRelPath;
    TarEntry entry;
    if (!owner->second->find(resolvedMember, entry)) {
        return false;
    }

    try {
        const fs::path output(outPath);
        const fs::path parent = output.parent_path();
        if (!parent.empty()) {
            fs::create_directories(parent);
        }
    } catch (const fs::filesystem_error& error) {
        std::cerr << "MiuiBackupExtractor: cannot create output parent for "
                  << outPath << ": " << error.what() << std::endl;
        return false;
    }

    return owner->second->readEntry(entry, outPath);
}
