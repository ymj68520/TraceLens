#pragma once
#ifndef LLM_PYTHON_PROXY_H
#define LLM_PYTHON_PROXY_H

#include <string>
#include <functional>
#include <nlohmann/json.hpp>

namespace forensics {

/**
 * @brief Proxy for calling the Python LLM service via HTTP.
 * 
 * This replaces direct C++ LLM calls by forwarding requests to
 * the Python FastAPI service at port 8090.
 * 
 * The existing C++ LLMAnalysisService is preserved but deprecated.
 * New LLM analysis flows should use this proxy instead.
 */
class LLMPythonProxy {
public:
    LLMPythonProxy(const std::string& python_service_url = "http://localhost:8090");

    /**
     * @brief Start a full case analysis pipeline on the Python service.
     * 
     * This triggers:
     * 1. File filtering by case description
     * 2. Per-file LLM descriptions
     * 3. Final case report generation
     * 
     * @param task_id Task identifier
     * @param files_db_path Path to _files.db
     * @param case_description Case description text
     * @param max_filter_files Maximum number of files to select
     * @return Job ID for status polling, or empty string on failure
     */
    std::string startCaseAnalysis(
        const std::string& task_id,
        const std::string& files_db_path,
        const std::string& case_description,
        int max_filter_files = 200
    );

    /**
     * @brief Poll the status of a case analysis job.
     * 
     * @param job_id Job ID from startCaseAnalysis
     * @return JSON with status, current_step, detail fields
     */
    nlohmann::json getCaseAnalysisStatus(const std::string& job_id);

    /**
     * @brief Wait for a case analysis job to complete with progress callbacks.
     * 
     * @param job_id Job ID from startCaseAnalysis
     * @param progress_callback Called with (step, detail) on each poll
     * @param poll_interval_ms Polling interval in milliseconds
     * @param timeout_seconds Maximum wait time
     * @return true if completed successfully, false on failure/timeout
     */
    bool waitForCompletion(
        const std::string& job_id,
        std::function<void(const std::string& step, const std::string& detail)> progress_callback = nullptr,
        int poll_interval_ms = 3000,
        int timeout_seconds = 3600
    );

    /**
     * @brief Check if the Python LLM service is available
     * @return true if service responds to health check
     */
    bool isServiceAvailable();

    /**
     * @brief Delete knowledge graph data associated with a task
     * @param task_id Task identifier
     * @return true if deletion request succeeded or if it already didn't exist
     */
    bool deleteGraphitiData(const std::string& task_id);

private:
    std::string python_service_url_;
};

} // namespace forensics

#endif // LLM_PYTHON_PROXY_H
