#include "TaskRoutes.h"
#include "TaskCRUDRoutes.h"
#include "TaskBatchRoutes.h"
#include "TaskMonitoringRoutes.h"

namespace forensics {

TaskRoutes::TaskRoutes(crow::App<>& app) : task_manager_(TaskManager::instance()) {
    // Register CORS OPTIONS handlers for all task routes
    register_cors_handlers(app);

    // Register route handlers from specialized classes
    TaskCRUDRoutes crud_routes(app);
    TaskBatchRoutes batch_routes(app);
    TaskMonitoringRoutes monitoring_routes(app);
}

void TaskRoutes::register_cors_handlers(crow::App<>& app) {
    // CORS OPTIONS handlers for /tasks routes
    CROW_ROUTE(app, "/tasks").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/tasks/<string>").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/tasks/<string>/results").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    // CORS OPTIONS handlers for /api/tasks routes
    CROW_ROUTE(app, "/api/tasks/<string>/results").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/list").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/progress").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/statistics").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/cleanup").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-create").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-status").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-cancel").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/audit-log").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/priority").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        add_cors_headers(res);
        res.code = 204;
        return res;
    });
}

void TaskRoutes::add_cors_headers(crow::response& res) {
    res.set_header("Access-Control-Allow-Origin", "*");
    res.set_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
    res.set_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With");
}

} // namespace forensics
