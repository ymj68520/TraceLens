/**
 * @file OSSExportTypes.h
 * @brief OSS导出类型枚举定义
 * 
 * 定义阿里云OSS数据获取和分析的不同方式
 */

#pragma once

namespace ForensicAnalyzer {
namespace OSS {

/**
 * @brief OSS数据导出/获取类型
 */
enum class OSSExportType {
    DIRECT_API,       ///< 通过API直接分析（需要网络连接和凭证）
    LOCAL_DIRECTORY,  ///< 分析已下载的本地目录（离线分析）
    INVENTORY_CSV,    ///< 分析OSS Inventory定期生成的清单文件
    ACCESS_LOG        ///< 分析OSS访问日志（审计操作历史）
};

/**
 * @brief OSS认证类型
 */
enum class OSSAuthType {
    ACCESS_KEY,       ///< 使用AK/SK认证（长期凭证）
    STS_TOKEN,        ///< STS临时安全凭证
    ECS_RAM_ROLE,     ///< ECS实例RAM角色（适用于云服务器）
    ANONYMOUS         ///< 匿名访问（仅限公开Bucket）
};

/**
 * @brief OSS存储类型
 */
enum class OSSStorageClass {
    STANDARD,         ///< 标准存储
    IA,               ///< 低频访问存储
    ARCHIVE,          ///< 归档存储
    COLD_ARCHIVE,     ///< 冷归档存储
    DEEP_COLD_ARCHIVE ///< 深度冷归档存储
};

/**
 * @brief 将导出类型转换为字符串
 */
inline const char* toString(OSSExportType type) {
    switch (type) {
        case OSSExportType::DIRECT_API: return "DIRECT_API";
        case OSSExportType::LOCAL_DIRECTORY: return "LOCAL_DIRECTORY";
        case OSSExportType::INVENTORY_CSV: return "INVENTORY_CSV";
        case OSSExportType::ACCESS_LOG: return "ACCESS_LOG";
        default: return "UNKNOWN";
    }
}

/**
 * @brief 将认证类型转换为字符串
 */
inline const char* toString(OSSAuthType type) {
    switch (type) {
        case OSSAuthType::ACCESS_KEY: return "ACCESS_KEY";
        case OSSAuthType::STS_TOKEN: return "STS_TOKEN";
        case OSSAuthType::ECS_RAM_ROLE: return "ECS_RAM_ROLE";
        case OSSAuthType::ANONYMOUS: return "ANONYMOUS";
        default: return "UNKNOWN";
    }
}

/**
 * @brief 将存储类型转换为字符串
 */
inline const char* toString(OSSStorageClass storageClass) {
    switch (storageClass) {
        case OSSStorageClass::STANDARD: return "Standard";
        case OSSStorageClass::IA: return "IA";
        case OSSStorageClass::ARCHIVE: return "Archive";
        case OSSStorageClass::COLD_ARCHIVE: return "ColdArchive";
        case OSSStorageClass::DEEP_COLD_ARCHIVE: return "DeepColdArchive";
        default: return "Unknown";
    }
}

} // namespace OSS
} // namespace ForensicAnalyzer
