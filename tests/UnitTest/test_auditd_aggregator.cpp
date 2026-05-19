// test_auditd_aggregator.cpp
// Unit tests for AuditdAggregator

#ifdef linux
#undef linux
#endif

#include <gtest/gtest.h>
#include "Parsers/AuditdAggregator.h"

using namespace forensics::linux;

class AuditdAggregatorTest : public ::testing::Test {
protected:
    // Helper to create a SYSCALL line
    std::string makeSyscallLine(int64_t timestamp, int serial,
        int pid = 1234, int uid = 0, int auid = 1000, const std::string& exe = "/usr/bin/ls") {
        return "type=SYSCALL msg=audit(" + std::to_string(timestamp) + ".000:" +
               std::to_string(serial) + "): arch=c000003e syscall=59 success=yes exit=0 "
               "a0=7ffd1234 a1=7ffd5678 a2=7ffd9abc a3=0 items=2 "
               "ppid=1 pid=" + std::to_string(pid) + " auid=" + std::to_string(auid) +
               " uid=" + std::to_string(uid) + " gid=0 euid=0 egid=0 ses=1 "
               "comm=\"ls\" exe=\"" + exe + "\" key=(null)";
    }

    // Helper to create an EXECVE line
    std::string makeExecveLine(int64_t timestamp, int serial,
        int argc = 2, const std::string& a0 = "ls", const std::string& a1 = "-la") {
        return "type=EXECVE msg=audit(" + std::to_string(timestamp) + ".000:" +
               std::to_string(serial) + "): argc=" + std::to_string(argc) +
               " a0=\"" + a0 + "\" a1=\"" + a1 + "\"";
    }

    // Helper to create a CWD line
    std::string makeCwdLine(int64_t timestamp, int serial, const std::string& cwd = "/home/user") {
        return "type=CWD msg=audit(" + std::to_string(timestamp) + ".000:" +
               std::to_string(serial) + "): cwd=\"" + cwd + "\"";
    }

    // Helper to create a PATH line
    std::string makePathLine(int64_t timestamp, int serial,
        const std::string& name = "/usr/bin/ls", const std::string& nametype = "NORMAL") {
        return "type=PATH msg=audit(" + std::to_string(timestamp) + ".000:" +
               std::to_string(serial) + "): item=0 name=\"" + name +
               "\" inode=12345 dev=08:01 mode=0100755 ouid=0 ogid=0 "
               "nametype=" + nametype;
    }

    // Helper to create a PROCTITLE line
    std::string makeProctitleLine(int64_t timestamp, int serial) {
        // Hex-encoded "ls -la" = 6C73202D6C61
        return "type=PROCTITLE msg=audit(" + std::to_string(timestamp) + ".000:" +
               std::to_string(serial) + "): proctitle=6C73202D6C61";
    }

    // Helper to create a USER_AUTH line
    std::string makeUserAuthLine(int64_t timestamp, int serial,
        const std::string& user = "admin", const std::string& result = "success") {
        return "type=USER_AUTH msg=audit(" + std::to_string(timestamp) + ".000:" +
               std::to_string(serial) + "): pid=1234 uid=0 auid=0 ses=1 "
               "msg='op=PAM:authentication acct=\"" + user +
               "\" exe=\"/usr/sbin/sshd\" addr=192.168.1.1 terminal=ssh res=" + result + "'";
    }
};

// ============================================================================
// Single Line Parsing
// ============================================================================

TEST_F(AuditdAggregatorTest, ParseSyscallLine) {
    auto parsed = AuditdAggregator::parseLine(makeSyscallLine(1700000000, 1));

    EXPECT_EQ(parsed.type, "SYSCALL");
    EXPECT_EQ(parsed.timestamp, 1700000000LL);
    EXPECT_EQ(parsed.serialNumber, 1);
    EXPECT_FALSE(parsed.body.empty());
}

TEST_F(AuditdAggregatorTest, ParseExecveLine) {
    auto parsed = AuditdAggregator::parseLine(makeExecveLine(1700000000, 1));

    EXPECT_EQ(parsed.type, "EXECVE");
    EXPECT_EQ(parsed.timestamp, 1700000000LL);
    EXPECT_EQ(parsed.serialNumber, 1);
}

TEST_F(AuditdAggregatorTest, ParseCwdLine) {
    auto parsed = AuditdAggregator::parseLine(makeCwdLine(1700000000, 1));

    EXPECT_EQ(parsed.type, "CWD");
}

TEST_F(AuditdAggregatorTest, ParsePathLine) {
    auto parsed = AuditdAggregator::parseLine(makePathLine(1700000000, 1));

    EXPECT_EQ(parsed.type, "PATH");
}

TEST_F(AuditdAggregatorTest, ParseInvalidLine) {
    auto parsed = AuditdAggregator::parseLine("this is not an audit line");

    EXPECT_TRUE(parsed.type.empty());
    EXPECT_EQ(parsed.timestamp, 0);
}

TEST_F(AuditdAggregatorTest, ParseEmptyLine) {
    auto parsed = AuditdAggregator::parseLine("");

    EXPECT_TRUE(parsed.type.empty());
}

// ============================================================================
// Event Aggregation
// ============================================================================

TEST_F(AuditdAggregatorTest, AggregateCompleteEvent) {
    std::string content =
        makeSyscallLine(1700000000, 1) + "\n" +
        makeExecveLine(1700000000, 1) + "\n" +
        makeCwdLine(1700000000, 1) + "\n" +
        makePathLine(1700000000, 1) + "\n" +
        makeProctitleLine(1700000000, 1) + "\n";

    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    const auto& event = events[0];

    EXPECT_EQ(event.serialNumber, 1);
    EXPECT_EQ(event.timestamp, 1700000000LL);
    EXPECT_EQ(event.pid, 1234);
    EXPECT_EQ(event.uid, 0);
    EXPECT_EQ(event.auid, 1000);
    EXPECT_EQ(event.exe, "/usr/bin/ls");
    EXPECT_EQ(event.comm, "ls");
    EXPECT_EQ(event.success, 1);
    EXPECT_EQ(event.exitCode, 0);

    // EXECVE fields
    EXPECT_EQ(event.argc, 2);
    ASSERT_EQ(event.argv.size(), 2);
    EXPECT_EQ(event.argv[0], "ls");
    EXPECT_EQ(event.argv[1], "-la");

    // CWD
    EXPECT_EQ(event.cwd, "/home/user");

    // PATH
    ASSERT_EQ(event.paths.size(), 1);
    EXPECT_EQ(event.paths[0].name, "/usr/bin/ls");

    // Classification
    EXPECT_EQ(event.eventType, "process_execution");
}

TEST_F(AuditdAggregatorTest, AggregateMultipleEvents) {
    std::string content =
        makeSyscallLine(1700000000, 1) + "\n" +
        makeExecveLine(1700000000, 1) + "\n" +
        makeSyscallLine(1700000001, 2) + "\n" +
        makeExecveLine(1700000001, 2, 1, "cat", "/etc/passwd") + "\n";

    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 2);
    EXPECT_EQ(events[0].serialNumber, 1);
    EXPECT_EQ(events[1].serialNumber, 2);
}

TEST_F(AuditdAggregatorTest, AggregateSortedByTimestamp) {
    std::string content =
        makeSyscallLine(1700000002, 2) + "\n" +
        makeSyscallLine(1700000000, 1) + "\n" +
        makeSyscallLine(1700000001, 3) + "\n";

    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 3);
    EXPECT_EQ(events[0].serialNumber, 1);
    EXPECT_EQ(events[1].serialNumber, 3);
    EXPECT_EQ(events[2].serialNumber, 2);
}

TEST_F(AuditdAggregatorTest, AggregateEmptyContent) {
    auto events = AuditdAggregator::aggregate("");
    EXPECT_TRUE(events.empty());
}

// ============================================================================
// Field Extraction
// ============================================================================

TEST_F(AuditdAggregatorTest, ExtractSyscallFields) {
    std::string content = makeSyscallLine(1700000000, 1, 5678, 1000, 1000, "/usr/bin/cat");
    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].pid, 5678);
    EXPECT_EQ(events[0].uid, 1000);
    EXPECT_EQ(events[0].auid, 1000);
    EXPECT_EQ(events[0].exe, "/usr/bin/cat");
}

TEST_F(AuditdAggregatorTest, ExtractExecveMultipleArgs) {
    std::string content =
        "type=SYSCALL msg=audit(1700000000.000:1): arch=c000003e syscall=59 success=yes exit=0 "
        "a0=7ffd1234 a1=7ffd5678 a2=7ffd9abc a3=0 items=2 ppid=1 pid=1234 auid=0 uid=0 gid=0 "
        "euid=0 egid=0 ses=1 comm=\"curl\" exe=\"/usr/bin/curl\" key=(null)\n"
        "type=EXECVE msg=audit(1700000000.000:1): argc=4 a0=\"curl\" a1=\"-X\" a2=\"POST\" a3=\"http://example.com\"\n";

    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].argc, 4);
    ASSERT_EQ(events[0].argv.size(), 4);
    EXPECT_EQ(events[0].argv[0], "curl");
    EXPECT_EQ(events[0].argv[1], "-X");
    EXPECT_EQ(events[0].argv[2], "POST");
    EXPECT_EQ(events[0].argv[3], "http://example.com");
}

TEST_F(AuditdAggregatorTest, ExtractMultiplePaths) {
    std::string content =
        makeSyscallLine(1700000000, 1) + "\n" +
        makePathLine(1700000000, 1, "/usr/bin/ls", "NORMAL") + "\n" +
        makePathLine(1700000000, 1, "/lib64/ld-linux-x86-64.so.2", "NORMAL") + "\n";

    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].paths.size(), 2);
}

TEST_F(AuditdAggregatorTest, ExtractUserAuth) {
    std::string content = makeUserAuthLine(1700000000, 1, "admin", "success");
    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].authUser, "admin");
    EXPECT_EQ(events[0].result, "success");
    EXPECT_EQ(events[0].eventType, "authentication");
}

// ============================================================================
// Event Classification
// ============================================================================

TEST_F(AuditdAggregatorTest, ClassifyProcessExecution) {
    std::string content =
        makeSyscallLine(1700000000, 1) + "\n" +
        makeExecveLine(1700000000, 1) + "\n";

    auto events = AuditdAggregator::aggregate(content);
    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].eventType, "process_execution");
}

TEST_F(AuditdAggregatorTest, ClassifyAuthentication) {
    std::string content = makeUserAuthLine(1700000000, 1);
    auto events = AuditdAggregator::aggregate(content);
    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].eventType, "authentication");
}

TEST_F(AuditdAggregatorTest, ClassifyFileAccess) {
    std::string content =
        makeSyscallLine(1700000000, 1) + "\n" +
        makePathLine(1700000000, 1, "/etc/shadow") + "\n";

    auto events = AuditdAggregator::aggregate(content);
    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].eventType, "file_access");
}

TEST_F(AuditdAggregatorTest, ClassifyPrivilegeChange) {
    // UID changes from auid=1000 to uid=0 (privilege escalation)
    std::string content =
        "type=SYSCALL msg=audit(1700000000.000:1): arch=c000003e syscall=59 success=yes exit=0 "
        "a0=7ffd1234 a1=7ffd5678 a2=7ffd9abc a3=0 items=2 ppid=1 pid=1234 "
        "auid=1000 uid=0 gid=0 euid=0 egid=0 ses=1 comm=\"sudo\" exe=\"/usr/bin/sudo\" key=(null)\n";

    auto events = AuditdAggregator::aggregate(content);
    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].eventType, "privilege_change");
}

// ============================================================================
// Severity Assessment
// ============================================================================

TEST_F(AuditdAggregatorTest, SeverityFailedAuth) {
    std::string content = makeUserAuthLine(1700000000, 1, "admin", "fail");
    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_GE(events[0].severity, 2);
}

TEST_F(AuditdAggregatorTest, SeverityRootShell) {
    std::string content =
        "type=SYSCALL msg=audit(1700000000.000:1): arch=c000003e syscall=59 success=yes exit=0 "
        "a0=7ffd1234 a1=7ffd5678 a2=7ffd9abc a3=0 items=2 ppid=1 pid=1234 "
        "auid=0 uid=0 gid=0 euid=0 egid=0 ses=1 comm=\"bash\" exe=\"/usr/bin/bash\" key=(null)\n";

    auto events = AuditdAggregator::aggregate(content);
    ASSERT_EQ(events.size(), 1);
    EXPECT_GE(events[0].severity, 2); // Root shell
}

TEST_F(AuditdAggregatorTest, SeverityNormalEvent) {
    std::string content = makeSyscallLine(1700000000, 1, 1234, 1000, 1000);
    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_LE(events[0].severity, 1); // Normal user command
}

// ============================================================================
// Raw Lines Preservation
// ============================================================================

TEST_F(AuditdAggregatorTest, RawLinesPreserved) {
    std::string content =
        makeSyscallLine(1700000000, 1) + "\n" +
        makeExecveLine(1700000000, 1) + "\n" +
        makeCwdLine(1700000000, 1) + "\n";

    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].rawLines.size(), 3);
}

// ============================================================================
// Event ID
// ============================================================================

TEST_F(AuditdAggregatorTest, EventIdFormat) {
    std::string content = makeSyscallLine(1700000000, 42);
    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].eventId, "1700000000:42");
}

// ============================================================================
// Provenance
// ============================================================================

TEST_F(AuditdAggregatorTest, ProvenanceSet) {
    std::string content = makeSyscallLine(1700000000, 1);
    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].provenance.parserName, "AuditdAggregator");
    EXPECT_EQ(events[0].provenance.parserVersion, "1.0.0");
}

// ============================================================================
// Normalized Timestamp
// ============================================================================

TEST_F(AuditdAggregatorTest, NormalizedTimestamp) {
    std::string content = makeSyscallLine(1700000000, 1);
    auto events = AuditdAggregator::aggregate(content);

    ASSERT_EQ(events.size(), 1);
    EXPECT_EQ(events[0].normalizedTime.normalizedUtcTimestamp, 1700000000LL);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
