// memory_analysis_sql.h
// SQL statements for the MemoryAnalyzer database (_memory.db)

#pragma once
#ifndef MEMORY_ANALYSIS_SQL_TABLES_H
#define MEMORY_ANALYSIS_SQL_TABLES_H

namespace MemoryAnalysisSQL {

// Consolidated multi-statement CREATE TABLE block. Run via sqlite3_exec().
// Columns mirror the real Volatility3 (2.x) JSON output field names so the
// parsers can map fields 1:1 without renaming.
inline constexpr const char* CREATE_ALL_TABLES = R"(
    CREATE TABLE IF NOT EXISTS processes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        offset INTEGER,           -- OFFSET (V)
        pid INTEGER,
        tid INTEGER,
        ppid INTEGER,
        comm TEXT,                -- COMM
        uid INTEGER,
        gid INTEGER,
        euid INTEGER,
        egid INTEGER,
        creation_time TEXT,       -- CREATION TIME (ISO 8601)
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS network_connections (
        -- Populated from linux.sockstat (vol3 2.x has no linux.netstat).
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        offset INTEGER,           -- Sock Offset
        pid INTEGER,
        tid INTEGER,
        comm TEXT,                -- Process Name
        family TEXT,              -- Family (AF_INET, AF_UNIX, ...)
        type TEXT,                -- Type (STREAM, DGRAM, ...)
        proto TEXT,               -- Proto
        local_addr TEXT,          -- Source Addr
        local_port TEXT,          -- Source Port (string in vol3 output)
        remote_addr TEXT,         -- Destination Addr
        remote_port TEXT,         -- Destination Port
        state TEXT,               -- State
        netns INTEGER,
        inserted_at INTEGER DEFAULT (strftime('%s','now'))
    );

    CREATE TABLE IF NOT EXISTS bash_history (
        -- Populated from linux.bash.
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pid INTEGER,
        comm TEXT,                -- Process
        command TEXT,             -- Command
        command_time TEXT,        -- CommandTime (ISO 8601) — key for Q102/Q103
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
        -- Populated from linux.psaux (vol3 2.x has no linux.cmdline).
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
    CREATE INDEX IF NOT EXISTS idx_net_rport ON network_connections(remote_port);
    CREATE INDEX IF NOT EXISTS idx_net_lport ON network_connections(local_port);
    CREATE INDEX IF NOT EXISTS idx_bash_command ON bash_history(command);
    CREATE INDEX IF NOT EXISTS idx_bash_cmdtime ON bash_history(command_time);
)";

} // namespace MemoryAnalysisSQL

#endif // MEMORY_ANALYSIS_SQL_TABLES_H
