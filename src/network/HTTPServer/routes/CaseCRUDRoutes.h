#pragma once
/**
 * CaseCRUDRoutes — REST API for ForensicCase management.
 *
 * Routes:
 *   GET    /api/cases                 — list all cases
 *   POST   /api/cases                 — create case (+ optional task_ids)
 *   GET    /api/cases/<id>            — get case detail
 *   PUT    /api/cases/<id>/tasks      — add task_ids to an existing case
 *   DELETE /api/cases/<id>            — delete case record
 *   PUT    /api/cases/<id>/status     — update cross-analysis status/job
 */
#include <crow.h>
#include "CaseManager.h"
#include "routes/RouteHelpers.h"

namespace forensics {

class CaseCRUDRoutes {
public:
    explicit CaseCRUDRoutes(crow::App<>& app);

private:
    CaseManager& case_manager_;

    crow::response handle_list_cases(const crow::request& req);
    crow::response handle_create_case(const crow::request& req);
    crow::response handle_get_case(const crow::request& req, const std::string& case_id);
    crow::response handle_add_tasks(const crow::request& req, const std::string& case_id);
    crow::response handle_delete_case(const crow::request& req, const std::string& case_id);
    crow::response handle_update_status(const crow::request& req, const std::string& case_id);

    nlohmann::json case_to_json(const ForensicCase& fc) const;
    std::string status_to_string(CaseStatus s) const;
};

} // namespace forensics
