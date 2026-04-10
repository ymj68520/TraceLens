// LinuxEnhancedOperations.cpp
// Database operations for containers, web servers, security, and enhanced analysis

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include <nlohmann/json.hpp>
#include <iostream>
#include <sstream>
#include <mutex>

using namespace LinuxAnalysis;
using json = nlohmann::json;

// Helper macros for binding
#define BIND_TEXT(stmt, index, text) \
    sqlite3_bind_text(stmt, index, text.c_str(), -1, SQLITE_TRANSIENT)

#define BIND_INT64(stmt, index, val) \
    sqlite3_bind_int64(stmt, index, val)

#define BIND_INT(stmt, index, val) \
    sqlite3_bind_int(stmt, index, val)

#define BIND_DOUBLE(stmt, index, val) \
    sqlite3_bind_double(stmt, index, val)

// RAII wrapper for sqlite3_stmt
class StmtGuard {
public:
    explicit StmtGuard(sqlite3_stmt* stmt) : stmt_(stmt) {}
    ~StmtGuard() { if (stmt_) sqlite3_finalize(stmt_); }
    operator sqlite3_stmt*() const { return stmt_; }
    sqlite3_stmt* get() const { return stmt_; }
private:
    sqlite3_stmt* stmt_;
};

// Helper function to convert vector<string> to JSON string
template<typename T>
std::string vectorToJson(const std::vector<T>& vec) {
    try {
        json j = vec;
        return j.dump();
    } catch (const std::exception& e) {
        std::cerr << "JSON serialization error: " << e.what() << std::endl;
        return "[]";
    }
}

// Helper function to parse JSON string to vector<string>
template<typename T>
std::vector<T> jsonToVector(const std::string& jsonStr) {
    try {
        if (jsonStr.empty()) return {};
        json j = json::parse(jsonStr);
        return j.get<std::vector<T>>();
    } catch (const std::exception& e) {
        std::cerr << "JSON parsing error: " << e.what() << std::endl;
        return {};
    }
}

// Helper function to safely get text from SQLite column
inline const char* safeColumnText(sqlite3_stmt* stmt, int col) {
    const unsigned char* text = sqlite3_column_text(stmt, col);
    return text ? reinterpret_cast<const char*>(text) : "";
}

// ============================================================================
// Docker Container Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertDockerContainer(const DockerContainerInfo& container) {
    const char* sql = LinuxAnalysisSQL::INSERT_DOCKER_CONTAINER;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, container.containerId);
    BIND_TEXT(stmt, 2, container.imageName);
    BIND_TEXT(stmt, 3, container.imageTag);
    BIND_TEXT(stmt, 4, container.command);
    BIND_INT64(stmt, 5, container.createdAt);
    BIND_TEXT(stmt, 6, container.state);
    BIND_TEXT(stmt, 7, vectorToJson(container.mounts));
    BIND_TEXT(stmt, 8, vectorToJson(container.ports));
    BIND_TEXT(stmt, 9, container.networkMode);
    BIND_TEXT(stmt, 10, container.hostConfig);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertDockerContainers(const std::vector<DockerContainerInfo>& containers) {
    beginTransaction();
    for (const auto& container : containers) {
        if (!insertDockerContainer(container)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<DockerContainerInfo> LinuxAnalysisDatabase::queryDockerContainers(const std::string& whereClause) {
    std::vector<DockerContainerInfo> containers;
    std::string sql = "SELECT container_id, image_name, image_tag, command, created_at, state, mounts, ports, network_mode, host_config FROM linux_docker_containers";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return containers;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DockerContainerInfo container;
        container.containerId = safeColumnText(stmt, 0);
        container.imageName = safeColumnText(stmt, 1);
        container.imageTag = safeColumnText(stmt, 2);
        container.command = safeColumnText(stmt, 3);
        container.createdAt = sqlite3_column_int64(stmt, 4);
        container.state = safeColumnText(stmt, 5);
        container.mounts = jsonToVector<std::string>(safeColumnText(stmt, 6));
        container.ports = jsonToVector<std::string>(safeColumnText(stmt, 7));
        container.networkMode = safeColumnText(stmt, 8);
        container.hostConfig = safeColumnText(stmt, 9);
        containers.push_back(container);
    }

    return containers;
}

std::vector<DockerContainerInfo> LinuxAnalysisDatabase::queryDockerContainersSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<DockerContainerInfo> containers;

    std::string sql = "SELECT container_id, image_name, image_tag, command, created_at, state, mounts, ports, network_mode, host_config FROM linux_docker_containers";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return containers;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return containers;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DockerContainerInfo container;
        container.containerId = safeColumnText(stmt, 0);
        container.imageName = safeColumnText(stmt, 1);
        container.imageTag = safeColumnText(stmt, 2);
        container.command = safeColumnText(stmt, 3);
        container.createdAt = sqlite3_column_int64(stmt, 4);
        container.state = safeColumnText(stmt, 5);
        container.mounts = jsonToVector<std::string>(safeColumnText(stmt, 6));
        container.ports = jsonToVector<std::string>(safeColumnText(stmt, 7));
        container.networkMode = safeColumnText(stmt, 8);
        container.hostConfig = safeColumnText(stmt, 9);
        containers.push_back(container);
    }

    return containers;
}

// ============================================================================
// Docker Image Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertDockerImage(const DockerImageInfo& image) {
    const char* sql = LinuxAnalysisSQL::INSERT_DOCKER_IMAGE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, image.imageId);
    BIND_TEXT(stmt, 2, vectorToJson(image.tags));
    BIND_INT64(stmt, 3, image.size);
    BIND_INT64(stmt, 4, image.createdAt);
    BIND_TEXT(stmt, 5, vectorToJson(image.layerIds));

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertDockerImages(const std::vector<DockerImageInfo>& images) {
    beginTransaction();
    for (const auto& image : images) {
        if (!insertDockerImage(image)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<DockerImageInfo> LinuxAnalysisDatabase::queryDockerImages(const std::string& whereClause) {
    std::vector<DockerImageInfo> images;
    std::string sql = "SELECT image_id, tags, size, created_at, layer_ids FROM linux_docker_images";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return images;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DockerImageInfo image;
        image.imageId = safeColumnText(stmt, 0);
        image.tags = jsonToVector<std::string>(safeColumnText(stmt, 1));
        image.size = sqlite3_column_int64(stmt, 2);
        image.createdAt = sqlite3_column_int64(stmt, 3);
        image.layerIds = jsonToVector<std::string>(safeColumnText(stmt, 4));
        images.push_back(image);
    }

    return images;
}

std::vector<DockerImageInfo> LinuxAnalysisDatabase::queryDockerImagesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<DockerImageInfo> images;

    std::string sql = "SELECT image_id, tags, size, created_at, layer_ids FROM linux_docker_images";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return images;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return images;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DockerImageInfo image;
        image.imageId = safeColumnText(stmt, 0);
        image.tags = jsonToVector<std::string>(safeColumnText(stmt, 1));
        image.size = sqlite3_column_int64(stmt, 2);
        image.createdAt = sqlite3_column_int64(stmt, 3);
        image.layerIds = jsonToVector<std::string>(safeColumnText(stmt, 4));
        images.push_back(image);
    }

    return images;
}

// ============================================================================
// Docker Volume Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertDockerVolume(const DockerVolumeInfo& volume) {
    const char* sql = LinuxAnalysisSQL::INSERT_DOCKER_VOLUME;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, volume.volumeName);
    BIND_TEXT(stmt, 2, volume.mountpoint);
    BIND_TEXT(stmt, 3, volume.driver);
    BIND_INT64(stmt, 4, volume.createdAt);
    BIND_TEXT(stmt, 5, vectorToJson(volume.containerIds));

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertDockerVolumes(const std::vector<DockerVolumeInfo>& volumes) {
    beginTransaction();
    for (const auto& volume : volumes) {
        if (!insertDockerVolume(volume)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<DockerVolumeInfo> LinuxAnalysisDatabase::queryDockerVolumes(const std::string& whereClause) {
    std::vector<DockerVolumeInfo> volumes;
    std::string sql = "SELECT volume_name, mountpoint, driver, created_at, container_ids FROM linux_docker_volumes";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return volumes;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DockerVolumeInfo volume;
        volume.volumeName = safeColumnText(stmt, 0);
        volume.mountpoint = safeColumnText(stmt, 1);
        volume.driver = safeColumnText(stmt, 2);
        volume.createdAt = sqlite3_column_int64(stmt, 3);
        volume.containerIds = jsonToVector<std::string>(safeColumnText(stmt, 4));
        volumes.push_back(volume);
    }

    return volumes;
}

std::vector<DockerVolumeInfo> LinuxAnalysisDatabase::queryDockerVolumesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<DockerVolumeInfo> volumes;

    std::string sql = "SELECT volume_name, mountpoint, driver, created_at, container_ids FROM linux_docker_volumes";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return volumes;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return volumes;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        DockerVolumeInfo volume;
        volume.volumeName = safeColumnText(stmt, 0);
        volume.mountpoint = safeColumnText(stmt, 1);
        volume.driver = safeColumnText(stmt, 2);
        volume.createdAt = sqlite3_column_int64(stmt, 3);
        volume.containerIds = jsonToVector<std::string>(safeColumnText(stmt, 4));
        volumes.push_back(volume);
    }

    return volumes;
}

// ============================================================================
// Podman Container Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertPodmanContainer(const PodmanContainerInfo& container) {
    const char* sql = LinuxAnalysisSQL::INSERT_PODMAN_CONTAINER;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, container.containerId);
    BIND_TEXT(stmt, 2, container.imageName);
    BIND_TEXT(stmt, 3, container.podName);
    BIND_INT(stmt, 4, container.isRootless ? 1 : 0);
    BIND_TEXT(stmt, 5, container.state);
    BIND_INT64(stmt, 6, container.createdAt);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertPodmanContainers(const std::vector<PodmanContainerInfo>& containers) {
    beginTransaction();
    for (const auto& container : containers) {
        if (!insertPodmanContainer(container)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<PodmanContainerInfo> LinuxAnalysisDatabase::queryPodmanContainers(const std::string& whereClause) {
    std::vector<PodmanContainerInfo> containers;
    std::string sql = "SELECT container_id, image_name, pod_name, is_rootless, state, created_at FROM linux_podman_containers";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return containers;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PodmanContainerInfo container;
        container.containerId = safeColumnText(stmt, 0);
        container.imageName = safeColumnText(stmt, 1);
        container.podName = safeColumnText(stmt, 2);
        container.isRootless = sqlite3_column_int(stmt, 3) != 0;
        container.state = safeColumnText(stmt, 4);
        container.createdAt = sqlite3_column_int64(stmt, 5);
        containers.push_back(container);
    }

    return containers;
}

std::vector<PodmanContainerInfo> LinuxAnalysisDatabase::queryPodmanContainersSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<PodmanContainerInfo> containers;

    std::string sql = "SELECT container_id, image_name, pod_name, is_rootless, state, created_at FROM linux_podman_containers";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return containers;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return containers;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PodmanContainerInfo container;
        container.containerId = safeColumnText(stmt, 0);
        container.imageName = safeColumnText(stmt, 1);
        container.podName = safeColumnText(stmt, 2);
        container.isRootless = sqlite3_column_int(stmt, 3) != 0;
        container.state = safeColumnText(stmt, 4);
        container.createdAt = sqlite3_column_int64(stmt, 5);
        containers.push_back(container);
    }

    return containers;
}

// ============================================================================
// Podman Pod Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertPodmanPod(const PodmanPodInfo& pod) {
    const char* sql = LinuxAnalysisSQL::INSERT_PODMAN_POD;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, pod.podName);
    BIND_TEXT(stmt, 2, pod.podId);
    BIND_TEXT(stmt, 3, vectorToJson(pod.containerIds));
    BIND_TEXT(stmt, 4, pod.state);
    BIND_INT64(stmt, 5, pod.createdAt);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertPodmanPods(const std::vector<PodmanPodInfo>& pods) {
    beginTransaction();
    for (const auto& pod : pods) {
        if (!insertPodmanPod(pod)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<PodmanPodInfo> LinuxAnalysisDatabase::queryPodmanPods(const std::string& whereClause) {
    std::vector<PodmanPodInfo> pods;
    std::string sql = "SELECT pod_name, pod_id, container_ids, state, created_at FROM linux_podman_pods";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return pods;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PodmanPodInfo pod;
        pod.podName = safeColumnText(stmt, 0);
        pod.podId = safeColumnText(stmt, 1);
        pod.containerIds = jsonToVector<std::string>(safeColumnText(stmt, 2));
        pod.state = safeColumnText(stmt, 3);
        pod.createdAt = sqlite3_column_int64(stmt, 4);
        pods.push_back(pod);
    }

    return pods;
}

std::vector<PodmanPodInfo> LinuxAnalysisDatabase::queryPodmanPodsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<PodmanPodInfo> pods;

    std::string sql = "SELECT pod_name, pod_id, container_ids, state, created_at FROM linux_podman_pods";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return pods;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return pods;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PodmanPodInfo pod;
        pod.podName = safeColumnText(stmt, 0);
        pod.podId = safeColumnText(stmt, 1);
        pod.containerIds = jsonToVector<std::string>(safeColumnText(stmt, 2));
        pod.state = safeColumnText(stmt, 3);
        pod.createdAt = sqlite3_column_int64(stmt, 4);
        pods.push_back(pod);
    }

    return pods;
}

// ============================================================================
// Apache Access Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertApacheAccessLog(const ApacheAccessLogEntry& entry) {
    const char* sql = LinuxAnalysisSQL::INSERT_APACHE_ACCESS_LOG;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, entry.timestamp);
    BIND_TEXT(stmt, 2, entry.remoteIp);
    BIND_TEXT(stmt, 3, entry.method);
    BIND_TEXT(stmt, 4, entry.url);
    BIND_TEXT(stmt, 5, entry.httpVersion);
    BIND_INT(stmt, 6, entry.statusCode);
    BIND_INT(stmt, 7, entry.responseSize);
    BIND_TEXT(stmt, 8, entry.referer);
    BIND_TEXT(stmt, 9, entry.userAgent);
    BIND_TEXT(stmt, 10, entry.vhost);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertApacheAccessLogs(const std::vector<ApacheAccessLogEntry>& entries) {
    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertApacheAccessLog(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<ApacheAccessLogEntry> LinuxAnalysisDatabase::queryApacheAccessLogs(const std::string& whereClause) {
    std::vector<ApacheAccessLogEntry> entries;
    std::string sql = "SELECT timestamp, remote_ip, method, url, http_version, status_code, response_size, referer, user_agent, vhost FROM linux_apache_access_logs";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ApacheAccessLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 0);
        entry.remoteIp = safeColumnText(stmt, 1);
        entry.method = safeColumnText(stmt, 2);
        entry.url = safeColumnText(stmt, 3);
        entry.httpVersion = safeColumnText(stmt, 4);
        entry.statusCode = sqlite3_column_int(stmt, 5);
        entry.responseSize = sqlite3_column_int(stmt, 6);
        entry.referer = safeColumnText(stmt, 7);
        entry.userAgent = safeColumnText(stmt, 8);
        entry.vhost = safeColumnText(stmt, 9);
        entries.push_back(entry);
    }

    return entries;
}

std::vector<ApacheAccessLogEntry> LinuxAnalysisDatabase::queryApacheAccessLogsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<ApacheAccessLogEntry> entries;

    std::string sql = "SELECT timestamp, remote_ip, method, url, http_version, status_code, response_size, referer, user_agent, vhost FROM linux_apache_access_logs";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return entries;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ApacheAccessLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 0);
        entry.remoteIp = safeColumnText(stmt, 1);
        entry.method = safeColumnText(stmt, 2);
        entry.url = safeColumnText(stmt, 3);
        entry.httpVersion = safeColumnText(stmt, 4);
        entry.statusCode = sqlite3_column_int(stmt, 5);
        entry.responseSize = sqlite3_column_int(stmt, 6);
        entry.referer = safeColumnText(stmt, 7);
        entry.userAgent = safeColumnText(stmt, 8);
        entry.vhost = safeColumnText(stmt, 9);
        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Apache Virtual Host Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertApacheVHost(const ApacheVHostConfig& vhost) {
    const char* sql = LinuxAnalysisSQL::INSERT_APACHE_VHOST;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, vhost.serverName);
    BIND_TEXT(stmt, 2, vhost.documentRoot);
    BIND_TEXT(stmt, 3, vectorToJson(vhost.serverAliases));
    BIND_TEXT(stmt, 4, vectorToJson(vhost.sslCertificates));
    BIND_TEXT(stmt, 5, vhost.configFilePath);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertApacheVHosts(const std::vector<ApacheVHostConfig>& vhosts) {
    beginTransaction();
    for (const auto& vhost : vhosts) {
        if (!insertApacheVHost(vhost)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<ApacheVHostConfig> LinuxAnalysisDatabase::queryApacheVHosts(const std::string& whereClause) {
    std::vector<ApacheVHostConfig> vhosts;
    std::string sql = "SELECT server_name, document_root, server_aliases, ssl_certificates, config_file_path FROM linux_apache_vhosts";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return vhosts;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ApacheVHostConfig vhost;
        vhost.serverName = safeColumnText(stmt, 0);
        vhost.documentRoot = safeColumnText(stmt, 1);
        vhost.serverAliases = jsonToVector<std::string>(safeColumnText(stmt, 2));
        vhost.sslCertificates = jsonToVector<std::string>(safeColumnText(stmt, 3));
        vhost.configFilePath = safeColumnText(stmt, 4);
        vhosts.push_back(vhost);
    }

    return vhosts;
}

std::vector<ApacheVHostConfig> LinuxAnalysisDatabase::queryApacheVHostsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<ApacheVHostConfig> vhosts;

    std::string sql = "SELECT server_name, document_root, server_aliases, ssl_certificates, config_file_path FROM linux_apache_vhosts";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return vhosts;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return vhosts;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ApacheVHostConfig vhost;
        vhost.serverName = safeColumnText(stmt, 0);
        vhost.documentRoot = safeColumnText(stmt, 1);
        vhost.serverAliases = jsonToVector<std::string>(safeColumnText(stmt, 2));
        vhost.sslCertificates = jsonToVector<std::string>(safeColumnText(stmt, 3));
        vhost.configFilePath = safeColumnText(stmt, 4);
        vhosts.push_back(vhost);
    }

    return vhosts;
}

// ============================================================================
// Nginx Access Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertNginxAccessLog(const NginxAccessLogEntry& entry) {
    const char* sql = LinuxAnalysisSQL::INSERT_NGINX_ACCESS_LOG;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, entry.timestamp);
    BIND_TEXT(stmt, 2, entry.remoteIp);
    BIND_TEXT(stmt, 3, entry.method);
    BIND_TEXT(stmt, 4, entry.url);
    BIND_INT(stmt, 5, entry.statusCode);
    BIND_INT(stmt, 6, entry.responseSize);
    BIND_TEXT(stmt, 7, entry.referer);
    BIND_TEXT(stmt, 8, entry.userAgent);
    BIND_DOUBLE(stmt, 9, entry.requestTime);
    BIND_TEXT(stmt, 10, entry.upstreamAddr);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertNginxAccessLogs(const std::vector<NginxAccessLogEntry>& entries) {
    beginTransaction();
    for (const auto& entry : entries) {
        if (!insertNginxAccessLog(entry)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<NginxAccessLogEntry> LinuxAnalysisDatabase::queryNginxAccessLogs(const std::string& whereClause) {
    std::vector<NginxAccessLogEntry> entries;
    std::string sql = "SELECT timestamp, remote_ip, method, url, status_code, response_size, referer, user_agent, request_time, upstream_addr FROM linux_nginx_access_logs";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        NginxAccessLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 0);
        entry.remoteIp = safeColumnText(stmt, 1);
        entry.method = safeColumnText(stmt, 2);
        entry.url = safeColumnText(stmt, 3);
        entry.statusCode = sqlite3_column_int(stmt, 4);
        entry.responseSize = sqlite3_column_int(stmt, 5);
        entry.referer = safeColumnText(stmt, 6);
        entry.userAgent = safeColumnText(stmt, 7);
        entry.requestTime = static_cast<float>(sqlite3_column_double(stmt, 8));
        entry.upstreamAddr = safeColumnText(stmt, 9);
        entries.push_back(entry);
    }

    return entries;
}

std::vector<NginxAccessLogEntry> LinuxAnalysisDatabase::queryNginxAccessLogsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<NginxAccessLogEntry> entries;

    std::string sql = "SELECT timestamp, remote_ip, method, url, status_code, response_size, referer, user_agent, request_time, upstream_addr FROM linux_nginx_access_logs";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return entries;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return entries;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        NginxAccessLogEntry entry;
        entry.timestamp = sqlite3_column_int64(stmt, 0);
        entry.remoteIp = safeColumnText(stmt, 1);
        entry.method = safeColumnText(stmt, 2);
        entry.url = safeColumnText(stmt, 3);
        entry.statusCode = sqlite3_column_int(stmt, 4);
        entry.responseSize = sqlite3_column_int(stmt, 5);
        entry.referer = safeColumnText(stmt, 6);
        entry.userAgent = safeColumnText(stmt, 7);
        entry.requestTime = static_cast<float>(sqlite3_column_double(stmt, 8));
        entry.upstreamAddr = safeColumnText(stmt, 9);
        entries.push_back(entry);
    }

    return entries;
}

// ============================================================================
// Nginx Server Block Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertNginxServerBlock(const NginxServerBlock& block) {
    const char* sql = LinuxAnalysisSQL::INSERT_NGINX_SERVER_BLOCK;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, block.serverName);
    BIND_TEXT(stmt, 2, block.root);
    BIND_TEXT(stmt, 3, vectorToJson(block.locations));
    BIND_TEXT(stmt, 4, block.sslCertificate);
    BIND_TEXT(stmt, 5, block.sslCertificateKey);
    BIND_TEXT(stmt, 6, vectorToJson(block.upstreams));
    BIND_TEXT(stmt, 7, block.configFilePath);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertNginxServerBlocks(const std::vector<NginxServerBlock>& blocks) {
    beginTransaction();
    for (const auto& block : blocks) {
        if (!insertNginxServerBlock(block)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<NginxServerBlock> LinuxAnalysisDatabase::queryNginxServerBlocks(const std::string& whereClause) {
    std::vector<NginxServerBlock> blocks;
    std::string sql = "SELECT server_name, root, locations, ssl_certificate, ssl_certificate_key, upstreams, config_file_path FROM linux_nginx_server_blocks";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return blocks;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        NginxServerBlock block;
        block.serverName = safeColumnText(stmt, 0);
        block.root = safeColumnText(stmt, 1);
        block.locations = jsonToVector<std::string>(safeColumnText(stmt, 2));
        block.sslCertificate = safeColumnText(stmt, 3);
        block.sslCertificateKey = safeColumnText(stmt, 4);
        block.upstreams = jsonToVector<std::string>(safeColumnText(stmt, 5));
        block.configFilePath = safeColumnText(stmt, 6);
        blocks.push_back(block);
    }

    return blocks;
}

std::vector<NginxServerBlock> LinuxAnalysisDatabase::queryNginxServerBlocksSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<NginxServerBlock> blocks;

    std::string sql = "SELECT server_name, root, locations, ssl_certificate, ssl_certificate_key, upstreams, config_file_path FROM linux_nginx_server_blocks";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return blocks;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return blocks;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        NginxServerBlock block;
        block.serverName = safeColumnText(stmt, 0);
        block.root = safeColumnText(stmt, 1);
        block.locations = jsonToVector<std::string>(safeColumnText(stmt, 2));
        block.sslCertificate = safeColumnText(stmt, 3);
        block.sslCertificateKey = safeColumnText(stmt, 4);
        block.upstreams = jsonToVector<std::string>(safeColumnText(stmt, 5));
        block.configFilePath = safeColumnText(stmt, 6);
        blocks.push_back(block);
    }

    return blocks;
}

// ============================================================================
// Setuid File Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSetuidFile(const SetuidFileInfo& file) {
    const char* sql = LinuxAnalysisSQL::INSERT_SETUID_FILE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, file.filePath);
    BIND_TEXT(stmt, 2, file.owner);
    BIND_TEXT(stmt, 3, file.groupName);
    BIND_INT(stmt, 4, file.permissions);
    BIND_INT(stmt, 5, file.isSetuid ? 1 : 0);
    BIND_INT(stmt, 6, file.isSetgid ? 1 : 0);
    BIND_INT64(stmt, 7, file.size);
    BIND_TEXT(stmt, 8, file.md5Hash);
    BIND_TEXT(stmt, 9, file.sha256Hash);
    BIND_INT(stmt, 10, file.isSuspicious ? 1 : 0);
    BIND_TEXT(stmt, 11, file.suspiciousReason);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertSetuidFiles(const std::vector<SetuidFileInfo>& files) {
    beginTransaction();
    for (const auto& file : files) {
        if (!insertSetuidFile(file)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<SetuidFileInfo> LinuxAnalysisDatabase::querySetuidFiles(const std::string& whereClause) {
    std::vector<SetuidFileInfo> files;
    std::string sql = "SELECT file_path, owner, group_name, permissions, is_setuid, is_setgid, size, md5_hash, sha256_hash, is_suspicious, suspicious_reason FROM linux_setuid_files";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return files;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SetuidFileInfo file;
        file.filePath = safeColumnText(stmt, 0);
        file.owner = safeColumnText(stmt, 1);
        file.groupName = safeColumnText(stmt, 2);
        file.permissions = static_cast<mode_t>(sqlite3_column_int(stmt, 3));
        file.isSetuid = sqlite3_column_int(stmt, 4) != 0;
        file.isSetgid = sqlite3_column_int(stmt, 5) != 0;
        file.size = sqlite3_column_int64(stmt, 6);
        file.md5Hash = safeColumnText(stmt, 7);
        file.sha256Hash = safeColumnText(stmt, 8);
        file.isSuspicious = sqlite3_column_int(stmt, 9) != 0;
        file.suspiciousReason = safeColumnText(stmt, 10);
        files.push_back(file);
    }

    return files;
}

std::vector<SetuidFileInfo> LinuxAnalysisDatabase::querySetuidFilesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SetuidFileInfo> files;

    std::string sql = "SELECT file_path, owner, group_name, permissions, is_setuid, is_setgid, size, md5_hash, sha256_hash, is_suspicious, suspicious_reason FROM linux_setuid_files";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return files;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return files;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SetuidFileInfo file;
        file.filePath = safeColumnText(stmt, 0);
        file.owner = safeColumnText(stmt, 1);
        file.groupName = safeColumnText(stmt, 2);
        file.permissions = static_cast<mode_t>(sqlite3_column_int(stmt, 3));
        file.isSetuid = sqlite3_column_int(stmt, 4) != 0;
        file.isSetgid = sqlite3_column_int(stmt, 5) != 0;
        file.size = sqlite3_column_int64(stmt, 6);
        file.md5Hash = safeColumnText(stmt, 7);
        file.sha256Hash = safeColumnText(stmt, 8);
        file.isSuspicious = sqlite3_column_int(stmt, 9) != 0;
        file.suspiciousReason = safeColumnText(stmt, 10);
        files.push_back(file);
    }

    return files;
}

// ============================================================================
// File Capability Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertFileCapability(const FileCapability& capability) {
    const char* sql = LinuxAnalysisSQL::INSERT_FILE_CAPABILITY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, capability.filePath);
    BIND_TEXT(stmt, 2, vectorToJson(capability.capabilities));
    BIND_TEXT(stmt, 3, capability.capabilitySet);
    BIND_INT(stmt, 4, capability.isInherited ? 1 : 0);
    BIND_INT(stmt, 5, capability.isSuspicious ? 1 : 0);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertFileCapabilities(const std::vector<FileCapability>& capabilities) {
    beginTransaction();
    for (const auto& capability : capabilities) {
        if (!insertFileCapability(capability)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<FileCapability> LinuxAnalysisDatabase::queryFileCapabilities(const std::string& whereClause) {
    std::vector<FileCapability> capabilities;
    std::string sql = "SELECT file_path, capabilities, capability_set, is_inherited, is_suspicious FROM linux_capabilities";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return capabilities;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileCapability capability;
        capability.filePath = safeColumnText(stmt, 0);
        capability.capabilities = jsonToVector<std::string>(safeColumnText(stmt, 1));
        capability.capabilitySet = safeColumnText(stmt, 2);
        capability.isInherited = sqlite3_column_int(stmt, 3) != 0;
        capability.isSuspicious = sqlite3_column_int(stmt, 4) != 0;
        capabilities.push_back(capability);
    }

    return capabilities;
}

std::vector<FileCapability> LinuxAnalysisDatabase::queryFileCapabilitiesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<FileCapability> capabilities;

    std::string sql = "SELECT file_path, capabilities, capability_set, is_inherited, is_suspicious FROM linux_capabilities";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return capabilities;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return capabilities;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        FileCapability capability;
        capability.filePath = safeColumnText(stmt, 0);
        capability.capabilities = jsonToVector<std::string>(safeColumnText(stmt, 1));
        capability.capabilitySet = safeColumnText(stmt, 2);
        capability.isInherited = sqlite3_column_int(stmt, 3) != 0;
        capability.isSuspicious = sqlite3_column_int(stmt, 4) != 0;
        capabilities.push_back(capability);
    }

    return capabilities;
}

// ============================================================================
// SELinux Status Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSELinuxStatus(const SELinuxStatus& status) {
    const char* sql = LinuxAnalysisSQL::INSERT_SELINUX_STATUS;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT(stmt, 1, status.isEnabled ? 1 : 0);
    BIND_TEXT(stmt, 2, status.mode);
    BIND_TEXT(stmt, 3, status.policyName);
    BIND_TEXT(stmt, 4, status.currentMode);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

std::vector<SELinuxStatus> LinuxAnalysisDatabase::querySELinuxStatus(const std::string& whereClause) {
    std::vector<SELinuxStatus> statuses;
    std::string sql = "SELECT is_enabled, mode, policy_name, current_mode FROM linux_selinux_status";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return statuses;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SELinuxStatus status;
        status.isEnabled = sqlite3_column_int(stmt, 0) != 0;
        status.mode = safeColumnText(stmt, 1);
        status.policyName = safeColumnText(stmt, 2);
        status.currentMode = safeColumnText(stmt, 3);
        statuses.push_back(status);
    }

    return statuses;
}

std::vector<SELinuxStatus> LinuxAnalysisDatabase::querySELinuxStatusSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SELinuxStatus> statuses;

    std::string sql = "SELECT is_enabled, mode, policy_name, current_mode FROM linux_selinux_status";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return statuses;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return statuses;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SELinuxStatus status;
        status.isEnabled = sqlite3_column_int(stmt, 0) != 0;
        status.mode = safeColumnText(stmt, 1);
        status.policyName = safeColumnText(stmt, 2);
        status.currentMode = safeColumnText(stmt, 3);
        statuses.push_back(status);
    }

    return statuses;
}

// ============================================================================
// SELinux AVC Denial Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertSELinuxAVCDenial(const SELinuxAVCDenial& denial) {
    const char* sql = LinuxAnalysisSQL::INSERT_SELINUX_AVC_DENIAL;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, denial.timestamp);
    BIND_TEXT(stmt, 2, denial.sourceContext);
    BIND_TEXT(stmt, 3, denial.targetContext);
    BIND_TEXT(stmt, 4, denial.objectClass);
    BIND_TEXT(stmt, 5, denial.permission);
    BIND_TEXT(stmt, 6, denial.executablePath);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertSELinuxAVCDenials(const std::vector<SELinuxAVCDenial>& denials) {
    beginTransaction();
    for (const auto& denial : denials) {
        if (!insertSELinuxAVCDenial(denial)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<SELinuxAVCDenial> LinuxAnalysisDatabase::querySELinuxAVCDenials(const std::string& whereClause) {
    std::vector<SELinuxAVCDenial> denials;
    std::string sql = "SELECT timestamp, source_context, target_context, object_class, permission, executable_path FROM linux_selinux_avc_denials";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return denials;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SELinuxAVCDenial denial;
        denial.timestamp = sqlite3_column_int64(stmt, 0);
        denial.sourceContext = safeColumnText(stmt, 1);
        denial.targetContext = safeColumnText(stmt, 2);
        denial.objectClass = safeColumnText(stmt, 3);
        denial.permission = safeColumnText(stmt, 4);
        denial.executablePath = safeColumnText(stmt, 5);
        denials.push_back(denial);
    }

    return denials;
}

std::vector<SELinuxAVCDenial> LinuxAnalysisDatabase::querySELinuxAVCDenialsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<SELinuxAVCDenial> denials;

    std::string sql = "SELECT timestamp, source_context, target_context, object_class, permission, executable_path FROM linux_selinux_avc_denials";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return denials;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return denials;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        SELinuxAVCDenial denial;
        denial.timestamp = sqlite3_column_int64(stmt, 0);
        denial.sourceContext = safeColumnText(stmt, 1);
        denial.targetContext = safeColumnText(stmt, 2);
        denial.objectClass = safeColumnText(stmt, 3);
        denial.permission = safeColumnText(stmt, 4);
        denial.executablePath = safeColumnText(stmt, 5);
        denials.push_back(denial);
    }

    return denials;
}

// ============================================================================
// AppArmor Profile Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAppArmorProfile(const AppArmorProfile& profile) {
    const char* sql = LinuxAnalysisSQL::INSERT_APPARMOR_PROFILE;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, profile.profileName);
    BIND_TEXT(stmt, 2, profile.mode);
    BIND_TEXT(stmt, 3, profile.filePath);
    BIND_TEXT(stmt, 4, vectorToJson(profile.allowedPaths));
    BIND_TEXT(stmt, 5, vectorToJson(profile.deniedPaths));
    BIND_INT(stmt, 6, profile.isEnabled ? 1 : 0);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAppArmorProfiles(const std::vector<AppArmorProfile>& profiles) {
    beginTransaction();
    for (const auto& profile : profiles) {
        if (!insertAppArmorProfile(profile)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<AppArmorProfile> LinuxAnalysisDatabase::queryAppArmorProfiles(const std::string& whereClause) {
    std::vector<AppArmorProfile> profiles;
    std::string sql = "SELECT profile_name, mode, file_path, allowed_paths, denied_paths, is_enabled FROM linux_apparmor_profiles";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return profiles;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AppArmorProfile profile;
        profile.profileName = safeColumnText(stmt, 0);
        profile.mode = safeColumnText(stmt, 1);
        profile.filePath = safeColumnText(stmt, 2);
        profile.allowedPaths = jsonToVector<std::string>(safeColumnText(stmt, 3));
        profile.deniedPaths = jsonToVector<std::string>(safeColumnText(stmt, 4));
        profile.isEnabled = sqlite3_column_int(stmt, 5) != 0;
        profiles.push_back(profile);
    }

    return profiles;
}

std::vector<AppArmorProfile> LinuxAnalysisDatabase::queryAppArmorProfilesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<AppArmorProfile> profiles;

    std::string sql = "SELECT profile_name, mode, file_path, allowed_paths, denied_paths, is_enabled FROM linux_apparmor_profiles";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return profiles;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return profiles;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AppArmorProfile profile;
        profile.profileName = safeColumnText(stmt, 0);
        profile.mode = safeColumnText(stmt, 1);
        profile.filePath = safeColumnText(stmt, 2);
        profile.allowedPaths = jsonToVector<std::string>(safeColumnText(stmt, 3));
        profile.deniedPaths = jsonToVector<std::string>(safeColumnText(stmt, 4));
        profile.isEnabled = sqlite3_column_int(stmt, 5) != 0;
        profiles.push_back(profile);
    }

    return profiles;
}

// ============================================================================
// AppArmor Violation Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAppArmorViolation(const AppArmorViolation& violation) {
    const char* sql = LinuxAnalysisSQL::INSERT_APPARMOR_VIOLATION;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, violation.timestamp);
    BIND_TEXT(stmt, 2, violation.profile);
    BIND_TEXT(stmt, 3, violation.operation);
    BIND_TEXT(stmt, 4, violation.targetPath);
    BIND_TEXT(stmt, 5, violation.executable);
    BIND_TEXT(stmt, 6, violation.status);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAppArmorViolations(const std::vector<AppArmorViolation>& violations) {
    beginTransaction();
    for (const auto& violation : violations) {
        if (!insertAppArmorViolation(violation)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<AppArmorViolation> LinuxAnalysisDatabase::queryAppArmorViolations(const std::string& whereClause) {
    std::vector<AppArmorViolation> violations;
    std::string sql = "SELECT timestamp, profile, operation, target_path, executable, status FROM linux_apparmor_violations";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return violations;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AppArmorViolation violation;
        violation.timestamp = sqlite3_column_int64(stmt, 0);
        violation.profile = safeColumnText(stmt, 1);
        violation.operation = safeColumnText(stmt, 2);
        violation.targetPath = safeColumnText(stmt, 3);
        violation.executable = safeColumnText(stmt, 4);
        violation.status = safeColumnText(stmt, 5);
        violations.push_back(violation);
    }

    return violations;
}

std::vector<AppArmorViolation> LinuxAnalysisDatabase::queryAppArmorViolationsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<AppArmorViolation> violations;

    std::string sql = "SELECT timestamp, profile, operation, target_path, executable, status FROM linux_apparmor_violations";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return violations;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return violations;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AppArmorViolation violation;
        violation.timestamp = sqlite3_column_int64(stmt, 0);
        violation.profile = safeColumnText(stmt, 1);
        violation.operation = safeColumnText(stmt, 2);
        violation.targetPath = safeColumnText(stmt, 3);
        violation.executable = safeColumnText(stmt, 4);
        violation.status = safeColumnText(stmt, 5);
        violations.push_back(violation);
    }

    return violations;
}

// ============================================================================
// Correlated Event Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertCorrelatedEvent(const CorrelatedEvent& event) {
    const char* sql = LinuxAnalysisSQL::INSERT_CORRELATED_EVENT;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, event.startTimestamp);
    BIND_INT64(stmt, 2, event.endTimestamp);
    BIND_TEXT(stmt, 3, event.eventType);
    BIND_TEXT(stmt, 4, event.initiatingUser);
    BIND_TEXT(stmt, 5, event.initiatingProcess);
    BIND_TEXT(stmt, 6, vectorToJson(event.relatedEventIds));
    BIND_TEXT(stmt, 7, event.description);
    BIND_INT(stmt, 8, event.severity);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertCorrelatedEvents(const std::vector<CorrelatedEvent>& events) {
    beginTransaction();
    for (const auto& event : events) {
        if (!insertCorrelatedEvent(event)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<CorrelatedEvent> LinuxAnalysisDatabase::queryCorrelatedEvents(const std::string& whereClause) {
    std::vector<CorrelatedEvent> events;
    std::string sql = "SELECT start_timestamp, end_timestamp, event_type, initiating_user, initiating_process, related_event_ids, description, severity FROM linux_correlated_events";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return events;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        CorrelatedEvent event;
        event.startTimestamp = sqlite3_column_int64(stmt, 0);
        event.endTimestamp = sqlite3_column_int64(stmt, 1);
        event.eventType = safeColumnText(stmt, 2);
        event.initiatingUser = safeColumnText(stmt, 3);
        event.initiatingProcess = safeColumnText(stmt, 4);
        event.relatedEventIds = jsonToVector<std::string>(safeColumnText(stmt, 5));
        event.description = safeColumnText(stmt, 6);
        event.severity = sqlite3_column_int(stmt, 7);
        events.push_back(event);
    }

    return events;
}

std::vector<CorrelatedEvent> LinuxAnalysisDatabase::queryCorrelatedEventsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<CorrelatedEvent> events;

    std::string sql = "SELECT start_timestamp, end_timestamp, event_type, initiating_user, initiating_process, related_event_ids, description, severity FROM linux_correlated_events";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return events;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return events;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        CorrelatedEvent event;
        event.startTimestamp = sqlite3_column_int64(stmt, 0);
        event.endTimestamp = sqlite3_column_int64(stmt, 1);
        event.eventType = safeColumnText(stmt, 2);
        event.initiatingUser = safeColumnText(stmt, 3);
        event.initiatingProcess = safeColumnText(stmt, 4);
        event.relatedEventIds = jsonToVector<std::string>(safeColumnText(stmt, 5));
        event.description = safeColumnText(stmt, 6);
        event.severity = sqlite3_column_int(stmt, 7);
        events.push_back(event);
    }

    return events;
}

// ============================================================================
// Attack Chain Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAttackChain(const AttackChain& chain) {
    const char* sql = LinuxAnalysisSQL::INSERT_ATTACK_CHAIN;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, chain.chainId);
    BIND_TEXT(stmt, 2, chain.attackType);
    // Serialize events vector to JSON
    json eventsJson = json::array();
    for (const auto& event : chain.events) {
        json eventJson;
        eventJson["start_timestamp"] = event.startTimestamp;
        eventJson["end_timestamp"] = event.endTimestamp;
        eventJson["event_type"] = event.eventType;
        eventJson["initiating_user"] = event.initiatingUser;
        eventJson["initiating_process"] = event.initiatingProcess;
        eventJson["related_event_ids"] = event.relatedEventIds;
        eventJson["description"] = event.description;
        eventJson["severity"] = event.severity;
        eventsJson.push_back(eventJson);
    }
    BIND_TEXT(stmt, 3, eventsJson.dump());
    BIND_TEXT(stmt, 4, chain.timeline);
    BIND_TEXT(stmt, 5, chain.summary);
    BIND_DOUBLE(stmt, 6, chain.confidence);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAttackChains(const std::vector<AttackChain>& chains) {
    beginTransaction();
    for (const auto& chain : chains) {
        if (!insertAttackChain(chain)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<AttackChain> LinuxAnalysisDatabase::queryAttackChains(const std::string& whereClause) {
    std::vector<AttackChain> chains;
    std::string sql = "SELECT chain_id, attack_type, events, timeline, summary, confidence FROM linux_attack_chains";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return chains;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AttackChain chain;
        chain.chainId = safeColumnText(stmt, 0);
        chain.attackType = safeColumnText(stmt, 1);

        // Parse events from JSON
        const char* eventsJson = safeColumnText(stmt, 2);
        if (eventsJson) {
            try {
                json eventsArray = json::parse(eventsJson);
                for (const auto& eventJson : eventsArray) {
                    CorrelatedEvent event;
                    if (eventJson.contains("start_timestamp")) event.startTimestamp = eventJson["start_timestamp"];
                    if (eventJson.contains("end_timestamp")) event.endTimestamp = eventJson["end_timestamp"];
                    if (eventJson.contains("event_type")) event.eventType = eventJson["event_type"];
                    if (eventJson.contains("initiating_user")) event.initiatingUser = eventJson["initiating_user"];
                    if (eventJson.contains("initiating_process")) event.initiatingProcess = eventJson["initiating_process"];
                    if (eventJson.contains("related_event_ids")) event.relatedEventIds = eventJson["related_event_ids"].get<std::vector<std::string>>();
                    if (eventJson.contains("description")) event.description = eventJson["description"];
                    if (eventJson.contains("severity")) event.severity = eventJson["severity"];
                    chain.events.push_back(event);
                }
            } catch (const std::exception& e) {
                std::cerr << "Error parsing events JSON: " << e.what() << std::endl;
            }
        }

        chain.timeline = safeColumnText(stmt, 3);
        chain.summary = safeColumnText(stmt, 4);
        chain.confidence = static_cast<float>(sqlite3_column_double(stmt, 5));
        chains.push_back(chain);
    }

    return chains;
}

std::vector<AttackChain> LinuxAnalysisDatabase::queryAttackChainsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<AttackChain> chains;

    std::string sql = "SELECT chain_id, attack_type, events, timeline, summary, confidence FROM linux_attack_chains";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return chains;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return chains;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        AttackChain chain;
        chain.chainId = safeColumnText(stmt, 0);
        chain.attackType = safeColumnText(stmt, 1);

        // Parse events from JSON
        const char* eventsJson = safeColumnText(stmt, 2);
        if (eventsJson) {
            try {
                json eventsArray = json::parse(eventsJson);
                for (const auto& eventJson : eventsArray) {
                    CorrelatedEvent event;
                    if (eventJson.contains("start_timestamp")) event.startTimestamp = eventJson["start_timestamp"];
                    if (eventJson.contains("end_timestamp")) event.endTimestamp = eventJson["end_timestamp"];
                    if (eventJson.contains("event_type")) event.eventType = eventJson["event_type"];
                    if (eventJson.contains("initiating_user")) event.initiatingUser = eventJson["initiating_user"];
                    if (eventJson.contains("initiating_process")) event.initiatingProcess = eventJson["initiating_process"];
                    if (eventJson.contains("related_event_ids")) event.relatedEventIds = eventJson["related_event_ids"].get<std::vector<std::string>>();
                    if (eventJson.contains("description")) event.description = eventJson["description"];
                    if (eventJson.contains("severity")) event.severity = eventJson["severity"];
                    chain.events.push_back(event);
                }
            } catch (const std::exception& e) {
                std::cerr << "Error parsing events JSON: " << e.what() << std::endl;
            }
        }

        chain.timeline = safeColumnText(stmt, 3);
        chain.summary = safeColumnText(stmt, 4);
        chain.confidence = static_cast<float>(sqlite3_column_double(stmt, 5));
        chains.push_back(chain);
    }

    return chains;
}

// ============================================================================
// Timeline Event Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertTimelineEvent(const LinuxTimelineEvent& event) {
    const char* sql = LinuxAnalysisSQL::INSERT_TIMELINE_EVENT;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, event.timestamp);
    BIND_TEXT(stmt, 2, event.sourceType);
    BIND_TEXT(stmt, 3, event.eventType);
    BIND_TEXT(stmt, 4, event.description);
    BIND_TEXT(stmt, 5, event.username);
    BIND_TEXT(stmt, 6, event.ipAddress);
    BIND_TEXT(stmt, 7, event.details);
    BIND_INT(stmt, 8, event.confidence);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertTimelineEvents(const std::vector<LinuxTimelineEvent>& events) {
    beginTransaction();
    for (const auto& event : events) {
        if (!insertTimelineEvent(event)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<LinuxTimelineEvent> LinuxAnalysisDatabase::queryTimelineEvents(const std::string& whereClause) {
    std::vector<LinuxTimelineEvent> events;
    std::string sql = "SELECT timestamp, source_type, event_type, description, username, ip_address, details, confidence FROM linux_timeline_events";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return events;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxTimelineEvent event;
        event.timestamp = sqlite3_column_int64(stmt, 0);
        event.sourceType = safeColumnText(stmt, 1);
        event.eventType = safeColumnText(stmt, 2);
        event.description = safeColumnText(stmt, 3);
        event.username = safeColumnText(stmt, 4);
        event.ipAddress = safeColumnText(stmt, 5);
        event.details = safeColumnText(stmt, 6);
        event.confidence = sqlite3_column_int(stmt, 7);
        events.push_back(event);
    }

    return events;
}

std::vector<LinuxTimelineEvent> LinuxAnalysisDatabase::queryTimelineEventsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<LinuxTimelineEvent> events;

    std::string sql = "SELECT timestamp, source_type, event_type, description, username, ip_address, details, confidence FROM linux_timeline_events";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return events;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return events;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        LinuxTimelineEvent event;
        event.timestamp = sqlite3_column_int64(stmt, 0);
        event.sourceType = safeColumnText(stmt, 1);
        event.eventType = safeColumnText(stmt, 2);
        event.description = safeColumnText(stmt, 3);
        event.username = safeColumnText(stmt, 4);
        event.ipAddress = safeColumnText(stmt, 5);
        event.details = safeColumnText(stmt, 6);
        event.confidence = sqlite3_column_int(stmt, 7);
        events.push_back(event);
    }

    return events;
}

// ============================================================================
// Timeline Gap Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertTimelineGap(const TimelineGap& gap) {
    const char* sql = LinuxAnalysisSQL::INSERT_TIMELINE_GAP;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_INT64(stmt, 1, gap.startTime);
    BIND_INT64(stmt, 2, gap.endTime);
    BIND_INT64(stmt, 3, gap.duration);
    BIND_TEXT(stmt, 4, gap.description);
    BIND_INT(stmt, 5, gap.isSuspicious ? 1 : 0);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertTimelineGaps(const std::vector<TimelineGap>& gaps) {
    beginTransaction();
    for (const auto& gap : gaps) {
        if (!insertTimelineGap(gap)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<TimelineGap> LinuxAnalysisDatabase::queryTimelineGaps(const std::string& whereClause) {
    std::vector<TimelineGap> gaps;
    std::string sql = "SELECT start_time, end_time, duration, description, is_suspicious FROM linux_timeline_gaps";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return gaps;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        TimelineGap gap;
        gap.startTime = sqlite3_column_int64(stmt, 0);
        gap.endTime = sqlite3_column_int64(stmt, 1);
        gap.duration = sqlite3_column_int64(stmt, 2);
        gap.description = safeColumnText(stmt, 3);
        gap.isSuspicious = sqlite3_column_int(stmt, 4) != 0;
        gaps.push_back(gap);
    }

    return gaps;
}

std::vector<TimelineGap> LinuxAnalysisDatabase::queryTimelineGapsSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<TimelineGap> gaps;

    std::string sql = "SELECT start_time, end_time, duration, description, is_suspicious FROM linux_timeline_gaps";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return gaps;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return gaps;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        TimelineGap gap;
        gap.startTime = sqlite3_column_int64(stmt, 0);
        gap.endTime = sqlite3_column_int64(stmt, 1);
        gap.duration = sqlite3_column_int64(stmt, 2);
        gap.description = safeColumnText(stmt, 3);
        gap.isSuspicious = sqlite3_column_int(stmt, 4) != 0;
        gaps.push_back(gap);
    }

    return gaps;
}

// ============================================================================
// Anomaly Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertAnomaly(const Anomaly& anomaly) {
    const char* sql = LinuxAnalysisSQL::INSERT_ANOMALY;
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return false;
    }
    StmtGuard guard(stmt);

    BIND_TEXT(stmt, 1, anomaly.anomalyType);
    BIND_TEXT(stmt, 2, anomaly.description);
    BIND_INT(stmt, 3, anomaly.severity);
    BIND_DOUBLE(stmt, 4, anomaly.confidence);
    BIND_TEXT(stmt, 5, vectorToJson(anomaly.evidenceIds));
    BIND_TEXT(stmt, 6, anomaly.mitigation);
    BIND_INT64(stmt, 7, anomaly.detectedAt);
    BIND_TEXT(stmt, 8, anomaly.anomalySubtype);
    BIND_TEXT(stmt, 9, anomaly.additionalData);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    if (!success) {
        setError(ErrorCode::DATABASE_EXECUTE_FAILED, sqlite3_errmsg(db_));
    }
    return success;
}

bool LinuxAnalysisDatabase::insertAnomalies(const std::vector<Anomaly>& anomalies) {
    beginTransaction();
    for (const auto& anomaly : anomalies) {
        if (!insertAnomaly(anomaly)) {
            rollbackTransaction();
            return false;
        }
    }
    return commitTransaction();
}

std::vector<Anomaly> LinuxAnalysisDatabase::queryAnomalies(const std::string& whereClause) {
    std::vector<Anomaly> anomalies;
    std::string sql = "SELECT anomaly_type, description, severity, confidence, evidence_ids, mitigation, detected_at, anomaly_subtype, additional_data FROM linux_anomalies";
    if (!whereClause.empty()) {
        sql += " WHERE " + whereClause;
    }

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return anomalies;
    }
    StmtGuard guard(stmt);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        Anomaly anomaly;
        anomaly.anomalyType = safeColumnText(stmt, 0);
        anomaly.description = safeColumnText(stmt, 1);
        anomaly.severity = sqlite3_column_int(stmt, 2);
        anomaly.confidence = static_cast<float>(sqlite3_column_double(stmt, 3));
        anomaly.evidenceIds = jsonToVector<std::string>(safeColumnText(stmt, 4));
        anomaly.mitigation = safeColumnText(stmt, 5);
        anomaly.detectedAt = sqlite3_column_int64(stmt, 6);
        anomaly.anomalySubtype = safeColumnText(stmt, 7);
        anomaly.additionalData = safeColumnText(stmt, 8);
        anomalies.push_back(anomaly);
    }

    return anomalies;
}

std::vector<Anomaly> LinuxAnalysisDatabase::queryAnomaliesSafe(const QueryBuilder& qb) {
    std::lock_guard<std::mutex> lock(mutex_);
    clearError();
    std::vector<Anomaly> anomalies;

    std::string sql = "SELECT anomaly_type, description, severity, confidence, evidence_ids, mitigation, detected_at, anomaly_subtype, additional_data FROM linux_anomalies";
    sql += qb.buildFullClause();

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, sqlite3_errmsg(db_));
        return anomalies;
    }
    StmtGuard guard(stmt);

    if (!qb.bindParameters(stmt)) {
        setError(ErrorCode::DATABASE_BIND_FAILED);
        return anomalies;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        Anomaly anomaly;
        anomaly.anomalyType = safeColumnText(stmt, 0);
        anomaly.description = safeColumnText(stmt, 1);
        anomaly.severity = sqlite3_column_int(stmt, 2);
        anomaly.confidence = static_cast<float>(sqlite3_column_double(stmt, 3));
        anomaly.evidenceIds = jsonToVector<std::string>(safeColumnText(stmt, 4));
        anomaly.mitigation = safeColumnText(stmt, 5);
        anomaly.detectedAt = sqlite3_column_int64(stmt, 6);
        anomaly.anomalySubtype = safeColumnText(stmt, 7);
        anomaly.additionalData = safeColumnText(stmt, 8);
        anomalies.push_back(anomaly);
    }

    return anomalies;
}
