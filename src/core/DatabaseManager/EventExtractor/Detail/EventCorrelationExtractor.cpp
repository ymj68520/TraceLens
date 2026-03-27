#include "../EventExtractor.h"
#include "DatabaseManager/SQL/event_extractor_sql.h"
#include "AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>
#include <sqlite3.h>
#include <algorithm>

bool EventExtractor::insertEventCorrelation(const EventCorrelation& correlation) {
    using namespace EventExtractorSQL;

    sqlite3_stmt* stmt;
    int rc = sqlite3_prepare_v2(eventDb_, INSERT_EVENT_CORRELATION, -1, &stmt, nullptr);

    if (rc != SQLITE_OK) {
        return false;
    }

    sqlite3_bind_int64(stmt, 1, correlation.eventId1);
    sqlite3_bind_int64(stmt, 2, correlation.eventId2);
    sqlite3_bind_text(stmt, 3, correlation.correlationType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_double(stmt, 4, correlation.confidence);
    sqlite3_bind_text(stmt, 5, correlation.description.c_str(), -1, SQLITE_TRANSIENT);

    rc = sqlite3_step(stmt);
    sqlite3_finalize(stmt);

    return rc == SQLITE_DONE;
}

bool EventExtractor::analyzeEventCorrelations() {
    AuditLog::instance().log("SYSTEM", "EVENT_CORRELATION_START", "Starting event correlation analysis");

    // 创建事件关联规则引擎
    EventCorrelationEngine::EventCorrelationEngine engine(eventDbPath_);

    // 初始化引擎
    if (!engine.initialize()) {
        std::cerr << "Failed to initialize event correlation engine" << std::endl;
        return false;
    }

    // 执行关联分析
    if (!engine.analyzeCorrelations()) {
        std::cerr << "Failed to analyze correlations" << std::endl;
        return false;
    }

    // 执行事件链分析
    auto chains = engine.analyzeEventChains();

    // 发现因果关系
    auto causalRelationships = engine.discoverCausalRelationships();

    // 导出结果
    engine.exportCorrelations(eventDbPath_ + "_correlations.json");
    engine.exportEventChains(eventDbPath_ + "_event_chains.json");
    engine.exportCausalRelationships(eventDbPath_ + "_causal_relationships.json");

    // 生成可视化
    std::string correlationsDot = engine.visualizeCorrelations();
    std::string eventChainsDot = engine.visualizeEventChains();
    std::string causalRelationshipsDot = engine.visualizeCausalRelationships();

    // 保存可视化结果
    std::ofstream corrDotFile(eventDbPath_ + "_correlations.dot");
    corrDotFile << correlationsDot;
    corrDotFile.close();

    std::ofstream chainsDotFile(eventDbPath_ + "_event_chains.dot");
    chainsDotFile << eventChainsDot;
    chainsDotFile.close();

    std::ofstream causalDotFile(eventDbPath_ + "_causal_relationships.dot");
    causalDotFile << causalRelationshipsDot;
    causalDotFile.close();

    AuditLog::instance().log("SYSTEM", "EVENT_CORRELATION_COMPLETE", "Event correlation analysis completed");
    return true;
}

// 检测是否为安全事件
bool EventExtractor::isSecurityEvent(const TimelineEvent& event) {
    // 检查事件类型
    if (event.eventType.find("SECURITY") != std::string::npos) return true;
    if (event.eventType.find("AUTH") != std::string::npos) return true;
    if (event.eventType.find("LOGIN") != std::string::npos) return true;
    if (event.eventType.find("FAIL") != std::string::npos) return true;

    // 检查描述内容
    std::string desc = event.description;
    if (desc.find("security") != std::string::npos) return true;
    if (desc.find("authentication") != std::string::npos) return true;
    if (desc.find("password") != std::string::npos) return true;
    if (desc.find("access denied") != std::string::npos) return true;
    if (desc.find("privilege") != std::string::npos) return true;

    return false;
}

// 检测是否为可疑活动
bool EventExtractor::isSuspiciousActivity(const TimelineEvent& event) {
    // 检查文件路径
    std::string path = event.filePath;
    if (path.find("/tmp/") != std::string::npos) return true;
    if (path.find("/var/tmp/") != std::string::npos) return true;
    if (path.find("/proc/") != std::string::npos) return true;
    if (path.find("/sys/") != std::string::npos) return true;

    // 检查文件类型
    std::string type = event.fileType;
    if (type == "executable") return true;
    if (type == "script") return true;

    // 检查描述内容
    std::string desc = event.description;
    if (desc.find("error") != std::string::npos) return true;
    if (desc.find("fail") != std::string::npos) return true;
    if (desc.find("warning") != std::string::npos) return true;
    if (desc.find("suspicious") != std::string::npos) return true;

    return false;
}

// 分类事件
EventCategory EventExtractor::classifyEvent(const TimelineEvent& event) {
    // 基于事件类型分类
    if (event.eventType == "CREATED" || event.eventType == "MODIFIED" ||
        event.eventType == "ACCESSED" || event.eventType == "CHANGED" ||
        event.eventType == "DELETED") {
        return EventCategory::FILE_OPERATION;
    }

    // 基于来源分类
    if (event.source == EventSource::SYSTEM) {
        return EventCategory::SYSTEM_ACTIVITY;
    }

    if (event.source == EventSource::NETWORK) {
        return EventCategory::NETWORK_ACTIVITY;
    }

    if (event.source == EventSource::SECURITY) {
        return EventCategory::SECURITY_EVENT;
    }

    if (event.source == EventSource::APPLICATION) {
        return EventCategory::APPLICATION_EVENT;
    }

    if (event.eventType.find("LOGIN") != std::string::npos ||
        event.eventType.find("USER") != std::string::npos) {
        return EventCategory::USER_ACTIVITY;
    }

    return EventCategory::UNKNOWN_CATEGORY;
}

// 评估事件优先级
EventPriority EventExtractor::assessPriority(const TimelineEvent& event) {
    // 基于事件类型
    if (event.eventType == "DELETED") return EventPriority::HIGH;
    if (event.eventType.find("SECURITY") != std::string::npos) return EventPriority::CRITICAL;
    if (event.eventType.find("ERROR") != std::string::npos) return EventPriority::HIGH;
    if (event.eventType.find("WARNING") != std::string::npos) return EventPriority::MEDIUM;

    // 基于文件类型
    if (event.fileType == "executable") return EventPriority::HIGH;
    if (event.fileType == "database") return EventPriority::MEDIUM;
    if (event.fileType == "system") return EventPriority::HIGH;

    // 基于文件大小
    if (event.fileSize > 100 * 1024 * 1024) return EventPriority::MEDIUM; // 大于100MB

    // 基于来源
    if (event.source == EventSource::SECURITY) return EventPriority::CRITICAL;
    if (event.source == EventSource::NETWORK) return EventPriority::MEDIUM;

    // 基于可疑活动
    if (isSuspiciousActivity(event)) return EventPriority::HIGH;

    return EventPriority::LOW;
}

// 评估事件严重程度
EventSeverity EventExtractor::assessSeverity(const TimelineEvent& event) {
    // 基于事件类型
    if (event.eventType.find("ERROR") != std::string::npos) return EventSeverity::ERROR;
    if (event.eventType.find("CRITICAL") != std::string::npos) return EventSeverity::CRITICAL;
    if (event.eventType.find("WARNING") != std::string::npos) return EventSeverity::WARNING;

    // 基于安全事件
    if (isSecurityEvent(event)) return EventSeverity::CRITICAL;

    // 基于可疑活动
    if (isSuspiciousActivity(event)) return EventSeverity::WARNING;

    // 基于文件类型
    if (event.fileType == "executable" && event.eventType == "CREATED") return EventSeverity::WARNING;
    if (event.fileType == "system" && event.eventType == "DELETED") return EventSeverity::ERROR;

    return EventSeverity::INFO;
}

// 识别事件来源
EventSource EventExtractor::identifySource(const TimelineEvent& event) {
    // 基于事件类型识别
    if (event.eventType == "CREATED" || event.eventType == "MODIFIED" ||
        event.eventType == "ACCESSED" || event.eventType == "CHANGED" ||
        event.eventType == "DELETED" || event.eventType == "FILE_DELETED") {
        return EventSource::FILE_SYSTEM;
    }

    if (event.eventType.find("WIN_LOG_") == 0 ||
        event.eventType == "WINDOWS_SERVICE" ||
        event.eventType == "SCHEDULED_TASK" ||
        event.eventType == "PREFETCH_EXECUTION" ||
        event.eventType == "AMCACHE_ENTRY") {
        return EventSource::WINDOWS_EVENT_LOG;
    }

    if (event.eventType == "WEB_HISTORY" ||
        event.eventType == "WEB_DOWNLOAD" ||
        event.eventType == "WEB_LOGIN") {
        return EventSource::WEB_BROWSER;
    }

    if (event.eventType == "LINUX_SYSLOG" ||
        event.eventType == "LOGIN_SUCCESS" ||
        event.eventType == "LOGIN_FAILURE" ||
        event.eventType == "SHELL_COMMAND" ||
        event.eventType == "CRON_JOB" ||
        event.eventType == "SSH_KEY" ||
        event.eventType == "PACKAGE_INSTALL" ||
        event.eventType == "SYSTEMD_SERVICE" ||
        event.eventType == "AUDIT_LOG") {
        return EventSource::LINUX_SYSLOG;
    }

    if (event.eventType == "ANDROID_LOG") {
        return EventSource::ANDROID_LOG;
    }

    if (event.eventType == "SYSTEM_START" || event.eventType == "SERVICE_START") {
        return EventSource::SYSTEM;
    }

    if (event.eventType == "NETWORK_CONNECT") {
        return EventSource::NETWORK;
    }

    if (event.eventType == "SECURITY_EVENT" || event.eventType == "WEB_LOGIN" ||
        event.eventType == "SSH_KEY" || event.eventType == "AUDIT_LOG") {
        return EventSource::SECURITY;
    }

    if (event.eventType == "PROCESS_CREATE" || event.eventType == "PREFETCH_EXECUTION" ||
        event.eventType == "SHELL_COMMAND") {
        return EventSource::APPLICATION;
    }

    if (event.eventType == "USB_DEVICE_CONNECT") {
        return EventSource::SYSTEM;
    }

    return EventSource::UNKNOWN;
}

// 标准化事件类型
std::string EventExtractor::normalizeEventType(const std::string& eventType) {
    // 标准化文件系统事件
    if (eventType == "CREATED") return "FILE_CREATED";
    if (eventType == "MODIFIED") return "FILE_MODIFIED";
    if (eventType == "ACCESSED") return "FILE_ACCESSED";
    if (eventType == "CHANGED") return "FILE_METADATA_CHANGED";
    if (eventType == "DELETED") return "FILE_DELETED";
    if (eventType == "FILE_DELETED") return "FILE_DELETED";

    // 标准化Windows事件
    if (eventType.find("WIN_LOG_") == 0) return "WINDOWS_EVENT";
    if (eventType == "WEB_HISTORY") return "WEB_BROWSER_ACTIVITY";
    if (eventType == "WEB_DOWNLOAD") return "WEB_BROWSER_DOWNLOAD";
    if (eventType == "WEB_LOGIN") return "WEB_BROWSER_LOGIN";
    if (eventType == "WINDOWS_SERVICE") return "WINDOWS_SERVICE";
    if (eventType == "SCHEDULED_TASK") return "SCHEDULED_TASK";
    if (eventType == "PREFETCH_EXECUTION") return "PROCESS_EXECUTION";
    if (eventType == "USB_DEVICE_CONNECT") return "HARDWARE_CONNECTION";
    if (eventType == "AMCACHE_ENTRY") return "FILE_METADATA";

    // 标准化Linux事件
    if (eventType == "LINUX_SYSLOG") return "LINUX_SYSTEM_LOG";
    if (eventType == "LOGIN_SUCCESS") return "USER_LOGIN_SUCCESS";
    if (eventType == "LOGIN_FAILURE") return "USER_LOGIN_FAILURE";
    if (eventType == "SHELL_COMMAND") return "SHELL_EXECUTION";
    if (eventType == "CRON_JOB") return "SCHEDULED_TASK";
    if (eventType == "SSH_KEY") return "SECURITY_KEY";
    if (eventType == "PACKAGE_INSTALL") return "SOFTWARE_INSTALL";
    if (eventType == "NETWORK_CONNECTION") return "NETWORK_CONNECTION";
    if (eventType == "SYSTEMD_SERVICE") return "SYSTEM_SERVICE";
    if (eventType == "AUDIT_LOG") return "SECURITY_AUDIT";

    // 标准化Android事件
    if (eventType == "ANDROID_LOG") return "ANDROID_SYSTEM_LOG";

    // 标准化系统事件
    if (eventType == "SYSTEM_START") return "SYSTEM_STARTUP";
    if (eventType == "LOGIN") return "USER_LOGIN";
    if (eventType == "PROCESS_CREATE") return "PROCESS_CREATED";
    if (eventType == "SECURITY_EVENT") return "SECURITY_ALERT";
    if (eventType == "SERVICE_START") return "SERVICE_STARTED";

    return "UNKNOWN_EVENT";
}

// 获取事件来源ID
std::string EventExtractor::getSourceId(const TimelineEvent& event) {
    // 基于事件类型和文件路径生成唯一ID
    if (event.source == EventSource::FILE_SYSTEM) {
        return "FS_" + std::to_string(event.inode);
    } else if (event.source == EventSource::WINDOWS_EVENT_LOG) {
        return "WIN_LOG_" + event.eventType;
    } else if (event.source == EventSource::LINUX_SYSLOG) {
        return "LINUX_LOG_" + event.eventType;
    } else if (event.source == EventSource::ANDROID_LOG) {
        return "ANDROID_LOG_" + event.eventType;
    } else if (event.source == EventSource::WEB_BROWSER) {
        return "WEB_" + event.filePath.substr(0, 32);
    } else {
        return "SYS_" + event.eventType;
    }
}
