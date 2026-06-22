#include <gtest/gtest.h>
#include "MemoryAnalyzer/Database/MemoryAnalysisDatabase.h"
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

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
