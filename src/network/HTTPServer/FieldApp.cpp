#include "FieldApp.h"

#include <httplib.h>
#include <nlohmann/json.hpp>
#include <openssl/crypto.h>
#include <cstdlib>
#include <filesystem>
#include <sstream>
#include <set>
#include "ConfigManager/ConfigManager.h"

namespace forensics {
namespace {

std::string env(const char* key) {
    const char* value = std::getenv(key);
    return value ? std::string(value) : std::string();
}

bool loopback(const std::string& peer) {
    return peer == "127.0.0.1" || peer == "::1" || peer == "::ffff:127.0.0.1";
}

bool equal_secret(const std::string& supplied, const std::string& expected) {
    return expected.size() >= 32 && supplied.size() == expected.size() &&
        CRYPTO_memcmp(supplied.data(), expected.data(), expected.size()) == 0;
}

bool configured_secret(const std::string& value) {
    return value.size() >= 32 && value.rfind("REPLACE_", 0) != 0 &&
        value != "change-this-in-production" &&
        std::set<char>(value.begin(), value.end()).size() >= 16;
}

void deny(crow::response& res, int code, const char* detail) {
    res.code = code;
    if (code == 401) res.set_header("WWW-Authenticate", "Bearer");
    res.set_header("Content-Type", "application/json");
    res.set_header("Cache-Control", "no-store");
    res.write(nlohmann::json{{"detail", detail}}.dump());
    res.end();
}

bool valid_auth_url(const std::string& value) {
    std::string port;
    if (value.rfind("http://127.0.0.1:", 0) == 0) port = value.substr(17);
    else if (value.rfind("http://[::1]:", 0) == 0) port = value.substr(13);
    else return false;
    if (port.empty() || port.size() > 5 ||
        port.find_first_not_of("0123456789") != std::string::npos) return false;
    const int number = std::stoi(port);
    return number > 0 && number <= 65535;
}

bool allowed_model_url(const std::string& url, const std::string& list) {
    if (url.empty()) return true;
    const std::size_t scheme_end = url.find("://");
    if (scheme_end == std::string::npos) return false;
    const std::size_t path_start = url.find('/', scheme_end + 3);
    const std::string origin = url.substr(0, path_start);
    if (!valid_auth_url(origin)) return false; // numeric loopback HTTP + explicit port
    std::stringstream entries(list);
    std::string entry;
    while (std::getline(entries, entry, ',')) {
        if (entry == origin) return true;
    }
    return false;
}

bool optional_outbound_blocked(const std::string& path) {
    const auto mode = env("FIELD_OUTBOUND_POLICY");
    if (!mode.empty() && mode != "disabled") return false;
    return path.find("/oss") != std::string::npos ||
           path.find("/graphiti") != std::string::npos ||
           path.find("/embedding") != std::string::npos;
}

bool python_service_scope(const crow::request& req, const std::string& path) {
    if (req.method == crow::HTTPMethod::GET) {
        return path == "/api/security/status" || path == "/api/health" ||
            path == "/api/tasks" ||
            path.rfind("/api/tasks/", 0) == 0 ||
            path.rfind("/api/forensics/", 0) == 0;
    }
    return req.method == crow::HTTPMethod::POST &&
        (path == "/api/forensics/extract" || path == "/api/forensics/dlls/analyze");
}

} // namespace

bool field_runtime_ready() {
    if (env("TRACELENS_FIELD_AUTH") != "enabled") return true;
    const auto c2p = env("FIELD_CPP_TO_PYTHON_TOKEN");
    const auto p2c = env("FIELD_PYTHON_TO_CPP_TOKEN");
    if (!valid_auth_url(env("FIELD_AUTH_URL")) || !configured_secret(c2p) ||
        !configured_secret(p2c) || equal_secret(c2p, p2c)) return false;
    if (env("TRACELENS_REQUIRE_RELEASE_LAYOUT") == "1") {
        const std::filesystem::path release(env("TRACELENS_RELEASE_ROOT"));
        const std::filesystem::path python(env("TRACELENS_PYTHON_BIN"));
        if (!release.is_absolute() || !python.is_absolute() ||
            !std::filesystem::is_directory(release) ||
            !std::filesystem::is_regular_file(python) ||
            !std::filesystem::is_regular_file(release / "scripts/android_container_pipeline_cli.py") ||
            !std::filesystem::is_regular_file(release / "scripts/android_image_reader_bridge.py")) return false;
    }
    for (const char* key : {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                            "http_proxy", "https_proxy", "all_proxy"}) {
        if (!env(key).empty()) return false;
    }
    const auto mode = env("FIELD_OUTBOUND_POLICY");
    if (mode.empty() || mode == "disabled") return true;
    if (mode != "local_only" || env("FIELD_MODEL_ORIGINS").empty()) return false;
    auto& config = ConfigManager::instance();
    if (!config.isLoaded() && !config.load()) return false;
    if (!allowed_model_url(config.getLLMBaseUrl(), env("FIELD_MODEL_ORIGINS")) ||
        !allowed_model_url(config.getTextBaseUrl(), env("FIELD_MODEL_ORIGINS")) ||
        !allowed_model_url(config.getVisionBaseUrl(), env("FIELD_MODEL_ORIGINS"))) return false;
    const auto endpoint = config.getLLMEndpoint();
    return endpoint.empty() || endpoint[0] == '/';
}

void FieldAuthMiddleware::before_handle(crow::request& req, crow::response& res, context& ctx) {
    if (env("TRACELENS_FIELD_AUTH") != "enabled") return; // legacy runtime; checker flags it
    const std::string path = req.url;
    if (req.method == crow::HTTPMethod::OPTIONS) {
        res.code = 204;
        res.end();
        return;
    }
    if (path == "/health/live") return;
    if (path != "/api" && path.rfind("/api/", 0) != 0 && path.rfind("/tasks", 0) != 0 &&
        path.rfind("/python/", 0) != 0 && path.rfind("/cs/", 0) != 0 &&
        path.rfind("/cs-disabled/", 0) != 0) {
        if (req.method == crow::HTTPMethod::GET || req.method == crow::HTTPMethod::HEAD) return;
        deny(res, 401, "authentication required");
        return;
    }
    const std::string internal = req.get_header_value("X-TraceLens-Service-Token");
    if (!internal.empty()) {
        if (loopback(req.remote_ip_address) && equal_secret(internal, env("FIELD_PYTHON_TO_CPP_TOKEN"))) {
            ctx.principal = "python-service";
            ctx.role = "service";
            if (!python_service_scope(req, path)) {
                deny(res, 403, "service scope denied");
                return;
            }
            if (optional_outbound_blocked(path)) deny(res, 503, "optional intelligence services disabled");
            return;
        }
        deny(res, 401, "invalid service credential");
        return;
    }
    const std::string authorization = req.get_header_value("Authorization");
    if (authorization.rfind("Bearer ", 0) != 0 || authorization.size() <= 7) {
        deny(res, 401, "bearer token required");
        return;
    }
    const std::string auth_url = env("FIELD_AUTH_URL");
    const std::string service_token = env("FIELD_CPP_TO_PYTHON_TOKEN");
    if (!valid_auth_url(auth_url) || !configured_secret(service_token)) {
        deny(res, 503, "field authentication unavailable");
        return;
    }
    try {
        httplib::Client client(auth_url);
        client.set_connection_timeout(1);
        client.set_read_timeout(2);
        client.set_follow_location(false);
        const nlohmann::json request = {
            {"authorization", authorization},
            {"method", crow::method_name(req.method)},
            {"path", path},
        };
        const httplib::Headers headers{{"X-TraceLens-Service-Token", service_token}};
        const auto result = client.Post("/api/field-auth/introspect", headers,
                                        request.dump(), "application/json");
        if (!result) {
            deny(res, 503, "field authentication unavailable");
            return;
        }
        if (result->status == 401 || result->status == 403) {
            deny(res, result->status, result->status == 401 ? "invalid bearer token" : "insufficient permission");
            return;
        }
        if (result->status != 200) {
            deny(res, 503, "field authentication unavailable");
            return;
        }
        const auto payload = nlohmann::json::parse(result->body);
        const auto subject = payload.at("principal");
        ctx.principal = subject.at("id").get<std::string>();
        ctx.role = subject.at("role").get<std::string>();
        if (ctx.principal.empty() || ctx.role.empty()) {
            deny(res, 503, "invalid authentication response");
        } else if (optional_outbound_blocked(path)) {
            deny(res, 503, "optional intelligence services disabled");
        }
    } catch (const std::exception&) {
        deny(res, 503, "field authentication unavailable");
    }
}

} // namespace forensics
