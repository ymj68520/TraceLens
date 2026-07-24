#include "client_config.h"

#include <cstdlib>
#include <fstream>
#include <sstream>

namespace tracelens {

namespace {

std::string trim(const std::string& s) {
    const auto a = s.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) return "";
    const auto b = s.find_last_not_of(" \t\r\n");
    return s.substr(a, b - a + 1);
}

// Splits a PATH-like colon-separated list, trimming each element and dropping
// empties. (Linux platform: ':' is the list separator.)
std::vector<std::string> split_dirs(const std::string& s) {
    std::vector<std::string> out;
    std::size_t pos = 0;
    while (pos <= s.size()) {
        const auto sep = s.find(':', pos);
        const std::string tok = (sep == std::string::npos) ? s.substr(pos)
                                                           : s.substr(pos, sep - pos);
        const std::string t = trim(tok);
        if (!t.empty()) out.push_back(t);
        if (sep == std::string::npos) break;
        pos = sep + 1;
    }
    return out;
}

}  // namespace

std::string ClientConfig::validate(const ClientConfig& c) {
    if (c.token_path.empty()) return "token_path is required";
    if (c.analyzer_path.empty()) return "analyzer_path is required";
    if (c.server_base_url.empty()) return "server_base_url is required";

    const auto pos = c.server_base_url.find("://");
    if (pos == std::string::npos) {
        return "server_base_url must include a scheme (https://...)";
    }
    const std::string scheme = c.server_base_url.substr(0, pos);
    std::string rest = c.server_base_url.substr(pos + 3);

    if (scheme == "https") {
        // Encrypted — fine.
    } else if (scheme == "http") {
        // Only localhost variants allowed (development convenience).
        std::string host = rest;
        if (const auto p = host.find('/'); p != std::string::npos) host = host.substr(0, p);
        if (!host.empty() && host.front() == '[') {
            // Bracketed IPv6 literal, e.g. [::1]:8000 -> ::1
            if (const auto rb = host.find(']'); rb != std::string::npos) {
                host = host.substr(1, rb - 1);
            }
        } else if (const auto p = host.find(':'); p != std::string::npos) {
            host = host.substr(0, p);  // drop the port
        }
        if (host != "localhost" && host != "127.0.0.1" && host != "::1") {
            return "http:// to a non-localhost server is not allowed; use https://";
        }
    } else {
        return "unsupported scheme '" + scheme + "'; use https://";
    }

    if (c.poll_interval_seconds < 5 || c.poll_interval_seconds > 30) {
        return "poll_interval_seconds must be between 5 and 30";
    }
    return "";
}

ClientConfig ClientConfig::load_from_file(const std::string& path, std::string& err) {
    ClientConfig c;
    std::ifstream f(path);
    if (!f) {
        err = "cannot open config file '" + path + "'";
        return c;
    }
    std::string line;
    while (std::getline(f, line)) {
        const auto t = trim(line);
        if (t.empty() || t[0] == '#') continue;
        const auto eq = t.find('=');
        if (eq == std::string::npos) continue;
        const std::string key = trim(t.substr(0, eq));
        const std::string val = trim(t.substr(eq + 1));
        if (key == "server_base_url")        c.server_base_url = val;
        else if (key == "poll_interval_seconds") c.poll_interval_seconds = std::atoi(val.c_str());
        else if (key == "reindex_interval_seconds") c.reindex_interval_seconds = std::atoi(val.c_str());
        else if (key == "token_path")        c.token_path = val;
        else if (key == "hostname")          c.hostname = val;
        else if (key == "analyzer_path")     c.analyzer_path = val;
        else if (key == "work_base_dir")     c.work_base_dir = val;
        else if (key == "state_db_path")     c.state_db_path = val;
        else if (key == "image_dirs")        c.image_dirs = split_dirs(val);
    }
    return c;
}

ClientConfig ClientConfig::load_from_env(std::string& err) {
    (void)err;  // env reads are individually optional; validate() surfaces gaps
    ClientConfig c;
    if (const char* v = std::getenv("TRACELENS_SERVER_URL"))      c.server_base_url = v;
    if (const char* v = std::getenv("TRACELENS_POLL_INTERVAL"))   c.poll_interval_seconds = std::atoi(v);
    if (const char* v = std::getenv("TRACELENS_REINDEX_INTERVAL")) c.reindex_interval_seconds = std::atoi(v);
    if (const char* v = std::getenv("TRACELENS_TOKEN_PATH"))      c.token_path = v;
    if (const char* v = std::getenv("TRACELENS_HOSTNAME"))        c.hostname = v;
    if (const char* v = std::getenv("TRACELENS_ANALYZER_PATH"))   c.analyzer_path = v;
    if (const char* v = std::getenv("TRACELENS_WORK_DIR"))        c.work_base_dir = v;
    if (const char* v = std::getenv("TRACELENS_STATE_DB"))        c.state_db_path = v;
    if (const char* v = std::getenv("TRACELENS_IMAGE_DIRS"))     c.image_dirs = split_dirs(v);
    return c;
}

}  // namespace tracelens
