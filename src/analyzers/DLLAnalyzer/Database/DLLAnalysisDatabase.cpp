// DLLAnalysisDatabase.cpp
// 数据库操作实现

#include "DLLAnalysisDatabase.h"
#include "../../core/DatabaseManager/SQL/windows_analysis_sql_tables.h"
#include "../../core/DatabaseManager/SQL/windows_analysis_sql_crud.h"
#include "../../core/DatabaseManager/SQL/windows_analysis_sql_llm.h"
#include "../../core/AuditLog/AuditLog.h"
#include <iostream>
#include <sstream>
#include <iomanip>

using namespace forensics::dll;

DLLAnalysisDatabase::DLLAnalysisDatabase(const std::string& dbPath)
    : dbPath_(dbPath), db_(nullptr) {
}

DLLAnalysisDatabase::~DLLAnalysisDatabase() {
    if (db_) {
        sqlite3_close(db_);
    }
}

bool DLLAnalysisDatabase::initialize() {
    AuditLog::instance().log("SYSTEM", "DLL_DB_INIT", "Initializing DLL analysis database: " + dbPath_);

    int rc = sqlite3_open(dbPath_.c_str(), &db_);
    if (rc != SQLITE_OK) {
        std::cerr << "Cannot open DLL database: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    // 启用外键约束
    sqlite3_exec(db_, "PRAGMA foreign_keys = ON;", nullptr, nullptr, nullptr);

    if (!createTables() || !createIndices()) {
        return false;
    }

    AuditLog::instance().log("SYSTEM", "DLL_DB_INIT_COMPLETE", "DLL database initialized");
    return true;
}

bool DLLAnalysisDatabase::createTables() {
    // CREATE_ALL_TABLES includes all Windows tables + DLL tables in one statement
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, windows_analysis_sql_tables::CREATE_ALL_TABLES,
                          nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create tables: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    return true;
}

bool DLLAnalysisDatabase::createIndices() {
    char* errMsg = nullptr;
    int rc = sqlite3_exec(db_, windows_analysis_sql_tables::CREATE_DLL_INDICES, nullptr, nullptr, &errMsg);
    if (rc != SQLITE_OK) {
        std::cerr << "Failed to create DLL indices: " << errMsg << std::endl;
        sqlite3_free(errMsg);
        return false;
    }
    return true;
}

// ========================================================================
// DLL基础信息操作
// ========================================================================

int64_t DLLAnalysisDatabase::insertDLLBaseInfo(const DLLAnalysisResult& result) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_BASE_INFO, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert statement: " << sqlite3_errmsg(db_) << std::endl;
        return -1;
    }

    // 绑定参数（共32个，对应INSERT语句的32个?占位符）
    int idx = 1;
    sqlite3_bind_int64(stmt, idx++, result.inode);
    sqlite3_bind_text(stmt, idx++, result.fileName.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.filePath.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int64(stmt, idx++, static_cast<int64_t>(result.fileSize));
    sqlite3_bind_text(stmt, idx++, result.md5Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.sha1Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.sha256Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.impHash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_null(stmt, idx++); // rich_hash (not yet collected)

    // PE元数据 (params 10-17)
    sqlite3_bind_text(stmt, idx++, result.peHeader.format.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, machineTypeToString(result.peHeader.machine).c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, idx++, static_cast<int>(result.peHeader.timestamp));
    sqlite3_bind_int(stmt, idx++, static_cast<int>(result.peHeader.subsystem));
    sqlite3_bind_int(stmt, idx++, static_cast<int>(result.peHeader.entryPointRVA));
    sqlite3_bind_int64(stmt, idx++, static_cast<int64_t>(result.peHeader.imageBase));
    sqlite3_bind_int(stmt, idx++, result.peHeader.isDLL ? 1 : 0);
    sqlite3_bind_int(stmt, idx++, static_cast<int>(result.peHeader.characteristics));

    // 版本信息 (params 17-20)
    sqlite3_bind_text(stmt, idx++, result.fileVersion.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.productVersion.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.companyName.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.fileDescription.c_str(), -1, SQLITE_STATIC);

    // 数字签名 (params 21-26)
    sqlite3_bind_text(stmt, idx++, result.signatureStatus.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.signerName.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_null(stmt, idx++); // cert_issuer
    sqlite3_bind_null(stmt, idx++); // cert_valid_from
    sqlite3_bind_null(stmt, idx++); // cert_valid_to

    // 时间戳 (params 27-30)
    sqlite3_bind_int64(stmt, idx++, static_cast<int64_t>(result.peHeader.timestamp)); // mtime
    sqlite3_bind_int64(stmt, idx++, static_cast<int64_t>(result.peHeader.timestamp)); // ctime
    sqlite3_bind_int64(stmt, idx++, static_cast<int64_t>(result.peHeader.timestamp)); // atime
    sqlite3_bind_int64(stmt, idx++, static_cast<int64_t>(result.peHeader.timestamp)); // crtime

    // 取证关联 (params 31-32)
    sqlite3_bind_int(stmt, idx++, 0); // is_deleted
    sqlite3_bind_int(stmt, idx++, result.threatScore);

    if (sqlite3_step(stmt) != SQLITE_DONE) {
        std::cerr << "Failed to insert DLL base info: " << sqlite3_errmsg(db_) << std::endl;
        sqlite3_finalize(stmt);
        return -1;
    }

    int64_t rowId = sqlite3_last_insert_rowid(db_);
    sqlite3_finalize(stmt);
    return rowId;
}

bool DLLAnalysisDatabase::updateDLLAnalysis(int64_t dllId, const DLLAnalysisResult& result) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::UPDATE_DLL_ANALYSIS, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare update statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    int idx = 1;
    // UPDATE_DLL_ANALYSIS has 19 parameters (18 SET columns + WHERE id = ?)
    // 1-7:  file_format, machine_type, compile_timestamp, subsystem, entry_point, image_base, characteristics
    // 8-11: file_version, product_version, company_name, file_description (not stored, null)
    // 12-13: signature_status, signer_name
    // 14-16: md5, sha1, sha256
    // 17:    imp_hash
    // 18:    threat_score
    // 19:    WHERE id = ?
    // params 1-18: SET columns
    sqlite3_bind_text(stmt, idx++, result.peHeader.format.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, machineTypeToString(result.peHeader.machine).c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, idx++, static_cast<int>(result.peHeader.timestamp));
    sqlite3_bind_int(stmt, idx++, static_cast<int>(result.peHeader.subsystem));
    sqlite3_bind_int(stmt, idx++, static_cast<int>(result.peHeader.entryPointRVA));
    sqlite3_bind_int64(stmt, idx++, static_cast<int64_t>(result.peHeader.imageBase));
    sqlite3_bind_int(stmt, idx++, static_cast<int>(result.peHeader.characteristics));
    sqlite3_bind_null(stmt, idx++); // file_version
    sqlite3_bind_null(stmt, idx++); // product_version
    sqlite3_bind_null(stmt, idx++); // company_name
    sqlite3_bind_null(stmt, idx++); // file_description
    sqlite3_bind_text(stmt, idx++, result.signatureStatus.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_null(stmt, idx++); // signer_name
    sqlite3_bind_text(stmt, idx++, result.md5Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.sha1Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.sha256Hash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, result.impHash.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, idx++, result.threatScore);

    // WHERE id = ?
    sqlite3_bind_int64(stmt, idx++, dllId);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

bool DLLAnalysisDatabase::updateThreatScore(int64_t dllId, int score) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::UPDATE_DLL_THREAT_SCORE, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare update threat score statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    sqlite3_bind_int(stmt, 1, score);
    sqlite3_bind_int64(stmt, 2, dllId);

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

// ========================================================================
// 节表操作
// ========================================================================

bool DLLAnalysisDatabase::insertSections(int64_t dllId, const std::vector<PESectionInfo>& sections) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_SECTION, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert section statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    for (const auto& section : sections) {
        sqlite3_reset(stmt);
        sqlite3_clear_bindings(stmt);

        int idx = 1;
        sqlite3_bind_int64(stmt, idx++, dllId);
        sqlite3_bind_text(stmt, idx++, section.name.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_int(stmt, idx++, static_cast<int>(section.virtualAddress));
        sqlite3_bind_int(stmt, idx++, static_cast<int>(section.virtualSize));
        sqlite3_bind_int(stmt, idx++, static_cast<int>(section.rawDataSize));
        sqlite3_bind_int(stmt, idx++, static_cast<int>(section.characteristics));
        sqlite3_bind_double(stmt, idx++, section.entropy);
        sqlite3_bind_int(stmt, idx++, section.isWriteable ? 1 : 0);
        sqlite3_bind_int(stmt, idx++, section.isExecutable ? 1 : 0);
        sqlite3_bind_int(stmt, idx++, section.isReadable ? 1 : 0);

        if (sqlite3_step(stmt) != SQLITE_DONE) {
            std::cerr << "Failed to insert section: " << sqlite3_errmsg(db_) << std::endl;
            sqlite3_finalize(stmt);
            return false;
        }
    }

    sqlite3_finalize(stmt);
    return true;
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

// ========================================================================
// 导入/导出操作
// ========================================================================

bool DLLAnalysisDatabase::insertImports(int64_t dllId, const std::vector<ImportedDLL>& imports) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_IMPORT, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert import statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    for (const auto& importedDLL : imports) {
        for (const auto& func : importedDLL.functions) {
            sqlite3_reset(stmt);
            sqlite3_clear_bindings(stmt);

            int idx = 1;
            sqlite3_bind_int64(stmt, idx++, dllId);
            sqlite3_bind_text(stmt, idx++, importedDLL.name.c_str(), -1, SQLITE_STATIC);
            sqlite3_bind_text(stmt, idx++, func.c_str(), -1, SQLITE_STATIC);
            sqlite3_bind_null(stmt, idx++); // import_ordinal
            sqlite3_bind_int(stmt, idx++, importedDLL.isDelayed ? 1 : 0);

            if (sqlite3_step(stmt) != SQLITE_DONE) {
                std::cerr << "Failed to insert import: " << sqlite3_errmsg(db_) << std::endl;
                sqlite3_finalize(stmt);
                return false;
            }
        }
    }

    sqlite3_finalize(stmt);
    return true;
}

bool DLLAnalysisDatabase::insertExports(int64_t dllId, const std::vector<ExportedFunction>& exports) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_EXPORT, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert export statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    for (const auto& exp : exports) {
        sqlite3_reset(stmt);
        sqlite3_clear_bindings(stmt);

        int idx = 1;
        sqlite3_bind_int64(stmt, idx++, dllId);
        sqlite3_bind_text(stmt, idx++, exp.name.c_str(), -1, SQLITE_STATIC);
        sqlite3_bind_int(stmt, idx++, static_cast<int>(exp.ordinal));
        sqlite3_bind_int(stmt, idx++, static_cast<int>(exp.rva));

        if (sqlite3_step(stmt) != SQLITE_DONE) {
            std::cerr << "Failed to insert export: " << sqlite3_errmsg(db_) << std::endl;
            sqlite3_finalize(stmt);
            return false;
        }
    }

    sqlite3_finalize(stmt);
    return true;
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

// ========================================================================
// 异常检测操作
// ========================================================================

bool DLLAnalysisDatabase::insertAnomaly(int64_t dllId, const Anomaly& anomaly) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_ANOMALY, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert anomaly statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    int idx = 1;
    sqlite3_bind_int64(stmt, idx++, dllId);
    sqlite3_bind_text(stmt, idx++, anomaly.type.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, anomaly.description.c_str(), -1, SQLITE_STATIC);

    // RiskLevel enum to string
    std::string riskStr;
    switch (anomaly.risk) {
        case RiskLevel::LOW: riskStr = "LOW"; break;
        case RiskLevel::MEDIUM: riskStr = "MEDIUM"; break;
        case RiskLevel::HIGH: riskStr = "HIGH"; break;
        case RiskLevel::CRITICAL: riskStr = "CRITICAL"; break;
        default: riskStr = "UNKNOWN"; break;
    }
    sqlite3_bind_text(stmt, idx++, riskStr.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_int(stmt, idx++, anomaly.riskScore);
    sqlite3_bind_null(stmt, idx++); // details

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
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

// ========================================================================
// 依赖关系操作
// ========================================================================

bool DLLAnalysisDatabase::insertDependency(int64_t parentId, int64_t childId, int depth) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_DEPENDENCY, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert dependency statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    int idx = 1;
    sqlite3_bind_int64(stmt, idx++, parentId);
    sqlite3_bind_int64(stmt, idx++, childId);
    sqlite3_bind_int(stmt, idx++, depth);
    sqlite3_bind_int(stmt, idx++, 1); // is_resolved = true

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
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

// ========================================================================
// 取证关联操作
// ========================================================================

bool DLLAnalysisDatabase::insertForensicLink(int64_t dllId, const std::string& linkType,
                                             const std::string& sourceId, const std::string& sourceData) {
    sqlite3_stmt* stmt;
    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::INSERT_DLL_FORENSIC_LINK, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare insert forensic link statement: " << sqlite3_errmsg(db_) << std::endl;
        return false;
    }

    int idx = 1;
    sqlite3_bind_int64(stmt, idx++, dllId);
    sqlite3_bind_text(stmt, idx++, linkType.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, sourceId.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_text(stmt, idx++, sourceData.c_str(), -1, SQLITE_STATIC);
    sqlite3_bind_null(stmt, idx++); // detected_at

    bool success = (sqlite3_step(stmt) == SQLITE_DONE);
    sqlite3_finalize(stmt);
    return success;
}

std::vector<std::tuple<std::string, std::string, std::string>>
DLLAnalysisDatabase::getForensicLinks(int64_t dllId) {
    std::vector<std::tuple<std::string, std::string, std::string>> links;
    sqlite3_stmt* stmt;

    if (sqlite3_prepare_v2(db_, windows_analysis_sql_crud::SELECT_DLL_FORENSIC_LINKS, -1, &stmt, nullptr) != SQLITE_OK) {
        std::cerr << "Failed to prepare select forensic links statement: " << sqlite3_errmsg(db_) << std::endl;
        return links;
    }

    sqlite3_bind_int64(stmt, 1, dllId);

    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::string linkType = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 2));
        std::string sourceId = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 3));
        std::string sourceData = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 4));
        links.emplace_back(linkType, sourceId, sourceData);
    }

    sqlite3_finalize(stmt);
    return links;
}

// ========================================================================
// 查询操作
// ========================================================================

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

// ========================================================================
// 统计操作
// ========================================================================

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

// ========================================================================
// 工具方法
// ========================================================================

std::string DLLAnalysisDatabase::machineTypeToString(MachineType type) {
    switch (type) {
        case MachineType::X86: return "x86";
        case MachineType::x64: return "x64";
        case MachineType::ARM: return "ARM";
        case MachineType::ARM64: return "ARM64";
        case MachineType::IA64: return "IA64";
        default: return "Unknown";
    }
}

MachineType DLLAnalysisDatabase::machineTypeFromString(const std::string& str) {
    if (str == "x86") return MachineType::X86;
    if (str == "x64") return MachineType::x64;
    if (str == "ARM") return MachineType::ARM;
    if (str == "ARM64") return MachineType::ARM64;
    if (str == "IA64") return MachineType::IA64;
    return MachineType::UNKNOWN;
}
