#include "FilterRoutes.h"
#include "RouteHelpers.h"
#include "../../Swagger/Swagger.h"
#include "../../HTTPserver.h"
#include "FileFilter/FileFilter.h"
#include "PathManager/PathManager.h"
#include <filesystem>
#include <fstream>

namespace fs = std::filesystem;

namespace forensics {

using json = nlohmann::json;

// Path traversal guard — rejects names containing directory separators or traversal sequences
static bool isValidProfileName(const std::string& name) {
    if (name.empty()) return false;
    if (name.find("..") != std::string::npos) return false;
    if (name.find('/') != std::string::npos) return false;
    if (name.find('\\') != std::string::npos) return false;
    if (name.find('\0') != std::string::npos) return false;
    return true;
}

FilterRoutes::FilterRoutes(crow::App<>& app) {
    // GET /api/filter/profiles - List all available filter profiles
    CROW_ROUTE(app, "/api/filter/profiles").methods("GET"_method)([this](const crow::request& req) {
        return handle_list_profiles(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/filter/profiles", "GET",
        "List filter profiles",
        "List all available file filter profiles with name, description, and filename.",
        {"Filter"},
        {},
        {{200, "List of filter profiles"}}
    );

    // GET /api/filter/profiles/<name> - Get profile details
    CROW_ROUTE(app, "/api/filter/profiles/<string>").methods("GET"_method)(
        [this](const crow::request& req, const std::string& name) {
            return handle_get_profile(req, name);
        });
    Swagger::instance().RegisterEndpoint(
        "/api/filter/profiles/{name}", "GET",
        "Get filter profile",
        "Retrieve the full details of a filter profile including all rules.",
        {"Filter"},
        {{"name", "path", "Profile name", true}},
        {{200, "Profile details"}, {404, "Profile not found"}}
    );

    // POST /api/filter/profiles - Create or update a filter profile
    CROW_ROUTE(app, "/api/filter/profiles").methods("POST"_method)([this](const crow::request& req) {
        return handle_create_profile(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/filter/profiles", "POST",
        "Create/update filter profile",
        "Create a new filter profile or update an existing one.",
        {"Filter"},
        {},
        {{201, "Profile created"}, {200, "Profile updated"}, {400, "Invalid request"}}
    );

    // DELETE /api/filter/profiles/<name> - Delete a custom profile
    CROW_ROUTE(app, "/api/filter/profiles/<string>").methods("DELETE"_method)(
        [this](const crow::request& req, const std::string& name) {
            return handle_delete_profile(req, name);
        });
    Swagger::instance().RegisterEndpoint(
        "/api/filter/profiles/{name}", "DELETE",
        "Delete filter profile",
        "Delete a custom filter profile. Built-in profiles cannot be deleted.",
        {"Filter"},
        {{"name", "path", "Profile name", true}},
        {{200, "Profile deleted"}, {404, "Profile not found"}, {403, "Cannot delete built-in profile"}}
    );

    // POST /api/filter/apply - Apply filter profile to a task
    CROW_ROUTE(app, "/api/filter/apply").methods("POST"_method)([this](const crow::request& req) {
        return handle_apply_filter(req);
    });
    Swagger::instance().RegisterEndpoint(
        "/api/filter/apply", "POST",
        "Apply filter to task",
        "Apply a filter profile to a task's raw database, creating a filtered database.",
        {"Filter"},
        {},
        {{200, "Filter applied"}, {400, "Invalid request"}, {404, "Task or profile not found"}}
    );
}

// ============================================================================
// GET /api/filter/profiles
// ============================================================================
crow::response FilterRoutes::handle_list_profiles(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    try {
        std::string profilesDir = getProfilesDirectory();
        if (profilesDir.empty()) {
            auto resp = ApiResponse::create_error("Filter profiles directory not found", "DIR_NOT_FOUND");
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        auto profiles = FileFilter::listProfiles(profilesDir);
        json data = json::array();
        for (const auto& [filename, name, description] : profiles) {
            data.push_back({
                {"filename", filename},
                {"name", name},
                {"description", description}
            });
        }

        auto resp = ApiResponse::create_success("Filter profiles listed", {{"profiles", data}, {"count", data.size()}});
        res.code = 200;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    } catch (const std::exception& e) {
        auto resp = ApiResponse::create_error(std::string("Failed to list profiles: ") + e.what(), "LIST_ERROR");
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    }

    return res;
}

// ============================================================================
// GET /api/filter/profiles/<name>
// ============================================================================
crow::response FilterRoutes::handle_get_profile(const crow::request& req, const std::string& name) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    if (!isValidProfileName(name)) {
        auto resp = ApiResponse::create_error("Invalid profile name", "VALIDATION_ERROR");
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
        return res;
    }

    try {
        std::string profilesDir = getProfilesDirectory();
        if (profilesDir.empty()) {
            auto resp = ApiResponse::create_error("Filter profiles directory not found", "DIR_NOT_FOUND");
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        std::string profilePath = profilesDir + "/" + name + ".json";
        if (!fs::exists(profilePath)) {
            auto resp = ApiResponse::create_error("Profile not found: " + name, "NOT_FOUND");
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        auto profile = FileFilter::loadProfile(profilePath);

        json data = {
            {"name", profile.name},
            {"description", profile.description},
            {"version", profile.version},
            {"include", conditionToJson(profile.include)},
            {"exclude", conditionToJson(profile.exclude)},
            {"combine_mode", profile.combine_mode == FilterCombineMode::ExcludeWins ? "exclude_wins" :
                             profile.combine_mode == FilterCombineMode::IncludeWins ? "include_wins" : "include_only"}
        };

        auto resp = ApiResponse::create_success("Profile details", data);
        res.code = 200;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    } catch (const std::exception& e) {
        auto resp = ApiResponse::create_error(std::string("Failed to load profile: ") + e.what(), "LOAD_ERROR");
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    }

    return res;
}

// ============================================================================
// POST /api/filter/profiles
// ============================================================================
crow::response FilterRoutes::handle_create_profile(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    try {
        json body = json::parse(req.body);

        // Validate required fields
        if (!body.contains("name") || !body["name"].is_string()) {
            auto resp = ApiResponse::create_error("'name' field is required and must be a string", "VALIDATION_ERROR");
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        std::string name = body["name"];
        if (!isValidProfileName(name)) {
            auto resp = ApiResponse::create_error("Invalid profile name", "VALIDATION_ERROR");
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        // Protect built-in profiles from being overwritten
        static const std::vector<std::string> builtins = {
            "general_forensics", "telecom_fraud", "data_breach", "virus_intrusion"
        };
        for (const auto& builtin : builtins) {
            if (name == builtin) {
                auto resp = ApiResponse::create_error("Cannot overwrite built-in profile: " + name, "FORBIDDEN");
                res.code = 403;
                res.set_header("Content-Type", "application/json");
                res.write(resp.to_json().dump());
                return res;
            }
        }

        std::string profilesDir = getProfilesDirectory();
        if (profilesDir.empty()) {
            // Create the directory if it doesn't exist
            profilesDir = "config/filter_profiles";
            fs::create_directories(profilesDir);
        }

        std::string profilePath = profilesDir + "/" + name + ".json";
        bool is_update = fs::exists(profilePath);

        // Build the JSON profile
        json profile;
        profile["profile_name"] = name;
        profile["description"] = body.value("description", "");
        profile["version"] = body.value("version", "1.0");
        profile["combine_mode"] = body.value("combine_mode", "exclude_wins");

        // Include condition
        if (body.contains("include") && body["include"].is_object()) {
            json inc = body["include"];
            profile["include"] = {
                {"extensions", inc.value("extensions", json::array())},
                {"path_patterns", inc.value("path_patterns", json::array())},
                {"filename_patterns", inc.value("filename_patterns", json::array())},
                {"min_size", inc.value("min_size", 0)},
                {"max_size", inc.value("max_size", 0)},
                {"include_deleted", inc.value("include_deleted", true)},
                {"include_allocated", inc.value("include_allocated", true)}
            };
        } else {
            profile["include"] = {
                {"extensions", json::array()},
                {"path_patterns", json::array()},
                {"filename_patterns", json::array()},
                {"min_size", 0},
                {"max_size", 0},
                {"include_deleted", true},
                {"include_allocated", true}
            };
        }

        // Exclude condition
        if (body.contains("exclude") && body["exclude"].is_object()) {
            json exc = body["exclude"];
            profile["exclude"] = {
                {"extensions", exc.value("extensions", json::array())},
                {"path_patterns", exc.value("path_patterns", json::array())},
                {"filename_patterns", exc.value("filename_patterns", json::array())}
            };
        } else {
            profile["exclude"] = {
                {"extensions", json::array()},
                {"path_patterns", json::array()},
                {"filename_patterns", json::array()}
            };
        }

        // Write to file
        std::ofstream ofs(profilePath);
        if (!ofs.is_open()) {
            auto resp = ApiResponse::create_error("Failed to write profile file", "WRITE_ERROR");
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }
        ofs << profile.dump(4) << std::endl;
        ofs.close();

        auto resp = ApiResponse::create_success(
            is_update ? "Profile updated" : "Profile created",
            {{"name", name}, {"path", profilePath}}
        );
        res.code = is_update ? 200 : 201;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());

    } catch (const json::parse_error& e) {
        auto resp = ApiResponse::create_error("Invalid JSON body", "PARSE_ERROR");
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    } catch (const std::exception& e) {
        auto resp = ApiResponse::create_error(std::string("Failed to create profile: ") + e.what(), "CREATE_ERROR");
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    }

    return res;
}

// ============================================================================
// DELETE /api/filter/profiles/<name>
// ============================================================================
crow::response FilterRoutes::handle_delete_profile(const crow::request& req, const std::string& name) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    if (!isValidProfileName(name)) {
        auto resp = ApiResponse::create_error("Invalid profile name", "VALIDATION_ERROR");
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
        return res;
    }

    try {
        std::string profilesDir = getProfilesDirectory();
        if (profilesDir.empty()) {
            auto resp = ApiResponse::create_error("Filter profiles directory not found", "DIR_NOT_FOUND");
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        std::string profilePath = profilesDir + "/" + name + ".json";
        if (!fs::exists(profilePath)) {
            auto resp = ApiResponse::create_error("Profile not found: " + name, "NOT_FOUND");
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        // Protect built-in profiles
        static const std::vector<std::string> builtins = {
            "general_forensics", "telecom_fraud", "data_breach", "virus_intrusion"
        };
        for (const auto& builtin : builtins) {
            if (name == builtin) {
                auto resp = ApiResponse::create_error("Cannot delete built-in profile: " + name, "FORBIDDEN");
                res.code = 403;
                res.set_header("Content-Type", "application/json");
                res.write(resp.to_json().dump());
                return res;
            }
        }

        fs::remove(profilePath);

        auto resp = ApiResponse::create_success("Profile deleted: " + name);
        res.code = 200;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());

    } catch (const std::exception& e) {
        auto resp = ApiResponse::create_error(std::string("Failed to delete profile: ") + e.what(), "DELETE_ERROR");
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    }

    return res;
}

// ============================================================================
// POST /api/filter/apply
// ============================================================================
crow::response FilterRoutes::handle_apply_filter(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    try {
        json body = json::parse(req.body);

        if (!body.contains("task_id") || !body["task_id"].is_string()) {
            auto resp = ApiResponse::create_error("'task_id' is required", "VALIDATION_ERROR");
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        if (!body.contains("profile_name") || !body["profile_name"].is_string()) {
            auto resp = ApiResponse::create_error("'profile_name' is required", "VALIDATION_ERROR");
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        std::string task_id = body["task_id"];
        std::string profile_name = body["profile_name"];

        if (!isValidProfileName(profile_name)) {
            auto resp = ApiResponse::create_error("Invalid profile name", "VALIDATION_ERROR");
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        // Get task's raw.db path
        auto& taskMgr = TaskManager::instance();
        auto task = taskMgr.get_task(task_id);
        if (task.id.empty()) {
            auto resp = ApiResponse::create_error("Task not found: " + task_id, "NOT_FOUND");
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        std::string rawDbPath = task.output_raw_db;
        if (rawDbPath.empty() || !fs::exists(rawDbPath)) {
            auto resp = ApiResponse::create_error("Raw database not found for task: " + task_id, "DB_NOT_FOUND");
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(resp.to_json().dump());
            return res;
        }

        // Generate filtered db path
        std::string filteredDbPath = rawDbPath;
        // Replace _raw.db with _filtered.db
        size_t pos = filteredDbPath.rfind("_raw.db");
        if (pos != std::string::npos) {
            filteredDbPath.replace(pos, 7, "_filtered.db");
        } else {
            filteredDbPath += ".filtered";
        }

        FileFilter filter;
        auto stats = filter.applyFilterByName(rawDbPath, filteredDbPath, profile_name);

        json data = {
            {"task_id", task_id},
            {"profile_name", profile_name},
            {"filtered_db", filteredDbPath},
            {"total_files", stats.total_files},
            {"included_files", stats.included_files},
            {"excluded_files", stats.excluded_files}
        };

        auto resp = ApiResponse::create_success("Filter applied successfully", data);
        res.code = 200;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());

    } catch (const json::parse_error& e) {
        auto resp = ApiResponse::create_error("Invalid JSON body", "PARSE_ERROR");
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    } catch (const std::exception& e) {
        auto resp = ApiResponse::create_error(std::string("Filter failed: ") + e.what(), "FILTER_ERROR");
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(resp.to_json().dump());
    }

    return res;
}

// ============================================================================
// Helpers
// ============================================================================

std::string FilterRoutes::getProfilesDirectory() {
    auto& pm = PathManager::instance();
    std::vector<std::string> candidates;

    if (pm.isInitialized()) {
        candidates.push_back((pm.getProjectRoot() / "config" / "filter_profiles").string());
        candidates.push_back((pm.getExeDir() / "config" / "filter_profiles").string());
    }

    candidates.push_back("config/filter_profiles");
    candidates.push_back("../config/filter_profiles");
    candidates.push_back("../../config/filter_profiles");

    for (const auto& candidate : candidates) {
        if (fs::exists(candidate) && fs::is_directory(candidate)) {
            return candidate;
        }
    }

    return "";
}

json FilterRoutes::conditionToJson(const FilterCondition& cond) {
    return {
        {"extensions", cond.extensions},
        {"path_patterns", cond.path_patterns},
        {"filename_patterns", cond.filename_patterns},
        {"min_size", cond.min_size},
        {"max_size", cond.max_size},
        {"include_deleted", cond.include_deleted},
        {"include_allocated", cond.include_allocated}
    };
}

FilterCondition FilterRoutes::jsonToCondition(const json& j) {
    FilterCondition cond;
    if (j.contains("extensions")) cond.extensions = j["extensions"].get<std::vector<std::string>>();
    if (j.contains("path_patterns")) cond.path_patterns = j["path_patterns"].get<std::vector<std::string>>();
    if (j.contains("filename_patterns")) cond.filename_patterns = j["filename_patterns"].get<std::vector<std::string>>();
    if (j.contains("min_size")) cond.min_size = j["min_size"].get<int64_t>();
    if (j.contains("max_size")) cond.max_size = j["max_size"].get<int64_t>();
    if (j.contains("include_deleted")) cond.include_deleted = j["include_deleted"].get<bool>();
    if (j.contains("include_allocated")) cond.include_allocated = j["include_allocated"].get<bool>();
    return cond;
}

} // namespace forensics
