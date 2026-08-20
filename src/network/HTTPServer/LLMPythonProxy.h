#pragma once
#ifndef LLM_PYTHON_PROXY_H
#define LLM_PYTHON_PROXY_H

#include <string>
#include <functional>
#include <nlohmann/json.hpp>
#include "ConfigManager/ConfigManager.h"

namespace forensics {

/**
 * @brief Ingestion mode for Graphiti operations.
 */
enum class IngestionMode {
    FULL,           // Ingest files, events, and all platform data with File entities
    FILES_ONLY,     // Update file entities only (skip events)
    EVENTS_ONLY,    // Sync events to existing files
    SINGLE_FILE     // Single file update
};

/**
 * @brief Convert IngestionMode to string.
 */
inline std::string to_string(IngestionMode mode) {
    switch (mode) {
        case IngestionMode::FULL: return "full";
        case IngestionMode::FILES_ONLY: return "files_only";
        case IngestionMode::EVENTS_ONLY: return "events_only";
        case IngestionMode::SINGLE_FILE: return "single_file";
        default: return "full";
    }
}

/**
 * @brief Job status from Graphiti ingestion.
 */
struct JobStatus {
    std::string job_id;
    std::string status;       // PENDING, RUNNING, COMPLETED, FAILED, CANCELLED
    int progress = 0;         // 0-100
    std::string current_phase;
    std::string created_at;
    std::string started_at;
    std::string completed_at;
    std::string error;
    nlohmann::json result;

    bool is_complete() const {
        return status == "COMPLETED" || status == "FAILED" || status == "CANCELLED";
    }
};

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
    /**
     * @brief Get the singleton instance of LLMPythonProxy.
     */
    static LLMPythonProxy& instance() {
        static LLMPythonProxy instance(ConfigManager::instance().getPythonServiceUrl());
        return instance;
    }

private:
    LLMPythonProxy(const std::string& python_service_url);

public:
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

    // ========================================================================
    // Graphiti Integration Methods
    // ========================================================================

    /**
     * @brief Trigger Graphiti ingestion for a task (fire-and-forget).
     *
     * This is a non-blocking call that queues the ingestion job.
     * Use getJobStatus() to poll for completion.
     *
     * @param task_id Task identifier
     * @param mode Ingestion mode (full, files_only, events_only)
     * @return Job ID for status tracking, or empty string on failure
     */
    std::string async_ingest(
        const std::string& task_id,
        IngestionMode mode = IngestionMode::FULL
    );

    /**
     * @brief Ingest or update a single file in the knowledge graph.
     *
     * @param file_id Database ID of the file
     * @param task_id Task identifier
     * @param force_reanalysis Trigger LLM re-analysis before ingest
     * @return Job ID for status tracking, or empty string on failure
     */
    std::string async_ingest_file(
        int64_t file_id,
        const std::string& task_id,
        bool force_reanalysis = false
    );

    /**
     * @brief Sync timeline events to the knowledge graph.
     *
     * @param task_id Task identifier
     * @param events List of event JSON objects
     * @return Job ID for status tracking, or empty string on failure
     */
    std::string async_ingest_events(
        const std::string& task_id,
        const nlohmann::json& events
    );

    /**
     * @brief Query the status of an ingestion job.
     *
     * @param job_id Job ID from async_ingest or related methods
     * @return JobStatus with current state, or empty status on failure
     */
    JobStatus get_job_status(const std::string& job_id);

    /**
     * @brief Cancel a running or pending ingestion job.
     *
     * @param job_id Job ID to cancel
     * @return true if cancelled, false if job not found or already complete
     */
    bool cancel_job(const std::string& job_id);

    /**
     * @brief Wait for an ingestion job to complete with progress callbacks.
     *
     * @param job_id Job ID from async_ingest or related methods
     * @param progress_callback Called with (progress_percent, phase) on each poll
     * @param poll_interval_ms Polling interval in milliseconds
     * @param timeout_seconds Maximum wait time
     * @return true if completed successfully, false on failure/timeout
     */
    bool wait_for_job_completion(
        const std::string& job_id,
        std::function<void(int progress, const std::string& phase)> progress_callback = nullptr,
        int poll_interval_ms = 3000,
        int timeout_seconds = 3600
    );

private:
    std::string python_service_url_;
    std::string _post(const std::string& endpoint, const nlohmann::json& payload);
    nlohmann::json _get(const std::string& endpoint);
    nlohmann::json _delete(const std::string& endpoint);
};

} // namespace forensics

#endif // LLM_PYTHON_PROXY_H
