/**
 * @file OSSDataTypes.h
 * @brief OSS核心数据结构定义
 * 
 * 定义OSS对象、Bucket和访问日志的数据结构
 */

#pragma once

#include <string>
#include <vector>
#include <map>
#include <cstdint>

namespace ForensicAnalyzer {
namespace OSS {

/**
 * @brief OSS对象信息
 * 
 * 存储OSS对象的完整元数据信息
 */
struct OSSObjectInfo {
    std::string key;                ///< 对象键（完整路径）
    std::string bucket;             ///< 所属Bucket名称
    int64_t size = 0;               ///< 对象大小（字节）
    std::string etag;               ///< ETag（通常是MD5校验值）
    int64_t lastModified = 0;       ///< 最后修改时间（Unix时间戳）
    std::string storageClass;       ///< 存储类型（Standard/IA/Archive等）
    std::string contentType;        ///< MIME类型
    std::string owner;              ///< 所有者ID
    std::map<std::string, std::string> userMeta; ///< 用户自定义元数据
    
    // 分析相关字段
    int64_t analyzedAt = 0;         ///< 分析时间
    std::string md5Hash;            ///< 本地计算的MD5（如果下载了文件）
    bool isDeleted = false;         ///< 是否在版本控制中被标记删除
    std::string versionId;          ///< 版本ID（如果启用了版本控制）
};

/**
 * @brief OSS访问日志条目
 * 
 * 存储单条OSS访问日志记录，用于审计和时间线分析
 */
struct OSSAccessLogEntry {
    std::string requestId;          ///< 请求ID（唯一标识）
    int64_t timestamp = 0;          ///< 请求时间（Unix时间戳）
    std::string operation;          ///< 操作类型（GetObject/PutObject/DeleteObject等）
    std::string bucket;             ///< 目标Bucket
    std::string objectKey;          ///< 目标对象键
    std::string remoteIP;           ///< 客户端IP地址
    std::string userAgent;          ///< 客户端User-Agent
    std::string accesserId;         ///< 访问者ID
    int httpStatus = 0;             ///< HTTP返回状态码
    int64_t bytesSent = 0;          ///< 发送字节数
    int64_t objectSize = 0;         ///< 对象大小
    int64_t timeTakenMs = 0;        ///< 请求耗时（毫秒）
    std::string referer;            ///< HTTP Referer
    std::string host;               ///< 请求Host
    std::string signatureVersion;   ///< 签名版本
    bool sslEnabled = false;        ///< 是否使用HTTPS
};

/**
 * @brief OSS Bucket信息
 * 
 * 存储Bucket级别的配置和状态信息
 */
struct OSSBucketInfo {
    std::string name;               ///< Bucket名称
    std::string region;             ///< 所在地域（如oss-cn-hangzhou）
    std::string endpoint;           ///< 访问域名
    std::string acl;                ///< 访问控制（private/public-read/public-read-write）
    std::string owner;              ///< 所有者ID
    int64_t creationDate = 0;       ///< 创建时间
    bool versioningEnabled = false; ///< 是否启用版本控制
    bool loggingEnabled = false;    ///< 是否启用访问日志
    std::string loggingBucket;      ///< 日志存储Bucket
    std::string loggingPrefix;      ///< 日志前缀
    std::string storageClass;       ///< 默认存储类型
    
    // 统计信息
    int64_t objectCount = 0;        ///< 对象数量
    int64_t totalSize = 0;          ///< 总存储大小
    int64_t analyzedAt = 0;         ///< 分析时间
};

/**
 * @brief OSS连接配置
 * 
 * 存储连接OSS所需的配置信息
 */
struct OSSConnectionConfig {
    std::string accessKeyId;        ///< Access Key ID
    std::string accessKeySecret;    ///< Access Key Secret
    std::string securityToken;      ///< STS安全令牌（可选）
    std::string endpoint;           ///< OSS Endpoint
    std::string bucket;             ///< 默认Bucket名称
    std::string region;             ///< 地域
    
    int connectTimeoutMs = 10000;   ///< 连接超时（毫秒）
    int requestTimeoutMs = 30000;   ///< 请求超时（毫秒）
    int maxConnections = 16;        ///< 最大连接数
    
    bool useProxy = false;          ///< 是否使用代理
    std::string proxyHost;          ///< 代理主机
    int proxyPort = 0;              ///< 代理端口
    
    bool enableCrc = true;          ///< 启用CRC校验
    bool enableMD5 = false;         ///< 启用MD5校验
};

/**
 * @brief OSS分析结果摘要
 * 
 * 分析任务完成后的统计摘要
 */
struct OSSAnalysisSummary {
    int64_t totalObjects = 0;       ///< 总对象数
    int64_t totalSize = 0;          ///< 总大小（字节）
    int64_t deletedObjects = 0;     ///< 已删除对象数
    int64_t logEntriesCount = 0;    ///< 日志条目数
    
    std::map<std::string, int64_t> objectsByStorageClass;  ///< 按存储类型分类
    std::map<std::string, int64_t> objectsByExtension;     ///< 按扩展名分类
    std::map<std::string, int64_t> operationCounts;        ///< 操作类型统计
    
    int64_t analysisStartTime = 0;  ///< 分析开始时间
    int64_t analysisEndTime = 0;    ///< 分析结束时间
    std::string exportType;         ///< 使用的导出类型
};

} // namespace OSS
} // namespace ForensicAnalyzer
