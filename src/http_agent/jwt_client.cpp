#include "jwt_client.h"

#include <filesystem>
#include <fstream>
#include <iterator>
#include <stdexcept>

#include "json.hpp"

namespace tracelens {

namespace {

std::string trim(const std::string& s) {
    const auto a = s.find_first_not_of(" \t\r\n");
    if (a == std::string::npos) return "";
    const auto b = s.find_last_not_of(" \t\r\n");
    return s.substr(a, b - a + 1);
}

// Decodes an UNPADDED base64url string (RFC 7515 §2: '-' and '_' in place of
// '+' and '/'). Returns "" on any invalid character.
std::string base64url_decode(const std::string& in) {
    auto val = [](char c) -> int {
        if (c >= 'A' && c <= 'Z') return c - 'A';
        if (c >= 'a' && c <= 'z') return c - 'a' + 26;
        if (c >= '0' && c <= '9') return c - '0' + 52;
        if (c == '-') return 62;
        if (c == '_') return 63;
        return -1;
    };
    std::string out;
    out.reserve(in.size() * 3 / 4);
    int bits = 0, acc = 0;
    for (char c : in) {
        const int v = val(c);
        if (v < 0) return {};
        acc = (acc << 6) | v;
        bits += 6;
        if (bits >= 8) {
            bits -= 8;
            out.push_back(static_cast<char>((acc >> bits) & 0xFF));
        }
    }
    return out;  // trailing bits (< 8) are discarded
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

std::string JwtClient::client_id() const {
    // Payload is the middle segment of "header.payload.signature".
    const auto p1 = token_.find('.');
    if (p1 == std::string::npos) return "";
    const auto p2 = token_.find('.', p1 + 1);
    const auto end = (p2 == std::string::npos) ? token_.size() : p2;
    const std::string seg = token_.substr(p1 + 1, end - p1 - 1);
    const std::string json = base64url_decode(seg);
    if (json.empty()) return "";
    try {
        const auto j = nlohmann::json::parse(json, nullptr, /*allow_exceptions=*/false);
        if (j.is_object() && j.contains("client_id") && j["client_id"].is_string()) {
            return j["client_id"].get<std::string>();
        }
    } catch (...) {
        // parse with exceptions=false does not throw, but stay defensive.
    }
    return "";
}

}  // namespace tracelens
