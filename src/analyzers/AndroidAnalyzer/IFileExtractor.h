/**
 * @file IFileExtractor.h
 * @brief Abstract interface for extracting files from a forensic data source.
 *
 * AndroidAnalyzer originally depended on FileExtractor, which is hardwired to
 * The Sleuth Kit (TSK): it resolves a path to an inode via the _raw.db metadata
 * table and then reads the bytes out of a block-level disk image.
 *
 * Real-world Android extractions — e.g. an ADB logical/file-system pull packaged
 * as an `Image.zip`, or the unzipped `data/` directory tree — are NOT block
 * images. They cannot be opened by TSK and have no _raw.db. To analyze them we
 * need alternate backends that resolve an image-relative path
 * (e.g. "data/data/com.foo/databases/foo.db") against either an extracted
 * directory or a zip archive, without ever touching TSK.
 *
 * IFileExtractor decouples AndroidAnalyzer from the storage backend. All nine
 * call sites in the AndroidAnalyzer module go through a single method,
 * `extractFileByPath(imageRelPath, outPath)`, so introducing this interface
 * lets us swap backends without touching any parsing logic.
 */

#pragma once
#ifndef IFILE_EXTRACTOR_H
#define IFILE_EXTRACTOR_H

#include <string>

/**
 * @brief Abstract file-extraction backend.
 *
 * Contract: given an image-relative path (no leading slash required; leading
 * slashes are tolerated), locate the corresponding file in the data source and
 * copy/extract its full contents to `outPath` on the local filesystem. The
 * output file must be readable with ordinary std::ifstream after the call.
 *
 * Implementations:
 *  - FileExtractor        : TSK block image + _raw.db (legacy path)
 *  - LogicalDirExtractor  : an already-extracted Android `data/` directory
 *  - ZipArchiveExtractor  : a logical extraction packaged as Image.zip (libzip)
 */
class IFileExtractor {
public:
    virtual ~IFileExtractor() = default;

    /**
     * @brief Open the underlying data source (image / directory / archive).
     * @return true if the source could be opened.
     */
    virtual bool initialize() = 0;

    /**
     * @brief Extract one file by its image-relative path.
     * @param imageRelPath Path inside the data source, e.g.
     *                     "data/data/com.foo/databases/foo.db". A leading '/'
     *                     is tolerated and stripped.
     * @param outPath      Local filesystem path to write the file contents to.
     *                     Parent directories need not exist beforehand.
     * @return true if the file was found and written.
     */
    virtual bool extractFileByPath(const std::string& imageRelPath,
                                   const std::string& outPath) = 0;
};

#endif // IFILE_EXTRACTOR_H
