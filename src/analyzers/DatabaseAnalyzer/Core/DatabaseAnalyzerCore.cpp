/**
 * @file DatabaseAnalyzerCore.cpp
 * @brief 数据库取证分析器核心实现
 */

#include "DatabaseAnalyzer.h"

#include <filesystem>

namespace fs = std::filesystem;

namespace ForensicAnalyzer {
namespace Database {

DatabaseAnalyzer::DatabaseAnalyzer() = default;

DatabaseAnalyzer::~DatabaseAnalyzer() = default;

bool DatabaseAnalyzer::initialize(const std::string& outputDbPath) {
    resultDb_ = std::make_unique<DBAnalysisDatabase>(outputDbPath);
    
    if (!resultDb_->initialize()) {
        setError("Failed to initialize result database: " + resultDb_->getLastError());
        return false;
    }
    
    return true;
}

int64_t DatabaseAnalyzer::analyze(const std::string& path) {
    // 自动检测类型
    DatabaseType type = DBParserFactory::detectType(path);
    if (type == DatabaseType::UNKNOWN) {
        setError("Unable to detect database type for: " + path);
        return -1;
    }
    
    return analyze(path, type);
}

int64_t DatabaseAnalyzer::analyze(const std::string& path, DatabaseType type) {
    if (!resultDb_) {
        setError("Analyzer not initialized. Call initialize() first.");
        return -1;
    }
    
    reportProgress("Creating parser", 0, -1);
    
    // 创建解析器
    auto parser = DBParserFactory::createParser(type);
    if (!parser) {
        setError("No parser available for type: " + databaseTypeToString(type));
        return -1;
    }
    
    // 设置进度回调
    if (progressCallback_) {
        parser->setProgressCallback(progressCallback_);
    }
    
    // 打开数据库
    reportProgress("Opening database", 0, -1);
    if (!parser->open(path)) {
        setError("Failed to open database: " + parser->getLastError());
        return -1;
    }
    
    // 执行分析
    int64_t sessionId = doAnalyze(parser.get());
    
    parser->close();
    
    return sessionId;
}

int64_t DatabaseAnalyzer::doAnalyze(IDBParser* parser) {
    // 开始会话
    int64_t sessionId = resultDb_->beginSession(parser->getPath(), parser->getType());
    if (sessionId < 0) {
        setError("Failed to begin session: " + resultDb_->getLastError());
        return -1;
    }
    
    DBAnalysisSummary summary;
    summary.databasePath = parser->getPath();
    summary.type = parser->getType();
    summary.version = parser->getVersion();
    summary.fileSizeBytes = parser->getFileSize();
    
    try {
        // 1. 提取表结构
        reportProgress("Extracting tables", 0, -1);
        auto tables = parser->getTables();
        resultDb_->insertTables(sessionId, tables);
        summary.tableCount = tables.size();
        
        // 2. 提取记录（如果启用）
        if (options_.extractRecords) {
            reportProgress("Extracting records", 0, tables.size());
            
            for (size_t i = 0; i < tables.size(); i++) {
                const auto& table = tables[i];
                
                // 检查排除列表
                bool excluded = false;
                for (const auto& exclude : options_.excludeTables) {
                    if (table.name == exclude) {
                        excluded = true;
                        break;
                    }
                }
                if (excluded) continue;
                
                // 检查包含列表
                if (!options_.includeTables.empty()) {
                    bool included = false;
                    for (const auto& include : options_.includeTables) {
                        if (table.name == include) {
                            included = true;
                            break;
                        }
                    }
                    if (!included) continue;
                }
                
                int limit = options_.maxRecordsPerTable;
                auto records = parser->getRecords(table.name, limit);
                resultDb_->insertRecords(sessionId, records);
                summary.totalRecords += records.size();
                
                reportProgress("Extracting records", i + 1, tables.size());
            }
        }
        
        // 3. 提取工件（如果启用）
        if (options_.extractArtifacts) {
            reportProgress("Extracting artifacts", 0, -1);
            auto artifacts = parser->extractArtifacts(options_);
            resultDb_->insertArtifacts(sessionId, artifacts);
            summary.artifactCount = artifacts.size();
        }
        
        // 4. 提取用户信息（如果启用）
        if (options_.extractUsers) {
            reportProgress("Extracting users", 0, -1);
            auto users = parser->getUsers();
            for (const auto& user : users) {
                resultDb_->insertUser(sessionId, user);
            }
            summary.userCount = users.size();
        }
        
        // 5. 恢复删除记录（如果启用）
        if (options_.extractDeletedRecords) {
            reportProgress("Recovering deleted records", 0, -1);
            auto deletedRecords = parser->recoverDeletedRecords(options_.maxDeletedRecords);
            for (auto& record : deletedRecords) {
                record.isDeleted = true;
            }
            resultDb_->insertRecords(sessionId, deletedRecords);
            summary.deletedRecords = deletedRecords.size();
        }
        
    } catch (const std::exception& e) {
        summary.lastError = e.what();
    }
    
    // 结束会话
    reportProgress("Completing analysis", 0, -1);
    resultDb_->endSession(sessionId, summary);
    
    return sessionId;
}

std::vector<std::pair<std::string, DatabaseType>> DatabaseAnalyzer::scanDirectory(
    const std::string& directory, 
    bool recursive) {
    
    std::vector<std::pair<std::string, DatabaseType>> databases;
    
    if (!fs::exists(directory) || !fs::is_directory(directory)) {
        return databases;
    }
    
    auto scanPath = [&databases](const fs::path& path) {
        if (fs::is_regular_file(path)) {
            DatabaseType type = DBParserFactory::detectType(path.string());
            if (type != DatabaseType::UNKNOWN) {
                databases.emplace_back(path.string(), type);
            }
        } else if (fs::is_directory(path)) {
            // 检查目录是否是MySQL或PostgreSQL数据目录
            DatabaseType type = DBParserFactory::detectType(path.string());
            if (type == DatabaseType::MYSQL || type == DatabaseType::POSTGRESQL) {
                databases.emplace_back(path.string(), type);
            }
        }
    };
    
    try {
        if (recursive) {
            for (const auto& entry : fs::recursive_directory_iterator(directory)) {
                scanPath(entry.path());
            }
        } else {
            for (const auto& entry : fs::directory_iterator(directory)) {
                scanPath(entry.path());
            }
        }
    } catch (const std::exception& e) {
        setError("Error scanning directory: " + std::string(e.what()));
    }
    
    return databases;
}

int DatabaseAnalyzer::analyzeDirectory(const std::string& directory, bool recursive) {
    auto databases = scanDirectory(directory, recursive);
    
    int successCount = 0;
    for (size_t i = 0; i < databases.size(); i++) {
        const auto& [path, type] = databases[i];
        
        reportProgress("Analyzing databases", i, databases.size());
        
        int64_t sessionId = analyze(path, type);
        if (sessionId >= 0) {
            successCount++;
        }
    }
    
    return successCount;
}

std::vector<DBAnalysisSummary> DatabaseAnalyzer::getAllSessions() {
    if (!resultDb_) return {};
    return resultDb_->getAllSessions();
}

DBAnalysisSummary DatabaseAnalyzer::getSessionSummary(int64_t sessionId) {
    if (!resultDb_) return {};
    return resultDb_->getSessionSummary(sessionId);
}

std::vector<DBTableInfo> DatabaseAnalyzer::getTables(int64_t sessionId) {
    if (!resultDb_) return {};
    return resultDb_->getTables(sessionId);
}

std::vector<DBRecordInfo> DatabaseAnalyzer::getRecords(int64_t sessionId, 
                                                       const std::string& tableName,
                                                       int limit, int offset) {
    if (!resultDb_) return {};
    return resultDb_->getRecords(sessionId, tableName, limit, offset);
}

std::vector<DBArtifact> DatabaseAnalyzer::getArtifacts(int64_t sessionId) {
    if (!resultDb_) return {};
    return resultDb_->getArtifacts(sessionId);
}

std::vector<DBUserInfo> DatabaseAnalyzer::getUsers(int64_t sessionId) {
    if (!resultDb_) return {};
    return resultDb_->getUsers(sessionId);
}

void DatabaseAnalyzer::setError(const std::string& error) {
    lastError_ = error;
}

void DatabaseAnalyzer::reportProgress(const std::string& phase, int64_t current, int64_t total) {
    if (progressCallback_) {
        progressCallback_(phase, current, total);
    }
}

} // namespace Database
} // namespace ForensicAnalyzer
