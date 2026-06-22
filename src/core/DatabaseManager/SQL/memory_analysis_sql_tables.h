// memory_analysis_sql.h
// SQL statements for the MemoryAnalyzer database (_memory.db)

#pragma once
#ifndef MEMORY_ANALYSIS_SQL_TABLES_H
#define MEMORY_ANALYSIS_SQL_TABLES_H

namespace MemoryAnalysisSQL {

// Consolidated multi-statement CREATE TABLE block. Run via sqlite3_exec().
inline constexpr const char* CREATE_ALL_TABLES = R"(
    CREATE TABLE IF NOT EXISTS processes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        offset INTEGER,
        pid INTEGER,
        ppid INTEGER,
        comm TEXT,
        uid INTEGER,
        gid INTEGER,
        start_time INTEGER,
        thread_count INTEGER,
        state TEXT,
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS network_connections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        offset INTEGER,
        pid INTEGER,
        comm TEXT,
        protocol TEXT,
        local_addr TEXT,
        local_port INTEGER,
        foreign_addr TEXT,
        foreign_port INTEGER,
        state TEXT,
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS sockets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        offset INTEGER,
        pid INTEGER,
        comm TEXT,
        family TEXT,
        type TEXT,
        local_addr TEXT,
        remote_addr TEXT,
        state TEXT,
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS bash_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pid INTEGER,
        comm TEXT,
        command TEXT,
        history_index INTEGER,
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS boot_info (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE,
        value TEXT,
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS cmdline (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pid INTEGER,
        comm TEXT,
        args TEXT,
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS analysis_meta (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE,
        value TEXT,
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE INDEX IF NOT EXISTS idx_processes_pid ON processes(pid);
    CREATE INDEX IF NOT EXISTS idx_net_pid ON network_connections(pid);
    CREATE INDEX IF NOT EXISTS idx_net_fport ON network_connections(foreign_port);
    CREATE INDEX IF NOT EXISTS idx_bash_command ON bash_history(command);
)";

} // namespace MemoryAnalysisSQL

#endif // MEMORY_ANALYSIS_SQL_TABLES_H
