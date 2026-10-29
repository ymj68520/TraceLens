// MobileEvidencePackage.h
// 手机取证统一取数格式（extraction artifact），取数层与分析层的唯一契约。
//
// 设计目标
// --------
// 1. 取数与分析分离：任何来源（MIUI / Harmony / 雷电 / iOS / UFED / 厂商导出）
//    的适配器只负责把原始检材翻译成本格式；分析层只读本格式，不再关心原始
//    容器、路径映射或厂商 schema。
// 2. 固定骨架 + 可扩展载荷：骨架字段（谁、从哪来、哪一类、什么时间、原始行）
//    固定；厂商特有字段一律进 payload_json，不因新增来源而改表。
// 3. 不丢信息：每条记录保留原始行（raw_json）与原始时间原文（timestamp_raw），
//    规范化字段只是索引，不是替代品。
// 4. 可追溯：每条记录带来源容器、成员路径、源库哈希、解析器版本；另有一张
//    coverage 表记录"应有而没取到"的工件，避免把缺失误读为不存在。
//
// 物理形态：单个 SQLite 数据库文件（默认后缀 .mep.db），可直接拷贝、归档、
// 哈希；分析层只读打开，不修改取数产物。

#pragma once
#ifndef MOBILE_EVIDENCE_PACKAGE_H
#define MOBILE_EVIDENCE_PACKAGE_H

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>

namespace mobile_evidence {

// 当前格式版本。分析层据此决定兼容路径；不兼容变更必须升主版本。
inline constexpr int kSchemaVersion = 1;
inline constexpr const char* kFormatName = "tracelens.mobile.evidence";

// 记录类别。新增来源若产生新的语义类别，在此追加；分析层按 kind 分派。
// 取值一旦发布即稳定，不得复用或改名。
namespace kind {
inline constexpr const char* kContact        = "contact";
inline constexpr const char* kCallLog        = "call_log";
inline constexpr const char* kSms            = "sms";
inline constexpr const char* kMms            = "mms";
inline constexpr const char* kImMessage      = "im_message";
inline constexpr const char* kImConversation = "im_conversation";
inline constexpr const char* kImContact      = "im_contact";
inline constexpr const char* kNote           = "note";
inline constexpr const char* kCalendarEvent  = "calendar_event";
inline constexpr const char* kBrowserHistory = "browser_history";
inline constexpr const char* kBrowserBookmark= "browser_bookmark";
inline constexpr const char* kWifiNetwork    = "wifi_network";
inline constexpr const char* kAccount        = "account";
inline constexpr const char* kDeviceIdentity = "device_identity";
inline constexpr const char* kInstalledApp   = "installed_app";
inline constexpr const char* kMediaFile      = "media_file";
inline constexpr const char* kDocumentFile   = "document_file";
inline constexpr const char* kSystemLog      = "system_log";
inline constexpr const char* kLocation       = "location";
inline constexpr const char* kRecording      = "recording";
inline constexpr const char* kCallRecording  = "call_recording";
inline constexpr const char* kDatabaseTable  = "database_table";
inline constexpr const char* kGeneric        = "generic";
}  // namespace kind

// 时间语义。取数层必须声明原文与单位，规范化秒值可缺省。
namespace time_unit {
inline constexpr const char* kSeconds      = "s";
inline constexpr const char* kMilliseconds = "ms";
inline constexpr const char* kMicroseconds = "us";
inline constexpr const char* kNanoseconds  = "ns";
inline constexpr const char* kAppleEpoch   = "apple_epoch_s";  // 2001-01-01 起算
inline constexpr const char* kText         = "text";           // 仅原文，未解析
}  // namespace time_unit

// 记录可用性。取数层必须如实标注，分析层不得把非 parsed 当成有数据。
namespace status {
inline constexpr const char* kParsed     = "parsed";
inline constexpr const char* kPartial    = "partial";
inline constexpr const char* kLocked     = "locked";       // 加密且无密钥
inline constexpr const char* kUnsupported= "unsupported";  // 已知格式但无解析器
inline constexpr const char* kMalformed  = "malformed";
inline constexpr const char* kFailed     = "failed";
}  // namespace status

// ---------------------------------------------------------------------------
// 一条规范化记录。
// ---------------------------------------------------------------------------
struct Record {
    // 语义类别，取值见 kind::*。分析层据此决定落哪张标准表。
    std::string kind;
    // 取数层自己的工件类别，原样写入 mobile_artifacts.kind。为空时回退到 kind。
    // 用于保留厂商既有类别名（calendar / recording / app_data_container ...），
    // 使下游 artifact reader 与时间轴契约不变。
    std::string nativeKind;
    // 是否同时产出一条 mobile_artifacts 行。仅落标准表的记录（如设备标识、
    // 应用清单）置 false，避免凭空新增下游可见的工件行。
    bool mobileArtifact = false;
    // 所属应用包名；系统级工件留空。
    std::string packageName;
    // 来源内该应用的稳定序号（同一包名多账号/多实例时区分）。
    int appIndex = 0;

    // 来源定位：容器 → 成员 → 表 → 主键，四级足以回溯到原始行。
    std::string sourcePath;    // 取数层内部路径，例如 apps/com.tencent.mm/db/...
    std::string sourceTable;   // 源库表名
    std::string sourceKey;     // 源库主键或稳定行标识

    // 原始行：完整、未经改写的键值对（JSON 对象）。
    std::string rawJson;
    // 规范化字段：分析层可直接取用的关键列（JSON 对象），是 rawJson 的子集投影。
    std::string payloadJson;

    // 时间：原文 + 单位 + 规范化秒值（UTC）。无法解析时 seconds 留空。
    std::string timestampRaw;
    std::string timestampUnit;
    std::optional<std::int64_t> timestampSeconds;

    // 来源完整性
    std::string sourceSha256;      // 源库文件哈希
    std::string sourceWalSha256;   // 旁路 WAL 哈希（若有）
    std::string parserVersion;

    // 关联的外部文件（媒体、附件、缩略图等），相对包根或原容器
    std::string relatedPath;
    std::string relatedStatus;

    // 数据库表级盘点（kind == kDatabaseTable 时使用）。其他类别留空。
    std::string databasePath;
    std::string databaseTable;
    std::string databaseColumnsJson;
    std::string databaseOpenStatus;
    std::optional<std::uint64_t> databaseRowCount;

    // 取数层对该行的可用性标注
    std::string status = status::kParsed;
};

// ---------------------------------------------------------------------------
// 文件清单条目：不逐行解析的二进制（媒体、文档、未解密库）也必须有条目，
// 否则"没解析"会退化成"不存在"。
// ---------------------------------------------------------------------------
struct FileEntry {
    std::string relativePath;   // 统一以来源根为基准的相对路径
    std::string fileName;
    std::string extension;
    std::string category;       // image/video/audio/document/database/archive/other
    std::string packageName;
    std::uint64_t size = 0;
    std::uint64_t modifiedTimeMs = 0;
    std::string sha256;
    std::string status = status::kParsed;
};

// ---------------------------------------------------------------------------
// 覆盖度：声明"来源里应该有什么、实际取到什么"。分析层与报告层据此区分
// "证据不存在"与"本次未能提取"。
// ---------------------------------------------------------------------------
struct Coverage {
    std::string artifactKind;   // sms/contacts/call_log/wechat/... 或 kind::*
    std::string sourcePath;
    std::string status;         // parsed/locked/not_found/unsupported/failed/partial
    // 取数层原有的状态字符串。既有下游（android_source_coverage 消费方）按
    // 厂商原生词表判断，例如雷电用大写 LOCKED / indexed / empty。非空时分析
    // 阶段优先写它，保证迁移不改变已发布的可见值。
    std::string nativeStatus;
    std::string detail;
    std::uint64_t recordCount = 0;
};

// ---------------------------------------------------------------------------
// 设备与采集元数据。
// ---------------------------------------------------------------------------
struct DeviceInfo {
    std::string platform;        // android / ios / harmonyos / unknown
    std::string manufacturer;
    std::string brand;
    std::string model;
    std::string deviceName;
    std::string osVersion;
    std::string buildVersion;
    std::string serialNumber;
    std::string imei;
    std::string meid;
    std::string iccid;
    std::string msisdn;          // 本机号码
    std::string androidId;
    std::string uniqueIdentifier;// iOS UDID 等
    std::string timezone;
    std::string locale;
    std::string extraJson;       // 其余设备属性
};

struct AcquisitionInfo {
    std::string adapterName;      // miui-backup / harmony-backup / ios-backup / ...
    std::string adapterVersion;
    std::string sourceType;       // directory / tar / zip / image / backup
    std::string sourcePath;       // 原始检材路径（仅记录，不保证可再访问）
    std::string sourceSha256;     // 容器哈希（若计算）
    std::string acquiredAt;       // 备份/提取时间原文
    std::int64_t acquiredAtSeconds = 0;
    std::string operatorName;     // 提取人/工具（若已知）
    std::string toolVersion;      // 第三方取证软件版本
    std::string notes;
    std::string extraJson;
};

// ---------------------------------------------------------------------------
// 备份清单。不同来源写的是不同的分析表（MIUI → miui_backup_manifest，
// 鸿蒙/雷电 → mobile_backup_manifest），因此保留 targetTable 让适配器声明。
// ---------------------------------------------------------------------------
struct BackupManifest {
    std::string targetTable;      // miui_backup_manifest / mobile_backup_manifest
    std::string platform;         // Android / HarmonyOS / ...
    std::string device;
    std::string backupVersion;
    std::int64_t backupTimeMs = 0;
    std::int64_t moduleCount = 0;
    std::string manifestSha256;
    std::string adapterVersion;
    bool present = false;
};

// ---------------------------------------------------------------------------
// 包描述：写入前的完整内存表示。适配器填充后交给 Writer 落盘。
// ---------------------------------------------------------------------------
struct Package {
    DeviceInfo device;
    AcquisitionInfo acquisition;
    BackupManifest manifest;
    std::vector<Record> records;
    std::vector<FileEntry> files;
    std::vector<Coverage> coverage;
};

// ---------------------------------------------------------------------------
// Writer：把 Package 落成一个 .mep.db。事务写入，失败不留下半成品。
// ---------------------------------------------------------------------------
class Writer {
public:
    explicit Writer(std::string dbPath);
    ~Writer();

    Writer(const Writer&) = delete;
    Writer& operator=(const Writer&) = delete;

    bool open();
    bool writePackage(const Package& package);
    bool close();

    const std::string& error() const { return error_; }

private:
    std::string dbPath_;
    std::string error_;
    void* db_ = nullptr;
    bool ownsDb_ = false;
};

// ---------------------------------------------------------------------------
// Reader：只读打开一个 .mep.db，供分析层消费。
// ---------------------------------------------------------------------------
class Reader {
public:
    explicit Reader(std::string dbPath);
    ~Reader();

    Reader(const Reader&) = delete;
    Reader& operator=(const Reader&) = delete;

    bool open();
    bool close();

    bool readDevice(DeviceInfo& out) const;
    bool readAcquisition(AcquisitionInfo& out) const;
    bool readManifest(BackupManifest& out) const;
    std::vector<Record> readRecords() const;
    std::vector<Record> readRecords(const std::string& kind) const;
    std::vector<FileEntry> readFiles() const;
    std::vector<Coverage> readCoverage() const;

    // 汇总：各类别记录数，便于分析层决定是否继续。
    std::map<std::string, std::uint64_t> recordCountsByKind() const;

    int schemaVersion() const { return schemaVersion_; }
    const std::string& error() const { return error_; }

private:
    std::string dbPath_;
    mutable std::string error_;
    void* db_ = nullptr;
    int schemaVersion_ = 0;
};

// 校验一个文件是否是本格式的包（读 schema_version 与 format 标识）。
bool looksLikePackage(const std::string& dbPath);

// 生成默认包路径：<source>_mobile_evidence.mep.db
std::string defaultPackagePath(const std::string& sourcePath);

}  // namespace mobile_evidence

#endif  // MOBILE_EVIDENCE_PACKAGE_H
