// DLLAnalysisDatabase.cpp
// 数据库操作实现
//
// This file holds construction, schema setup, and all write operations
// (insert/update). Read-only queries live in DLLAnalysisDatabase_Queries.cpp.

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

    // 文件系统时间戳 (params 27-30) - 使用实际文件时间戳而非PE编译时间戳
    sqlite3_bind_int64(stmt, idx++, result.mtime);  // 修改时间
    sqlite3_bind_int64(stmt, idx++, result.ctime);  // 元数据变更时间
    sqlite3_bind_int64(stmt, idx++, result.atime);  // 访问时间
    sqlite3_bind_int64(stmt, idx++, result.crtime); // 创建时间

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

