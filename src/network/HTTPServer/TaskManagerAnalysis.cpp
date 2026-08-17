// TaskManagerAnalysis.cpp
// TaskManager::start_analysis — pipeline orchestration for a single forensic task.
// Extracted from TaskManager.cpp for maintainability; same class, same public API.

#include "TaskManager.h"
#include "TaskPersistence.h"
#include "TaskWatchdog.h"
#include "TaskSerialization.h"
#include "LLMPythonProxy.h"
#include "EventClusterAnalyzer.h"
#include "SceneDetector.h"
#include "ConfigManager/ConfigManager.h"
#include "PathManager/PathManager.h"
#include "FileFilter/FileFilter.h"
#include "../../analyzers/WindowsFilesAnalyzer/Common/WindowsAnalyzerDeclarations.h"
#include "../../analyzers/LinuxFilesAnalyzer/Common/LinuxAnalyzerDeclarations.h"
#include <fstream>


using forensics::TaskPersistence;
using forensics::TaskWatchdog;
using forensics::FileFilter;

void TaskManager::start_analysis(const std::string& task_id) {
    if (!analysis_pool_) {
        std::cerr << "CRITICAL: ThreadPool not initialized in TaskManager" << std::endl;
        return;
    }

    analysis_pool_->enqueue([this, task_id]() {
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
                update_status(task_id, TaskStatus::FAILED, "Image file not found");
                return;
            }

            // Generate DB paths
            std::filesystem::path p(imagePath);
            std::string baseName = p.stem().string();

            // Use PathManager for per-task directory (HTTP Server mode)
            auto& pm = forensics::PathManager::instance();
            std::string rawDbPath, eventDbPath, fileDbPath;

            if (!task.db_output_dir.empty()) {
                // Legacy override: use user-specified db_output_dir
                std::filesystem::create_directories(task.db_output_dir);
                std::string outPrefix = task.db_output_dir + "/";
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
                                  "Android logical analysis failed for source: " + task.android_source);
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

                // Graphiti ingestion (best-effort, fire-and-forget) — same as the
                // TSK pipeline tail so logical tasks join the knowledge graph too.
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
                update_progress(task_id, TaskPhase::FINALIZING, 10, "Triggering knowledge graph ingestion...");
                try {
                    auto& proxy = forensics::LLMPythonProxy::instance();
                    std::string graphiti_job_id = proxy.async_ingest(task_id, forensics::IngestionMode::FULL);
                    if (!graphiti_job_id.empty()) {
                        add_audit_log(task_id, "GRAPHITI_INGESTION",
                            "Triggered Graphiti knowledge graph ingestion (job_id: " + graphiti_job_id + ")");
                        {
                            std::lock_guard<std::mutex> lock(mtx_);
                            if (tasks_.count(task_id)) tasks_[task_id].graphiti_job_id = graphiti_job_id;
                        }
                        save_tasks_internal();
                    }
                } catch (const std::exception& e) {
                    std::cerr << "Warning: Exception triggering Graphiti ingestion: " << e.what() << std::endl;
                }

                // Finalize — android.db is the result database for logical tasks.
                if (is_task_cancelled(task_id)) { update_status(task_id, TaskStatus::CANCELLED, "Task cancelled"); return; }
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
            if (task.enable_decryption) {
                analyzer->setEnableDecryption(true);
                if (!task.key_file_dir.empty()) analyzer->setKeyFileDir(task.key_file_dir);
                if (!task.decrypt_password.empty()) analyzer->setDecryptPassword(task.decrypt_password);
            }
            task.decrypt_password.clear();
            clear_decryption_password(task_id);

            if (!analyzer->analyze()) {
                update_status(task_id, TaskStatus::FAILED, "Failed to analyze image");
                return;
            }
            update_progress(task_id, TaskPhase::IMAGE_ANALYSIS, 50, "Image analysis completed, extracting metadata...");

            if (!analyzer->extractToDatabase(rawDbPath)) {
                update_status(task_id, TaskStatus::FAILED, "Failed to create raw database");
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
                update_status(task_id, TaskStatus::FAILED, "Failed to extract timeline events");
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
                update_status(task_id, TaskStatus::FAILED, "Failed to classify files");
                return;
            }
            update_progress(task_id, TaskPhase::FILE_CLASSIFICATION, 100, "File classification completed");

            // 4. LLM Analysis (Optional) - Stores descriptions directly in _files.db
            if (task.llm_analyze) {
                if (is_task_cancelled(task_id)) { return; }
                update_progress(task_id, TaskPhase::LLM_ANALYSIS, 10, "Starting LLM file description generation...");
                
                forensics::LLMAnalysisService llmService;
                if (llmService.initialize()) {
                    llmService.setSceneType(sceneType);
                    // Provide image + raw DB paths so files can be extracted from the
                    // image before LLM analysis (files live inside the image, not on disk).
                    llmService.setImagePaths(imagePath, effectiveRawDb);
                    auto& config = forensics::ConfigManager::instance();
                    forensics::LLMAnalysisService::AnalysisOptions llmOpts;
                    llmOpts.maxFiles = config.getLLMMaxFiles();
                    llmOpts.maxContentLength = config.getLLMMaxContentLength();
                    llmOpts.skipBinaryFiles = config.getLLMSkipBinary();
                    
                    int analyzedCount = 0;
                    
                    if (task.llm_mode == "full") {
                        // Full mode: analyze all files
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 30, "Full mode: Analyzing all files...");
                        analyzedCount = llmService.analyzeAllFiles(task_id, fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) {
                                if (is_task_cancelled(task_id)) return; // Wait, analyzeAllFiles doesn't support cancellation return value?
                                int progress = 30;
                                if (total > 0) {
                                    progress += (current * 60 / total);
                                }
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, progress, 
                                    "Analyzing file " + std::to_string(current) + "/" + std::to_string(total));
                            });
                    } else {
                        // Smart mode: LLM selects important files first
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 20, "Smart mode: Selecting important files...");
                        // For smart mode, we scan more files initially (up to 2x global limit) to provide better context
                        llmOpts.maxFiles = std::max(llmOpts.maxFiles, static_cast<size_t>(1000));

                        analyzedCount = llmService.analyzeSmartFiles(task_id, fileDbPath, llmOpts,
                            [this, task_id](int current, int total, const std::string& file) {
                                if (is_task_cancelled(task_id)) return;
                                int progress = 30;
                                if (total > 0) {
                                    progress += (current * 60 / total);
                                }
                                update_progress(task_id, TaskPhase::LLM_ANALYSIS, progress, 
                                    "Analyzing important file " + std::to_string(current) + "/" + std::to_string(total));
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
                        analyzedCount = clusterAnalyzer.analyzeEventClusters(eventDbPath, allClusters);
                    } else {
                        // Smart mode: LLM selects important event clusters first
                        update_progress(task_id, TaskPhase::LLM_ANALYSIS, 92, "Smart mode: Selecting important event clusters...");
                        analyzedCount = clusterAnalyzer.analyzeSmartEventClusters(eventDbPath, 100); // 分析最多100个重要事件簇
                    }
                    
                    update_progress(task_id, TaskPhase::LLM_ANALYSIS, 95, 
                        "Event cluster analysis completed: " + std::to_string(analyzedCount) + " clusters analyzed");
                } else {
                    std::cerr << "Warning: Failed to initialize event cluster analyzer" << std::endl;
                }
            }

            // 6. Platform-Specific Analysis (Unified)
            if (!task.scenarios.empty()) {
                if (is_task_cancelled(task_id)) { return; }
                int total_scenarios = static_cast<int>(task.scenarios.size());
                update_progress(task_id, TaskPhase::PLATFORM_ANALYSIS, 0,
                    "Starting platform analysis for " + std::to_string(total_scenarios) + " scenario(s)...");

                int scenario_index = 0;
                for (auto scenario : task.scenarios) {
                    if (is_task_cancelled(task_id)) { return; }

                    int base_progress = (scenario_index * 100) / total_scenarios;
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

            // 7. Graphiti Knowledge Graph Ingestion (Async, Fire-and-Forget)
            if (is_task_cancelled(task_id)) { return; }
            update_progress(task_id, TaskPhase::FINALIZING, 10, "Triggering knowledge graph ingestion...");

            // Trigger Graphiti ingestion in the background (non-blocking)
            // This will create File entities, link episodes, and build entity relationships
            try {
                auto& proxy = forensics::LLMPythonProxy::instance();
                std::string graphiti_job_id = proxy.async_ingest(task_id, forensics::IngestionMode::FULL);

                if (!graphiti_job_id.empty()) {
                    add_audit_log(task_id, "GRAPHITI_INGESTION",
                        "Triggered Graphiti knowledge graph ingestion (job_id: " + graphiti_job_id + ")");

                    // Store the Graphiti job ID for potential status tracking
                    task.graphiti_job_id = graphiti_job_id;
                    save_tasks_internal();
                } else {
                    std::cerr << "Warning: Failed to trigger Graphiti ingestion for task " << task_id << std::endl;
                    add_audit_log(task_id, "WARNING", "Failed to trigger Graphiti ingestion");
                }
            } catch (const std::exception& e) {
                // Don't fail the entire task if Graphiti ingestion fails
                std::cerr << "Warning: Exception triggering Graphiti ingestion: " << e.what() << std::endl;
                add_audit_log(task_id, "WARNING", "Graphiti ingestion failed: " + std::string(e.what()));
            }

            // Finalization
            if (is_task_cancelled(task_id)) { return; }
            update_progress(task_id, TaskPhase::FINALIZING, 50, "Finalizing analysis results...");

            set_result_db(task_id, fileDbPath);
            update_progress(task_id, TaskPhase::FINALIZING, 100, "Analysis completed successfully");
            update_status(task_id, TaskStatus::COMPLETED, "Analysis completed successfully");

        } catch (const std::exception& e) {
            update_status(task_id, TaskStatus::FAILED, std::string("Analysis error: ") + e.what());
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

        // android.db follows the per-task convention used by RouteHelpers'
        // get_database_path("android"). It is also exposed as the task's
        // output_files_db so /tasks/<id>/results and the MIUI query routes
        // (which fall back to output_files_db) both resolve to it.
        std::string androidDbPath;
        if (!task.db_output_dir.empty()) {
            androidDbPath = task.db_output_dir + "/" + baseName + "_android.db";
        } else {
            androidDbPath = pm.getTaskDbPaths(task_id, baseName).androidDb.string();
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

        androidAnalyzer->setOutputDatabasePath(androidDbPath);

        if (!androidAnalyzer->initialize()) {
            add_audit_log(task_id, "ERROR", "Failed to initialize Android analyzer (logical)");
            return false;
        }
        androidAnalyzer->analyzeAndroidData();

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
                      ", db=" + androidDbPath + ")");
        return true;
    } catch (const std::exception& e) {
        add_audit_log(task_id, "ERROR",
                      std::string("Logical Android analysis exception: ") + e.what());
        std::cerr << "Error: Logical Android analysis failed: " << e.what() << std::endl;
        return false;
    }
}

