#include "LLMPythonProxy.h"
#include <httplib.h>
#include <iostream>
#include <thread>
#include <chrono>

namespace forensics {

LLMPythonProxy::LLMPythonProxy(const std::string& python_service_url)
    : python_service_url_(python_service_url) {}

std::string LLMPythonProxy::startCaseAnalysis(
    const std::string& task_id,
    const std::string& files_db_path,
    const std::string& case_description,
    int max_filter_files)
{
    try {
        httplib::Client cli(python_service_url_);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(30);

        nlohmann::json body = {
            {"task_id", task_id},
            {"files_db_path", files_db_path},
            {"case_description", case_description},
            {"max_filter_files", max_filter_files}
        };

        auto res = cli.Post("/api/llm/case-analysis", body.dump(), "application/json");

        if (res && res->status == 200) {
            auto response = nlohmann::json::parse(res->body);
            if (response.contains("job_id")) {
                return response["job_id"].get<std::string>();
            }
        }

        if (res) {
            std::cerr << "LLMPythonProxy::startCaseAnalysis failed: HTTP " 
                      << res->status << " - " << res->body << std::endl;
        } else {
            std::cerr << "LLMPythonProxy::startCaseAnalysis failed: connection error" << std::endl;
        }
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::startCaseAnalysis exception: " << e.what() << std::endl;
    }

    return "";
}

nlohmann::json LLMPythonProxy::getCaseAnalysisStatus(const std::string& job_id) {
    try {
        httplib::Client cli(python_service_url_);
        cli.set_connection_timeout(10);
        cli.set_read_timeout(15);

        auto res = cli.Get(("/api/llm/case-analysis/" + job_id).c_str());

        if (res && res->status == 200) {
            return nlohmann::json::parse(res->body);
        }
    } catch (const std::exception& e) {
        std::cerr << "LLMPythonProxy::getCaseAnalysisStatus exception: " << e.what() << std::endl;
    }

    return {{"status", "error"}, {"detail", "Failed to get status"}};
}

bool LLMPythonProxy::waitForCompletion(
    const std::string& job_id,
    std::function<void(const std::string& step, const std::string& detail)> progress_callback,
    int poll_interval_ms,
    int timeout_seconds)
{
    auto start = std::chrono::steady_clock::now();
    auto timeout = std::chrono::seconds(timeout_seconds);

    while (true) {
        auto elapsed = std::chrono::steady_clock::now() - start;
        if (elapsed > timeout) {
            std::cerr << "LLMPythonProxy: Timeout waiting for analysis completion" << std::endl;
            return false;
        }

        auto status = getCaseAnalysisStatus(job_id);
        std::string state = status.value("status", "unknown");

        if (progress_callback) {
            std::string step = status.value("current_step", "");
            std::string detail = status.value("detail", "");
            progress_callback(step, detail);
        }

        if (state == "completed") {
            return true;
        } else if (state == "failed" || state == "error") {
            std::cerr << "LLMPythonProxy: Analysis failed - " 
                      << status.value("detail", "unknown error") << std::endl;
            return false;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(poll_interval_ms));
    }
}

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

} // namespace forensics
