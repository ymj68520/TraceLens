#pragma once

#include <crow.h>
#include <nlohmann/json.hpp>
#include "../TaskManager.h"
#include "OSSAnalyzer/OSSAnalyzer.h"
#include <mutex>
#include <unordered_map>
#include <thread>

namespace forensics {

/**
 * @brief OSS分析任务状态
 */
enum class OSSAnalysisStatus {
    PENDING,
    RUNNING,
    COMPLETED,
    FAILED
};

/**
 * @brief OSS分析任务信息
 */
struct OSSAnalysisJob {
    std::string id;
    std::string task_id;
    ForensicAnalyzer::OSS::OSSExportType export_type;
    std::string source_path;  // 本地目录或配置文件路径
    OSSAnalysisStatus status = OSSAnalysisStatus::PENDING;
    std::string error_message;
    int64_t objects_analyzed = 0;
    int64_t logs_analyzed = 0;
    std::chrono::system_clock::time_point created_time;
    std::chrono::system_clock::time_point completed_time;
};

/**
 * @brief OSS分析路由处理器
 * 处理: /api/forensics/oss/*
 */
class OSSRoutes {
public:
    explicit OSSRoutes(crow::App<>& app);
    
private:
    TaskManager& task_manager_;
    
    // 分析任务跟踪
    std::unordered_map<std::string, OSSAnalysisJob> analysis_jobs_;
    std::mutex jobs_mutex_;
    
    // ========== API端点处理器 ==========
    
    /**
     * @brief 启动OSS分析任务
     * POST /api/forensics/oss/analyze
     */
    crow::response handle_analyze_start(const crow::request& req);
    
    /**
     * @brief 获取分析任务状态
     * GET /api/forensics/oss/analyze/status?job_id=xxx
     */
    crow::response handle_analyze_status(const crow::request& req);
    
    /**
     * @brief 获取OSS对象列表
     * GET /api/forensics/oss/objects?task_id=xxx
     */
    crow::response handle_get_objects(const crow::request& req);
    
    /**
     * @brief 获取OSS访问日志
     * GET /api/forensics/oss/logs?task_id=xxx
     */
    crow::response handle_get_access_logs(const crow::request& req);
    
    /**
     * @brief 获取OSS分析摘要
     * GET /api/forensics/oss/summary?task_id=xxx
     */
    crow::response handle_get_summary(const crow::request& req);
    
    /**
     * @brief 按存储类型统计对象
     * GET /api/forensics/oss/statistics/storage-class?task_id=xxx
     */
    crow::response handle_storage_class_stats(const crow::request& req);
    
    /**
     * @brief 按扩展名统计对象
     * GET /api/forensics/oss/statistics/extensions?task_id=xxx
     */
    crow::response handle_extension_stats(const crow::request& req);
    
    /**
     * @brief 获取Bucket信息列表
     * GET /api/forensics/oss/buckets?task_id=xxx
     */
    crow::response handle_get_buckets(const crow::request& req);
    
    // ========== 工作线程 ==========
    
    void run_analysis_job(const std::string& job_id);
    
    // ========== 辅助方法 ==========
    
    std::string get_oss_database_path(const std::string& task_id);
    static void add_cors_headers(crow::response& res);
    static std::string generate_job_id();
};

} // namespace forensics
