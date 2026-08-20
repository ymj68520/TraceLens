#include "LLMPythonProxy.h"
#include <httplib.h>
#include <iostream>
#include <thread>
#include <chrono>

namespace forensics {

LLMPythonProxy::LLMPythonProxy(const std::string& python_service_url)
    : python_service_url_(python_service_url) {}

bool LLMPythonProxy::isServiceAvailable() {
    try {
        httplib::Client cli(python_service_url_);
        cli.set_connection_timeout(5);
        cli.set_read_timeout(5);

        auto res = cli.Get("/health");
        return res && res->status == 200;
    } catch (...) {
        return false;
    }
}

bool LLMPythonProxy::deleteGraphitiData(const std::string& task_id) {
    try {
        httplib::Client cli(python_service_url_);
        cli.set_connection_timeout(5);
        cli.set_read_timeout(10);

        nlohmann::json body = {
            {"task_id", task_id}
        };

        auto res = cli.Delete(("/api/graphiti/tasks/" + task_id).c_str(), body.dump(), "application/json");
        if (res && (res->status == 200 || res->status == 404)) {
            return true; // Return true if deleted or didn't exist
        }
    } catch (...) {
        // Fall back gracefully
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
        cli.set_connection_timeout(10);
        cli.set_read_timeout(30);

        nlohmann::json body = {
            {"task_id", task_id},
            {"mode", to_string(mode)}
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
                      << res->status << " - " << res->body << std::endl;
        } else {
            std::cerr << "LLMPythonProxy::async_ingest failed: connection error" << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::async_ingest exception: " << e.what() << std::endl;
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
                      << res->status << " - " << res->body << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::async_ingest_file exception: " << e.what() << std::endl;
    }

    return "";
}

std::string LLMPythonProxy::async_ingest_events(
    const std::string& task_id,
    const nlohmann::json& events)
{
    try {
        httplib::Client cli(python_service_url_);
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
                      << res->status << " - " << res->body << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::async_ingest_events exception: " << e.what() << std::endl;
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
        cli.set_connection_timeout(5);
        cli.set_read_timeout(10);

        auto res = cli.Get(("/api/graphiti/jobs/" + job_id).c_str());

        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            status.status = response.value("status", "unknown");
            status.progress = response.value("progress", 0);
            status.current_phase = response.value("current_phase", "");
            status.created_at = response.value("created_at", "");
            status.started_at = response.value("started_at", "");
            status.completed_at = response.value("completed_at", "");
            status.error = response.value("error", "");

            if (response.contains("result")) {
                status.result = response["result"];
            }
        } else {
            status.status = "not_found";
        }
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::get_job_status exception: " << e.what() << std::endl;
        status.status = "error";
        status.error = e.what();
    }

    return status;
}

bool LLMPythonProxy::cancel_job(const std::string& job_id) {
    try {
        httplib::Client cli(python_service_url_);
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
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::cancel_job exception: " << e.what() << std::endl;
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
                std::cerr << "LLMPythonProxy: Job failed - " << status.error << std::endl;
            }
            return false;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(poll_interval_ms));
    }
}

} // namespace forensics
