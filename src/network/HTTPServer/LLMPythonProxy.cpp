#include "LLMPythonProxy.h"
#include <httplib.h>
#include <iostream>
#include <thread>
#include <chrono>
#include <cstdlib>

namespace forensics {

namespace {
void configure_field_client(httplib::Client& client) {
    const char* mode = std::getenv("TRACELENS_FIELD_AUTH");
    if (!mode || std::string(mode) != "enabled") return;
    const char* token = std::getenv("FIELD_CPP_TO_PYTHON_TOKEN");
    client.set_default_headers({{"X-TraceLens-Service-Token", token ? token : ""}});
}
}

LLMPythonProxy::LLMPythonProxy(const std::string& python_service_url)
    : python_service_url_(python_service_url) {}

bool LLMPythonProxy::isServiceAvailable() {
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(5);
        cli.set_read_timeout(5);

        auto res = cli.Get("/health");
        return res && res->status == 200;
    } catch (...) {
        return false;
    }
}

bool LLMPythonProxy::recordFileAnalysisResult(
    const std::string& task_id,
    const std::string& files_db_path,
    const std::string& file_path,
    const std::string& description,
    const std::string& summary,
    const std::string& keywords,
    const std::string& model_used) {
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(5);
        // Descriptions can be long; the server-side write itself is a local
        // SQLite three-write (WAL, milliseconds).
        cli.set_read_timeout(30);

        nlohmann::json body = {
            {"task_id", task_id},
            {"file_path", file_path},
            {"description", description},
            {"summary", summary},
            {"keywords", keywords},
            {"model_used", model_used},
        };

        // The file-analysis endpoint family lives under the /api/llm router
        // (routes/llm.py includes file_analysis.router); /api/file-analysis/record
        // has never existed and 404s into the direct-file-db fallback.
        auto res = cli.Post("/api/llm/file-analysis/record", body.dump(), "application/json");
        if (res && res->status == 200) {
            try {
                auto response = nlohmann::json::parse(res->body);
                return response.value("persisted", false);
            } catch (const std::exception&) {
                return false;
            }
        }
        if (res) {
            std::cerr << "LLMPythonProxy::recordFileAnalysisResult failed: HTTP "
                      << res->status << std::endl;
        }
    } catch (const std::exception&) {
        std::cerr << "LLMPythonProxy::recordFileAnalysisResult exception" << std::endl;
    }
    return false;
}

bool LLMPythonProxy::deleteGraphitiData(const std::string& task_id) {
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(5);
        // The Python side gives DETACH DELETE on a whole task graph up to 60s
        // (_status.py delete_task_graph). A shorter client timeout abandoned a
        // still-running purge and reported success, leaving the graph behind.
        cli.set_read_timeout(90);

        nlohmann::json body = {
            {"task_id", task_id}
        };

        auto res = cli.Delete(("/api/graphiti/tasks/" + task_id).c_str(), body.dump(), "application/json");
        if (res && (res->status == 200 || res->status == 404)) {
            return true; // Return true if deleted or didn't exist
        }
        if (res) {
            std::cerr << "deleteGraphitiData failed for task " << task_id
                      << ": HTTP " << res->status << std::endl;
        } else {
            std::cerr << "deleteGraphitiData failed for task " << task_id
                      << ": " << httplib::to_string(res.error()) << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "deleteGraphitiData exception for task " << task_id
                  << ": " << e.what() << std::endl;
    }
    return false;
}

bool LLMPythonProxy::deleteTaskReportData(const std::string& task_id) {
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(5);
        // Cascading over report versions also removes published snapshot
        // trees; allow more than the per-graph ceiling.
        cli.set_read_timeout(120);

        auto res = cli.Delete(("/api/reports/tasks/" + task_id).c_str());
        if (res && (res->status == 200 || res->status == 404)) {
            return true;
        }
        if (res) {
            std::cerr << "deleteTaskReportData failed for task " << task_id
                      << ": HTTP " << res->status << " " << res->body << std::endl;
        } else {
            std::cerr << "deleteTaskReportData failed for task " << task_id
                      << ": " << httplib::to_string(res.error()) << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "deleteTaskReportData exception for task " << task_id
                  << ": " << e.what() << std::endl;
    }
    return false;
}

// ========================================================================
// Graphiti Integration Methods
// ========================================================================

std::string LLMPythonProxy::async_ingest(
    const std::string& task_id,
    IngestionMode mode)
{
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(30);

        nlohmann::json body = {
            {"task_id", task_id},
            {"mode", to_string(mode)},
            // Marks the initial analysis pipeline as the trigger so the
            // Python worker fires the report tail for ANALYZED_ONLY jobs;
            // manual UI re-ingests leave it unset and skip the tail.
            {"trigger_source", "pipeline"}
        };

        auto res = cli.Post("/api/graphiti/ingest", body.dump(), "application/json");

        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            if (response.contains("job_id")) {
                std::string job_id = response["job_id"].get<std::string>();
                std::cout << "LLMPythonProxy: Triggered Graphiti ingestion for task "
                          << task_id << ", job_id: " << job_id << std::endl;
                return job_id;
            }
        }

        if (res) {
            std::cerr << "LLMPythonProxy::async_ingest failed: HTTP "
                      << res->status << std::endl;
        } else {
            std::cerr << "LLMPythonProxy::async_ingest failed: connection error" << std::endl;
        }
    } catch (const std::exception&) {
        std::cerr << "LLMPythonProxy::async_ingest exception" << std::endl;
    }

    return "";
}

std::string LLMPythonProxy::async_ingest_file(
    int64_t file_id,
    const std::string& task_id,
    bool force_reanalysis)
{
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(30);

        nlohmann::json body = {
            {"file_id", file_id},
            {"task_id", task_id},
            {"update_analysis", force_reanalysis}
        };

        auto res = cli.Post("/api/graphiti/ingest/file", body.dump(), "application/json");

        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            if (response.contains("job_id")) {
                return response["job_id"].get<std::string>();
            }
        }

        if (res) {
            std::cerr << "LLMPythonProxy::async_ingest_file failed: HTTP "
                      << res->status << std::endl;
        }
    } catch (const std::exception&) {
        std::cerr << "LLMPythonProxy::async_ingest_file exception" << std::endl;
    }

    return "";
}

std::string LLMPythonProxy::async_ingest_events(
    const std::string& task_id,
    const nlohmann::json& events)
{
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(30);

        nlohmann::json body = {
            {"task_id", task_id},
            {"events", events}
        };

        auto res = cli.Post("/api/graphiti/ingest/events", body.dump(), "application/json");

        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            if (response.contains("job_id")) {
                return response["job_id"].get<std::string>();
            }
        }

        if (res) {
            std::cerr << "LLMPythonProxy::async_ingest_events failed: HTTP "
                      << res->status << std::endl;
        }
    } catch (const std::exception&) {
        std::cerr << "LLMPythonProxy::async_ingest_events exception" << std::endl;
    }

    return "";
}

JobStatus LLMPythonProxy::get_job_status(const std::string& job_id) {
    JobStatus status;
    status.job_id = job_id;
    status.status = "unknown";
    status.progress = 0;
    status.current_phase = "unknown";

    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(5);
        cli.set_read_timeout(10);

        auto res = cli.Get(("/api/graphiti/jobs/" + job_id).c_str());

        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            status.status = response.value("status", "unknown");
            status.progress = response.value("progress", 0);
            status.current_phase = response.value("current_phase", "");
            status.created_at = response.value("created_at", "");
            status.started_at = response.contains("started_at") && response["started_at"].is_string()
                ? response["started_at"].get<std::string>() : "";
            status.completed_at = response.contains("completed_at") && response["completed_at"].is_string()
                ? response["completed_at"].get<std::string>() : "";
            // The python job endpoint returns "error": null on success;
            // value("error", "") would throw type_error.302 on null and lose
            // the whole status (surfaced live by the FINALIZING wait loop).
            if (response.contains("error") && !response["error"].is_null()
                && response["error"].is_string()) {
                status.error = response["error"].get<std::string>();
            }

            if (response.contains("result")) {
                status.result = response["result"];
            }
        } else {
            status.status = "not_found";
        }
    } catch (const std::exception&) {
        std::cerr << "LLMPythonProxy::get_job_status exception" << std::endl;
        status.status = "error";
        status.error = "backend_exception";
    }

    return status;
}

bool LLMPythonProxy::cancel_job(const std::string& job_id) {
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(5);
        cli.set_read_timeout(10);

        auto res = cli.Delete(("/api/graphiti/jobs/" + job_id).c_str());

        if (res) {
            if (res->status == 200) {
                auto response = nlohmann::json::parse(res->body);
                return response.value("success", false);
            } else if (res->status == 404) {
                return false; // Job not found
            }
        }
    } catch (const std::exception&) {
        std::cerr << "LLMPythonProxy::cancel_job exception" << std::endl;
    }

    return false;
}

bool LLMPythonProxy::wait_for_job_completion(
    const std::string& job_id,
    std::function<void(int progress, const std::string& phase)> progress_callback,
    int poll_interval_ms,
    int timeout_seconds)
{
    auto start = std::chrono::steady_clock::now();
    auto timeout = std::chrono::seconds(timeout_seconds);

    while (true) {
        auto elapsed = std::chrono::steady_clock::now() - start;
        if (elapsed > timeout) {
            std::cerr << "LLMPythonProxy: Timeout waiting for job completion" << std::endl;
            return false;
        }

        JobStatus status = get_job_status(job_id);

        if (progress_callback) {
            progress_callback(status.progress, status.current_phase);
        }

        if (status.status == "COMPLETED") {
            return true;
        } else if (status.status == "FAILED" || status.status == "CANCELLED" || status.status == "not_found") {
            if (!status.error.empty()) {
                std::cerr << "LLMPythonProxy: Job failed" << std::endl;
            }
            return false;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(poll_interval_ms));
    }
}

bool LLMPythonProxy::trigger_report_tail(const std::string& task_id) {
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(60);
        nlohmann::json body = {{"task_id", task_id}, {"requested_by", "pipeline"}};
        auto res = cli.Post("/api/reports/pipeline-tail", body.dump(), "application/json");
        if (res && (res->status == 200 || res->status == 202)) {
            auto response = nlohmann::json::parse(res->body);
            const std::string state = response.value("state", "");
            return state == "running" || state == "completed";
        }
    } catch (...) {
    }
    return false;
}

LLMPythonProxy::ReportTailStatus LLMPythonProxy::get_report_tail_status(const std::string& task_id) {
    ReportTailStatus status;
    status.state = "unknown";
    try {
        httplib::Client cli(python_service_url_);
        configure_field_client(cli);
        cli.set_connection_timeout(5);
        cli.set_read_timeout(15);
        auto res = cli.Get(("/api/reports/pipeline-tail/status?task_id=" + task_id).c_str());
        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            status.state = response.value("state", "unknown");
            status.generation_id = response.contains("generation_id") && response["generation_id"].is_string()
                ? response["generation_id"].get<std::string>() : "";
            status.report_id = response.contains("report_id") && response["report_id"].is_string()
                ? response["report_id"].get<std::string>() : "";
            status.error_code = response.contains("error_code") && response["error_code"].is_string()
                ? response["error_code"].get<std::string>() : "";
        }
    } catch (...) {
    }
    return status;
}

} // namespace forensics
