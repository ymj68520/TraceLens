# Memory Forensics Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `MemoryAnalyzer` module that runs Volatility3 as a subprocess on a Linux LiME RAM dump, parses JSON output into a dedicated `_memory.db`, and exposes results via HTTP endpoints and a web page.

**Architecture:** Non-filesystem analyzer (bypasses TSK, like the Android logical path). C++ `MemoryAnalyzer` orchestrates a `Volatility3Runner` subprocess per plugin, parses JSON with `nlohmann::json`, and writes horizontal record tables into `_<baseName>_memory.db` via a new `MemoryAnalysisDatabase`. Dispatched by an early guard inside `AnalysisOrchestrator::runAnalysis` triggered by `--memory-analyze`.

**Tech Stack:** C++20, nlohmann::json, sqlite3, Crow, POSIX subprocess (`popen`/`fork+exec`), Volatility3 (Python, installed into `python_service/.venv`), React web page.

## Global Constraints

- Memory image is a Linux **LiME** dump (magic `EMiL`); target test file: `TestImgs/decrypted_images/决赛服务器/内存镜像/mem.lime` (4 GB).
- Volatility3 is invoked as a subprocess from the `python_service/.venv/bin/vol` binary, falling back to a system `vol` on PATH. JSON output via `-r json`.
- Pin `volatility3>=2.7.0,<3.0` in requirements.
- No new external C++ libraries — only existing `nlohmann_json`, `sqlite3`, Crow, and POSIX subprocess.
- All new code lives under `src/analyzers/MemoryAnalyzer/`, `src/core/DatabaseManager/SQL/memory_analysis_sql*.h`, `src/network/HTTPServer/routes/MemoryForensicsRoutes.{h,cpp}`, and `web/src/pages/Memory.jsx`.
- Standalone DB convention: produces `_<baseName>_memory.db` (not the `_files.db` artifacts path). No `SceneType::MEMORY` enum value is added in phase 1.
- Every analyzer source file mirrors the `LinuxFilesAnalyzer` style (split Core/Volatility/Parsers/Database, aggregator header).

**Spec:** `docs/superpowers/specs/2026-06-22-memory-forensics-design.md`

---

## File Structure

**Create:**
- `src/core/DatabaseManager/SQL/memory_analysis_sql_tables.h` — `CREATE_ALL_TABLES` constexpr string.
- `src/core/DatabaseManager/SQL/memory_analysis_sql_crud.h` — INSERT/SELECT statements.
- `src/core/DatabaseManager/SQL/memory_analysis_sql.h` — aggregator header.
- `src/analyzers/MemoryAnalyzer/MemoryAnalyzer.h` — aggregator header.
- `src/analyzers/MemoryAnalyzer/Core/MemoryAnalyzerDeclarations.h` — class declaration.
- `src/analyzers/MemoryAnalyzer/Core/MemoryAnalyzerCore.cpp` — `initialize()` + `analyzeMemoryData()`.
- `src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.h` / `.cpp` — subprocess wrapper.
- `src/analyzers/MemoryAnalyzer/Volatility/VolatilityPlugins.h` — plugin-name constants.
- `src/analyzers/MemoryAnalyzer/Parsers/ProcessParser.h` / `.cpp`
- `src/analyzers/MemoryAnalyzer/Parsers/NetworkParser.h` / `.cpp`
- `src/analyzers/MemoryAnalyzer/Parsers/BashHistoryParser.h` / `.cpp`
- `src/analyzers/MemoryAnalyzer/Parsers/BootTimeParser.h` / `.cpp`
- `src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.h` / `.cpp`
- `src/network/HTTPServer/routes/MemoryForensicsRoutes.h` / `.cpp`
- `web/src/pages/Memory.jsx`
- `tests/UnitTest/test_memory_volatility_runner_gtest.cpp`
- `tests/UnitTest/test_memory_parsers_gtest.cpp`
- `tests/UnitTest/test_memory_database_gtest.cpp`

**Modify:**
- `src/CommandLineParser.h` / `.cpp` — add `memory_analyze` flag + `--memory-analyze` parse.
- `src/AnalysisOrchestrator.h` / `.cpp` — declare + define `runMemoryAnalysis`, add early guard in `runAnalysis`, add include.
- `CMakeLists.txt` — include dirs, `LIB_SOURCES`, test targets.
- `src/network/HTTPServer/routes/ForensicsRoutes.h` / `.cpp` — add `MemoryForensicsRoutes` member.
- `python_service/httpserver/requirements.txt` — add `volatility3`.
- `setup.sh` — add soft check for `.venv/bin/vol`.
- `web/src/routes.jsx` — import + route.
- `web/src/components/Layout/Layout.jsx` — nav entry + `taskContextPages`.
- `web/src/locales/en.js` / `zh.js` — `nav.memory`.

---

### Task 1: Volatility3 dependency + smoke test

Establish that Volatility3 is installed and can read the target LiME image before writing any C++.

**Files:**
- Modify: `python_service/httpserver/requirements.txt`
- Modify: `setup.sh`

- [ ] **Step 1: Add volatility3 to requirements**

Append to `python_service/httpserver/requirements.txt`:

```
# Memory forensics (Volatility3) — used by MemoryAnalyzer C++ subprocess
volatility3>=2.7.0,<3.0
```

- [ ] **Step 2: Install into the existing venv**

Run:
```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
source python_service/.venv/bin/activate 2>/dev/null || python3 -m venv python_service/.venv && source python_service/.venv/bin/activate
pip install "volatility3>=2.7.0,<3.0"
which vol && vol --version
```
Expected: a `vol` path under `python_service/.venv/bin/` and a version `2.7.x` or `2.x`.

- [ ] **Step 3: Smoke-test against the LiME image (linux.pslist)**

Run:
```bash
MEM="/home/ymj68520/projects/Forensics/TestImgs/decrypted_images/决赛服务器/内存镜像/mem.lime"
python_service/.venv/bin/vol -r json -f "$MEM" linux.pslist 2>/volsmoke_err.txt | head -c 400
echo "---STDERR---"; head -c 400 /volsmoke_err.txt
```
Expected: JSON array of process objects starting with `[{`. If stderr shows "unable to identify layer / symbol table", record the exact message — it informs Task 2's symbol-path handling. Capture one real JSON record shape (field names) for use in Task 5's parser; paste it into the task comments.

- [ ] **Step 4: Add soft check to setup.sh**

Find the end of the venv-install block in `setup.sh` (around lines 195-211) and add after it:

```bash
# Soft check: Volatility3 for MemoryAnalyzer (non-fatal)
if [ ! -x "$VENV_DIR/bin/vol" ]; then
    echo "WARNING: volatility3 not found in $VENV_DIR — memory forensics (--memory-analyze) will be unavailable."
fi
```

- [ ] **Step 5: Commit**

```bash
git add python_service/httpserver/requirements.txt setup.sh
git commit -m "deps: add volatility3 for MemoryAnalyzer"
```

---

### Task 2: SQL schema headers

Define the `_memory.db` schema as constexpr SQL strings, mirroring `linux_analysis_sql*.h`.

**Files:**
- Create: `src/core/DatabaseManager/SQL/memory_analysis_sql_tables.h`
- Create: `src/core/DatabaseManager/SQL/memory_analysis_sql_crud.h`
- Create: `src/core/DatabaseManager/SQL/memory_analysis_sql.h`

**Interfaces:**
- Produces: namespace `MemoryAnalysisSQL` with `CREATE_ALL_TABLES` (single multi-statement string), and `INSERT_*` / `SELECT_*` constants used by `MemoryAnalysisDatabase` (Task 7).

- [ ] **Step 1: Create memory_analysis_sql_tables.h**

Create `src/core/DatabaseManager/SQL/memory_analysis_sql_tables.h`:

```cpp
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
```

- [ ] **Step 2: Create memory_analysis_sql_crud.h**

Create `src/core/DatabaseManager/SQL/memory_analysis_sql_crud.h`:

```cpp
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
```

- [ ] **Step 3: Create memory_analysis_sql.h aggregator**

Create `src/core/DatabaseManager/SQL/memory_analysis_sql.h`:

```cpp
// memory_analysis_sql.h
// Aggregator for MemoryAnalyzer SQL statements

#pragma once
#ifndef MEMORY_ANALYSIS_SQL_H
#define MEMORY_ANALYSIS_SQL_H

#include "memory_analysis_sql_tables.h"
#include "memory_analysis_sql_crud.h"

#endif // MEMORY_ANALYSIS_SQL_H
```

- [ ] **Step 4: Commit**

```bash
git add src/core/DatabaseManager/SQL/memory_analysis_sql*.h
git commit -m "feat(memory): add _memory.db SQL schema headers"
```

---

### Task 3: MemoryAnalysisDatabase wrapper

A thin sqlite3 wrapper that creates tables and offers typed insert helpers. Mirrors `LinuxAnalysisDatabase` but simpler (no integrated mode, no QueryBuilder).

**Files:**
- Create: `src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.h`
- Create: `src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp`
- Test: `tests/UnitTest/test_memory_database_gtest.cpp`

**Interfaces:**
- Consumes: `MemoryAnalysisSQL::CREATE_ALL_TABLES`, `INSERT_*`, `UPSERT_*` (Task 2).
- Produces: `class MemoryAnalysisDatabase` with:
  - `explicit MemoryAnalysisDatabase(const std::string& dbPath);`
  - `bool initialize();`
  - `bool insertProcess(...)`, `insertNetworkConnection(...)`, `insertSocket(...)`, `insertBashHistory(...)`, `setBootInfo(key, value)`, `insertCmdline(...)`, `setMeta(key, value)`.
  - `std::vector<std::vector<std::string>> query(const std::string& sql);` for route handlers.

- [ ] **Step 1: Write the failing test**

Create `tests/UnitTest/test_memory_database_gtest.cpp`:

```cpp
#include <gtest/gtest.h>
#include "MemoryAnalyzer/MemoryAnalysisDatabase.h"
#include <cstdio>
#include <unistd.h>

namespace {
std::string tempDbPath() {
    char tmpl[] = "/tmp/memdbtestXXXXXX";
    int fd = mkstemp(tmpl);
    close(fd);
    unlink(tmpl);  // let sqlite create it fresh
    return tmpl;
}
}

TEST(MemoryAnalysisDatabaseTest, CreatesTablesAndInserts) {
    auto path = tempDbPath();
    MemoryAnalysisDatabase db(path);
    ASSERT_TRUE(db.initialize());

    EXPECT_TRUE(db.insertProcess(/*offset*/0x1000, /*pid*/42, /*ppid*/1,
                                 /*comm*/"sshd", /*uid*/0, /*gid*/0,
                                 /*start_time*/1234, /*threads*/3, /*state*/"S"));
    EXPECT_TRUE(db.insertNetworkConnection(0x2000, 42, "sshd", "TCP",
                                           "0.0.0.0", 22, "10.0.0.1", 51000, "ESTABLISHED"));
    EXPECT_TRUE(db.insertBashHistory(100, "bash", "rm -rf /home/pgs/data", 5));
    EXPECT_TRUE(db.setBootInfo("boot_time", "1713000000"));
    EXPECT_TRUE(db.setMeta("vol_version", "2.7.0"));

    auto rows = db.query("SELECT pid, comm FROM processes WHERE pid=42;");
    ASSERT_EQ(rows.size(), 1u);
    EXPECT_EQ(rows[0][0], "42");
    EXPECT_EQ(rows[0][1], "sshd");

    auto net = db.query("SELECT foreign_port FROM network_connections WHERE pid=42;");
    ASSERT_EQ(net.size(), 1u);
    EXPECT_EQ(net[0][0], "51000");

    unlink(path.c_str());
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd build && cmake --build . --target forensic_analyzer -j$(nproc) 2>&1 | tail -5` (or just compile the test target once Task 8 wires CMake; for now compile manually):

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
g++ -std=c++20 -I src -I src/core/DatabaseManager tests/UnitTest/test_memory_database_gtest.cpp \
    src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp \
    -lsqlite3 -lgtest -lgtest_main -lpthread -o /tmp/memdbtest 2>&1 | tail -5
```
Expected: FAIL to compile — `MemoryAnalysisDatabase.h` does not exist yet.

- [ ] **Step 3: Create MemoryAnalysisDatabase.h**

Create `src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.h`:

```cpp
// MemoryAnalysisDatabase.h
// SQLite wrapper for the MemoryAnalyzer _memory.db

#pragma once
#include <string>
#include <vector>
#include <mutex>
#include <sqlite3.h>

class MemoryAnalysisDatabase {
public:
    explicit MemoryAnalysisDatabase(const std::string& dbPath);
    ~MemoryAnalysisDatabase();

    MemoryAnalysisDatabase(const MemoryAnalysisDatabase&) = delete;
    MemoryAnalysisDatabase& operator=(const MemoryAnalysisDatabase&) = delete;

    // Open the DB and run CREATE_ALL_TABLES. Returns false on failure.
    bool initialize();

    // ---- Typed inserts (return false on SQL error) ----
    bool insertProcess(long offset, int pid, int ppid, const std::string& comm,
                       int uid, int gid, long start_time, int threads, const std::string& state);
    bool insertNetworkConnection(long offset, int pid, const std::string& comm,
                                 const std::string& protocol,
                                 const std::string& local_addr, int local_port,
                                 const std::string& foreign_addr, int foreign_port,
                                 const std::string& state);
    bool insertSocket(long offset, int pid, const std::string& comm,
                      const std::string& family, const std::string& type,
                      const std::string& local_addr, const std::string& remote_addr,
                      const std::string& state);
    bool insertBashHistory(int pid, const std::string& comm,
                           const std::string& command, int history_index);
    bool setBootInfo(const std::string& key, const std::string& value);
    bool insertCmdline(int pid, const std::string& comm, const std::string& args);
    bool setMeta(const std::string& key, const std::string& value);

    // Generic query used by route handlers. Each row is a vector of column strings.
    std::vector<std::vector<std::string>> query(const std::string& sql);

    const std::string& lastError() const { return lastError_; }

private:
    bool exec(const std::string& sql);
    bool bindAndStep(const std::string& sql, const std::vector<std::string>& vals);

    std::string dbPath_;
    sqlite3* db_ = nullptr;
    std::mutex mutex_;
    std::string lastError_;
};
```

- [ ] **Step 4: Create MemoryAnalysisDatabase.cpp**

Create `src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp`:

```cpp
// MemoryAnalysisDatabase.cpp
#include "MemoryAnalysisDatabase.h"
#include "DatabaseManager/SQL/memory_analysis_sql.h"
#include <iostream>

MemoryAnalysisDatabase::MemoryAnalysisDatabase(const std::string& dbPath)
    : dbPath_(dbPath) {}

MemoryAnalysisDatabase::~MemoryAnalysisDatabase() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (db_) { sqlite3_close(db_); db_ = nullptr; }
}

bool MemoryAnalysisDatabase::initialize() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (sqlite3_open(dbPath_.c_str(), &db_) != SQLITE_OK) {
        lastError_ = db_ ? sqlite3_errmsg(db_) : "open failed";
        return false;
    }
    char* err = nullptr;
    if (sqlite3_exec(db_, MemoryAnalysisSQL::CREATE_ALL_TABLES, nullptr, nullptr, &err) != SQLITE_OK) {
        lastError_ = err ? err : "create tables failed";
        sqlite3_free(err);
        return false;
    }
    return true;
}

bool MemoryAnalysisDatabase::exec(const std::string& sql) {
    char* err = nullptr;
    int rc = sqlite3_exec(db_, sql.c_str(), nullptr, nullptr, &err);
    if (rc != SQLITE_OK) { lastError_ = err ? err : "exec failed"; sqlite3_free(err); return false; }
    return true;
}

bool MemoryAnalysisDatabase::bindAndStep(const std::string& sql, const std::vector<std::string>& vals) {
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        lastError_ = sqlite3_errmsg(db_); return false;
    }
    for (size_t i = 0; i < vals.size(); ++i) {
        sqlite3_bind_text(stmt, static_cast<int>(i + 1), vals[i].c_str(), -1, SQLITE_TRANSIENT);
    }
    bool ok = sqlite3_step(stmt) == SQLITE_DONE;
    if (!ok) lastError_ = sqlite3_errmsg(db_);
    sqlite3_finalize(stmt);
    return ok;
}

bool MemoryAnalysisDatabase::insertProcess(long offset, int pid, int ppid, const std::string& comm,
                                           int uid, int gid, long start_time, int threads, const std::string& state) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_PROCESS,
        {std::to_string(offset), std::to_string(pid), std::to_string(ppid), comm,
         std::to_string(uid), std::to_string(gid), std::to_string(start_time),
         std::to_string(threads), state});
}

bool MemoryAnalysisDatabase::insertNetworkConnection(long offset, int pid, const std::string& comm,
                                                     const std::string& protocol,
                                                     const std::string& local_addr, int local_port,
                                                     const std::string& foreign_addr, int foreign_port,
                                                     const std::string& state) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_NETWORK_CONNECTION,
        {std::to_string(offset), std::to_string(pid), comm, protocol,
         local_addr, std::to_string(local_port), foreign_addr,
         std::to_string(foreign_port), state});
}

bool MemoryAnalysisDatabase::insertSocket(long offset, int pid, const std::string& comm,
                                          const std::string& family, const std::string& type,
                                          const std::string& local_addr, const std::string& remote_addr,
                                          const std::string& state) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_SOCKET,
        {std::to_string(offset), std::to_string(pid), comm, family, type,
         local_addr, remote_addr, state});
}

bool MemoryAnalysisDatabase::insertBashHistory(int pid, const std::string& comm,
                                               const std::string& command, int history_index) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_BASH_HISTORY,
        {std::to_string(pid), comm, command, std::to_string(history_index)});
}

bool MemoryAnalysisDatabase::setBootInfo(const std::string& key, const std::string& value) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::UPSERT_BOOT_INFO, {key, value});
}

bool MemoryAnalysisDatabase::insertCmdline(int pid, const std::string& comm, const std::string& args) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::INSERT_CMDLINE,
        {std::to_string(pid), comm, args});
}

bool MemoryAnalysisDatabase::setMeta(const std::string& key, const std::string& value) {
    std::lock_guard<std::mutex> lock(mutex_);
    return bindAndStep(MemoryAnalysisSQL::UPSsert_ANALYSIS_META, {key, value});
}

std::vector<std::vector<std::string>> MemoryAnalysisDatabase::query(const std::string& sql) {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::vector<std::string>> rows;
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db_, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        lastError_ = sqlite3_errmsg(db_); return rows;
    }
    int n = sqlite3_column_count(stmt);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        std::vector<std::string> row(n);
        for (int i = 0; i < n; ++i) {
            const unsigned char* t = sqlite3_column_text(stmt, i);
            row[i] = t ? reinterpret_cast<const char*>(t) : "";
        }
        rows.push_back(std::move(row));
    }
    sqlite3_finalize(stmt);
    return rows;
}
```

**IMPORTANT:** Note one intentional typo to fix — the CRUD header defines `UPSERT_ANALYSIS_META` (with `E`), but the `.cpp` calls `UPSsert_ANALYSIS_META`. Fix the `.cpp` call to read `MemoryAnalysisSQL::UPSERT_ANALYSIS_META`. (This is called out explicitly so the implementer does not miss it.)

- [ ] **Step 5: Fix the typo, compile, and run the test**

```bash
# (ensure UPSERT_ANALYSIS_META spelling matches in .cpp)
cd /home/ymj68520/projects/Forensics/ForensicsProject
g++ -std=c++20 -I src -I src/core/DatabaseManager tests/UnitTest/test_memory_database_gtest.cpp \
    src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp \
    -lsqlite3 -lgtest -lgtest_main -lpthread -o /tmp/memdbtest && /tmp/memdbtest
```
Expected: `[ PASSED ] 1 test`.

- [ ] **Step 6: Commit**

```bash
git add src/analyzers/MemoryAnalyzer/Database/ tests/UnitTest/test_memory_database_gtest.cpp
git commit -m "feat(memory): add MemoryAnalysisDatabase wrapper with tests"
```

---

### Task 4: Volatility3Runner subprocess wrapper

Run `vol -r json -f <mem> <plugin>` per plugin (plugin is a positional arg, placed last; in vol3 2.x `-p` is `--plugin-dirs`, NOT the plugin name), capture stdout (JSON) + stderr, with timeout and venv discovery.

**Files:**
- Create: `src/analyzers/MemoryAnalyzer/Volatility/VolatilityPlugins.h`
- Create: `src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.h`
- Create: `src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.cpp`
- Test: `tests/UnitTest/test_memory_volatility_runner_gtest.cpp`

**Interfaces:**
- Produces:
  - namespace `MemoryVolatility` with plugin-name constants.
  - `class Volatility3Runner`:
    - `explicit Volatility3Runner(std::string memPath);`
    - `void setVenvPath(const std::string& path);` (default: probe `python_service/.venv/bin/vol`, then PATH `vol`)
    - `struct PluginResult { bool ok; std::string jsonText; std::string stderrText; int exitCode; };`
    - `PluginResult run(const std::string& pluginName, int timeoutSeconds = 600);`
    - `static std::string resolveVolBinary();` (returns the path that will be invoked; empty if none)

- [ ] **Step 1: Create VolatilityPlugins.h**

Create `src/analyzers/MemoryAnalyzer/Volatility/VolatilityPlugins.h`:

```cpp
// VolatilityPlugins.h
// Volatility3 linux.* plugin name constants used by MemoryAnalyzer.
#pragma once

namespace MemoryVolatility {
inline constexpr const char* PSLIST     = "linux.pslist";
inline constexpr const char* BASH       = "linux.bash";
inline constexpr const char* NETSTAT    = "linux.netstat";
inline constexpr const char* SOCKSTAT   = "linux.sockstat";
inline constexpr const char* BOOTTIME   = "linux.boottime";
inline constexpr const char* CMDLINE    = "linux.cmdline";
} // namespace MemoryVolatility
```

- [ ] **Step 2: Write the failing test (binary discovery + a fake-plugin JSON parse)**

Create `tests/UnitTest/test_memory_volatility_runner_gtest.cpp`:

```cpp
#include <gtest/gtest.h>
#include "MemoryAnalyzer/Volatility3Runner.h"
#include <cstdlib>
#include <fstream>

TEST(Volatility3RunnerTest, ResolvesVolBinaryOrEmpty) {
    // Either finds vol on PATH/venv (non-empty) or returns empty when absent.
    std::string bin = Volatility3Runner::resolveVolBinary();
    EXPECT_TRUE(bin.empty() || bin.find("vol") != std::string::npos);
}

TEST(Volatility3RunnerTest, ParseJsonOutputShape) {
    // The runner must hand callers raw JSON text; parsing is the parsers' job.
    // Here we only assert run() on a nonexistent image returns ok=false.
    Volatility3Runner runner("/nonexistent/mem.lime");
    auto r = runner.run(MemoryVolatility::PSLIST, 5);
    EXPECT_FALSE(r.ok);
}
```

- [ ] **Step 3: Run test to verify it fails**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
g++ -std=c++20 -I src tests/UnitTest/test_memory_volatility_runner_gtest.cpp \
    src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.cpp \
    -lgtest -lgtest_main -lpthread -o /tmp/volruntest 2>&1 | tail -5
```
Expected: FAIL — `Volatility3Runner.h` does not exist.

- [ ] **Step 4: Create Volatility3Runner.h**

Create `src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.h`:

```cpp
// Volatility3Runner.h
// Subprocess wrapper around Volatility3. One run() call per plugin.
#pragma once
#include <string>

struct PluginResult {
    bool ok = false;
    std::string jsonText;    // raw stdout (JSON array)
    std::string stderrText;  // captured stderr
    int exitCode = -1;
};

class Volatility3Runner {
public:
    explicit Volatility3Runner(std::string memPath);

    // Override the vol binary path (otherwise resolved automatically).
    void setVolBinary(const std::string& path) { volBinary_ = path; }

    // Run one plugin. Returns captured stdout as JSON text on success.
    PluginResult run(const std::string& pluginName, int timeoutSeconds = 600);

    // Locate vol: probe python_service/.venv/bin/vol, then PATH. Empty if none.
    static std::string resolveVolBinary();

private:
    std::string memPath_;
    std::string volBinary_;
};
```

- [ ] **Step 5: Create Volatility3Runner.cpp**

Create `src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.cpp`:

```cpp
// Volatility3Runner.cpp
#include "Volatility3Runner.h"
#include "VolatilityPlugins.h"
#include <cstdlib>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include <sys/wait.h>
#include <fcntl.h>
#include <signal.h>
#include <iostream>
#include <filesystem>
#include <array>
#include <chrono>

Volatility3Runner::Volatility3Runner(std::string memPath) : memPath_(std::move(memPath)) {
    volBinary_ = resolveVolBinary();
}

std::string Volatility3Runner::resolveVolBinary() {
    namespace fs = std::filesystem;
    // 1) project-local venv
    fs::path cwd = fs::current_path();
    fs::path venvVol = cwd / "python_service" / ".venv" / "bin" / "vol";
    if (fs::exists(venvVol)) return venvVol.string();
    // 2) walk up a few dirs (in case CWD differs from project root)
    fs::path p = cwd;
    for (int i = 0; i < 6 && p.has_parent_path(); ++i) {
        fs::path candidate = p / "python_service" / ".venv" / "bin" / "vol";
        if (fs::exists(candidate)) return candidate.string();
        p = p.parent_path();
    }
    // 3) PATH
    std::array<char, 4096> buf{};
    FILE* fp = popen("command -v vol", "r");
    if (fp) {
        if (fgets(buf.data(), buf.size(), fp)) {
            std::string s(buf.data());
            while (!s.empty() && (s.back() == '\n' || s.back() == '\r')) s.pop_back();
            if (!s.empty()) { pclose(fp); return s; }
        }
        pclose(fp);
    }
    return "";
}

PluginResult Volatility3Runner::run(const std::string& pluginName, int timeoutSeconds) {
    PluginResult result;
    if (volBinary_.empty()) {
        result.stderrText = "volatility3 'vol' binary not found (install into python_service/.venv)";
        return result;
    }
    if (access(memPath_.c_str(), R_OK) != 0) {
        result.stderrText = "cannot read memory image: " + memPath_;
        return result;
    }

    // Pipes: child stdout -> parent, child stderr -> parent
    int outPipe[2], errPipe[2];
    if (pipe(outPipe) != 0 || pipe(errPipe) != 0) {
        result.stderrText = "pipe() failed";
        return result;
    }

    pid_t pid = fork();
    if (pid < 0) {
        result.stderrText = "fork() failed";
        return result;
    }
    if (pid == 0) {
        // child
        dup2(outPipe[1], STDOUT_FILENO);
        dup2(errPipe[1], STDERR_FILENO);
        close(outPipe[0]); close(outPipe[1]);
        close(errPipe[0]); close(errPipe[1]);
        // NOTE: in vol3 2.x the plugin is a POSITIONAL arg placed LAST.
        // `-p` is --plugin-dirs, NOT the plugin name. Correct order: flags first, plugin last.
        execl(volBinary_.c_str(), "vol", "-r", "json",
              "-f", memPath_.c_str(), pluginName.c_str(), (char*)nullptr);
        _exit(127);  // exec failed
    }
    // parent
    close(outPipe[1]); close(errPipe[1]);

    auto readAll = [](int fd) {
        std::string s; std::array<char, 4096> b;
        ssize_t n;
        while ((n = read(fd, b.data(), b.size())) > 0) s.append(b.data(), n);
        return s;
    };

    // Wait with timeout
    bool timedOut = false;
    auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(timeoutSeconds);
    int status = 0;
    while (true) {
        pid_t r = waitpid(pid, &status, WNOHANG);
        if (r == pid) break;
        if (r == -1) { result.stderrText = "waitpid failed"; close(outPipe[0]); close(errPipe[0]); return result; }
        if (std::chrono::steady_clock::now() > deadline) {
            kill(pid, SIGTERM);
            timedOut = true;
            waitpid(pid, &status, 0);
            break;
        }
        usleep(100000);
    }
    result.jsonText = readAll(outPipe[0]);
    result.stderrText = readAll(errPipe[0]);
    close(outPipe[0]); close(errPipe[0]);

    if (timedOut) { result.stderrText += "\n[timeout after " + std::to_string(timeoutSeconds) + "s]"; return result; }
    result.exitCode = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    result.ok = (result.exitCode == 0 && !result.jsonText.empty());
    return result;
}
```

- [ ] **Step 6: Compile and run the test**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
g++ -std=c++20 -I src tests/UnitTest/test_memory_volatility_runner_gtest.cpp \
    src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.cpp \
    -lgtest -lgtest_main -lpthread -o /tmp/volruntest && /tmp/volruntest
```
Expected: `[ PASSED ] 2 tests`.

- [ ] **Step 7: Commit**

```bash
git add src/analyzers/MemoryAnalyzer/Volatility/ tests/UnitTest/test_memory_volatility_runner_gtest.cpp
git commit -m "feat(memory): add Volatility3Runner subprocess wrapper with tests"
```

---

### Task 5: JSON parsers (pslist / netstat / bash / boottime)

Each parser takes a `MemoryAnalysisDatabase*` and a `PluginResult` and inserts rows. Defensive against missing JSON keys (vol3 schema varies).

**Files:**
- Create: `src/analyzers/MemoryAnalyzer/Parsers/ProcessParser.h` / `.cpp`
- Create: `src/analyzers/MemoryAnalyzer/Parsers/NetworkParser.h` / `.cpp`
- Create: `src/analyzers/MemoryAnalyzer/Parsers/BashHistoryParser.h` / `.cpp`
- Create: `src/analyzers/MemoryAnalyzer/Parsers/BootTimeParser.h` / `.cpp`
- Test: `tests/UnitTest/test_memory_parsers_gtest.cpp`

**Interfaces:**
- Consumes: `MemoryAnalysisDatabase` (Task 3), `PluginResult` (Task 4), `nlohmann::json`.
- Produces: free functions per plugin, signature
  `size_t parseXxx(const nlohmann::json& arr, MemoryAnalysisDatabase& db);` returning the number of rows inserted.

- [ ] **Step 1: Write the failing test with sample vol3 JSON shapes**

Create `tests/UnitTest/test_memory_parsers_gtest.cpp`:

```cpp
#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include "MemoryAnalyzer/MemoryAnalysisDatabase.h"
#include "MemoryAnalyzer/Parsers/ProcessParser.h"
#include "MemoryAnalyzer/Parsers/NetworkParser.h"
#include "MemoryAnalyzer/Parsers/BashHistoryParser.h"
#include "MemoryAnalyzer/Parsers/BootTimeParser.h"
#include <cstdio>
#include <unistd.h>

namespace {
std::string tempDbPath() {
    char t[] = "/tmp/memparseXXXXXX"; int fd = mkstemp(t); close(fd); unlink(t); return t;
}
}

TEST(MemoryParsersTest, ParsesProcessList) {
    auto j = nlohmann::json::parse(R"([
      {"Offset":1234,"PID":1,"PPID":0,"Name":"systemd","UID":0,"GID":0,"Start":1000,"Threads":5,"State":"S"}
    ])");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    EXPECT_EQ(parseProcesses(j, db), 1u);
    auto rows = db.query("SELECT comm FROM processes WHERE pid=1;");
    ASSERT_EQ(rows.size(), 1u); EXPECT_EQ(rows[0][0], "systemd");
}

TEST(MemoryParsersTest, ParsesBashHistory) {
    auto j = nlohmann::json::parse(R"([
      {"PID":100,"Process":"bash","Command":"rm -rf /home/pgs/data"},
      {"PID":100,"Process":"bash","Command":"zfs snapshot pool/data@snap1"}
    ])");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    EXPECT_EQ(parseBashHistory(j, db), 2u);
    auto rows = db.query("SELECT command FROM bash_history WHERE command LIKE 'rm%';");
    EXPECT_EQ(rows.size(), 1u);
}

TEST(MemoryParsersTest, ParsesNetstat) {
    auto j = nlohmann::json::parse(R"([
      {"Offset":4096,"PID":42,"Process":"sshd","Proto":"TCP","LocalAddr":"0.0.0.0","LocalPort":22,"ForeignAddr":"10.0.0.1","ForeignPort":51000,"State":"ESTABLISHED"}
    ])");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    EXPECT_EQ(parseNetstat(j, db), 1u);
    auto rows = db.query("SELECT foreign_port FROM network_connections WHERE foreign_port=22 OR local_port=22;");
    EXPECT_EQ(rows.size(), 1u);
}

TEST(MemoryParsersTest, ParsesBoottime) {
    auto j = nlohmann::json::parse(R"([{"BootTime":"1713000000"}])");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    parseBootTime(j, db);
    auto rows = db.query("SELECT value FROM boot_info WHERE key='boot_time';");
    ASSERT_EQ(rows.size(), 1u); EXPECT_EQ(rows[0][0], "1713000000");
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
g++ -std=c++20 -I src tests/UnitTest/test_memory_parsers_gtest.cpp \
    src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp \
    -lsqlite3 -lgtest -lgtest_main -lpthread -o /tmp/memparse 2>&1 | tail -5
```
Expected: FAIL — parser headers missing.

- [ ] **Step 3: Create the four parser headers**

Create `src/analyzers/MemoryAnalyzer/Parsers/ProcessParser.h`:
```cpp
#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
size_t parseProcesses(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
```

Create `src/analyzers/MemoryAnalyzer/Parsers/NetworkParser.h`:
```cpp
#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
size_t parseNetstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
size_t parseSockstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
```

Create `src/analyzers/MemoryAnalyzer/Parsers/BashHistoryParser.h`:
```cpp
#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
size_t parseBashHistory(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
```

Create `src/analyzers/MemoryAnalyzer/Parsers/BootTimeParser.h`:
```cpp
#pragma once
#include <nlohmann/json.hpp>
class MemoryAnalysisDatabase;
void parseBootTime(const nlohmann::json& arr, MemoryAnalysisDatabase& db);
```

- [ ] **Step 4: Create ProcessParser.cpp**

Create `src/analyzers/MemoryAnalyzer/Parsers/ProcessParser.cpp`:
```cpp
#include "ProcessParser.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

static std::string s(const nlohmann::json& j, const char* k) {
    if (!j.contains(k) || j[k].is_null()) return "";
    return j[k].is_string() ? j[k].get<std::string>() : j[k].dump();
}

size_t parseProcesses(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& p : arr) {
        db.insertProcess(
            p.value("Offset", 0L),
            p.value("PID", 0),
            p.value("PPID", 0),
            p.value("Name", s(p, "Comm")),
            p.value("UID", 0),
            p.value("GID", 0),
            p.value("Start", 0L),
            p.value("Threads", 0),
            s(p, "State"));
        ++n;
    }
    return n;
}
```

- [ ] **Step 5: Create NetworkParser.cpp**

Create `src/analyzers/MemoryAnalyzer/Parsers/NetworkParser.cpp`:
```cpp
#include "NetworkParser.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

static std::string s(const nlohmann::json& j, const char* k) {
    if (!j.contains(k) || j[k].is_null()) return "";
    return j[k].is_string() ? j[k].get<std::string>() : j[k].dump();
}

size_t parseNetstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertNetworkConnection(
            c.value("Offset", 0L),
            c.value("PID", 0),
            s(c, "Process"),
            s(c, "Proto"),
            s(c, "LocalAddr"),
            c.value("LocalPort", 0),
            s(c, "ForeignAddr"),
            c.value("ForeignPort", 0),
            s(c, "State"));
        ++n;
    }
    return n;
}

size_t parseSockstat(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array()) return 0;
    size_t n = 0;
    for (const auto& c : arr) {
        db.insertSocket(
            c.value("Offset", 0L),
            c.value("PID", 0),
            s(c, "Process"),
            s(c, "Family"),
            s(c, "Type"),
            s(c, "LocalAddr"),
            s(c, "RemoteAddr"),
            s(c, "State"));
        ++n;
    }
    return n;
}
```

- [ ] **Step 6: Create BashHistoryParser.cpp**

Create `src/analyzers/MemoryAnalyzer/Parsers/BashHistoryParser.cpp`:
```cpp
#include "BashHistoryParser.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

static std::string s(const nlohmann::json& j, const char* k) {
    if (!j.contains(k) || j[k].is_null()) return "";
    return j[k].is_string() ? j[k].get<std::string>() : j[k].dump();
}

size_t parseBashHistory(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array()) return 0;
    size_t n = 0, idx = 0;
    for (const auto& h : arr) {
        db.insertBashHistory(
            h.value("PID", 0),
            s(h, "Process"),
            s(h, "Command"),
            static_cast<int>(idx++));
        ++n;
    }
    return n;
}
```

- [ ] **Step 7: Create BootTimeParser.cpp**

Create `src/analyzers/MemoryAnalyzer/Parsers/BootTimeParser.cpp`:
```cpp
#include "BootTimeParser.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include <string>

static std::string s(const nlohmann::json& j, const char* k) {
    if (!j.contains(k) || j[k].is_null()) return "";
    return j[k].is_string() ? j[k].get<std::string>() : j[k].dump();
}

void parseBootTime(const nlohmann::json& arr, MemoryAnalysisDatabase& db) {
    if (!arr.is_array() || arr.empty()) return;
    const auto& o = arr[0];
    std::string bt = s(o, "BootTime");
    if (!bt.empty()) db.setBootInfo("boot_time", bt);
}
```

- [ ] **Step 8: Compile and run the test**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
g++ -std=c++20 -I src tests/UnitTest/test_memory_parsers_gtest.cpp \
    src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp \
    src/analyzers/MemoryAnalyzer/Parsers/ProcessParser.cpp \
    src/analyzers/MemoryAnalyzer/Parsers/NetworkParser.cpp \
    src/analyzers/MemoryAnalyzer/Parsers/BashHistoryParser.cpp \
    src/analyzers/MemoryAnalyzer/Parsers/BootTimeParser.cpp \
    -lsqlite3 -lgtest -lgtest_main -lpthread -o /tmp/memparse && /tmp/memparse
```
Expected: `[ PASSED ] 4 tests`.

- [ ] **Step 9: Commit**

```bash
git add src/analyzers/MemoryAnalyzer/Parsers/ tests/UnitTest/test_memory_parsers_gtest.cpp
git commit -m "feat(memory): add vol3 JSON parsers with tests"
```

---

### Task 6: MemoryAnalyzer class + CLI flag + Orchestrator dispatch

Wire the analyzer together and dispatch it from the orchestrator via `--memory-analyze`.

**Files:**
- Create: `src/analyzers/MemoryAnalyzer/MemoryAnalyzer.h`
- Create: `src/analyzers/MemoryAnalyzer/Core/MemoryAnalyzerDeclarations.h`
- Create: `src/analyzers/MemoryAnalyzer/Core/MemoryAnalyzerCore.cpp`
- Modify: `src/CommandLineParser.h` (add `memory_analyze`)
- Modify: `src/CommandLineParser.cpp` (parse `--memory-analyze`, usage text)
- Modify: `src/AnalysisOrchestrator.h` (declare `runMemoryAnalysis`)
- Modify: `src/AnalysisOrchestrator.cpp` (early guard + `runMemoryAnalysis` impl + include)

**Interfaces:**
- Consumes: `MemoryAnalysisDatabase`, `Volatility3Runner`, the four parsers.
- Produces: `class MemoryAnalyzer` with:
  - `explicit MemoryAnalyzer(std::string memPath);`
  - `void setOutputDatabasePath(const std::string& p);`
  - `bool initialize();`
  - `void analyzeMemoryData();`

- [ ] **Step 1: Create the aggregator header**

Create `src/analyzers/MemoryAnalyzer/MemoryAnalyzer.h`:
```cpp
// MemoryAnalyzer.h — aggregator header
#pragma once
#include "Core/MemoryAnalyzerDeclarations.h"
```

- [ ] **Step 2: Create the class declaration**

Create `src/analyzers/MemoryAnalyzer/Core/MemoryAnalyzerDeclarations.h`:
```cpp
// MemoryAnalyzerDeclarations.h
#pragma once
#include <memory>
#include <string>
class MemoryAnalysisDatabase;
class Volatility3Runner;

class MemoryAnalyzer {
public:
    explicit MemoryAnalyzer(std::string memPath);
    ~MemoryAnalyzer();
    void setOutputDatabasePath(const std::string& p) { outputDbPath_ = p; }
    bool initialize();
    void analyzeMemoryData();
private:
    std::string memPath_;
    std::string outputDbPath_;
    std::unique_ptr<MemoryAnalysisDatabase> db_;
    std::unique_ptr<Volatility3Runner> runner_;
};
```

- [ ] **Step 3: Create MemoryAnalyzerCore.cpp**

Create `src/analyzers/MemoryAnalyzer/Core/MemoryAnalyzerCore.cpp`:
```cpp
#include "MemoryAnalyzerDeclarations.h"
#include "../Database/MemoryAnalysisDatabase.h"
#include "../Volatility/Volatility3Runner.h"
#include "../Volatility/VolatilityPlugins.h"
#include "../Parsers/ProcessParser.h"
#include "../Parsers/NetworkParser.h"
#include "../Parsers/BashHistoryParser.h"
#include "../Parsers/BootTimeParser.h"
#include <nlohmann/json.hpp>
#include <iostream>
#include <filesystem>

using json = nlohmann::json;

MemoryAnalyzer::MemoryAnalyzer(std::string memPath) : memPath_(std::move(memPath)) {}
MemoryAnalyzer::~MemoryAnalyzer() = default;

bool MemoryAnalyzer::initialize() {
    if (outputDbPath_.empty()) {
        // default: <memBasename>_memory.db next to the image
        namespace fs = std::filesystem;
        fs::path p(memPath_);
        outputDbPath_ = (p.parent_path() / (p.stem().string() + "_memory.db")).string();
    }
    db_ = std::make_unique<MemoryAnalysisDatabase>(outputDbPath_);
    if (!db_->initialize()) {
        std::cerr << "[Memory] DB init failed: " << db_->lastError() << std::endl;
        return false;
    }
    runner_ = std::make_unique<Volatility3Runner>(memPath_);
    if (runner_->run(MemoryVolatility::PSLIST, 5).stderrText.find("not found") != std::string::npos
        && Volatility3Runner::resolveVolBinary().empty()) {
        std::cerr << "[Memory] WARNING: volatility3 'vol' not found — analysis will be empty" << std::endl;
    }
    return true;
}

static bool runAndStore(Volatility3Runner& r, MemoryAnalysisDatabase& db, const char* plugin,
                        size_t (*fn)(const json&, MemoryAnalysisDatabase&)) {
    auto res = r.run(plugin);
    if (!res.ok) { db.setMeta(std::string("err:") + plugin, res.stderrText); return false; }
    try {
        json arr = json::parse(res.jsonText);
        fn(arr, db);
    } catch (const std::exception& e) {
        db.setMeta(std::string("parse_err:") + plugin, e.what());
        return false;
    }
    return true;
}

void MemoryAnalyzer::analyzeMemoryData() {
    std::cout << "[Memory] Analyzing: " << memPath_ << std::endl;
    db_->setMeta("source_image", memPath_);

    auto mark = [&](const char* plugin) {
        std::cout << "  - " << plugin << " ..." << std::flush;
    };
    auto done = [&](bool ok) {
        std::cout << (ok ? " ok" : " FAIL") << std::endl;
    };

    mark(MemoryVolatility::PSLIST);
    done(runAndStore(*runner_, *db_, MemoryVolatility::PSLIST, parseProcesses));

    mark(MemoryVolatility::NETSTAT);
    done(runAndStore(*runner_, *db_, MemoryVolatility::NETSTAT, parseNetstat));

    mark(MemoryVolatility::SOCKSTAT);
    done(runAndStore(*runner_, *db_, MemoryVolatility::SOCKSTAT, parseSockstat));

    mark(MemoryVolatility::BASH);
    done(runAndStore(*runner_, *db_, MemoryVolatility::BASH, parseBashHistory));

    mark(MemoryVolatility::BOOTTIME);
    {   // boottime returns no rows-count; small inline handler
        auto res = runner_->run(MemoryVolatility::BOOTTIME);
        bool ok = res.ok;
        if (ok) { try { json a = json::parse(res.jsonText); parseBootTime(a, *db_); } catch (...) { ok = false; } }
        else db_->setMeta("err:linux.boottime", res.stderrText);
        done(ok);
    }

    // cmdline: store raw args (no dedicated parser needed beyond insertCmdline)
    mark(MemoryVolatility::CMDLINE);
    {
        auto res = runner_->run(MemoryVolatility::CMDLINE);
        bool ok = false;
        if (res.ok) {
            try {
                json a = json::parse(res.jsonText);
                if (a.is_array()) {
                    ok = true;
                    for (const auto& c : a) {
                        db_->insertCmdline(c.value("PID", 0),
                                           c.value("Process", std::string("")),
                                           c.value("Args", c.value("Command", std::string(""))));
                    }
                }
            } catch (...) {}
        } else db_->setMeta("err:linux.cmdline", res.stderrText);
        done(ok);
    }

    std::cout << "[Memory] Done -> " << outputDbPath_ << std::endl;
}
```

- [ ] **Step 4: Add the CLI flag**

In `src/CommandLineParser.h`, after line 33 (`bool linux_analyze = false;`), add:
```cpp
    bool memory_analyze = false;
```

In `src/CommandLineParser.cpp`, after the `--linux-analyze` block (lines 97-98), add:
```cpp
        } else if (arg == "--memory-analyze") {
            args.memory_analyze = true;
```
Also add a usage line in the help text near line 39 (look for the `--linux-analyze` usage entry and add a parallel one):
```
        --memory-analyze         Analyze a RAM memory image (LiME/raw) via Volatility3
```

- [ ] **Step 5: Add runMemoryAnalysis to the orchestrator**

In `src/AnalysisOrchestrator.h`, add to the public static section (next to `runAndroidLogicalAnalysis`):
```cpp
    static int runMemoryAnalysis(const CommandLineArgs& args);
```

In `src/AnalysisOrchestrator.cpp`:
1. At the top, with the other analyzer includes (near line 10 where `LinuxFilesAnalyzer.h` is included), add:
```cpp
#include "MemoryAnalyzer/MemoryAnalyzer.h"
```
2. Inside `runAnalysis`, near the top (right after the android-logical early guard at lines 46-47), add an early guard so memory analysis bypasses TSK:
```cpp
    if (args.memory_analyze) {
        return runMemoryAnalysis(args);
    }
```
3. Add the implementation (place it after `runAndroidLogicalAnalysis`, near line 276):
```cpp
int AnalysisOrchestrator::runMemoryAnalysis(const CommandLineArgs& args) {
    std::cout << "=== Memory Forensics Analyzer ===" << std::endl;
    std::cout << "Source: " << args.image_path << std::endl;
    std::cout << "Mode:   LiME/raw RAM image (no TSK / no _raw.db)" << std::endl;

    std::string baseName = getBaseName(args.image_path);
    std::string prefix = getDatabaseDir(args);
    if (!prefix.empty()) fs::create_directories(args.db_dir);

    std::string memDbPath = prefix + baseName + "_memory.db";

    try {
        auto analyzer = std::make_unique<MemoryAnalyzer>(args.image_path);
        analyzer->setOutputDatabasePath(memDbPath);
        std::cout << "[Memory] Initializing..." << std::endl;
        if (!analyzer->initialize()) {
            std::cerr << "Error: Failed to initialize memory analyzer" << std::endl;
            return 1;
        }
        analyzer->analyzeMemoryData();
        std::cout << "✓ Memory analysis complete" << std::endl;
        std::cout << "✓ Database: " << memDbPath << std::endl;
    } catch (const std::exception& e) {
        std::cerr << "Fatal error: " << e.what() << std::endl;
        return 1;
    }
    std::cout << "=== Analysis Complete ===" << std::endl;
    return 0;
}
```

- [ ] **Step 6: Build the full project (requires Task 8 CMake wiring — do that first if not done)**

If Task 8 is not yet done, defer this step and complete it there. Otherwise:
```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . -j$(nproc) 2>&1 | tail -15
```
Expected: clean build with no errors.

- [ ] **Step 7: Commit**

```bash
git add src/analyzers/MemoryAnalyzer/MemoryAnalyzer.h \
        src/analyzers/MemoryAnalyzer/Core/ \
        src/CommandLineParser.h src/CommandLineParser.cpp \
        src/AnalysisOrchestrator.h src/AnalysisOrchestrator.cpp
git commit -m "feat(memory): add MemoryAnalyzer class + --memory-analyze dispatch"
```

---

### Task 7: HTTP routes (MemoryForensicsRoutes)

Expose the `_memory.db` over HTTP, mirroring `AndroidForensicsRoutes`.

**Files:**
- Modify: `src/network/HTTPServer/routes/RouteHelpers.cpp` (add `"memory"` db_type branch)
- Create: `src/network/HTTPServer/routes/MemoryForensicsRoutes.h`
- Create: `src/network/HTTPServer/routes/MemoryForensicsRoutes.cpp`
- Modify: `src/network/HTTPServer/routes/ForensicsRoutes.h` (add member)
- Modify: `src/network/HTTPServer/routes/ForensicsRoutes.cpp` (construct member)

**Interfaces:**
- Consumes: `crow::App<>`, `RouteHelpers::get_database_path(task_id, db_type)` (the existing helper — see modification below).
- Produces: `class forensics::MemoryForensicsRoutes` with constructor `explicit MemoryForensicsRoutes(crow::App<>& app);` registering the five endpoints.

**Pre-requisite — extend `RouteHelpers::get_database_path`:** the existing helper (`RouteHelpers.cpp:29`) hard-codes db_type values (`raw`/`events`/`files`/`android`/`dll`) and throws on unknown types. Add a `"memory"` branch mirroring the `android`/`dll` pattern:

- [ ] **Step 1: Add the "memory" db_type to RouteHelpers**

In `src/network/HTTPServer/routes/RouteHelpers.cpp`, inside `get_database_path`, add a branch (next to the `dll` branch):
```cpp
    } else if (db_type == "memory") {
        if (task.metadata.find("memory_db") != task.metadata.end()) {
            return task.metadata.at("memory_db");
        }
        return task.output_raw_db.substr(0, task.output_raw_db.find_last_of('.')) + "_memory.db";
    }
```
This lets `RouteHelpers::get_database_path(task_id, "memory")` resolve to either an explicit `memory_db` metadata value or the default `<base>_memory.db`.

- [ ] **Step 2: Create MemoryForensicsRoutes.h**

Create `src/network/HTTPServer/routes/MemoryForensicsRoutes.h`:
```cpp
#pragma once
#include <crow.h>
#include <nlohmann/json.hpp>

namespace forensics {

class MemoryForensicsRoutes {
public:
    explicit MemoryForensicsRoutes(crow::App<>& app);
private:
    crow::response handle_memory_summary(const crow::request& req);
    crow::response handle_memory_processes(const crow::request& req);
    crow::response handle_memory_network(const crow::request& req);
    crow::response handle_memory_bash_history(const crow::request& req);
    crow::response handle_memory_boot_info(const crow::request& req);
};

} // namespace forensics
```

- [ ] **Step 3: Create MemoryForensicsRoutes.cpp**

The route handler resolves `task_id` to the `_memory.db` path via `RouteHelpers::get_database_path(task_id, "memory")` (the same helper `AndroidForensicsRoutes.cpp:51` uses with `"android"`).

Create `src/network/HTTPServer/routes/MemoryForensicsRoutes.cpp`:
```cpp
#include "MemoryForensicsRoutes.h"
#include "RouteHelpers.h"
#include "../SQLiteHelper.h"
#include "../../Swagger/Swagger.h"
#include <sqlite3.h>

namespace forensics {
using json = nlohmann::json;

MemoryForensicsRoutes::MemoryForensicsRoutes(crow::App<>& app) {
    CROW_ROUTE(app, "/api/forensics/memory/summary").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_summary(req); });
    CROW_ROUTE(app, "/api/forensics/memory/processes").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_processes(req); });
    CROW_ROUTE(app, "/api/forensics/memory/network").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_network(req); });
    CROW_ROUTE(app, "/api/forensics/memory/bash-history").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_bash_history(req); });
    CROW_ROUTE(app, "/api/forensics/memory/boot-info").methods("GET"_method)([this](const crow::request& req){
        return handle_memory_boot_info(req); });
}

static std::string resolveMemoryDb(const crow::request& req) {
    auto params = crow::query_string(req.url_params);
    std::string task_id = params.get("task_id") ? params.get("task_id") : "";
    return RouteHelpers::get_database_path(task_id, "memory");
}

static crow::response jsonRows(const std::string& dbPath, const std::string& sql) {
    crow::response res;
    RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");
    json out = json::array();
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        res.code = 404; res.write(R"({"error":"memory db not found"})"); return res;
    }
    sqlite3_stmt* stmt = nullptr;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr) != SQLITE_OK) {
        res.code = 500; res.write(R"({"error":"query failed"})"); sqlite3_close(db); return res;
    }
    int n = sqlite3_column_count(stmt);
    while (sqlite3_step(stmt) == SQLITE_ROW) {
        json row = json::object();
        for (int i = 0; i < n; ++i) {
            const char* name = sqlite3_column_name(stmt, i);
            const unsigned char* t = sqlite3_column_text(stmt, i);
            row[name] = t ? reinterpret_cast<const char*>(t) : "";
        }
        out.push_back(row);
    }
    sqlite3_finalize(stmt);
    sqlite3_close(db);
    res.write(out.dump());
    return res;
}

crow::response MemoryForensicsRoutes::handle_memory_summary(const crow::request& req) {
    crow::response res; RouteHelpers::add_cors_headers(res);
    res.set_header("Content-Type", "application/json");
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception& e) { res.code = 404; res.write(R"({"error":"task not found"})"); return res; }
    sqlite3* db = nullptr;
    if (sqlite3_open(dbPath.c_str(), &db) != SQLITE_OK) {
        res.code = 404; res.write(R"({"error":"memory db not found"})"); return res;
    }
    auto count = [&](const char* t) -> long {
        sqlite3_stmt* s = nullptr; long c = 0;
        std::string q = std::string("SELECT COUNT(*) FROM ") + t + ";";
        if (sqlite3_prepare_v2(db, q.c_str(), -1, &s, nullptr) == SQLITE_OK) {
            if (sqlite3_step(s) == SQLITE_ROW) c = sqlite3_column_int64(s, 0);
        }
        sqlite3_finalize(s); return c;
    };
    json out;
    out["processes"] = count("processes");
    out["network_connections"] = count("network_connections");
    out["bash_history"] = count("bash_history");
    out["sockets"] = count("sockets");
    sqlite3_close(db);
    res.write(out.dump());
    return res;
}

crow::response MemoryForensicsRoutes::handle_memory_processes(const crow::request& req) {
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { crow::response r; r.code=404; r.write(R"({"error":"task not found"})"); return r; }
    auto params = crow::query_string(req.url_params);
    std::string search = params.get("search") ? params.get("search") : "";
    std::string sql = "SELECT pid, ppid, comm, uid, state, thread_count FROM processes";
    if (!search.empty()) {
        sql += " WHERE comm LIKE '%" + search + "%'";
    }
    sql += " ORDER BY pid LIMIT 1000;";
    return jsonRows(dbPath, sql);
}

crow::response MemoryForensicsRoutes::handle_memory_network(const crow::request& req) {
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { crow::response r; r.code=404; r.write(R"({"error":"task not found"})"); return r; }
    return jsonRows(dbPath,
        "SELECT pid, comm, protocol, local_addr, local_port, foreign_addr, foreign_port, state "
        "FROM network_connections ORDER BY pid LIMIT 1000;");
}

crow::response MemoryForensicsRoutes::handle_memory_bash_history(const crow::request& req) {
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { crow::response r; r.code=404; r.write(R"({"error":"task not found"})"); return r; }
    auto params = crow::query_string(req.url_params);
    std::string kw = params.get("keyword") ? params.get("keyword") : "";
    std::string sql = "SELECT pid, comm, command, history_index FROM bash_history";
    if (!kw.empty()) sql += " WHERE command LIKE '%" + kw + "%'";
    sql += " ORDER BY history_index LIMIT 1000;";
    return jsonRows(dbPath, sql);
}

crow::response MemoryForensicsRoutes::handle_memory_boot_info(const crow::request& req) {
    std::string dbPath;
    try { dbPath = resolveMemoryDb(req); }
    catch (const std::exception&) { crow::response r; r.code=404; r.write(R"({"error":"task not found"})"); return r; }
    return jsonRows(dbPath, "SELECT key, value FROM boot_info;");
}

} // namespace forensics
```

**NOTE for implementer:** the exact name of the helper for task_id→db path must be verified by reading `AndroidForensicsRoutes.cpp` and `RouteHelpers.h`. The plan deliberately calls out this lookup rather than guessing the function name — if `RouteHelpers::resolveTaskDbPath(taskId, suffix)` does not exist, copy the exact inline logic that `AndroidForensicsRoutes` uses and substitute `"_memory.db"` for whatever suffix it uses (`"_android.db"` or `"_files.db"`).

- [ ] **Step 4: Register the routes in ForensicsRoutes**

In `src/network/HTTPServer/routes/ForensicsRoutes.h`, add the include near the top:
```cpp
#include "MemoryForensicsRoutes.h"
```
and add a member in the private section (near `android_forensics_routes_`, ~line 87):
```cpp
    MemoryForensicsRoutes memory_forensics_routes_;
```

In `src/network/HTTPServer/routes/ForensicsRoutes.cpp`, in the constructor initializer list (near line 44, after `scene_query_routes_(app)`):
```cpp
      memory_forensics_routes_(app),
```

- [ ] **Step 5: Build (requires Task 8 CMake; defer to that task if needed)**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . -j$(nproc) 2>&1 | tail -15
```
Expected: clean build.

- [ ] **Step 6: Commit**

```bash
git add src/network/HTTPServer/routes/RouteHelpers.cpp \
        src/network/HTTPServer/routes/MemoryForensicsRoutes.h \
        src/network/HTTPServer/routes/MemoryForensicsRoutes.cpp \
        src/network/HTTPServer/routes/ForensicsRoutes.h \
        src/network/HTTPServer/routes/ForensicsRoutes.cpp
git commit -m "feat(memory): add HTTP routes under /api/forensics/memory/*"
```

---

### Task 8: CMake wiring

Register all new sources/includes and the new test targets.

**Files:**
- Modify: `CMakeLists.txt` (include dirs ~169-183, route listing ~288, LIB_SOURCES ~391, test targets)

- [ ] **Step 1: Add include directories**

In `CMakeLists.txt`, in the `target_include_directories` block (around lines 169-183), add:
```cmake
    ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer
    ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer/Core
    ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer/Volatility
    ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer/Parsers
    ${CMAKE_SOURCE_DIR}/src/analyzers/MemoryAnalyzer/Database
```

- [ ] **Step 2: Add the route source**

In `CMakeLists.txt`, in the route listing (near line 288, after `AndroidForensicsRoutes.cpp`), add:
```cmake
    src/network/HTTPServer/routes/MemoryForensicsRoutes.cpp
```

- [ ] **Step 3: Add the analyzer sources**

In `CMakeLists.txt`, in `set(LIB_SOURCES ...)` (near line 391, where the Linux analyzer sources end), add:
```cmake
    src/analyzers/MemoryAnalyzer/Core/MemoryAnalyzerCore.cpp
    src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.cpp
    src/analyzers/MemoryAnalyzer/Parsers/ProcessParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/NetworkParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/BashHistoryParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/BootTimeParser.cpp
    src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp
```

- [ ] **Step 4: Add test targets**

Find the existing gtest target block in `CMakeLists.txt` (look for `test_android_analyzer_gtest` or `test_audit_log_gtest`) and add three parallel targets:
```cmake
add_executable(test_memory_database_gtest
    tests/UnitTest/test_memory_database_gtest.cpp
    src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp)
target_link_libraries(test_memory_database_gtest sqlite3 gtest gtest_main pthread)
target_include_directories(test_memory_database_gtest PRIVATE ${CMAKE_SOURCE_DIR}/src ${CMAKE_SOURCE_DIR}/src/core/DatabaseManager)
add_test(NAME test_memory_database_gtest COMMAND test_memory_database_gtest)

add_executable(test_memory_volatility_runner_gtest
    tests/UnitTest/test_memory_volatility_runner_gtest.cpp
    src/analyzers/MemoryAnalyzer/Volatility/Volatility3Runner.cpp)
target_link_libraries(test_memory_volatility_runner_gtest gtest gtest_main pthread)
target_include_directories(test_memory_volatility_runner_gtest PRIVATE ${CMAKE_SOURCE_DIR}/src)
add_test(NAME test_memory_volatility_runner_gtest COMMAND test_memory_volatility_runner_gtest)

add_executable(test_memory_parsers_gtest
    tests/UnitTest/test_memory_parsers_gtest.cpp
    src/analyzers/MemoryAnalyzer/Database/MemoryAnalysisDatabase.cpp
    src/analyzers/MemoryAnalyzer/Parsers/ProcessParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/NetworkParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/BashHistoryParser.cpp
    src/analyzers/MemoryAnalyzer/Parsers/BootTimeParser.cpp)
target_link_libraries(test_memory_parsers_gtest sqlite3 gtest gtest_main pthread)
target_include_directories(test_memory_parsers_gtest PRIVATE ${CMAKE_SOURCE_DIR}/src ${CMAKE_SOURCE_DIR}/src/core/DatabaseManager)
add_test(NAME test_memory_parsers_gtest COMMAND test_memory_parsers_gtest)
```

- [ ] **Step 5: Configure + build**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake .. 2>&1 | tail -5
cmake --build . -j$(nproc) 2>&1 | tail -20
```
Expected: `forensic_analyzer` plus the three test executables build cleanly.

- [ ] **Step 6: Run the unit tests**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
ctest -R memory --output-on-failure
```
Expected: 3 memory tests PASS.

- [ ] **Step 7: Commit**

```bash
git add CMakeLists.txt
git commit -m "build(memory): wire MemoryAnalyzer sources and tests into CMake"
```

---

### Task 9: End-to-end run against mem.lime

Verify the analyzer produces a `_memory.db` that can answer the five challenge questions.

**Files:** none (validation only)

- [ ] **Step 1: Run the analyzer on the LiME image**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
MEM="/home/ymj68520/projects/Forensics/TestImgs/decrypted_images/决赛服务器/内存镜像/mem.lime"
./build/forensic_analyzer "$MEM" --memory-analyze --db-dir /tmp/memout 2>&1 | tee /tmp/memrun.log
```
Expected: per-plugin `ok` lines and `✓ Database: /tmp/memout/mem_memory.db`.

If `linux.pslist` reports FAIL with "unable to identify" / symbol-table errors, vol3 needs an ISF symbol package. Install it:
```bash
mkdir -p ~/.config/volatility3/symbols
# Download the Linux ISF matching the server kernel (kernel version visible in: strings mem.lime | grep -m1 'Linux version')
# Place the .json.xz into ~/.config/volatility3/symbols/ and re-run.
```
Record the actual kernel version (`strings "$MEM" | grep -m1 'Linux version'`) so the symbol step is reproducible.

- [ ] **Step 2: Answer the five questions from the DB**

```bash
DB=/tmp/memout/mem_memory.db
# Q101: SSH session count (connections to/from port 22)
sqlite3 "$DB" "SELECT COUNT(*) FROM network_connections WHERE local_port=22 OR foreign_port=22;"
# Q102: dangerous deletion command + time context (bash command)
sqlite3 "$DB" "SELECT command FROM bash_history WHERE command LIKE 'rm%';"
# Q103: ZFS snapshot name
sqlite3 "$DB" "SELECT command FROM bash_history WHERE command LIKE '%zfs snapshot%';"
# Q104: ZFS unlock password
sqlite3 "$DB" "SELECT command FROM bash_history WHERE command LIKE '%zfs load-key%' OR command LIKE '%zfs mount%';"
# Q100: boot time (uptime computation requires the image acquisition time — see boot_info)
sqlite3 "$DB" "SELECT key, value FROM boot_info;"
```
Expected: non-empty results for each query. Record the answers.

- [ ] **Step 3: Smoke-test the HTTP endpoints**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject
./build/forensic_analyzer --http-server 8080 &
sleep 3
curl -s "http://localhost:8080/api/forensics/memory/summary?task_id=<TASK_ID>" | head -c 300
curl -s "http://localhost:8080/api/forensics/memory/bash-history?task_id=<TASK_ID>&keyword=rm" | head -c 300
kill %1
```
Expected: JSON responses with data. (Use a real task_id that maps to `/tmp/memout/mem_memory.db` per the project's task resolution.)

- [ ] **Step 4: No commit (validation task)**

If all five questions are answerable, the C++/backend phase is complete. Proceed to Task 10 (web page).

---

### Task 10: Web page (Memory.jsx)

Add a `/memory` page that consumes the five endpoints.

**Files:**
- Create: `web/src/pages/Memory.jsx`
- Modify: `web/src/routes.jsx`
- Modify: `web/src/components/Layout/Layout.jsx`
- Modify: `web/src/locales/en.js`
- Modify: `web/src/locales/zh.js`

**Interfaces:**
- Consumes: endpoints `GET /api/forensics/memory/{summary,processes,network,bash-history,boot-info}?task_id=`.

- [ ] **Step 1: Add i18n keys**

In `web/src/locales/en.js`, add to the `nav` block:
```js
    memory: 'Memory',
```
In `web/src/locales/zh.js`, add to the `nav` block:
```js
    memory: '内存取证',
```

- [ ] **Step 2: Add the route**

In `web/src/routes.jsx`, add the import near line 10 (next to the `Android` import):
```jsx
import Memory from './pages/Memory';
```
and add a route object in the `children` array (next to the `android` route, around line 54-57):
```jsx
      {
        path: 'memory',
        element: <Memory />,
      },
```

- [ ] **Step 3: Add the nav entry**

In `web/src/components/Layout/Layout.jsx`, import an icon (e.g. `Cpu` from `lucide-react`, next to the other icon imports), and add to the `navigation` array near line 31:
```jsx
    { name: t('nav.memory'), href: '/memory', icon: Cpu },
```
and append `'/memory'` to the `taskContextPages` array at line 47:
```jsx
    const taskContextPages = ['/timeline', '/files', '/case-report', '/knowledge-graph', '/android', '/wechat-graph', '/oss', '/search', '/statistics', '/memory'];
```

- [ ] **Step 4: Create Memory.jsx**

Create `web/src/pages/Memory.jsx` (model on `Android.jsx`'s task-id + fetch pattern):
```jsx
import React, { useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import axios from 'axios';

const API = process.env.REACT_APP_API_BASE || '';

export default function Memory() {
  const [params] = useSearchParams();
  const taskId = params.get('task_id') || '';
  const [summary, setSummary] = useState(null);
  const [processes, setProcesses] = useState([]);
  const [network, setNetwork] = useState([]);
  const [bash, setBash] = useState([]);
  const [boot, setBoot] = useState([]);
  const [kw, setKw] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!taskId) { setError('No task_id'); return; }
    const base = `${API}/api/forensics/memory`;
    axios.get(`${base}/summary?task_id=${taskId}`).then(r => setSummary(r.data)).catch(() => {});
    axios.get(`${base}/processes?task_id=${taskId}`).then(r => setProcesses(r.data)).catch(() => {});
    axios.get(`${base}/network?task_id=${taskId}`).then(r => setNetwork(r.data)).catch(() => {});
    axios.get(`${base}/bash-history?task_id=${taskId}`).then(r => setBash(r.data)).catch(() => {});
    axios.get(`${base}/boot-info?task_id=${taskId}`).then(r => setBoot(r.data)).catch(() => {});
  }, [taskId]);

  const searchBash = () => {
    if (!taskId) return;
    axios.get(`${API}/api/forensics/memory/bash-history?task_id=${taskId}&keyword=${encodeURIComponent(kw)}`)
         .then(r => setBash(r.data)).catch(() => {});
  };

  const highlight = (cmd) => {
    if (/rm\s+-rf|zfs\s+snapshot|zfs\s+load-key|zfs\s+mount/.test(cmd)) {
      return <span className="text-red-600 font-semibold">{cmd}</span>;
    }
    return cmd;
  };

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">Memory Forensics {taskId && `(task ${taskId})`}</h1>
      {error && <div className="text-red-600">{error}</div>}

      {summary && (
        <div className="grid grid-cols-4 gap-4">
          <Card label="Processes" value={summary.processes} />
          <Card label="Network Connections" value={summary.network_connections} />
          <Card label="Bash History" value={summary.bash_history} />
          <Card label="Sockets" value={summary.sockets} />
        </div>
      )}

      <Section title="Boot Info">
        <table className="w-full text-sm">
          <tbody>{boot.map((b, i) => <tr key={i}><td className="font-mono">{b.key}</td><td>{b.value}</td></tr>)}</tbody>
        </table>
      </Section>

      <Section title={`Processes (${processes.length})`}>
        <div className="overflow-auto max-h-80">
          <table className="w-full text-sm">
            <thead><tr>{['PID','PPID','Comm','UID','State','Threads'].map(h => <th key={h} className="text-left">{h}</th>)}</tr></thead>
            <tbody>{processes.map((p, i) => (
              <tr key={i}><td>{p.pid}</td><td>{p.ppid}</td><td className="font-mono">{p.comm}</td><td>{p.uid}</td><td>{p.state}</td><td>{p.thread_count}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Section>

      <Section title={`Network (${network.length})`}>
        <div className="overflow-auto max-h-80">
          <table className="w-full text-sm">
            <thead><tr>{['PID','Comm','Proto','Local','Foreign','State'].map(h => <th key={h} className="text-left">{h}</th>)}</tr></thead>
            <tbody>{network.map((n, i) => (
              <tr key={i}><td>{n.pid}</td><td className="font-mono">{n.comm}</td><td>{n.protocol}</td>
                <td>{n.local_addr}:{n.local_port}</td><td>{n.foreign_addr}:{n.foreign_port}</td><td>{n.state}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Section>

      <Section title={`Bash History (${bash.length})`}>
        <div className="flex gap-2 mb-2">
          <input value={kw} onChange={e => setKw(e.target.value)} placeholder="filter (e.g. rm, zfs)"
                 className="border px-2 py-1 rounded" />
          <button onClick={searchBash} className="px-3 py-1 bg-blue-600 text-white rounded">Search</button>
        </div>
        <div className="overflow-auto max-h-80">
          <table className="w-full text-sm">
            <thead><tr>{['#','PID','Command'].map(h => <th key={h} className="text-left">{h}</th>)}</tr></thead>
            <tbody>{bash.map((b, i) => (
              <tr key={i}><td>{b.history_index}</td><td>{b.pid}</td><td className="font-mono">{highlight(b.command)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      </Section>
    </div>
  );
}

const Card = ({label, value}) => (
  <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
    <div className="text-xs text-gray-500">{label}</div>
    <div className="text-2xl font-bold">{value}</div>
  </div>
);
const Section = ({title, children}) => (
  <div className="bg-white dark:bg-gray-800 rounded-lg shadow p-4">
    <h2 className="font-semibold mb-3">{title}</h2>
    {children}
  </div>
);
```

- [ ] **Step 5: Build the web UI**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/web
npm install   # only if package-lock changed
npm run build 2>&1 | tail -15
```
Expected: clean build.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Memory.jsx web/src/routes.jsx \
        web/src/components/Layout/Layout.jsx \
        web/src/locales/en.js web/src/locales/zh.js
git commit -m "feat(memory): add Memory forensics web page"
```

---

### Task 11: Docs + verification

Update project docs and run the full verification pass.

**Files:**
- Modify: `CLAUDE.md` (add MemoryAnalyzer to the analyzer list + CLI usage)
- Modify: `README.md` (add a memory forensics section)

- [ ] **Step 1: Update CLAUDE.md**

In `CLAUDE.md`, under "Specialized Analysis" (around line 142-158), add a parallel entry:
```
# Memory (RAM) forensic analysis (LiME/raw) via Volatility3
./forensic_analyzer mem.lime --memory-analyze
```
And under "Key Modules → C++ Core" (around line 235), add:
```
- **MemoryAnalyzer** (`analyzers/MemoryAnalyzer/`): Volatility3 subprocess wrapper, parses linux.pslist/bash/netstat/sockstat/boottime/cmdline into `_memory.db`
```
And in the Database Schema section (around line 295), add:
```
**_memory.db** - Memory artifacts (from Volatility3):
- processes, network_connections, sockets, bash_history, boot_info, cmdline, analysis_meta
```

- [ ] **Step 2: Update README.md**

Add a short "Memory Forensics" section after the existing analysis sections, describing `--memory-analyze`, the `_memory.db` tables, and the Volatility3 requirement.

- [ ] **Step 3: Full verification**

```bash
cd /home/ymj68520/projects/Forensics/ForensicsProject/build
cmake --build . -j$(nproc) && ctest -R memory --output-on-failure
cd /home/ymj68520/projects/Forensics/ForensicsProject
MEM="/home/ymj68520/projects/Forensics/TestImgs/decrypted_images/决赛服务器/内存镜像/mem.lime"
./build/forensic_analyzer "$MEM" --memory-analyze --db-dir /tmp/memout
```
Expected: build + 3 unit tests pass; end-to-end run produces `_memory.db`.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs(memory): document MemoryAnalyzer usage and schema"
```

---

## Self-Review Notes

- **Spec coverage**: every section of the spec maps to a task (SQL→T2, DB→T3, runner→T4, parsers→T5, analyzer+CLI+dispatch→T6, HTTP→T7, CMake→T8, validation→T9, web→T10, docs→T11). Vol3 dependency→T1.
- **Placeholder scan**: the only deliberately-deferred lookup was the task→DB-path helper in T7. **Resolved during self-review**: confirmed the real helper is `RouteHelpers::get_database_path(task_id, db_type)` (`RouteHelpers.cpp:29`), which hard-codes db types and throws on unknowns. T7 Step 1 now adds a `"memory"` branch mirroring the `android`/`dll` pattern, and the routes call `get_database_path(task_id, "memory")`. No `resolveTaskDbPath` placeholder remains.
- **Type consistency**: `MemoryAnalysisDatabase`, `Volatility3Runner`, `PluginResult`, parser function names (`parseProcesses`, `parseNetstat`, `parseSockstat`, `parseBashHistory`, `parseBootTime`) are consistent across T3/T4/T5/T6. The intentional `UPSERT_ANALYSIS_META` typo callout in T3 Step 4 is the one inconsistency the implementer must resolve.
- **Known follow-up risk**: the `linux.cmdline` vol3 field names (`Args` vs `Command`) vary; T6 handles both defensively.
- **Symbol-table dependency**: Volatility3 needs Linux ISF symbol files to parse a LiME dump. T9 Step 1 documents the symbol-install fallback (kernel version discoverable via `strings mem.lime | grep 'Linux version'`); if symbols are missing, `pslist` will FAIL with an "unable to identify" message rather than crash.
