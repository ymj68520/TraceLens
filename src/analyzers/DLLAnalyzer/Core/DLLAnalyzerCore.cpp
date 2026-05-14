// DLLAnalyzerCore.cpp
// DLL分析器主类实现

#include "analyzers/DLLAnalyzer/Core/DLLAnalyzer.h"
#include "analyzers/DLLAnalyzer/Core/PEAnalyzer.h"
#include "analyzers/DLLAnalyzer/Core/AnomalyDetector.h"
#include "analyzers/DLLAnalyzer/Core/DependencyAnalyzer.h"
#include "core/Logger/Logger.h"
#include <algorithm>
#include <filesystem>

namespace forensics {
namespace dll {

// ============================================================================
// 构造函数和析构函数
// ============================================================================

DLLAnalyzer::DLLAnalyzer(const std::string& outputDbPath)
    : dllDatabase_(std::make_unique<DLLAnalysisDatabase>(outputDbPath))
    , peAnalyzer_(std::make_unique<PEAnalyzer>())
    , anomalyDetector_(std::make_unique<AnomalyDetector>())
    , dependencyAnalyzer_(std::make_unique<DependencyAnalyzer>())
    , enableAnomalyDetection_(true)
    , enableSignatureVerification_(false)
    , maxFileSize_(100 * 1024 * 1024)
    , stats_{0, 0, 0, 0, 0} {

    LOG_INFO("DLLAnalyzer created with output DB: " + outputDbPath);
}

DLLAnalyzer::~DLLAnalyzer() = default;

// ============================================================================
// 公有方法
// ============================================================================

bool DLLAnalyzer::initialize() {
    LOG_INFO("Initializing DLLAnalyzer...");

    if (!dllDatabase_->initialize()) {
        LOG_ERROR("Failed to initialize DLL analysis database");
        return false;
    }

    LOG_INFO("DLLAnalyzer initialized successfully");
    return true;
}

void DLLAnalyzer::analyze() {
    LOG_INFO("Starting DLL analysis...");

    auto dllFiles = scanDLLFiles();
    LOG_INFO("Found " + std::to_string(dllFiles.size()) + " DLL files to analyze");

    stats_ = {0, 0, 0, 0, 0};

    for (const auto& dllPath : dllFiles) {
        int64_t inode = -1;

        try {
            uint64_t fileSize = std::filesystem::file_size(dllPath);
            if (fileSize > maxFileSize_) {
                LOG_WARNING("Skipping " + dllPath + " (too large)");
                continue;
            }

            std::error_code ec;
            auto status = std::filesystem::status(dllPath, ec);
            if (!ec) {
                inode = static_cast<int64_t>(fileSize) ^ static_cast<int64_t>(
                    std::chrono::duration_cast<std::chrono::seconds>(
                        std::filesystem::last_write_time(dllPath, ec).time_since_epoch()).count());
            }
        } catch (const std::exception& e) {
            LOG_WARNING("Cannot access " + dllPath + ": " + std::string(e.what()));
            continue;
        }

        if (analyzeDLL(dllPath, inode)) {
            stats_.totalDLLsAnalyzed++;
        }
    }

    LOG_INFO("DLL analysis completed. Analyzed " + std::to_string(stats_.totalDLLsAnalyzed) +
             " / " + std::to_string(dllFiles.size()) + " DLLs");
}

// =========================================================================
// 分析选项
// =========================================================================

void DLLAnalyzer::setExtractDirectory(const std::string& dir) {
    extractDirectory_ = dir;
    LOG_DEBUG("Extract directory set to: " + dir);
}

void DLLAnalyzer::setMaxFileSize(size_t maxSize) {
    maxFileSize_ = maxSize;
    LOG_DEBUG("Max file size set to: " + std::to_string(maxSize));
}

void DLLAnalyzer::enableAnomalyDetection(bool enable) {
    enableAnomalyDetection_ = enable;
    LOG_INFO("Anomaly detection " + std::string(enable ? "enabled" : "disabled"));
}

void DLLAnalyzer::enableSignatureVerification(bool enable) {
    enableSignatureVerification_ = enable;
    LOG_INFO("Signature verification " + std::string(enable ? "enabled" : "disabled"));
}

DLLAnalyzer::AnalysisStats DLLAnalyzer::getStats() const {
    return stats_;
}

// =========================================================================
// 私有方法
// =========================================================================

std::vector<std::string> DLLAnalyzer::scanDLLFiles() {
    std::vector<std::string> dllFiles;

    LOG_WARNING("DLL scanning not yet fully implemented - returning empty list");
    // TODO: 实现从文件系统或数据库扫描DLL文件

    return dllFiles;
}

bool DLLAnalyzer::analyzeDLL(const std::string& dllPath, int64_t inode) {
    LOG_DEBUG("Analyzing DLL: " + dllPath);

    try {
        // Step 1: PE分析（元数据提取）
        DLLAnalysisResult result = peAnalyzer_->analyze(dllPath);

        // 填充文件路径和inode
        result.filePath = dllPath;
        result.fileName = std::filesystem::path(dllPath).filename().string();
        result.inode = inode;

        // 如果PE分析失败，跳过
        if (!result.peHeader.isValid) {
            LOG_WARNING("Invalid PE file: " + dllPath);
            return false;
        }

        // Step 2: 异常检测
        if (enableAnomalyDetection_) {
            result.anomalies = anomalyDetector_->detect(result);
            result.threatScore = calculateThreatScore(result);
        }

        // Step 3: 依赖分析（仅在可疑DLL上执行以节省时间）
        if (result.threatScore >= 30) {
            LOG_DEBUG("Running dependency analysis on suspicious DLL: " + dllPath);
            auto depTree = dependencyAnalyzer_->buildDependencyTree(dllPath, 3);
            (void)depTree;
        }

        // Step 4: 数字签名验证（可选，占位实现）
        if (enableSignatureVerification_) {
            result.signatureStatus = "Unsigned";
        }

        // Step 5: 存储到数据库
        int64_t dllId = dllDatabase_->insertDLLBaseInfo(result);
        if (dllId < 0) {
            LOG_ERROR("Failed to insert DLL base info for: " + dllPath);
            return false;
        }

        if (!dllDatabase_->insertSections(dllId, result.peHeader.sections)) {
            LOG_WARNING("Failed to insert sections for: " + dllPath);
        }

        if (!dllDatabase_->insertImports(dllId, result.imports)) {
            LOG_WARNING("Failed to insert imports for: " + dllPath);
        }

        if (!dllDatabase_->insertExports(dllId, result.exports)) {
            LOG_WARNING("Failed to insert exports for: " + dllPath);
        }

        for (const auto& anomaly : result.anomalies) {
            if (!dllDatabase_->insertAnomaly(dllId, anomaly)) {
                LOG_WARNING("Failed to insert anomaly for: " + dllPath);
            }
        }

        dllDatabase_->updateThreatScore(dllId, result.threatScore);

        // 更新统计
        if (result.threatScore >= 30) {
            stats_.suspiciousDLLs++;
        }

        if (result.signatureStatus == "Signed") {
            stats_.signedDLLs++;
        } else if (result.signatureStatus == "Unsigned") {
            stats_.unsignedDLLs++;
        }

        LOG_DEBUG("Successfully analyzed DLL: " + dllPath +
                  " (threat score: " + std::to_string(result.threatScore) + ")");

        return true;

    } catch (const std::exception& e) {
        LOG_ERROR("Exception analyzing DLL " + dllPath + ": " + std::string(e.what()));
        return false;
    }
}

int DLLAnalyzer::calculateThreatScore(const DLLAnalysisResult& result) const {
    int score = 0;

    for (const auto& anomaly : result.anomalies) {
        score += anomaly.riskScore;
    }

    if (result.threatScore > 0) {
        score = std::max(score, result.threatScore);
    }

    if (isSuspiciousDLL(result.filePath)) {
        score += 10;
    }

    return std::min(std::max(score, 0), 100);
}

bool DLLAnalyzer::isSuspiciousDLL(const std::string& dllPath) const {
    std::string lowerPath = dllPath;
    std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(), ::tolower);

    static const std::unordered_set<std::string> suspiciousNames = {
        "inject", "hook", "bypass", "crack", "keygen", "patch",
        "exploit", "shellcode", "backdoor", "rootkit", "trojan"
    };

    std::string filename = std::filesystem::path(dllPath).filename().string();
    std::transform(filename.begin(), filename.end(), filename.begin(), ::tolower);

    for (const auto& suspicious : suspiciousNames) {
        if (filename.find(suspicious) != std::string::npos) {
            return true;
        }
    }

    return false;
}

} // namespace dll
} // namespace forensics
