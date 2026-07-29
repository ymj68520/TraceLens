#include "MiuiBackupExtractor.h"

#include "AndroidBackupHeader.h"
#include "MiuiPathMap.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
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
    packageFailures_.clear();
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
            packageFailures_.push_back(
                {package.packageName, package.bakFile, "parse_error"});
            continue;
        }
        if (header.encryption != BackupEncryption::None) {
            std::cerr << "MiuiBackupExtractor: encrypted backup deferred for "
                      << package.packageName << " (" << header.encMarker << ')' << std::endl;
            packageFailures_.push_back(
                {package.packageName, package.bakFile, "encrypted_locked"});
            continue;
        }
        if (header.compression != 0 && header.compression != 1) {
            std::cerr << "MiuiBackupExtractor: unsupported compression "
                      << header.compression << " for " << package.packageName << std::endl;
            packageFailures_.push_back(
                {package.packageName, package.bakFile, "parse_error"});
            continue;
        }

        auto index = std::make_unique<TarIndex>();
        if (!index->build(bakPath.string(), header.payloadOffset, header.compression == 1)) {
            std::cerr << "MiuiBackupExtractor: failed to index " << bakPath << std::endl;
            packageFailures_.push_back(
                {package.packageName, package.bakFile, "parse_error"});
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
            std::error_code permissionError;
            fs::permissions(parent, fs::perms::owner_all,
                            fs::perm_options::replace, permissionError);
            if (permissionError) {
                return false;
            }
        }
        std::ofstream privateOutput(output, std::ios::binary | std::ios::trunc);
        if (!privateOutput) {
            return false;
        }
        privateOutput.close();
        std::error_code permissionError;
        fs::permissions(output, fs::perms::owner_read | fs::perms::owner_write,
                        fs::perm_options::replace, permissionError);
        if (permissionError) {
            fs::remove(output, permissionError);
            return false;
        }
    } catch (const fs::filesystem_error& error) {
        std::cerr << "MiuiBackupExtractor: cannot create output parent for "
                  << outPath << ": " << error.what() << std::endl;
        return false;
    }

    return owner->second->readEntry(entry, outPath);
}

void MiuiBackupExtractor::enumerateEntries(const EntryVisitor& visitor) const {
    if (!initialized_ || !visitor) {
        return;
    }

    for (const auto& package : manifest_.packages) {
        const std::string packagePrefix = "apps/" + package.packageName + "/";
        std::vector<std::string> members;
        for (const auto& entry : entryOwner_) {
            if (entry.first.rfind(packagePrefix, 0) == 0) {
                members.push_back(entry.first);
            }
        }
        std::sort(members.begin(), members.end());
        for (const auto& member : members) {
            visitor(member, package.bakFile);
        }
    }
}

bool MiuiBackupExtractor::extractTarMember(const std::string& memberName,
                                           const std::string& outPath) const {
    if (!initialized_) {
        return false;
    }

    const auto owner = entryOwner_.find(memberName);
    if (owner == entryOwner_.end()) {
        return false;
    }

    TarEntry entry;
    if (!owner->second->find(memberName, entry)) {
        return false;
    }

    try {
        const fs::path output(outPath);
        const fs::path parent = output.parent_path();
        if (!parent.empty()) {
            fs::create_directories(parent);
            std::error_code permissionError;
            fs::permissions(parent, fs::perms::owner_all,
                            fs::perm_options::replace, permissionError);
            if (permissionError) {
                return false;
            }
        }
        std::ofstream privateOutput(output, std::ios::binary | std::ios::trunc);
        if (!privateOutput) {
            return false;
        }
        privateOutput.close();
        std::error_code permissionError;
        fs::permissions(output, fs::perms::owner_read | fs::perms::owner_write,
                        fs::perm_options::replace, permissionError);
        if (permissionError) {
            fs::remove(output, permissionError);
            return false;
        }
    } catch (const fs::filesystem_error& error) {
        std::cerr << "MiuiBackupExtractor: cannot create output parent for "
                  << outPath << ": " << error.what() << std::endl;
        return false;
    }

    return owner->second->readEntry(entry, outPath);
}

bool MiuiBackupExtractor::entrySize(const std::string& memberName, uint64_t& size) const {
    size = 0;
    const auto owner = entryOwner_.find(memberName);
    if (!initialized_ || owner == entryOwner_.end()) {
        return false;
    }

    TarEntry entry;
    if (!owner->second->find(memberName, entry)) {
        return false;
    }
    size = entry.size;
    return true;
}
