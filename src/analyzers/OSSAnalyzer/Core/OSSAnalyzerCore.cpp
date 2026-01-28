/**
 * @file OSSAnalyzerCore.cpp
 * @brief OSS分析器核心实现
 */

#include "OSSAnalyzer.h"
#include "AuditLog/AuditLog.h"
#include "Logger/Logger.h"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <chrono>
#include <regex>

namespace fs = std::filesystem;

namespace ForensicAnalyzer {
namespace OSS {

OSSAnalyzer::OSSAnalyzer() = default;

OSSAnalyzer::OSSAnalyzer(const OSSConnectionConfig& config, DatabaseManager* dbManager)
    : config_(config), dbManager_(dbManager) {
}

OSSAnalyzer::~OSSAnalyzer() = default;

bool OSSAnalyzer::initialize() {
    // 初始化数据库
    std::string dbPath = outputDbPath_.empty() ? "oss_analysis.db" : outputDbPath_;
    ossDb_ = std::make_unique<OSSAnalysisDatabase>(dbPath);
    
    if (!ossDb_->initialize()) {
        setError("Failed to initialize OSS analysis database");
        return false;
    }
    
    // 如果有连接配置，初始化客户端
    if (!config_.endpoint.empty()) {
        client_ = std::make_unique<OSSClient>(config_);
        if (!client_->initialize()) {
            LOG_WARNING("OSS Client initialization failed, API mode disabled");
            // 不返回false，因为可能只是使用离线模式
        }
    }
    
    AuditLog::instance().log("SYSTEM", "OSS_INIT", "OSS Analyzer initialized");
    LOG_INFO("OSS Analyzer initialized, database: " + dbPath);
    return true;
}

void OSSAnalyzer::analyzeOSSData() {
    reportProgress("Starting OSS analysis", 0, -1);
    AuditLog::instance().log("SYSTEM", "OSS_ANALYSIS_START", "Starting OSS data analysis");
    
    // 默认使用API分析
    if (client_ && client_->isInitialized()) {
        analyzeFromAPI();
    }
    
    reportProgress("OSS analysis completed", 100, 100);
    AuditLog::instance().log("SYSTEM", "OSS_ANALYSIS_COMPLETE", "OSS data analysis completed");
}

bool OSSAnalyzer::analyzeFromAPI(const std::string& bucketName, const std::string& prefix) {
    if (!client_ || !client_->isInitialized()) {
        setError("OSS Client not initialized");
        return false;
    }
    
    std::string bucket = bucketName.empty() ? config_.bucket : bucketName;
    if (bucket.empty()) {
        setError("Bucket name is required");
        return false;
    }
    
    reportProgress("Fetching bucket info", 0, -1);
    
    // 获取Bucket信息
    auto bucketInfo = client_->getBucketInfo(bucket);
    bucketInfo.analyzedAt = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();
    ossDb_->insertBucket(bucketInfo);
    
    reportProgress("Listing objects", 0, -1);
    
    // 列出并存储所有对象
    int64_t count = 0;
    ossDb_->beginTransaction();
    
    client_->listAllObjects(bucket, prefix, 
        [this, &count](const OSSObjectInfo& obj) {
            OSSObjectInfo objCopy = obj;
            objCopy.analyzedAt = std::chrono::duration_cast<std::chrono::seconds>(
                std::chrono::system_clock::now().time_since_epoch()
            ).count();
            ossDb_->insertObject(objCopy);
            count++;
            
            if (count % 100 == 0) {
                reportProgress("Listing objects", count, -1);
            }
        },
        [this](int64_t current, int64_t total) {
            reportProgress("Listing objects", current, total);
        }
    );
    
    ossDb_->commitTransaction();
    
    // 更新Bucket统计信息
    bucketInfo.objectCount = count;
    ossDb_->insertBucket(bucketInfo);
    
    LOG_INFO("Analyzed " + std::to_string(count) + " objects from bucket: " + bucket);
    AuditLog::instance().log("SYSTEM", "OSS_API_ANALYSIS", 
        "Analyzed " + std::to_string(count) + " objects from: " + bucket);
    
    return true;
}

bool OSSAnalyzer::analyzeFromLocalDirectory(const std::string& localDir, const std::string& bucketName) {
    if (!fs::exists(localDir) || !fs::is_directory(localDir)) {
        setError("Directory does not exist: " + localDir);
        return false;
    }
    
    reportProgress("Scanning local directory", 0, -1);
    
    bool result = parseLocalDirectory(localDir, bucketName);
    
    if (result) {
        AuditLog::instance().log("SYSTEM", "OSS_LOCAL_ANALYSIS", 
            "Analyzed local directory: " + localDir);
    }
    
    return result;
}

bool OSSAnalyzer::parseLocalDirectory(const std::string& dir, const std::string& bucket, const std::string& prefix) {
    int64_t count = 0;
    int64_t totalSize = 0;
    
    ossDb_->beginTransaction();
    
    for (const auto& entry : fs::recursive_directory_iterator(dir)) {
        if (!entry.is_regular_file()) continue;
        
        std::string fullPath = entry.path().string();
        std::string relativePath = fs::relative(entry.path(), fs::path(dir)).string();
        
        // 将反斜杠转换为正斜杠（Windows兼容）
        std::replace(relativePath.begin(), relativePath.end(), '\\', '/');
        
        OSSObjectInfo obj = createObjectInfoFromFile(fullPath, bucket, prefix + relativePath);
        ossDb_->insertObject(obj);
        
        count++;
        totalSize += obj.size;
        
        if (count % 100 == 0) {
            reportProgress("Scanning files", count, -1);
        }
    }
    
    ossDb_->commitTransaction();
    
    // 创建虚拟Bucket记录
    OSSBucketInfo bucketInfo;
    bucketInfo.name = bucket;
    bucketInfo.objectCount = count;
    bucketInfo.totalSize = totalSize;
    bucketInfo.analyzedAt = std::chrono::duration_cast<std::chrono::seconds>(
        std::chrono::system_clock::now().time_since_epoch()
    ).count();
    ossDb_->insertBucket(bucketInfo);
    
    LOG_INFO("Scanned " + std::to_string(count) + " files from local directory");
    return true;
}

OSSObjectInfo OSSAnalyzer::createObjectInfoFromFile(const std::string& filePath, const std::string& bucket, const std::string& key) {
    OSSObjectInfo obj;
    obj.bucket = bucket;
    obj.key = key;
    
    try {
        auto status = fs::status(filePath);
        obj.size = fs::file_size(filePath);
        
        auto lastWrite = fs::last_write_time(filePath);
        auto sctp = std::chrono::time_point_cast<std::chrono::system_clock::duration>(
            lastWrite - fs::file_time_type::clock::now() + std::chrono::system_clock::now()
        );
        obj.lastModified = std::chrono::duration_cast<std::chrono::seconds>(
            sctp.time_since_epoch()
        ).count();
        
        // 推断content type
        std::string ext = fs::path(filePath).extension().string();
        if (!ext.empty()) {
            std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
            if (ext == ".jpg" || ext == ".jpeg") obj.contentType = "image/jpeg";
            else if (ext == ".png") obj.contentType = "image/png";
            else if (ext == ".gif") obj.contentType = "image/gif";
            else if (ext == ".pdf") obj.contentType = "application/pdf";
            else if (ext == ".txt") obj.contentType = "text/plain";
            else if (ext == ".html" || ext == ".htm") obj.contentType = "text/html";
            else if (ext == ".json") obj.contentType = "application/json";
            else if (ext == ".xml") obj.contentType = "application/xml";
            else if (ext == ".zip") obj.contentType = "application/zip";
            else obj.contentType = "application/octet-stream";
        }
        
        obj.storageClass = "Local";
        obj.analyzedAt = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()
        ).count();
        
    } catch (const std::exception& e) {
        LOG_WARNING("Failed to read file info: " + filePath + " - " + e.what());
    }
    
    return obj;
}

bool OSSAnalyzer::analyzeFromInventory(const std::string& csvPath) {
    if (!fs::exists(csvPath)) {
        setError("Inventory file does not exist: " + csvPath);
        return false;
    }
    
    reportProgress("Parsing inventory file", 0, -1);
    
    bool result = parseInventoryCSV(csvPath);
    
    if (result) {
        AuditLog::instance().log("SYSTEM", "OSS_INVENTORY_ANALYSIS", 
            "Analyzed inventory file: " + csvPath);
    }
    
    return result;
}

bool OSSAnalyzer::parseInventoryCSV(const std::string& csvPath) {
    std::ifstream file(csvPath);
    if (!file.is_open()) {
        setError("Cannot open inventory file: " + csvPath);
        return false;
    }
    
    std::string line;
    int64_t count = 0;
    bool isHeader = true;
    std::vector<std::string> headers;
    
    ossDb_->beginTransaction();
    
    while (std::getline(file, line)) {
        if (line.empty()) continue;
        
        std::vector<std::string> fields;
        std::stringstream ss(line);
        std::string field;
        
        // 简单CSV解析（不处理带引号的字段中的逗号）
        while (std::getline(ss, field, ',')) {
            // 去除引号
            if (!field.empty() && field.front() == '"' && field.back() == '"') {
                field = field.substr(1, field.size() - 2);
            }
            fields.push_back(field);
        }
        
        if (isHeader) {
            headers = fields;
            isHeader = false;
            continue;
        }
        
        // 解析字段（假设标准Inventory格式）
        OSSObjectInfo obj;
        for (size_t i = 0; i < headers.size() && i < fields.size(); ++i) {
            const auto& header = headers[i];
            const auto& value = fields[i];
            
            if (header == "Bucket") obj.bucket = value;
            else if (header == "Key") obj.key = value;
            else if (header == "Size") obj.size = std::stoll(value);
            else if (header == "ETag") obj.etag = value;
            else if (header == "StorageClass") obj.storageClass = value;
            else if (header == "LastModifiedDate") {
                // 尝试解析ISO时间格式
                // 简化处理：直接存储为0，实际应该解析
                obj.lastModified = 0;
            }
        }
        
        obj.analyzedAt = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()
        ).count();
        
        ossDb_->insertObject(obj);
        count++;
        
        if (count % 1000 == 0) {
            reportProgress("Parsing inventory", count, -1);
        }
    }
    
    ossDb_->commitTransaction();
    
    LOG_INFO("Parsed " + std::to_string(count) + " objects from inventory");
    return true;
}

bool OSSAnalyzer::analyzeAccessLogs(const std::string& logPath) {
    if (!fs::exists(logPath)) {
        setError("Log path does not exist: " + logPath);
        return false;
    }
    
    reportProgress("Parsing access logs", 0, -1);
    
    int64_t count = 0;
    ossDb_->beginTransaction();
    
    if (fs::is_directory(logPath)) {
        for (const auto& entry : fs::directory_iterator(logPath)) {
            if (entry.is_regular_file()) {
                parseAccessLogFile(entry.path().string());
                count++;
            }
        }
    } else {
        parseAccessLogFile(logPath);
        count = 1;
    }
    
    ossDb_->commitTransaction();
    
    AuditLog::instance().log("SYSTEM", "OSS_LOG_ANALYSIS", 
        "Analyzed " + std::to_string(count) + " log files");
    
    return true;
}

bool OSSAnalyzer::parseAccessLogFile(const std::string& logPath) {
    std::ifstream file(logPath);
    if (!file.is_open()) {
        LOG_WARNING("Cannot open log file: " + logPath);
        return false;
    }
    
    std::string line;
    int64_t count = 0;
    
    while (std::getline(file, line)) {
        if (line.empty()) continue;
        
        auto entry = parseAccessLogLine(line);
        if (!entry.requestId.empty()) {
            ossDb_->insertAccessLog(entry);
            count++;
        }
    }
    
    LOG_DEBUG("Parsed " + std::to_string(count) + " log entries from: " + logPath);
    return true;
}

OSSAccessLogEntry OSSAnalyzer::parseAccessLogLine(const std::string& line) {
    OSSAccessLogEntry entry;
    
    // OSS访问日志格式（空格分隔，部分字段用引号包裹）
    // 格式：RemoteIP - - [Time] "Request" Status Bytes "Referer" "UserAgent" ...
    
    // 简化解析：使用正则表达式
    // OSS日志格式: IP - - [timestamp] "METHOD /path HTTP/version" status bytes "referer" "user-agent"
    std::regex logPattern(R"regex((\S+)\s+\S+\s+\S+\s+\[([^\]]+)\]\s+"([^"]+)"\s+(\d+)\s+(\d+)\s+"([^"]*)"\s+"([^"]*)")regex");
    std::smatch match;
    
    if (std::regex_search(line, match, logPattern) && match.size() >= 8) {
        entry.remoteIP = match[1];
        // 时间戳解析简化
        entry.timestamp = 0; // 实际应解析 match[2]
        
        // 解析请求行
        std::string request = match[3];
        std::istringstream reqStream(request);
        std::string method, path;
        reqStream >> method >> path;
        entry.operation = method;
        entry.objectKey = path;
        
        entry.httpStatus = std::stoi(match[4]);
        entry.bytesSent = std::stoll(match[5]);
        entry.referer = match[6];
        entry.userAgent = match[7];
        
        // 生成请求ID
        entry.requestId = "log_" + std::to_string(std::hash<std::string>{}(line));
    }
    
    return entry;
}

bool OSSAnalyzer::fetchAndAnalyzeAccessLogs(
    const std::string& bucketName,
    int64_t startTime,
    int64_t endTime
) {
    if (!client_ || !client_->isInitialized()) {
        setError("OSS Client not initialized");
        return false;
    }
    
    std::string loggingBucket, loggingPrefix;
    if (!client_->getBucketLogging(bucketName, loggingBucket, loggingPrefix)) {
        setError("Bucket logging not enabled or failed to get logging config");
        return false;
    }
    
    reportProgress("Fetching access logs", 0, -1);
    
    // 列出日志文件
    auto logFiles = client_->listAccessLogFiles(loggingBucket, loggingPrefix, startTime, endTime);
    
    int64_t count = 0;
    for (const auto& logFile : logFiles) {
        std::string content;
        if (client_->getObjectContent(loggingBucket, logFile.key, content)) {
            std::istringstream stream(content);
            std::string line;
            while (std::getline(stream, line)) {
                auto entry = parseAccessLogLine(line);
                if (!entry.requestId.empty()) {
                    entry.bucket = bucketName;
                    ossDb_->insertAccessLog(entry);
                    count++;
                }
            }
        }
        
        reportProgress("Parsing logs", count, -1);
    }
    
    LOG_INFO("Fetched and parsed " + std::to_string(count) + " access log entries");
    return true;
}

// ========== 查询方法 ==========

std::vector<OSSObjectInfo> OSSAnalyzer::getAllObjects() {
    return ossDb_ ? ossDb_->getAllObjects() : std::vector<OSSObjectInfo>{};
}

std::vector<OSSObjectInfo> OSSAnalyzer::getObjectsByBucket(const std::string& bucket) {
    return ossDb_ ? ossDb_->getObjectsByBucket(bucket) : std::vector<OSSObjectInfo>{};
}

std::vector<OSSObjectInfo> OSSAnalyzer::getObjectsByExtension(const std::string& extension) {
    return ossDb_ ? ossDb_->getObjectsByExtension(extension) : std::vector<OSSObjectInfo>{};
}

std::vector<OSSAccessLogEntry> OSSAnalyzer::getAccessLogs(int64_t startTime, int64_t endTime) {
    if (!ossDb_) return {};
    if (endTime == 0) {
        endTime = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()
        ).count();
    }
    return ossDb_->getAccessLogsByTimeRange(startTime, endTime);
}

OSSAnalysisSummary OSSAnalyzer::getAnalysisSummary() {
    return ossDb_ ? ossDb_->getAnalysisSummary() : OSSAnalysisSummary{};
}

// ========== 工具方法 ==========

void OSSAnalyzer::setError(const std::string& error) {
    lastError_ = error;
    LOG_ERROR(error);
}

void OSSAnalyzer::reportProgress(const std::string& phase, int64_t current, int64_t total) {
    if (progressCallback_) {
        progressCallback_(phase, current, total);
    }
}

} // namespace OSS
} // namespace ForensicAnalyzer
