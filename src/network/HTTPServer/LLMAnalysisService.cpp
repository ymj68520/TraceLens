#include "LLMAnalysisService.h"
#include "LLMScratch.h"
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "core/PathManager/PathManager.h"
#include <sqlite3.h>
#include <iostream>
#include <filesystem>
#include <sstream>
#include <algorithm>
#include <ctime>
#include <cstring>

namespace fs = std::filesystem;

namespace forensics {

LLMAnalysisService::LLMAnalysisService() = default;

LLMAnalysisService::~LLMAnalysisService() {
    // D4b RAII: the task-scoped extraction scratch dies with the analysis
    // run, on every exit path (success, failure, cancellation, exception).
    if (!taskId_.empty()) {
        llm_scratch::cleanupTask(taskId_);
    }
}

void LLMAnalysisService::setTaskId(const std::string& taskId) {
    taskId_ = taskId;
}

std::string LLMAnalysisService::TaskScratchDir(const std::string& taskId) {
    return llm_scratch::dirForTask(taskId);
}

void LLMAnalysisService::CleanupTaskScratch(const std::string& taskId) {
    llm_scratch::cleanupTask(taskId);
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

void LLMAnalysisService::setImagePaths(const std::string& imagePath, const std::string& rawDbPath) {
    imagePath_ = imagePath;
    rawDbPath_ = rawDbPath;
}

std::string LLMAnalysisService::resolveFileForAnalysis(const std::string& filePath) {
    // No image configured: file paths are host-filesystem paths (e.g. loose files)
    if (imagePath_.empty() || rawDbPath_.empty()) {
        return filePath;
    }

    // Fast path: if the file already exists on the host filesystem, use it directly.
    if (fs::exists(filePath)) {
        return filePath;
    }

    // Extract the file from the forensic image to a temporary directory.
    try {
        FileExtractor extractor(imagePath_, rawDbPath_);
        if (!extractor.initialize()) {
            std::cerr << "Warning: Failed to initialize FileExtractor for image: " << imagePath_ << std::endl;
            return "";
        }

        // Build a safe output path under the task's extracted_files directory.
        // The filePath is relative to the image root (e.g. "grub/grub.cfg").
        // Normalize it into a flat filename to avoid directory traversal issues.
        std::string safeName = filePath;
        std::replace(safeName.begin(), safeName.end(), '/', '_');
        std::replace(safeName.begin(), safeName.end(), '\\', '_');

        // Use a task-scoped temp dir (D4b): per-task subtree avoids the old
        // flat-namespace collisions across tasks and is cleaned by the
        // service destructor / task deletion.
        fs::path extractDir(llm_scratch::dirForTask(taskId_));
        fs::create_directories(extractDir);
        fs::path outputPath = extractDir / safeName;

        if (extractor.extractFileByPath(filePath, outputPath)) {
            return outputPath.string();
        }

        // Some images store paths with a leading slash; retry without it.
        if (!filePath.empty() && filePath[0] == '/') {
            if (extractor.extractFileByPath(filePath.substr(1), outputPath)) {
                return outputPath.string();
            }
        }
        // Or with a leading slash added.
        if (filePath.empty() || filePath[0] != '/') {
            if (extractor.extractFileByPath("/" + filePath, outputPath)) {
                return outputPath.string();
            }
        }

        std::cerr << "Warning: Could not extract file from image: " << filePath << std::endl;
        return "";
    } catch (const std::exception& e) {
        std::cerr << "Warning: Exception extracting file " << filePath << ": " << e.what() << std::endl;
        return "";
    }
}

int LLMAnalysisService::analyzeAllFiles(const std::string& task_id,
                                         const std::string& filesDbPath,
                                         const AnalysisOptions& options,
                                         ProgressCallback progressCallback) {
    if (!initialized_) {
        if (!initialize()) {
            return 0;
        }
    }

    // Get files to analyze from the database
    auto files = getFilesFromDatabase(filesDbPath, options);
    if (files.empty()) {
        return 0;
    }

    // Limit number of files
    if (files.size() > options.maxFiles) {
        files.resize(options.maxFiles);
    }

    int analyzed = 0;
    int total = files.size();

    for (size_t i = 0; i < files.size(); ++i) {
        const auto& filePath = files[i];

        if (progressCallback) {
            progressCallback(i + 1, total, filePath);
        }

        try {
            // Resolve the file to a host-filesystem path (extract from image if needed)
            std::string localPath = resolveFileForAnalysis(filePath);
            if (localPath.empty()) {
                continue;  // extraction failed, warning already logged
            }

            auto result = fileAnalyzer_->analyzeFile(localPath, options.maxContentLength, task_id);

            if (result.success) {
                // Store directly to _files.db in the files table
                storeDescription(filesDbPath, filePath,
                                result.description, result.summary, result.keywords,
                                result.modelUsed);
                analyzed++;
            }
        } catch (const std::exception& e) {
            std::cerr << "Failed to analyze file " << filePath << ": " << e.what() << std::endl;
        }
    }

    return analyzed;
}

int LLMAnalysisService::analyzeSmartFiles(const std::string& task_id,
                                           const std::string& filesDbPath,
                                           const AnalysisOptions& options,
                                           ProgressCallback progressCallback) {
    if (!initialized_) {
        if (!initialize()) {
            return 0;
        }
    }

    // First, select important files using LLM
    auto importantFiles = selectImportantFiles(filesDbPath, options.maxFiles);
    if (importantFiles.empty()) {
        std::cerr << "No important files selected by LLM" << std::endl;
        return 0;
    }

    int analyzed = 0;
    int total = importantFiles.size();

    for (size_t i = 0; i < importantFiles.size(); ++i) {
        const auto& filePath = importantFiles[i];

        if (progressCallback) {
            progressCallback(i + 1, total, filePath);
        }

        try {
            // Resolve the file to a host-filesystem path (extract from image if needed)
            std::string localPath = resolveFileForAnalysis(filePath);
            if (localPath.empty()) {
                continue;  // extraction failed, warning already logged
            }

            auto result = fileAnalyzer_->analyzeFile(localPath, options.maxContentLength, task_id);

            if (result.success) {
                // Store directly to _files.db in the files table
                storeDescription(filesDbPath, filePath,
                                result.description, result.summary, result.keywords,
                                result.modelUsed);
                analyzed++;
            }
        } catch (const std::exception& e) {
            std::cerr << "Failed to analyze file " << filePath << ": " << e.what() << std::endl;
        }
    }

    return analyzed;
}

std::vector<std::string> LLMAnalysisService::selectImportantFiles(const std::string& filesDbPath,
                                                                    size_t maxFiles) {
    if (!initialized_) {
        if (!initialize()) {
            return {};
        }
    }

    // Get all files from database
    AnalysisOptions opts;
    opts.maxFiles = 10000;  // Get more files for smart selection
    auto allFiles = getFilesFromDatabase(filesDbPath, opts);
    if (allFiles.empty()) {
        return {};
    }

    // Build summary of file list for LLM
    std::string fileListSummary = buildFileListSummary(allFiles);

    // Ask LLM to select important files
    std::string prompt = R"(You are a digital forensics expert. Analyze the following list of files from a forensic disk image and identify the most important files for investigation.

Consider:
- System configuration files
- User documents (especially recently modified)
- Database files that may contain evidence
- Log files with timestamps
- Scripts or executables that could be malicious
- Files with suspicious names or locations
- Communication-related files (emails, messages, contacts)
- Browser history and cache

File list:
)" + fileListSummary + R"(

Return ONLY a JSON array of file paths that should be analyzed, limited to )" + std::to_string(maxFiles) + R"( most important files.
Format: ["path1", "path2", ...]
Do not include any explanation, only the JSON array.)";

    try {
        auto response = router_->chat(prompt);
        
        if (!response.success) {
            std::cerr << "LLM request failed: " << response.errorMessage << std::endl;
            // Fallback: return first N files
            if (allFiles.size() > maxFiles) {
                allFiles.resize(maxFiles);
            }
            return allFiles;
        }

        return parseImportantFiles(response.content, allFiles);
    } catch (const std::exception& e) {
        std::cerr << "Failed to select important files: " << e.what() << std::endl;
        // Fallback: return first N files
        if (allFiles.size() > maxFiles) {
            allFiles.resize(maxFiles);
        }
        return allFiles;
    }
}

bool LLMAnalysisService::storeDescription(const std::string& dbPath,
                                           const std::string& filePath,
                                           const std::string& description,
                                           const std::string& summary,
                                           const std::vector<std::string>& keywords,
                                           const std::string& modelUsed) {
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

    // Use UPDATE_FILE_LLM_ANALYSIS from file_classifier_sql.h
    // UPDATE files SET llm_summary=?, llm_description=?, llm_keywords=?, llm_analyzed_at=?, llm_model_used=? WHERE path=?
    sqlite3_stmt* stmt = nullptr;
    rc = sqlite3_prepare_v2(db, FileClassifierSQL::UPDATE_FILE_LLM_ANALYSIS, -1, &stmt, nullptr);
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
    sqlite3_bind_text(stmt, 6, filePath.c_str(), -1, SQLITE_TRANSIENT);

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
    std::string sql = "SELECT path FROM files";
    
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

    sql += " LIMIT " + std::to_string(options.maxFiles);

    sqlite3_stmt* stmt = nullptr;
    rc = sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr);
    if (rc != SQLITE_OK) {
        sqlite3_close(db);
        return files;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        const char* path = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
        if (path) {
            files.push_back(path);
        }
    }

    sqlite3_finalize(stmt);
    sqlite3_close(db);

    return files;
}

std::string LLMAnalysisService::buildFileListSummary(const std::vector<std::string>& files) {
    std::stringstream ss;
    
    // Group files by directory and extension for a compact summary
    std::map<std::string, std::vector<std::string>> byDir;
    
    for (const auto& file : files) {
        std::filesystem::path p(file);
        std::string dir = p.parent_path().string();
        std::string name = p.filename().string();
        byDir[dir].push_back(name);
    }

    for (const auto& [dir, names] : byDir) {
        ss << dir << "/\n";
        for (const auto& name : names) {
            ss << "  - " << name << "\n";
        }
    }

    return ss.str();
}

std::vector<std::string> LLMAnalysisService::parseImportantFiles(const std::string& llmResponse,
                                                                   const std::vector<std::string>& allFiles) {
    std::vector<std::string> importantFiles;

    // Try to parse JSON array from response
    try {
        // Find JSON array in response
        size_t start = llmResponse.find('[');
        size_t end = llmResponse.rfind(']');
        
        if (start != std::string::npos && end != std::string::npos && end > start) {
            std::string jsonStr = llmResponse.substr(start, end - start + 1);
            
            // Simple parsing - look for quoted strings
            size_t pos = 0;
            while ((pos = jsonStr.find('"', pos)) != std::string::npos) {
                size_t endQuote = jsonStr.find('"', pos + 1);
                if (endQuote == std::string::npos) break;
                
                std::string path = jsonStr.substr(pos + 1, endQuote - pos - 1);
                
                // Check if this path exists in our file list
                auto it = std::find(allFiles.begin(), allFiles.end(), path);
                if (it != allFiles.end()) {
                    importantFiles.push_back(path);
                } else {
                    // Try partial match
                    for (const auto& f : allFiles) {
                        if (f.find(path) != std::string::npos || 
                            path.find(f) != std::string::npos) {
                            importantFiles.push_back(f);
                            break;
                        }
                    }
                }
                
                pos = endQuote + 1;
            }
        }
    } catch (...) {
        // Fallback: return empty, caller should handle
    }

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
