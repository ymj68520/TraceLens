// DLLAnalysisDatabase_Queries.cpp
// Read-only queries: getDLLBy*, counts, sections/imports/exports/anomalies getters
// Part of DLLAnalysisDatabase implementation; methods belong to
// forensics::dll::DLLAnalysisDatabase declared in DLLAnalysisDatabase.h.
// Split from DLLAnalysisDatabase.cpp for maintainability.

#include "DLLAnalysisDatabase.h"
#include "../../core/DatabaseManager/SQL/windows_analysis_sql_tables.h"
#include "../../core/DatabaseManager/SQL/windows_analysis_sql_crud.h"
#include "../../core/DatabaseManager/SQL/windows_analysis_sql_llm.h"
#include "../../core/AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>
#include <iomanip>

using namespace forensics::dll;

DLLAnalysisResult DLLAnalysisDatabase::readDLLFromRow(sqlite3_stmt* stmt) {
    DLLAnalysisResult result;

    // dll_base_info列索引 (SELECT * FROM dll_base_info)
    // 0:id, 1:inode, 2:name, 3:path, 4:size, 5:md5, 6:sha1, 7:sha256
    // 8:imp_hash, 9:rich_hash,
    // 10:file_format, 11:machine_type, 12:compile_timestamp, 13:subsystem
    // 14:entry_point, 15:image_base, 16:is_dll, 17:characteristics
    // 18:file_version, 19:product_version, 20:company_name, 21:file_description
    // 22:signature_status, 23:signer_name, 24:cert_issuer, 25:cert_valid_from, 26:cert_valid_to
    // 27:mtime, 28:ctime, 29:atime, 30:crtime
    // 31:is_deleted, 32:threat_score, 33:llm_summary, 34:llm_description
    // 35:llm_keywords, 36:llm_analyzed_at, 37:llm_model_used, 38:created_at

    result.inode = sqlite3_column_int64(stmt, 1);
    result.fileName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
    result.filePath = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
    result.fileSize = static_cast<uint64_t>(sqlite3_column_int64(stmt, 4));

    // 哈希 (cols 5-8)
    if (sqlite3_column_type(stmt, 5) != SQLITE_NULL)
        result.md5Hash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 5));
    if (sqlite3_column_type(stmt, 6) != SQLITE_NULL)
        result.sha1Hash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 6));
    if (sqlite3_column_type(stmt, 7) != SQLITE_NULL)
        result.sha256Hash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 7));
    if (sqlite3_column_type(stmt, 8) != SQLITE_NULL)
        result.impHash = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 8));

    // rich_hash at col[9] — skip (not in DLLAnalysisResult)

    // PE头信息 (cols 10-17)
    if (sqlite3_column_type(stmt, 10) != SQLITE_NULL)
        result.peHeader.format = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 10));
    if (sqlite3_column_type(stmt, 11) != SQLITE_NULL)
        result.peHeader.machine = machineTypeFromString(
            reinterpret_cast<const char*>(sqlite3_column_text(stmt, 11)));
    result.peHeader.timestamp = static_cast<uint32_t>(sqlite3_column_int(stmt, 12));
    result.peHeader.subsystem = static_cast<uint16_t>(sqlite3_column_int(stmt, 13));
    result.peHeader.entryPointRVA = static_cast<uint32_t>(sqlite3_column_int(stmt, 14));
    result.peHeader.imageBase = static_cast<uint64_t>(sqlite3_column_int64(stmt, 15));
    result.peHeader.isDLL = sqlite3_column_int(stmt, 16) != 0;
    result.peHeader.characteristics = static_cast<uint16_t>(sqlite3_column_int(stmt, 17));

    // 版本信息 (cols 18-21)
    if (sqlite3_column_type(stmt, 18) != SQLITE_NULL)
        result.fileVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 18));
    if (sqlite3_column_type(stmt, 19) != SQLITE_NULL)
        result.productVersion = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 19));
    if (sqlite3_column_type(stmt, 20) != SQLITE_NULL)
        result.companyName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 20));
    if (sqlite3_column_type(stmt, 21) != SQLITE_NULL)
        result.fileDescription = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 21));

    // 数字签名 (cols 22-23)
    if (sqlite3_column_type(stmt, 22) != SQLITE_NULL)
        result.signatureStatus = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 22));
    if (sqlite3_column_type(stmt, 23) != SQLITE_NULL)
        result.signerName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 23));

    // cert_issuer, cert_valid_from, cert_valid_to at cols 24-26 — skip

    // 时间戳: mtime=27, ctime=28, atime=29, crtime=30
    // Use crtime (col 30) as the canonical timestamp
    result.peHeader.timestamp = static_cast<uint32_t>(sqlite3_column_int(stmt, 30));

    // 威胁评分 at col[32]
    result.threatScore = sqlite3_column_int(stmt, 32);

    // LLM分析 (cols 33-35)
    if (sqlite3_column_type(stmt, 33) != SQLITE_NULL)
        result.llmSummary = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 33));
    if (sqlite3_column_type(stmt, 34) != SQLITE_NULL)
        result.llmDescription = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 34));
    if (sqlite3_column_type(stmt, 35) != SQLITE_NULL)
        result.llmKeywords = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 35));

    return result;
}

std::optional<DLLAnalysisResult> DLLAnalysisDatabase::getDLLByInode(int64_t inode) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_BY_INODE, -1, &stmt, nullptr) != SQLITE_OK) {
        return std::nullopt;
    }

    sqlite3_bind_int64(stmt, 1, inode);

    std::optional<DLLAnalysisResult> result;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        result = readDLLFromRow(stmt);
    }

    sqlite3_finalize(stmt);
    return result;
}

std::optional<DLLAnalysisResult> DLLAnalysisDatabase::getDLLByPath(const std::string& path) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_BY_PATH, -1, &stmt, nullptr) != SQLITE_OK) {
        return std::nullopt;
    }

    sqlite3_bind_text(stmt, 1, path.c_str(), -1, SQLITE_STATIC);

    std::optional<DLLAnalysisResult> result;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        result = readDLLFromRow(stmt);
    }

    sqlite3_finalize(stmt);
    return result;
}

std::optional<DLLAnalysisResult> DLLAnalysisDatabase::getDLLById(int64_t dllId) {
    // 使用SELECT_DLL_BY_INODE替代，这里通过id查询
    // 先获取id然后通过inode查，或者直接执行SELECT * WHERE id = ?
    std::string sql = "SELECT * FROM dll_base_info WHERE id = ?";
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        return std::nullopt;
    }

    sqlite3_bind_int64(stmt, 1, dllId);

    std::optional<DLLAnalysisResult> result;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        result = readDLLFromRow(stmt);
    }

    sqlite3_finalize(stmt);
    return result;
}

std::vector<DLLAnalysisResult> DLLAnalysisDatabase::getDLLsByThreatScore(int minScore) {
    std::vector<DLLAnalysisResult> results;
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_SUSPICIOUS_DLLS, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select suspicious DLLs: " << sqlite3_errmsg(db_) << std::endl;
        return results;
    }

    sqlite3_bind_int(stmt, 1, minScore);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        results.push_back(readDLLFromRow(stmt));
    }

    sqlite3_finalize(stmt);
    return results;
}

std::vector<DLLAnalysisResult> DLLAnalysisDatabase::getSuspiciousDLLs(int limit) {
    std::vector<DLLAnalysisResult> results;
    // Strip trailing semicolon/newline from the base SQL before appending LIMIT
    std::string baseSQL = windows_analysis_sql_crud::SELECT_SUSPICIOUS_DLLS;
    while (!baseSQL.empty() && (baseSQL.back() == ';' || baseSQL.back() == '\n' || baseSQL.back() == '\r' || baseSQL.back() == ' '))
        baseSQL.pop_back();
    std::string sql = baseSQL + " LIMIT " + std::to_string(limit);

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select suspicious DLLs: " << sqlite3_errmsg(db_) << std::endl;
        return results;
    }

    sqlite3_bind_int(stmt, 1, 30); // default threshold

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        results.push_back(readDLLFromRow(stmt));
    }

    sqlite3_finalize(stmt);
    return results;
}

std::vector<DLLAnalysisResult> DLLAnalysisDatabase::getAllDLLs(int limit) {
    std::vector<DLLAnalysisResult> results;
    std::string sql = std::string(windows_analysis_sql_crud::SELECT_ALL_DLLS) +
                      " LIMIT " + std::to_string(limit);

    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select all DLLs: " << sqlite3_errmsg(db_) << std::endl;
        return results;
    }

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        results.push_back(readDLLFromRow(stmt));
    }

    sqlite3_finalize(stmt);
    return results;
}

size_t DLLAnalysisDatabase::getDLLCount() {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, "SELECT COUNT(*) FROM dll_base_info;", -1, &stmt, nullptr) != SQLITE_OK) {
        return 0;
    }

    size_t count = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        count = static_cast<size_t>(sqlite3_column_int64(stmt, 0));
    }

    sqlite3_finalize(stmt);
    return count;
}

size_t DLLAnalysisDatabase::getSuspiciousCount() {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_,
        "SELECT COUNT(*) FROM dll_base_info WHERE threat_score >= 30;",
        -1, &stmt, nullptr) != SQLITE_OK) {
        return 0;
    }

    size_t count = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        count = static_cast<size_t>(sqlite3_column_int64(stmt, 0));
    }

    sqlite3_finalize(stmt);
    return count;
}

int DLLAnalysisDatabase::getAverageThreatScore() {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_,
        "SELECT AVG(threat_score) FROM dll_base_info WHERE threat_score > 0;",
        -1, &stmt, nullptr) != SQLITE_OK) {
        return 0;
    }

    int avg = 0;
    if (sqlite3_step(stmt) == SQLITE_ROW) {
        avg = sqlite3_column_int(stmt, 0);
    }

    sqlite3_finalize(stmt);
    return avg;
}

std::vector<PESectionInfo> DLLAnalysisDatabase::getSections(int64_t dllId) {
    std::vector<PESectionInfo> sections;
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_SECTIONS, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select sections statement: " << sqlite3_errmsg(db_) << std::endl;
        return sections;
    }

    sqlite3_bind_int64(stmt, 1, dllId);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        PESectionInfo section;
        section.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        section.virtualAddress = static_cast<uint32_t>(sqlite3_column_int(stmt, 3));
        section.virtualSize = static_cast<uint32_t>(sqlite3_column_int(stmt, 4));
        section.rawDataSize = static_cast<uint32_t>(sqlite3_column_int(stmt, 5));
        section.characteristics = static_cast<uint32_t>(sqlite3_column_int(stmt, 6));
        section.entropy = sqlite3_column_double(stmt, 7);
        section.isWriteable = sqlite3_column_int(stmt, 8) != 0;
        section.isExecutable = sqlite3_column_int(stmt, 9) != 0;
        section.isReadable = sqlite3_column_int(stmt, 10) != 0;
        sections.push_back(section);
    }

    sqlite3_finalize(stmt);
    return sections;
}

std::vector<ImportedDLL> DLLAnalysisDatabase::getImports(int64_t dllId) {
    std::vector<ImportedDLL> imports;
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_IMPORTS, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select imports statement: " << sqlite3_errmsg(db_) << std::endl;
        return imports;
    }

    sqlite3_bind_int64(stmt, 1, dllId);

    std::string currentDLLName;
    ImportedDLL currentImport;

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::string dllName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        std::string funcName = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));

        if (dllName != currentDLLName) {
            if (!currentDLLName.empty()) {
                imports.push_back(currentImport);
            }
            currentDLLName = dllName;
            currentImport = ImportedDLL{dllName, {}, false};
        }
        if (!funcName.empty()) {
            currentImport.functions.push_back(funcName);
        }
    }

    if (!currentDLLName.empty()) {
        imports.push_back(currentImport);
    }

    sqlite3_finalize(stmt);
    return imports;
}

std::vector<ExportedFunction> DLLAnalysisDatabase::getExports(int64_t dllId) {
    std::vector<ExportedFunction> exports;
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_EXPORTS, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select exports statement: " << sqlite3_errmsg(db_) << std::endl;
        return exports;
    }

    sqlite3_bind_int64(stmt, 1, dllId);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        ExportedFunction exp;
        exp.name = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        exp.ordinal = static_cast<uint16_t>(sqlite3_column_int(stmt, 3));
        exp.rva = static_cast<uint32_t>(sqlite3_column_int(stmt, 4));
        exports.push_back(exp);
    }

    sqlite3_finalize(stmt);
    return exports;
}

std::vector<Anomaly> DLLAnalysisDatabase::getAnomalies(int64_t dllId) {
    std::vector<Anomaly> anomalies;
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_ANOMALIES, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select anomalies statement: " << sqlite3_errmsg(db_) << std::endl;
        return anomalies;
    }

    sqlite3_bind_int64(stmt, 1, dllId);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        Anomaly anomaly;
        anomaly.type = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        anomaly.description = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));

        std::string riskStr = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        if (riskStr == "LOW") anomaly.risk = RiskLevel::LOW;
        else if (riskStr == "MEDIUM") anomaly.risk = RiskLevel::MEDIUM;
        else if (riskStr == "HIGH") anomaly.risk = RiskLevel::HIGH;
        else if (riskStr == "CRITICAL") anomaly.risk = RiskLevel::CRITICAL;
        else anomaly.risk = RiskLevel::LOW;

        anomaly.riskScore = sqlite3_column_int(stmt, 5);
        anomalies.push_back(anomaly);
    }

    sqlite3_finalize(stmt);
    return anomalies;
}

std::vector<std::pair<int64_t, int64_t>> DLLAnalysisDatabase::getDependencies(int64_t parentId) {
    std::vector<std::pair<int64_t, int64_t>> deps;
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_DEPENDENCIES, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select dependencies statement: " << sqlite3_errmsg(db_) << std::endl;
        return deps;
    }

    sqlite3_bind_int64(stmt, 1, parentId);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        int64_t childId = sqlite3_column_int64(stmt, 2);
        deps.emplace_back(parentId, childId);
    }

    sqlite3_finalize(stmt);
    return deps;
}

