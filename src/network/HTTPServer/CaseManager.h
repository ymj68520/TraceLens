#pragma once
/**
 * CaseManager — singleton that stores and persists ForensicCase objects.
 *
 * Cases are persisted to   data/cases.json   (via PathManager).
 * Design intentionally mirrors TaskManager so integration is familiar.
 */
#include <string>
#include <map>
#include <vector>
#include <mutex>
#include <chrono>
#include <filesystem>

#include <boost/uuid/uuid.hpp>
#include <boost/uuid/uuid_generators.hpp>
#include <boost/uuid/uuid_io.hpp>
#include <nlohmann/json.hpp>

#include "HTTPServerDataTypes.h"

class CaseManager {
public:
    static CaseManager& instance() {
        static CaseManager inst;
        return inst;
    }

    ~CaseManager() = default;

    // ── CRUD ────────────────────────────────────────────────────────────────

    /** Create a new case. Returns the new case ID. */
    std::string create_case(const std::string& name,
                            const std::string& description,
                            const std::vector<std::string>& task_ids = {});

    /** Add a task ID to an existing case. */
    bool add_task(const std::string& case_id, const std::string& task_id);

    /** Retrieve a case by ID (returns empty if not found). */
    ForensicCase get_case(const std::string& case_id);

    /** Return all cases in creation order. */
    std::vector<ForensicCase> get_all_cases();

    /** Delete a case record (does NOT delete contained tasks). */
    bool delete_case(const std::string& case_id);

    // ── Status ──────────────────────────────────────────────────────────────

    /** Update the case status (e.g., ANALYSING → COMPLETED). */
    void update_status(const std::string& case_id, CaseStatus status);

    /** Store the Python cross-analysis job ID. */
    void set_cross_analysis_job(const std::string& case_id, const std::string& job_id);

    // ── Persistence ─────────────────────────────────────────────────────────

    void save_cases();
    void load_cases();

private:
    CaseManager();

    void save_cases_internal();

    std::string status_to_string(CaseStatus s) const;
    CaseStatus status_from_string(const std::string& s) const;

    std::map<std::string, ForensicCase> cases_;
    std::mutex mtx_;
};
