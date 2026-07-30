#pragma once
#include <string>
#include <algorithm>
#include <cstring>

// MiuiPathMap: header-only path translation between MIUI backup tar member
// names (apps/<pkg>/db|f|sp/...) and the TSK-style analyzer query paths
// (data/data/<pkg>/databases|files|shared_prefs/...).
//
// Contract: unmappable inputs return an empty string (no silent failure).

inline static std::string normalizeFwd(const std::string& s) {
    std::string r = s;
    std::replace(r.begin(), r.end(), '\\', '/');
    if (!r.empty() && r[0] == '/') r.erase(0, 1);
    return r;
}

// Map a TSK-style analyzer query path to the tar member name used by MIUI backups.
// Returns empty string if the path is not a mappable app-data path.
inline std::string analyzerPathToTarMember(const std::string& imageRelPath) {
    std::string p = normalizeFwd(imageRelPath);
    const std::string prefix = "data/data/";
    if (p.rfind(prefix, 0) != 0) return "";
    std::string rest = p.substr(prefix.size());
    auto slash = rest.find('/');
    if (slash == std::string::npos) return "";
    std::string pkg = rest.substr(0, slash);
    std::string tail = rest.substr(slash + 1);
    std::string sub;
    if (tail.rfind("databases/", 0) == 0)        sub = "db/" + tail.substr(strlen("databases/"));
    else if (tail.rfind("files/", 0) == 0)        sub = "f/" + tail.substr(strlen("files/"));
    else if (tail.rfind("app_flutter/files/", 0) == 0) sub = "f/" + tail;
    else if (tail.rfind("shared_prefs/", 0) == 0) sub = "sp/" + tail.substr(strlen("shared_prefs/"));
    else return "";
    return "apps/" + pkg + "/" + sub;
}

// Inverse, used when reporting source paths in inventory rows.
inline std::string tarMemberToAnalyzerPath(const std::string& memberName) {
    std::string p = normalizeFwd(memberName);
    const std::string prefix = "apps/";
    if (p.rfind(prefix, 0) != 0) return "";
    std::string rest = p.substr(prefix.size());
    auto s1 = rest.find('/'); if (s1 == std::string::npos) return "";
    std::string pkg = rest.substr(0, s1);
    std::string tail = rest.substr(s1 + 1);
    std::string sub;
    if (tail.rfind("db/", 0) == 0)       sub = "databases/" + tail.substr(3);
    else if (tail.rfind("f/app_flutter/files/", 0) == 0) sub = tail.substr(2);
    else if (tail.rfind("f/", 0) == 0)    sub = "files/" + tail.substr(2);
    else if (tail.rfind("sp/", 0) == 0)   sub = "shared_prefs/" + tail.substr(3);
    else return "";
    return "data/data/" + pkg + "/" + sub;
}
