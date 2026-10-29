// TaskManagerAnalysis.cpp
// TaskManager::start_analysis — pipeline orchestration for a single forensic task.
// Extracted from TaskManager.cpp for maintainability; same class, same public API.

#include "TaskManager.h"
#include "AndroidAnalyzer/HarmonyBackupExtractor.h"
#include "AndroidAnalyzer/ThunderForensicBackupExtractor.h"
#include "AndroidAnalyzer/MeiyaBackupExtractor.h"
#include "AndroidAnalyzer/MobileEvidenceMeiyaAdapter.h"
#include "AndroidAnalyzer/MobileEvidencePackage.h"
#include "AndroidAnalyzer/MobileEvidenceAnalysis.h"
#include "TaskPersistence.h"
#include "TaskWatchdog.h"
#include "TaskSerialization.h"
#include "TaskStageLedger.h"
#include "AnalysisBudget.h"
#include "AndroidPreflightAdmission.h"
#include "RaidTaskAdmission.h"
#include "AndroidContainerNormalization.h"
#include "AliyunImagePreparation.h"
#include "LLMPythonProxy.h"
#include "../../integration/LLMIntegration/LLMClient.h"
#include "EventClusterAnalyzer.h"
#include "SceneDetector.h"
#include "ConfigManager/ConfigManager.h"
#include "PathManager/PathManager.h"
#include "FileFilter/FileFilter.h"
#include "FileCarving/FileCarver.h"
#include "../../analyzers/WindowsFilesAnalyzer/Common/WindowsAnalyzerDeclarations.h"
#include "../../analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h"
#include <fstream>
#include <filesystem>
#include <thread>
#include <cstdlib>
#include <sqlite3.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <array>
#include <iomanip>
#include <sstream>

// TaskManager is declared at global scope, so the ledger's namespace (nested in
// forensics) needs qualifying at every use site.
namespace stage_ledger = forensics::stage_ledger;


using forensics::TaskPersistence;
using forensics::TaskWatchdog;
using forensics::FileFilter;

namespace {
std::string hashAndroidOutputFile(const std::filesystem::path& path) {
    std::ifstream source(path, std::ios::binary);
    if (!source) return {};
    EVP_MD_CTX* context = EVP_MD_CTX_new();
    if (!context) return {};
    bool okay = EVP_DigestInit_ex(context, EVP_sha256(), nullptr) == 1;
    std::array<char, 1 << 20> buffer{};
    while (okay && source) {
        source.read(buffer.data(), buffer.size());
        if (source.gcount() > 0)
            okay = EVP_DigestUpdate(context, buffer.data(),
                                    static_cast<std::size_t>(source.gcount())) == 1;
    }
    unsigned char digest[EVP_MAX_MD_SIZE]{};
    unsigned int size = 0;
    okay = okay && !source.bad() && EVP_DigestFinal_ex(context, digest, &size) == 1;
    EVP_MD_CTX_free(context);
    if (!okay) return {};
    std::ostringstream output;
    output << std::hex << std::setfill('0');
    for (unsigned int i = 0; i < size; ++i)
        output << std::setw(2) << static_cast<unsigned int>(digest[i]);
    return output.str();
}

bool appendAndroidArtifactProvenance(const std::filesystem::path& manifestPath,
                                     const std::filesystem::path& androidDb,
                                     const std::string& derivedHash) {
    try {
        std::ifstream input(manifestPath);
        nlohmann::json manifest; input >> manifest;
        if (manifest.at("normalized_kind") != "userdata" ||
            manifest.at("derived_sha256") != derivedHash) return false;
        const std::string dbHash = hashAndroidOutputFile(androidDb);
        if (dbHash.size() != 64) return false;
        for (const auto& step : manifest.at("steps"))
            if (step.value("step_id", std::string()) == "artifact-android-db") return false;
        manifest["steps"].push_back({
            {"step_id", "artifact-android-db"}, {"parent_step", "filesystem"},
            {"operation", "ARTIFACT_ANALYSIS"}, {"input_id", "userdata-filesystem"},
            {"input_sha256", derivedHash},
            {"input_format", manifest.at("userdata").at("filesystem")},
            {"tool", "AndroidAnalyzer"}, {"tool_version", "TraceLens-stage5"},
            {"parameters", nlohmann::json::object()},
            {"output_id", "android.db"}, {"output_sha256", dbHash},
            {"output_format", "sqlite"}, {"status", "SUCCESS"},
            {"warnings", nlohmann::json::array()}});
        const auto temporary = std::filesystem::path(manifestPath.string() + ".tmp");
        std::ofstream output(temporary, std::ios::trunc);
        if (!output) return false;
        output << manifest.dump(2) << '\n'; output.close();
        if (!output) return false;
        std::error_code ec;
        std::filesystem::rename(temporary, manifestPath, ec);
        return !ec;
    } catch (const std::exception&) { return false; }
}

struct AndroidCoverageSummary {
    int parsed = 0;
    int unresolved = 0;
    bool available = false;
};

AndroidCoverageSummary inspectAndroidCoverage(const std::string& databasePath) {
    AndroidCoverageSummary summary;
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(databasePath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return summary;
    }
    sqlite3_stmt* statement = nullptr;
    const char* sql = "SELECT status, COUNT(*) FROM android_source_coverage GROUP BY status";
    if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK) {
        summary.available = true;
        while (sqlite3_step(statement) == SQLITE_ROW) {
            const char* status = reinterpret_cast<const char*>(sqlite3_column_text(statement, 0));
            const int count = sqlite3_column_int(statement, 1);
            if (status && (std::string(status) == "parsed" || std::string(status) == "PARSED")) summary.parsed += count;
            else summary.unresolved += count;
        }
    }
    sqlite3_finalize(statement);
    sqlite3_close(db);
    return summary;
}

bool writeAndroidCoverageManifest(const AnalysisTask& task, const std::string& databasePath) {
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(databasePath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        sqlite3_close(db); return false;
    }
    nlohmann::json manifest = {
        {"schema_version", 1}, {"source", task.image_path},
        {"source_image_sha256", task.metadata.count("preflight_source_sha256")
             ? task.metadata.at("preflight_source_sha256") : ""},
        {"container", task.android_source == "filesystem-image"
             ? (task.metadata.count("preflight_container")
                 ? task.metadata.at("preflight_container") : "unknown")
             : task.android_source},
        {"partition", {{"name", task.metadata.count("preflight_partition_name")
                                ? task.metadata.at("preflight_partition_name") : ""},
                       {"offset", task.metadata.count("preflight_partition_offset")
                                ? task.metadata.at("preflight_partition_offset") : ""}}},
        {"filesystem", task.metadata.count("preflight_filesystem")
             ? task.metadata.at("preflight_filesystem") : "not_applicable"},
        {"encryption", task.metadata.count("preflight_encryption_state")
             ? task.metadata.at("preflight_encryption_state") : "UNKNOWN"},
        {"reader", task.metadata.count("preflight_filesystem") &&
                       task.metadata.at("preflight_filesystem") == "f2fs"
             ? "qnxprobe-1.34-fc74ca829c27" : "The Sleuth Kit"},
        {"artifact_types", nlohmann::json::object()},
    };
    std::map<std::string, std::string> tables{{"sms", "sms_messages"},
        {"contacts", "contacts"}, {"installed_packages", "installed_packages"},
        {"wifi", "wifi_networks"}, {"calls", "call_logs"}};
    sqlite3_stmt* rows = nullptr;
    if (sqlite3_prepare_v2(db,
        "SELECT artifact_kind,source_path,status,detail FROM android_source_coverage "
        "ORDER BY artifact_kind,source_path", -1, &rows, nullptr) != SQLITE_OK) {
        sqlite3_close(db); return false;
    }
    while (sqlite3_step(rows) == SQLITE_ROW) {
        auto field = [&](int i) -> std::string {
            const char* text = reinterpret_cast<const char*>(sqlite3_column_text(rows, i));
            return text ? text : "";
        };
        const std::string kind = field(0), path = field(1), status = field(2), detail = field(3);
        auto& artifact = manifest["artifact_types"][kind];
        if (artifact.is_null()) artifact = {
            {"status", "NOT_FOUND"}, {"source_candidates", nlohmann::json::array()},
            {"parsed_count", 0}, {"failure_reason", ""}};
        artifact["source_candidates"].push_back(path);
        if (status == "LOCKED" || status == "locked_or_unsupported") artifact["status"] = "LOCKED";
        else if (status == "NOT_PRESENT_IN_SOURCE") artifact["status"] = "NOT_PRESENT_IN_SOURCE";
        else if (status == "extract_failed") artifact["status"] = "EXTRACT_FAILED";
        else if (status == "UNSUPPORTED") artifact["status"] = "UNSUPPORTED";
        else if (status == "MALFORMED") artifact["status"] = "MALFORMED";
        else if (status == "parsed" || status == "PARSED") artifact["status"] = "PARSED";
        else if (status == "staged_for_parser" || status == "FOUND") artifact["status"] = "FOUND";
        if (artifact["status"] != "PARSED" && !detail.empty()) artifact["failure_reason"] = detail;
    }
    sqlite3_finalize(rows);
    for (const auto& [kind, table] : tables) {
        if (manifest["artifact_types"].contains(kind)) {
            std::string query = "SELECT COUNT(*) FROM " + table;
            sqlite3_stmt* count = nullptr;
            if (sqlite3_prepare_v2(db, query.c_str(), -1, &count, nullptr) == SQLITE_OK &&
                sqlite3_step(count) == SQLITE_ROW) {
                const int n = sqlite3_column_int(count, 0);
                manifest["artifact_types"][kind]["parsed_count"] = n;
                if (n > 0) {
                    manifest["artifact_types"][kind]["status"] = "PARSED";
                    manifest["artifact_types"][kind]["failure_reason"] = "";
                }
            }
            sqlite3_finalize(count);
        }
    }
    sqlite3_stmt* metrics = nullptr;
    if (sqlite3_prepare_v2(db, "SELECT reader,walk_milliseconds,indexed_file_count,"
        "extracted_member_count,bytes_read,analysis_milliseconds FROM android_filesystem_metrics "
        "LIMIT 1", -1, &metrics, nullptr) == SQLITE_OK &&
        sqlite3_step(metrics) == SQLITE_ROW) {
        const char* actualReader = reinterpret_cast<const char*>(sqlite3_column_text(metrics, 0));
        if (actualReader) manifest["reader"] = actualReader;
        manifest["performance"] = {
            {"walk_milliseconds", sqlite3_column_int64(metrics, 1)},
            {"indexed_file_count", sqlite3_column_int64(metrics, 2)},
            {"extracted_member_count", sqlite3_column_int64(metrics, 3)},
            {"bytes_read", sqlite3_column_int64(metrics, 4)},
            {"analysis_milliseconds", sqlite3_column_int64(metrics, 5)}};
    }
    sqlite3_finalize(metrics);
    sqlite3_close(db);
    const std::filesystem::path normalizationPath = std::filesystem::path(databasePath).parent_path() /
                                       "android_normalization_manifest.json";
    if (std::filesystem::is_regular_file(normalizationPath) &&
        !std::filesystem::is_symlink(normalizationPath)) {
        try {
            std::ifstream normalization(normalizationPath);
            nlohmann::json detail; normalization >> detail;
            manifest["normalization"] = {
                {"manifest", "android_normalization_manifest.json"},
                {"kind", detail.value("kind", std::string())},
                {"normalized_kind", detail.value("normalized_kind", std::string())},
                {"source_sha256", detail.value("source_sha256", std::string())},
                {"derived_sha256", detail.value("derived_sha256", std::string())},
                {"selected_slot", detail.value("selected_slot", 0)}};
            if (detail.contains("userdata"))
                manifest["filesystem"] = detail["userdata"].value("filesystem", std::string("not_applicable"));
            if (detail.value("normalized_kind", std::string()) == "super")
                manifest["userdata"] = { {"status", "NOT_PRESENT_IN_SOURCE"} };
            if (detail.value("normalized_kind", std::string()) == "super") {
                manifest["reader"] = "AOSP liblp/lpunpack android-10.0.0_r36";
                manifest["encryption"] = "NOT_APPLICABLE";
            }
        } catch (const std::exception&) { return false; }
    }
    const std::filesystem::path output = std::filesystem::path(databasePath).parent_path() /
                                          "android_coverage_manifest.json";
    const std::filesystem::path temporary = output.string() + ".tmp";
    std::ofstream stream(temporary, std::ios::trunc);
    if (!stream) return false;
    stream << manifest.dump(2) << '\n';
    stream.close();
    if (!stream) return false;
    std::error_code error;
    std::filesystem::rename(temporary, output, error);
    return !error;
}
}  // namespace

// Platform-artifact progress → task progress. The artifact walks stream
// rows whose total is unknown upfront (per-table caps, many tables), so the
// phase percentage approaches its scenario ceiling asymptotically; the phase
// description carries the concrete counter. Throttled to one update per 5
// artifacts (~1-2 minutes at real LLM pacing).
void TaskManager::attachPlatformProgressCallback(LinuxFilesAnalyzer& analyzer, const std::string& task_id,
                                                 int base_progress, int per_scenario_progress,
                                                 const std::string& scenario_name) {
    analyzer.setProgressCallback(
        [this, task_id, base_progress, per_scenario_progress, scenario_name](
            size_t artifacts_done, const std::string& artifact_type) {
            if (artifacts_done == 0 || artifacts_done % 5 != 0) return;
            const double inner = 99.0 * (1.0 - 1.0 / (1.0 + static_cast<double>(artifacts_done) / 800.0));
            int pct = base_progress + static_cast<int>(inner * per_scenario_progress / 100.0);
            const int ceiling = base_progress + per_scenario_progress - 1;
            if (pct > ceiling) pct = ceiling;
            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, pct,
                            "Analyzing " + scenario_name + " artifacts (" +
                                std::to_string(artifacts_done) + " done, current: " + artifact_type + ")...");
        });
}

void TaskManager::attachPlatformProgressCallback(WindowsFilesAnalyzer& analyzer, const std::string& task_id,
                                                 int base_progress, int per_scenario_progress,
                                                 const std::string& scenario_name) {
    analyzer.setProgressCallback(
        [this, task_id, base_progress, per_scenario_progress, scenario_name](
            size_t artifacts_done, const std::string& artifact_type) {
            if (artifacts_done == 0 || artifacts_done % 5 != 0) return;
            const double inner = 99.0 * (1.0 - 1.0 / (1.0 + static_cast<double>(artifacts_done) / 800.0));
            int pct = base_progress + static_cast<int>(inner * per_scenario_progress / 100.0);
            const int ceiling = base_progress + per_scenario_progress - 1;
            if (pct > ceiling) pct = ceiling;
            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, pct,
                            "Analyzing " + scenario_name + " artifacts (" +
                                std::to_string(artifacts_done) + " done, current: " + artifact_type + ")...");
        });
}

// mvp-phase1-acceptance SPEC §5: completion requires Graphiti ingestion.
// Runs its own poll loop (instead of LLMPythonProxy::wait_for_job_completion)
// so a cancelled task never blocks until the timeout and the watchdog
// heartbeat stays fresh during hours-long ingestion waits.
bool TaskManager::wait_for_graphiti_ingestion(const std::string& task_id, const std::string& job_id) {
    auto& config = forensics::ConfigManager::instance();
    // Aligned with the Python side's GRAPHITI_JOB_TIMEOUT_HOURS default (12h).
    const int timeout_minutes = config.getInt("GRAPHITI_INGEST_WAIT_TIMEOUT_MIN", 720);
    if (timeout_minutes <= 0) {
        // Escape hatch: restore the legacy fire-and-forget completion.
        return true;
    }

    auto& proxy = forensics::LLMPythonProxy::instance();
    const int max_attempts = 1 + config.getInt("GRAPHITI_INGEST_RETRIES", 2);
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::minutes(timeout_minutes);
    std::string active_job = job_id;

    for (int attempt = 1; attempt <= max_attempts; ++attempt) {
        if (active_job.empty()) {
            update_progress(task_id, TaskPhase::FINALIZING, 50,
                            "Triggering knowledge graph ingestion (attempt " + std::to_string(attempt) + ")...");
            active_job = proxy.async_ingest(task_id, forensics::IngestionMode::ANALYZED_ONLY);
            if (!active_job.empty()) {
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id)) tasks_[task_id].graphiti_job_id = active_job;
                save_tasks_internal();
            }
        }
        if (active_job.empty()) {
            add_audit_log(task_id, "WARNING",
                          "Graphiti ingestion trigger failed (attempt " + std::to_string(attempt) + ")");
            continue;
        }

        while (std::chrono::steady_clock::now() < deadline) {
            if (is_task_cancelled(task_id)) return false;
            // A pause during the ingestion wait stops the task here. The graph
            // job keeps running server-side and its completion is recorded in
            // the ledger on the next attempt, so nothing is lost by leaving.
            if (is_task_paused(task_id)) return false;
            // Watchdog liveness: refresh only phase_start_time.
            touch_heartbeat(task_id);
            const auto status = proxy.get_job_status(active_job);
            if (status.status == "COMPLETED") {
                add_audit_log(task_id, "GRAPHITI_INGESTION", "Ingestion job completed");
                return true;
            }
            if (status.status == "FAILED" || status.status == "CANCELLED") {
                add_audit_log(task_id, "WARNING",
                              "Graphiti ingestion job " + status.status +
                                  (status.error.empty() ? "" : ": " + status.error));
                break;  // leave the poll loop; retry below
            }
            // Unknown/empty status (Python restarting) keeps waiting.
            std::this_thread::sleep_for(std::chrono::seconds(
                config.getInt("GRAPHITI_INGEST_POLL_SECONDS", 10)));
        }
        if (std::chrono::steady_clock::now() >= deadline) break;
        active_job.clear();
    }

    return false;
}

// First-stage 材料自主研判 report gate: mirror the ingestion gate — the task
// is only COMPLETED once the pipeline-tail report generation has finished;
// failure after retries fails the task (artifacts stay browsable).
bool TaskManager::wait_for_pipeline_report(const std::string& task_id) {
    auto& config = forensics::ConfigManager::instance();
    const int timeout_minutes = config.getInt("REPORT_TAIL_WAIT_TIMEOUT_MIN", 60);
    if (timeout_minutes <= 0) {
        // Escape hatch: restore the legacy fire-and-forget completion.
        return true;
    }
    const int max_attempts = 1 + config.getInt("REPORT_TAIL_RETRIES", 1);
    auto& proxy = forensics::LLMPythonProxy::instance();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::minutes(timeout_minutes);
    for (int attempt = 1; attempt <= max_attempts; ++attempt) {
        update_progress(task_id, TaskPhase::FINALIZING, 40,
                        "Generating first-stage material review report (attempt " +
                            std::to_string(attempt) + ")...");
        if (!proxy.trigger_report_tail(task_id)) {
            add_audit_log(task_id, "WARNING",
                          "Report tail trigger failed (attempt " + std::to_string(attempt) + ")");
            continue;
        }
        while (std::chrono::steady_clock::now() < deadline) {
            if (is_task_cancelled(task_id)) return false;
            touch_heartbeat(task_id);
            const auto status = proxy.get_report_tail_status(task_id);
            if (status.state == "completed") {
                add_audit_log(task_id, "REPORT",
                              "First-stage material review report generated");
                return true;
            }
            if (status.state == "failed") {
                add_audit_log(task_id, "WARNING",
                              "Report tail failed: " +
                                  (status.error_code.empty() ? "unknown" : status.error_code));
                break;  // leave the poll loop; retry below
            }
            const double elapsed = std::chrono::duration<double>(
                std::chrono::steady_clock::now() - deadline).count();
            const int pct = 40 + static_cast<int>(50.0 * (1.0 + elapsed / 60.0
                / static_cast<double>(timeout_minutes)));
            update_progress(task_id, TaskPhase::FINALIZING,
                            pct < 90 ? pct : 90,
                            "Generating first-stage material review report...");
            std::this_thread::sleep_for(std::chrono::seconds(
                config.getInt("REPORT_TAIL_POLL_SECONDS", 15)));
        }
        if (std::chrono::steady_clock::now() >= deadline) break;
    }
    return false;
}

void TaskManager::start_analysis(const std::string& task_id) {
    if (!analysis_pool_) {
        std::cerr << "CRITICAL: ThreadPool not initialized in TaskManager" << std::endl;
        return;
    }

    analysis_pool_->enqueue([this, task_id]() {
        // Attribute any LLM attempt on this thread to this task so the
        // LLMClient attempt hook can refresh the watchdog heartbeat while a
        // single LLM call/retry chain runs (it can legitimately occupy the
        // thread for tens of minutes without a per-file callback).
        TaskManager::set_thread_heartbeat_task(task_id);
        struct HeartbeatGuard {
            ~HeartbeatGuard() { TaskManager::set_thread_heartbeat_task(std::string()); }
        } heartbeat_guard;

        // Install the process-wide LLM attempt hook exactly once. It resolves
        // the task from the calling thread (see t_heartbeat_task_id), so one
        // hook serves every concurrently running task.
        static std::once_flag llm_attempt_hook_once;
        std::call_once(llm_attempt_hook_once, [this]() {
            forensics::llm::LLMClient::set_attempt_hook([this]() {
                const std::string& tid = TaskManager::thread_heartbeat_task();
                if (!tid.empty()) touch_heartbeat(tid);
            });
        });

        // RAII cleanup handler for deleted tasks
        struct TaskCleanup {
            TaskManager& tm;
            const std::string& id;
            ~TaskCleanup() {
                bool is_deleted = false;
                {
                    std::lock_guard<std::mutex> lock(tm.mtx_);
                    is_deleted = (tm.tasks_.count(id) == 0);
                }
                if (is_deleted) {
                    try {
                        auto& pm = forensics::PathManager::instance();
                        std::string task_root = pm.getTaskDir(id).string();
                        if (!task_root.empty() && std::filesystem::exists(task_root)) {
                            std::filesystem::remove_all(task_root);
                        }
                    } catch (...) {}
                }
            }
        } cleanup_handler{*this, task_id};

        try {
            // Re-fetch task to ensure we have the most up-to-date state (atomic load)
            AnalysisTask task = get_task(task_id);
            struct BackupPasswordWiper {
                AnalysisTask& task;
                ~BackupPasswordWiper() {
                    if (!task.backup_password.empty())
                        OPENSSL_cleanse(task.backup_password.data(), task.backup_password.size());
                }
            } wipeBackupPassword{task};
            if (task.id.empty()) {
                std::cerr << "Analysis Error: Task " << task_id << " not found in manager" << std::endl;
                return;
            }
            
            if (is_task_cancelled(task_id)) {
                update_status(task_id, TaskStatus::CANCELLED, "任务开始前已取消");
                return;
            }
            if (is_task_paused(task_id)) {
                update_status(task_id, TaskStatus::PAUSED, "任务开始前已暂停");
                return;
            }

            // Guard against re-running
            if (task.status == TaskStatus::RUNNING || task.status == TaskStatus::COMPLETED) {
                return;
            }

            // Check dependencies
            if (!can_start_task(task_id)) {
                update_status(task_id, TaskStatus::PENDING, "等待依赖任务完成");
                return;
            }

            std::string imagePath = task.image_path;
            if (task.metadata.count("source_kind") && task.metadata.at("source_kind") == "raid") {
                const auto admission = admitRaidImage(imagePath, task.metadata.at("raid_job_id"),
                    task.metadata.at("raid_manifest_sha256"), task.metadata.at("raid_requested_by"),
                    task.metadata.at("raid_allow_partial") == "true");
                if (!admission.accepted) {
                    update_status(task_id, TaskStatus::FAILED, "RAID source changed before analysis", admission.code);
                    return;
                }
                const auto taskRoot = forensics::PathManager::instance().getTaskDir(task_id);
                std::filesystem::create_directories(taskRoot);
                const auto frozen = taskRoot / "raid_source_manifest.json";
                std::error_code copyError;
                if (!std::filesystem::exists(frozen))
                    std::filesystem::copy_file(task.metadata.at("raid_manifest_path"), frozen,
                                              std::filesystem::copy_options::none, copyError);
                if (copyError || !sourceMatchesPreflightHash(frozen.string(), task.metadata.at("raid_manifest_file_sha256"))) {
                    update_status(task_id, TaskStatus::FAILED, "RAID source snapshot unavailable", "RAID_SNAPSHOT_INVALID");
                    return;
                }
            }
            update_status(task_id, TaskStatus::RUNNING, "正在初始化分析…");
            update_progress(task_id, TaskPhase::INITIALIZING, 10, "正在初始化分析环境…");

            if (!std::filesystem::exists(imagePath)) {
                update_status(task_id, TaskStatus::FAILED, "Image file not found",
                              "Image file not found on disk: '" + imagePath +
                              "'. Verify the path exists and is readable by the server process.");
                return;
            }

            // Generate DB paths
            const bool harmonyBackup = HarmonyBackupExtractor::recognizes(imagePath);
            bool harmonyCoverageIncomplete = !task.platform_analyze;
            if (task.android_source == "harmony-backup" && !harmonyBackup) {
                update_status(task_id, TaskStatus::FAILED, "INVALID_HARMONY_BACKUP");
                return;
            }
            if (harmonyBackup) {
                task.android_source = "harmony-backup";
                task.scenarios = {ForensicScenario::ANDROID};
                std::lock_guard<std::mutex> lock(mtx_);
                tasks_[task_id].android_source = task.android_source;
                tasks_[task_id].scenarios = task.scenarios;
                tasks_[task_id].metadata["device_platform"] = "HarmonyOS";
                tasks_[task_id].metadata["source_identity_kind"] = "logical_file_id_not_inode";
            }
            // Same treatment for ThunderForensic extractions (OPPO / vivo /
            // OnePlus / ...): the source may arrive as the tar file or its
            // project directory, whatever the caller picked, and is routed to
            // the generic adapter.
            std::string thunderBrand;
            const bool thunderBackup =
                ThunderForensicBackupExtractor::recognizes(imagePath, &thunderBrand);
            if (isThunderForensicSource(task.android_source) && !thunderBackup) {
                update_status(task_id, TaskStatus::FAILED, "INVALID_THUNDERFORENSIC_BACKUP");
                return;
            }
            if (thunderBackup) {
                task.android_source = kThunderForensicSource;
                task.scenarios = {ForensicScenario::ANDROID};
                std::lock_guard<std::mutex> lock(mtx_);
                tasks_[task_id].android_source = task.android_source;
                tasks_[task_id].scenarios = task.scenarios;
                tasks_[task_id].metadata["device_platform"] = "Android";
                if (!thunderBrand.empty()) {
                    const std::size_t space = thunderBrand.find(' ');
                    tasks_[task_id].metadata["device_brand"] =
                        thunderBrand.substr(0, space);
                    if (space != std::string::npos)
                        tasks_[task_id].metadata["device_model"] =
                            thunderBrand.substr(space + 1);
                }
            }
            // Meiya (MobileMaster FL-901) case exports are XOR-obfuscated
            // SQLite containers, not Android path trees: they are decoded and
            // converted into the unified package instead of going through
            // AndroidAnalyzer. Recognition is a bounded header probe.
            const bool meiyaCase =
                meiya::MeiyaBackupExtractor::recognizes(imagePath);
            if (task.android_source == "meiya" && !meiyaCase) {
                update_status(task_id, TaskStatus::FAILED, "INVALID_MEIYA_CASE_EXPORT",
                              "Expect a Meiya case directory (containing <case>.mf or "
                              "<device>/<device>.dmf) or a single .mf file.");
                return;
            }
            if (meiyaCase && (task.android_source == "meiya" || task.android_source.empty() ||
                              task.android_source == "tsk" || task.android_source == "dir")) {
                task.android_source = "meiya";
                task.scenarios = {ForensicScenario::ANDROID};
                std::lock_guard<std::mutex> lock(mtx_);
                tasks_[task_id].android_source = task.android_source;
                tasks_[task_id].scenarios = task.scenarios;
                tasks_[task_id].metadata["device_platform"] = "Android";
                tasks_[task_id].metadata["device_brand"] = "Meiya MobileMaster FL-901";
            }

            std::filesystem::path p(imagePath);
            std::string baseName = task.android_source == "aliyun-image" ? "system" : p.stem().string();

            // Use PathManager for per-task directory (HTTP Server mode)
            auto& pm = forensics::PathManager::instance();
            std::string rawDbPath, eventDbPath, fileDbPath;

            if (!task.db_output_dir.empty()) {
            // Legacy db_output_dir is treated as a relative subdirectory under
            // the configured task root; absolute paths cannot escape the data root.
            std::filesystem::path requested(task.db_output_dir);
            if (requested.is_absolute()) {
                requested = requested.lexically_relative(pm.getDataDir());
            }
            bool escapes = requested.empty() || requested == ".";
            for (const auto& part : requested) {
                if (part == "..") escapes = true;
            }
            if (escapes) {
                throw std::runtime_error("db_output_dir must remain under the configured data directory");
            }
            auto outputRoot = std::filesystem::weakly_canonical(pm.getDataDir() / requested);
            auto dataRoot = std::filesystem::weakly_canonical(pm.getDataDir());
            auto relative = outputRoot.lexically_relative(dataRoot);
            if (relative.empty() || *relative.begin() == "..") {
                throw std::runtime_error("db_output_dir escapes the configured data directory");
            }
            std::filesystem::create_directories(outputRoot);
            std::string outPrefix = outputRoot.string() + "/";
                rawDbPath = outPrefix + baseName + "_raw.db";
                eventDbPath = outPrefix + baseName + "_events.db";
                fileDbPath = outPrefix + baseName + "_files.db";
            } else {
                // New default: data/tasks/<task_id>/
                pm.ensureTaskDir(task_id);
                auto dbPaths = pm.getTaskDbPaths(task_id, baseName);
                rawDbPath = dbPaths.rawDb.string();
                eventDbPath = dbPaths.eventsDb.string();
                fileDbPath = dbPaths.filesDb.string();
            }

            // Set database paths in the task
            {
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id)) {
                    tasks_[task_id].output_raw_db = rawDbPath;
                    tasks_[task_id].output_events_db = eventDbPath;
                }
            }

            update_progress(task_id, TaskPhase::INITIALIZING, 30, "分析环境已初始化");

            if (task.android_source == "aliyun-image") {
                const auto admission = admitAliyunImage(imagePath, task.metadata["preflight_job_id"],
                    task.metadata["preflight_source_sha256"], task.metadata["preflight_detected_kind"]);
                if (!admission.accepted) {
                    update_status(task_id, TaskStatus::FAILED, admission.detail, admission.code);
                    return;
                }
                const auto taskRoot = pm.getTaskDir(task_id);
                const auto work = taskRoot / "work" / "aliyun_image";
                if (std::filesystem::is_symlink(taskRoot) || std::filesystem::is_symlink(taskRoot / "work") ||
                    std::filesystem::weakly_canonical(taskRoot).parent_path() !=
                        std::filesystem::weakly_canonical(pm.getDataDir() / "tasks"))
                    throw std::runtime_error("阿里云镜像任务目录越界");
                std::filesystem::create_directories(work);
                if (std::filesystem::weakly_canonical(work).lexically_relative(
                        std::filesystem::weakly_canonical(taskRoot)).string().rfind("..", 0) == 0 ||
                    std::filesystem::is_symlink(work))
                    throw std::runtime_error("阿里云镜像输出目录越界");
                const auto prepared = prepareAliyunImage(imagePath, work.string(),
                    admission.metadata.at("preflight_source_sha256"),
                    [this, task_id](uint64_t done, uint64_t total) {
                        update_progress(task_id, TaskPhase::INITIALIZING,
                            total ? 30 + static_cast<int>(60 * done / total) : 30,
                            "正在校验并解包阿里云系统盘（" + std::to_string(done / (1024 * 1024)) + " MiB）");
                    }, [this, task_id]() { return is_task_cancelled(task_id); });
                if (is_task_cancelled(task_id)) {
                    update_status(task_id, TaskStatus::CANCELLED, "阿里云镜像任务已取消"); return;
                }
                if (!prepared.okay) {
                    update_status(task_id, TaskStatus::FAILED, "阿里云镜像校验或解包失败", prepared.code); return;
                }
                const std::string original = imagePath;
                imagePath = prepared.manifest.at("derived_path").get<std::string>();
                task.image_path = imagePath;
                {
                    std::lock_guard<std::mutex> lock(mtx_);
                    auto& saved = tasks_.at(task_id);
                    // All existing readers (extraction, previews, LLM, reports)
                    // now resolve the verified disk; the original archive is retained in provenance.
                    saved.image_path = imagePath;
                    saved.metadata["aliyun_original_source"] = original;
                    saved.metadata["aliyun_manifest_path"] = (work / "source_manifest.json").string();
                    saved.metadata["aliyun_manifest_sha256"] = hashAndroidOutputFile(work / "source_manifest.json");
                    saved.metadata["aliyun_raw_sha256"] = prepared.manifest.at("raw_sha256").get<std::string>();
                    saved.metadata["aliyun_member_name"] = prepared.manifest.at("member_name").get<std::string>();
                    saved.metadata["aliyun_prepared"] = "true";
                    saved.metadata["source_verification"] = "VERIFIED_ARCHIVE_AND_RAW";
                    task.metadata = saved.metadata;
                    save_tasks_internal();
                }
                update_progress(task_id, TaskPhase::INITIALIZING, 100, "阿里云 RAW 校验完成，进入原有 Linux 取证流程");
            }

            // ── Logical Android analysis short-circuit ───────────────────────
            // A logical data source (directory / zip / MIUI backup) is NOT a TSK
            // disk image: there is no filesystem to carve and no _raw.db to build.
            // Run the Android analyzer directly against the source and skip the
            // entire TSK / event / classification pipeline.
            if (task.android_source == "dir" ||
                task.android_source == "zip" ||
                task.android_source == "miui-backup" ||
                task.android_source == "meiya" ||
                task.android_source == "mobile-evidence" ||
                isThunderForensicSource(task.android_source) ||
                task.android_source == "tar" ||
                task.android_source == "seven-zip" ||
                task.android_source == "android-backup" ||
                task.android_source == "filesystem-image" ||
                task.android_source == "android-container") {

                if (is_task_cancelled(task_id)) {
                    update_status(task_id, TaskStatus::CANCELLED, "任务已取消");
                    clear_backup_password(task_id);
                    return;
                }

                std::string archiveFailure;
                bool ok = runLogicalAndroidAnalysis(task, baseName, &archiveFailure);

                // Drop the runtime-only backup password as soon as the analyzer
                // has consumed it (mirrors the decryption-password handling).
                clear_backup_password(task_id);

                if (!ok) {
                    update_status(task_id, TaskStatus::FAILED,
                                  archiveFailure.empty() ? "Android logical analysis failed for source: " + task.android_source : archiveFailure,
                                  archiveFailure.empty() ? "Android logical analysis failed for source '" + task.android_source +
                                      "' at path '" + task.image_path +
                                      "'. Verify the source layout (dir tree / zip / MIUI backup) and "
                                      "see cpp_server.log for the analyzer error." : archiveFailure);
                    return;
                }

                if (is_task_cancelled(task_id)) {
                    update_status(task_id, TaskStatus::CANCELLED, "任务已取消");
                    return;
                }

                // The helper wrote android.db and overwrote output_files_db so
                // results + MIUI query routes resolve to it. Re-read the task.
                std::string logicalResultDb;
                {
                    std::lock_guard<std::mutex> lock(mtx_);
                    if (tasks_.count(task_id)) logicalResultDb = tasks_[task_id].output_files_db;
                }
                if (logicalResultDb.empty()) logicalResultDb = fileDbPath;

                if (!writeAndroidCoverageManifest(task, logicalResultDb)) {
                    update_status(task_id, TaskStatus::FAILED,
                                  "Android coverage manifest could not be written");
                    return;
                }

                // The Android analyzer already ran its own artifact-level LLM
                // analysis inside analyzeAndroidData() (AndroidLLMAnalysisService,
                // mirroring the Linux/Windows analyzers). The legacy file-level
                // LLMAnalysisService is a no-op on android.db (no `files` table),
                // so we only surface a progress note here rather than re-running it.
                if (task.llm_analyze) {
                    update_progress(task_id, TaskPhase::LLM_ANALYSIS, 100,
                                    "手机记录的逐条智能分析已完成");
                }

                // No Graphiti gate for logical sources: android.db carries no
                // `files`/`events` tables, so a FULL ingestion job (raw_reader)
                // can never succeed — every dir/zip/miui-backup task failed at
                // 99% under the SPEC §5 gate. Skip ingestion until a reader for
                // android.db exists and finalize on the analysis result itself.
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "任务已取消"); return; }
                add_audit_log(task_id, "GRAPHITI_INGESTION",
                              "Skipped: no Graphiti reader for android.db (source: " +
                                  task.android_source + ")");
                const auto coverage = inspectAndroidCoverage(logicalResultDb);
                const bool incomplete = !coverage.available || coverage.unresolved > 0 || coverage.parsed == 0;
                bool superNormalized = false;
                bool lockedPersisted = false;
                {
                    std::lock_guard<std::mutex> lock(mtx_);
                    auto it = tasks_.find(task_id);
                    if (it != tasks_.end()) {
                        const auto prior = it->second.metadata.find("android_coverage_status");
                        superNormalized = prior != it->second.metadata.end() &&
                            prior->second == "SUPER_NORMALIZED_NO_USERDATA";
                        lockedPersisted = prior != it->second.metadata.end() &&
                            prior->second == "COMPLETED_WITH_LOCKED_USERDATA";
                        if (!superNormalized && !lockedPersisted)
                            it->second.metadata["android_coverage_status"] = incomplete ? "incomplete" : "parsed_sources_present";
                        it->second.metadata["android_coverage_parsed"] = std::to_string(coverage.parsed);
                        it->second.metadata["android_coverage_unresolved"] = std::to_string(coverage.unresolved);
                    }
                }
                add_audit_log(task_id, "ANDROID_COVERAGE",
                    "Source coverage: parsed=" + std::to_string(coverage.parsed) +
                    ", unresolved=" + std::to_string(coverage.unresolved) +
                    ", available=" + (coverage.available ? "true" : "false"));
                // First-stage 材料自主研判 report gate — mirror the TSK/Harmony
                // completion gate so logical-source tasks (dir/zip/MIUI/OPPO
                // backups) also end their initial pipeline with the auto report.
                // Locked/super-normalized tasks carry no analyzable artifacts;
                // a report over an empty evidence set would be noise.
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "任务已取消"); return; }
                if (task.llm_analyze && !superNormalized && !lockedPersisted) {
                    const char* logicalFieldMode = std::getenv("TRACELENS_FIELD_AUTH");
                    const char* logicalOutbound = std::getenv("FIELD_OUTBOUND_POLICY");
                    const bool logicalNoIntel = logicalFieldMode &&
                        std::string(logicalFieldMode) == "enabled" &&
                        (!logicalOutbound || std::string(logicalOutbound) == "disabled");
                    if (!logicalNoIntel &&
                        forensics::ConfigManager::instance().getBool("REPORT_AUTO_GENERATE_ENABLED", true)) {
                        update_progress(task_id, TaskPhase::FINALIZING, 95,
                                        "生成首次材料自主研判报告…");
                        if (!wait_for_pipeline_report(task_id)) {
                            update_status(task_id, TaskStatus::FAILED,
                                          "首次材料自主研判报告未完成",
                                          "报告生成失败或超时；分析产物仍可浏览，请查看报告任务状态。");
                            add_audit_log(task_id, "ERROR", "Analysis failed at the report completion gate");
                            return;
                        }
                    }
                }
                const bool locked = task.android_source == "filesystem-image" &&
                    task.metadata.count("preflight_locked") && task.metadata.at("preflight_locked") == "true";
                const std::string message = superNormalized
                    ? "SUPER_NORMALIZED_USERDATA_NOT_PRESENT: 系统逻辑分区已规范化；来源中没有 userdata，未分析用户数据。"
                    : locked
                    ? "COMPLETED_WITH_LOCKED_USERDATA: userdata 已识别，但用户加密内容不可读取，Android 工件覆盖不完整。"
                    : incomplete
                    ? "手机来源已处理；部分内容未解析，请核对来源覆盖状态"
                    : "手机来源已处理；已记录来源覆盖情况，请复核";
                update_progress(task_id, TaskPhase::FINALIZING, 100, message);
                update_status(task_id, TaskStatus::COMPLETED, message);
                return;
            }

            // 1. Image Analysis
            if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "任务已取消"); return; }
            if (is_task_paused(task_id)) { update_status(task_id, TaskStatus::PAUSED, "已暂停（检材分析前）"); return; }

            // Resume fast path: a previous run already produced raw.db from this
            // same image with the same configuration, and that database is still
            // on disk. Re-walking a multi-hundred-GB image is the single most
            // expensive thing the pipeline does, so this is the highest-value
            // skip in the ledger.
            const std::string imageConfigFp = stage_ledger::combine({
                task.image_path,
                std::to_string(static_cast<int>(task.xfs_mode)),
                task.enable_decryption ? "decrypt" : "plain",
                task.android_source});
            bool imageStageReused = false;
            {
                const auto parsed = stage_ledger::parse(
                    get_stage_entry(task_id, stage_ledger::kImageAnalysis));
                const std::string rawFingerprint = stage_ledger::fingerprintSqlite(rawDbPath);
                std::error_code sizeEc;
                const auto rawSize = std::filesystem::exists(rawDbPath, sizeEc)
                    ? std::filesystem::file_size(rawDbPath, sizeEc) : 0;
                if (parsed.state == "done" && !rawFingerprint.empty() && !sizeEc &&
                    parsed.detail == imageConfigFp && rawSize > 0) {
                    imageStageReused = true;
                    add_audit_log(task_id, "STAGE_SKIPPED",
                                  "IMAGE_ANALYSIS reused: raw.db matches the completed stage fingerprint");
                    update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 100,
                                    "检材结构分析与元数据提取已完成（续跑复用）");
                } else if (parsed.state == "done") {
                    // The ledger claims done but raw.db changed, is unusable, or
                    // the configuration differs. The claim is void and every
                    // stage derived from raw.db must be re-derived too.
                    add_audit_log(task_id, "STAGE_INVALIDATED",
                                  "IMAGE_ANALYSIS ledger claim dropped (raw.db changed or configuration differs); "
                                  "downstream stages will re-run");
                    clear_downstream_stages(task_id, stage_ledger::kImageAnalysis);
                }
            }

            if (!imageStageReused) {
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 10, "正在分析检材结构…");
            auto analyzer = std::make_unique<ImageAnalyzer>(imagePath);
            analyzer->setXFSMode(task.xfs_mode);
            analyzer->setCancellationCallback([this, task_id]() { return is_task_cancelled(task_id); });
            // Metadata-extraction heartbeat: the TSK walk streams files whose
            // total is unknown, so ImageAnalyzer reports the cumulative count
            // and we map it onto an asymptotic 50→99% phase percentage. Each
            // update refreshes progress.phase_start_time, which is what the
            // TaskWatchdog uses as the liveness signal — without this, any
            // image whose walk outlasts TASK_WATCHDOG_STALE_MINUTES is killed
            // as "hung" while still actively processing.
            analyzer->setProgressCallback([this, task_id](int files_extracted) {
                const int pct = 50 + static_cast<int>(
                    49.0 * (1.0 - 1.0 / (1.0 + files_extracted / 2000.0)));
                update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, pct,
                                "Extracting metadata... (" + std::to_string(files_extracted) +
                                " files)");
            });
            if (task.enable_decryption) {
                analyzer->setEnableDecryption(true);
                if (!task.key_file_dir.empty()) analyzer->setKeyFileDir(task.key_file_dir);
                if (!task.decrypt_password.empty()) analyzer->setDecryptPassword(task.decrypt_password);
            }
            task.decrypt_password.clear();
            clear_decryption_password(task_id);

            if (!analyzer->analyze()) {
                update_status(task_id, TaskStatus::FAILED, "Failed to analyze image",
                              "ImageAnalyzer::analyze() returned false for '" + imagePath +
                              "'. The image format could not be opened or no filesystem was "
                              "recognized. See the cpp_server.log segment for this task for "
                              "detailed TSK/EWF errors.");
                return;
            }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 50, "检材结构分析已完成，正在提取元数据…");

            if (!analyzer->extractToDatabase(rawDbPath)) {
                update_status(task_id, TaskStatus::FAILED, "Failed to create raw database",
                              "extractToDatabase produced no files for '" + imagePath +
                              "' (raw DB: " + rawDbPath +
                              "). Either the image contains no walkable filesystem or the "
                              "filesystem walker failed. See cpp_server.log for this task.");
                return;
            }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 100, "检材结构分析与元数据提取已完成");
            if (task.android_source == "aliyun-image") {
                sqlite3* probe = nullptr;
                sqlite3_stmt* statement = nullptr;
                bool linuxMarkers = false;
                if (sqlite3_open_v2(rawDbPath.c_str(), &probe, SQLITE_OPEN_READONLY, nullptr) == SQLITE_OK &&
                    sqlite3_prepare_v2(probe, "SELECT 1 FROM files WHERE is_deleted=0 AND path IN "
                        "('/etc/os-release','/usr/lib/os-release','/etc/passwd') LIMIT 1", -1,
                        &statement, nullptr) == SQLITE_OK)
                    linuxMarkers = sqlite3_step(statement) == SQLITE_ROW;
                sqlite3_finalize(statement);
                if (probe) sqlite3_close(probe);
                if (!linuxMarkers) {
                    update_status(task_id, TaskStatus::FAILED, "未发现 Linux 系统标识，请核对镜像类型", "ALIYUN_NOT_LINUX_IMAGE");
                    return;
                }
            }
            // Ledger write happens only after the artifact is complete and any
            // post-conditions (e.g. the aliyun Linux-marker probe) passed:
            // a "done" entry must never describe a database we would reject.
            mark_stage_complete(task_id, stage_ledger::kImageAnalysis, imageConfigFp,
                                task.filter_profile.empty() ? stage_ledger::kEventExtraction
                                                            : stage_ledger::kFilter);
            } // end !imageStageReused

            // 1.4b. Auto-detect platform scenarios when the user did not pick any.
            // Probes the *un-filtered* raw DB for tell-tale artifact paths and
            // back-fills task.scenarios so downstream classification / platform
            // analyzers run against the right OS. Must run before the filter,
            // since filter profiles drop system-noise — exactly these markers.
            if (task.scenarios.empty()) {
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "任务已取消"); return; }
                update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 2,
                                "Detecting platform scenarios from image...");
                SceneDetection detection = detectScenes(rawDbPath);
                if (detection.ok && !detection.detected.empty()) {
                    {
                        std::lock_guard<std::mutex> lock(mtx_);
                        if (tasks_.count(task_id)) {
                            tasks_[task_id].scenarios = detection.detected;
                            task.scenarios = detection.detected;
                        }
                    }
                    // Record the detection for traceability (which platforms,
                    // and how many marker files each matched).
                    std::string detail;
                    for (size_t i = 0; i < detection.detected.size(); ++i) {
                        if (i) detail += ", ";
                        detail += scenario_to_string(detection.detected[i]);
                        detail += "=" + std::to_string(detection.counts[detection.detected[i]]);
                    }
                    add_audit_log(task_id, "SCENE_DETECTED",
                                  "Auto-detected scenarios: " + detail);
                } else if (detection.ok) {
                    add_audit_log(task_id, "SCENE_DETECTED",
                                  "No platform markers found; running generic analysis");
                }
            }

            // 1.5. Apply file filter (if profile specified)
            std::string effectiveRawDb = rawDbPath;
            std::string filteredDbPath;
            if (!task.filter_profile.empty()) {
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "任务已取消"); return; }
                if (is_task_paused(task_id)) { update_status(task_id, TaskStatus::PAUSED, "已暂停（过滤前）"); return; }

                filteredDbPath = rawDbPath;
                size_t pos = filteredDbPath.rfind("_raw.db");
                if (pos != std::string::npos) {
                    filteredDbPath.replace(pos, 7, "_filtered.db");
                } else {
                    filteredDbPath += ".filtered";
                }

                // Filter fingerprints the raw DB it copied from and the profile
                // it applied; either changing invalidates the filtered copy and
                // everything derived from it.
                const std::string filterFp = stage_ledger::combine({
                    stage_ledger::fingerprintSqlite(rawDbPath), task.filter_profile});
                const auto filterEntry = stage_ledger::parse(
                    get_stage_entry(task_id, stage_ledger::kFilter));
                const bool filterUsable = filterEntry.state == "done" &&
                                          filterEntry.detail == filterFp &&
                                          !stage_ledger::fingerprintSqlite(filteredDbPath).empty();
                if (filterUsable) {
                    effectiveRawDb = filteredDbPath;
                    add_audit_log(task_id, "STAGE_SKIPPED",
                                  "FILE_FILTER reused: filtered DB matches the completed stage fingerprint");
                    update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10,
                                    "文件过滤已完成（续跑复用：" + task.filter_profile + "）");
                } else {
                    if (filterEntry.state == "done") {
                        add_audit_log(task_id, "STAGE_INVALIDATED",
                                      "FILE_FILTER ledger claim dropped (raw DB or profile changed)");
                        clear_downstream_stages(task_id, stage_ledger::kFilter);
                    }
                    update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 5, "Applying file filter: " + task.filter_profile + "...");

                    try {
                        FileFilter filter;
                        auto filterStats = filter.applyFilterByName(rawDbPath, filteredDbPath, task.filter_profile);
                        if (filterStats.included_files > 0) {
                            effectiveRawDb = filteredDbPath;
                            update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10,
                                "Filter applied: " + std::to_string(filterStats.included_files) + "/" +
                                std::to_string(filterStats.total_files) + " files selected");
                            mark_stage_complete(task_id, stage_ledger::kFilter, filterFp,
                                                stage_ledger::kEventExtraction);
                        } else {
                            // Filter excluded everything: stay on the unfiltered
                            // DB (honest degradation, same as the original
                            // pipeline) and record no filter claim so a later
                            // resume re-attempts the filter rather than
                            // inheriting a silently unfiltered view.
                            std::cerr << "Warning: Filter excluded all files for task " << task_id << std::endl;
                            add_audit_log(task_id, "WARNING",
                                          "Filter profile '" + task.filter_profile +
                                          "' excluded every file; continuing unfiltered");
                        }
                    } catch (const std::exception& e) {
                        std::cerr << "Warning: Filter failed for task " << task_id << ": " << e.what() << std::endl;
                        // Continue with unfiltered data
                    }
                }
            }

            // Update output_raw_db if filter changed the effective database
            if (effectiveRawDb != rawDbPath) {
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id)) {
                    tasks_[task_id].output_raw_db = effectiveRawDb;
                }
            }

            // 2. Event Extraction
            if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "任务已取消"); return; }
            if (is_task_paused(task_id)) { update_status(task_id, TaskStatus::PAUSED, "已暂停（时间线提取前）"); return; }
            auto eventExtractor = std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath);
            {
                // events.db is a pure derivation of the effective raw DB, so the
                // input fingerprint is that database's stat fingerprint.
                const std::string eventsFp = stage_ledger::fingerprintSqlite(effectiveRawDb);
                if (stage_is_reusable(task_id, stage_ledger::kEventExtraction, eventsFp,
                                      {eventDbPath})) {
                    add_audit_log(task_id, "STAGE_SKIPPED",
                                  "EVENT_EXTRACTION reused: events DB matches the completed stage fingerprint");
                    update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 100,
                                    "时间线事件提取已完成（续跑复用）");
                    // The device-artifact merges below run against eventDb_; on
                    // this path extractEvents() never opened it.
                    if (!eventExtractor->openEventDatabaseForImports()) {
                        update_status(task_id, TaskStatus::FAILED,
                                      "Failed to reopen events DB for artifact import",
                                      "events.db existed and matched its fingerprint but could not be "
                                      "opened for the platform artifact merge (events DB: " + eventDbPath + ").");
                        return;
                    }
                } else {
                    update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 10, "正在提取时间线事件…");
                    // extractEvents() appends rows into an existing events table
                    // (CREATE TABLE IF NOT EXISTS + INSERT), so a partial database
                    // from an interrupted attempt must go before the re-run.
                    remove_sqlite_artifacts({eventDbPath});
                    if (!eventExtractor->extractEvents()) {
                        std::cerr << "Error: Failed to extract events from " << effectiveRawDb << std::endl;
                        update_status(task_id, TaskStatus::FAILED, "Failed to extract timeline events",
                                      "EventExtractor::extractEvents() failed on raw DB '" + effectiveRawDb +
                                          "' (events DB: " + eventDbPath + "). See cpp_server.log.");
                        return;
                    }
                    update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 100, "时间线事件提取已完成");
                    mark_stage_complete(task_id, stage_ledger::kEventExtraction, eventsFp,
                                        stage_ledger::kFileClassification);
                }
            }

            // 3. File Classification (scene-aware)
            if (is_task_cancelled(task_id)) { return; }
            if (is_task_paused(task_id)) { update_status(task_id, TaskStatus::PAUSED, "已暂停（文件分类前）"); return; }
            auto fileClassifier = std::make_unique<FileClassifier>(effectiveRawDb, fileDbPath);

            // Map ForensicScenario to SceneType for scene-aware classification
            SceneType sceneType = SceneType::NONE;
            if (!task.scenarios.empty()) {
                switch (task.scenarios[0]) {
                    case ForensicScenario::ANDROID: sceneType = SceneType::ANDROID; break;
                    case ForensicScenario::WINDOWS: sceneType = SceneType::WINDOWS; break;
                    case ForensicScenario::LINUX: sceneType = SceneType::LINUX; break;
                    case ForensicScenario::SERVER_CLOUD: sceneType = SceneType::SERVER_CLOUD; break;
                }
            }
            fileClassifier->setSceneType(sceneType);

            {
                const int sceneInt = static_cast<int>(sceneType);
                const std::string classifyFp = stage_ledger::combine({
                    stage_ledger::fingerprintSqlite(effectiveRawDb), std::to_string(sceneInt)});
                if (stage_is_reusable(task_id, stage_ledger::kFileClassification, classifyFp,
                                      {fileDbPath})) {
                    add_audit_log(task_id, "STAGE_SKIPPED",
                                  "FILE_CLASSIFICATION reused: files DB matches the completed stage fingerprint");
                    update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 100,
                                    "文件分类已完成（续跑复用）");
                } else {
                    update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10, "正在按类型分类文件…");
                    // A stale files DB from an interrupted earlier attempt would
                    // collect duplicate rows (FileClassifier only INSERTs), so
                    // the artifact is removed before the re-run.
                    remove_sqlite_artifacts({fileDbPath});
                    if (!fileClassifier->classifyAndExtract()) {
                        update_status(task_id, TaskStatus::FAILED, "Failed to classify files",
                                      "FileClassifier::classifyAndExtract() failed (raw DB: " + effectiveRawDb +
                                          ", files DB: " + fileDbPath + "). See cpp_server.log.");
                        return;
                    }
                    update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 100, "文件分类已完成");
                    mark_stage_complete(task_id, stage_ledger::kFileClassification, classifyFp,
                                        task.llm_analyze ? stage_ledger::kLlmAnalysis
                                                         : stage_ledger::kPlatformAnalysis);
                }
            }

            // Publish the files DB path as soon as it exists: SPEC E record
            // calls arrive during LLM analysis and resolve the write target
            // from this task field — setting it only at finalization left it
            // empty for the whole LLM phase (HTTP 400 on every record call).
            set_result_db(task_id, fileDbPath);

            // 4. LLM Analysis (Optional) - Stores descriptions directly in _files.db
            // This stage needs no artifact reset on re-run: every candidate query
            // filters on "llm_analyzed_at IS NULL" (LLMAnalysisService.cpp
            // getScenePrioritizedFiles / getFilesFromDatabase), so a resumed run
            // re-analyzes only the files that never got a description. That is
            // also why it records a completion entry without a fingerprint: its
            // progress is carried by the per-row markers in files.db itself.
            if (task.llm_analyze) {
                if (is_task_cancelled(task_id)) { return; }
                if (is_task_paused(task_id)) { update_status(task_id, TaskStatus::PAUSED, "已暂停（智能分析前）"); return; }
                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 10, "正在生成文件智能分析说明…");
                
                forensics::LLMAnalysisService llmService;
                if (llmService.initialize()) {
                    llmService.setSceneType(sceneType);
                    // Provide image + raw DB paths so files can be extracted from the
                    // image before LLM analysis (files live inside the image, not on disk).
                    llmService.setImagePaths(imagePath, effectiveRawDb, task_id);
                    auto& config = forensics::ConfigManager::instance();
                    forensics::LLMAnalysisService::AnalysisOptions llmOpts;
                    // Task-level budget wins over the global cap. It also caps
                    // knowledge-graph ingestion and the report evidence seed,
                    // which both read the analyzed-file set (llm_analyzed_at),
                    // so one number governs the whole cost curve.
                    const bool smartMode = task.llm_mode != "full";
                    const auto budget = forensics::analysis_budget::resolve(
                        task.llm_max_files,
                        config.getLLMMaxFiles(),
                        config.getLLMSmartCandidateFiles(),
                        smartMode);
                    add_audit_log(task_id, "LLM_CONFIG",
                                  forensics::analysis_budget::describe(budget, smartMode));
                    llmOpts.maxFiles = static_cast<size_t>(budget.files);
                    llmOpts.maxContentLength = config.getLLMMaxContentLength();
                    llmOpts.skipBinaryFiles = config.getLLMSkipBinary();

                    int analyzedCount = 0;
                    // Surfaced on the mode-specific start message below, so the
                    // budget is visible exactly where the work begins.
                    const std::string budgetText = budget.files == 0
                        ? std::string("不限")
                        : std::to_string(budget.files) + " 个文件";
                    
                    if (task.llm_mode == "full") {
                        // Full mode: analyze all files
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 30,
                            "完整模式：正在分析文件（预算 " + budgetText + "）…");
                        analyzedCount = llmService.analyzeAllFiles(fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) -> bool {
                                if (is_task_cancelled(task_id)) return false;
                                if (is_task_paused(task_id)) return false;
                                int progress = 30;
                                if (total > 0) {
                                    progress += (current * 60 / total);
                                }
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, progress,
                                    "Analyzing file " + std::to_string(current) + "/" + std::to_string(total));
                                // Partial ledger entry: how many of the selected
                                // files have descriptions, so an interrupted run
                                // reports a truthful "继续将处理剩余 N 个" position.
                                if (current % 25 == 0 || current == total) {
                                    mark_stage_partial(task_id, stage_ledger::kLlmAnalysis,
                                        std::to_string(current) + "/" + std::to_string(total) + ":full");
                                }
                                return true;
                            });
                    } else {
                        // Smart mode: LLM selects important files first.
                        // File budget honours the resolved budget exactly — the
                        // previous hardcoded floor of 1000 made real-image tasks
                        // run for many hours on local LLMs.
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 20,
                            "智能模式：正在筛选重要文件（预算 " + budgetText + "）…");
                        // 候选扫描范围由 LLM_SMART_CANDIDATE_FILES 控制（selectImportantFiles 内部读取），
                        // 分析数量上限用已解析的任务级预算；两者默认有限，显式配置 0 才是全量。
                        analyzedCount = llmService.analyzeSmartFiles(fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) -> bool {
                                if (is_task_cancelled(task_id)) return false;
                                if (is_task_paused(task_id)) return false;
                                int progress = 30;
                                if (total > 0) {
                                    progress += (current * 60 / total);
                                }
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, progress,
                                    "Analyzing important file " + std::to_string(current) + "/" + std::to_string(total));
                                if (current % 25 == 0 || current == total) {
                                    mark_stage_partial(task_id, stage_ledger::kLlmAnalysis,
                                        std::to_string(current) + "/" + std::to_string(total) + ":smart");
                                }
                                return true;
                            });
                        // Record how the selection was reached. Without this a
                        // fallback run is indistinguishable from a successful
                        // one in the task record, which is how a 5000-candidate
                        // prompt failure stayed invisible while still producing
                        // a full-looking analysis.
                        const auto& selection = llmService.lastSelectionStats();
                        add_audit_log(task_id, "LLM_SELECTION",
                            "source=" + selection.source +
                            " candidates=" + std::to_string(selection.candidates) +
                            " listed=" + std::to_string(selection.listed) +
                            " reply_usable=" + std::to_string(selection.reply_usable) +
                            " selected=" + std::to_string(selection.selected));
                    }
                    
                    update_progress(task_id, TaskPhase::LLM_ANALYSIS, 100, 
                        "LLM analysis completed: " + std::to_string(analyzedCount) + " files analyzed (stored in _files.db)");
                    mark_stage_complete(task_id, stage_ledger::kLlmAnalysis, "",
                                        stage_ledger::kPlatformAnalysis);
                } else {
                    std::cerr << "Warning: Failed to initialize LLM analysis service" << std::endl;
                }
            }

            // 5. Event Cluster Analysis (Optional) — independent of the file
            // description switch: llm_event_analyze alone controls this stage.
            if (task.llm_event_analyze) {
                if (is_task_cancelled(task_id)) { return; }
                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 90, "Starting event cluster analysis...");
                
                forensics::EventClusterAnalyzer clusterAnalyzer;
                if (clusterAnalyzer.initialize()) {
                    int analyzedCount = 0;
                    
                    if (task.llm_mode == "full") {
                        // Full mode: analyze all event clusters
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 92, "Full mode: Analyzing all event clusters...");
                        auto allClusters = clusterAnalyzer.getAllEventClusters(eventDbPath);
                        analyzedCount = clusterAnalyzer.analyzeEventClusters(eventDbPath, allClusters,
                            [this, task_id](int current, int total, const std::string&) -> bool {
                                if (is_task_cancelled(task_id)) return false;
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 92,
                                    "Analyzing event cluster " + std::to_string(current) + "/" + std::to_string(total));
                                return true;
                            });
                    } else {
                        // Smart mode: LLM selects important event clusters first
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 92, "Smart mode: Selecting important event clusters...");
                        const int configuredClusterLimit = forensics::ConfigManager::instance().getLLMMaxEventClusters();
                        const size_t clusterLimit = configuredClusterLimit > 0
                            ? static_cast<size_t>(configuredClusterLimit)
                            : 0;
                        analyzedCount = clusterAnalyzer.analyzeSmartEventClusters(eventDbPath, clusterLimit,
                            [this, task_id](int current, int total, const std::string&) -> bool {
                                if (is_task_cancelled(task_id)) return false;
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 93,
                                    "Analyzing event cluster " + std::to_string(current) + "/" + std::to_string(total));
                                return true;
                            });
                    }
                    
                    update_progress(task_id, TaskPhase::LLM_ANALYSIS, 95, 
                        "Event cluster analysis completed: " + std::to_string(analyzedCount) + " clusters analyzed");
                } else {
                    std::cerr << "Warning: Failed to initialize event cluster analyzer" << std::endl;
                }
            }

            // 6. Platform-Specific Analysis (Unified) — task-level switch
            // (mvp: selected by the user at creation time, default on).
            if (!task.platform_analyze) {
                add_audit_log(task_id, "SKIPPED", "Platform analysis disabled for this task");
                update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 100,
                                "Platform analysis skipped (disabled for this task)");
            } else if (!task.scenarios.empty()) {
                if (is_task_cancelled(task_id)) { return; }
                int total_scenarios = static_cast<int>(task.scenarios.size());
                update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 0,
                    "Starting platform analysis for " + std::to_string(total_scenarios) + " scenario(s)...");

                int scenario_index = 0;
                for (auto scenario : task.scenarios) {
                    if (is_task_cancelled(task_id)) { return; }
                    if (is_task_paused(task_id)) { update_status(task_id, TaskStatus::PAUSED, "已暂停（平台分析中）"); return; }

                    int base_progress = (scenario_index * 100) / total_scenarios;
                    int per_scenario_progress = std::max(1, 100 / total_scenarios);
                    std::string scenario_name = scenario_to_string(scenario);

                    // Per-scenario ledger entry: a multi-scenario task that died
                    // between scenarios keeps the finished ones. The artifact is
                    // the scenario's own database (android.db / windows.db /
                    // linux.db / oss.db), keyed by the raw DB it derives from.
                    const std::string scenarioStage = "PLATFORM_ANALYSIS." + scenario_name;
                    std::string scenarioDbPath;
                    switch (scenario) {
                        case ForensicScenario::ANDROID:
                            scenarioDbPath = pm.getTaskDbPaths(task_id, baseName).androidDb.string(); break;
                        case ForensicScenario::WINDOWS:
                            scenarioDbPath = pm.getTaskDbPaths(task_id, baseName).windowsDb.string(); break;
                        case ForensicScenario::LINUX:
                            scenarioDbPath = pm.getTaskDbPaths(task_id, baseName).linuxDb.string(); break;
                        case ForensicScenario::SERVER_CLOUD:
                            scenarioDbPath = pm.getTaskDbPaths(task_id, baseName).ossDb.string(); break;
                    }
                    const std::string scenarioFp = stage_ledger::combine({
                        stage_ledger::fingerprintSqlite(effectiveRawDb), scenario_name,
                        task.llm_analyze ? "llm" : "nollm"});
                    if (stage_is_reusable(task_id, scenarioStage, scenarioFp, {scenarioDbPath})) {
                        add_audit_log(task_id, "STAGE_SKIPPED",
                                      scenarioStage + " reused: scenario DB matches the completed fingerprint");
                        scenario_index++;
                        update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS,
                                        (scenario_index * 100) / total_scenarios,
                                        scenario_name + " analysis reused (续跑复用)");
                        continue;
                    }

                    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, base_progress,
                        "Analyzing " + scenario_name + " artifacts...");

                    // Set only when the scenario ran without throwing. The
                    // artifact-existence check below is not enough on its own: a
                    // leftover database from a previous attempt would otherwise
                    // let a soft-failed scenario be recorded as complete.
                    bool scenarioSucceeded = false;
                    try {
                        switch (scenario) {
                            case ForensicScenario::ANDROID: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                if (!dbManager->initialize()) {
                                    std::cerr << "Warning: Failed to initialize DatabaseManager for Android analysis" << std::endl;
                                    break;
                                }
                                auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(imagePath, dbManager.get());
                                std::string androidDbPath = pm.getTaskDbPaths(task_id, baseName).androidDb.string();
                                // Platform analyzers only INSERT (CREATE TABLE IF
                                // NOT EXISTS), so a partial database from the
                                // interrupted attempt must be cleared first.
                                remove_sqlite_artifacts({androidDbPath});
                                androidAnalyzer->setOutputDatabasePath(androidDbPath);
                                androidAnalyzer->setSkipAI(!task.llm_analyze);
                                androidAnalyzer->setSourceCallbacks([this, task_id](std::size_t) { touch_heartbeat(task_id); },
                                    [this, task_id]() { return is_task_cancelled(task_id); });
                                if (androidAnalyzer->initialize()) {
                                    androidAnalyzer->analyzeAndroidData();
                                    if (harmonyBackup) {
                                        if (!eventExtractor->importAndroidArtifacts(androidDbPath))
                                            throw std::runtime_error("HARMONY_TIMELINE_IMPORT_FAILED");
                                        if (!writeAndroidCoverageManifest(task, androidDbPath))
                                            throw std::runtime_error("HARMONY_COVERAGE_WRITE_FAILED");
                                        const auto coverage = inspectAndroidCoverage(androidDbPath);
                                        harmonyCoverageIncomplete = coverage.unresolved > 0;
                                        std::lock_guard<std::mutex> lock(mtx_);
                                        tasks_[task_id].metadata["android_db"] = androidDbPath;
                                        tasks_[task_id].metadata["android_coverage_status"] = coverage.unresolved ? "incomplete" : "parsed_sources_present";
                                    }
                                } else {
                                    if (harmonyBackup) throw std::runtime_error("HARMONY_INIT_FAILED");
                                    std::cerr << "Warning: Failed to initialize Android analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::WINDOWS: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                if (!dbManager->initialize()) {
                                    std::cerr << "Warning: Failed to initialize DatabaseManager for Windows analysis" << std::endl;
                                    break;
                                }
                                auto windowsAnalyzer = std::make_unique<WindowsFilesAnalyzer>(imagePath, dbManager.get());
                                std::string windowsDbPath = pm.getTaskDbPaths(task_id, baseName).windowsDb.string();
                                remove_sqlite_artifacts({windowsDbPath});
                                windowsAnalyzer->setOutputDatabasePath(windowsDbPath);
                                attachPlatformProgressCallback(*windowsAnalyzer, task_id, base_progress,
                                                               per_scenario_progress, scenario_name);
                                if (windowsAnalyzer->initialize()) {
                                    windowsAnalyzer->analyzeWindowsData();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Windows analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::LINUX: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                if (!dbManager->initialize()) {
                                    std::cerr << "Warning: Failed to initialize DatabaseManager for Linux analysis" << std::endl;
                                    if (task.android_source == "aliyun-image") throw std::runtime_error("阿里云 Linux 分析数据库初始化失败");
                                    break;
                                }
                                auto linuxAnalyzer = std::make_unique<LinuxFilesAnalyzer>(imagePath, dbManager.get());
                                std::string linuxDbPath = pm.getTaskDbPaths(task_id, baseName).linuxDb.string();
                                remove_sqlite_artifacts({linuxDbPath});
                                linuxAnalyzer->setOutputDatabasePath(linuxDbPath);
                                attachPlatformProgressCallback(*linuxAnalyzer, task_id, base_progress,
                                                               per_scenario_progress, scenario_name);
                                if (linuxAnalyzer->initialize()) {
                                    linuxAnalyzer->analyzeLinuxData();
                                    if (task.android_source == "aliyun-image" && !eventExtractor->importLinuxArtifacts(linuxDbPath))
                                        throw std::runtime_error("阿里云 Linux 事件导入时间线失败");
                                } else {
                                    if (task.android_source == "aliyun-image") throw std::runtime_error("阿里云 Linux 分析器初始化失败");
                                    std::cerr << "Warning: Failed to initialize Linux analyzer" << std::endl;
                                }
                                break;
                            }
                            case ForensicScenario::SERVER_CLOUD: {
                                auto dbManager = std::make_unique<DatabaseManager>(effectiveRawDb);
                                if (!dbManager->initialize()) {
                                    std::cerr << "Warning: Failed to initialize DatabaseManager for Server/Cloud analysis" << std::endl;
                                    break;
                                }
                                auto serverAnalyzer = std::make_unique<LinuxFilesAnalyzer>(imagePath, dbManager.get());
                                std::string serverDbPath = pm.getTaskDbPaths(task_id, baseName).ossDb.string();
                                remove_sqlite_artifacts({serverDbPath});
                                serverAnalyzer->setOutputDatabasePath(serverDbPath);
                                attachPlatformProgressCallback(*serverAnalyzer, task_id, base_progress,
                                                               per_scenario_progress, scenario_name);
                                if (serverAnalyzer->initialize()) {
                                    serverAnalyzer->analyzeServerCloudArtifacts();
                                } else {
                                    std::cerr << "Warning: Failed to initialize Server/Cloud analyzer" << std::endl;
                                }
                                break;
                            }
                        }
                        scenarioSucceeded = true;
                    } catch (const std::exception& e) {
                        std::cerr << "Warning: " << scenario_name << " analysis failed: " << e.what() << std::endl;
                        add_audit_log(task_id, "WARNING", scenario_name + " analysis failed: " + std::string(e.what()));
                        if (harmonyBackup || task.android_source == "aliyun-image") throw;
                        // Soft failure: the scenario is intentionally left
                        // unrecorded in the ledger so a resume retries it,
                        // matching the original pipeline's tolerance for
                        // per-scenario errors.
                    }

                    // Record only when the scenario actually ran to completion
                    // AND produced its database: a scenario that soft-failed
                    // must stay unclaimed so a later resume re-attempts it.
                    if (scenarioSucceeded &&
                        !stage_ledger::fingerprintSqlite(scenarioDbPath).empty()) {
                        mark_stage_complete(task_id, scenarioStage, scenarioFp);
                    }

                    scenario_index++;
                    int done_progress = (scenario_index * 100) / total_scenarios;
                    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, done_progress,
                        scenario_name + " analysis completed");
                }
                // Platform phase is complete once every scenario has a claim.
                bool allScenariosDone = true;
                for (auto scenario : task.scenarios) {
                    const auto entry = stage_ledger::parse(
                        get_stage_entry(task_id, "PLATFORM_ANALYSIS." + scenario_to_string(scenario)));
                    if (entry.state != "done") { allScenariosDone = false; break; }
                }
                if (allScenariosDone) {
                    mark_stage_complete(task_id, stage_ledger::kPlatformAnalysis, "",
                                        task.file_carving ? stage_ledger::kFileCarving
                                                          : stage_ledger::kFinalizing);
                }
            }

            // 7. File Carving (Optional) — signature-based recovery from unallocated space
            if (task.file_carving && !harmonyBackup && !is_task_cancelled(task_id)) {
              if (is_task_paused(task_id)) { update_status(task_id, TaskStatus::PAUSED, "已暂停（文件恢复前）"); return; }
              auto carvedEntry = stage_ledger::parse(
                  get_stage_entry(task_id, stage_ledger::kFileCarving));
              const std::string carveFp = stage_ledger::fingerprintStat(imagePath);
              std::filesystem::path carveDir = pm.getTaskDir(task_id) / "carved_files";
              const bool carvingReusable = carvedEntry.state == "done" &&
                  !carveFp.empty() && carvedEntry.detail == carveFp &&
                  std::filesystem::exists(carveDir);
              if (carvingReusable) {
                  add_audit_log(task_id, "STAGE_SKIPPED",
                                "FILE_CARVING reused: recovered files match the completed stage fingerprint");
                  update_progress(task_id, TaskPhase::FILE_CARVING, 100, "文件恢复已完成（续跑复用）");
              } else {
                update_progress(task_id, TaskPhase::FILE_CARVING, 0, "正在恢复文件…");
                try {
                    std::filesystem::create_directories(carveDir);
                    FileCarver carver;
                    carver.setCancelCallback([this, task_id]() {
                        return is_task_cancelled(task_id);
                    });
                    carver.setProgressCallback(
                        [this, task_id](uint64_t current, uint64_t total, const std::string&) {
                            int pct = total > 0 ? static_cast<int>(current * 100 / total) : 0;
                            update_progress(task_id, TaskPhase::FILE_CARVING, std::min(pct, 100),
                                "Carving unallocated space: " + std::to_string(current) + "/" + std::to_string(total));
                        });
                    int carved = carver.carve(imagePath, carveDir.string());
                    add_audit_log(task_id, "FILE_CARVING",
                        "Recovered " + std::to_string(carved) + " files to " + carveDir.string());
                    update_progress(task_id, TaskPhase::FILE_CARVING, 100,
                        "File carving completed: " + std::to_string(carved) + " files recovered");
                    mark_stage_complete(task_id, stage_ledger::kFileCarving, carveFp,
                                        stage_ledger::kFinalizing);
                } catch (const std::exception& e) {
                    std::cerr << "Warning: File carving failed: " << e.what() << std::endl;
                    add_audit_log(task_id, "WARNING", std::string("File carving failed: ") + e.what());
                }
              } // end !carvingReusable
            }

            // 8. Graphiti Knowledge Graph Ingestion — MVP completion gate.
            // mvp-phase1-acceptance SPEC §5: the task is COMPLETED only once
            // ingestion has finished; failure after retries fails the task.
            if (is_task_cancelled(task_id)) { return; }
            if (is_task_paused(task_id)) { update_status(task_id, TaskStatus::PAUSED, "已暂停（知识图谱摄取前）"); return; }
            update_progress(task_id, TaskPhase::FINALIZING, 10, "Triggering knowledge graph ingestion...");

            std::string graphiti_job_id;
            const char* fieldMode = std::getenv("TRACELENS_FIELD_AUTH");
            const char* outbound = std::getenv("FIELD_OUTBOUND_POLICY");
            const bool noOptionalIntelligence = fieldMode && std::string(fieldMode) == "enabled" &&
                (!outbound || std::string(outbound) == "disabled");

            // Resume fast path: a previous attempt that already finished
            // ingestion must not re-wait for it — the graph is idempotent
            // server-side (file-episode dedupe + ingested_at watermark), but the
            // wait itself costs hours on a real image. Only the report gate is
            // retried in that case.
            const bool ingestionAlreadyDone = stage_ledger::parse(
                get_stage_entry(task_id, "FINALIZING.ingestion")).state == "done";

            if (!noOptionalIntelligence && !ingestionAlreadyDone) {
                try {
                    auto& proxy = forensics::LLMPythonProxy::instance();
                    // LLM_MAX_FILES caps which files were described. The tail must
                    // not ingest the whole files table: analyzed_only builds
                    // entities and episodes only for files that have a description.
                    graphiti_job_id = proxy.async_ingest(task_id, forensics::IngestionMode::ANALYZED_ONLY);
                } catch (const std::exception& e) {
                    std::cerr << "Warning: Exception triggering Graphiti ingestion: " << e.what() << std::endl;
                    add_audit_log(task_id, "WARNING", "Graphiti ingestion failed: " + std::string(e.what()));
                }
            }
            if (graphiti_job_id.empty() && !noOptionalIntelligence && ingestionAlreadyDone) {
                add_audit_log(task_id, "STAGE_SKIPPED",
                              "FINALIZING ingestion reused: knowledge graph ingestion already completed");
                update_progress(task_id, TaskPhase::FINALIZING, 50,
                                "知识图谱摄取已完成（续跑复用），正在检查研判报告…");
            }
            if (!graphiti_job_id.empty()) {
                add_audit_log(task_id, "GRAPHITI_INGESTION",
                    "Triggered Graphiti knowledge graph ingestion (job_id: " + graphiti_job_id + ")");
                task.graphiti_job_id = graphiti_job_id;
                save_tasks_internal();
            }

            // Finalization — gated on ingestion (budget: GRAPHITI_INGEST_WAIT_TIMEOUT_MIN,
            // 0 restores the legacy fire-and-forget completion).
            const bool ingestion_ok = noOptionalIntelligence || ingestionAlreadyDone ||
                                      wait_for_graphiti_ingestion(task_id, graphiti_job_id);
            if (is_task_cancelled(task_id)) { return; }

            set_result_db(task_id, fileDbPath);
            if (!ingestion_ok) {
                const int budget_minutes = forensics::ConfigManager::instance()
                                               .getInt("GRAPHITI_INGEST_WAIT_TIMEOUT_MIN", 720);
                update_status(task_id, TaskStatus::FAILED,
                              "Knowledge graph ingestion did not complete",
                              "Graphiti ingestion failed or timed out (budget: " +
                                  std::to_string(budget_minutes) +
                                  " minutes). Analysis artifacts remain available for browsing.");
                add_audit_log(task_id, "ERROR", "Analysis failed at the Graphiti ingestion gate");
                return;
            }
            // The ingestion ledger entry is written as soon as the gate passes,
            // so a later failure in the report stage resumes straight to the
            // report instead of re-waiting hours for an already-built graph.
            if (!noOptionalIntelligence && !ingestionAlreadyDone) {
                mark_stage_complete(task_id, "FINALIZING.ingestion", "",
                                    "FINALIZING.report");
            }

            // The first-stage report belongs to the initial analysis pipeline.
            // Its worker callback is deliberately disabled to avoid racing this gate.
            if (task.llm_analyze && !noOptionalIntelligence &&
                forensics::ConfigManager::instance().getBool("REPORT_AUTO_GENERATE_ENABLED", true)) {
                const bool report_ok = wait_for_pipeline_report(task_id);
                if (is_task_cancelled(task_id)) { return; }
                if (!report_ok) {
                    update_status(task_id, TaskStatus::FAILED,
                                  "首次材料自主研判报告未完成",
                                  "报告生成失败或超时；分析产物仍可浏览，请查看报告任务状态。");
                    add_audit_log(task_id, "ERROR", "Analysis failed at the report completion gate");
                    return;
                }
            }
            const std::string completionMessage = harmonyBackup && harmonyCoverageIncomplete
                ? "HarmonyOS backup analyzed; some sources are absent or unsupported. Review mobile source coverage."
                : "Analysis completed successfully";
            mark_stage_complete(task_id, stage_ledger::kFinalizing, "");
            update_progress(task_id, TaskPhase::FINALIZING, 100, completionMessage);
            update_status(task_id, TaskStatus::COMPLETED, completionMessage);

        } catch (const std::exception& e) {
            update_status(task_id, TaskStatus::FAILED, std::string("Analysis error: ") + e.what(),
                          std::string("Unhandled exception in analysis pipeline: ") + e.what());
            add_audit_log(task_id, "ERROR", "Analysis failed: " + std::string(e.what()));
        }
    });
}

bool TaskManager::runLogicalAndroidAnalysis(const AnalysisTask& task,
                                            const std::string& baseName,
                                            std::string* failureCode) {
    const std::string& task_id = task.id;
    const std::string& imagePath = task.image_path;
    const bool archiveMode = task.android_source == "filesystem-image" ||
        task.android_source == "android-container" ||
        task.android_source == "tar" ||
        task.android_source == "seven-zip" || task.android_source == "android-backup";
    if (archiveMode) {
        const auto expected = task.metadata.find("preflight_source_sha256");
        if (expected == task.metadata.end() ||
            !sourceMatchesPreflightHash(imagePath, expected->second)) {
            if (failureCode) *failureCode = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
            add_audit_log(task_id, "ERROR", "EVIDENCE_CHANGED_AFTER_PREFLIGHT");
            return false;
        }
    }

    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 10,
                    "Analyzing Android artifacts (source=" + task.android_source + ")...");

    try {
        auto& pm = forensics::PathManager::instance();
        pm.ensureTaskDir(task_id);
        auto dataRoot = std::filesystem::weakly_canonical(pm.getDataDir());
        std::filesystem::path androidDbPath = pm.getTaskDbPaths(task_id, baseName).androidDb;
        if (!task.db_output_dir.empty()) {
            std::filesystem::path requested(task.db_output_dir);
            if (requested.is_absolute()) requested = requested.lexically_relative(dataRoot);
            bool escapes = requested.empty() || requested == ".";
            for (const auto& part : requested) if (part == "..") escapes = true;
            if (escapes) throw std::runtime_error("db_output_dir must remain under the configured data directory");
            auto outputRoot = std::filesystem::weakly_canonical(dataRoot / requested);
            auto relative = outputRoot.lexically_relative(dataRoot);
            if (relative.empty() || *relative.begin() == "..") {
                throw std::runtime_error("db_output_dir escapes the configured data directory");
            }
            std::filesystem::create_directories(outputRoot);
            androidDbPath = outputRoot / (baseName + "_android.db");
        }

        const bool lockedImage = task.android_source == "filesystem-image" &&
            task.metadata.count("preflight_locked") && task.metadata.at("preflight_locked") == "true";
        if (lockedImage) {
            AndroidAnalysisDatabase database(androidDbPath.string());
            if (!database.initialize() ||
                !database.recordSourceCoverage("userdata", imagePath, "LOCKED",
                    "F2FS_PER_FILE_ENCRYPTION_OR_UNAVAILABLE_NAMES; "
                    "preflight identified userdata but no clear Android artifact path")) {
                if (failureCode) *failureCode = "LOCKED_COVERAGE_WRITE_FAILED";
                return false;
            }
            const std::pair<const char*, const char*> candidates[] = {
                {"sms", "data/data/com.android.providers.telephony/databases/mmssms.db"},
                {"contacts", "data/data/com.android.providers.contacts/databases/contacts2.db"},
                {"calls", "data/data/com.android.providers.contacts/databases/calllog.db"},
                {"installed_packages", "data/system/packages.xml"},
                {"wifi", "data/misc/wifi/WifiConfigStore.xml"},
                {"whatsapp", "data/data/com.whatsapp/databases/msgstore.db"},
                {"telegram", "data/data/org.telegram.messenger/files/cache4.db"},
            };
            for (const auto& [kind, path] : candidates)
                database.recordSourceCoverage(kind, path, "LOCKED",
                    "USERDATA_LOCKED; candidate path not asserted present");
            std::lock_guard<std::mutex> lock(mtx_);
            if (tasks_.count(task_id)) {
                tasks_[task_id].output_files_db = androidDbPath;
                tasks_[task_id].metadata["android_db"] = androidDbPath;
                tasks_[task_id].metadata["android_coverage_status"] = "COMPLETED_WITH_LOCKED_USERDATA";
            }
            return true;
        }

        // ── Unified mobile evidence package: analysis-only stage.
        // The package is the hand-off artefact; the original acquisition may
        // be gone. Mirrors the CLI's --mobile-package path.
        if (task.android_source == "mobile-evidence") {
            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 20,
                            "正在读取统一手机取数包…");
            if (!mobile_evidence::looksLikePackage(imagePath)) {
                if (failureCode) *failureCode = "INVALID_MOBILE_EVIDENCE_PACKAGE";
                add_audit_log(task_id, "ERROR",
                    "Not a mobile evidence package: " + imagePath);
                return false;
            }
            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 60,
                            "正在写入分析库…");
            AndroidAnalysisDatabase database(androidDbPath.string());
            if (!database.initialize()) {
                if (failureCode) *failureCode = "MOBILE_EVIDENCE_ANALYSIS_DB_INIT_FAILED";
                return false;
            }
            mobile_evidence::AnalysisOptions analysisOptions;
            mobile_evidence::AnalysisResult result;
            if (!mobile_evidence::analyzePackage(imagePath, database,
                                                 analysisOptions, result)) {
                if (failureCode) *failureCode = "MOBILE_EVIDENCE_ANALYSIS_FAILED";
                return false;
            }
            {
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id)) {
                    tasks_[task_id].output_files_db = androidDbPath;
                    tasks_[task_id].metadata["android_db"] = androidDbPath;
                    tasks_[task_id].metadata["mobile_evidence_package"] = imagePath;
                    tasks_[task_id].metadata["device_platform"] = "Android";
                }
            }
            set_result_db(task_id, androidDbPath);

            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 100,
                            "统一取数包分析完成");
            add_audit_log(task_id, "ANDROID_ANALYSIS",
                "Mobile evidence package analyzed: " + imagePath +
                ", contacts=" + std::to_string(result.contacts) +
                ", call_logs=" + std::to_string(result.callLogs) +
                ", sms=" + std::to_string(result.sms) +
                ", db=" + androidDbPath.string());
            return true;
        }

        // ── Meiya case export: decode containers, then run the unified
        // analysis on the produced package. AndroidAnalyzer cannot read these
        // formats, so this branch owns the whole extraction + analysis span.
        if (task.android_source == "meiya") {
            const auto taskRoot = pm.getTaskDir(task_id);
            const std::filesystem::path packagePath =
                taskRoot / (baseName + "_mobile_evidence.mep.db");

            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 20,
                            "正在解码美亚容器（掩码自推导 + SQLite 校验）…");
            meiya::MeiyaBackupExtractor extractor(imagePath);
            if (!extractor.initialize()) {
                if (failureCode) *failureCode = "MEIYA_CONTAINER_DECODE_FAILED";
                add_audit_log(task_id, "ERROR",
                    "Meiya container decode failed: " + extractor.error());
                return false;
            }
            for (const auto& container : extractor.containers()) {
                add_audit_log(task_id, "INFO",
                    "Meiya container " + container.sourcePath.filename().string() +
                    " [" + container.family + "] " + container.status +
                    (container.detail.empty() ? "" : " - " + container.detail));
            }

            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 55,
                            "正在转换为统一取数包…");
            mobile_evidence::MeiyaAdapterOptions adapterOptions;
            mobile_evidence::Package package;
            if (!mobile_evidence::buildPackageFromMeiya(extractor, adapterOptions, package)) {
                if (failureCode) *failureCode = "MEIYA_PACKAGE_BUILD_FAILED";
                return false;
            }
            mobile_evidence::Writer writer(packagePath.string());
            if (!writer.writePackage(package)) {
                if (failureCode) *failureCode = "MEIYA_PACKAGE_WRITE_FAILED";
                add_audit_log(task_id, "ERROR",
                    "Meiya package write failed: " + writer.error());
                return false;
            }
            writer.close();

            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 75,
                            "正在写入分析库…");
            AndroidAnalysisDatabase database(androidDbPath.string());
            if (!database.initialize()) {
                if (failureCode) *failureCode = "MEIYA_ANALYSIS_DB_INIT_FAILED";
                return false;
            }
            mobile_evidence::AnalysisOptions analysisOptions;
            mobile_evidence::AnalysisResult result;
            if (!mobile_evidence::analyzePackage(packagePath.string(), database,
                                                 analysisOptions, result)) {
                if (failureCode) *failureCode = "MEIYA_PACKAGE_ANALYSIS_FAILED";
                return false;
            }

            {
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id)) {
                    tasks_[task_id].output_files_db = androidDbPath;
                    tasks_[task_id].metadata["android_db"] = androidDbPath;
                    tasks_[task_id].metadata["mobile_evidence_package"] = packagePath.string();
                    tasks_[task_id].metadata["meiya_containers_total"] =
                        std::to_string(extractor.containers().size());
                    std::size_t decrypted = 0;
                    for (const auto& container : extractor.containers()) {
                        if (container.status == "decrypted") ++decrypted;
                    }
                    tasks_[task_id].metadata["meiya_containers_decrypted"] =
                        std::to_string(decrypted);
                    tasks_[task_id].metadata["meiya_records"] =
                        std::to_string(package.records.size());
                }
            }
            set_result_db(task_id, androidDbPath);

            update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 100,
                            "美亚案件解析完成");
            add_audit_log(task_id, "ANDROID_ANALYSIS",
                "Meiya case decoded: containers=" +
                std::to_string(extractor.containers().size()) +
                ", records=" + std::to_string(package.records.size()) +
                ", contacts=" + std::to_string(result.contacts) +
                ", call_logs=" + std::to_string(result.callLogs) +
                ", sms=" + std::to_string(result.sms) +
                ", db=" + androidDbPath.string());
            return true;
        }

        std::string analysisImagePath = imagePath;
        std::string analysisImageSha256;
        const bool containerImage = task.android_source == "android-container";
        if (containerImage) {
            const auto plan = task.metadata.find("preflight_plan_sha256");
            const auto sourceHash = task.metadata.find("preflight_source_sha256");
            const auto slot = task.metadata.find("preflight_selected_slot");
            if (plan == task.metadata.end() || sourceHash == task.metadata.end() ||
                slot == task.metadata.end()) {
                if (failureCode) *failureCode = "NORMALIZATION_PREFLIGHT_MISSING";
                return false;
            }
            const auto normalized = normalizeAndroidContainer(imagePath,
                pm.getTaskDir(task_id).string(), sourceHash->second, plan->second,
                std::stoi(slot->second),
                [this, &task_id]() { touch_heartbeat(task_id); },
                [this, &task_id]() { return is_task_cancelled(task_id); });
            if (!normalized.okay) {
                if (failureCode) *failureCode = normalized.code;
                add_audit_log(task_id, "ERROR", "Android normalization: " + normalized.code);
                return false;
            }
            const auto& output = normalized.manifest;
            if (output.value("normalized_kind", std::string()) == "super") {
                AndroidAnalysisDatabase database(androidDbPath.string());
                if (!database.initialize() || !database.recordSourceCoverage(
                    "userdata", imagePath, "NOT_PRESENT_IN_SOURCE",
                    "super supplies system/vendor/product logical partitions, not userdata")) {
                    if (failureCode) *failureCode = "SUPER_COVERAGE_WRITE_FAILED";
                    return false;
                }
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id)) {
                    tasks_[task_id].output_files_db = androidDbPath;
                    tasks_[task_id].metadata["android_db"] = androidDbPath;
                    tasks_[task_id].metadata["android_coverage_status"] = "SUPER_NORMALIZED_NO_USERDATA";
                    tasks_[task_id].metadata["android_normalization_manifest"] =
                        output.at("manifest_path").get<std::string>();
                }
                return true;
            }
            if (output.value("normalized_kind", std::string()) != "userdata") {
                if (failureCode) *failureCode = "NORMALIZATION_KIND_UNSUPPORTED";
                return false;
            }
            analysisImagePath = output.at("derived_image").get<std::string>();
            analysisImageSha256 = output.at("derived_sha256").get<std::string>();
            add_audit_log(task_id, "ANDROID_NORMALIZATION",
                "Sparse userdata normalized to validated raw image; manifest=" +
                output.at("manifest_path").get<std::string>());
            {
                std::lock_guard<std::mutex> lock(mtx_);
                if (tasks_.count(task_id))
                    tasks_[task_id].metadata["android_normalization_manifest"] =
                        output.at("manifest_path").get<std::string>();
            }
        }

        // dbManager is nullptr: logical sources have no _raw.db to read from.
        auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(analysisImagePath, nullptr);

        // Select the non-TSK backend matching the chosen data source.
        AndroidSourceMode mode =
            task.android_source == "zip"          ? AndroidSourceMode::Zip :
            task.android_source == "miui-backup"  ? AndroidSourceMode::MiuiBackup :
            isThunderForensicSource(task.android_source) ? AndroidSourceMode::ThunderForensicBackup :
            task.android_source == "tar"          ? AndroidSourceMode::Tar :
            task.android_source == "seven-zip"    ? AndroidSourceMode::SevenZip :
            task.android_source == "android-backup" ? AndroidSourceMode::AndroidBackup :
            (task.android_source == "filesystem-image" || containerImage) ? AndroidSourceMode::FilesystemImage :
                                                     AndroidSourceMode::LogicalDir;
        androidAnalyzer->setSourceMode(mode);
        if (containerImage) {
            androidAnalyzer->setSourceImageSha256(analysisImageSha256);
            androidAnalyzer->setExpectedPartitionOffset(0);
        } else if (archiveMode) {
            const auto hash = task.metadata.find("preflight_source_sha256");
            if (hash != task.metadata.end()) androidAnalyzer->setSourceImageSha256(hash->second);
        }
        if (mode == AndroidSourceMode::FilesystemImage) {
            const auto offset = task.metadata.find("preflight_partition_offset");
            if (offset != task.metadata.end())
                androidAnalyzer->setExpectedPartitionOffset(std::stoull(offset->second));
        }
        const char* fieldMode = std::getenv("TRACELENS_FIELD_AUTH");
        const char* outbound = std::getenv("FIELD_OUTBOUND_POLICY");
        const bool fieldDisabled = fieldMode && std::string(fieldMode) == "enabled" &&
            (!outbound || std::string(outbound) == "disabled");
        androidAnalyzer->setSkipAI(!task.llm_analyze || fieldDisabled);

        if (!task.backup_password.empty()) {
            androidAnalyzer->setBackupPassword(task.backup_password);
        }

        androidAnalyzer->setOutputDatabasePath(androidDbPath.string());

        if (!androidAnalyzer->initialize()) {
            if (failureCode) *failureCode = androidAnalyzer->sourceError();
            add_audit_log(task_id, "ERROR", "Failed to initialize Android analyzer (logical)");
            return false;
        }
        if (!task.platform_analyze) {
            add_audit_log(task_id, "SKIPPED", "Platform analysis disabled for this task");
        } else {
            androidAnalyzer->analyzeAndroidData();
        }
        if (containerImage &&
            !sourceMatchesPreflightHash(analysisImagePath, analysisImageSha256)) {
            if (failureCode) *failureCode = "DERIVED_IMAGE_CHANGED_AFTER_NORMALIZATION";
            return false;
        }
        if (archiveMode) {
            const auto expected = task.metadata.find("preflight_source_sha256");
            if (expected == task.metadata.end() ||
                !sourceMatchesPreflightHash(imagePath, expected->second)) {
                if (failureCode) *failureCode = "EVIDENCE_CHANGED_AFTER_PREFLIGHT";
                add_audit_log(task_id, "ERROR", "EVIDENCE_CHANGED_AFTER_PREFLIGHT during Android analysis");
                return false;
            }
        }
        if (containerImage) {
            androidAnalyzer.reset(); // Close SQLite before hashing the final artifact.
            const auto manifestPath = pm.getTaskDir(task_id) / "android_normalization_manifest.json";
            if (!appendAndroidArtifactProvenance(manifestPath, androidDbPath,
                                                 analysisImageSha256)) {
                if (failureCode) *failureCode = "ARTIFACT_PROVENANCE_FAILED";
                return false;
            }
        }

        // Record the produced database on the task so downstream result
        // retrieval and the MIUI query routes find it.
        {
            std::lock_guard<std::mutex> lock(mtx_);
            if (tasks_.count(task_id)) {
                tasks_[task_id].output_files_db = androidDbPath;
                tasks_[task_id].metadata["android_db"] = androidDbPath;
            }
        }
        set_result_db(task_id, androidDbPath);

        update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 100,
                        "Android analysis completed");
        add_audit_log(task_id, "ANDROID_ANALYSIS",
                      "Logical Android analysis completed (source=" + task.android_source +
                      ", db=" + androidDbPath.string() + ")");
        return true;
    } catch (const std::exception& e) {
        if (failureCode) *failureCode = "ANDROID_ARCHIVE_ANALYSIS_EXCEPTION";
        add_audit_log(task_id, "ERROR",
                      std::string("Logical Android analysis exception: ") + e.what());
        std::cerr << "Error: Logical Android analysis failed: " << e.what() << std::endl;
        return false;
    }
}
