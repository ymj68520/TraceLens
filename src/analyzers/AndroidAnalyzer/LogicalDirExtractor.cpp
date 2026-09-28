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
    const fs::path relative = candidate.lexically_relative(root);
    if (relative.empty() || relative.is_absolute() ||
        *relative.begin() == "..") {
        std::cerr << "LogicalDirExtractor: path escapes root: " << relPath << std::endl;
        return {};
    }

    if (!fs::exists(candidate) || !fs::is_regular_file(candidate)) {
        return {};
    }
    return candidate.string();
}

std::vector<std::string> LogicalDirExtractor::findPathsByFilename(
    const std::string& filename, std::size_t limit) const {
    std::vector<std::string> found;
    if (!initialized_ || filename.empty() || limit == 0) return found;
    std::error_code error;
    const fs::path root = fs::weakly_canonical(rootDir_, error);
    if (error) return found;

    // Search the app's data roots, not an unbounded whole-device tree.
    const std::vector<fs::path> appRoots = {
        root / "data/data/com.tencent.mm", root / "data/user/0/com.tencent.mm",
        root / "data/user_de/0/com.tencent.mm", root / "data/com.tencent.mm",
        root / "user/0/com.tencent.mm", root / "com.tencent.mm"
    };
    std::size_t inspected = 0;
    for (const auto& candidateRoot : appRoots) {
        if (!fs::is_directory(candidateRoot, error)) { error.clear(); continue; }
        fs::recursive_directory_iterator iter(candidateRoot,
            fs::directory_options::skip_permission_denied, error);
        const fs::recursive_directory_iterator end;
        for (; !error && iter != end && found.size() < limit && inspected < 100000;
             iter.increment(error)) {
            ++inspected;
            if (iter->is_symlink(error)) { iter.disable_recursion_pending(); error.clear(); continue; }
            if (!iter->is_regular_file(error)) { error.clear(); continue; }
            if (iter->path().filename() != filename) continue;
            const fs::path resolved = fs::weakly_canonical(iter->path(), error);
            if (error) { error.clear(); continue; }
            const fs::path relative = resolved.lexically_relative(root);
            if (!relative.empty() && !relative.is_absolute() && *relative.begin() != "..") {
                found.push_back(relative.generic_string());
            }
        }
        error.clear();
        if (found.size() >= limit || inspected >= 100000) break;
    }
    std::sort(found.begin(), found.end());
    found.erase(std::unique(found.begin(), found.end()), found.end());
    return found;
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
