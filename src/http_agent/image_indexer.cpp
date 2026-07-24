#include "image_indexer.h"

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <map>
#include <sys/stat.h>
#include <system_error>
#include <utility>

namespace tracelens {

namespace fs = std::filesystem;

std::string format_string(ImageFormat f) {
    switch (f) {
        case ImageFormat::E01:      return "E01";
        case ImageFormat::DD:       return "DD";
        case ImageFormat::Directory:return "Directory";
        case ImageFormat::Unknown:  break;
    }
    return "";
}

namespace {

std::string to_lower(const std::string& s) {
    std::string o;
    o.reserve(s.size());
    for (char c : s) o.push_back(static_cast<char>(std::tolower(static_cast<unsigned char>(c))));
    return o;
}

bool has_suffix(const std::string& s, const std::string& suf) {
    return s.size() >= suf.size() &&
           s.compare(s.size() - suf.size(), suf.size(), suf) == 0;
}

}  // namespace

ImageFormat detect_format(const std::string& name, bool is_dir) {
    if (is_dir) return ImageFormat::Directory;
    const std::string n = to_lower(name);
    if (has_suffix(n, ".dd") || has_suffix(n, ".img") ||
        has_suffix(n, ".raw") || has_suffix(n, ".000")) {
        return ImageFormat::DD;
    }
    // EWF segment: ".e" followed by exactly two digits (.e00 .. .e99).
    if (n.size() >= 4 && n[n.size() - 4] == '.' && n[n.size() - 3] == 'e' &&
        std::isdigit(static_cast<unsigned char>(n[n.size() - 2])) &&
        std::isdigit(static_cast<unsigned char>(n[n.size() - 1]))) {
        return ImageFormat::E01;
    }
    return ImageFormat::Unknown;
}

std::string e01_base(const std::string& name) {
    if (detect_format(name, /*is_dir=*/false) != ImageFormat::E01) return "";
    if (name.size() < 4) return "";  // defensive; detect_format guarantees >= 4
    return name.substr(0, name.size() - 4);
}

DiskImageIndexer::DiskImageIndexer(std::vector<std::string> dirs)
    : dirs_(std::move(dirs)) {}

std::vector<DiskImageEntry> DiskImageIndexer::scan(std::string& err) const {
    err.clear();
    std::vector<DiskImageEntry> out;
    // E01 dedup: lowercased base name -> the smallest-segment entry seen so far.
    std::map<std::string, DiskImageEntry> e01;

    for (const auto& dir : dirs_) {
        std::error_code ec;
        if (!fs::is_directory(dir, ec)) {
            if (err.empty()) err = "not a directory: " + dir;
            continue;
        }
        for (fs::directory_iterator it(dir, ec), end; !ec && it != end; it.increment(ec)) {
            const auto& de = *it;
            const bool is_dir = de.is_directory(ec);
            const std::string name = de.path().filename().string();
            const ImageFormat fmt = detect_format(name, is_dir);
            if (fmt == ImageFormat::Unknown) continue;

            std::error_code aec;
            const std::string abspath = fs::absolute(de.path(), aec).string();
            if (aec) continue;

            // Size via POSIX stat(): unlike std::filesystem::file_size() (which
            // rejects directories with EISDIR), stat() returns st_size for any
            // type — a directory's own entry size (e.g. 4096 on ext4), a regular
            // file's byte length. Skip non-positive sizes: the schema requires
            // size_bytes > 0.
            struct stat st;
            if (::stat(abspath.c_str(), &st) != 0) continue;
            const std::uint64_t sz = static_cast<std::uint64_t>(st.st_size);
            if (sz == 0) continue;

            if (fmt == ImageFormat::E01) {
                const std::string key = to_lower(e01_base(name));
                auto found = e01.find(key);
                if (found == e01.end()) {
                    e01.emplace(key, DiskImageEntry{abspath, sz, fmt});
                } else if (abspath < found->second.path) {
                    // Keep the lexicographically-smallest segment (the set's
                    // first segment, which the analyzer opens).
                    found->second = DiskImageEntry{abspath, sz, fmt};
                }
                continue;
            }
            out.push_back({abspath, sz, fmt});
        }
        if (ec && err.empty()) err = "scan error in " + dir + ": " + ec.message();
    }

    for (auto& [k, v] : e01) out.push_back(std::move(v));
    return out;
}

}  // namespace tracelens
