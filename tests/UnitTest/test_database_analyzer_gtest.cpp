/**
 * @file test_database_analyzer_gtest.cpp
 * @brief DatabaseAnalyzer模块单元测试
 */

#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>

#include "DatabaseAnalyzer/Common/DBDataTypes.h"
#include "DatabaseAnalyzer/Parsers/IDBParser.h"
#include "DatabaseAnalyzer/Parsers/DBParserFactory.h"
#include "DatabaseAnalyzer/Parsers/SQLiteAnalyzer.h"
#include "DatabaseAnalyzer/Database/DBAnalysisDatabase.h"

namespace fs = std::filesystem;
using namespace ForensicAnalyzer::Database;

class DatabaseAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {
        // 创建临时测试目录
        test_dir_ = fs::temp_directory_path() / "db_analyzer_test";
        fs::create_directories(test_dir_);
        
        result_db_path_ = (test_dir_ / "results.db").string();
        test_sqlite_path_ = (test_dir_ / "test.sqlite").string();
    }
    
    void TearDown() override {
        fs::remove_all(test_dir_);
    }
    
    // 创建测试SQLite数据库
    void createTestSQLiteDb() {
        sqlite3* db = nullptr;
        sqlite3_open(test_sqlite_path_.c_str(), &db);
        
        const char* sql = R"(
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT,
                created_at INTEGER
            );
            INSERT INTO users (name, email, created_at) VALUES 
                ('Alice', 'alice@example.com', 1700000000),
                ('Bob', 'bob@example.com', 1700000100),
                ('Charlie', 'charlie@example.com', 1700000200);
            
            CREATE TABLE logs (
                id INTEGER PRIMARY KEY,
                user_id INTEGER,
                action TEXT,
                timestamp INTEGER
            );
            INSERT INTO logs (user_id, action, timestamp) VALUES
                (1, 'login', 1700001000),
                (2, 'logout', 1700001100);
            
            CREATE INDEX idx_users_email ON users(email);
        )";
        
        sqlite3_exec(db, sql, nullptr, nullptr, nullptr);
        sqlite3_close(db);
    }
    
    fs::path test_dir_;
    std::string result_db_path_;
    std::string test_sqlite_path_;
};

// ========== 数据类型测试 ==========

TEST_F(DatabaseAnalyzerTest, DatabaseTypeEnumValues) {
    EXPECT_EQ(static_cast<int>(DatabaseType::UNKNOWN), 0);
    EXPECT_EQ(static_cast<int>(DatabaseType::SQLITE), 1);
    EXPECT_EQ(static_cast<int>(DatabaseType::MYSQL), 2);
    EXPECT_EQ(static_cast<int>(DatabaseType::POSTGRESQL), 3);
}

TEST_F(DatabaseAnalyzerTest, DatabaseTypeToString) {
    EXPECT_EQ(databaseTypeToString(DatabaseType::SQLITE), "SQLite");
    EXPECT_EQ(databaseTypeToString(DatabaseType::MYSQL), "MySQL");
    EXPECT_EQ(databaseTypeToString(DatabaseType::POSTGRESQL), "PostgreSQL");
    EXPECT_EQ(databaseTypeToString(DatabaseType::UNKNOWN), "Unknown");
}

TEST_F(DatabaseAnalyzerTest, ColumnDataTypeEnumValues) {
    EXPECT_EQ(static_cast<int>(ColumnDataType::UNKNOWN), 0);
    EXPECT_EQ(static_cast<int>(ColumnDataType::INTEGER), 1);
    EXPECT_EQ(static_cast<int>(ColumnDataType::TEXT), 3);
}

TEST_F(DatabaseAnalyzerTest, DBTableInfoDefaultValues) {
    DBTableInfo table;
    EXPECT_TRUE(table.name.empty());
    EXPECT_EQ(table.rowCount, 0);
    EXPECT_EQ(table.sizeBytes, 0);
    EXPECT_TRUE(table.columns.empty());
}

TEST_F(DatabaseAnalyzerTest, DBAnalysisOptionsDefaultValues) {
    DBAnalysisOptions options;
    EXPECT_TRUE(options.extractSchema);
    EXPECT_TRUE(options.extractRecords);
    EXPECT_TRUE(options.extractDeletedRecords);
    EXPECT_TRUE(options.extractArtifacts);
    EXPECT_EQ(options.maxRecordsPerTable, -1);
}

// ========== 工厂测试 ==========

TEST_F(DatabaseAnalyzerTest, FactoryGetRegisteredTypes) {
    auto types = DBParserFactory::getRegisteredTypes();
    EXPECT_GE(types.size(), 3u);  // 至少有 SQLite, MySQL, PostgreSQL
    
    bool hasSqlite = false;
    for (const auto& type : types) {
        if (type == DatabaseType::SQLITE) hasSqlite = true;
    }
    EXPECT_TRUE(hasSqlite);
}

TEST_F(DatabaseAnalyzerTest, FactoryIsTypeSupported) {
    EXPECT_TRUE(DBParserFactory::isTypeSupported(DatabaseType::SQLITE));
    EXPECT_TRUE(DBParserFactory::isTypeSupported(DatabaseType::MYSQL));
    EXPECT_TRUE(DBParserFactory::isTypeSupported(DatabaseType::POSTGRESQL));
    EXPECT_FALSE(DBParserFactory::isTypeSupported(DatabaseType::UNKNOWN));
}

TEST_F(DatabaseAnalyzerTest, FactoryDetectSQLiteFile) {
    createTestSQLiteDb();
    
    DatabaseType type = DBParserFactory::detectType(test_sqlite_path_);
    EXPECT_EQ(type, DatabaseType::SQLITE);
}

TEST_F(DatabaseAnalyzerTest, FactoryDetectUnknownFile) {
    // 创建一个非数据库文件
    std::string textFile = (test_dir_ / "test.txt").string();
    std::ofstream ofs(textFile);
    ofs << "This is not a database file";
    ofs.close();
    
    DatabaseType type = DBParserFactory::detectType(textFile);
    EXPECT_EQ(type, DatabaseType::UNKNOWN);
}

TEST_F(DatabaseAnalyzerTest, FactoryCreateSQLiteParser) {
    auto parser = DBParserFactory::createParser(DatabaseType::SQLITE);
    ASSERT_NE(parser, nullptr);
    EXPECT_EQ(parser->getType(), DatabaseType::SQLITE);
}

// ========== SQLite解析器测试 ==========

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerOpenClose) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    EXPECT_FALSE(analyzer.isOpen());
    
    EXPECT_TRUE(analyzer.open(test_sqlite_path_));
    EXPECT_TRUE(analyzer.isOpen());
    EXPECT_EQ(analyzer.getPath(), test_sqlite_path_);
    
    analyzer.close();
    EXPECT_FALSE(analyzer.isOpen());
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerOpenNonexistent) {
    SQLiteAnalyzer analyzer;
    EXPECT_FALSE(analyzer.open("/nonexistent/path/db.sqlite"));
    EXPECT_FALSE(analyzer.getLastError().empty());
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerGetTables) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    ASSERT_TRUE(analyzer.open(test_sqlite_path_));
    
    auto tables = analyzer.getTables();
    EXPECT_EQ(tables.size(), 2u);  // users, logs
    
    bool hasUsers = false, hasLogs = false;
    for (const auto& table : tables) {
        if (table.name == "users") hasUsers = true;
        if (table.name == "logs") hasLogs = true;
    }
    EXPECT_TRUE(hasUsers);
    EXPECT_TRUE(hasLogs);
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerGetTableInfo) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    ASSERT_TRUE(analyzer.open(test_sqlite_path_));
    
    auto usersTable = analyzer.getTableInfo("users");
    EXPECT_EQ(usersTable.name, "users");
    EXPECT_EQ(usersTable.columns.size(), 4u);  // id, name, email, created_at
    EXPECT_EQ(usersTable.rowCount, 3);
    
    // 检查列信息
    bool hasIdCol = false;
    for (const auto& col : usersTable.columns) {
        if (col.name == "id") {
            hasIdCol = true;
            EXPECT_TRUE(col.isPrimaryKey);
        }
    }
    EXPECT_TRUE(hasIdCol);
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerGetRecords) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    ASSERT_TRUE(analyzer.open(test_sqlite_path_));
    
    auto records = analyzer.getRecords("users");
    EXPECT_EQ(records.size(), 3u);
    
    // 检查第一条记录
    bool foundAlice = false;
    for (const auto& record : records) {
        auto it = record.values.find("name");
        if (it != record.values.end() && it->second == "Alice") {
            foundAlice = true;
            EXPECT_EQ(record.values.at("email"), "alice@example.com");
        }
    }
    EXPECT_TRUE(foundAlice);
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerGetRecordsWithLimit) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    ASSERT_TRUE(analyzer.open(test_sqlite_path_));
    
    auto records = analyzer.getRecords("users", 2);
    EXPECT_EQ(records.size(), 2u);
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerExecuteQuery) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    ASSERT_TRUE(analyzer.open(test_sqlite_path_));
    
    auto records = analyzer.executeQuery("SELECT name, email FROM users WHERE id = 1");
    EXPECT_EQ(records.size(), 1u);
    EXPECT_EQ(records[0].values.at("name"), "Alice");
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerGetVersion) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    ASSERT_TRUE(analyzer.open(test_sqlite_path_));
    
    std::string version = analyzer.getVersion();
    EXPECT_FALSE(version.empty());
    // SQLite版本通常类似 "3.x.x"
    EXPECT_EQ(version[0], '3');
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerGetPageSize) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    ASSERT_TRUE(analyzer.open(test_sqlite_path_));
    
    int pageSize = analyzer.getPageSize();
    // 常见页大小: 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536
    EXPECT_GT(pageSize, 0);
    EXPECT_EQ(pageSize % 512, 0);
}

TEST_F(DatabaseAnalyzerTest, SQLiteAnalyzerGetAnalysisSummary) {
    createTestSQLiteDb();
    
    SQLiteAnalyzer analyzer;
    ASSERT_TRUE(analyzer.open(test_sqlite_path_));
    
    auto summary = analyzer.getAnalysisSummary();
    EXPECT_EQ(summary.type, DatabaseType::SQLITE);
    EXPECT_EQ(summary.tableCount, 2);
    EXPECT_GT(summary.totalRecords, 0);
    EXPECT_GT(summary.fileSizeBytes, 0);
}

// ========== 结果数据库测试 ==========

TEST_F(DatabaseAnalyzerTest, DBAnalysisDatabaseInitialize) {
    DBAnalysisDatabase db(result_db_path_);
    EXPECT_TRUE(db.initialize());
    EXPECT_TRUE(fs::exists(result_db_path_));
}

TEST_F(DatabaseAnalyzerTest, DBAnalysisDatabaseSession) {
    DBAnalysisDatabase db(result_db_path_);
    ASSERT_TRUE(db.initialize());
    
    int64_t sessionId = db.beginSession("/path/to/test.db", DatabaseType::SQLITE);
    EXPECT_GT(sessionId, 0);
    
    DBAnalysisSummary summary;
    summary.version = "3.40.0";
    summary.fileSizeBytes = 12345;
    summary.tableCount = 5;
    
    EXPECT_TRUE(db.endSession(sessionId, summary));
    
    auto savedSummary = db.getSessionSummary(sessionId);
    EXPECT_EQ(savedSummary.version, "3.40.0");
    EXPECT_EQ(savedSummary.tableCount, 5);
}

TEST_F(DatabaseAnalyzerTest, DBAnalysisDatabaseInsertTable) {
    DBAnalysisDatabase db(result_db_path_);
    ASSERT_TRUE(db.initialize());
    
    int64_t sessionId = db.beginSession("/test.db", DatabaseType::SQLITE);
    
    DBTableInfo table;
    table.name = "users";
    table.rowCount = 100;
    table.sizeBytes = 4096;
    table.engine = "SQLite";
    
    DBColumnInfo col1;
    col1.name = "id";
    col1.dataType = "INTEGER";
    col1.isPrimaryKey = true;
    table.columns.push_back(col1);
    
    DBColumnInfo col2;
    col2.name = "name";
    col2.dataType = "TEXT";
    table.columns.push_back(col2);
    
    EXPECT_TRUE(db.insertTable(sessionId, table));
    
    auto tables = db.getTables(sessionId);
    EXPECT_EQ(tables.size(), 1u);
    EXPECT_EQ(tables[0].name, "users");
    EXPECT_EQ(tables[0].rowCount, 100);
}

TEST_F(DatabaseAnalyzerTest, DBAnalysisDatabaseInsertArtifact) {
    DBAnalysisDatabase db(result_db_path_);
    ASSERT_TRUE(db.initialize());
    
    int64_t sessionId = db.beginSession("/test.db", DatabaseType::SQLITE);
    
    DBArtifact artifact;
    artifact.type = ArtifactType::DELETED_RECORD;
    artifact.source = "users";
    artifact.description = "Recovered deleted user record";
    artifact.data["name"] = "DeletedUser";
    artifact.pageNumber = 42;
    
    EXPECT_TRUE(db.insertArtifact(sessionId, artifact));
    
    auto artifacts = db.getArtifacts(sessionId);
    EXPECT_EQ(artifacts.size(), 1u);
    EXPECT_EQ(artifacts[0].type, ArtifactType::DELETED_RECORD);
    EXPECT_EQ(artifacts[0].pageNumber, 42);
}

TEST_F(DatabaseAnalyzerTest, DBAnalysisDatabaseTransaction) {
    DBAnalysisDatabase db(result_db_path_);
    ASSERT_TRUE(db.initialize());
    
    int64_t sessionId = db.beginSession("/test.db", DatabaseType::SQLITE);
    
    db.beginTransaction();
    
    for (int i = 0; i < 10; i++) {
        DBTableInfo table;
        table.name = "table_" + std::to_string(i);
        table.rowCount = i * 10;
        db.insertTable(sessionId, table);
    }
    
    db.commit();
    
    auto tables = db.getTables(sessionId);
    EXPECT_EQ(tables.size(), 10u);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
