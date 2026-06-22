/**
 * @file LogicalDirExtractor.h
 * @brief IFileExtractor backend for an already-extracted Android data directory.
 *
 * Many Android forensic acquisitions (notably ADB logical/file-system pulls and
 * the `Image.zip` dumps from this project's 4th Pangu-Stone-Cup final) are NOT
 * block-level images. They are a plain tree of files rooted at an Android
 * `data/` directory. TSK cannot open them and there is no _raw.db.
 *
 * This backend resolves image-relative paths (e.g.
 * "data/data/com.foo/databases/foo.db") directly against a directory root using
 * std::filesystem, then copies the file to the requested output path. It never
 * touches TSK.
 */

#pragma once
#ifndef LOGICAL_DIR_EXTRACTOR_H
#define LOGICAL_DIR_EXTRACTOR_H

#include <string>
#include "IFileExtractor.h"

class LogicalDirExtractor : public IFileExtractor {
public:
    /**
     * @param rootDir Absolute or relative path to the extracted Android data
     *                root (the directory that *contains* `data/`, or whose
     *                contents begin with `data/`). A leading-slash image path
     *                is tolerated.
     */
    explicit LogicalDirExtractor(const std::string& rootDir);

    bool initialize() override;
    bool extractFileByPath(const std::string& imageRelPath,
                           const std::string& outPath) override;

    const std::string& rootDir() const { return rootDir_; }

private:
    std::string rootDir_;
    bool initialized_ = false;

    /**
     * @brief Normalize an image-relative path: strip leading '/', collapse
     *        backslashes to forward slashes.
     */
    static std::string normalizeRelPath(const std::string& imageRelPath);

    /**
     * @brief Resolve relPath under rootDir_, returning an empty path if the
     *        result escapes rootDir_ (e.g. via "..") or does not exist.
     */
    std::string resolveSafe(const std::string& relPath) const;
};

#endif // LOGICAL_DIR_EXTRACTOR_H
