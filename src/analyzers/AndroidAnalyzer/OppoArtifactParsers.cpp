#include "OppoArtifactParsers.h"
#include "AndroidAnalysisDatabase.h"
#include "MobileBackupSchema.h"
#include "OppoBackupExtractor.h"
#include <openssl/evp.h>
#include <algorithm>
#include <array>
#include <cstdio>
#include <cstring>
#include <fstream>
#include <optional>
#include <sstream>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {

constexpr const char* kParserVersion = "oppo-thunderforensic-v1";
constexpr const char* kManifestMember = "ThunderForensic.json";
constexpr const char* kPhoneDataPrefix = "PhoneData/";
constexpr const char* kLogDataPrefix = "LogData/";
// Bounds artifact growth for a hostile or runaway container.
constexpr std::size_t kMaxArtifactRows = 1000000;
constexpr std::uint64_t kMaxMemberJsonBytes = 64ULL << 20;

std::string scalar(const json& item, std::initializer_list<const char*> keys) {
    for (const char* key : keys) {
        if (!item.contains(key) || item[key].is_null()) continue;
        const json& value = item[key];
        if (value.is_string()) return value.get<std::string>();
        return value.dump();
    }
    return {};
}

std::string serialized(const json& value) {
    return value.dump(-1, ' ', false, json::error_handler_t::replace);
}

// Days-from-civil (Howard Hinnant) to avoid locale-dependent time parsing.
std::int64_t daysFromCivil(std::int64_t year, unsigned month, unsigned day) {
    year -= month <= 2;
    const std::int64_t era = (year >= 0 ? year : year - 399) / 400;
    const unsigned yearOfEra = static_cast<unsigned>(year - era * 400);
    const unsigned dayOfYear = (153 * (month + (month > 2 ? -3 : 9)) + 2) / 5 + day - 1;
    const unsigned dayOfEra = yearOfEra * 365 + yearOfEra / 4 - yearOfEra / 100 + dayOfYear;
    return era * 146097 + static_cast<std::int64_t>(dayOfEra) - 719468;
}

bool readUtcParts(const std::string& text, std::int64_t& epochSeconds) {
    int year = 0, month = 0, day = 0, hour = 0, minute = 0, second = 0;
    char separator = 0;
    std::istringstream in(text);
    in >> year;
    if (in.peek() != '-') return false;
    in.ignore();
    in >> month;
    if (in.peek() != '-') return false;
    in.ignore();
    in >> day;
    in >> separator;
    if (separator != 'T' && separator != ' ') return false;
    in >> hour;
    if (in.peek() != ':') return false;
    in.ignore();
    in >> minute;
    if (in.peek() != ':') return false;
    in.ignore();
    in >> second;
    if (in.fail() || month < 1 || month > 12 || day < 1 || day > 31 || hour > 23 || minute > 59 ||
        second > 60)
        return false;
    std::int64_t days = daysFromCivil(year, static_cast<unsigned>(month),
                                      static_cast<unsigned>(day));
    epochSeconds = days * 86400 + hour * 3600 + minute * 60 + second;
    // Apply the trailing zone offset (Z or ±HH:MM); the default is UTC.
    const std::streamoff consumed = in.tellg();
    if (consumed < 0) return true;
    const std::size_t position = std::min<std::size_t>(static_cast<std::size_t>(consumed),
                                                       text.size());
    const std::string rest = text.substr(position);
    if (!rest.empty() && (rest[0] == '+' || rest[0] == '-')) {
        int zoneHour = 0, zoneMinute = 0;
        if (std::sscanf(rest.c_str(), "%3d:%2d", &zoneHour, &zoneMinute) == 2) {
            const std::int64_t offset =
                zoneHour * 3600 + (zoneHour < 0 ? -zoneMinute : zoneMinute) * 60;
            epochSeconds -= offset;
        }
    }
    return true;
}

std::optional<std::int64_t> parseIsoToSeconds(const std::string& text) {
    if (text.size() < 19) return std::nullopt;
    std::int64_t seconds = 0;
    if (!readUtcParts(text, seconds)) return std::nullopt;
    return seconds;
}

std::string memberKindFor(const std::string& memberName) {
    const std::string stem = fs::path(memberName).stem().string();
    if (stem == "deviceinfo") return "device_info";
    if (stem == "imei") return "device_identifier";
    if (stem == "application") return "application";
    if (stem == "uninstalllist") return "uninstall_list";
    if (stem == "app_traffic") return "app_traffic";
    if (stem == "appusagedetail") return "app_usage_session";
    if (stem == "wifi") return "wifi";
    if (stem == "image_extractor" || stem == "video_extractor" || stem == "audio_extractor")
        return "media";
    if (stem == "contacts") return "contact";
    if (stem == "calllogs") return "call_log";
    if (stem == "smss") return "sms";
    if (stem == "mmss") return "mms";
    if (stem == "calendar") return "calendar_event";
    if (stem == "siminfo") return "sim_info";
    if (stem == "simstate") return "sim_state";
    if (stem == "bluetooth") return "bluetooth";
    if (stem == "doc_extractor") return "document";
    return "phone_data:" + stem;
}

std::string bytesSha256(const std::string& bytes) {
    unsigned char digest[EVP_MAX_MD_SIZE];
    unsigned size = 0;
    std::unique_ptr<EVP_MD_CTX, decltype(&EVP_MD_CTX_free)> context(EVP_MD_CTX_new(),
                                                                    EVP_MD_CTX_free);
    if (!context || EVP_DigestInit_ex(context.get(), EVP_sha256(), nullptr) != 1 ||
        EVP_DigestUpdate(context.get(), bytes.data(), bytes.size()) != 1 ||
        EVP_DigestFinal_ex(context.get(), digest, &size) != 1)
        return {};
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (unsigned i = 0; i < size; ++i) out << std::setw(2) << unsigned(digest[i]);
    return out.str();
}

std::string wifiSsidDisplay(std::string ssid) {
    // ThunderForensic keeps the raw quoted form ("Pixel_9577bn"); store the
    // human-readable network name like the standard WifiConfigStore parser.
    if (ssid.size() >= 2 && ssid.front() == '"' && ssid.back() == '"')
        return ssid.substr(1, ssid.size() - 2);
    return ssid;
}

// Maps ThunderForensic list items onto the standard artifact tables when the
// field names are recognizable. Field spellings beyond this sample are
// unknown; unrecognized items stay in mobile_artifacts with their raw JSON.
bool fillContactRecord(const json& item, std::map<std::string, std::string>& record) {
    const std::string name = scalar(item, {"Name", "name", "DisplayName", "display_name"});
    const std::string phone = scalar(item, {"Phone", "phone", "PhoneNumber", "phone_number",
                                            "Number", "number", "Mobile", "mobile"});
    if (name.empty() && phone.empty()) return false;
    record["display_name"] = name;
    record["phone"] = phone;
    return true;
}

bool fillCallRecord(const json& item, std::map<std::string, std::string>& record) {
    const std::string number = scalar(item, {"Number", "number", "PhoneNumber", "Phone", "phone"});
    if (number.empty()) return false;
    record["number"] = number;
    record["date"] = scalar(item, {"Date", "date", "Time", "time", "DateMs", "date_ms"});
    record["duration"] = scalar(item, {"Duration", "duration"});
    record["type"] = scalar(item, {"Type", "type", "CallType", "call_type"});
    return true;
}

bool fillSmsRecord(const json& item, std::map<std::string, std::string>& record) {
    const std::string body = scalar(item, {"Body", "body", "Content", "content", "Text", "text",
                                           "SmsContent", "sms_content"});
    const std::string address = scalar(item, {"Address", "address", "Number", "number",
                                              "PhoneNumber", "Phone", "phone"});
    if (body.empty() && address.empty()) return false;
    record["address"] = address;
    record["body"] = body;
    record["date"] = scalar(item, {"Date", "date", "Time", "time", "DateMs", "date_ms"});
    record["type"] = scalar(item, {"Type", "type", "SmsType", "sms_type"});
    return true;
}

void insertDeviceIdentifiers(AndroidAnalysisDatabase& output, const std::string& sourcePath,
                             const json& item) {
    static const std::array<const char*, 7> kIdentifierKeys = {
        "androidid", "imei1", "imei2", "meid", "serial", "macaddress", "android_id"};
    const std::string key = scalar(item, {"Key", "key"});
    const std::string value = scalar(item, {"Value", "value"});
    if (key.empty() || value.empty()) return;
    for (const char* candidate : kIdentifierKeys) {
        if (key == candidate) {
            output.insertDeviceIdentifier(key, value, "", sourcePath);
            return;
        }
    }
}

// Maps /storage/emulated/0/<rest> to the sdcard/<rest> container member when
// the payload rides along in the tar.
std::string mediaRelatedPath(const OppoBackupExtractor& source, const json& item) {
    const std::string mobilePath = scalar(item, {"MobilePath", "mobile_path", "Path", "path"});
    if (mobilePath.empty()) return {};
    static const std::array<const char*, 2> kStoragePrefixes = {"/storage/emulated/0/",
                                                                "/sdcard/"};
    for (const char* prefix : kStoragePrefixes) {
        const std::size_t position = mobilePath.find(prefix);
        if (position == std::string::npos) continue;
        const std::string candidate = "sdcard/" + mobilePath.substr(position + strlen(prefix));
        if (source.entries().count(candidate)) return candidate;
    }
    return {};
}

}  // namespace

bool analyzeOppoBackup(OppoBackupExtractor& source, AndroidAnalysisDatabase& output) {
    sqlite3* dest = output.handle();
    if (!dest) return false;
    if (sqlite3_exec(dest, mobile_backup_schema::DDL, nullptr, nullptr, nullptr) != SQLITE_OK)
        return false;
    if (!output.beginTransaction()) return false;

    std::size_t artifactRows = 0;
    bool committed = false;
    try {
        // Re-running the same source replaces derived records; never accumulate
        // duplicates.
        if (sqlite3_exec(dest,
                         "DELETE FROM mobile_artifacts; DELETE FROM installed_apps; "
                         "DELETE FROM app_db_inventory; DELETE FROM android_source_coverage; "
                         "DELETE FROM android_source_provenance;",
                         nullptr, nullptr, nullptr) != SQLITE_OK)
            throw std::runtime_error("OPPO_RESULT_RESET_FAILED");

        auto insertArtifact = [&](const std::string& kind, const std::string& packageName,
                                  const std::string& sourcePath, const std::string& sourceTable,
                                  const std::string& sourceKey, const std::string& recordJson,
                                  const std::string& timestampRaw,
                                  std::optional<std::int64_t> timestampSeconds,
                                  const std::string& relatedPath = {},
                                  const std::string& relatedStatus = {}) {
            if (artifactRows >= kMaxArtifactRows) return;
            sqlite3_stmt* statement = nullptr;
            if (sqlite3_prepare_v2(dest,
                                   "INSERT OR REPLACE INTO mobile_artifacts(kind,package_name,"
                                   "app_index,source_path,source_table,source_key,record_json,"
                                   "timestamp_raw,time_unit,timestamp_seconds,parser_version,"
                                   "related_path,related_status) "
                                   "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                   -1, &statement, nullptr) != SQLITE_OK)
                throw std::runtime_error("OPPO_ARTIFACT_PREPARE_FAILED");
            sqlite3_bind_text(statement, 1, kind.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 2, packageName.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_int(statement, 3, 0);
            sqlite3_bind_text(statement, 4, sourcePath.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 5, sourceTable.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 6, sourceKey.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 7, recordJson.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 8, timestampRaw.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 9, timestampSeconds ? "s" : "", -1, SQLITE_TRANSIENT);
            if (timestampSeconds) sqlite3_bind_int64(statement, 10, *timestampSeconds);
            else sqlite3_bind_null(statement, 10);
            sqlite3_bind_text(statement, 11, kParserVersion, -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 12, relatedPath.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 13, relatedStatus.c_str(), -1, SQLITE_TRANSIENT);
            if (sqlite3_step(statement) != SQLITE_DONE) {
                sqlite3_finalize(statement);
                throw std::runtime_error("OPPO_ARTIFACT_WRITE_FAILED");
            }
            sqlite3_finalize(statement);
            ++artifactRows;
        };

        // ---- Backup manifest (ThunderForensic.json) ----
        std::string manifestBytes;
        if (!source.readMemberBytes(kManifestMember, manifestBytes, 8ULL << 20))
            throw std::runtime_error("OPPO_MANIFEST_UNREADABLE");
        const json manifest = json::parse(manifestBytes);
        const json& device = manifest.contains("Device") && manifest["Device"].is_object()
                                 ? manifest["Device"]
                                 : json::object();
        const json& software = manifest.contains("Software") && manifest["Software"].is_object()
                                   ? manifest["Software"]
                                   : json::object();
        std::string deviceDisplay = scalar(device, {"Brand"}) ;
        const std::string model = scalar(device, {"Model"});
        if (!model.empty() && deviceDisplay.find(model) == std::string::npos)
            deviceDisplay = deviceDisplay.empty() ? model : deviceDisplay + " " + model;
        if (deviceDisplay.empty()) deviceDisplay = scalar(device, {"Name"});

        std::int64_t backupTimeMs = 0;
        if (manifest.contains("TaskInfo") && manifest["TaskInfo"].is_object()) {
            const std::string createdAt =
                scalar(manifest["TaskInfo"], {"CreateAt", "CompleteAt"});
            if (const auto seconds = parseIsoToSeconds(createdAt)) backupTimeMs = *seconds * 1000;
        }
        std::size_t moduleCount = 0;
        for (const auto& [path, entry] : source.entries())
            if (path.starts_with(kPhoneDataPrefix) && path.ends_with(".json")) ++moduleCount;

        {
            sqlite3_stmt* statement = nullptr;
            if (sqlite3_prepare_v2(dest,
                                   "INSERT OR REPLACE INTO mobile_backup_manifest "
                                   "VALUES(1,?,?,?,?,?,?,?)",
                                   -1, &statement, nullptr) != SQLITE_OK)
                throw std::runtime_error("OPPO_MANIFEST_PREPARE_FAILED");
            sqlite3_bind_text(statement, 1, "Android", -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 2, deviceDisplay.c_str(), -1, SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 3, scalar(software, {"Version"}).c_str(), -1,
                              SQLITE_TRANSIENT);
            sqlite3_bind_int64(statement, 4, backupTimeMs);
            sqlite3_bind_int64(statement, 5, static_cast<std::int64_t>(moduleCount));
            sqlite3_bind_text(statement, 6, bytesSha256(manifestBytes).c_str(), -1,
                              SQLITE_TRANSIENT);
            sqlite3_bind_text(statement, 7, kParserVersion, -1, SQLITE_TRANSIENT);
            if (sqlite3_step(statement) != SQLITE_DONE) {
                sqlite3_finalize(statement);
                throw std::runtime_error("OPPO_MANIFEST_WRITE_FAILED");
            }
            sqlite3_finalize(statement);
        }

        // ---- PhoneData JSON artifacts ----
        std::size_t sdcardMembers = 0, logMembers = 0;
        for (const auto& [path, entry] : source.entries()) {
            if (path.starts_with("sdcard/")) ++sdcardMembers;
            if (path.starts_with(kLogDataPrefix)) ++logMembers;
        }

        for (const auto& [path, entry] : source.entries()) {
            if (!path.starts_with(kPhoneDataPrefix) || !path.ends_with(".json")) continue;
            const std::string kind = memberKindFor(path);
            const std::string sourceTable = fs::path(path).stem().string();
            if (path == kManifestMember || entry.size > kMaxMemberJsonBytes) {
                output.recordSourceCoverage("phone_data", path, "UNSUPPORTED",
                                            "member_size_limit");
                continue;
            }
            std::string bytes;
            if (!source.readMemberBytes(path, bytes)) {
                output.recordSourceCoverage("phone_data", path, "EXTRACT_FAILED",
                                            source.error());
                continue;
            }
            json document;
            try {
                document = json::parse(bytes);
            } catch (const std::exception&) {
                // ThunderForensic writes extractor error strings (e.g.
                // "java.lang.SecurityException: ...") into the .json member
                // when an artifact could not be acquired — surface that reason
                // instead of a bare parse failure.
                std::string detail = "invalid JSON document";
                if (!bytes.empty() && bytes.find_first_of("[{") != 0) {
                    std::string reason = bytes.substr(0, bytes.find('\n'));
                    if (reason.size() > 300) reason = reason.substr(0, 300);
                    detail = "extractor_error: " + reason;
                }
                output.recordSourceCoverage("phone_data", path, "parse_failed", detail);
                continue;
            }
            // Normalize: arrays iterate directly; objects contribute their
            // array-valued fields (appusagedetail carries eventResultList).
            std::vector<std::pair<std::string, const json*>> sections;
            if (document.is_array()) {
                sections.emplace_back("", &document);
            } else if (document.is_object()) {
                for (const auto& [key, value] : document.items())
                    if (value.is_array()) sections.emplace_back(key, &value);
                if (sections.empty()) sections.emplace_back("", &document);
            } else {
                output.recordSourceCoverage("phone_data", path, "empty",
                                            "non-object JSON document");
                continue;
            }

            std::size_t rows = 0, standardRows = 0;
            std::size_t rowIndex = 0;
            for (const auto& [section, list] : sections) {
                if (!list->is_array()) continue;
                for (const auto& item : *list) {
                    const std::size_t index = rowIndex++;
                    if (!item.is_object()) continue;
                    const std::string packageName = scalar(item, {"PackageName", "package_name"});
                    const std::string timestampRaw =
                        scalar(item, {"InstallTime", "CreateTime", "ModifyTime", "StartTime",
                                      "startTime", "Date", "date", "Time", "time",
                                      "LastConnected"});
                    const auto timestampSeconds = parseIsoToSeconds(timestampRaw);
                    // The mobile_artifacts reader contract (android_artifact_
                    // reader.py) parses source_key as JSON — the row's primary
                    // key. Keep Harmony's shape: a JSON object, not a bare string.
                    const json keyObject = section.empty()
                        ? json{{"row", index}}
                        : json{{"section", section}, {"row", index}};
                    const std::string sourceKey = serialized(keyObject);
                    insertArtifact(kind, packageName, path, sourceTable, sourceKey,
                                   serialized(item), timestampRaw, timestampSeconds);
                    ++rows;

                    // Standard-table projections keep the OPPO records visible
                    // to the existing Android query surface.
                    if (kind == "application" && !packageName.empty()) {
                        output.insertInstalledApp(packageName,
                                                  scalar(item, {"AppName", "app_name"}),
                                                  scalar(item, {"VersionCode"}),
                                                  scalar(item, {"VersionName"}),
                                                  item.value("ApkSize", 0ULL), 0, 0,
                                                  serialized(item));
                        ++standardRows;
                    } else if (kind == "wifi") {
                        WifiNetwork network;
                        network.ssid = wifiSsidDisplay(scalar(item, {"Ssid", "ssid"}));
                        network.keyMgmt = scalar(item, {"KeyType", "key_type"});
                        if (!network.ssid.empty() && output.insertWifiNetwork(network))
                            ++standardRows;
                    } else if (kind == "contact") {
                        std::map<std::string, std::string> record;
                        if (fillContactRecord(item, record) && output.insertContact(record))
                            ++standardRows;
                    } else if (kind == "call_log") {
                        std::map<std::string, std::string> record;
                        if (fillCallRecord(item, record) && output.insertCallLog(record))
                            ++standardRows;
                    } else if (kind == "sms") {
                        std::map<std::string, std::string> record;
                        if (fillSmsRecord(item, record) && output.insertSMS(record))
                            ++standardRows;
                    } else if (kind == "media") {
                        const std::string related = mediaRelatedPath(source, item);
                        sqlite3_stmt* update = nullptr;
                        if (!related.empty() &&
                            sqlite3_prepare_v2(dest,
                                               "UPDATE mobile_artifacts SET related_path=?, "
                                               "related_status='present_in_container' "
                                               "WHERE source_path=? AND source_key=?",
                                               -1, &update, nullptr) == SQLITE_OK) {
                            sqlite3_bind_text(update, 1, related.c_str(), -1, SQLITE_TRANSIENT);
                            sqlite3_bind_text(update, 2, path.c_str(), -1, SQLITE_TRANSIENT);
                            const std::string key = serialized(json{{"row", index}});
                            sqlite3_bind_text(update, 3, key.c_str(), -1, SQLITE_TRANSIENT);
                            sqlite3_step(update);
                            sqlite3_finalize(update);
                        }
                    }
                    if (kind == "device_info" || kind == "device_identifier")
                        insertDeviceIdentifiers(output, path, item);
                }
            }
            output.recordSourceCoverage("phone_data", path,
                                        rows > 0 ? "parsed" : "empty",
                                        "rows=" + std::to_string(rows) +
                                            "; standard_table_rows=" +
                                            std::to_string(standardRows));
        }

        // ---- LogData / sdcard inventory (payloads are not parsed line-wise) ----
        for (const auto& [path, entry] : source.entries()) {
            if (!path.starts_with(kLogDataPrefix)) continue;
            json record = {{"name", fs::path(path).filename().string()},
                           {"size", entry.size},
                           {"modified", entry.modified}};
            insertArtifact("device_log", "", path, "logdata",
                           serialized(json{{"member", path}}), serialized(record), {},
                           std::nullopt);
        }
        output.recordSourceCoverage("device_log", "<LogData>", logMembers > 0 ? "indexed" : "empty",
                                    "log_files=" + std::to_string(logMembers) +
                                        "; line-level parsing is not performed");
        output.recordSourceCoverage("sdcard_files", "<sdcard>",
                                    sdcardMembers > 0 ? "indexed" : "empty",
                                    "members=" + std::to_string(sdcardMembers) +
                                        "; payloads remain in the container");

        if (!output.commitTransaction()) throw std::runtime_error("OPPO_COMMIT_FAILED");
        committed = true;
        return true;
    } catch (const std::exception&) {
        if (!committed) output.rollbackTransaction();
        return false;
    }
}
