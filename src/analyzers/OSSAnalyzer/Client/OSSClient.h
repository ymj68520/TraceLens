/**
 * @file OSSClient.h
 * @brief 阿里云OSS客户端接口
 * 
 * 封装阿里云OSS C++ SDK，提供对象列表、获取、下载等操作
 */

#pragma once

#include <string>
#include <vector>
#include <memory>
#include <functional>

#include "../Common/OSSDataTypes.h"
#include "../Common/OSSExportTypes.h"

namespace ForensicAnalyzer {
namespace OSS {

/**
 * @brief 对象列表回调类型
 */
using ObjectListCallback = std::function<void(const OSSObjectInfo& object)>;

/**
 * @brief 进度回调类型
 * @param current 当前进度
 * @param total 总量
 */
using ProgressCallback = std::function<void(int64_t current, int64_t total)>;

/**
 * @class OSSClient
 * @brief 阿里云OSS客户端
 * 
 * 封装阿里云OSS C++ SDK，提供连接、对象操作和日志获取功能
 */
class OSSClient {
public:
    OSSClient();
    explicit OSSClient(const OSSConnectionConfig& config);
    ~OSSClient();
    
    // 禁止拷贝
    OSSClient(const OSSClient&) = delete;
    OSSClient& operator=(const OSSClient&) = delete;
    
    /**
     * @brief 初始化客户端
     * @return 成功返回true
     */
    bool initialize();
    
    /**
     * @brief 设置连接配置
     * @param config 连接配置
     */
    void setConfig(const OSSConnectionConfig& config);
    
    /**
     * @brief 测试连接
     * @return 连接成功返回true
     */
    bool testConnection();
    
    // ========== Bucket操作 ==========
    
    /**
     * @brief 列出所有Bucket
     * @return Bucket信息列表
     */
    std::vector<OSSBucketInfo> listBuckets();
    
    /**
     * @brief 获取Bucket信息（包括ACL、版本控制等配置）
     * @param bucketName Bucket名称
     * @return Bucket信息
     */
    OSSBucketInfo getBucketInfo(const std::string& bucketName);
    
    // ========== 对象操作 ==========
    
    /**
     * @brief 列出Bucket中的对象
     * @param bucketName Bucket名称
     * @param prefix 前缀筛选（可选）
     * @param marker 分页标记（可选）
     * @param maxKeys 最大返回数（默认1000）
     * @return 对象列表
     */
    std::vector<OSSObjectInfo> listObjects(
        const std::string& bucketName,
        const std::string& prefix = "",
        const std::string& marker = "",
        int maxKeys = 1000
    );
    
    /**
     * @brief 列出所有对象（自动分页）
     * @param bucketName Bucket名称
     * @param prefix 前缀筛选（可选）
     * @param callback 每个对象的回调
     * @param progressCallback 进度回调（可选）
     * @return 总对象数
     */
    int64_t listAllObjects(
        const std::string& bucketName,
        const std::string& prefix,
        ObjectListCallback callback,
        ProgressCallback progressCallback = nullptr
    );
    
    /**
     * @brief 获取对象元数据
     * @param bucketName Bucket名称
     * @param objectKey 对象键
     * @return 对象信息
     */
    OSSObjectInfo getObjectMeta(const std::string& bucketName, const std::string& objectKey);
    
    /**
     * @brief 下载对象到文件
     * @param bucketName Bucket名称
     * @param objectKey 对象键
     * @param localPath 本地文件路径
     * @param progressCallback 进度回调（可选）
     * @return 成功返回true
     */
    bool downloadObject(
        const std::string& bucketName,
        const std::string& objectKey,
        const std::string& localPath,
        ProgressCallback progressCallback = nullptr
    );
    
    /**
     * @brief 获取对象内容到内存
     * @param bucketName Bucket名称
     * @param objectKey 对象键
     * @param content 输出内容
     * @return 成功返回true
     */
    bool getObjectContent(
        const std::string& bucketName,
        const std::string& objectKey,
        std::string& content
    );
    
    // ========== 日志操作 ==========
    
    /**
     * @brief 获取Bucket访问日志配置
     * @param bucketName Bucket名称
     * @param loggingBucket 输出：日志存储Bucket
     * @param loggingPrefix 输出：日志前缀
     * @return 是否启用日志
     */
    bool getBucketLogging(
        const std::string& bucketName,
        std::string& loggingBucket,
        std::string& loggingPrefix
    );
    
    /**
     * @brief 列出访问日志文件
     * @param loggingBucket 日志Bucket
     * @param loggingPrefix 日志前缀
     * @param startTime 开始时间（可选）
     * @param endTime 结束时间（可选）
     * @return 日志文件对象列表
     */
    std::vector<OSSObjectInfo> listAccessLogFiles(
        const std::string& loggingBucket,
        const std::string& loggingPrefix,
        int64_t startTime = 0,
        int64_t endTime = 0
    );
    
    /**
     * @brief 获取最后错误信息
     * @return 错误信息
     */
    std::string getLastError() const { return lastError_; }
    
    /**
     * @brief 检查客户端是否已初始化
     */
    bool isInitialized() const { return initialized_; }
    
private:
    OSSConnectionConfig config_;
    bool initialized_ = false;
    std::string lastError_;
    
    // SDK客户端（使用pimpl模式隐藏SDK依赖）
    class Impl;
    std::unique_ptr<Impl> impl_;
    
    void setError(const std::string& error);
};

} // namespace OSS
} // namespace ForensicAnalyzer
