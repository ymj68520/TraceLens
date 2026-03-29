#include "TaskRoutes.h"
#include "TaskCRUDRoutes.h"
#include "TaskBatchRoutes.h"
#include "TaskMonitoringRoutes.h"
#include "RouteHelpers.h"

namespace forensics {

TaskRoutes::TaskRoutes(crow::App<>& app)
    : task_manager_(TaskManager::instance()),
      crud_routes_(app),
      batch_routes_(app),
      monitoring_routes_(app) {
    // Register CORS OPTIONS handlers for all task routes
    register_cors_handlers(app);

    // Route handlers are registered by the sub-route constructors
}

void TaskRoutes::register_cors_handlers(crow::App<>& app) {
    // CORS OPTIONS handlers for /tasks routes
    CROW_ROUTE(app, "/tasks").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/tasks/<string>").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/tasks/<string>/results").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    // CORS OPTIONS handlers for /api/tasks routes
    CROW_ROUTE(app, "/api/tasks/<string>/results").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/list").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/progress").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/statistics").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/cleanup").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-create").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-status").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/batch-cancel").methods("OPTIONS"_method)([](const crow::request& req){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/audit-log").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/priority").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });

    CROW_ROUTE(app, "/api/tasks/<string>/databases").methods("OPTIONS"_method)([](const crow::request& req, const std::string& task_id){
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        res.code = 204;
        return res;
    });
}

} // namespace forensics
