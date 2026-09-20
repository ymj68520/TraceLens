// TaskManagerAnalysis.cpp
// TaskManager::start_analysis — pipeline orchestration for a single forensic task.
// Extracted from TaskManager.cpp for maintainability; same class, same public API.

#include "TaskManager.h"
#include "TaskPersistence.h"
#include "TaskWatchdog.h"
#include "TaskSerialization.h"
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


using forensics::TaskPersistence;
using forensics::TaskWatchdog;
using forensics::FileFilter;

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
            active_job = proxy.async_ingest(task_id, forensics::IngestionMode::FULL);
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
            if (task.id.empty()) {
                std::cerr << "Analysis Error: Task " << task_id << " not found in manager" << std::endl;
                return;
            }
            
            if (is_task_cancelled(task_id)) {
                update_status(task_id, TaskStatus::CANCELLED, "Cancelled before start");
                return;
            }

            // Guard against re-running
            if (task.status == TaskStatus::RUNNING || task.status == TaskStatus::COMPLETED) {
                return;
            }

            // Check dependencies
            if (!can_start_task(task_id)) {
                update_status(task_id, TaskStatus::PENDING, "Waiting for dependencies");
                return;
            }

            std::string imagePath = task.image_path;
            update_status(task_id, TaskStatus::RUNNING, "Initializing analysis...");
            update_progress(task_id, TaskPhase::INITIALIZING, 10, "Initializing analysis environment...");

            if (!std::filesystem::exists(imagePath)) {
                update_status(task_id, TaskStatus::FAILED, "Image file not found",
                              "Image file not found on disk: '" + imagePath +
                              "'. Verify the path exists and is readable by the server process.");
                return;
            }

            // Generate DB paths
            std::filesystem::path p(imagePath);
            std::string baseName = p.stem().string();

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

            update_progress(task_id, TaskPhase::INITIALIZING, 30, "Analysis environment initialized");

            // ── Logical Android analysis short-circuit ───────────────────────
            // A logical data source (directory / zip / MIUI backup) is NOT a TSK
            // disk image: there is no filesystem to carve and no _raw.db to build.
            // Run the Android analyzer directly against the source and skip the
            // entire TSK / event / classification pipeline.
            if (task.android_source == "dir" ||
                task.android_source == "zip" ||
                task.android_source == "miui-backup") {

                if (is_task_cancelled(task_id)) {
                    update_status(task_id, TaskStatus::CANCELLED, "Task cancelled");
                    clear_backup_password(task_id);
                    return;
                }

                bool ok = runLogicalAndroidAnalysis(task, baseName);

                // Drop the runtime-only backup password as soon as the analyzer
                // has consumed it (mirrors the decryption-password handling).
                clear_backup_password(task_id);

                if (!ok) {
                    update_status(task_id, TaskStatus::FAILED,
                                  "Android logical analysis failed for source: " + task.android_source,
                                  "Android logical analysis failed for source '" + task.android_source +
                                      "' at path '" + task.image_path +
                                      "'. Verify the source layout (dir tree / zip / MIUI backup) and "
                                      "see cpp_server.log for the analyzer error.");
                    return;
                }

                if (is_task_cancelled(task_id)) {
                    update_status(task_id, TaskStatus::CANCELLED, "Task cancelled");
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

                // The Android analyzer already ran its own artifact-level LLM
                // analysis inside analyzeAndroidData() (AndroidLLMAnalysisService,
                // mirroring the Linux/Windows analyzers). The legacy file-level
                // LLMAnalysisService is a no-op on android.db (no `files` table),
                // so we only surface a progress note here rather than re-running it.
                if (task.llm_analyze) {
                    update_progress(task_id, TaskPhase::LLM_ANALYSIS, 100,
                                    "Android artifact LLM analysis completed (per-artifact)");
                }

                // No Graphiti gate for logical sources: android.db carries no
                // `files`/`events` tables, so a FULL ingestion job (raw_reader)
                // can never succeed — every dir/zip/miui-backup task failed at
                // 99% under the SPEC §5 gate. Skip ingestion until a reader for
                // android.db exists and finalize on the analysis result itself.
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
                add_audit_log(task_id, "GRAPHITI_INGESTION",
                              "Skipped: no Graphiti reader for android.db (source: " +
                                  task.android_source + ")");
                update_progress(task_id, TaskPhase::FINALIZING, 100, "Analysis completed successfully");
                update_status(task_id, TaskStatus::COMPLETED, "Android logical analysis completed");
                return;
            }

            // 1. Image Analysis
            if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 10, "Analyzing image structure...");
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
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 50, "Image analysis completed, extracting metadata...");

            if (!analyzer->extractToDatabase(rawDbPath)) {
                update_status(task_id, TaskStatus::FAILED, "Failed to create raw database",
                              "extractToDatabase produced no files for '" + imagePath +
                              "' (raw DB: " + rawDbPath +
                              "). Either the image contains no walkable filesystem or the "
                              "filesystem walker failed. See cpp_server.log for this task.");
                return;
            }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 100, "Image analysis and metadata extraction completed");

            // 1.4b. Auto-detect platform scenarios when the user did not pick any.
            // Probes the *un-filtered* raw DB for tell-tale artifact paths and
            // back-fills task.scenarios so downstream classification / platform
            // analyzers run against the right OS. Must run before the filter,
            // since filter profiles drop system-noise — exactly these markers.
            if (task.scenarios.empty()) {
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
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
            if (!task.filter_profile.empty()) {
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
                update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 5, "Applying file filter: " + task.filter_profile + "...");

                try {
                    FileFilter filter;
                    std::string filteredDbPath = rawDbPath;
                    size_t pos = filteredDbPath.rfind("_raw.db");
                    if (pos != std::string::npos) {
                        filteredDbPath.replace(pos, 7, "_filtered.db");
                    } else {
                        filteredDbPath += ".filtered";
                    }

                    auto filterStats = filter.applyFilterByName(rawDbPath, filteredDbPath, task.filter_profile);
                    if (filterStats.included_files > 0) {
                        effectiveRawDb = filteredDbPath;
                        update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10,
                            "Filter applied: " + std::to_string(filterStats.included_files) + "/" +
                            std::to_string(filterStats.total_files) + " files selected");
                    } else {
                        std::cerr << "Warning: Filter excluded all files for task " << task_id << std::endl;
                    }
                } catch (const std::exception& e) {
                    std::cerr << "Warning: Filter failed for task " << task_id << ": " << e.what() << std::endl;
                    // Continue with unfiltered data
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
            if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
            update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 10, "Extracting timeline events...");
            auto eventExtractor = std::make_unique<EventExtractor>(effectiveRawDb, eventDbPath);
            if (!eventExtractor->extractEvents()) {
                std::cerr << "Error: Failed to extract events from " << effectiveRawDb << std::endl;
                update_status(task_id, TaskStatus::FAILED, "Failed to extract timeline events",
                              "EventExtractor::extractEvents() failed on raw DB '" + effectiveRawDb +
                                  "' (events DB: " + eventDbPath + "). See cpp_server.log.");
                return;
            }
            update_progress(task_id, TaskPhase::EVENT_EXTRACTION, 100, "Timeline events extraction completed");

            // 3. File Classification (scene-aware)
            if (is_task_cancelled(task_id)) { return; }
            update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 10, "Classifying files by type...");
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

            if (!fileClassifier->classifyAndExtract()) {
                update_status(task_id, TaskStatus::FAILED, "Failed to classify files",
                              "FileClassifier::classifyAndExtract() failed (raw DB: " + effectiveRawDb +
                                  ", files DB: " + fileDbPath + "). See cpp_server.log.");
                return;
            }
            update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 100, "File classification completed");

            // Publish the files DB path as soon as it exists: SPEC E record
            // calls arrive during LLM analysis and resolve the write target
            // from this task field — setting it only at finalization left it
            // empty for the whole LLM phase (HTTP 400 on every record call).
            set_result_db(task_id, fileDbPath);

            // 4. LLM Analysis (Optional) - Stores descriptions directly in _files.db
            if (task.llm_analyze) {
                if (is_task_cancelled(task_id)) { return; }
                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 10, "Starting LLM file description generation...");
                
                forensics::LLMAnalysisService llmService;
                if (llmService.initialize()) {
                    llmService.setSceneType(sceneType);
                    // Provide image + raw DB paths so files can be extracted from the
                    // image before LLM analysis (files live inside the image, not on disk).
                    llmService.setImagePaths(imagePath, effectiveRawDb, task_id);
                    auto& config = forensics::ConfigManager::instance();
                    forensics::LLMAnalysisService::AnalysisOptions llmOpts;
                    llmOpts.maxFiles = config.getLLMMaxFiles();
                    llmOpts.maxContentLength = config.getLLMMaxContentLength();
                    llmOpts.skipBinaryFiles = config.getLLMSkipBinary();
                    
                    int analyzedCount = 0;
                    
                    if (task.llm_mode == "full") {
                        // Full mode: analyze all files
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 30, "Full mode: Analyzing all files...");
                        analyzedCount = llmService.analyzeAllFiles(fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) -> bool {
                                if (is_task_cancelled(task_id)) return false;
                                int progress = 30;
                                if (total > 0) {
                                    progress += (current * 60 / total);
                                }
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, progress,
                                    "Analyzing file " + std::to_string(current) + "/" + std::to_string(total));
                                return true;
                            });
                    } else {
                        // Smart mode: LLM selects important files first.
                        // File budget honours LLM_MAX_FILES exactly — the previous
                        // hardcoded floor of 1000 made real-image tasks run for
                        // many hours on local LLMs.
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 20, "Smart mode: Selecting important files...");
                        // 候选扫描范围由 LLM_SMART_CANDIDATE_FILES 控制（selectImportantFiles 内部读取），
                        // 分析数量上限沿用 LLM_MAX_FILES；两者默认有限（500/1000），显式配置 0 才是全量。
                        analyzedCount = llmService.analyzeSmartFiles(fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) -> bool {
                                if (is_task_cancelled(task_id)) return false;
                                int progress = 30;
                                if (total > 0) {
                                    progress += (current * 60 / total);
                                }
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, progress,
                                    "Analyzing important file " + std::to_string(current) + "/" + std::to_string(total));
                                return true;
                            });
                    }
                    
                    update_progress(task_id, TaskPhase::LLM_ANALYSIS, 100, 
                        "LLM analysis completed: " + std::to_string(analyzedCount) + " files analyzed (stored in _files.db)");
                } else {
                    std::cerr << "Warning: Failed to initialize LLM analysis service" << std::endl;
                }
            }

            // 5. Event Cluster Analysis (Optional) - Similar to LLM analysis for files
            if (task.llm_analyze) {
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

                    int base_progress = (scenario_index * 100) / total_scenarios;
                    int per_scenario_progress = std::max(1, 100 / total_scenarios);
                    std::string scenario_name = scenario_to_string(scenario);
                    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, base_progress,
                        "Analyzing " + scenario_name + " artifacts...");

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
                                androidAnalyzer->setOutputDatabasePath(androidDbPath);
                                if (androidAnalyzer->initialize()) {
                                    androidAnalyzer->analyzeAndroidData();
                                } else {
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
                                    break;
                                }
                                auto linuxAnalyzer = std::make_unique<LinuxFilesAnalyzer>(imagePath, dbManager.get());
                                std::string linuxDbPath = pm.getTaskDbPaths(task_id, baseName).linuxDb.string();
                                linuxAnalyzer->setOutputDatabasePath(linuxDbPath);
                                attachPlatformProgressCallback(*linuxAnalyzer, task_id, base_progress,
                                                               per_scenario_progress, scenario_name);
                                if (linuxAnalyzer->initialize()) {
                                    linuxAnalyzer->analyzeLinuxData();
                                } else {
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
                    } catch (const std::exception& e) {
                        std::cerr << "Warning: " << scenario_name << " analysis failed: " << e.what() << std::endl;
                        add_audit_log(task_id, "WARNING", scenario_name + " analysis failed: " + std::string(e.what()));
                    }

                    scenario_index++;
                    int done_progress = (scenario_index * 100) / total_scenarios;
                    update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, done_progress,
                        scenario_name + " analysis completed");
                }
            }

            // 7. File Carving (Optional) — signature-based recovery from unallocated space
            if (task.file_carving && !is_task_cancelled(task_id)) {
                update_progress(task_id, TaskPhase::FILE_CARVING, 0, "Starting file carving...");
                try {
                    std::filesystem::path carveDir = pm.getTaskDir(task_id) / "carved_files";
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
                } catch (const std::exception& e) {
                    std::cerr << "Warning: File carving failed: " << e.what() << std::endl;
                    add_audit_log(task_id, "WARNING", std::string("File carving failed: ") + e.what());
                }
            }

            // 8. Graphiti Knowledge Graph Ingestion — MVP completion gate.
            // mvp-phase1-acceptance SPEC §5: the task is COMPLETED only once
            // ingestion has finished; failure after retries fails the task.
            if (is_task_cancelled(task_id)) { return; }
            update_progress(task_id, TaskPhase::FINALIZING, 10, "Triggering knowledge graph ingestion...");

            std::string graphiti_job_id;
            try {
                auto& proxy = forensics::LLMPythonProxy::instance();
                graphiti_job_id = proxy.async_ingest(task_id, forensics::IngestionMode::FULL);
            } catch (const std::exception& e) {
                std::cerr << "Warning: Exception triggering Graphiti ingestion: " << e.what() << std::endl;
                add_audit_log(task_id, "WARNING", "Graphiti ingestion failed: " + std::string(e.what()));
            }
            if (!graphiti_job_id.empty()) {
                add_audit_log(task_id, "GRAPHITI_INGESTION",
                    "Triggered Graphiti knowledge graph ingestion (job_id: " + graphiti_job_id + ")");
                task.graphiti_job_id = graphiti_job_id;
                save_tasks_internal();
            }

            // Finalization — gated on ingestion (budget: GRAPHITI_INGEST_WAIT_TIMEOUT_MIN,
            // 0 restores the legacy fire-and-forget completion).
            const bool ingestion_ok = wait_for_graphiti_ingestion(task_id, graphiti_job_id);
            if (is_task_cancelled(task_id)) { return; }

            set_result_db(task_id, fileDbPath);
            if (!ingestion_ok) {
                update_status(task_id, TaskStatus::FAILED,
                              "Knowledge graph ingestion did not complete",
                              "Graphiti ingestion failed or timed out (budget: GRAPHITI_INGEST_WAIT_TIMEOUT_MIN minutes). Analysis artifacts remain available for browsing.");
                add_audit_log(task_id, "ERROR", "Analysis failed at the Graphiti ingestion gate");
                return;
            }
            update_progress(task_id, TaskPhase::FINALIZING, 100, "Analysis completed successfully");
            update_status(task_id, TaskStatus::COMPLETED, "Analysis completed successfully");

        } catch (const std::exception& e) {
            update_status(task_id, TaskStatus::FAILED, std::string("Analysis error: ") + e.what(),
                          std::string("Unhandled exception in analysis pipeline: ") + e.what());
            add_audit_log(task_id, "ERROR", "Analysis failed: " + std::string(e.what()));
        }
    });
}

bool TaskManager::runLogicalAndroidAnalysis(const AnalysisTask& task,
                                            const std::string& baseName) {
    const std::string& task_id = task.id;
    const std::string& imagePath = task.image_path;

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

        // dbManager is nullptr: logical sources have no _raw.db to read from.
        auto androidAnalyzer = std::make_unique<AndroidAnalyzer>(imagePath, nullptr);

        // Select the non-TSK backend matching the chosen data source.
        AndroidSourceMode mode =
            task.android_source == "zip"          ? AndroidSourceMode::Zip :
            task.android_source == "miui-backup"  ? AndroidSourceMode::MiuiBackup :
                                                     AndroidSourceMode::LogicalDir;
        androidAnalyzer->setSourceMode(mode);

        if (!task.backup_password.empty()) {
            androidAnalyzer->setBackupPassword(task.backup_password);
        }

        androidAnalyzer->setOutputDatabasePath(androidDbPath.string());

        if (!androidAnalyzer->initialize()) {
            add_audit_log(task_id, "ERROR", "Failed to initialize Android analyzer (logical)");
            return false;
        }
        if (!task.platform_analyze) {
            add_audit_log(task_id, "SKIPPED", "Platform analysis disabled for this task");
        } else {
            androidAnalyzer->analyzeAndroidData();
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
        add_audit_log(task_id, "ERROR",
                      std::string("Logical Android analysis exception: ") + e.what());
        std::cerr << "Error: Logical Android analysis failed: " << e.what() << std::endl;
        return false;
    }
}

