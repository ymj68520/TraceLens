#include "ZipArchiveExtractor.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <fstream>
#include <filesystem>
#include <vector>
#include <algorithm>

namespace fs = std::filesystem;

ZipArchiveExtractor::ZipArchiveExtractor(const std::string& zipPath)
    : zipPath_(zipPath) {
}

ZipArchiveExtractor::~ZipArchiveExtractor() {
#ifdef HAVE_LIBZIP
    if (archive_) {
        // NOTE: we deliberately use zip_discard() instead of zip_close().
        // DuckX bundles a third-party "kuba-zip" library that also exports a
        // symbol named `zip_close` (and `zip_open`) with a different ABI. Since
        // DuckX is statically linked into the executable, its `zip_close`
        // shadows libzip's, so calling zip_close() here would dispatch to the
        // wrong implementation. zip_discard() is unique to libzip; for a
        // read-only archive it simply frees the handle without committing.
        zip_discard(archive_);
        archive_ = nullptr;
    }
#endif
}

#ifdef HAVE_LIBZIP

std::string ZipArchiveExtractor::normalizeRelPath(const std::string& imageRelPath) {
    std::string p = imageRelPath;
    std::replace(p.begin(), p.end(), '\\', '/');
    while (!p.empty() && p[0] == '/') {
        p.erase(p.begin());
    }
    return p;
}

int ZipArchiveExtractor::locateEntry(const std::string& imageRelPath) const {
    if (!archive_) {
        return -1;
    }

    std::string rel = normalizeRelPath(imageRelPath);

    // 1. Exact match.
    zip_int64_t idx = zip_name_locate(archive_, rel.c_str(), 0);
    if (idx >= 0) {
        return static_cast<int>(idx);
    }

    // 2. Strip a leading "data/" — the analyzer issues paths like
    //    "data/data/com.foo/..." which already match the zip layout, but be
    //    defensive in case a caller passes "/data/..." that should map to a
    //    zip entry lacking the leading "data/".
    const std::string prefix = "data/";
    if (rel.rfind(prefix, 0) == 0) {
        idx = zip_name_locate(archive_, rel.substr(prefix.size()).c_str(), 0);
        if (idx >= 0) {
            return static_cast<int>(idx);
        }
    }

    // 3. Prepend "data/" in case the caller passed a bare app path.
    idx = zip_name_locate(archive_, ("data/" + rel).c_str(), 0);
    if (idx >= 0) {
        return static_cast<int>(idx);
    }

    return -1;
}

bool ZipArchiveExtractor::initialize() {
    if (zipPath_.empty()) {
        std::cerr << "ZipArchiveExtractor: zip path is empty" << std::endl;
        return false;
    }
    if (!fs::exists(zipPath_)) {
        std::cerr << "ZipArchiveExtractor: archive not found: " << zipPath_ << std::endl;
        return false;
    }

    // IMPORTANT: do not call zip_open() here. DuckX statically links a
    // third-party "kuba-zip" library that exports a colliding `zip_open`
    // symbol with an incompatible signature, which shadows libzip's. We open
    // via libzip's source API instead (zip_source_file_create +
    // zip_open_from_source) — those symbols are unique to libzip and resolve
    // correctly.
    zip_error_t error;
    zip_error_init(&error);

    zip_source_t* source = zip_source_file_create(zipPath_.c_str(), 0, -1, &error);
    if (!source) {
        std::cerr << "ZipArchiveExtractor: failed to create source for " << zipPath_
                  << ": " << zip_error_strerror(&error) << std::endl;
        zip_error_fini(&error);
        AuditLog::instance().log("SYSTEM", "ZIP_OPEN_FAILED", zipPath_);
        return false;
    }

    archive_ = zip_open_from_source(source, ZIP_RDONLY, &error);
    if (!archive_) {
        std::cerr << "ZipArchiveExtractor: failed to open " << zipPath_
                  << ": " << zip_error_strerror(&error) << std::endl;
        // open_from_source only takes ownership of source on success.
        zip_source_free(source);
        zip_error_fini(&error);
        AuditLog::instance().log("SYSTEM", "ZIP_OPEN_FAILED", zipPath_);
        return false;
    }
    zip_error_fini(&error);

    initialized_ = true;
    std::cout << "ZipArchiveExtractor initialized: " << zipPath_
              << " (" << zip_get_num_entries(archive_, 0) << " entries)" << std::endl;
    AuditLog::instance().log("SYSTEM", "ZIP_INIT", "Zip extractor: " + zipPath_);
    return true;
}

bool ZipArchiveExtractor::extractFileByPath(const std::string& imageRelPath,
                                            const std::string& outPath) {
    if (!initialized_ || !archive_) {
        std::cerr << "ZipArchiveExtractor: not initialized" << std::endl;
        return false;
    }

    int idx = locateEntry(imageRelPath);
    if (idx < 0) {
        return false;  // not present; callers handle absence gracefully
    }

    // Skip directory entries (they end with '/').
    zip_stat_t st;
    zip_stat_init(&st);
    if (zip_stat_index(archive_, static_cast<zip_uint64_t>(idx), 0, &st) != 0) {
        std::cerr << "ZipArchiveExtractor: zip_stat_index failed for " << imageRelPath << std::endl;
        return false;
    }
    if (st.name && std::string(st.name).back() == '/') {
        return false;  // directory entry, not a file
    }

    zip_file_t* zf = zip_fopen_index(archive_, static_cast<zip_uint64_t>(idx), 0);
    if (!zf) {
        std::cerr << "ZipArchiveExtractor: zip_fopen_index failed for " << imageRelPath
                  << ": " << zip_strerror(archive_) << std::endl;
        return false;
    }

    try {
        const fs::path out(outPath);
        fs::path parent = out.parent_path();
        if (!parent.empty() && !fs::exists(parent)) {
            fs::create_directories(parent);
        }
    } catch (const std::exception& e) {
        std::cerr << "ZipArchiveExtractor: cannot create output dir for " << outPath
                  << ": " << e.what() << std::endl;
        zip_fclose(zf);
        return false;
    }

    std::ofstream ofs(outPath, std::ios::binary | std::ios::trunc);
    if (!ofs) {
        std::cerr << "ZipArchiveExtractor: cannot open output: " << outPath << std::endl;
        zip_fclose(zf);
        return false;
    }

    constexpr zip_uint64_t BUF = 1 << 20;  // 1 MiB
    std::vector<char> buffer(BUF);
    zip_uint64_t remaining = (st.valid & ZIP_STAT_SIZE) ? st.size : 0;
    bool sizeKnown = (st.valid & ZIP_STAT_SIZE) != 0;

    while (true) {
        zip_int64_t n = zip_fread(zf, buffer.data(), BUF);
        if (n < 0) {
            std::cerr << "ZipArchiveExtractor: read error for " << imageRelPath << std::endl;
            ofs.close();
            zip_fclose(zf);
            fs::remove(outPath);
            return false;
        }
        if (n == 0) {
            break;
        }
        ofs.write(buffer.data(), static_cast<std::streamsize>(n));
        if (sizeKnown) {
            remaining -= static_cast<zip_uint64_t>(n);
            if (remaining == 0) {
                break;
            }
        }
    }

    ofs.flush();
    bool ok = ofs.good();
    ofs.close();
    zip_fclose(zf);

    if (!ok) {
        fs::remove(outPath);
        return false;
    }
    return true;
}

#else  // !HAVE_LIBZIP

bool ZipArchiveExtractor::initialize() {
    std::cerr << "ZipArchiveExtractor: built without libzip support (HAVE_LIBZIP not defined). "
              << "Install libzip and rebuild to read zip archives." << std::endl;
    (void)zipPath_;
    return false;
}

bool ZipArchiveExtractor::extractFileByPath(const std::string&, const std::string&) {
    return false;
}

#endif  // HAVE_LIBZIP
