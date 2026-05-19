// LinuxContainerLogOperations.cpp
// Database operations for container runtime logs and security findings (Phase 8)

#include <sstream>

// ============================================================================
// Docker Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertContainerLog(const DockerLogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_container_logs
        (timestamp, stream, message, container_id, container_name, pod_name, namespace,
         runtime_type, file_path, parser_name, parser_version, source_file, raw_record)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare container log insert");
        return false;
    }

    sqlite3_bind_int64(stmt, 1, entry.timestamp);
    sqlite3_bind_text(stmt, 2, entry.stream.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, entry.containerId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, entry.containerName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, "", -1, SQLITE_TRANSIENT);  // pod_name (not in DockerLogEntry)
    sqlite3_bind_text(stmt, 7, "", -1, SQLITE_TRANSIENT);  // namespace
    sqlite3_bind_text(stmt, 8, "docker", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, entry.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 12, entry.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 13, entry.provenance.rawRecord.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert container log");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertContainerLogs(const std::vector<DockerLogEntry>& entries) {
    if (entries.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertContainerLog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// CRI Log Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertCRILog(const CRILogEntry& entry) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_container_logs
        (timestamp, stream, message, container_id, container_name, pod_name, namespace,
         runtime_type, file_path, parser_name, parser_version, source_file, raw_record)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare CRI log insert");
        return false;
    }

    sqlite3_bind_int64(stmt, 1, entry.timestamp);
    sqlite3_bind_text(stmt, 2, entry.stream.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, entry.message.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, entry.containerId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, entry.containerName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, entry.podName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, entry.namespace_.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, "cri", -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, entry.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, entry.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, entry.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 12, entry.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 13, entry.provenance.rawRecord.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert CRI log");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertCRILogs(const std::vector<CRILogEntry>& entries) {
    if (entries.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& entry : entries) {
        if (!insertCRILog(entry)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}

// ============================================================================
// Container Security Finding Operations
// ============================================================================

bool LinuxAnalysisDatabase::insertContainerSecurityFinding(const ContainerSecurityFinding& finding) {
    std::lock_guard<std::mutex> lock(mutex_);

    const char* sql = R"(
        INSERT INTO linux_container_security_findings
        (finding_type, severity, container_id, container_name, pod_name, namespace,
         description, evidence, file_path, parser_name, parser_version, source_file)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    )";

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql, -1, &stmt, nullptr) != SQLITE_OK) {
        setError(ErrorCode::DATABASE_PREPARE_FAILED, "Failed to prepare container security finding insert");
        return false;
    }

    sqlite3_bind_text(stmt, 1, finding.findingType.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 2, finding.severity.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 3, finding.containerId.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 4, finding.containerName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 5, finding.podName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 6, finding.namespace_.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 7, finding.description.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 8, finding.evidence.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 9, finding.filePath.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 10, finding.provenance.parserName.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 11, finding.provenance.parserVersion.c_str(), -1, SQLITE_TRANSIENT);
    sqlite3_bind_text(stmt, 12, finding.provenance.sourceFile.c_str(), -1, SQLITE_TRANSIENT);

    bool success = sqlite3_step(stmt) == SQLITE_DONE;
    sqlite3_finalize(stmt);

    if (!success) {
        setError(ErrorCode::DATABASE_INSERT_FAILED, "Failed to insert container security finding");
    }
    return success;
}

bool LinuxAnalysisDatabase::insertContainerSecurityFindings(const std::vector<ContainerSecurityFinding>& findings) {
    if (findings.empty()) return true;
    if (!beginTransaction()) return false;

    bool allSuccess = true;
    for (const auto& finding : findings) {
        if (!insertContainerSecurityFinding(finding)) {
            allSuccess = false;
            break;
        }
    }

    if (allSuccess) return commitTransaction();
    rollbackTransaction();
    return false;
}
