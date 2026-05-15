// DLLAnalysisRoutes.cpp
// REST API endpoints for DLL analysis

#include "DLLAnalysisRoutes.h"
#include "RouteHelpers.h"
#include "analyzers/DLLAnalyzer/Core/DLLAnalyzer.h"
#include "analyzers/DLLAnalyzer/Database/DLLAnalysisDatabase.h"
#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"
#include "core/Logger/Logger.h"
#include <filesystem>
#include <future>
#include <chrono>
#include <system_error>
#include <sstream>

namespace forensics {

using json = nlohmann::json;

// Result wrapper for safe cross-thread DLL analysis results
struct AnalysisResult {
    bool success = false;
    dll::DLLAnalysisResult dllResult;
    std::string error;
};

DLLAnalysisRoutes::DLLAnalysisRoutes(crow::App<>& app) {
    // List all DLLs
    CROW_ROUTE(app, "/api/forensics/dlls").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_dll_list(req);
    });

    // Get DLL by ID
    CROW_ROUTE(app, "/api/forensics/dlls/<int>").methods("GET"_method)([this](const crow::request& req, int dll_id) {
        return handle_get_dll_by_id(req, dll_id);
    });

    // Get suspicious DLLs
    CROW_ROUTE(app, "/api/forensics/dlls/suspicious").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_suspicious_dlls(req);
    });

    // Get DLL statistics
    CROW_ROUTE(app, "/api/forensics/dlls/statistics").methods("GET"_method)([this](const crow::request& req) {
        return handle_get_dll_statistics(req);
    });

    // Get DLL anomalies
    CROW_ROUTE(app, "/api/forensics/dlls/<int>/anomalies").methods("GET"_method)([this](const crow::request& req, int dll_id) {
        return handle_get_dll_anomalies(req, dll_id);
    });

    // Analyze single DLL on-demand
    CROW_ROUTE(app, "/api/forensics/dlls/analyze").methods("POST"_method)([this](const crow::request& req) {
        return handle_analyze_single_dll(req);
    });

    // Health check endpoint
    CROW_ROUTE(app, "/api/forensics/dlls/health").methods("GET"_method)([](const crow::request& req) {
        crow::response res;
        RouteHelpers::add_cors_headers(res);
        json result = {
            {"status", "ok"},
            {"service", "dll-analyzer"},
            {"version", "1.0"},
            {"timestamp", std::time(nullptr)}
        };
        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
        return res;
    });
}

crow::response DLLAnalysisRoutes::handle_get_dll_list(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string dll_db_path = RouteHelpers::get_database_path(task_id, "dll");
        dll::DLLAnalysisDatabase db(dll_db_path);

        if (!db.initialize()) {
            json error = {{"error", "Failed to initialize DLL database"}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        int limit = 100;
        const char* limit_param = params.get("limit");
        if (limit_param) {
            limit = std::atoi(limit_param);
        }

        auto dlls = db.getAllDLLs(limit);

        json result = json::array();
        for (const auto& dll : dlls) {
            json dll_json;
            dll_json["id"] = dll.inode; // Using inode as temporary ID
            dll_json["file_path"] = dll.filePath;
            dll_json["file_name"] = dll.fileName;
            dll_json["file_size"] = dll.fileSize;
            dll_json["threat_score"] = dll.threatScore;
            dll_json["format"] = dll.peHeader.format;
            dll_json["machine_type"] = dll.peHeader.machine;
            dll_json["signature_status"] = dll.signatureStatus;
            result.push_back(dll_json);
        }

        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response DLLAnalysisRoutes::handle_get_dll_by_id(const crow::request& req, int64_t dll_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string dll_db_path = RouteHelpers::get_database_path(task_id, "dll");
        dll::DLLAnalysisDatabase db(dll_db_path);

        if (!db.initialize()) {
            json error = {{"error", "Failed to initialize DLL database"}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        auto dll = db.getDLLById(dll_id);
        if (!dll) {
            json error = {{"error", "DLL not found"}};
            res.code = 404;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        json dll_json;
        dll_json["id"] = dll->inode;
        dll_json["file_path"] = dll->filePath;
        dll_json["file_name"] = dll->fileName;
        dll_json["file_size"] = dll->fileSize;
        dll_json["md5"] = dll->md5Hash;
        dll_json["sha1"] = dll->sha1Hash;
        dll_json["sha256"] = dll->sha256Hash;
        dll_json["imp_hash"] = dll->impHash;
        dll_json["threat_score"] = dll->threatScore;
        dll_json["format"] = dll->peHeader.format;
        dll_json["machine_type"] = dll->peHeader.machine;
        dll_json["compile_timestamp"] = dll->peHeader.timestamp;
        dll_json["subsystem"] = dll->peHeader.subsystem;
        dll_json["entry_point"] = dll->peHeader.entryPointRVA;
        dll_json["image_base"] = dll->peHeader.imageBase;
        dll_json["is_dll"] = dll->peHeader.isDLL;
        dll_json["signature_status"] = dll->signatureStatus;
        dll_json["signer_name"] = dll->signerName;
        dll_json["file_version"] = dll->fileVersion;
        dll_json["company_name"] = dll->companyName;
        dll_json["llm_summary"] = dll->llmSummary;
        dll_json["llm_description"] = dll->llmDescription;
        dll_json["llm_keywords"] = dll->llmKeywords;

        // Sections
        json sections = json::array();
        for (const auto& section : dll->peHeader.sections) {
            json sec_json;
            sec_json["name"] = section.name;
            sec_json["virtual_address"] = section.virtualAddress;
            sec_json["virtual_size"] = section.virtualSize;
            sec_json["entropy"] = section.entropy;
            sec_json["is_writeable"] = section.isWriteable;
            sec_json["is_executable"] = section.isExecutable;
            sec_json["is_readable"] = section.isReadable;
            sections.push_back(sec_json);
        }
        dll_json["sections"] = sections;

        // Imports
        json imports = json::array();
        for (const auto& import : dll->imports) {
            json imp_json;
            imp_json["dll_name"] = import.name;
            imp_json["is_delayed"] = import.isDelayed;
            imp_json["functions"] = import.functions;
            imports.push_back(imp_json);
        }
        dll_json["imports"] = imports;

        // Exports
        json exports = json::array();
        for (const auto& export_func : dll->exports) {
            json exp_json;
            exp_json["name"] = export_func.name;
            exp_json["ordinal"] = export_func.ordinal;
            exp_json["rva"] = export_func.rva;
            exports.push_back(exp_json);
        }
        dll_json["exports"] = exports;

        // Anomalies
        json anomalies = json::array();
        for (const auto& anomaly : dll->anomalies) {
            json anom_json;
            anom_json["type"] = anomaly.type;
            anom_json["description"] = anomaly.description;
            anom_json["risk"] = static_cast<int>(anomaly.risk);
            anom_json["risk_score"] = anomaly.riskScore;
            anomalies.push_back(anom_json);
        }
        dll_json["anomalies"] = anomalies;

        res.set_header("Content-Type", "application/json");
        res.write(dll_json.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response DLLAnalysisRoutes::handle_get_suspicious_dlls(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string dll_db_path = RouteHelpers::get_database_path(task_id, "dll");
        dll::DLLAnalysisDatabase db(dll_db_path);

        if (!db.initialize()) {
            json error = {{"error", "Failed to initialize DLL database"}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        int limit = 100;
        const char* limit_param = params.get("limit");
        if (limit_param) {
            limit = std::atoi(limit_param);
        }

        int min_score = 30;
        const char* score_param = params.get("min_score");
        if (score_param) {
            min_score = std::atoi(score_param);
        }

        auto suspicious_dlls = db.getSuspiciousDLLs(limit);

        json result = json::array();
        for (const auto& dll : suspicious_dlls) {
            if (dll.threatScore >= min_score) {
                json dll_json;
                dll_json["file_path"] = dll.filePath;
                dll_json["file_name"] = dll.fileName;
                dll_json["threat_score"] = dll.threatScore;
                dll_json["signature_status"] = dll.signatureStatus;
                dll_json["anomaly_count"] = dll.anomalies.size();
                result.push_back(dll_json);
            }
        }

        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response DLLAnalysisRoutes::handle_get_dll_statistics(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string dll_db_path = RouteHelpers::get_database_path(task_id, "dll");
        dll::DLLAnalysisDatabase db(dll_db_path);

        if (!db.initialize()) {
            json error = {{"error", "Failed to initialize DLL database"}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        json stats;
        stats["total_dlls"] = db.getDLLCount();
        stats["suspicious_dlls"] = db.getSuspiciousCount();
        stats["average_threat_score"] = db.getAverageThreatScore();

        res.set_header("Content-Type", "application/json");
        res.write(stats.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response DLLAnalysisRoutes::handle_get_dll_anomalies(const crow::request& req, int64_t dll_id) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";

    if (task_id.empty()) {
        json error = {{"error", "task_id parameter is required"}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
        return res;
    }

    try {
        std::string dll_db_path = RouteHelpers::get_database_path(task_id, "dll");
        dll::DLLAnalysisDatabase db(dll_db_path);

        if (!db.initialize()) {
            json error = {{"error", "Failed to initialize DLL database"}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        auto anomalies = db.getAnomalies(dll_id);

        json result = json::array();
        for (const auto& anomaly : anomalies) {
            json anom_json;
            anom_json["type"] = anomaly.type;
            anom_json["description"] = anomaly.description;
            anom_json["risk"] = static_cast<int>(anomaly.risk);
            anom_json["risk_score"] = anomaly.riskScore;
            result.push_back(anom_json);
        }

        res.set_header("Content-Type", "application/json");
        res.write(result.dump());
    } catch (const std::exception& e) {
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }
    return res;
}

crow::response DLLAnalysisRoutes::handle_analyze_single_dll(const crow::request& req) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);

    try {
        // Parse request body
        auto body = json::parse(req.body);

        if (!body.contains("file_path") || !body["file_path"].is_string()) {
            json error = {{"error", "file_path is required"}};
            res.code = 400;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        std::string filePath = body["file_path"];

        // Validate file exists (distinguish not-found vs permission denied)
        std::error_code ec;
        bool exists = std::filesystem::exists(filePath, ec);
        if (!exists) {
            json error;
            if (ec == std::errc::permission_denied) {
                error = {{"error", "Permission denied"}, {"path", filePath}, {"code", "PERMISSION_DENIED"}};
                res.code = 403;
            } else {
                error = {{"error", "File not found"}, {"path", filePath}, {"code", "FILE_NOT_FOUND"}};
                res.code = 404;
            }
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        // Run analysis in async thread with 30-second timeout.
        // DLLAnalyzer is created inside the lambda so its lifecycle is
        // entirely contained within the worker thread -- no dangling
        // references possible if the timeout fires and the caller returns.
        auto future = std::async(std::launch::async, [filePath]() -> AnalysisResult {
            try {
                dll::DLLAnalyzer analyzer(":memory:");
                analyzer.enableAnomalyDetection(true);
                analyzer.enableSignatureVerification(false);

                if (!analyzer.initialize()) {
                    return {false, {}, "Failed to initialize DLL analyzer"};
                }

                if (!analyzer.analyzeSingleFile(filePath, 0)) {
                    return {false, {}, "Failed to analyze DLL: " + filePath};
                }

                auto db = analyzer.getDatabase();
                auto result = db->getDLLByPath(filePath);
                if (!result) {
                    return {false, {}, "Analysis completed but no result found"};
                }

                return {true, *result, ""};
            } catch (const std::exception& e) {
                return {false, {}, e.what()};
            }
        });

        if (future.wait_for(std::chrono::seconds(30)) != std::future_status::ready) {
            LOG_ERROR("Analysis timeout for: " + filePath);
            json error = {{"error", "Analysis timeout after 30 seconds"}, {"path", filePath}};
            res.code = 408; // Request Timeout
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        AnalysisResult analysisResult = future.get();
        if (!analysisResult.success) {
            LOG_ERROR("Failed to analyze DLL: " + filePath + " - " + analysisResult.error);
            json error = {{"error", analysisResult.error}, {"path", filePath}};
            res.code = 500;
            res.set_header("Content-Type", "application/json");
            res.write(error.dump());
            return res;
        }

        const auto& dllResult = analysisResult.dllResult;

        // Convert to JSON response
        json dllJson;
        dllJson["success"] = true;
        dllJson["file_path"] = dllResult.filePath;
        dllJson["file_name"] = dllResult.fileName;
        dllJson["file_size"] = dllResult.fileSize;
        dllJson["format"] = dllResult.peHeader.format;
        dllJson["machine_type"] = static_cast<int>(dllResult.peHeader.machine);
        dllJson["threat_score"] = dllResult.threatScore;
        dllJson["signature_status"] = dllResult.signatureStatus;
        dllJson["md5"] = dllResult.md5Hash;
        dllJson["sha1"] = dllResult.sha1Hash;
        dllJson["sha256"] = dllResult.sha256Hash;
        dllJson["imp_hash"] = dllResult.impHash;
        dllJson["compile_timestamp"] = dllResult.peHeader.timestamp;
        dllJson["entry_point"] = dllResult.peHeader.entryPointRVA;
        dllJson["image_base"] = dllResult.peHeader.imageBase;
        dllJson["subsystem"] = dllResult.peHeader.subsystem;
        dllJson["signer_name"] = dllResult.signerName;
        dllJson["file_version"] = dllResult.fileVersion;
        dllJson["company_name"] = dllResult.companyName;
        dllJson["llm_summary"] = dllResult.llmSummary;
        dllJson["llm_description"] = dllResult.llmDescription;
        dllJson["llm_keywords"] = dllResult.llmKeywords;

        // Sections
        json sections = json::array();
        for (const auto& section : dllResult.peHeader.sections) {
            json secJson;
            secJson["name"] = section.name;
            secJson["virtual_address"] = section.virtualAddress;
            secJson["virtual_size"] = section.virtualSize;
            secJson["entropy"] = section.entropy;
            secJson["is_writeable"] = section.isWriteable;
            secJson["is_executable"] = section.isExecutable;
            secJson["is_readable"] = section.isReadable;
            sections.push_back(secJson);
        }
        dllJson["sections"] = sections;

        // Imports
        json imports = json::array();
        for (const auto& import : dllResult.imports) {
            json impJson;
            impJson["dll_name"] = import.name;
            impJson["is_delayed"] = import.isDelayed;
            impJson["functions"] = import.functions;
            imports.push_back(impJson);
        }
        dllJson["imports"] = imports;

        // Exports
        json exports = json::array();
        for (const auto& exp : dllResult.exports) {
            json expJson;
            expJson["name"] = exp.name;
            expJson["ordinal"] = exp.ordinal;
            expJson["rva"] = exp.rva;
            exports.push_back(expJson);
        }
        dllJson["exports"] = exports;

        // Anomalies
        json anomalies = json::array();
        for (const auto& anomaly : dllResult.anomalies) {
            json anomJson;
            anomJson["type"] = anomaly.type;
            anomJson["description"] = anomaly.description;
            anomJson["risk"] = static_cast<int>(anomaly.risk);
            anomJson["risk_score"] = anomaly.riskScore;
            anomalies.push_back(anomJson);
        }
        dllJson["anomalies"] = anomalies;

        res.set_header("Content-Type", "application/json");
        res.write(dllJson.dump());

        LOG_INFO("Successfully analyzed DLL: " + filePath);
    } catch (const nlohmann::json::parse_error& e) {
        LOG_ERROR("JSON parse error in DLL analysis: " + std::string(e.what()));
        json error = {{"error", "Invalid JSON: " + std::string(e.what())}};
        res.code = 400;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    } catch (const std::exception& e) {
        LOG_ERROR("Exception in DLL analysis: " + std::string(e.what()));
        json error = {{"error", e.what()}};
        res.code = 500;
        res.set_header("Content-Type", "application/json");
        res.write(error.dump());
    }

    return res;
}

} // namespace forensics

