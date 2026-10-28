// MobileBackupSchema.h
// Shared DDL for the vendor-neutral mobile backup artifact tables.
//
// Both the HarmonyOS adapter (HarmonyArtifactParsers) and the generic
// ThunderForensic adapter (ThunderForensicArtifactParsers, covering OPPO /
// vivo / OnePlus and other brands) persist into mobile_backup_manifest /
// mobile_artifacts so that the backup-overview query, the artifact reader and
// the report evidence pipeline stay vendor-agnostic. Keep every adapter on
// this one definition.

#pragma once

namespace mobile_backup_schema {

inline constexpr const char* DDL = R"SQL(
      CREATE TABLE IF NOT EXISTS mobile_backup_manifest(id INTEGER PRIMARY KEY CHECK(id=1),platform TEXT,
        device TEXT,backup_version TEXT,backup_time_ms INTEGER,module_count INTEGER,manifest_sha256 TEXT,adapter_version TEXT);
      CREATE TABLE IF NOT EXISTS mobile_artifacts(id INTEGER PRIMARY KEY,kind TEXT NOT NULL,package_name TEXT NOT NULL,
        app_index INTEGER NOT NULL,source_path TEXT NOT NULL,source_table TEXT NOT NULL,source_key TEXT NOT NULL,
        record_json TEXT NOT NULL,timestamp_raw TEXT,time_unit TEXT,timestamp_seconds INTEGER,
        source_db_sha256 TEXT,source_wal_sha256 TEXT,parser_version TEXT NOT NULL,
        related_path TEXT,related_status TEXT,
        llm_summary TEXT,llm_description TEXT,llm_keywords TEXT,llm_analyzed_at INTEGER,llm_model_used TEXT,
        UNIQUE(source_path,source_table,source_key));
      CREATE INDEX IF NOT EXISTS mobile_artifacts_kind ON mobile_artifacts(kind,id);
)SQL";

}  // namespace mobile_backup_schema
