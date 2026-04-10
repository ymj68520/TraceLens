// LinuxContainerOperations.cpp
// Database operations for Docker and Podman containers

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include "Detail/LinuxDatabaseHelpers.h"
#include <mutex>

using namespace LinuxAnalysis;

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
