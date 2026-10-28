#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <sqlite3.h>
#include <unistd.h>
#include "report/ReportGenerator.h"

TEST(ChineseReport, LocalizesTemplateAndCountsWithoutTranslatingEvidence) {
    const auto root = std::filesystem::temp_directory_path() /
        ("chinese_report_" + std::to_string(getpid()));
    std::filesystem::create_directories(root);
    const auto dbPath = root / "files.db";
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(dbPath.c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE mobile_artifacts(id INTEGER); INSERT INTO mobile_artifacts VALUES(1);"
        "CREATE TABLE sms_messages(id INTEGER); INSERT INTO sms_messages VALUES(1);"
        "CREATE TABLE events(timestamp INTEGER,event_type TEXT,file_path TEXT,description TEXT,severity TEXT);"
        "INSERT INTO events VALUES(1700000000,'sms','/Original Evidence.txt','Original message text','1');",
        nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(db);
    const auto reportPath = root / "report.md";
    forensics::ReportGenerator generator(dbPath.string(), dbPath.string());
    ASSERT_TRUE(generator.writeMarkdown("/Original Source.img", reportPath.string()));
    std::ifstream stream(reportPath);
    const std::string output((std::istreambuf_iterator<char>(stream)), {});
    EXPECT_NE(output.find("# 取证分析报告"), std::string::npos);
    EXPECT_NE(output.find("| 手机备份记录 | 1 |"), std::string::npos);
    EXPECT_NE(output.find("| 短信 | 1 |"), std::string::npos);
    EXPECT_NE(output.find("时间线（前 100 条事件）"), std::string::npos);
    EXPECT_NE(output.find("Original message text"), std::string::npos);
    EXPECT_NE(output.find("/Original Source.img"), std::string::npos);
    EXPECT_EQ(output.find("Forensic Analysis Report"), std::string::npos);
    std::filesystem::remove_all(root);
}
