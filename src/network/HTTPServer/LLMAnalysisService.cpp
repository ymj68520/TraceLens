#include "LLMAnalysisService.h"
#include "FileSelectionService.h"
#include "DatabaseManager/SourceIndex.h"
#include "network/HTTPServer/LLMPythonProxy.h"
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "core/PathManager/PathManager.h"
#include "network/HTTPServer/LLMScratch.h"
#include <sqlite3.h>
#include <iostream>
#include <filesystem>
#include <sstream>
#include <algorithm>
#include <unordered_set>
#include <unordered_map>
#include <queue>
#include <functional>
#include <cctype>
#include <cstdlib>
#include <ctime>
#include <cstring>
#include <fstream>
#include <numeric>
#include <atomic>
#include <mutex>
#include <thread>

namespace fs = std::filesystem;

namespace forensics {

namespace {
// Lowest path priority that still counts as evidence. Priority 5 is the noise
// bucket (temp dirs, registry transaction logs, binaries demoted by the header
// check); a budget larger than the evidence stays unfilled rather than being
// padded with it. Shared by the full-database candidate scan and the
// deterministic ranking so both apply the same floor.
constexpr int kMinSelectablePriority = 10;

// TSK exposes NTFS metafiles under names starting with "$". Most are storage
// bookkeeping, but two are primary evidence:
//   $MFT             the master file table (every file record and timestamp)
//   $UsnJrnl         the USN change journal (create/write/delete/rename trail)
//   $Secure:$SDS     the security descriptor stream (ACL history)
// Returning true here means "keep this entry as a candidate".
bool isForensicDollarEntry(const std::string& name) {
    static const std::vector<std::string> keep = {
        "$mft", "$usnjrnl", "$secure:$sds", "$logfile", "$i30",
    };
    std::string lower;
    lower.reserve(name.size());
    for (char c : name) lower += static_cast<char>(::tolower(static_cast<unsigned char>(c)));
    for (const auto& k : keep) {
        if (lower == k) return true;
    }
    return false;
}
}  // namespace

LLMAnalysisService::LLMAnalysisService() = default;
LLMAnalysisService::~LLMAnalysisService() {
    if (!scratchTaskId_.empty()) {
        forensics::llm_scratch::cleanupTask(scratchTaskId_);
    }
}

bool LLMAnalysisService::initialize() {
    try {
        auto& configManager = ConfigManager::instance();
        if (!configManager.isLoaded()) {
            configManager.load();
        }
        
        // Use standard text model config for forensics analysis
        auto config = configManager.getTextModelConfig();
        
        router_ = std::make_shared<llm::ModelRouter>();
        router_->addModel("default", config, llm::ModelInfo{
            "default", 
            "text", 
            {llm::ModelCapability::TextGeneration, llm::ModelCapability::Analysis}
        });
        fileAnalyzer_ = std::make_unique<llm::FileAnalyzer>(router_);
        initialized_ = true;
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Failed to initialize LLMAnalysisService: " << e.what() << std::endl;
        return false;
    }
}

void LLMAnalysisService::setImagePaths(const std::string& imagePath,
                                       const std::string& rawDbPath,
                                       const std::string& taskId) {
    imagePath_ = imagePath;
    rawDbPath_ = rawDbPath;
    scratchTaskId_ = taskId;
}

std::string LLMAnalysisService::resolveFileForAnalysis(const std::string& filePath) {
    // No image configured: file paths are host-filesystem paths (e.g. loose files)
    if (imagePath_.empty() || rawDbPath_.empty()) {
        return filePath;
    }

    // Image-backed analysis: ALWAYS extract from the image. A host-filesystem
    // fast path (fs::exists) would silently analyse the ANALYST's own files
    // (e.g. /etc/passwd exists on any Linux host) instead of the evidence.

    // Extract the file from the forensic image to a temporary directory.
    try {
        // Reuse one extractor across files: opening the image + every partition
        // + the SQLite DB per file dominates analysis time on large images.
        std::lock_guard<std::mutex> extractLock(imageExtractorMutex_);
        if (!imageExtractor_) {
            auto extractor = std::make_unique<FileExtractor>(imagePath_, rawDbPath_);
            if (!extractor->initialize()) {
                std::cerr << "Warning: Failed to initialize FileExtractor for image: " << imagePath_ << std::endl;
                return "";
            }
            imageExtractor_ = std::move(extractor);
        }
        FileExtractor& extractor = *imageExtractor_;

        const auto extractDir = scratchTaskId_.empty()
            ? std::filesystem::path(forensics::llm_scratch::dirForTask(scratchTaskId_))
            : PathManager::instance().getTaskExtractDir(scratchTaskId_);
        const auto staged=extractor.materializeSource(filePath,extractDir);
        if(staged.value("success",false)) return staged["materialized_path"].get<std::string>();
        std::cerr << "Warning: Could not extract file from image: " << filePath << std::endl;
        return "";
    } catch (const std::exception& e) {
        std::cerr << "Warning: Exception extracting file " << filePath << ": " << e.what() << std::endl;
        return "";
    }
}

int LLMAnalysisService::analyzeAllFiles(const std::string& filesDbPath,
                                         const AnalysisOptions& options,
                                         ProgressCallback progressCallback) {
    if (!initialized_) {
        if (!initialize()) {
            return 0;
        }
    }

    // Get files to analyze from the database
    auto files = selectImportantFiles(filesDbPath, options.maxFiles);
    if (files.empty()) {
        return 0;
    }

    // 请求可收紧数量；maxFiles == 0 仍遵守选择计划中的有限配置。
    if (options.maxFiles > 0 && files.size() > options.maxFiles) {
        files.resize(options.maxFiles);
    }

    return runFileAnalyses(filesDbPath, options, files, progressCallback, "full-mode");
}

int LLMAnalysisService::llmConcurrency() const {
    auto& configManager = ConfigManager::instance();
    if (!configManager.isLoaded()) {
        configManager.load();
    }
    int workers = configManager.getLLMMaxConcurrency();
    return workers < 1 ? 1 : workers;
}

int LLMAnalysisService::runFileAnalyses(const std::string& filesDbPath,
                                        const AnalysisOptions& options,
                                        const std::vector<std::string>& files,
                                        ProgressCallback progressCallback,
                                        const char* modeLabel) {
    const int total = static_cast<int>(files.size());
    if (total == 0) {
        return 0;
    }

    // One shared LLMClient serialises every chat() on its httplib handle, so
    // each worker gets its own router and FileAnalyzer. Workers is 1 unless
    // LLM_MAX_CONCURRENCY says otherwise, which keeps the old single-flight path.
    int workers = llmConcurrency();
    if (workers > total) {
        workers = total;
    }

    std::atomic<int> next{0};
    std::atomic<int> analyzed{0};
    std::atomic<bool> stop{false};
    std::mutex progressMutex;

    auto worker = [&]() {
        while (!stop.load()) {
            const int index = next.fetch_add(1);
            if (index >= total) {
                return;
            }
            const std::string& filePath = files[static_cast<size_t>(index)];
            const auto planId=selectionPlan_.value("plan_id",std::string());
            const auto sourceKey=scratchTaskId_+":"+filePath;
            try {
            if(!planId.empty() && selection::finished(filesDbPath,planId,sourceKey))continue;
            auto router=std::make_shared<llm::ModelRouter>();
            auto config=ConfigManager::instance().getTextModelConfig();
            config.budgetDb=filesDbPath;config.budgetPlan=planId;config.budgetSource=sourceKey;
            config.budgetTask=scratchTaskId_;config.budgetReference=filePath;
            router->addModel("default",config,llm::ModelInfo{"default","text",{llm::ModelCapability::TextGeneration,llm::ModelCapability::Analysis}});
            auto vision=ConfigManager::instance().getVisionModelConfig();vision.budgetDb=config.budgetDb;vision.budgetPlan=config.budgetPlan;
            vision.budgetSource=config.budgetSource;vision.budgetTask=config.budgetTask;vision.budgetReference=config.budgetReference;
            router->addModel("vision",vision,llm::ModelInfo{"vision","vision",{llm::ModelCapability::Vision,llm::ModelCapability::ImageAnalysis}});
            llm::FileAnalyzer analyzer(router);
            analyzer.setLogicalPath(sources::referencePath(filePath));


            if (progressCallback) {
                std::lock_guard<std::mutex> lock(progressMutex);
                if (!stop.load() && !progressCallback(index + 1, total, forensics::sources::referencePath(filePath))) {
                    std::cout << "LLM " << modeLabel << " analysis stopped by callback after "
                              << index << "/" << total << " files" << std::endl;
                    stop.store(true);
                    return;
                }
            }
            if (stop.load()) {
                return;
            }

                // Resolve the file to a host-filesystem path (extract from image if needed).
                // Image extraction itself is serialised inside resolveFileForAnalysis.
                std::string localPath = resolveFileForAnalysis(filePath);
                if (localPath.empty()) {
                    if(!planId.empty())selection::finish(filesDbPath,planId,sourceKey,"failed","来源提取失败");
                    continue;  // source remains unknown
                }

                auto result = analyzer.analyzeFile(localPath, options.maxContentLength);
                if (result.success) {
                    if (storeDescription(filesDbPath, filePath,
                                         result.description, result.summary, result.keywords,
                                         result.modelUsed)) {
                        if(!planId.empty())selection::finish(filesDbPath,planId,sourceKey,"completed");
                        analyzed.fetch_add(1);
                    }
                } else if (result.errorMessage.size() > 0) {
                    if(!planId.empty())selection::finish(filesDbPath,planId,sourceKey,"failed",result.errorMessage);
                    if(result.errorMessage.find("MODEL_RUN_BUDGET_EXHAUSTED")!=std::string::npos)stop.store(true);
                    std::cerr << "Warning: LLM analysis failed for " << filePath
                              << ": " << result.errorMessage << std::endl;
                }
            } catch (const std::exception& e) {
                std::cerr << "Failed to analyze file " << filePath << ": " << e.what() << std::endl;
            }
        }
    };

    if (workers == 1) {
        worker();
    } else {
        std::cout << "LLM " << modeLabel << " analysis running with concurrency "
                  << workers << " (" << total << " files)" << std::endl;
        std::vector<std::thread> pool;
        pool.reserve(static_cast<size_t>(workers));
        for (int i = 0; i < workers; ++i) {
            pool.emplace_back(worker);
        }
        for (auto& thread : pool) {
            thread.join();
        }
    }
    return analyzed.load();
}

int LLMAnalysisService::analyzeSmartFiles(const std::string& filesDbPath,
                                           const AnalysisOptions& options,
                                           ProgressCallback progressCallback) {
    if (!initialized_) {
        if (!initialize()) {
            return 0;
        }
    }

    // All entry points consume the same bounded native selection plan.
    auto importantFiles = selectImportantFiles(filesDbPath, options.maxFiles);
    if (importantFiles.empty()) {
        std::cerr << "本轮没有通过内容与预算准入的候选文件" << std::endl;
        return 0;
    }

    return runFileAnalyses(filesDbPath, options, importantFiles, progressCallback, "smart-mode");
}

std::vector<std::string> LLMAnalysisService::selectImportantFiles(const std::string& filesDbPath,size_t maxFiles) {
    try {
        selectionDatabase_=filesDbPath;
        selectionPlan_=FileSelectionService::plan({{scratchTaskId_,filesDbPath,rawDbPath_,imagePath_}},FileSelectionService::budget(maxFiles));
        std::vector<std::string> selected;
        for(const auto& item:selectionPlan_.at("selected"))selected.push_back(item.at("reference").get<std::string>());
        std::cout<<"候选选择完成："<<selectionPlan_.at("counts").dump()<<std::endl;
        return selected;
    }catch(const std::exception& e){std::cerr<<"候选计划不可用："<<e.what()<<std::endl;throw;}
}

nlohmann::json LLMAnalysisService::selectionSummary() const {
    if(!selectionPlan_.is_object())return nlohmann::json::object();
    const auto id=selectionPlan_.value("plan_id",std::string());
    nlohmann::json result={{"plan_id",id},{"counts",selectionPlan_.value("counts",nlohmann::json::object())},{"completed",0},{"failed",0}};
    sqlite3* raw=nullptr;
    if(sqlite3_open_v2(selectionDatabase_.c_str(),&raw,SQLITE_OPEN_READONLY,nullptr)==SQLITE_OK){
        try{sources::Statement s(raw,"SELECT state,COUNT(*) FROM selection_execution WHERE plan_id=? GROUP BY state");s.bind(1,id);
            while(sqlite3_step(s.value)==SQLITE_ROW){const std::string state=reinterpret_cast<const char*>(sqlite3_column_text(s.value,0));result[state]=sqlite3_column_int64(s.value,1);}
        }catch(...){result["progress_unavailable"]=true;}
    }if(raw)sqlite3_close(raw);return result;
}

bool LLMAnalysisService::storeDescription(const std::string& dbPath,
                                           const std::string& filePath,
                                           const std::string& description,
                                           const std::string& summary,
                                           const std::vector<std::string>& keywords,
                                           const std::string& modelUsed) {
    // llm-throughput-hardening SPEC E: the Python three-write
    // (files display cache + file_analyses truth row + file_descriptions) is
    // the single writer. The legacy direct writes below remain only as the
    // fallback for when the Python service is unreachable — the pipeline must
    // never lose an analysis just because persistence moved.
    if (!scratchTaskId_.empty()) {
        std::string keywordsStr;
        for (size_t i = 0; i < keywords.size(); ++i) {
            if (i > 0) keywordsStr += ",";
            keywordsStr += keywords[i];
        }
        if (forensics::LLMPythonProxy::instance().recordFileAnalysisResult(
                scratchTaskId_, dbPath, filePath, description, summary,
                keywordsStr, modelUsed)) {
            return true;
        }
        std::cerr << "Python record endpoint unavailable for " << filePath
                  << " — falling back to direct file-db write" << std::endl;
    }

    sqlite3* db = nullptr;
    int rc = sqlite3_open(dbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to open database: " << dbPath << std::endl;
        return false;
    }

    // Convert keywords to comma-separated string
    std::stringstream ss;
    for (size_t i = 0; i < keywords.size(); ++i) {
        if (i > 0) ss << ",";
        ss << keywords[i];
    }
    std::string keywordsStr = ss.str();

    // Get current timestamp
    int64_t currentTime = static_cast<int64_t>(std::time(nullptr));

    const auto sourceId=forensics::sources::referenceId(filePath);
    const auto logicalPath=forensics::sources::referencePath(filePath);
    sqlite3_busy_timeout(db,10000);
    if(sqlite3_exec(db,"BEGIN IMMEDIATE",nullptr,nullptr,nullptr)!=SQLITE_OK){sqlite3_close(db);return false;}
    sqlite3_stmt* identity=nullptr;
    const std::string identitySql=sourceId.empty()?"SELECT rowid FROM files WHERE path=?":"SELECT rowid FROM files WHERE path=? AND source_id=?";
    if(sqlite3_prepare_v2(db,identitySql.c_str(),-1,&identity,nullptr)!=SQLITE_OK){sqlite3_close(db);return false;}
    sqlite3_bind_text(identity,1,logicalPath.c_str(),-1,SQLITE_TRANSIENT);
    if(!sourceId.empty())sqlite3_bind_text(identity,2,sourceId.c_str(),-1,SQLITE_TRANSIENT);
    const bool found=sqlite3_step(identity)==SQLITE_ROW;
    const auto fileRow=found?sqlite3_column_int64(identity,0):-1;
    const bool unique=found && sqlite3_step(identity)==SQLITE_DONE;
    sqlite3_finalize(identity);
    if(!unique){sqlite3_close(db);return false;}
    // Use UPDATE_FILE_LLM_ANALYSIS from file_classifier_sql.h
    // UPDATE files SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE path=?
    sqlite3_stmt* stmt = nullptr;
    rc = sqlite3_prepare_v2(db, "UPDATE files SET llm_summary=?,llm_description=?,llm_keywords=?,llm_analyzed_at=?,llm_model_used=? WHERE rowid=?", -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to prepare statement: " << sqlite3_errmsg(db) << std::endl;
        sqlite3_close(db);
        return false;
    }

    // Bind parameters: llm_summary, llm_description, llm_keywords, llm_analyzed_at, llm_model_used, path
    sqlite3_bind_text(stmt, 1, summary.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, keywordsStr.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 4, currentTime);
    sqlite3_bind_text(stmt, 5, modelUsed.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_int64(stmt, 6, fileRow);

    rc = sqlite3_step(stmt);
    int changes = sqlite3_changes(db);
    sqlite3_finalize(stmt);

    if (rc != SQLITE_DONE) {
        std::cerr << "Failed to update LLM analysis for file: " << filePath << std::endl;
        sqlite3_close(db);
        return false;
    }

    // Also write to the file_descriptions table with is_relevant=1 so that
    // AI-analyzed files from the main pipeline appear in the investigation
    // center's evidence list automatically. The Python side (persist_to_files_db)
    // does the same; the C++ side must stay in sync.
    sqlite3_exec(db,
        "CREATE TABLE IF NOT EXISTS file_descriptions ("
        "  file_path TEXT PRIMARY KEY,"
        "  description TEXT,"
        "  summary TEXT,"
        "  keywords TEXT,"
        "  model_used TEXT,"
        "  is_relevant INTEGER DEFAULT 0,"
        "  created_at INTEGER DEFAULT 0"
        ")",
        nullptr, nullptr, nullptr);

    sqlite3_stmt* descStmt = nullptr;
    const char* descSql =
        "INSERT INTO file_descriptions (file_path, description, summary, keywords, model_used, is_relevant, created_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?) "
        "ON CONFLICT(file_path) DO UPDATE SET "
        "  description = excluded.description, "
        "  summary = excluded.summary, "
        "  keywords = excluded.keywords, "
        "  model_used = excluded.model_used, "
        "  created_at = excluded.created_at";

    if (sqlite3_prepare_v2(db, descSql, -1, &descStmt, nullptr) == SQLITE_OK) {
        sqlite3_bind_text(descStmt, 1, filePath.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(descStmt, 2, description.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(descStmt, 3, summary.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(descStmt, 4, keywordsStr.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(descStmt, 5, modelUsed.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_int64(descStmt, 6, currentTime);
        sqlite3_step(descStmt);
        sqlite3_finalize(descStmt);
    }

    if(sqlite3_exec(db,"COMMIT",nullptr,nullptr,nullptr)!=SQLITE_OK){sqlite3_close(db);return false;}
    sqlite3_close(db);

    if (changes == 0) {
        std::cerr << "Warning: No rows updated for file: " << filePath << std::endl;
        return false;
    }

    return true;
}

std::vector<std::string> LLMAnalysisService::getFilesFromDatabase(const std::string& dbPath,
                                                                    const AnalysisOptions& options) {
    std::vector<std::string> files;

    sqlite3* db = nullptr;
    int rc = sqlite3_open(dbPath.c_str(), &db);
    if (rc != SQLITE_OK) {
        return files;
    }

    // Build query based on options
    std::string sql = forensics::sources::column(db,"source_id") ? "SELECT path,source_id FROM files" : "SELECT path FROM files";
    
    std::vector<std::string> conditions;
    if (!options.fileTypes.empty()) {
        std::stringstream ss;
        ss << "category IN (";
        for (size_t i = 0; i < options.fileTypes.size(); ++i) {
            if (i > 0) ss << ",";
            ss << "'" << options.fileTypes[i] << "'";
        }
        ss << ")";
        conditions.push_back(ss.str());
    }

    if (options.skipBinaryFiles) {
        conditions.push_back("category NOT IN ('Executables', 'Unknown Files')");
    }

    if (!conditions.empty()) {
        sql += " WHERE ";
        for (size_t i = 0; i < conditions.size(); ++i) {
            if (i > 0) sql += " AND ";
            sql += conditions[i];
        }
    }

    // maxFiles == 0 表示全量（不追加 LIMIT 子句）
    if (options.maxFiles > 0) {
        sql += " LIMIT " + std::to_string(options.maxFiles);
    }

    sqlite3_stmt* stmt = nullptr;
    rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        sqlite3_close(db);
        return files;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        if (path) {
            const auto id=sqlite3_column_count(stmt)>1?sqlite3_column_text(stmt,1):nullptr;
            files.push_back(forensics::sources::reference(id?reinterpret_cast<const char*>(id):"",path));
        }
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);

    return files;
}

std::vector<std::string> LLMAnalysisService::getPrioritizedCandidates(
        const std::string& dbPath, size_t budget, bool skipBinaryFiles) {
    // Smart selection needs the *best* candidates in the whole database, not
    // the first N rows. On the PC.E01 Windows image the previous LIMIT 5000
    // over insertion order covered 1.6% of 305,716 files and missed every
    // registry hive, all 370 .evtx logs and Amcache: the interesting artefacts
    // were unreachable by construction. Scan every row, score it, and keep a
    // bounded top-budget set.
    std::vector<std::string> files;
    if (budget == 0) {
        return files;
    }

    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        return files;
    }

    // "Unknown Files" is not a reliable binary signal: it is exactly where TSK
    // puts .evtx logs, registry hives (.hve) and other opaque-but-critical
    // artefacts. Only true executables are excluded here; anything else is
    // scored, and forensicPathPriority demotes genuine noise.
    std::string sql = forensics::sources::column(db,"source_id") ? "SELECT path,source_id FROM files" : "SELECT path FROM files";
    if (skipBinaryFiles) {
        sql += " WHERE category != 'Executables'";
    }

    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        sqlite3_close(db);
        return files;
    }

    // Min-heap on (priority, slot): the root is the weakest kept entry, so a
    // stronger candidate evicts it. The slot index (not a sequence number)
    // lets an eviction replace exactly the entry the heap points at.
    using Entry = std::pair<int, size_t>;
    std::priority_queue<Entry, std::vector<Entry>, std::greater<Entry>> heap;
    std::vector<std::string> kept;
    kept.reserve(budget);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        if (!path || !*path) continue;
        const auto id=sqlite3_column_count(stmt)>1?sqlite3_column_text(stmt,1):nullptr;
        std::string value=forensics::sources::reference(id?reinterpret_cast<const char*>(id):"",path);

        // TSK virtual entries ($MFT-style pseudo files) are filesystem
        // metadata, not analysable evidence; dropping them before scoring also
        // stops them from consuming the budget.
        std::filesystem::path p(value);
        std::string name = p.filename().string();
        // TSK virtual entries ($AttrDef, $BadClus, $Bitmap, $Boot) are
        // filesystem bookkeeping and carry no case evidence. Two names in the
        // same "$" namespace do: $MFT is the full filesystem metadata table and
        // $UsnJrnl is the change journal that records every create/write/delete.
        // Skipping the whole prefix made the two most valuable filesystem-level
        // artifacts permanently unreachable on every NTFS image.
        if (!name.empty() && name[0] == '$' && !isForensicDollarEntry(name)) continue;

        int priority = forensicPathPriority(value);
        if (priority < kMinSelectablePriority) continue;

        if (kept.size() < budget) {
            heap.emplace(priority, kept.size());
            kept.push_back(std::move(value));
            continue;
        }
        if (priority <= heap.top().first) continue;
        size_t slot = heap.top().second;
        heap.pop();
        kept[slot] = std::move(value);
        heap.emplace(priority, slot);
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);

    // The heap orders by priority only; restore the deterministic priority
    // ordering the rest of the pipeline expects.
    return selectByHeuristic(std::move(kept), budget);
}

int LLMAnalysisService::forensicPathPriority(const std::string& reference) {
    const std::string path=forensics::sources::referencePath(reference);
    // Key-material filenames are data whatever directory they sit in: an
    // authorized_keys copy inside a vendored tree is still evidence.
    static const std::vector<std::string> keyFilePatterns = {
        "authorized_keys", "known_hosts", "id_rsa", "id_ed25519"};
    static const std::vector<std::string> credPatterns = {
        "shadow", "passwd",
        ".bash_history", ".zsh_history", "sh_history", "history.db", "sudoers",
        // compound names the word-boundary check below cannot reach via the
        // bare words ("gshadow" has g before shadow, "opasswd" an o before passwd)
        "gshadow", "opasswd"};
    static const std::vector<std::string> highExt = {
        ".log", ".db", ".sqlite", ".sqlite3", ".md", ".txt", ".json", ".xml",
        ".csv", ".conf", ".cfg", ".ini", ".yaml", ".yml", ".sh", ".py", ".pdf",
        ".docx", ".xlsx", ".pptx", ".eml", ".htm", ".html"};

    std::string lower;
    lower.reserve(path.size());
    for (char c : path) lower += static_cast<char>(::tolower(static_cast<unsigned char>(c)));

    // Core forensic artefacts outrank everything else. They are routinely
    // classified as "Unknown Files"/"Executables" (evtx, hve, registry hives),
    // so the skip-binary category filter drops them and no later rule ever
    // sees them: on PC.E01 all 370 .evtx logs and Amcache were unreachable.
    // These paths are the reason to run the analysis, whatever their category.
    // Markers are path-shaped on purpose: a bare "/system" would match every
    // /Windows/System32 file and collapse the ranking.
    static const std::vector<std::string> coreArtefactMarkers = {
        // Windows event logs and registry hives
        "/winevt/logs/", ".evtx",
        "/system32/config/", "/appcompat/programs/", "amcache.hve", "syscache.hve",
        "ntuser.dat", "usrclass.dat",
        // execution / persistence / user-activity artefacts
        "/windows/prefetch/", "sruedb", "/srum/", "/recentdocs/",
        "automaticdestinations", "customdestinations",
        // Linux credentials stay top-tier; logs keep their existing 80 band
        // (see the /var/log rule below) so established rankings do not shift.
        "/etc/shadow", "/etc/passwd",
        ".bash_history", ".zsh_history",
    };
    // Registry transaction logs and companions are storage internals, not the
    // hive itself: a plain "ntuser.dat" substring also hits NTUSER.DAT.LOG,
    // .blf and .regtrans-ms (the 窝点嫌疑人 image listed 10 of them ahead of real
    // evidence). The existing .log1/.log2 rule demotes those to noise, so the
    // core marker must not claim them first.
    const bool registryCompanion =
        lower.find(".log1") != std::string::npos ||
        lower.find(".log2") != std::string::npos ||
        lower.find(".blf") != std::string::npos ||
        lower.find(".regtrans-ms") != std::string::npos ||
        (lower.size() > 4 && lower.compare(lower.size() - 4, 4, ".log") == 0);
    for (const auto& p : coreArtefactMarkers) {
        if (lower.find(p) != std::string::npos) {
            if (registryCompanion) continue;
            // /Windows/System32/config/systemprofile/... is a per-service
            // profile tree (95 files on PC.E01), not the hive directory.
            if (p == "/system32/config/" &&
                lower.find("/system32/config/systemprofile/") != std::string::npos) {
                continue;
            }
            return 100;
        }
    }

    // Non-document binaries and UI resource packs: no text for the LLM, and a
    // credential word inside them is an identifier (WPS Shadow_Settings.kuip,
    // chrome_child.dll). Windows-image replay showed these flooding the whole
    // budget — .dll/.pak under AppData inherit the 90 user-area score, .kuip
    // even hits the shadow credential pattern.
    static const std::vector<std::string> binaryResourceSuffixes = {
        ".dll", ".sys", ".ocx", ".efi", ".msi", ".cab", ".pak", ".kuip",
        ".exe", ".mui", ".ico", ".pb"};
    for (const auto& s : binaryResourceSuffixes) {
        if (lower.size() >= s.size() &&
            lower.compare(lower.size() - s.size(), s.size(), s) == 0) {
            return 5;
        }
    }
    // Program-install trees under user profiles are the same noise class
    // (chrome.exe payloads, WPS office6), as are GPU font caches.
    static const std::vector<std::string> programTreeMarkers = {
        "chrome/application", "appdata/local/programs", "fontcache",
        "kingsoft", "iconcache.db"};
    for (const auto& p : programTreeMarkers) {
        if (lower.find(p) != std::string::npos) return 5;
    }
    // Chromium runtime state: leveldb stores are binary, the component
    // directories hold update manifests — neither is analysable text, and on
    // Windows images they inherit the 90 user-area score wholesale.
    if (lower.find("leveldb") != std::string::npos) return 5;
    // Leveldb-internal filenames carry no path hint of their store, hence the
    // name shapes: a pure-numeric .log segment and LOG.old. Both are binary
    // storage internals wherever they sit.
    if (lower.size() > 4 && lower.find_last_of('.') != std::string::npos) {
        const std::size_t dot = lower.find_last_of('.');
        const std::string stem = lower.substr(lower.find_last_of('/') + 1, dot - lower.find_last_of('/') - 1);
        const std::string ext = lower.substr(dot);
        if (ext == ".log" && !stem.empty() &&
            stem.find_first_not_of("0123456789") == std::string::npos) {
            return 5;
        }
        if (ext == ".old" && stem == "log") return 5;
        // Registry hive transaction logs (SOFTWARE.LOG1, SAM.LOG2). They carry
        // no readable text and the text pipeline only reports them as empty.
        if (ext == ".log1" || ext == ".log2") return 5;
    }
    static const std::vector<std::string> chromeComponentDirs = {
        "certificaterevocation", "certificatetransparency", "crashpad",
        "filetypepolicies", "meipreload", "origintrials", "pnacl",
        "sslerrorassistant", "subresource filter", "swreporter",
        "software reporter tool", "widevinecdm", "system profile"};
    for (const auto& p : chromeComponentDirs) {
        if (lower.find(p) != std::string::npos) return 5;
    }
    // Distro-owned content trees never hold a credential data file, yet their
    // basenames are full of the words above (locale catalogs passwd.mo in 30+
    // languages, yumdb package dirs, firewalld kpasswd.xml, sample.sudoers).
    // Checked before the credential rule: junk wins over credentials here.
    static const std::vector<std::string> distroJunkTrees = {
        "/usr/share/", "/usr/lib", "/usr/include", "/var/lib/yum", "/var/lib/dnf",
        "/var/lib/docker", "/var/lib/snapd", "/snap/", "/lost+found",
        // Compiled SELinux policy modules are binary policy blobs (1,756 under
        // /etc/selinux/targeted/active/modules on the 服务器镜像). They sit in
        // /etc and so inherited the 60-point config score, spending over a
        // third of the Linux budget on distro policy rather than evidence.
        "/etc/selinux/",
        // Upstream test suites shipped by packages (mysql-test holds thousands
        // of fixture .test/.result files under /www/server/mysql on the same
        // image); they are vendor fixtures, never case data.
        "/mysql-test/",
        // Kernel headers and module build trees (15,138 files under
        // /usr/src/kernels on the 服务器镜像) are distro source, not evidence.
        "/usr/src/kernels/", "/usr/src/debug/", "/lib/modules/",
    };
    const std::size_t lastSlashEarly = lower.find_last_of('/');
    const std::string baseEarly =
        (lastSlashEarly == std::string::npos) ? lower : lower.substr(lastSlashEarly + 1);
    for (const auto& p : keyFilePatterns) {
        if (baseEarly.find(p) != std::string::npos) return 100;
    }
    for (const auto& p : distroJunkTrees) {
        if (lower.find(p) != std::string::npos) return 5;
    }
    // Dependency trees same as above: a credential word inside site-packages or
    // vendor/ is a code identifier or test fixture (keycert.passwd.pem,
    // Cython/Shadow.py), never a credential data file. User caches (.cache/)
    // stay credential-first — exported credentials do land in caches.
    static const std::vector<std::string> dependencyTreeMarkers = {
        "__pycache__", "site-packages", "node_modules", "vendor/",
        "bower_components", ".git/objects", ".git/modules",
    };
    for (const auto& p : dependencyTreeMarkers) {
        if (lower.find(p) != std::string::npos) return 5;
    }
    // Credentials / histories / access artefacts: top priority. Matched on the
    // basename only, and the hit must be word-bounded: directory-name and
    // compound-binary hits (yumdb .../passwd-0.79.../checksum_type, gpasswd,
    // saslpasswd2) are bookkeeping or executables, not credential data.
    const std::size_t lastSlash = lower.find_last_of('/');
    const std::string basename =
        (lastSlash == std::string::npos) ? lower : lower.substr(lastSlash + 1);
    auto wordBoundedAt = [&lower](std::size_t pos, std::size_t len) {
        const bool before = (pos == 0) ||
            !::isalnum(static_cast<unsigned char>(lower[pos - 1]));
        const std::size_t end = pos + len;
        const bool after = (end >= lower.size()) ||
            !::isalnum(static_cast<unsigned char>(lower[end]));
        return before && after;
    };
    const std::size_t baseStart =
        (lastSlash == std::string::npos) ? 0 : lastSlash + 1;
    // Images are vision-pipeline evidence, never credential data files: a
    // credential word in "tile_drop_shadow.png" is a graphic-asset name.
    static const std::vector<std::string> imageSuffixes = {
        ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"};
    const bool isImageFile = std::any_of(
        imageSuffixes.begin(), imageSuffixes.end(), [&](const std::string& s) {
            return lower.size() >= s.size() &&
                   lower.compare(lower.size() - s.size(), s.size(), s) == 0;
        });
    for (const auto& p : credPatterns) {
        if (isImageFile) break;
        std::size_t at = basename.find(p);
        while (at != std::string::npos) {
            if (wordBoundedAt(baseStart + at, p.size())) return 100;
            at = basename.find(p, at + 1);
        }
    }
    // Bulk-junk markers: package-manager caches, vendored dependency trees,
    // VCS internals, Windows system droppings, container/distro bulk. These
    // are noise even under /root or /home and are scored before the user-area
    // rule below, otherwise they inherit 90 and eat the smart-selection
    // budget. Marker notes: "vendor/" carries its separator so an ordinary
    // document named vendor-audit-notes.txt stays user data; ".gradle" has no
    // separator because the dir is dot-prefixed already.
    static const std::vector<std::string> junkMarkers = {
        // caches & package-manager stores (dependency trees are checked
        // earlier, before the credential rule)
        ".cache/", "/var/cache/",
        ".npm/", "_cacache", ".yarn/", ".pnpm-store", ".cargo/registry",
        ".m2/repository", ".gradle", "go/pkg/mod",
        // windows system junk
        "desktop.ini", "thumbs.db", "thumbcache", "pagefile.sys", "hiberfil.sys",
        "swapfile.sys", "$recycle.bin", "inetcache", "softwaredistribution",
        "winsxs", "appdata/local/temp", "appdata\\local\\temp",
        // container / distro bulk trees
        "/var/lib/docker", "/var/lib/snapd", "/snap/", "/lost+found",
        "/var/lib/yum", "/var/lib/dnf",
    };
    for (const auto& p : junkMarkers) {
        if (lower.find(p) != std::string::npos) return 5;
    }
    // Temp / backup / editor droppings: suffix- and prefix-shaped junk.
    static const std::vector<std::string> junkSuffixes = {".tmp", ".swp", ".swo"};
    for (const auto& s : junkSuffixes) {
        if (lower.size() >= s.size() &&
            lower.compare(lower.size() - s.size(), s.size(), s) == 0) {
            return 5;
        }
    }
    if (!lower.empty() && lower.back() == '~') return 5;        // emacs/gedit backups
    if (lower.find(".~lock") != std::string::npos) return 5;    // office lock files
    if (lower.find(".ds_store") != std::string::npos) return 5; // macOS finder droppings
    // User data areas beat system areas. The Desktop/Documents/Downloads terms
    // must be real path segments: as bare substrings they also matched
    // "Microsoft.DesktopAppInstaller…xml" and ".../DesktopSpotlight/..." under
    // ProgramData, which put 13,632 system-package files in the user tier on
    // PC.E01 and pushed actual desktop evidence out of the budget.
    const bool inUserTree =
        lower.find("/home/") != std::string::npos || lower.rfind("/home/", 0) == 0 ||
        lower.find("/users/") != std::string::npos ||
        lower.find("/root/") != std::string::npos;
    const bool inUserFolder =
        lower.find("/desktop/") != std::string::npos ||
        lower.find("/documents/") != std::string::npos ||
        lower.find("/downloads/") != std::string::npos;
    if (inUserTree || inUserFolder) {
        // A directory full of same-shaped images is the cheapest way to burn the
        // analysis budget: on PC.E01, 248 of 368 selected files were JPGs from
        // one Documents/VM_Config folder, and 83% of them described themselves
        // as uniformly grey or unreadable. Images stay selectable (a screenshot
        // can be the evidence) but rank below documents in the same tree.
        static const std::vector<std::string> imageSuffixesForRank = {
            ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tif", ".tiff", ".webp"};
        for (const auto& suffix : imageSuffixesForRank) {
            if (lower.size() >= suffix.size() &&
                lower.compare(lower.size() - suffix.size(), suffix.size(), suffix) == 0) {
                return 60;
            }
        }
        return 90;
    }
    // System logs and journals. The journal term must be a real journal
    // artefact: as a bare substring it also matched package-database stubs
    // (yumdb .../x86_64/journalc) and promoted 68 of them to the log band,
    // bypassing the /var/lib/yum demotion.
    if (lower.find("/var/log/") != std::string::npos ||
        lower.find("/var/log/journal/") != std::string::npos ||
        lower.find("/journal/") != std::string::npos ||
        lower.find("imjournal") != std::string::npos) {
        return 80;
    }
    // Browser / mail / chat profiles
    if (lower.find(".mozilla") != std::string::npos || lower.find("chrome") != std::string::npos ||
        lower.find("wechat") != std::string::npos || lower.find("telegram") != std::string::npos ||
        lower.find("mail") != std::string::npos) {
        return 75;
    }
    // Databases anywhere
    if (lower.size() > 3 &&
        (lower.substr(lower.size() - 3) == ".db" ||
         lower.find(".sqlite") != std::string::npos)) {
        return 70;
    }
    // System configuration
    if (lower.find("/etc/") != std::string::npos || lower.rfind("/etc/", 0) == 0) {
        return 60;
    }
    // Boot / scheduler
    if (lower.find("/boot/") != std::string::npos || lower.find("cron") != std::string::npos) {
        return 50;
    }
    // Low-value bulk content
    if (lower.find("fonts") != std::string::npos ||
        lower.find("ssl/certs") != std::string::npos ||
        lower.find("locale") != std::string::npos ||
        lower.find("icons") != std::string::npos ||
        lower.find("node_modules") != std::string::npos) {
        return 5;
    }
    // Analysable extensions get a mid score, everything else low
    for (const auto& e : highExt) {
        if (lower.size() >= e.size() &&
            lower.compare(lower.size() - e.size(), e.size(), e) == 0) {
            return 30;
        }
    }
    return 10;
}

bool LLMAnalysisService::hasBinaryContainerHeader(const std::string& path) {
    // A renamed binary keeps whatever score its directory earns. Only files the
    // path rules already consider worth analysing are checked, and only the
    // first bytes: MZ is a PE image (exe/dll saved as .old), PK is a zip-family
    // container. Anything unreadable is left to the path score — a missing file
    // is not evidence of anything.
    std::ifstream in(path, std::ios::binary);
    if (!in) {
        return false;
    }
    unsigned char magic[4] = {0, 0, 0, 0};
    in.read(reinterpret_cast<char*>(magic), sizeof(magic));
    if (in.gcount() < 2) {
        return false;
    }
    if (magic[0] == 'M' && magic[1] == 'Z') {
        return true;
    }
    return in.gcount() >= 4 && magic[0] == 'P' && magic[1] == 'K' &&
           magic[2] == 0x03 && magic[3] == 0x04;
}

std::vector<std::string> LLMAnalysisService::selectByHeuristic(std::vector<std::string> files,
                                                               size_t maxFiles) {
    // Score once, up front. The comparator of a sort may re-read a path many
    // times, and the header check opens the file each call.
    std::vector<int> scores;
    scores.reserve(files.size());
    for (const auto& path : files) {
        int priority = forensicPathPriority(path);
        if (priority > 5 && hasBinaryContainerHeader(path)) {
            priority = 5;
        }
        scores.push_back(priority);
    }

    std::vector<size_t> order(files.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&](size_t a, size_t b) {
        return scores[a] > scores[b];
    });

    // Priority 5 is the noise bucket (temp dirs, registry transaction logs, and
    // binaries the header check pulled down). A budget larger than the evidence
    // must stay unfilled rather than be padded with it. The floor sits below
    // every evidence band, so a sparse image still keeps its real files. The
    // filter uses the scores above: recomputing the path priority here would
    // undo the header demotion.
    std::vector<std::string> ranked;
    for (size_t index : order) {
        if (static_cast<int>(ranked.size()) >= static_cast<int>(maxFiles)) {
            break;
        }
        if (scores[index] < kMinSelectablePriority) {
            break;
        }
        ranked.push_back(std::move(files[index]));
    }
    return ranked;
}

std::string LLMAnalysisService::buildFileListSummary(const std::vector<std::string>& files) {
    // One indexed full path per line. The previous directory-grouped layout
    // listed bare file names under a heading, so a model asked for "paths"
    // could not reproduce any entry that parseImportantFiles could match
    // (observed on a Windows image: 1 of 1000 paths matched). Indices make the
    // reply unambiguous and let one index select exactly one database row.
    std::stringstream ss;
    for (size_t i = 0; i < files.size(); ++i) {
        ss << (i + 1) << ' ' << forensics::sources::referencePath(files[i]) << '\n';
    }
    return ss.str();
}

std::vector<std::string> LLMAnalysisService::parseImportantFiles(const std::string& llmResponse,
                                                                   const std::vector<std::string>& allFiles) {
    std::vector<std::string> importantFiles;

    // The prompt now hands the model an indexed list, so the canonical reply is
    // a JSON array of integers. Three reply shapes are accepted, in order of
    // reliability: (1) indices into allFiles, (2) full paths, (3) bare file
    // names matched against the basename of each candidate. Every match is
    // resolved to an exact element of allFiles so the caller can never receive
    // a path that does not exist in the database.
    std::unordered_set<std::string> known(allFiles.begin(), allFiles.end());

    // Only unique logical paths/basenames can identify an indexed source.
    std::unordered_map<std::string, std::string> byBasename;
    std::unordered_map<std::string, std::string> byPath;
    auto resolveName = [&](const std::string& raw) -> std::string {
        if (byBasename.empty()) {
            for (const auto& f : allFiles) {
                const auto logical=forensics::sources::referencePath(f);
                std::filesystem::path p(logical);
                auto add=[&](auto& map,const std::string& key){auto result=map.emplace(key,f);if(!result.second)result.first->second.clear();};
                add(byBasename,p.filename().string());add(byPath,logical);
            }
        }
        auto exact=byPath.find(raw);
        if(exact!=byPath.end())return exact->second;
        auto it = byBasename.find(raw);
        return it == byBasename.end() ? std::string() : it->second;
    };

    try {
        size_t start = llmResponse.find('[');
        size_t end = llmResponse.rfind(']');
        if (start != std::string::npos && end != std::string::npos && end > start) {
            std::string jsonStr = llmResponse.substr(start, end - start + 1);

            // Single pass so the model's ranking order is preserved: whichever
            // shape it answers in, the first entries it names are the ones the
            // budget keeps when the reply exceeds maxFiles.
            size_t pos = 0;
            while (pos < jsonStr.size()) {
                size_t quote = jsonStr.find('"', pos);
                size_t tokenEnd = jsonStr.find_first_of(",[]", pos);
                // A quoted entry starts before the next separator: read it.
                if (quote != std::string::npos &&
                    (tokenEnd == std::string::npos || quote < tokenEnd)) {
                    size_t endQuote = jsonStr.find('"', quote + 1);
                    if (endQuote == std::string::npos) break;

                    std::string entry = jsonStr.substr(quote + 1, endQuote - quote - 1);
                    pos = endQuote + 1;

                    // Reject junk entries the model sometimes emits ("", "/").
                    // An empty needle would partial-match EVERY file below.
                    if (entry.size() < 2 || entry == "/") continue;

                    if (known.count(entry)) {
                        importantFiles.push_back(entry);
                        continue;
                    }
                    std::string byName = resolveName(entry);
                    if (!byName.empty()) {
                        importantFiles.push_back(std::move(byName));
                        continue;
                    }
                    // Ambiguous names and partial path fragments are not identities.
                    continue;
                }
                if (tokenEnd == std::string::npos) break;

                // Unquoted token: an index, or structural punctuation.
                std::string token = jsonStr.substr(pos, tokenEnd - pos);
                pos = tokenEnd + 1;
                size_t b = token.find_first_not_of(" \t\r\n");
                size_t e = token.find_last_not_of(" \t\r\n");
                if (b == std::string::npos || e == std::string::npos) continue;
                token = token.substr(b, e - b + 1);
                char* endPtr = nullptr;
                long value = std::strtol(token.c_str(), &endPtr, 10);
                if (endPtr && *endPtr == '\0' && value >= 1 &&
                    static_cast<size_t>(value) <= allFiles.size()) {
                    importantFiles.push_back(allFiles[value - 1]);
                }
            }
        }
    } catch (...) {
        // Fallback: return empty, caller should handle
    }

    // Dedupe while keeping first occurrence
    std::unordered_set<std::string> seen;
    std::vector<std::string> unique;
    unique.reserve(importantFiles.size());
    for (auto& f : importantFiles) {
        if (seen.insert(f).second) {
            unique.push_back(std::move(f));
        }
    }
    importantFiles = std::move(unique);

    return importantFiles;
}

void LLMAnalysisService::setSceneType(SceneType scene) {
    sceneType_ = scene;
}

SceneType LLMAnalysisService::getSceneType() const {
    return sceneType_;
}

std::vector<FileRecord> LLMAnalysisService::getScenePrioritizedFiles(sqlite3* db, int limit) {
    std::vector<FileRecord> files;

    std::string query;
    if (sceneType_ != SceneType::NONE) {
        query = "SELECT id, inode, name, path, size, extension, category, type, "
                "mtime, ctime, is_deleted, md5, scene_type, scene_priority, scene_relevant "
                "FROM files WHERE type = 'REG' "
                "AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) "
                "AND scene_priority > 0 "
                "ORDER BY scene_priority DESC, size ASC LIMIT ?";
    } else {
        query = "SELECT id, inode, name, path, size, extension, category, type, "
                "mtime, ctime, is_deleted, md5, NULL, 0, 0 "
                "FROM files WHERE type = 'REG' "
                "AND (llm_analyzed_at IS NULL OR llm_analyzed_at = 0) "
                "ORDER BY size ASC LIMIT ?";
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db, query.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return files;
    }

    sqlite3_bind_int(stmt, 1, limit);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileRecord file;
        file.id = sqlite3_column_int(stmt, 0);
        file.inode = sqlite3_column_int64(stmt, 1);

        const char* name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        file.name = name ? name : "";

        const char* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        file.path = path ? path : "";

        file.size = sqlite3_column_int64(stmt, 4);

        const char* ext = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
        file.extension = ext ? ext : "";

        const char* cat = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
        file.category = cat ? cat : "";

        const char* type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
        file.type = type ? type : "";

        file.mtime = sqlite3_column_int64(stmt, 8);
        file.ctime = sqlite3_column_int64(stmt, 9);
        file.isDeleted = sqlite3_column_int(stmt, 10);

        const char* md5 = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11));
        file.md5 = md5 ? md5 : "";

        const char* sceneType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 12));
        file.sceneType = sceneType ? sceneType : "";

        file.scenePriority = sqlite3_column_int(stmt, 13);
        file.sceneRelevant = sqlite3_column_int(stmt, 14);

        files.push_back(file);
    }

    sqlite3_finalize(stmt);
    return files;
}

bool LLMAnalysisService::shouldSkipFile(const FileRecord& file) {
    if (sceneType_ == SceneType::NONE) return false;
    return file.scenePriority == 0;
}

std::string LLMAnalysisService::getSceneSpecificPrompt(const FileRecord& file) {
    std::string basePrompt = "Analyze this forensic file and provide:\n"
        "1. A brief summary of the file's purpose\n"
        "2. A detailed description of its contents\n"
        "3. Relevant keywords for searching\n\n"
        "File path: " + file.path + "\n"
        "File name: " + file.name + "\n";

    if (sceneType_ == SceneType::ANDROID) {
        basePrompt += "\nAndroid forensic analysis. Focus on mobile app data, communications, and device configuration.\n";
    } else if (sceneType_ == SceneType::WINDOWS) {
        basePrompt += "\nWindows forensic analysis. Focus on registry artifacts, event logs, and user activity.\n";
    } else if (sceneType_ == SceneType::LINUX) {
        basePrompt += "\nLinux forensic analysis. Focus on system logs, user accounts, and network configuration.\n";
    } else if (sceneType_ == SceneType::SERVER_CLOUD) {
        basePrompt += "\nServer/Cloud forensic analysis. Focus on system logs, network configuration, and service artifacts.\n";
    }

    return basePrompt;
}

} // namespace forensics
