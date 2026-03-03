/**
 * @file OSSClient.cpp
 * @brief 阿里云OSS客户端实现
 * 
 * 封装阿里云OSS C++ SDK的具体实现
 */

#include "OSSClient.h"
#include "Logger/Logger.h"

// 阿里云OSS SDK头文件
#include <alibabacloud/oss/OssClient.h>
#include <alibabacloud/oss/client/ClientConfiguration.h>

#include <chrono>
#include <ctime>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace ForensicAnalyzer {
namespace OSS {

using namespace AlibabaCloud::OSS;

/**
 * @brief 解析 OSS 返回的 ISO 8601 时间字符串为 Unix 时间戳
 * 格式示例: "2024-01-15T08:30:00.000Z" 或 "2024-01-15T08:30:00Z"
 */
static int64_t parseOssDateTime(const std::string& dt) {
    if (dt.empty()) return 0;
    try {
        std::tm tm = {};
        std::istringstream ss(dt);
        // Try "%Y-%m-%dT%H:%M:%S"
        ss >> std::get_time(&tm, "%Y-%m-%dT%H:%M:%S");
        if (ss.fail()) return 0;
        tm.tm_isdst = -1;
        return static_cast<int64_t>(timegm(&tm));
    } catch (...) {
        return 0;
    }
}

/**
 * @brief OSSClient的内部实现类（pimpl模式）
 */
class OSSClient::Impl {
public:
    std::unique_ptr<AlibabaCloud::OSS::OssClient> client;
    
    Impl() = default;
    ~Impl() = default;
};

OSSClient::OSSClient() : impl_(std::make_unique<Impl>()) {
}

OSSClient::OSSClient(const OSSConnectionConfig& config) 
    : config_(config), impl_(std::make_unique<Impl>()) {
}

OSSClient::~OSSClient() = default;

void OSSClient::setConfig(const OSSConnectionConfig& config) {
    config_ = config;
    initialized_ = false;
}

bool OSSClient::initialize() {
    if (config_.endpoint.empty() || config_.accessKeyId.empty() || config_.accessKeySecret.empty()) {
        setError("Invalid configuration: endpoint, accessKeyId, and accessKeySecret are required");
        return false;
    }
    
    try {
        // 初始化OSS SDK
        InitializeSdk();
        
        // 配置客户端
        ClientConfiguration conf;
        conf.connectTimeoutMs = config_.connectTimeoutMs;
        conf.requestTimeoutMs = config_.requestTimeoutMs;
        conf.maxConnections = config_.maxConnections;
        conf.enableCrc64 = config_.enableCrc;
        
        if (config_.useProxy && !config_.proxyHost.empty()) {
            conf.proxyHost = config_.proxyHost;
            conf.proxyPort = config_.proxyPort;
        }
        
        // 创建客户端
        if (!config_.securityToken.empty()) {
            // 使用STS临时凭证
            impl_->client = std::make_unique<AlibabaCloud::OSS::OssClient>(
                config_.endpoint,
                config_.accessKeyId,
                config_.accessKeySecret,
                config_.securityToken,
                conf
            );
        } else {
            // 使用长期凭证
            impl_->client = std::make_unique<AlibabaCloud::OSS::OssClient>(
                config_.endpoint,
                config_.accessKeyId,
                config_.accessKeySecret,
                conf
            );
        }
        
        initialized_ = true;
        LOG_INFO("OSS Client initialized for endpoint: " + config_.endpoint);
        return true;
        
    } catch (const std::exception& e) {
        setError("Failed to initialize OSS client: " + std::string(e.what()));
        return false;
    }
}

bool OSSClient::testConnection() {
    if (!initialized_) {
        setError("Client not initialized");
        return false;
    }
    
    try {
        // 尝试列出Bucket来测试连接
        ListBucketsRequest request;
        auto outcome = impl_->client->ListBuckets(request);
        
        if (!outcome.isSuccess()) {
            setError("Connection test failed: " + outcome.error().Message());
            return false;
        }
        
        return true;
        
    } catch (const std::exception& e) {
        setError("Connection test failed: " + std::string(e.what()));
        return false;
    }
}

std::vector<OSSBucketInfo> OSSClient::listBuckets() {
    std::vector<OSSBucketInfo> results;
    
    if (!initialized_) {
        setError("Client not initialized");
        return results;
    }
    
    try {
        ListBucketsRequest request;
        auto outcome = impl_->client->ListBuckets(request);
        
        if (!outcome.isSuccess()) {
            setError("Failed to list buckets: " + outcome.error().Message());
            return results;
        }
        
        for (const auto& bucket : outcome.result().Buckets()) {
            OSSBucketInfo info;
            info.name = bucket.Name();
            info.region = bucket.Location();
            info.creationDate = parseOssDateTime(bucket.CreationDate());
            info.storageClass = bucket.StorageClass();
            results.push_back(info);
        }
        
    } catch (const std::exception& e) {
        setError("Failed to list buckets: " + std::string(e.what()));
    }
    
    return results;
}

OSSBucketInfo OSSClient::getBucketInfo(const std::string& bucketName) {
    OSSBucketInfo info;
    
    if (!initialized_) {
        setError("Client not initialized");
        return info;
    }
    
    try {
        // 获取Bucket基本信息
        GetBucketInfoRequest infoRequest(bucketName);
        auto infoOutcome = impl_->client->GetBucketInfo(infoRequest);
        
        if (infoOutcome.isSuccess()) {
            info.name = bucketName;
            info.region = infoOutcome.result().Location();
            info.acl = std::to_string(static_cast<int>(infoOutcome.result().Acl()));
            info.storageClass = infoOutcome.result().StorageClass();
            info.creationDate = parseOssDateTime(infoOutcome.result().CreationDate());
            info.owner = infoOutcome.result().Owner().Id();
        }
        
        // 获取版本控制状态
        GetBucketVersioningRequest versionRequest(bucketName);
        auto versionOutcome = impl_->client->GetBucketVersioning(versionRequest);
        if (versionOutcome.isSuccess()) {
            info.versioningEnabled = (versionOutcome.result().Status() == VersioningStatus::Enabled);
        }
        
        // 获取日志配置
        GetBucketLoggingRequest loggingRequest(bucketName);
        auto loggingOutcome = impl_->client->GetBucketLogging(loggingRequest);
        if (loggingOutcome.isSuccess()) {
            info.loggingEnabled = !loggingOutcome.result().TargetBucket().empty();
            info.loggingBucket = loggingOutcome.result().TargetBucket();
            info.loggingPrefix = loggingOutcome.result().TargetPrefix();
        }
        
        info.analyzedAt = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()
        ).count();
        
    } catch (const std::exception& e) {
        setError("Failed to get bucket info: " + std::string(e.what()));
    }
    
    return info;
}

std::vector<OSSObjectInfo> OSSClient::listObjects(
    const std::string& bucketName,
    const std::string& prefix,
    const std::string& marker,
    int maxKeys
) {
    std::vector<OSSObjectInfo> results;
    
    if (!initialized_) {
        setError("Client not initialized");
        return results;
    }
    
    try {
        ListObjectsRequest request(bucketName);
        if (!prefix.empty()) request.setPrefix(prefix);
        if (!marker.empty()) request.setMarker(marker);
        request.setMaxKeys(maxKeys);
        
        auto outcome = impl_->client->ListObjects(request);
        
        if (!outcome.isSuccess()) {
            setError("Failed to list objects: " + outcome.error().Message());
            return results;
        }
        
        for (const auto& obj : outcome.result().ObjectSummarys()) {
            OSSObjectInfo info;
            info.bucket = bucketName;
            info.key = obj.Key();
            info.size = obj.Size();
            info.etag = obj.ETag();
            info.lastModified = parseOssDateTime(obj.LastModified());
            info.storageClass = obj.StorageClass();
            info.owner = obj.Owner().Id();
            results.push_back(info);
        }
        
    } catch (const std::exception& e) {
        setError("Failed to list objects: " + std::string(e.what()));
    }
    
    return results;
}

int64_t OSSClient::listAllObjects(
    const std::string& bucketName,
    const std::string& prefix,
    ObjectListCallback callback,
    ProgressCallback progressCallback
) {
    if (!initialized_) {
        setError("Client not initialized");
        return 0;
    }
    
    int64_t totalCount = 0;
    std::string marker;
    bool isTruncated = true;
    
    try {
        while (isTruncated) {
            ListObjectsRequest request(bucketName);
            if (!prefix.empty()) request.setPrefix(prefix);
            if (!marker.empty()) request.setMarker(marker);
            request.setMaxKeys(1000);
            
            auto outcome = impl_->client->ListObjects(request);
            
            if (!outcome.isSuccess()) {
                setError("Failed to list objects: " + outcome.error().Message());
                break;
            }
            
            for (const auto& obj : outcome.result().ObjectSummarys()) {
                OSSObjectInfo info;
                info.bucket = bucketName;
                info.key = obj.Key();
                info.size = obj.Size();
                info.etag = obj.ETag();
                info.lastModified = parseOssDateTime(obj.LastModified());
                info.storageClass = obj.StorageClass();
                info.owner = obj.Owner().Id();
                
                callback(info);
                totalCount++;
            }
            
            isTruncated = outcome.result().IsTruncated();
            marker = outcome.result().NextMarker();
            
            if (progressCallback) {
                progressCallback(totalCount, -1); // Total unknown
            }
        }
        
    } catch (const std::exception& e) {
        setError("Failed to list all objects: " + std::string(e.what()));
    }
    
    return totalCount;
}

OSSObjectInfo OSSClient::getObjectMeta(const std::string& bucketName, const std::string& objectKey) {
    OSSObjectInfo info;
    
    if (!initialized_) {
        setError("Client not initialized");
        return info;
    }
    
    try {
        HeadObjectRequest request(bucketName, objectKey);
        auto outcome = impl_->client->HeadObject(request);
        
        if (!outcome.isSuccess()) {
            setError("Failed to get object meta: " + outcome.error().Message());
            return info;
        }
        
        info.bucket = bucketName;
        info.key = objectKey;
        info.size = outcome.result().ContentLength();
        info.etag = outcome.result().ETag();
        info.lastModified = parseOssDateTime(outcome.result().LastModified());
        info.contentType = outcome.result().ContentType();
        
        // 获取用户自定义元数据
        for (const auto& meta : outcome.result().UserMetaData()) {
            info.userMeta[meta.first] = meta.second;
        }
        
    } catch (const std::exception& e) {
        setError("Failed to get object meta: " + std::string(e.what()));
    }
    
    return info;
}

bool OSSClient::downloadObject(
    const std::string& bucketName,
    const std::string& objectKey,
    const std::string& localPath,
    ProgressCallback progressCallback
) {
    if (!initialized_) {
        setError("Client not initialized");
        return false;
    }
    
    try {
        GetObjectRequest request(bucketName, objectKey);
        request.setResponseStreamFactory([&localPath]() {
            return std::make_shared<std::fstream>(localPath, 
                std::ios_base::out | std::ios_base::binary | std::ios_base::trunc);
        });
        
        if (progressCallback) {
            AlibabaCloud::OSS::TransferProgress tp;
            tp.Handler = [&progressCallback](size_t /*increment*/, int64_t transferred, int64_t total, void* /*userData*/) {
                progressCallback(transferred, total);
            };
            request.setTransferProgress(tp);
        }
        
        auto outcome = impl_->client->GetObject(request);
        
        if (!outcome.isSuccess()) {
            setError("Failed to download object: " + outcome.error().Message());
            return false;
        }
        
        return true;
        
    } catch (const std::exception& e) {
        setError("Failed to download object: " + std::string(e.what()));
        return false;
    }
}

bool OSSClient::getObjectContent(
    const std::string& bucketName,
    const std::string& objectKey,
    std::string& content
) {
    if (!initialized_) {
        setError("Client not initialized");
        return false;
    }
    
    try {
        GetObjectRequest request(bucketName, objectKey);
        auto outcome = impl_->client->GetObject(request);
        
        if (!outcome.isSuccess()) {
            setError("Failed to get object content: " + outcome.error().Message());
            return false;
        }
        
        std::stringstream ss;
        ss << outcome.result().Content()->rdbuf();
        content = ss.str();
        
        return true;
        
    } catch (const std::exception& e) {
        setError("Failed to get object content: " + std::string(e.what()));
        return false;
    }
}

bool OSSClient::getBucketLogging(
    const std::string& bucketName,
    std::string& loggingBucket,
    std::string& loggingPrefix
) {
    if (!initialized_) {
        setError("Client not initialized");
        return false;
    }
    
    try {
        GetBucketLoggingRequest request(bucketName);
        auto outcome = impl_->client->GetBucketLogging(request);
        
        if (!outcome.isSuccess()) {
            setError("Failed to get bucket logging: " + outcome.error().Message());
            return false;
        }
        
        loggingBucket = outcome.result().TargetBucket();
        loggingPrefix = outcome.result().TargetPrefix();
        
        return !loggingBucket.empty();
        
    } catch (const std::exception& e) {
        setError("Failed to get bucket logging: " + std::string(e.what()));
        return false;
    }
}

std::vector<OSSObjectInfo> OSSClient::listAccessLogFiles(
    const std::string& loggingBucket,
    const std::string& loggingPrefix,
    int64_t startTime,
    int64_t endTime
) {
    // 简单实现：仅按前缀列出文件
    // 实际可以根据时间戳筛选
    return listObjects(loggingBucket, loggingPrefix, "", 1000);
}

void OSSClient::setError(const std::string& error) {
    lastError_ = error;
    LOG_ERROR(error);
}

} // namespace OSS
} // namespace ForensicAnalyzer
