// memory_analysis_sql_crud.h
// INSERT / SELECT statements for the MemoryAnalyzer database

#pragma once
#ifndef MEMORY_ANALYSIS_SQL_CRUD_H
#define MEMORY_ANALYSIS_SQL_CRUD_H

namespace MemoryAnalysisSQL {

inline constexpr const char* INSERT_PROCESS =
    "INSERT INTO processes (offset, pid, ppid, comm, uid, gid, start_time, thread_count, state) "
    "VALUES (?,?,?,?,?,?,?,?,?);";

inline constexpr const char* INSERT_NETWORK_CONNECTION =
    "INSERT INTO network_connections (offset, pid, comm, protocol, local_addr, local_port, foreign_addr, foreign_port, state) "
    "VALUES (?,?,?,?,?,?,?,?,?);";

inline constexpr const char* INSERT_SOCKET =
    "INSERT INTO sockets (offset, pid, comm, family, type, local_addr, remote_addr, state) "
    "VALUES (?,?,?,?,?,?,?,?);";

inline constexpr const char* INSERT_BASH_HISTORY =
    "INSERT INTO bash_history (pid, comm, command, history_index) "
    "VALUES (?,?,?,?);";

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
