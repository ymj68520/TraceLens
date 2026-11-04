/**
 * @file IosBackupExtractor.h
 * @brief IFileExtractor backend for an iTunes/Finder iOS logical backup.
 *
 * An iOS backup is not a container in the Android sense: it is a directory
 * holding ``Manifest.plist`` (device identity, encryption flag) and
 * ``Manifest.db`` (a SQLite index), plus shard directories named after the
 * first two hex characters of each file's SHA-1.
 *
 * ``Manifest.db``'s ``Files`` table maps ``fileID`` (the shard file name) to
 * ``domain`` + ``relativePath``. This backend resolves a logical path of the
 * form ``<domain>/<relativePath>`` (e.g. ``HomeDomain/Library/SMS/sms.db``)
 * through that index and copies the shard bytes to the caller's output path.
 *
 * The backup is never modified: shards are opened read-only and copied out.
 */

#pragma once
#ifndef IOS_BACKUP_EXTRACTOR_H
#define IOS_BACKUP_EXTRACTOR_H

#include <map>
#include <memory>
#include <string>
#include <vector>

#include "IFileExtractor.h"

struct sqlite3;

class IosBackupExtractor : public IFileExtractor {
public:
    /**
     * @param rootPath Either the backup directory itself (the one holding
     *                 Manifest.db) or a wrapper directory that contains it.
     */
    explicit IosBackupExtractor(const std::string& rootPath);
    ~IosBackupExtractor() override;

    bool initialize() override;
    bool extractFileByPath(const std::string& imageRelPath,
                           const std::string& outPath) override;
    std::vector<std::string> findPathsByFilename(
        const std::string& filename, std::size_t limit = 200) const override;
    std::vector<AndroidSourceProvenance> usedSourceProvenance() const override;

    /** True when Manifest.plist says the backup is encrypted. */
    bool encrypted() const { return encrypted_; }
    /** Reason initialize() failed, empty on success. */
    const std::string& error() const { return error_; }
    /** Resolved backup directory (valid after initialize()). */
    const std::string& backupRoot() const { return backupRoot_; }
    /** Device identity from Manifest.plist (empty values when unknown). */
    const std::map<std::string, std::string>& device() const { return device_; }
    /** Backup format version from Manifest.plist. */
    const std::string& backupVersion() const { return backupVersion_; }
    /** Number of entries recorded in Manifest.db's Files table. */
    std::size_t entryCount() const { return entryCount_; }
    /** Number of applications listed in Manifest.plist. */
    std::size_t applicationCount() const { return applicationCount_; }
    /** SHA-256 of Manifest.db, computed once during initialize(). */
    const std::string& manifestSha256() const { return manifestSha256_; }
    /** SHA-256 of Manifest.plist, computed once during initialize(). */
    const std::string& manifestPlistSha256() const { return manifestPlistSha256_; }

    /** Look up the shard path for a logical path; empty when absent. */
    std::string shardPathFor(const std::string& imageRelPath) const;
    /** Enumerate every logical path recorded for one domain. */
    std::vector<std::string> listDomain(const std::string& domain) const;
    /** Every domain present in Manifest.db, sorted. */
    std::vector<std::string> domains() const;

    /** Recognise a directory as an iOS backup without fully initializing. */
    static bool recognizes(const std::string& rootPath);

private:
    struct Entry {
        std::string fileId;
        std::string domain;
        std::string relativePath;
        long long size = 0;
    };

    std::string rootPath_;
    std::string backupRoot_;
    std::string error_;
    bool encrypted_ = false;
    bool initialized_ = false;
    std::string backupVersion_;
    std::string manifestSha256_;
    std::string manifestPlistSha256_;
    std::size_t entryCount_ = 0;
    std::size_t applicationCount_ = 0;
    std::map<std::string, std::string> device_;
    // Logical path ("<domain>/<relativePath>") -> shard metadata.
    std::map<std::string, Entry> index_;
    // Domain -> logical paths, for findPathsByFilename.
    std::map<std::string, std::vector<std::string>> byDomain_;
    mutable std::map<std::string, AndroidSourceProvenance> used_;

    bool resolveBackupRoot();
    bool loadManifestPlist();
    bool loadManifestIndex();
    void recordProvenance(const std::string& logicalPath, const Entry& entry,
                          std::size_t size, const std::string& sha256) const;
    static std::string normalizeLogical(const std::string& raw);
};

#endif // IOS_BACKUP_EXTRACTOR_H
