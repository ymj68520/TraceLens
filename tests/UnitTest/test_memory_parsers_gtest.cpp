#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include "MemoryAnalyzer/Database/MemoryAnalysisDatabase.h"
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
