#include "CaseCRUDRoutes.h"
#include "RouteHelpers.h"

namespace forensics {

using json = nlohmann::json;

// ── Constructor — register all routes ────────────────────────────────────────

CaseCRUDRoutes::CaseCRUDRoutes(crow::App<>& app)
    : case_manager_(CaseManager::instance()) {

    CROW_ROUTE(app, "/api/cases").methods("GET"_method)([this](const crow::request& req) {
        return handle_list_cases(req);
    });

    CROW_ROUTE(app, "/api/cases").methods("POST"_method)([this](const crow::request& req) {
        return handle_create_case(req);
    });

    CROW_ROUTE(app, "/api/cases/<string>").methods("GET"_method)(
        [this](const crow::request& req, const std::string& id) {
            return handle_get_case(req, id);
        });

    CROW_ROUTE(app, "/api/cases/<string>/tasks").methods("PUT"_method)(
        [this](const crow::request& req, const std::string& id) {
            return handle_add_tasks(req, id);
        });

    CROW_ROUTE(app, "/api/cases/<string>").methods("DELETE"_method)(
        [this](const crow::request& req, const std::string& id) {
            return handle_delete_case(req, id);
        });

    CROW_ROUTE(app, "/api/cases/<string>/status").methods("PUT"_method)(
        [this](const crow::request& req, const std::string& id) {
            return handle_update_status(req, id);
        });
}

// ── Handlers ─────────────────────────────────────────────────────────────────

crow::response CaseCRUDRoutes::handle_list_cases(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    auto cases = case_manager_.get_all_cases();
    json arr = json::array();
    for (const auto& fc : cases) arr.push_back(case_to_json(fc));
    json resp = {{"cases", arr}, {"total", (int)cases.size()}};
    res.set_header("Content-Type", "application/json");
    res.write(resp.dump());
    return res;
}

crow::response CaseCRUDRoutes::handle_create_case(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        std::string name        = body.value("name", "Unnamed Case");
        std::string description = body.value("description", "");
        std::vector<std::string> task_ids;
        if (body.contains("task_ids") && body["task_ids"].is_array()) {
            task_ids = body["task_ids"].get<std::vector<std::string>>();
        }
        std::string id = case_manager_.create_case(name, description, task_ids);
        ForensicCase fc = case_manager_.get_case(id);
        res.code = 201;
        res.set_header("Content-Type", "application/json");
        res.write(case_to_json(fc).dump());
    } catch (const std::exception& e) {
        res.code = 400;
        res.write(json{{"error", e.what()}}.dump());
    }
    return res;
}

crow::response CaseCRUDRoutes::handle_get_case(const crow::request& req, const std::string& case_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    ForensicCase fc = case_manager_.get_case(case_id);
    if (fc.id.empty()) {
        res.code = 404;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", "Case not found"}, {"case_id", case_id}}.dump());
        return res;
    }
    res.set_header("Content-Type", "application/json");
    res.write(case_to_json(fc).dump());
    return res;
}

crow::response CaseCRUDRoutes::handle_add_tasks(const crow::request& req, const std::string& case_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        if (!body.contains("task_ids") || !body["task_ids"].is_array()) {
            res.code = 400;
            res.write(json{{"error", "task_ids array required"}}.dump());
            return res;
        }
        for (const auto& tid : body["task_ids"]) {
            case_manager_.add_task(case_id, tid.get<std::string>());
        }
        res.set_header("Content-Type", "application/json");
        res.write(case_to_json(case_manager_.get_case(case_id)).dump());
    } catch (const std::exception& e) {
        res.code = 400;
        res.write(json{{"error", e.what()}}.dump());
    }
    return res;
}

crow::response CaseCRUDRoutes::handle_delete_case(const crow::request& req, const std::string& case_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    bool ok = case_manager_.delete_case(case_id);
    if (!ok) {
        res.code = 404;
        res.set_header("Content-Type", "application/json");
        res.write(json{{"error", "Case not found"}}.dump());
        return res;
    }
    res.set_header("Content-Type", "application/json");
    res.write(json{{"success", true}, {"message", "Case deleted"}}.dump());
    return res;
}

crow::response CaseCRUDRoutes::handle_update_status(const crow::request& req, const std::string& case_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    try {
        auto body = json::parse(req.body);
        if (body.contains("status")) {
            std::string s = body["status"];
            CaseStatus cs = CaseStatus::OPEN;
            if (s == "analysing") cs = CaseStatus::ANALYSING;
            else if (s == "completed") cs = CaseStatus::COMPLETED;
            else if (s == "failed") cs = CaseStatus::FAILED;
            case_manager_.update_status(case_id, cs);
        }
        if (body.contains("cross_analysis_job_id")) {
            case_manager_.set_cross_analysis_job(case_id, body["cross_analysis_job_id"]);
        }
        res.set_header("Content-Type", "application/json");
        res.write(case_to_json(case_manager_.get_case(case_id)).dump());
    } catch (const std::exception& e) {
        res.code = 400;
        res.write(json{{"error", e.what()}}.dump());
    }
    return res;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

json CaseCRUDRoutes::case_to_json(const ForensicCase& fc) const {
    auto epoch_ms = [](auto tp) {
        return std::chrono::duration_cast<std::chrono::milliseconds>(
            tp.time_since_epoch()).count();
    };
    return {
        {"id",                    fc.id},
        {"name",                  fc.name},
        {"description",           fc.description},
        {"task_ids",              fc.task_ids},
        {"status",                status_to_string(fc.status)},
        {"cross_analysis_job_id", fc.cross_analysis_job_id},
        {"created_at",            epoch_ms(fc.created_at)},
        {"updated_at",            epoch_ms(fc.updated_at)},
    };
}

std::string CaseCRUDRoutes::status_to_string(CaseStatus s) const {
    switch (s) {
        case CaseStatus::OPEN:      return "open";
        case CaseStatus::ANALYSING: return "analysing";
        case CaseStatus::COMPLETED: return "completed";
        case CaseStatus::FAILED:    return "failed";
    }
    return "open";
}

} // namespace forensics
