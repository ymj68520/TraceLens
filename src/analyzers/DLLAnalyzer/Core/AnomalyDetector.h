// AnomalyDetector.h
// DLL异常检测器
// 基于PE文件特征的异常检测规则引擎

#pragma once
#ifndef ANOMALY_DETECTOR_H
#define ANOMALY_DETECTOR_H

#include <vector>
#include <unordered_set>
#include "../Common/DLLDataTypes.h"

namespace forensics {
namespace dll {

/**
 * @brief DLL异常检测器
 *
 * 职责：
 *   - 检测PE文件的异常特征（高熵节、可疑导入、RWX权限等）
 *   - 基于规则的威胁评分
 *   - 支持单独调用每个检测规则（便于单元测试）
 */
class AnomalyDetector {
public:
    AnomalyDetector();
    ~AnomalyDetector();

    // 禁止拷贝
    AnomalyDetector(const AnomalyDetector&) = delete;
    AnomalyDetector& operator=(const AnomalyDetector&) = delete;

    /**
     * @brief 检测所有异常
     * @param result DLL分析结果（包含PE头、节表、导入信息等）
     * @return 检测到的异常列表
     */
    std::vector<Anomaly> detect(const DLLAnalysisResult& result);

    /**
     * @brief 检查高熵节（加密/加壳检测）
     * @param sections 节表列表
     * @return 如果.text节熵值>7.5则返回异常，否则返回NONE
     */
    Anomaly checkHighEntropySections(const std::vector<PESectionInfo>& sections);

    /**
     * @brief 检查可疑导入函数
     * @param imports 导入的DLL和函数列表
     * @return 如果包含3个以上可疑函数则返回异常，否则返回NONE
     */
    Anomaly checkSuspiciousImports(const std::vector<ImportedDLL>& imports);

    /**
     * @brief 检查.text节是否同时具有WRITE+EXECUTE权限
     * @param sections 节表列表
     * @return 如果.text节同时可写可执行则返回异常，否则返回NONE
     */
    Anomaly checkWriteExecuteInText(const std::vector<PESectionInfo>& sections);

    /**
     * @brief 检查异常节名
     * @param sections 节表列表
     * @return 如果包含非常见节名则返回异常，否则返回NONE
     */
    Anomaly checkUnusualSectionNames(const std::vector<PESectionInfo>& sections);

    /**
     * @brief 检查入口点异常
     * @param header PE头信息
     * @return 如果入口点不在.text/.code节则返回异常，否则返回NONE
     */
    Anomaly checkEntryPointAnomaly(const PEHeaderInfo& header);

private:
    /**
     * @brief 已知系统DLL白名单
     */
    static const std::unordered_set<std::string> SYSTEM_DLLS;

    /**
     * @brief 加壳工具特征签名
     */
    static const std::unordered_set<std::string> PACKER_SIGNATURES;

    /**
     * @brief 可疑注入函数
     */
    static const std::unordered_set<std::string> INJECTION_FUNCTIONS;

    /**
     * @brief 可疑提权函数
     */
    static const std::unordered_set<std::string> PRIVILEGE_ESCALATION_FUNCTIONS;

    /**
     * @brief 反调试函数
     */
    static const std::unordered_set<std::string> ANTI_DEBUG_FUNCTIONS;

    /**
     * @brief 持久化函数
     */
    static const std::unordered_set<std::string> PERSISTENCE_FUNCTIONS;

    /**
     * @brief 标准节名白名单
     */
    static const std::unordered_set<std::string> STANDARD_SECTION_NAMES;
};

} // namespace dll
} // namespace forensics

#endif // ANOMALY_DETECTOR_H
