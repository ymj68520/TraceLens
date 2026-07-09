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

    EXPECT_TRUE(db.insertProcess(/*offset*/0x1000, /*pid*/42, /*tid*/42, /*ppid*/1,
                                 /*comm*/"sshd", /*uid*/0, /*gid*/0,
                                 /*euid*/0, /*egid*/0, /*creation_time*/"2024-04-17T10:00:00Z"));
    EXPECT_TRUE(db.insertNetworkConnection(/*offset*/0x2000, /*pid*/42, /*tid*/42,
                                           /*comm*/"sshd", /*family*/"AF_INET", /*type*/"STREAM",
                                           /*proto*/"TCP", /*local_addr*/"0.0.0.0", /*local_port*/"22",
                                           /*remote_addr*/"10.0.0.1", /*remote_port*/"51000",
                                           /*state*/"ESTABLISHED", /*netns*/0));
    EXPECT_TRUE(db.insertBashHistory(/*pid*/100, /*comm*/"bash",
                                     /*command*/"rm -rf /home/pgs/data",
                                     /*command_time*/"2024-04-17T11:00:00Z", /*index*/5));
    EXPECT_TRUE(db.setBootInfo("boot_time", "1713000000"));
    EXPECT_TRUE(db.setMeta("vol_version", "2.7.0"));

    auto rows = db.query("SELECT pid, comm FROM processes WHERE pid=42;");
    ASSERT_EQ(rows.size(), 1u);
    EXPECT_EQ(rows[0][0], "42");
    EXPECT_EQ(rows[0][1], "sshd");

    auto net = db.query("SELECT remote_port FROM network_connections WHERE pid=42;");
    ASSERT_EQ(net.size(), 1u);
    EXPECT_EQ(net[0][0], "51000");

    unlink(path.c_str());
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
