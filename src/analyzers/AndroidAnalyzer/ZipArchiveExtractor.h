/**
 * @file ZipArchiveExtractor.h
 * @brief IFileExtractor backend that reads individual files out of a zip
 *        archive on demand, without extracting the whole archive to disk.
 *
 * Android logical extractions are frequently packaged as a single large
 * `Image.zip` (e.g. the 4th Pangu-Stone-Cup final's phone dumps). Extracting
 * such a 9-10 GB archive fully is wasteful when only a handful of databases
 * are needed. This backend opens the archive once with libzip and serves each
 * requested image-relative path via zip_fopen.
 *
 * Compiled only when libzip is available (HAVE_LIBZIP / CMake flag). When
 * libzip is absent, the class is still declared (so call sites compile) but
 * initialize() always fails.
 */

#pragma once
#ifndef ZIP_ARCHIVE_EXTRACTOR_H
#define ZIP_ARCHIVE_EXTRACTOR_H

#include <string>
#include "IFileExtractor.h"

#ifdef HAVE_LIBZIP
#include <zip.h>
#endif

class ZipArchiveExtractor : public IFileExtractor {
public:
    explicit ZipArchiveExtractor(const std::string& zipPath);
    ~ZipArchiveExtractor() override;

    ZipArchiveExtractor(const ZipArchiveExtractor&) = delete;
    ZipArchiveExtractor& operator=(const ZipArchiveExtractor&) = delete;

    bool initialize() override;
    bool extractFileByPath(const std::string& imageRelPath,
                           const std::string& outPath) override;

    const std::string& zipPath() const { return zipPath_; }

private:
    std::string zipPath_;
    bool initialized_ = false;

#ifdef HAVE_LIBZIP
    zip_t* archive_ = nullptr;

    /**
     * @brief Look up imageRelPath inside the archive. Tries exact match, then
     *        leading-slash variants, then a leading-"data/" variant, to absorb
     *        the path-shape differences between TSK-style paths and the
     *        relative paths actually stored in logical-extraction zips.
     * @return non-negative zip index on hit, -1 on miss.
     */
    int locateEntry(const std::string& imageRelPath) const;

    static std::string normalizeRelPath(const std::string& imageRelPath);
#endif
};

#endif // ZIP_ARCHIVE_EXTRACTOR_H
