#pragma once
#ifndef EVENT_EXTRACTOR_H
#define EVENT_EXTRACTOR_H

#include <string>
#include <sqlite3.h>
#include <memory>
#include <vector>
#include <fstream>
#include "EventCorrelationEngine/EventCorrelationEngine.h"

// 事件优先级枚举
enum class EventPriority {
    LOW,
    MEDIUM,
    HIGH,
    CRITICAL
};

// 事件严重程度枚举
enum class EventSeverity {
    INFO,
    WARNING,
    ERROR,
    CRITICAL
};

// 事件来源枚举
enum class EventSource {
    FILE_SYSTEM,
    WINDOWS_EVENT_LOG,
    LINUX_SYSLOG,
    ANDROID_LOG,
    WEB_BROWSER,
    SYSTEM,
    NETWORK,
    SECURITY,
    APPLICATION,
    UNKNOWN
};

// 事件类别枚举
enum class EventCategory {
    FILE_OPERATION,        // 文件操作（创建、修改、访问、删除）
    SYSTEM_ACTIVITY,       // 系统活动（启动、关闭、服务）
    USER_ACTIVITY,         // 用户活动（登录、注销、权限变更）
    NETWORK_ACTIVITY,      // 网络活动（连接、断开、流量）
    SECURITY_EVENT,        // 安全事件（认证失败、权限提升）
    APPLICATION_EVENT,     // 应用程序事件（启动、错误、崩溃）
    DATABASE_ACTIVITY,     // 数据库活动（查询、更新、备份）
    HARDWARE_EVENT,        // 硬件事件（设备连接、故障）
    EXTERNAL_SOURCE,       // 外部来源事件
    UNKNOWN_CATEGORY
};

struct TimelineEvent {
	int64_t timestamp;
	std::string eventType;  // CREATED, MODIFIED, ACCESSED, CHANGED, DELETED
	std::string filePath;
	int64_t inode;
	std::string description;
	int64_t fileSize;
	std::string fileType;
	std::string systemContext;
	EventPriority priority;     // 事件优先级
	EventSeverity severity;     // 事件严重程度
	EventSource source;         // 事件来源
	EventCategory category;     // 事件类别
	std::string normalizedType; // 标准化事件类型
	std::string sourceId;       // 事件来源ID
};

struct SystemEvent {
	int64_t timestamp;
	std::string eventType;  // SYSTEM_START, LOGIN, PROCESS_CREATE, NETWORK_CONNECT, SECURITY_EVENT, SERVICE_START
	std::string source;
	std::string user;
	std::string process;
	std::string ipAddress;
	int port;
	std::string service;
	std::string description;
	std::string severity;
	std::string systemContext;
};

struct EventCorrelation {
	int64_t eventId1;
	int64_t eventId2;
	std::string correlationType;  // same_user, same_time, same_process, same_ip, same_file
	double confidence;
	std::string description;
};

class EventExtractor {
public:
	explicit EventExtractor(const std::string& sourceDbPath,
		const std::string& eventDbPath);
	~EventExtractor();

	bool extractEvents();

    bool importWindowsArtifacts(const std::string& windowsDbPath);
    bool importLinuxArtifacts(const std::string& linuxDbPath);
    bool importAndroidArtifacts(const std::string& androidDbPath);

    // Scene-aware: import artifacts from unified files.db
    bool importSceneArtifacts(const std::string& fileDbPath, const std::string& sceneType);
    
    // System event methods
    bool insertSystemEvent(const SystemEvent& event);
    bool extractSystemEvents();
    
    // Event correlation methods
    bool insertEventCorrelation(const EventCorrelation& correlation);
    bool analyzeEventCorrelations();
    
    // Event standardization methods
    bool standardizeEvents();
    TimelineEvent standardizeEvent(const TimelineEvent& event);
    
    // Event classification methods
    EventCategory classifyEvent(const TimelineEvent& event);
    
    // Event priority and severity assessment
    EventPriority assessPriority(const TimelineEvent& event);
    EventSeverity assessSeverity(const TimelineEvent& event);
    
    // Event source identification
    EventSource identifySource(const TimelineEvent& event);

private:
	std::string sourceDbPath_;
	std::string eventDbPath_;
	sqlite3* sourceDb_;
	sqlite3* eventDb_;

	bool openDatabases();
	bool createEventTables();
	bool extractFileSystemEvents();
	bool insertEvent(const TimelineEvent& event);
	void closeDatabases();
	
	// Helper methods for event processing
	std::string normalizeEventType(const std::string& eventType);
	std::string getSourceId(const TimelineEvent& event);
	bool isSecurityEvent(const TimelineEvent& event);
	bool isSuspiciousActivity(const TimelineEvent& event);

	// Scene-aware: import helpers for unified files.db
	bool importAndroidArtifactsFromFilesDb(const std::string& fileDbPath);
	bool importWindowsArtifactsFromFilesDb(const std::string& fileDbPath);
	bool importLinuxArtifactsFromFilesDb(const std::string& fileDbPath);
};

#endif // EVENT_EXTRACTOR_H
