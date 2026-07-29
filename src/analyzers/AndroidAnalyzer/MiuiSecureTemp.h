#pragma once

#include <filesystem>
#include <string>
#include <system_error>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#else
#include <cstdlib>
#include <unistd.h>
#endif

namespace miui_secure_temp {
namespace fs = std::filesystem;

inline bool isSameOrDescendant(const fs::path& candidate, const fs::path& root) {
    if (candidate == root) return true;
    const fs::path relative = candidate.lexically_relative(root);
    return !relative.empty() && !relative.is_absolute() && *relative.begin() != "..";
}

inline bool canonicalDirectory(const fs::path& input, fs::path& output) {
    std::error_code error;
    output = fs::canonical(input, error);
    return !error && fs::is_directory(output, error) && !error;
}

inline bool safeParent(const fs::path& parent, const fs::path& evidenceRoot) {
    fs::path canonicalParent;
    fs::path canonicalEvidence;
    if (!canonicalDirectory(parent, canonicalParent) ||
        !canonicalDirectory(evidenceRoot, canonicalEvidence)) {
        return false;
    }
    return !isSameOrDescendant(canonicalParent, canonicalEvidence);
}

inline bool createDirectory(const fs::path& evidenceRoot, const std::string& prefix,
                            fs::path& output) {
    output.clear();
    std::vector<fs::path> candidates;
    std::error_code error;
    const fs::path configured = fs::temp_directory_path(error);
    if (!error) candidates.push_back(configured);
#ifndef _WIN32
    candidates.emplace_back("/tmp");
    candidates.emplace_back("/var/tmp");
#endif

    for (const fs::path& candidate : candidates) {
        if (!safeParent(candidate, evidenceRoot)) continue;
#ifndef _WIN32
        std::string pattern = (candidate / (prefix + "-XXXXXX")).string();
        std::vector<char> writable(pattern.begin(), pattern.end());
        writable.push_back('\0');
        if (char* created = ::mkdtemp(writable.data())) {
            output = fs::path(created);
            return true;
        }
#else
        for (unsigned attempt = 0; attempt < 128; ++attempt) {
            const fs::path path = candidate /
                (prefix + "-" + std::to_string(::GetCurrentProcessId()) + "-" +
                 std::to_string(attempt));
            error.clear();
            if (fs::create_directory(path, error)) {
                output = path;
                return true;
            }
            if (error && error != std::errc::file_exists) break;
        }
#endif
    }
    return false;
}

}  // namespace miui_secure_temp
