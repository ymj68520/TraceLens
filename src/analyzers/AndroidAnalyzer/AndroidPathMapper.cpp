#include "AndroidPathMapper.h"

#include <algorithm>
#include <cctype>
#include <set>

namespace {
bool starts(const std::string& value, const std::string& prefix) {
    return value.rfind(prefix, 0) == 0;
}

bool isAndroidRoot(const std::string& path) {
    return starts(path, "data/data/") || starts(path, "data/user/0/") ||
           starts(path, "data/user_de/0/") || starts(path, "data/system/") ||
           starts(path, "data/misc/wifi/") ||
           path == "system/build.prop" || starts(path, "system/app/") ||
           starts(path, "system/priv-app/");
}

bool isAndroidMember(const std::string& path) {
    return starts(path, "data/") || starts(path, "system/");
}

bool isNested(const std::string& path) {
    const auto dot = path.rfind('.');
    if (dot == std::string::npos) return false;
    std::string suffix = path.substr(dot);
    std::transform(suffix.begin(), suffix.end(), suffix.begin(),
                   [](unsigned char ch) { return static_cast<char>(std::tolower(ch)); });
    return suffix == ".zip" || suffix == ".tar" || suffix == ".7z" ||
           suffix == ".img" || suffix == ".ab" || suffix == ".e01";
}

bool validPackage(const std::string& pkg) {
    return !pkg.empty() && pkg.size() <= 255 && pkg != "." && pkg != ".." &&
           std::any_of(pkg.begin(), pkg.end(), [](unsigned char ch) { return std::isalnum(ch); }) &&
           std::all_of(pkg.begin(), pkg.end(), [](unsigned char ch) {
               return std::isalnum(ch) || ch == '.' || ch == '_';
           });
}

std::string mapAdbBackup(const std::string& path) {
    // AOSP full-backup TAR layout: apps/<package>/db/<database>.
    if (!starts(path, "apps/")) return {};
    const auto pkgEnd = path.find('/', 5);
    if (pkgEnd == std::string::npos) return {};
    const std::string pkg = path.substr(5, pkgEnd - 5);
    if (!validPackage(pkg)) return {};
    const std::string rest = path.substr(pkgEnd + 1);
    if (starts(rest, "db/") && rest.size() > 3)
        return "data/data/" + pkg + "/databases/" + rest.substr(3);
    if (starts(rest, "f/") && rest.size() > 2)
        return "data/data/" + pkg + "/files/" + rest.substr(2);
    if (starts(rest, "sp/") && rest.size() > 3)
        return "data/data/" + pkg + "/shared_prefs/" + rest.substr(3);
    return {}; // manifest/metadata and shared storage are not Android DB paths.
}
} // namespace

bool AndroidPathMapper::safeMemberPath(const std::string& raw, std::string& cleaned,
                                       std::string& reason) {
    cleaned.clear();
    if (raw.empty() || raw.size() > 4096 || raw.find('\0') != std::string::npos) {
        reason = "invalid_or_overlong_member_path";
        return false;
    }
    if (starts(raw, "//") || starts(raw, "\\\\") ||
        (raw.size() >= 2 && std::isalpha(static_cast<unsigned char>(raw[0])) && raw[1] == ':')) {
        reason = "absolute_or_unc_member_path";
        return false;
    }
    // An absolute path is accepted only when it is itself a demonstrable
    // Android root, as some FFS exporters store /data/data/... literally.
    const bool absolute = raw.front() == '/';
    std::string value = absolute ? raw.substr(1) : raw;
    if (starts(value, "./")) value.erase(0, 2);
    if (value.find('\\') != std::string::npos || value.find("//") != std::string::npos) {
        reason = "ambiguous_member_separator";
        return false;
    }
    std::size_t start = 0;
    while (start < value.size()) {
        const auto end = value.find('/', start);
        const std::string part = value.substr(start, end == std::string::npos ? end : end - start);
        if (part.empty() || part == ".." || part == "." || part.size() > 255) {
            reason = "unsafe_member_component";
            return false;
        }
        if (end == std::string::npos) break;
        start = end + 1;
    }
    if (absolute && !isAndroidRoot(value)) {
        reason = "absolute_non_android_member_path";
        return false;
    }
    cleaned = std::move(value);
    return true;
}

bool AndroidPathMapper::normalizeRequest(const std::string& raw, std::string& normalized) {
    std::string reason;
    if (!safeMemberPath(raw, normalized, reason)) return false;
    return isAndroidMember(normalized);
}

AndroidPathMappingResult AndroidPathMapper::buildUserdata(
    const std::vector<std::string>& regularPaths) {
    AndroidPathMappingResult result;
    result.rootMapping = "userdata_root_mounted_at_data";
    result.confidence = "high";
    for (const auto& raw : regularPaths) {
        std::string path, reason;
        if (!safeMemberPath(raw, path, reason)) {
            result.reason = "RISK_REJECTED: " + reason;
            result.normalizedToMember.clear();
            return result;
        }
        std::string normalized;
        // A previously normalized logical tree may itself be stored at the
        // filesystem root. Preserve that unambiguously recognizable case.
        if (starts(path, "data/data/") || starts(path, "data/user/") ||
            starts(path, "data/system/") || starts(path, "data/misc/"))
            normalized = path;
        else if (starts(path, "data/") || starts(path, "user/") ||
                 starts(path, "user_de/") || starts(path, "system/") ||
                 starts(path, "system_ce/") || starts(path, "system_de/") ||
                 starts(path, "misc/") || starts(path, "misc_ce/") ||
                 starts(path, "misc_de/") || starts(path, "media/"))
            normalized = "data/" + path;
        if (normalized.empty()) continue;
        if (!result.normalizedToMember.emplace(normalized, raw).second) {
            result.reason = "RISK_REJECTED: ambiguous_normalized_path";
            result.normalizedToMember.clear();
            return result;
        }
    }
    result.valid = !result.normalizedToMember.empty();
    result.reason = result.valid ? "userdata_paths_mapped" : "no_android_userdata_paths";
    return result;
}

AndroidPathMappingResult AndroidPathMapper::build(
    const std::vector<std::string>& regularMembers, bool androidBackup) {
    AndroidPathMappingResult result;
    std::vector<std::string> paths;
    paths.reserve(regularMembers.size());
    for (const auto& raw : regularMembers) {
        std::string path, reason;
        if (!safeMemberPath(raw, path, reason)) {
            result.reason = "RISK_REJECTED: " + reason;
            return result;
        }
        paths.push_back(std::move(path));
    }
    if (paths.empty()) {
        result.reason = "no_regular_members";
        return result;
    }

    std::set<std::string> candidates{"", "userdata/", "root/"};
    // Single outer wrapper is allowed only if every regular file is inside it.
    const auto slash = paths.front().find('/');
    if (slash != std::string::npos) {
        const std::string wrapper = paths.front().substr(0, slash + 1);
        if (std::all_of(paths.begin(), paths.end(), [&](const std::string& path) {
                return starts(path, wrapper);
            })) candidates.insert(wrapper);
    }
    std::string chosen;
    std::size_t best = 0;
    for (const auto& prefix : candidates) {
        std::size_t hits = 0;
        for (const auto& path : paths) {
            if (starts(path, prefix) && isAndroidRoot(path.substr(prefix.size()))) ++hits;
        }
        if (hits > best || (hits == best && prefix.size() < chosen.size())) {
            best = hits;
            chosen = prefix;
        }
    }
    const bool adbLayout = androidBackup &&
        std::any_of(paths.begin(), paths.end(), [](const std::string& path) {
            return !mapAdbBackup(path).empty();
        });
    if (best == 0 && !adbLayout) {
        result.reason = "no_demonstrable_android_root";
        return result;
    }
    result.rootMapping = best ? (chosen.empty() ? "archive_root" : chosen) : "adb_apps";
    result.confidence = chosen.empty() || adbLayout ? "high" : "medium";
    result.reason = best ? "recognized_android_artifact_paths" : "aosp_adb_apps_namespace";

    for (std::size_t i = 0; i < paths.size(); ++i) {
        const auto& path = paths[i];
        if (isNested(path)) ++result.nestedContainerCount;
        std::string normalized;
        if (best && starts(path, chosen) && isAndroidMember(path.substr(chosen.size())))
            normalized = path.substr(chosen.size());
        else if (androidBackup) normalized = mapAdbBackup(path);
        if (normalized.empty()) continue;
        if (!result.normalizedToMember.emplace(normalized, regularMembers[i]).second) {
            result.reason = "RISK_REJECTED: ambiguous_normalized_path";
            result.normalizedToMember.clear();
            result.valid = false;
            return result;
        }
    }
    result.valid = !result.normalizedToMember.empty();
    return result;
}
