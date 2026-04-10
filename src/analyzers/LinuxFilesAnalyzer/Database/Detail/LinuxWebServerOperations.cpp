// LinuxWebServerOperations.cpp
// Database operations for Apache and Nginx web servers

#include "LinuxAnalysisDatabase.h"
#include "LinuxQueryBuilder.h"
#include "DatabaseManager/SQL/linux_analysis_sql.h"
#include "Detail/LinuxDatabaseHelpers.h"
#include <mutex>

using namespace LinuxAnalysis;

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
