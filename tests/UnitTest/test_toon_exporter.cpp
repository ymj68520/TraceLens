#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include "TOONExporter.h"
#include <sqlite3.h>

using namespace forensics;
using ::testing::HasSubstr;
using ::testing::StartsWith;

/**
 * @brief Test empty records export
 */
TEST(TOONExporter, EmptyRecords) {
    std::vector<FileRecordWithLLM> records;
    TOONExporter exporter;
    TOONExportConfig config;
    
    std::string result = exporter.exportToTOON(records, config);
    
    // Should contain schema header and zero records count
    EXPECT_THAT(result, HasSubstr("TOON.schema:"));
    EXPECT_THAT(result, HasSubstr("# records[0]"));
}

/**
 * @brief Test single record export
 */
TEST(TOONExporter, SingleRecord) {
    std::vector<FileRecordWithLLM> records;
    FileRecordWithLLM record;
    record.name = "test.txt";
    record.path = "/home/user/test.txt";
    record.size = 1024;
    record.category = "Documents";
    record.llm_summary = "A simple test file";
    record.llm_description = "This is a test document containing sample text.";
    record.llm_keywords = "test,sample,document";
    records.push_back(record);
    
    TOONExporter exporter;
    TOONExportConfig config;
    
    std::string result = exporter.exportToTOON(records, config);
    
    // Should contain schema header
    EXPECT_THAT(result, HasSubstr("TOON.schema:"));
    // Should contain record count
    EXPECT_THAT(result, HasSubstr("# records[1]"));
    // Should contain file data
    EXPECT_THAT(result, HasSubstr("test.txt"));
    EXPECT_THAT(result, HasSubstr("/home/user/test.txt"));
    EXPECT_THAT(result, HasSubstr("A simple test file"));
}

/**
 * @brief Test multiple records export
 */
TEST(TOONExporter, MultipleRecords) {
    std::vector<FileRecordWithLLM> records;
    
    for (int i = 0; i < 3; i++) {
        FileRecordWithLLM record;
        record.name = "file" + std::to_string(i) + ".txt";
        record.path = "/path/to/file" + std::to_string(i) + ".txt";
        record.size = 100 * (i + 1);
        record.category = "Documents";
        record.llm_summary = "Summary " + std::to_string(i);
        records.push_back(record);
    }
    
    TOONExporter exporter;
    TOONExportConfig config;
    
    std::string result = exporter.exportToTOON(records, config);
    
    // Should have 3 records
    EXPECT_THAT(result, HasSubstr("# records[3]"));
    // Check all files present
    EXPECT_THAT(result, HasSubstr("file0.txt"));
    EXPECT_THAT(result, HasSubstr("file1.txt"));
    EXPECT_THAT(result, HasSubstr("file2.txt"));
}

/**
 * @brief Test escaping special characters
 */
TEST(TOONExporter, EscapeSpecialCharacters) {
    // Test quotes
    std::string escaped = TOONExporter::escapeValue("Hello \"World\"");
    EXPECT_THAT(escaped, HasSubstr("\"\""));  // Doubled quotes
    EXPECT_THAT(escaped, StartsWith("\""));   // Wrapped in quotes
    
    // Test pipes (delimiter)
    escaped = TOONExporter::escapeValue("value | with | pipes");
    EXPECT_THAT(escaped, StartsWith("\""));   // Should be quoted
    
    // Test newlines
    escaped = TOONExporter::escapeValue("line1\nline2");
    EXPECT_THAT(escaped, HasSubstr("\\n"));   // Escaped newline
    
    // Test simple value (no escaping needed)
    escaped = TOONExporter::escapeValue("simple value");
    EXPECT_EQ(escaped, "simple value");       // No quotes needed
    
    // Test empty value
    escaped = TOONExporter::escapeValue("");
    EXPECT_EQ(escaped, "\"\"");               // Empty quoted string
}

/**
 * @brief Test custom field selection
 */
TEST(TOONExporter, CustomFieldSelection) {
    std::vector<FileRecordWithLLM> records;
    FileRecordWithLLM record;
    record.name = "test.pdf";
    record.path = "/docs/test.pdf";
    record.size = 2048;
    record.category = "Documents";
    record.llm_summary = "PDF summary";
    record.llm_description = "PDF description";
    record.llm_keywords = "pdf,report";
    records.push_back(record);
    
    TOONExporter exporter;
    TOONExportConfig config;
    config.fields = {"name", "size", "llm_summary"};  // Only 3 fields
    
    std::string result = exporter.exportToTOON(records, config);
    
    // Schema should only have selected fields
    EXPECT_THAT(result, HasSubstr("TOON.schema: name | size | llm_summary"));
    // Should contain selected data
    EXPECT_THAT(result, HasSubstr("test.pdf"));
    EXPECT_THAT(result, HasSubstr("2048"));
    EXPECT_THAT(result, HasSubstr("PDF summary"));
    // Should NOT contain non-selected fields in schema
    EXPECT_THAT(result, Not(HasSubstr("llm_description")));
}

/**
 * @brief Test SQLite integration with in-memory database
 */
TEST(TOONExporter, SQLiteIntegration) {
    // Create in-memory database
    sqlite3* db = nullptr;
    int rc = sqlite3_open(":memory:", &db);
    ASSERT_EQ(rc, SQLITE_OK);
    
    // Create files table
    const char* create_sql = R"(
        CREATE TABLE files (
            id INTEGER PRIMARY KEY,
            inode INTEGER,
            name TEXT,
            path TEXT,
            size INTEGER,
            extension TEXT,
            category TEXT,
            type TEXT,
            mtime INTEGER,
            ctime INTEGER,
            is_deleted INTEGER,
            md5 TEXT,
            llm_summary TEXT,
            llm_description TEXT,
            llm_keywords TEXT,
            llm_analyzed_at INTEGER,
            llm_model_used TEXT
        );
    )";
    
    char* errmsg = nullptr;
    rc = sqlite3_exec(db, create_sql, nullptr, nullptr, &errmsg);
    ASSERT_EQ(rc, SQLITE_OK) << "Create table failed: " << (errmsg ? errmsg : "");
    
    // Insert test data
    const char* insert_sql = R"(
        INSERT INTO files (inode, name, path, size, extension, category, type,
                           mtime, ctime, is_deleted, md5, llm_summary, llm_description,
                           llm_keywords, llm_analyzed_at, llm_model_used)
        VALUES (1001, 'report.docx', '/home/user/docs/report.docx', 50000, 'docx',
                'Documents', 'REG', 1700000000, 1699000000, 0, 'abc123',
                'Annual financial report', 'Company annual report with financials',
                'finance,annual,report', 1700100000, 'gpt-4');
    )";
    
    rc = sqlite3_exec(db, insert_sql, nullptr, nullptr, &errmsg);
    ASSERT_EQ(rc, SQLITE_OK) << "Insert failed: " << (errmsg ? errmsg : "");
    
    // Export to TOON
    TOONExporter exporter;
    TOONExportConfig config;
    
    std::string result = exporter.exportToTOON(db, config);
    
    // Verify output
    EXPECT_THAT(result, HasSubstr("TOON.schema:"));
    EXPECT_THAT(result, HasSubstr("# records[1]"));
    EXPECT_THAT(result, HasSubstr("report.docx"));
    EXPECT_THAT(result, HasSubstr("Annual financial report"));
    EXPECT_THAT(result, HasSubstr("finance,annual,report"));
    
    sqlite3_close(db);
}

/**
 * @brief Test getAllFieldNames returns expected fields
 */
TEST(TOONExporter, GetAllFieldNames) {
    auto fields = TOONExporter::getAllFieldNames();
    
    EXPECT_TRUE(std::find(fields.begin(), fields.end(), "name") != fields.end());
    EXPECT_TRUE(std::find(fields.begin(), fields.end(), "path") != fields.end());
    EXPECT_TRUE(std::find(fields.begin(), fields.end(), "size") != fields.end());
    EXPECT_TRUE(std::find(fields.begin(), fields.end(), "llm_summary") != fields.end());
    EXPECT_TRUE(std::find(fields.begin(), fields.end(), "llm_description") != fields.end());
    EXPECT_TRUE(std::find(fields.begin(), fields.end(), "llm_keywords") != fields.end());
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
