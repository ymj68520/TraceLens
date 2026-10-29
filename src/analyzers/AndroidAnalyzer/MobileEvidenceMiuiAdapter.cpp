// MobileEvidenceMiuiAdapter.cpp
// MIUI 离线备份 → 统一取数包。
//
// 职责边界：本文件只做"取数"，即把 MIUI 的容器成员与私有编码翻译成统一
// 记录；不做去重策略之外的任何分析判断，也不写 android.db。

#include "MobileEvidenceMiuiAdapter.h"

#include "MiuiBackupExtractor.h"
#include "MiuiBakProtoParsers.h"
#include "MiuiPathMap.h"

#include <algorithm>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <set>
#include <sstream>
#include <string>
#include <tuple>
#include <unordered_set>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace mobile_evidence {
namespace {

constexpr const char* kTmpBakSuffix = "miui_bak/_tmp_bak";

// MIUI 把号码渲染成带分组空格的形式（"158 0964 9804"），统一成纯数字串，
// 便于与通话记录、短信地址做等值关联。
std::string normalizeNumber(const std::string& input) {
    std::string out;
    out.reserve(input.size());
    for (char c : input) {
        if (c == ' ' || c == '-' || c == '(' || c == ')') continue;
        out.push_back(c);
    }
    return out;
}

// 从 MIUI .bak 文件名（"联系人(com.android.contacts).bak"）提取包名。
std::string packageFromBakFile(const std::string& bakFile) {
    const std::string name = fs::path(bakFile).filename().string();
    const auto open = name.find('(');
    const auto close = name.rfind(')');
    if (open == std::string::npos || close == std::string::npos || close <= open + 1) {
        return {};
    }
    return name.substr(open + 1, close - open - 1);
}

// 从 tar 成员名（apps/<pkg>/...）提取包名。
std::string packageFromMember(const std::string& memberName) {
    const std::string prefix = "apps/";
    if (memberName.rfind(prefix, 0) != 0) return {};
    const auto end = memberName.find('/', prefix.size());
    if (end == std::string::npos) return {};
    return memberName.substr(prefix.size(), end - prefix.size());
}

Record makeRecord(const std::string& kindName, const std::string& packageName,
                  const std::string& sourcePath, const std::string& sourceTable,
                  const std::string& sourceKey, const std::string& parserVersion) {
    Record record;
    record.kind = kindName;
    record.packageName = packageName;
    record.sourcePath = sourcePath;
    record.sourceTable = sourceTable;
    record.sourceKey = sourceKey;
    record.parserVersion = parserVersion;
    return record;
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

// ---- 记录级适配 -----------------------------------------------------------

void appendContacts(Package& package, const std::vector<MiuiProtoContactRow>& rows,
                    const std::string& bakFile, const std::string& memberName,
                    const std::string& packageName, const std::string& version) {
    std::set<std::pair<std::string, std::string>> seen;
    std::uint64_t written = 0;
    for (const auto& row : rows) {
        const std::string number = normalizeNumber(row.number);
        if (row.displayName.empty() && number.empty()) continue;
        if (!seen.emplace(row.displayName, number).second) continue;

        Record record = makeRecord(kind::kContact, packageName, memberName, "contacts", {},
                                   version);
        record.rawJson = json{
            {"display_name", row.displayName},
            {"nickname", row.nickname},
            {"number", row.number},
            {"number_type", row.numberType},
        }.dump();
        record.payloadJson = json{
            {"display_name", row.displayName},
            {"phone_number", number},
            {"number_type", row.numberType},
        }.dump();
        record.sourceKey = row.displayName + "|" + number;
        record.relatedPath = bakFile;
        package.records.push_back(std::move(record));
        ++written;
    }
    addCoverage(package, kind::kContact, memberName, status::kParsed,
                "MIUI miui_bak protobuf contact records", written);
}

void appendCallLogs(Package& package, const std::vector<MiuiProtoCallRow>& rows,
                    const std::string& bakFile, const std::string& memberName,
                    const std::string& packageName, const std::string& version) {
    std::set<std::tuple<std::string, std::uint64_t, int>> seen;
    std::uint64_t written = 0;
    for (const auto& row : rows) {
        if (!seen.emplace(row.number, row.dateMs, row.type).second) continue;

        Record record = makeRecord(kind::kCallLog, packageName, memberName, "calls", {}, version);
        record.rawJson = json{
            {"number", row.number},
            {"date", row.dateMs},
            {"duration", row.duration},
            {"type", row.type},
        }.dump();
        record.payloadJson = json{
            {"number", normalizeNumber(row.number)},
            {"duration_seconds", row.duration},
            {"type", row.type},
        }.dump();
        record.sourceKey = row.number + "|" + std::to_string(row.dateMs) + "|" +
                           std::to_string(row.type);
        record.timestampRaw = std::to_string(row.dateMs);
        record.timestampUnit = time_unit::kMilliseconds;
        record.timestampSeconds = static_cast<std::int64_t>(row.dateMs / 1000);
        record.relatedPath = bakFile;
        package.records.push_back(std::move(record));
        ++written;
    }
    addCoverage(package, kind::kCallLog, memberName, status::kParsed,
                "MIUI miui_bak protobuf call records", written);
}

void appendSms(Package& package, const std::vector<MiuiProtoSmsRow>& rows,
               const std::string& bakFile, const std::string& memberName,
               const std::string& packageName, const std::string& version) {
    std::set<std::tuple<std::string, std::uint64_t, std::string>> seen;
    std::uint64_t written = 0;
    for (const auto& row : rows) {
        // 同一条短信可能同时出现在 短信 与 短信设置 两个 .bak 中。
        if (!seen.emplace(row.address, row.dateMs, row.body).second) continue;

        Record record = makeRecord(kind::kSms, packageName, memberName, "sms", {}, version);
        record.rawJson = json{
            {"address", row.address},
            {"body", row.body},
            {"date", row.dateMs},
            {"type", row.type},
            {"read", row.read},
            {"status", row.status},
            {"service_center", row.serviceCenter},
            {"thread_id", row.threadId},
        }.dump();
        record.payloadJson = json{
            {"address", row.address},
            {"body", row.body},
            {"type", row.type},
            {"read", row.read},
            {"thread_id", row.threadId},
        }.dump();
        record.sourceKey = row.address + "|" + std::to_string(row.dateMs);
        record.timestampRaw = std::to_string(row.dateMs);
        record.timestampUnit = time_unit::kMilliseconds;
        record.timestampSeconds = static_cast<std::int64_t>(row.dateMs / 1000);
        record.relatedPath = bakFile;
        package.records.push_back(std::move(record));
        ++written;
    }
    addCoverage(package, kind::kSms, memberName, status::kParsed,
                "MIUI miui_bak protobuf SMS records", written);
}

void appendNotes(Package& package, const std::vector<MiuiProtoNoteRow>& rows,
                 const std::string& bakFile, const std::string& memberName,
                 const std::string& packageName, const std::string& version) {
    std::set<std::tuple<std::string, std::string, std::string>> seen;
    std::uint64_t written = 0;
    for (const auto& row : rows) {
        if (!seen.emplace(row.noteId, row.title, row.snippet).second) continue;

        Record record = makeRecord(kind::kNote, packageName, memberName, "notes", {}, version);
        record.rawJson = json{
            {"note_id", row.noteId},
            {"title", row.title},
            {"snippet", row.snippet},
            {"kind", row.kind},
            {"created", row.createdMs},
            {"modified", row.modifiedMs},
        }.dump();
        record.payloadJson = json{
            {"note_id", row.noteId},
            {"title", row.title},
            {"content", row.snippet},
            {"tags", row.kind},
        }.dump();
        record.sourceKey = row.noteId.empty() ? row.title + "|" + row.snippet : row.noteId;
        if (row.modifiedMs != 0) {
            record.timestampRaw = std::to_string(row.modifiedMs);
            record.timestampUnit = time_unit::kMilliseconds;
            record.timestampSeconds = static_cast<std::int64_t>(row.modifiedMs / 1000);
        } else if (row.createdMs != 0) {
            record.timestampRaw = std::to_string(row.createdMs);
            record.timestampUnit = time_unit::kMilliseconds;
            record.timestampSeconds = static_cast<std::int64_t>(row.createdMs / 1000);
        }
        record.relatedPath = bakFile;
        package.records.push_back(std::move(record));
        ++written;
    }
    addCoverage(package, kind::kNote, memberName, status::kParsed,
                "MIUI miui_bak protobuf note records", written);
}

// ---- 应用清单与文件清单 ---------------------------------------------------

void appendInstalledApps(Package& package, MiuiBackupExtractor& source,
                         const std::string& version) {
    const BackupMeta& manifest = source.manifest();
    std::uint64_t written = 0;
    for (size_t index = 0; index < manifest.packages.size(); ++index) {
        if (!source.hasUniqueManifestBakFile(index)) continue;
        const BackupPackage& entry = manifest.packages[index];

        Record record = makeRecord(kind::kInstalledApp, entry.packageName,
                                   entry.bakFile, "descript.xml", entry.packageName, version);
        record.rawJson = json{
            {"package_name", entry.packageName},
            {"bak_file", entry.bakFile},
            {"bak_type", entry.bakType},
            {"error", entry.error},
            {"state", entry.state},
            {"pkg_size", entry.pkgSize},
            {"sd_size", entry.sdSize},
            {"discovered_on_disk", entry.discoveredOnDisk},
        }.dump();
        record.payloadJson = json{
            {"package_name", entry.packageName},
            {"display_name", entry.packageName},
            {"data_size", entry.pkgSize},
            {"sd_size", entry.sdSize},
            {"bak_type", entry.bakType},
        }.dump();
        package.records.push_back(std::move(record));
        ++written;
    }
    addCoverage(package, kind::kInstalledApp, "descript.xml", status::kParsed,
                "MIUI manifest package rows", written);
}

void appendExternalFiles(Package& package, MiuiBackupExtractor& source) {
    if (!source.hasExternalRoot()) {
        addCoverage(package, "sdcard_files", "<sdcard>", "not_found",
                    "No sibling sdcard/ tree in this acquisition");
        return;
    }

    std::uint64_t written = 0;
    source.enumerateExternalFiles([&](const MiuiBackupExtractor::ExternalFile& file) {
        const fs::path path(file.relativePath);
        std::string extension = path.extension().string();
        if (!extension.empty() && extension.front() == '.') extension.erase(0, 1);
        std::transform(extension.begin(), extension.end(), extension.begin(),
                       [](unsigned char c) { return static_cast<char>(std::tolower(c)); });

        static const std::unordered_set<std::string> kImage{"jpg", "jpeg", "png", "gif", "webp",
                                                            "bmp", "heic", "dng", "raw"};
        static const std::unordered_set<std::string> kVideo{"mp4", "mov", "3gp", "mkv", "avi",
                                                            "webm", "ts", "m4v"};
        static const std::unordered_set<std::string> kAudio{"mp3", "m4a", "aac", "amr", "wav",
                                                            "ogg", "flac", "opus"};
        static const std::unordered_set<std::string> kDocument{"pdf", "doc", "docx", "xls",
                                                               "xlsx", "ppt", "pptx", "txt",
                                                               "csv", "rtf"};

        FileEntry entry;
        entry.relativePath = file.relativePath;
        entry.fileName = path.filename().string();
        entry.extension = extension;
        entry.category = kImage.count(extension) ? "image"
                       : kVideo.count(extension) ? "video"
                       : kAudio.count(extension) ? "audio"
                       : kDocument.count(extension) ? "document"
                       : "other";
        entry.size = file.size;
        entry.modifiedTimeMs = file.modifiedTime;
        package.files.push_back(std::move(entry));
        ++written;
        return true;
    });

    addCoverage(package, "sdcard_files", "<sdcard>",
                written > 0 ? status::kParsed : "empty",
                "External storage inventory; payloads remain in the sdcard tree", written);
}

// 未解密的数据库也必须留痕，否则分析层会把它当成"不存在"。
void appendDatabaseInventory(Package& package, MiuiBackupExtractor& source,
                             const std::string& version) {
    std::uint64_t databases = 0;
    source.enumerateEntryDetails([&](const std::string& memberName, const std::string& bakFile,
                                     const TarEntry& entry) {
        if (!entry.isRegularFile()) return;
        const std::string suffix = fs::path(memberName).extension().string();
        const bool looksLikeDatabase = suffix == ".db" || suffix == ".sqlite" ||
                                       suffix == ".sqlite3" || suffix == ".sqlitedb";
        if (!looksLikeDatabase) return;

        FileEntry file;
        file.relativePath = memberName;
        file.fileName = fs::path(memberName).filename().string();
        file.extension = suffix.empty() ? "" : suffix.substr(1);
        file.category = "database";
        file.packageName = packageFromMember(memberName);
        file.size = entry.size;
        file.modifiedTimeMs = entry.modifiedTime;
        file.status = status::kUnsupported;  // 仅登记，未逐行解析
        package.files.push_back(std::move(file));
        ++databases;
    });
    addCoverage(package, "app_database_files", "<miui-backup>", status::kParsed,
                "Database members inventoried; row-level parsing is a later stage",
                databases);
    (void)version;
}

void appendManifestCoverage(Package& package, MiuiBackupExtractor& source) {
    const BackupMeta& manifest = source.manifest();
    package.device.deviceName = manifest.device;
    package.device.osVersion = manifest.miuiVersion;
    package.device.platform = "android";
    package.device.extraJson = json{
        {"vendor_rom", "MIUI"},
        {"miui_version", manifest.miuiVersion},
        {"recovered_missing_packages", manifest.recoveredMissingPackages},
    }.dump();

    package.acquisition.acquiredAt = std::to_string(manifest.date);
    package.acquisition.acquiredAtSeconds = static_cast<std::int64_t>(manifest.date / 1000);
    package.acquisition.sourceType = "miui-backup";
    package.acquisition.sourcePath = manifest.sourceFolder;

    addCoverage(package, "backup_manifest", "descript.xml", status::kParsed,
                "device=" + manifest.device + "; miui=" + manifest.miuiVersion +
                    "; packages=" + std::to_string(manifest.packages.size()),
                manifest.packages.size());

    for (const auto& failure : source.packageFailures()) {
        addCoverage(package, "package_open", failure.bakFile, status::kFailed,
                    "package=" + failure.packageName + "; open_status=" + failure.openStatus);
    }
}

}  // namespace

bool buildPackageFromMiui(MiuiBackupExtractor& source,
                          const MiuiAdapterOptions& options,
                          Package& out) {
    const BackupMeta& manifest = source.manifest();
    if (manifest.packages.empty() && manifest.sourceFolder.empty()) {
        return false;  // 提取器未初始化或清单不可读
    }

    out = Package{};
    out.acquisition.adapterName = "miui-backup";
    out.acquisition.adapterVersion = options.adapterVersion;

    appendManifestCoverage(out, source);
    appendInstalledApps(out, source, options.adapterVersion);
    appendDatabaseInventory(out, source, options.adapterVersion);

    // ---- miui_bak/_tmp_bak 私有 protobuf 记录 ----
    std::vector<std::pair<std::string, std::string>> members;
    source.enumerateBakMembers([&](const std::string& bakFile, const std::string& memberName,
                                   const TarEntry&) {
        if (memberName.size() >= std::char_traits<char>::length(kTmpBakSuffix) &&
            memberName.compare(memberName.size() - std::char_traits<char>::length(kTmpBakSuffix),
                               std::char_traits<char>::length(kTmpBakSuffix), kTmpBakSuffix) == 0) {
            members.emplace_back(bakFile, memberName);
        }
    });
    std::sort(members.begin(), members.end());

    for (const auto& [bakFile, memberName] : members) {
        const std::string packageName = packageFromMember(memberName).empty()
            ? packageFromBakFile(bakFile) : packageFromMember(memberName);

        const std::string tempPath = (fs::temp_directory_path() /
            ("tracelens-mep-" + std::to_string(reinterpret_cast<std::uintptr_t>(&source)) + "-" +
             std::to_string(out.records.size()) + ".tmp")).string();
        if (!source.extractBakMember(bakFile, memberName, tempPath)) {
            addCoverage(out, "miui_bak_state", memberName, status::kFailed,
                        "extract failed for " + bakFile);
            continue;
        }

        std::ifstream input(tempPath, std::ios::binary);
        const std::string bytes((std::istreambuf_iterator<char>(input)),
                                std::istreambuf_iterator<char>());
        input.close();
        std::error_code removeError;
        fs::remove(tempPath, removeError);

        const MiuiBakKind bakKind = classifyMiuiBakContent(bytes);
        switch (bakKind) {
            case MiuiBakKind::Contacts: {
                std::vector<MiuiProtoContactRow> rows;
                if (parseMiuiContactsBak(bytes, rows)) {
                    appendContacts(out, rows, bakFile, memberName, packageName,
                                   options.adapterVersion);
                } else {
                    addCoverage(out, kind::kContact, memberName, status::kMalformed,
                                "contact protobuf did not match the expected wire shape");
                }
                break;
            }
            case MiuiBakKind::CallLog: {
                std::vector<MiuiProtoCallRow> rows;
                if (parseMiuiCallLogBak(bytes, rows)) {
                    appendCallLogs(out, rows, bakFile, memberName, packageName,
                                   options.adapterVersion);
                } else {
                    addCoverage(out, kind::kCallLog, memberName, status::kMalformed,
                                "call log protobuf did not match the expected wire shape");
                }
                break;
            }
            case MiuiBakKind::Sms: {
                std::vector<MiuiProtoSmsRow> rows;
                if (parseMiuiSmsBak(bytes, rows)) {
                    appendSms(out, rows, bakFile, memberName, packageName,
                              options.adapterVersion);
                } else {
                    addCoverage(out, kind::kSms, memberName, status::kMalformed,
                                "SMS protobuf did not match the expected wire shape");
                }
                break;
            }
            case MiuiBakKind::Notes: {
                std::vector<MiuiProtoNoteRow> rows;
                if (parseMiuiNotesBak(bytes, rows)) {
                    appendNotes(out, rows, bakFile, memberName, packageName,
                                options.adapterVersion);
                } else {
                    addCoverage(out, kind::kNote, memberName, status::kMalformed,
                                "note protobuf did not match the expected wire shape");
                }
                break;
            }
            case MiuiBakKind::Json:
                addCoverage(out, "app_settings", memberName, status::kUnsupported,
                            "plain app-settings JSON; no record extraction in this adapter");
                break;
            case MiuiBakKind::Unknown:
            default:
                addCoverage(out, "miui_bak_state", memberName, status::kUnsupported,
                            "unrecognized miui_bak payload (" +
                                std::to_string(bytes.size()) + " bytes)");
                break;
        }
    }

    if (options.includeExternalStorage) appendExternalFiles(out, source);

    // 明确声明"这些类别本次没有产出"，避免下游把空表读成"设备没有短信"。
    const std::set<std::string> produced = [&out] {
        std::set<std::string> kinds;
        for (const auto& record : out.records) kinds.insert(record.kind);
        return kinds;
    }();
    for (const char* expected : {kind::kSms, kind::kContact, kind::kCallLog, kind::kNote}) {
        if (produced.count(expected)) continue;
        addCoverage(out, expected, "<miui-backup>", "no_candidate_path",
                    "No records of this kind were produced by the MIUI adapter");
    }

    return true;
}

}  // namespace mobile_evidence
