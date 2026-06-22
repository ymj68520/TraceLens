#include "LogicalDirExtractor.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <filesystem>
#include <algorithm>

namespace fs = std::filesystem;

LogicalDirExtractor::LogicalDirExtractor(const std::string& rootDir)
    : rootDir_(rootDir) {
}

std::string LogicalDirExtractor::normalizeRelPath(const std::string& imageRelPath) {
    std::string p = imageRelPath;
    // Tolerate Windows-style separators
    std::replace(p.begin(), p.end(), '\\', '/');
    // Strip leading slashes (Android logical pulls use relative "data/...")
    while (!p.empty() && p[0] == '/') {
        p.erase(p.begin());
    }
    return p;
}

std::string LogicalDirExtractor::resolveSafe(const std::string& relPath) const {
    if (relPath.empty()) {
        return {};
    }
    fs::path root;
    try {
        root = fs::weakly_canonical(rootDir_);
    } catch (...) {
        // Root may not exist yet; fall back to absolute/lexically-normal form.
        root = fs::absolute(rootDir_).lexically_normal();
    }

    fs::path candidate = root / relPath;
    try {
        candidate = fs::weakly_canonical(candidate);
    } catch (...) {
        candidate = fs::absolute(candidate).lexically_normal();
    }

    // Path-traversal guard: resolved path must live under root.
    std::string rootStr = root.string();
    std::string candStr = candidate.string();
    if (candStr.rfind(rootStr, 0) != 0) {
        std::cerr << "LogicalDirExtractor: path escapes root: " << relPath << std::endl;
        return {};
    }

    if (!fs::exists(candidate) || !fs::is_regular_file(candidate)) {
        return {};
    }
    return candidate.string();
}

bool LogicalDirExtractor::initialize() {
    if (rootDir_.empty()) {
        std::cerr << "LogicalDirExtractor: root directory is empty" << std::endl;
        return false;
    }
    if (!fs::exists(rootDir_)) {
        std::cerr << "LogicalDirExtractor: root directory not found: " << rootDir_ << std::endl;
        return false;
    }
    if (!fs::is_directory(rootDir_)) {
        std::cerr << "LogicalDirExtractor: root is not a directory: " << rootDir_ << std::endl;
        return false;
    }

    // If the supplied root itself *is* a "data" directory, keep it as-is so
    // callers can pass either the parent of data/ or data/ directly. We only
    // verify existence here; path resolution handles both layouts.
    initialized_ = true;
    std::cout << "LogicalDirExtractor initialized: " << rootDir_ << std::endl;
    AuditLog::instance().log("SYSTEM", "LOGICAL_DIR_INIT", "Logical dir extractor: " + rootDir_);
    return true;
}

bool LogicalDirExtractor::extractFileByPath(const std::string& imageRelPath,
                                            const std::string& outPath) {
    if (!initialized_) {
        std::cerr << "LogicalDirExtractor: not initialized" << std::endl;
        return false;
    }

    std::string rel = normalizeRelPath(imageRelPath);

    // Try resolving directly under root first.
    std::string resolved = resolveSafe(rel);

    // If root points at .../data (i.e. caller passed the data dir itself), a
    // relPath of "data/data/com.foo/..." won't match; retry with a leading
    // "data/" stripped, and also the reverse case where rel already starts
    // with "data/" but root already contains it.
    if (resolved.empty()) {
        const std::string prefix = "data/";
        if (rel.rfind(prefix, 0) == 0) {
            resolved = resolveSafe(rel.substr(prefix.size()));
        }
    }
    if (resolved.empty()) {
        resolved = resolveSafe("data/" + rel);
    }

    if (resolved.empty()) {
        return false;  // callers treat missing files as normal (some artifacts absent)
    }

    try {
        const fs::path out(outPath);
        fs::path parent = out.parent_path();
        if (!parent.empty() && !fs::exists(parent)) {
            fs::create_directories(parent);
        }
        fs::copy_file(resolved, out, fs::copy_options::overwrite_existing);
        return true;
    } catch (const std::exception& e) {
        std::cerr << "LogicalDirExtractor: copy failed for " << imageRelPath
                  << " -> " << outPath << ": " << e.what() << std::endl;
        return false;
    }
}
