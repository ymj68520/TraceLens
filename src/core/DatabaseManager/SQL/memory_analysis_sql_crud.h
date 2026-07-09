// memory_analysis_sql_crud.h
// INSERT / SELECT statements for the MemoryAnalyzer database

#pragma once
#ifndef MEMORY_ANALYSIS_SQL_CRUD_H
#define MEMORY_ANALYSIS_SQL_CRUD_H

namespace MemoryAnalysisSQL {

inline constexpr const char* INSERT_PROCESS =
    "INSERT INTO processes (offset, pid, tid, ppid, comm, uid, gid, euid, egid, creation_time) "
    "VALUES (?,?,?,?,?,?,?,?,?,?);";

inline constexpr const char* INSERT_NETWORK_CONNECTION =
    "INSERT INTO network_connections (offset, pid, tid, comm, family, type, proto, "
    "local_addr, local_port, remote_addr, remote_port, state, netns) "
    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?);";

inline constexpr const char* INSERT_BASH_HISTORY =
    "INSERT INTO bash_history (pid, comm, command, command_time, history_index) "
    "VALUES (?,?,?,?,?);";

inline constexpr const char* UPSERT_BOOT_INFO =
    "INSERT INTO boot_info (key, value) VALUES (?,?) "
    "ON CONFLICT(key) DO UPDATE SET value=excluded.value;";

inline constexpr const char* INSERT_CMDLINE =
    "INSERT INTO cmdline (pid, comm, args) VALUES (?,?,?);";

inline constexpr const char* UPSERT_ANALYSIS_META =
    "INSERT INTO analysis_meta (key, value) VALUES (?,?) "
    "ON CONFLICT(key) DO UPDATE SET value=excluded.value;";

} // namespace MemoryAnalysisSQL

#endif // MEMORY_ANALYSIS_SQL_CRUD_H
