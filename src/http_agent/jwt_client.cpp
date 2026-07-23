#include "jwt_client.h"

#include <filesystem>
#include <fstream>
#include <iterator>
#include <stdexcept>

namespace tracelens {

namespace {

std::string trim(const std::string& s) {
    const auto a = s.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) return "";
    const auto b = s.find_last_not_of(" \t\r\n");
    return s.substr(a, b - a + 1);
}

}  // namespace

JwtClient::JwtClient(const std::string& token) : token_(trim(token)) {
    if (token_.empty()) {
        throw std::runtime_error("JwtClient: token is empty");
    }
}

JwtClient JwtClient::load_from_file(const std::string& path) {
    namespace fs = std::filesystem;
    std::error_code ec;
    const auto st = fs::status(path, ec);
    if (ec) {
        throw std::runtime_error("JwtClient: cannot stat token file '" + path +
                                 "': " + ec.message());
    }
    // Reject a file with ANY group/other permission bit set (read OR write OR
    // exec) — a secret must be owner-only. group_all/others_all cover rwx so a
    // group-writable 0660 file is rejected, not just a group-readable 0640 one.
    using fs::perms;
    if ((st.permissions() & (perms::group_all | perms::others_all)) != perms::none) {
        throw std::runtime_error(
            "JwtClient: token file '" + path +
            "' is accessible by group/other; chmod 0600 required");
    }
    std::ifstream f(path);
    if (!f) {
        throw std::runtime_error("JwtClient: cannot open token file '" + path + "'");
    }
    std::string tok((std::istreambuf_iterator<char>(f)),
                    std::istreambuf_iterator<char>());
    return JwtClient(tok);
}

std::string JwtClient::bearer_value() const { return "Bearer " + token_; }

}  // namespace tracelens
