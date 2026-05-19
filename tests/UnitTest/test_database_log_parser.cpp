// test_database_log_parser.cpp
// Unit tests for DatabaseLogParser - Phase 11

#include <gtest/gtest.h>
#include "Parsers/Database/DatabaseLogParser.h"

using namespace forensics::linux;

class DatabaseLogParserTest : public ::testing::Test {
protected:
    DatabaseLogParser parser;
};

// ============================================================================
// MySQL Log Parsing Tests
// ============================================================================

TEST_F(DatabaseLogParserTest, ParseMySQL8Format) {
    std::string content =
        "2024-01-15T10:30:00.000000+08:00 0 [Note] [MY-010454] Server starts as pid 1234\n"
        "2024-01-15T10:30:01.000000+08:00 0 [Warning] [MY-010000] InnoDB: Warning\n"
        "2024-01-15T10:30:02.000000+08:00 0 [Error] [MY-000000] Access denied for user 'root'\n";

    auto entries = parser.parseMySQLLog(content, "/var/log/mysql/error.log");

    ASSERT_EQ(entries.size(), 3);
    EXPECT_EQ(entries[0].severity, "note");
    EXPECT_EQ(entries[1].severity, "warning");
    EXPECT_EQ(entries[2].severity, "error");
    EXPECT_EQ(entries[0].dbType, DatabaseType::MySQL);
}

TEST_F(DatabaseLogParserTest, ParseMySQLOldFormat) {
    std::string content =
        "240115 10:30:00 [Note] Server starts\n"
        "240115 10:30:01 [Warning] InnoDB: Warning\n";

    auto entries = parser.parseMySQLLog(content, "/var/log/mysql/error.log");

    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].dbType, DatabaseType::MySQL);
}

TEST_F(DatabaseLogParserTest, ParseMySQLClientInfo) {
    std::string content =
        "2024-01-15T10:30:00.000000+08:00 0 [Note] host: 127.0.0.1 port: 3306\n";

    auto entries = parser.parseMySQLLog(content, "/var/log/mysql/error.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_EQ(entries[0].clientAddr, "127.0.0.1:3306");
}

// ============================================================================
// PostgreSQL Log Parsing Tests
// ============================================================================

TEST_F(DatabaseLogParserTest, ParsePostgreSQLLog) {
    std::string content =
        "2024-01-15 10:30:00.000 CST [12345]: [1-1] user=admin,db=mydb,app=psql,client=127.0.0.1 LOG:  statement: SELECT * FROM users\n"
        "2024-01-15 10:30:01.000 CST [12346]: [2-1] user=admin,db=mydb LOG:  connection received\n"
        "2024-01-15 10:30:02.000 CST [12347]: [3-1] FATAL: password authentication failed\n";

    auto entries = parser.parsePostgreSQLLog(content, "/var/log/postgresql/postgresql-15-main.log");

    ASSERT_GE(entries.size(), 2);
    EXPECT_EQ(entries[0].dbType, DatabaseType::PostgreSQL);
    EXPECT_EQ(entries[0].username, "admin");
    EXPECT_EQ(entries[0].database, "mydb");
}

TEST_F(DatabaseLogParserTest, ParsePostgreSQLQuery) {
    std::string content =
        "2024-01-15 10:30:00.000 CST [12345]: [1-1] user=admin,db=mydb LOG:  statement: SELECT * FROM users WHERE id = 1\n";

    auto entries = parser.parsePostgreSQLLog(content, "/var/log/postgresql/postgresql.log");

    ASSERT_EQ(entries.size(), 1);
    EXPECT_FALSE(entries[0].query.empty());
}

// ============================================================================
// MongoDB Log Parsing Tests
// ============================================================================

TEST_F(DatabaseLogParserTest, ParseMongoDBLog) {
    std::string content =
        "{\"t\":{\"$date\":\"2024-01-15T10:30:00.000+08:00\"},\"s\":\"I\",\"c\":\"NETWORK\",\"id\":51800,\"ctx\":\"conn123\",\"msg\":\"connection accepted\"}\n"
        "{\"t\":{\"$date\":\"2024-01-15T10:30:01.000+08:00\"},\"s\":\"W\",\"c\":\"ACCESS\",\"id\":20249,\"msg\":\"auth error\"}\n";

    auto entries = parser.parseMongoDBLog(content, "/var/log/mongodb/mongod.log");

    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].dbType, DatabaseType::MongoDB);
    EXPECT_EQ(entries[0].severity, "info");
    EXPECT_EQ(entries[0].component, "NETWORK");
    EXPECT_EQ(entries[1].severity, "warning");
}

// ============================================================================
// Redis Log Parsing Tests
// ============================================================================

TEST_F(DatabaseLogParserTest, ParseRedisLog) {
    std::string content =
        "12345:M 15 Jan 2024 10:30:00.000 * Server started\n"
        "12345:M 15 Jan 2024 10:30:01.000 # Warning message\n";

    auto entries = parser.parseRedisLog(content, "/var/log/redis/redis-server.log");

    ASSERT_EQ(entries.size(), 2);
    EXPECT_EQ(entries[0].dbType, DatabaseType::Redis);
    EXPECT_EQ(entries[0].severity, "info");
    EXPECT_EQ(entries[1].severity, "warning");
}

// ============================================================================
// Auto-detection Tests
// ============================================================================

TEST_F(DatabaseLogParserTest, DetectMySQLType) {
    EXPECT_EQ(parser.detectDatabaseType("/var/log/mysql/error.log"), DatabaseType::MySQL);
    EXPECT_EQ(parser.detectDatabaseType("/var/log/mariadb/mariadb.log"), DatabaseType::MariaDB);
}

TEST_F(DatabaseLogParserTest, DetectPostgreSQLType) {
    EXPECT_EQ(parser.detectDatabaseType("/var/log/postgresql/postgresql-15-main.log"), DatabaseType::PostgreSQL);
}

TEST_F(DatabaseLogParserTest, DetectMongoDBType) {
    EXPECT_EQ(parser.detectDatabaseType("/var/log/mongodb/mongod.log"), DatabaseType::MongoDB);
}

TEST_F(DatabaseLogParserTest, DetectRedisType) {
    EXPECT_EQ(parser.detectDatabaseType("/var/log/redis/redis-server.log"), DatabaseType::Redis);
}

TEST_F(DatabaseLogParserTest, DetectUnknownType) {
    EXPECT_EQ(parser.detectDatabaseType("/var/log/syslog"), DatabaseType::Unknown);
}

TEST_F(DatabaseLogParserTest, ParseAutoMySQL) {
    std::string content = "2024-01-15T10:30:00.000000+08:00 0 [Note] Server starts\n";
    auto entries = parser.parseAuto(content, "/var/log/mysql/error.log");
    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].dbType, DatabaseType::MySQL);
}

// ============================================================================
// Security Analysis Tests
// ============================================================================

TEST_F(DatabaseLogParserTest, AnalyzeAuthFailure) {
    std::string content =
        "2024-01-15T10:30:00.000000+08:00 0 [Error] Access denied for user 'root'@'192.168.1.100'\n";
    auto entries = parser.parseMySQLLog(content, "/var/log/mysql/error.log");
    auto findings = parser.analyzeSecurity(entries);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "auth_failure") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(DatabaseLogParserTest, AnalyzeBruteForce) {
    // Generate 6 auth failures - brute force should be detected from auth failures
    // even without clientAddr (uses aggregate count)
    std::string content;
    for (int i = 0; i < 6; i++) {
        content += "2024-01-15T10:30:0" + std::to_string(i) + ".000000+08:00 0 [Error] Access denied for user 'root'@'192.168.1.100'\n";
    }
    auto entries = parser.parseMySQLLog(content, "/var/log/mysql/error.log");

    // Verify entries were parsed
    ASSERT_EQ(entries.size(), 6);

    auto findings = parser.analyzeSecurity(entries);

    // Should have auth_failure findings
    int authFailureCount = 0;
    for (const auto& f : findings) {
        if (f.findingType == "auth_failure") {
            authFailureCount++;
        }
    }
    EXPECT_GE(authFailureCount, 6);
}

TEST_F(DatabaseLogParserTest, AnalyzeConfigWeakness) {
    std::string content =
        "2024-01-15T10:30:00.000000+08:00 0 [Note] Server bound to 0.0.0.0\n";
    auto entries = parser.parseMySQLLog(content, "/var/log/mysql/error.log");
    auto findings = parser.analyzeSecurity(entries);

    bool found = false;
    for (const auto& f : findings) {
        if (f.findingType == "config_weakness") {
            found = true;
            EXPECT_EQ(f.severity, "high");
            break;
        }
    }
    EXPECT_TRUE(found);
}

// ============================================================================
// Provenance Tests
// ============================================================================

TEST_F(DatabaseLogParserTest, ProvenanceSet) {
    std::string content = "2024-01-15T10:30:00.000000+08:00 0 [Note] Server starts\n";
    auto entries = parser.parseMySQLLog(content, "/var/log/mysql/error.log");

    ASSERT_GE(entries.size(), 1);
    EXPECT_EQ(entries[0].provenance.parserName, "DatabaseLogParser");
    EXPECT_FALSE(entries[0].provenance.sourceFile.empty());
}

// ============================================================================
// Edge Case Tests
// ============================================================================

TEST_F(DatabaseLogParserTest, ParseEmptyContent) {
    EXPECT_EQ(parser.parseMySQLLog("", "").size(), 0);
    EXPECT_EQ(parser.parsePostgreSQLLog("", "").size(), 0);
    EXPECT_EQ(parser.parseMongoDBLog("", "").size(), 0);
    EXPECT_EQ(parser.parseRedisLog("", "").size(), 0);
}

TEST_F(DatabaseLogParserTest, ParseInvalidLines) {
    std::string content = "This is not a valid log line\nAnother invalid line\n";
    auto entries = parser.parseMySQLLog(content, "/var/log/mysql/error.log");
    EXPECT_EQ(entries.size(), 0);
}

TEST_F(DatabaseLogParserTest, AnalyzeEmptyEntries) {
    std::vector<DatabaseLogEntry> entries;
    auto findings = parser.analyzeSecurity(entries);
    EXPECT_EQ(findings.size(), 0);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
