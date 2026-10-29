// MobileEvidenceSchema.h
// 统一取数格式的 DDL。与 MobileEvidencePackage.h 的字段一一对应。
//
// 设计约束
// --------
// * 三张主表固定：mobile_evidence_meta（设备/采集）、mobile_evidence_record
//   （规范化记录）、mobile_evidence_file（文件清单）；一张覆盖表。
// * 记录表不随厂商增减列。厂商差异全部落在 raw_json / payload_json。
// * 保留 UNIQUE(source_path, source_table, source_key) 以实现重复导入幂等；
//   但 source_key 可能与 source_table 一起为空（如整包导出），此时用 row_uid
//   兜底，避免同一秒内多条记录互相覆盖。

#pragma once
#ifndef MOBILE_EVIDENCE_SCHEMA_H
#define MOBILE_EVIDENCE_SCHEMA_H

namespace mobile_evidence {
namespace schema {

inline constexpr const char* kDDL = R"SQL(
CREATE TABLE IF NOT EXISTS mobile_evidence_meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS mobile_evidence_record (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    row_uid TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    native_kind TEXT,
    mobile_artifact INTEGER NOT NULL DEFAULT 0,
    package_name TEXT NOT NULL DEFAULT '',
    app_index INTEGER NOT NULL DEFAULT 0,
    source_path TEXT NOT NULL DEFAULT '',
    source_table TEXT NOT NULL DEFAULT '',
    source_key TEXT NOT NULL DEFAULT '',
    raw_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL DEFAULT '{}',
    timestamp_raw TEXT,
    timestamp_unit TEXT,
    timestamp_seconds INTEGER,
    source_sha256 TEXT,
    source_wal_sha256 TEXT,
    parser_version TEXT NOT NULL DEFAULT '',
    related_path TEXT,
    related_status TEXT,
    database_path TEXT,
    database_table TEXT,
    database_columns_json TEXT,
    database_open_status TEXT,
    database_row_count INTEGER,
    status TEXT NOT NULL DEFAULT 'parsed'
);
CREATE INDEX IF NOT EXISTS idx_mer_kind ON mobile_evidence_record(kind, id);
CREATE INDEX IF NOT EXISTS idx_mer_package ON mobile_evidence_record(package_name, id);
CREATE INDEX IF NOT EXISTS idx_mer_time ON mobile_evidence_record(timestamp_seconds);

CREATE TABLE IF NOT EXISTS mobile_evidence_file (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    relative_path TEXT NOT NULL UNIQUE,
    file_name TEXT,
    extension TEXT,
    category TEXT,
    package_name TEXT,
    size INTEGER NOT NULL DEFAULT 0,
    modified_time_ms INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT,
    status TEXT NOT NULL DEFAULT 'parsed'
);
CREATE INDEX IF NOT EXISTS idx_mef_category ON mobile_evidence_file(category);

CREATE TABLE IF NOT EXISTS mobile_evidence_coverage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    artifact_kind TEXT NOT NULL,
    source_path TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    native_status TEXT,
    detail TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    UNIQUE(artifact_kind, source_path)
);

-- 供分析层直接消费的视图：把 payload 里的常用键提成列，仍保留完整原文。
CREATE VIEW IF NOT EXISTS v_record_flat AS
SELECT id, kind, native_kind, mobile_artifact, package_name, app_index,
       source_path, source_table, source_key,
       timestamp_raw, timestamp_unit, timestamp_seconds, status, raw_json, payload_json
FROM mobile_evidence_record;
)SQL";

// 元数据键名。取数层与分析层都从这里取，避免字符串漂移。
namespace meta_key {
inline constexpr const char* kFormat          = "format";
inline constexpr const char* kSchemaVersion   = "schema_version";
inline constexpr const char* kCreatedAt       = "created_at";
inline constexpr const char* kRecordCount     = "record_count";
inline constexpr const char* kFileCount       = "file_count";
inline constexpr const char* kCoverageCount   = "coverage_count";
inline constexpr const char* kAdapterName     = "adapter_name";
inline constexpr const char* kAdapterVersion  = "adapter_version";
inline constexpr const char* kPlatform        = "platform";
inline constexpr const char* kDeviceJson      = "device_json";
inline constexpr const char* kAcquisitionJson = "acquisition_json";
inline constexpr const char* kManifestJson    = "manifest_json";
}  // namespace meta_key

}  // namespace schema
}  // namespace mobile_evidence

#endif  // MOBILE_EVIDENCE_SCHEMA_H
