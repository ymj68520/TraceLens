// MobileEvidenceMeiyaAdapter.cpp
// 美亚 TBL_PR_* → 统一取数包。

#include "MobileEvidenceMeiyaAdapter.h"

#include <sqlite3.h>

#include <algorithm>
#include <cctype>
#include <ctime>
#include <filesystem>
#include <map>
#include <memory>
#include <set>
#include <string>
#include <system_error>
#include <vector>

#include <nlohmann/json.hpp>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace mobile_evidence {
namespace {

using Statement = std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)>;

std::string text(sqlite3_stmt* statement, int column) {
    const unsigned char* value = sqlite3_column_text(statement, column);
    return value ? reinterpret_cast<const char*>(value) : std::string{};
}

// 美亚时间统一是 "YYYY-MM-DD HH:MM:SS" 的本地时间，无时区标记。
// 原样保留 timestamp_raw，规范化秒值按 UTC 解析仅用于排序。
bool parseMeiyaTime(const std::string& input, std::int64_t& seconds) {
    if (input.size() < 19) return false;
    std::tm tm{};
    if (std::sscanf(input.c_str(), "%4d-%2d-%2d %2d:%2d:%2d",
                    &tm.tm_year, &tm.tm_mon, &tm.tm_mday,
                    &tm.tm_hour, &tm.tm_min, &tm.tm_sec) != 6) {
        return false;
    }
    tm.tm_year -= 1900;
    tm.tm_mon -= 1;
    tm.tm_isdst = 0;
#ifdef _WIN32
    seconds = _mkgmtime(&tm);
#else
    seconds = timegm(&tm);
#endif
    return true;
}

// 通用单行读取：把一整行导成 JSON（保留全部列），同时给出规范化投影。
json rowToJson(sqlite3_stmt* statement) {
    json row = json::object();
    const int columns = sqlite3_column_count(statement);
    for (int index = 0; index < columns; ++index) {
        const std::string name = sqlite3_column_name(statement, index);
        switch (sqlite3_column_type(statement, index)) {
            case SQLITE_NULL:
                row[name] = nullptr;
                break;
            case SQLITE_INTEGER:
                row[name] = sqlite3_column_int64(statement, index);
                break;
            case SQLITE_FLOAT:
                row[name] = sqlite3_column_double(statement, index);
                break;
            case SQLITE_BLOB:
                row[name] = json{{"__blob_bytes", sqlite3_column_bytes(statement, index)}};
                break;
            default:
                row[name] = text(statement, index);
                break;
        }
    }
    return row;
}

struct TableMapping {
    const char* table;
    const char* kind;
    // 关键列（规范化投影）
    std::vector<const char*> payloadKeys;
    // 时间列（原文）
    const char* timeColumn;
};

// 只映射语义明确的规范化表；其余表仍以 coverage 声明"已盘点未映射"。
const std::vector<TableMapping>& mappings() {
    static const std::vector<TableMapping> table = {
        {"TBL_PR_SMS_INFO", kind::kSms,
         {"strSMSPhoneNum", "strSMSContents", "dwSMSType", "dwReadStatus", "dwDeleted",
          "strSMSCenter", "strSMSName"},
         "strSMSSentAt"},
        {"TBL_PR_CONTACT_INFO", kind::kContact,
         {"strContactName", "strContactMobilePhone", "strContactHomePhone",
          "strContactWorkPhone", "strContactCustomedNumber", "strContactOtherPhone",
          "strContactNickname", "strNote"},
         "strLastUpdatedTime"},
        {"TBL_PR_DIALOG_INFO", kind::kCallLog,
         {"strDialogPhoneNum", "strDialogName", "dwDialogDuration", "dwDialogType",
          "dwDeleted", "strDialogLocation"},
         "strDialogInitiatedAt"},
        {"TBL_PR_NOTES_INFO", kind::kNote,
         {"strContents", "strTitle", "strPath", "dwDeleted"},
         "strCreated"},
        {"TBL_PR_CALENDAR_INFO", kind::kCalendarEvent,
         {"strCalendarTitle", "strCalendarContents", "strCalendarLocation",
          "strCalendarStartTime", "strCalendarEndDate1", "strCalendarType"},
         "strCalendarStartTime"},
        {"TBL_PR_WIFI_LINK_NET_INFO", kind::kWifiNetwork,
         {"strName", "strMAC", "strEncAlgorithm", "strIpAddress", "strLinkType"},
         "strJoinTime"},
        {"TBL_PR_WIFI_PASSWD_INFO", kind::kWifiNetwork,
         {"strName", "strPassWord", "strAlgorithm"},
         nullptr},
        {"TBL_PR_INSTALL_INFO", kind::kInstalledApp,
         {"strName", "strPackageName", "strVersion", "strType", "iSize", "strPath",
          "strInstallerName"},
         "strUpdateDate"},
        {"TBL_PR_MEDIA_INFO", kind::kMediaFile,
         {"strFileName", "strFilePath", "dwFileSize", "iMediaType", "strAlbum",
          "strMediaFileMd5"},
         "strFileModifiedDate"},
        {"TBL_PR_FILE_DOCUMENT_INFO", kind::kDocumentFile,
         {"strFileName", "strFilePath", "dwFileSize"},
         "strFileModifiedDate"},
        {"TBL_PR_SYS_ACCOUNT_INFO", kind::kAccount,
         {"strName", "strType", "strPassWord"},
         nullptr},
        {"TBL_PR_SYS_BOOT_TIME_INFO", kind::kSystemLog,
         {"strBootTime", "strBootType", "strBootReason"},
         "strBootTime"},
        {"TBL_PR_BT_INFO", kind::kGeneric,
         {"strName", "strMAC", "strDeviceType"},
         "strLastConnectTime"},
    };
    return table;
}

bool tableExists(sqlite3* db, const std::string& table) {
    Statement statement(nullptr, sqlite3_finalize);
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                           -1, &raw, nullptr) != SQLITE_OK) {
        return false;
    }
    statement.reset(raw);
    sqlite3_bind_text(statement.get(), 1, table.c_str(), -1, SQLITE_TRANSIENT);
    return sqlite3_step(statement.get()) == SQLITE_ROW;
}

std::uint64_t tableRows(sqlite3* db, const std::string& table) {
    const std::string sql = "SELECT COUNT(*) FROM \"" + table + "\"";
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &raw, nullptr) != SQLITE_OK) return 0;
    Statement statement(raw, sqlite3_finalize);
    if (sqlite3_step(statement.get()) != SQLITE_ROW) return 0;
    return static_cast<std::uint64_t>(sqlite3_column_int64(statement.get(), 0));
}

void addCoverage(Package& package, const std::string& artifactKind,
                 const std::string& sourcePath, const std::string& state,
                 const std::string& detail, std::uint64_t count = 0) {
    Coverage entry;
    entry.artifactKind = artifactKind;
    entry.sourcePath = sourcePath;
    entry.status = state;
    entry.detail = detail;
    entry.recordCount = count;
    package.coverage.push_back(std::move(entry));
}

// 把一个 TBL_PR_* 表整体导出为统一记录。
std::uint64_t exportTable(Package& package, sqlite3* db, const TableMapping& mapping,
                          const std::string& containerName, const std::string& deviceSerial,
                          const std::string& parserVersion, std::uint64_t rowLimit,
                          std::string& error) {
    if (!tableExists(db, mapping.table)) {
        addCoverage(package, mapping.kind, mapping.table, "not_found",
                    "table absent in " + containerName);
        return 0;
    }

    const std::string sql = "SELECT * FROM \"" + std::string(mapping.table) + "\"";
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &raw, nullptr) != SQLITE_OK) {
        error = sqlite3_errmsg(db);
        return 0;
    }
    Statement statement(raw, sqlite3_finalize);

    std::uint64_t written = 0;
    while (sqlite3_step(statement.get()) == SQLITE_ROW) {
        if (rowLimit != 0 && written >= rowLimit) break;

        const json full = rowToJson(statement.get());
        json payload = json::object();
        for (const char* key : mapping.payloadKeys) {
            if (full.contains(key)) payload[key] = full[key];
        }

        Record record;
        record.kind = mapping.kind;
        record.packageName = "meiya";  // 规范化层由美亚产生，非单一应用
        record.sourcePath = containerName + ":" + mapping.table;
        record.sourceTable = mapping.table;
        // 用行内的 ID 作稳定键；无 ID 时退回行序号。
        if (full.contains("ID") && !full["ID"].is_null()) {
            record.sourceKey = full["ID"].is_string() ? full["ID"].get<std::string>()
                                                      : full["ID"].dump();
        } else {
            record.sourceKey = std::to_string(written + 1);
        }
        record.rawJson = full.dump();
        record.payloadJson = payload.dump();
        record.parserVersion = parserVersion;
        record.status = status::kParsed;

        if (mapping.timeColumn && full.contains(mapping.timeColumn) &&
            full[mapping.timeColumn].is_string()) {
            const std::string rawTime = full[mapping.timeColumn].get<std::string>();
            if (!rawTime.empty()) {
                record.timestampRaw = rawTime;
                record.timestampUnit = time_unit::kText;
                std::int64_t seconds = 0;
                if (parseMeiyaTime(rawTime, seconds)) {
                    record.timestampSeconds = seconds;
                    record.timestampUnit = time_unit::kSeconds;
                }
            }
        }

        package.records.push_back(std::move(record));
        ++written;
    }

    const std::string detail = "device=" + deviceSerial +
        "; container=" + containerName + "; table=" + mapping.table;
    addCoverage(package, mapping.kind, mapping.table,
                written > 0 ? status::kParsed : "empty", detail, written);
    return written;
}

// 案件库：只取案件与设备信息（不做逐行业务导出）。
void exportCaseIdentity(Package& package, const meiya::DecryptedContainer& container,
                        const std::string& parserVersion) {
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(container.decryptedPath.string().c_str(), &db, SQLITE_OPEN_READONLY,
                        nullptr) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return;
    }

    const char* sql =
        "SELECT strName, strCaseNo, strCaseType, strInvestigator, strPoliceNo, "
        "strPath, strCreateTime FROM TBL_GJ_CASE_INFO LIMIT 1";
    sqlite3_stmt* raw = nullptr;
    if (sqlite3_prepare_v2(db, sql, -1, &raw, nullptr) == SQLITE_OK) {
        Statement statement(raw, sqlite3_finalize);
        if (sqlite3_step(statement.get()) == SQLITE_ROW) {
            const json row = rowToJson(statement.get());
            Record record;
            record.kind = kind::kGeneric;
            record.packageName = "meiya";
            record.sourcePath = container.sourcePath.filename().string() + ":TBL_GJ_CASE_INFO";
            record.sourceTable = "TBL_GJ_CASE_INFO";
            record.sourceKey = "case";
            record.rawJson = row.dump();
            record.payloadJson = row.dump();
            record.parserVersion = parserVersion;
            record.status = status::kParsed;
            package.records.push_back(std::move(record));

            // 案件元数据同时进设备/采集信息，便于报告直接引用。
            if (row.contains("strName") && row["strName"].is_string()) {
                package.acquisition.notes += "case=" + row["strName"].get<std::string>() + "; ";
            }
            addCoverage(package, "case_identity", record.sourcePath, status::kParsed,
                        "case metadata from TBL_GJ_CASE_INFO", 1);
        }
    }
    sqlite3_close(db);
}

}  // namespace

bool buildPackageFromMeiya(const meiya::MeiyaBackupExtractor& source,
                           const MeiyaAdapterOptions& options,
                           Package& out) {
    out = Package{};
    out.acquisition.adapterName = "meiya-mobilemaster";
    out.acquisition.adapterVersion = options.adapterVersion;
    out.acquisition.sourceType = "meiya-case";
    out.acquisition.sourcePath = source.caseRoot();
    out.device.platform = "android";

    // 案件身份
    if (const auto* caseContainer = source.findContainer("case")) {
        exportCaseIdentity(out, *caseContainer, options.adapterVersion);
        addCoverage(out, "case_container", caseContainer->sourcePath.filename().string(),
                    status::kParsed,
                    "mask=" + caseContainer->encryptionLabel +
                        "; schema_entries=" + std::to_string(caseContainer->schemaEntries));
    }

    // 设备信息
    std::string deviceSerial;
    std::string manufacturer;
    std::string model;
    std::string imei;
    for (const auto& device : source.devices()) {
        if (deviceSerial.empty()) {
            deviceSerial = device.serial;
            manufacturer = device.manufacturer;
            model = device.model;
            imei = device.imei;
        }
        addCoverage(out, "device_info", device.sourceContainer, status::kParsed,
                    "serial=" + device.serial + "; model=" + device.model +
                        "; imei=" + device.imei);
    }
    if (!source.devices().empty()) {
        out.device.manufacturer = manufacturer;
        out.device.model = model;
        out.device.imei = imei;
        out.device.serialNumber = deviceSerial;
        out.device.extraJson = json{
            {"meiya_devices", json::array()},
        }.dump();
        json devices = json::array();
        for (const auto& device : source.devices()) {
            devices.push_back({
                {"serial", device.serial},
                {"manufacturer", device.manufacturer},
                {"model", device.model},
                {"imei", device.imei},
                {"mac", device.mac},
                {"bluetooth_mac", device.bluetoothMac},
                {"characteristic", device.characteristic},
                {"container", device.sourceContainer},
            });
        }
        out.device.extraJson = json{{"meiya_devices", devices}}.dump();
    }

    // 各设备规范化库
    for (const auto* container : source.findContainers("device")) {
        sqlite3* db = nullptr;
        if (sqlite3_open_v2(container->decryptedPath.string().c_str(), &db,
                            SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
            if (db) sqlite3_close(db);
            addCoverage(out, "device_container", container->sourcePath.filename().string(),
                        status::kFailed, "cannot open decrypted container");
            continue;
        }

        const std::string serial =
            container->sourcePath.stem().string();  // GM1910.dmf → GM1910
        std::string error;
        for (const auto& mapping : mappings()) {
            exportTable(out, db, mapping, container->sourcePath.filename().string(), serial,
                        options.adapterVersion, options.maximumRowsPerTable, error);
            if (!error.empty()) {
                addCoverage(out, mapping.kind, mapping.table, status::kFailed, error);
                error.clear();
            }
        }

        // 规范化层已覆盖，但表清单仍要声明：未映射的表不是"没有数据"。
        sqlite3_stmt* raw = nullptr;
        std::set<std::string> mapped;
        for (const auto& mapping : mappings()) mapped.insert(mapping.table);
        if (sqlite3_prepare_v2(db,
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'TBL_PR_%'",
                -1, &raw, nullptr) == SQLITE_OK) {
            Statement statement(raw, sqlite3_finalize);
            while (sqlite3_step(statement.get()) == SQLITE_ROW) {
                const std::string table = text(statement.get(), 0);
                if (mapped.count(table)) continue;
                const std::uint64_t rows = tableRows(db, table);
                addCoverage(out, "unmapped_table", table, status::kUnsupported,
                            "device=" + serial + "; rows=" + std::to_string(rows), rows);
            }
        }
        sqlite3_close(db);
    }

    // 未逐行解析的容器（应用库、审计流水）登记在文件清单里。
    if (options.inventoryApplicationDatabases) {
        for (const auto& container : source.containers()) {
            if (container.family == "device" || container.family == "case") continue;
            if (container.status != "decrypted") {
                addCoverage(out, "container_" + container.family,
                            container.sourcePath.filename().string(), status::kLocked,
                            container.detail);
                continue;
            }
            FileEntry entry;
            entry.relativePath = container.sourcePath.filename().string();
            entry.fileName = container.sourcePath.filename().string();
            entry.extension = container.sourcePath.extension().string();
            if (!entry.extension.empty() && entry.extension.front() == '.') {
                entry.extension.erase(0, 1);
            }
            entry.category = "database";
            entry.packageName = container.deviceSerial;
            entry.size = container.containerSize;
            entry.status = status::kUnsupported;  // 已解密，行级解析由应用层扩展
            out.files.push_back(std::move(entry));
        }
    }

    // 每个统一类别都要有覆盖度结论，避免下游把空表读成"设备没有"。
    std::set<std::string> produced;
    for (const auto& record : out.records) produced.insert(record.kind);
    for (const char* expected : {kind::kSms, kind::kContact, kind::kCallLog, kind::kNote,
                                 kind::kCalendarEvent, kind::kWifiNetwork,
                                 kind::kInstalledApp, kind::kMediaFile, kind::kAccount}) {
        if (produced.count(expected)) continue;
        addCoverage(out, expected, "<meiya-case>", "no_candidate_path",
                    "No rows of this kind were produced by the Meiya adapter");
    }

    return true;
}

}  // namespace mobile_evidence
