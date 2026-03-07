#include "LLMAnalysisService.h"
#include "DatabaseManager/SQL/file_classifier_sql.h"
#include <sqlite3.h>
#include <iostream>
#include <filesystem>
#include <sstream>
#include <algorithm>
#include <ctime>

namespace forensics {

LLMAnalysisService::LLMAnalysisService() = default;
LLMAnalysisService::~LLMAnalysisService() = default;

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

int LLMAnalysisService::analyzeAllFiles(const std::string& filesDbPath,
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
            auto result = fileAnalyzer_->analyzeFile(filePath, options.maxContentLength);
            
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

int LLMAnalysisService::analyzeSmartFiles(const std::string& filesDbPath,
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
            auto result = fileAnalyzer_->analyzeFile(filePath, options.maxContentLength);
            
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
    sqlite3_close(db);

    if (rc != SQLITE_DONE) {
        std::cerr << "Failed to update LLM analysis for file: " << filePath << std::endl;
        return false;
    }

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

} // namespace forensics
