// DLLAnalyzerCore.cpp
// DLL分析器主类实现

#include "analyzers/DLLAnalyzer/Core/DLLAnalyzer.h"
#include "analyzers/DLLAnalyzer/Core/PEAnalyzer.h"
#include "analyzers/DLLAnalyzer/Core/AnomalyDetector.h"
#include "analyzers/DLLAnalyzer/Core/DependencyAnalyzer.h"
#include "core/Logger/Logger.h"
#include "core/ThreadPool/ThreadPool.h"
#include <algorithm>
#include <filesystem>
#include <mutex>

namespace forensics {
namespace dll {

// ============================================================================
// 静态成员初始化
// ============================================================================

const std::unordered_set<std::string> DLLAnalyzer::SYSTEM_DLL_NAMES_ = {
    "kernel32.dll", "kernelbase.dll", "ntdll.dll", "user32.dll", "gdi32.dll",
    "advapi32.dll", "ws2_32.dll", "wininet.dll", "ole32.dll", "oleaut32.dll",
    "libc.so.6", "libdl.so.2", "libpthread.so.0", "libm.so.6"
};

const std::unordered_set<std::string> DLLAnalyzer::SYSTEM_DIRECTORIES_ = {
    "/usr/lib", "/usr/lib64", "/lib", "/lib64",
    "c:\\windows\\system32", "c:\\windows\\syswow64"
};

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

    // 性能优化：并行分析DLL文件
    // 根据CPU核心数调整线程数，避免过度并行
    const size_t numThreads = std::min(
        static_cast<size_t>(std::thread::hardware_concurrency()),
        static_cast<size_t>(8)
    );

    if (dllFiles.size() > 1) {
        LOG_INFO("Using parallel analysis with " + std::to_string(numThreads) + " threads");

        forensics::ThreadPool pool(numThreads);
        std::vector<std::future<bool>> futures;
        futures.reserve(dllFiles.size());

        for (const auto& dllPath : dllFiles) {
            futures.emplace_back(
                pool.enqueue([this, &dllPath]() {
                    int64_t inode = -1;

                    try {
                        uint64_t fileSize = std::filesystem::file_size(dllPath);
                        if (fileSize > maxFileSize_) {
                            LOG_WARNING("Skipping " + dllPath + " (too large)");
                            return false;
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
                        return false;
                    }

                    bool success = analyzeDLL(dllPath, inode);

                    // 原子更新统计信息
                    if (success) {
                        std::lock_guard<std::mutex> lock(statsMutex_);
                        stats_.totalDLLsAnalyzed++;
                    }

                    return success;
                })
            );
        }

        // 等待所有任务完成
        size_t successCount = 0;
        for (auto& future : futures) {
            try {
                if (future.get()) {
                    successCount++;
                }
            } catch (const std::exception& e) {
                LOG_WARNING("DLL analysis task failed: " + std::string(e.what()));
            }
        }

        LOG_INFO("Parallel analysis completed. Successfully analyzed " +
                 std::to_string(successCount) + " / " + std::to_string(dllFiles.size()) + " DLLs");

        LOG_INFO("Using sequential analysis (small file set or single thread)");

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

        LOG_INFO("Sequential analysis completed. Analyzed " +
                 std::to_string(stats_.totalDLLsAnalyzed) + " / " +
                 std::to_string(dllFiles.size()) + " DLLs");
    }
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

/**
 * @brief 检查DLL是否在白名单中（已知安全）
 */
bool DLLAnalyzer::isWhitelistedDLL(const std::string& dllPath) const {
    std::string filename = std::filesystem::path(dllPath).filename().string();
    std::transform(filename.begin(), filename.end(), filename.begin(), ::tolower);

    // 检查文件名白名单
    if (SYSTEM_DLL_NAMES_.find(filename) != SYSTEM_DLL_NAMES_.cend()) {
        return true;
    }

    // 检查目录白名单
    std::string lowerPath = dllPath;
    std::transform(lowerPath.begin(), lowerPath.end(), lowerPath.begin(), ::tolower);

    for (const auto& sysDir : SYSTEM_DIRECTORIES_) {
        if (lowerPath.find(sysDir) == 0) {
            return true;
        }
    }

    return false;
}

/**
 * @brief 扫描单个目录中的DLL文件
 */
std::vector<std::string> DLLAnalyzer::scanDirectoryParallel(const std::string& dirPath) {
    std::vector<std::string> dllFiles;

    try {
        // 常见DLL扩展名
        static const std::vector<std::string> dllExtensions = {
            ".dll", ".DLL", ".so", ".so.1", ".so.2", ".so.3",
            ".ocx", ".cpl", ".sys", ".drv"
        };

        // 遍历目录
        for (const auto& entry : std::filesystem::recursive_directory_iterator(
             dirPath, std::filesystem::directory_options::skip_permission_denied)) {

            if (!entry.is_regular_file()) {
                continue;
            }

            std::string path = entry.path().string();
            std::string ext = entry.path().extension().string();

            // 检查扩展名
            bool isDLL = false;
            for (const auto& dllExt : dllExtensions) {
                if (ext == dllExt) {
                    isDLL = true;
                    break;
                }
            }

            if (!isDLL) {
                continue;
            }

            // 跳过白名单DLL
            if (isWhitelistedDLL(path)) {
                LOG_DEBUG("Skipping whitelisted DLL: " + path);
                continue;
            }

            dllFiles.push_back(path);
        }

    } catch (const std::exception& e) {
        LOG_WARNING("Error scanning directory " + dirPath + ": " + std::string(e.what()));
    }

    return dllFiles;
}

/**
 * @brief 扫描DLL文件（支持多目录并行扫描）
 */
std::vector<std::string> DLLAnalyzer::scanDLLFiles() {
    LOG_INFO("Scanning for DLL files...");

    std::vector<std::string> dllFiles;

    // TODO: 从WindowsFilesAnalyzer获取已提取的DLL列表
    // 或从FileClassifier结果中获取EXECUTABLE类型的文件
    // 当前版本扫描常见Windows系统目录

    // Windows系统目录（如果存在）
    #ifdef _WIN32
    const char* windir = std::getenv("WINDIR");
    if (windir) {
        std::string system32 = std::string(windir) + "\\System32";
        std::string syswow64 = std::string(windir) + "\\SysWOW64";

        if (std::filesystem::exists(system32)) {
            LOG_INFO("Scanning " + system32 + "...");
            auto systemDLLs = scanDirectoryParallel(system32);
            dllFiles.insert(dllFiles.end(), systemDLLs.begin(), systemDLLs.end());
        }

        if (std::filesystem::exists(syswow64)) {
            LOG_INFO("Scanning " + syswow64 + "...");
            auto wow64DLLs = scanDirectoryParallel(syswow64);
            dllFiles.insert(dllFiles.end(), wow64DLLs.begin(), wow64DLLs.end());
        }
    }
    #endif

    // Linux系统目录
    #ifndef _WIN32
    const std::vector<std::string> linuxLibDirs = {
        "/usr/lib", "/usr/lib64", "/lib", "/lib64",
        "/usr/local/lib", "/usr/local/lib64"
    };

    // 并行扫描（最多4个线程）
    const size_t maxScanThreads = 4;
    forensics::ThreadPool pool(maxScanThreads);
    std::vector<std::future<std::vector<std::string>>> futures;

    for (const auto& libDir : linuxLibDirs) {
        if (std::filesystem::exists(libDir)) {
            LOG_INFO("Scanning " + libDir + "...");
            futures.emplace_back(
                pool.enqueue([this, libDir](const std::string& dir) {
                    return scanDirectoryParallel(dir);
                }, libDir)
            );
        }
    }

    // 收集结果
    for (auto& future : futures) {
        try {
            auto result = future.get();
            dllFiles.insert(dllFiles.end(), result.begin(), result.end());
        } catch (const std::exception& e) {
            LOG_WARNING("Failed to get scan result: " + std::string(e.what()));
        }
    }
    #endif

    LOG_INFO("Found " + std::to_string(dllFiles.size()) + " DLL files");
    return dllFiles;
}

bool DLLAnalyzer::isAlreadyAnalyzed(const std::string& dllPath, int64_t inode) const {
    // 首先通过路径检查
    auto existingByPath = dllDatabase_->getDLLByPath(dllPath);
    if (existingByPath) {
        return true;
    }

    // 如果inode有效，也通过inode检查
    if (inode > 0) {
        auto existingByInode = dllDatabase_->getDLLByInode(inode);
        if (existingByInode) {
            return true;
        }
    }

    return false;
}

bool DLLAnalyzer::analyzeDLL(const std::string& dllPath, int64_t inode) {
    LOG_DEBUG("Analyzing DLL: " + dllPath);

    // 增量分析：跳过已分析的DLL
    if (isAlreadyAnalyzed(dllPath, inode)) {
        LOG_DEBUG("Skipping already analyzed DLL: " + dllPath);
        return false;
    }

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
