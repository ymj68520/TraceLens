#include "CaseManager.h"
#include "PathManager/PathManager.h"
#include <fstream>
#include <iostream>

// ── Constructor / load ────────────────────────────────────────────────────────

CaseManager::CaseManager() {
    load_cases();
}

// ── CRUD ─────────────────────────────────────────────────────────────────────

std::string CaseManager::create_case(const std::string& name,
                                     const std::string& description,
                                     const std::vector<std::string>& task_ids) {
    std::lock_guard<std::mutex> lock(mtx_);

    boost::uuids::uuid uuid = boost::uuids::random_generator()();
    std::string id = boost::uuids::to_string(uuid);

    ForensicCase fc;
    fc.id          = id;
    fc.name        = name;
    fc.description = description;
    fc.task_ids    = task_ids;
    fc.status      = CaseStatus::OPEN;
    fc.created_at  = std::chrono::system_clock::now();
    fc.updated_at  = fc.created_at;

    cases_[id] = fc;
    save_cases_internal();
    return id;
}

bool CaseManager::add_task(const std::string& case_id, const std::string& task_id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (!cases_.count(case_id)) return false;
    auto& fc = cases_[case_id];
    // Avoid duplicates
    if (std::find(fc.task_ids.begin(), fc.task_ids.end(), task_id) == fc.task_ids.end()) {
        fc.task_ids.push_back(task_id);
        fc.updated_at = std::chrono::system_clock::now();
        save_cases_internal();
    }
    return true;
}

ForensicCase CaseManager::get_case(const std::string& case_id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (cases_.count(case_id)) return cases_[case_id];
    return {};
}

std::vector<ForensicCase> CaseManager::get_all_cases() {
    std::lock_guard<std::mutex> lock(mtx_);
    std::vector<ForensicCase> result;
    result.reserve(cases_.size());
    for (const auto& [id, fc] : cases_) result.push_back(fc);
    return result;
}

bool CaseManager::delete_case(const std::string& case_id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (!cases_.count(case_id)) return false;
    cases_.erase(case_id);
    save_cases_internal();
    return true;
}

// ── Status ────────────────────────────────────────────────────────────────────

void CaseManager::update_status(const std::string& case_id, CaseStatus status) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (!cases_.count(case_id)) return;
    cases_[case_id].status     = status;
    cases_[case_id].updated_at = std::chrono::system_clock::now();
    save_cases_internal();
}

void CaseManager::set_cross_analysis_job(const std::string& case_id, const std::string& job_id) {
    std::lock_guard<std::mutex> lock(mtx_);
    if (!cases_.count(case_id)) return;
    cases_[case_id].cross_analysis_job_id = job_id;
    cases_[case_id].updated_at            = std::chrono::system_clock::now();
    save_cases_internal();
}

// ── Persistence ───────────────────────────────────────────────────────────────

static std::filesystem::path cases_json_path() {
    return forensics::PathManager::instance().getDataDir() / "cases.json";
}

void CaseManager::save_cases() {
    std::lock_guard<std::mutex> lock(mtx_);
    save_cases_internal();
}

void CaseManager::save_cases_internal() {
    using json = nlohmann::json;
    try {
        json arr = json::array();
        for (const auto& [id, fc] : cases_) {
            auto epoch_ms = [](auto tp) {
                return std::chrono::duration_cast<std::chrono::milliseconds>(
                    tp.time_since_epoch()).count();
            };
            json j;
            j["id"]                    = fc.id;
            j["name"]                  = fc.name;
            j["description"]           = fc.description;
            j["task_ids"]              = fc.task_ids;
            j["status"]                = status_to_string(fc.status);
            j["cross_analysis_job_id"] = fc.cross_analysis_job_id;
            j["created_at"]            = epoch_ms(fc.created_at);
            j["updated_at"]            = epoch_ms(fc.updated_at);
            arr.push_back(j);
        }
        auto path = cases_json_path();
        std::filesystem::create_directories(path.parent_path());
        std::ofstream ofs(path);
        ofs << arr.dump(2);
    } catch (const std::exception& e) {
        std::cerr << "[CaseManager] Save failed: " << e.what() << std::endl;
    }
}

void CaseManager::load_cases() {
    using json = nlohmann::json;
    auto path = cases_json_path();
    if (!std::filesystem::exists(path)) return;
    try {
        std::ifstream ifs(path);
        json arr = json::parse(ifs);
        for (const auto& j : arr) {
            ForensicCase fc;
            fc.id                    = j.value("id", "");
            fc.name                  = j.value("name", "");
            fc.description           = j.value("description", "");
            fc.task_ids              = j.value("task_ids", std::vector<std::string>{});
            fc.status                = status_from_string(j.value("status", "open"));
            fc.cross_analysis_job_id = j.value("cross_analysis_job_id", "");
            auto ms_to_tp = [](long long ms) {
                return std::chrono::system_clock::time_point{std::chrono::milliseconds{ms}};
            };
            fc.created_at = ms_to_tp(j.value("created_at", 0LL));
            fc.updated_at = ms_to_tp(j.value("updated_at", 0LL));
            if (!fc.id.empty()) cases_[fc.id] = fc;
        }
    } catch (const std::exception& e) {
        std::cerr << "[CaseManager] Load failed: " << e.what() << std::endl;
    }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

std::string CaseManager::status_to_string(CaseStatus s) const {
    switch (s) {
        case CaseStatus::OPEN:      return "open";
        case CaseStatus::ANALYSING: return "analysing";
        case CaseStatus::COMPLETED: return "completed";
        case CaseStatus::FAILED:    return "failed";
    }
    return "open";
}

CaseStatus CaseManager::status_from_string(const std::string& s) const {
    if (s == "analysing") return CaseStatus::ANALYSING;
    if (s == "completed") return CaseStatus::COMPLETED;
    if (s == "failed")    return CaseStatus::FAILED;
    return CaseStatus::OPEN;
}
