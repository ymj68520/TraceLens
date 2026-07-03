#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include "MemoryAnalyzer/Database/MemoryAnalysisDatabase.h"
#include "MemoryAnalyzer/Parsers/ProcessParser.h"
#include "MemoryAnalyzer/Parsers/NetworkParser.h"
#include "MemoryAnalyzer/Parsers/BashHistoryParser.h"
#include "MemoryAnalyzer/Parsers/BootTimeParser.h"
#include <cstdio>
#include <unistd.h>

// These fixtures mirror the ACTUAL Volatility3 2.x JSON renderer output, whose
// row keys are the plugin TreeGrid column headers (e.g. "OFFSET (V)", "COMM",
// "Source Addr", "Boot Time"). Do not "simplify" them to made-up keys — the
// parsers are validated against real vol3 shapes on purpose.

namespace {
std::string tempDbPath() {
    char t[] = "/tmp/memparseXXXXXX"; int fd = mkstemp(t); close(fd); unlink(t); return t;
}
}

TEST(MemoryParsersTest, ParsesProcessList) {
    // Real linux.pslist columns: "OFFSET (V)", "PID", "PPID", "COMM", "UID", "GID".
    // Custom delimiter: the column name "OFFSET (V)" contains )" which would
    // otherwise terminate a plain R"(...)" literal early.
    auto j = nlohmann::json::parse(R"json([
      {"OFFSET (V)":18446612345,"PID":1,"TID":1,"PPID":0,"COMM":"systemd",
       "UID":0,"GID":0,"EUID":0,"EGID":0,"CREATION TIME":"2024-04-13T00:00:01+00:00",
       "File output":"Disabled"}
    ])json");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    EXPECT_EQ(parseProcesses(j, db), 1u);
    auto rows = db.query("SELECT comm, ppid FROM processes WHERE pid=1;");
    ASSERT_EQ(rows.size(), 1u);
    EXPECT_EQ(rows[0][0], "systemd");   // was silently empty before the fix
    EXPECT_EQ(rows[0][1], "0");
}

TEST(MemoryParsersTest, ParsesPsauxCmdline) {
    // Real linux.psaux columns: "PID", "PPID", "COMM", "ARGS".
    auto j = nlohmann::json::parse(R"([
      {"PID":100,"PPID":1,"COMM":"bash","ARGS":"-bash"}
    ])");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    EXPECT_EQ(parseCmdline(j, db), 1u);
    auto rows = db.query("SELECT comm, args FROM cmdline WHERE pid=100;");
    ASSERT_EQ(rows.size(), 1u);
    EXPECT_EQ(rows[0][0], "bash");
    EXPECT_EQ(rows[0][1], "-bash");
}

TEST(MemoryParsersTest, ParsesBashHistory) {
    // Real linux.bash columns: "PID", "Process", "CommandTime", "Command".
    auto j = nlohmann::json::parse(R"([
      {"PID":100,"Process":"bash","CommandTime":"2024-04-13T00:01:00+00:00","Command":"rm -rf /home/pgs/data"},
      {"PID":100,"Process":"bash","CommandTime":"2024-04-13T00:02:00+00:00","Command":"zfs snapshot pool/data@snap1"}
    ])");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    EXPECT_EQ(parseBashHistory(j, db), 2u);
    auto rows = db.query("SELECT command FROM bash_history WHERE command LIKE 'rm%';");
    EXPECT_EQ(rows.size(), 1u);
}

TEST(MemoryParsersTest, ParsesSockstatIntoSocketsAndConnections) {
    // Real linux.sockstat columns include "Process Name", "Sock Offset",
    // "Proto", "Source Addr", "Source Port" (str), "Destination Addr",
    // "Destination Port" (str), "State". Feeds both tables.
    auto j = nlohmann::json::parse(R"([
      {"NetNS":4026531840,"Process Name":"sshd","PID":42,"TID":42,"FD":3,
       "Sock Offset":4096,"Family":"AF_INET","Type":"SOCK_STREAM","Proto":"TCP",
       "Source Addr":"0.0.0.0","Source Port":"22","Destination Addr":"10.0.0.1",
       "Destination Port":"51000","State":"ESTABLISHED","Filter":""}
    ])");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    EXPECT_EQ(parseSockstat(j, db), 1u);
    EXPECT_EQ(parseNetstat(j, db), 1u);

    auto sock = db.query("SELECT comm, family, local_addr, remote_addr FROM sockets WHERE pid=42;");
    ASSERT_EQ(sock.size(), 1u);
    EXPECT_EQ(sock[0][0], "sshd");
    EXPECT_EQ(sock[0][2], "0.0.0.0");
    EXPECT_EQ(sock[0][3], "10.0.0.1");

    auto conn = db.query("SELECT protocol, local_port, foreign_port FROM network_connections WHERE pid=42;");
    ASSERT_EQ(conn.size(), 1u);
    EXPECT_EQ(conn[0][0], "TCP");
    EXPECT_EQ(conn[0][1], "22");       // port parsed from a JSON string
    EXPECT_EQ(conn[0][2], "51000");
}

TEST(MemoryParsersTest, ParsesBoottime) {
    // Real linux.boottime columns: "TIME NS", "Boot Time" (ISO-8601 string).
    auto j = nlohmann::json::parse(R"([{"TIME NS":1713000000000000000,"Boot Time":"2024-04-13T00:00:00+00:00"}])");
    MemoryAnalysisDatabase db(tempDbPath()); db.initialize();
    parseBootTime(j, db);
    auto rows = db.query("SELECT value FROM boot_info WHERE key='boot_time';");
    ASSERT_EQ(rows.size(), 1u);
    EXPECT_EQ(rows[0][0], "2024-04-13T00:00:00+00:00");
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
