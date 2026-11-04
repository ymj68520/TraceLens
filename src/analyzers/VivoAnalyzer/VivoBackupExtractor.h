/**
 * @file VivoBackupExtractor.h
 * @brief IFileExtractor backend for a vivo (iQOO) PC-assistant backup.
 *
 * A vivo backup is a directory holding ``.backup`` (a JSON header) and a
 * LevelDB ``db/`` index, plus one payload file per item named by its SHA-1.
 * The index is authoritative: a key of the form
 * ``<category>_<7-digit index>_<sha1>`` maps a content hash to the original
 * on-device filename, size and mtime.
 *
 * Reading LevelDB from C++ would need a new third-party dependency, and the
 * Python preflight already parses the index with a proven library. So this
 * extractor consumes the preflight's normalised JSON (``index.json``) and only
 * does what C++ must do itself: resolve a logical path to its payload file and
 * copy the bytes.
 *
 * Two honesty rules are enforced here:
 *  - a payload marked obfuscated is copied but reported as unreadable, never
 *    passed to a SQLite parser as if it were a database;
 *  - a missing payload file is reported as missing, not as an empty artifact.
 */

#pragma once
#ifndef VIVO_BACKUP_EXTRACTOR_H
#define VIVO_BACKUP_EXTRACTOR_H

#include <cstddef>
#include <map>
#include <string>
#include <vector>

#include "IFileExtractor.h"

struct sqlite3;

class VivoBackupExtractor : public IFileExtractor {
public:
    /**
     * @param rootPath   The backup directory (holding ``.backup`` and ``db/``),
     *                   or a wrapper that contains it.
     * @param indexPath  Normalised index JSON produced by the Python preflight.
     *                   When empty, the extractor looks for ``index.json`` in
     *                   the backup directory.
     */
    explicit VivoBackupExtractor(const std::string& rootPath,
                                 const std::string& indexPath = "");
    ~VivoBackupExtractor() override;

    bool initialize() override;
    bool extractFileByPath(const std::string& imageRelPath,
                           const std::string& outPath) override;
    std::vector<std::string> findPathsByFilename(
        const std::string& filename, std::size_t limit = 200) const override;
    std::vector<AndroidSourceProvenance> usedSourceProvenance() const override;

    const std::string& error() const { return error_; }
    const std::string& backupRoot() const { return backupRoot_; }
    const std::string& model() const { return model_; }
    const std::string& backupVersion() const { return backupVersion_; }
    long long backupTimeMs() const { return backupTimeMs_; }
    bool obfuscated() const { return obfuscated_; }
    /** True when the payload could be decoded (obfuscation reversed). */
    bool payloadReadable() const { return obfuscated_ ? deobfuscationSucceeded_ : true; }
    std::size_t itemCount() const { return items_.size(); }
    std::size_t applicationCount() const { return applicationCount_; }

    /** All indexed items, for the artifact parser to walk. */
    struct Item {
        std::string category;
        std::string hash;
        std::string originalPath;
        long long size = 0;
        long long mtimeMs = 0;
        std::string appName;
        std::string package;
        std::string versionName;
    };
    const std::vector<Item>& items() const { return items_; }

    /** Recognise a directory as a vivo backup without fully initializing. */
    static bool recognizes(const std::string& rootPath);

private:
    std::string rootPath_;
    std::string indexPath_;
    std::string backupRoot_;
    std::string error_;
    std::string model_;
    std::string backupVersion_;
    long long backupTimeMs_ = 0;
    bool obfuscated_ = false;
    bool deobfuscationSucceeded_ = false;
    bool initialized_ = false;
    std::size_t applicationCount_ = 0;
    std::vector<Item> items_;
    std::map<std::string, std::size_t> byOriginalPath_;
    mutable std::map<std::string, AndroidSourceProvenance> used_;

    bool resolveBackupRoot();
    bool loadIndex();
    bool loadHeader();
    void recordProvenance(const Item& item, std::size_t size, const std::string& sha256) const;
    static std::string normalizeLogical(const std::string& raw);
};

#endif  // VIVO_BACKUP_EXTRACTOR_H
