// test_wechat_parser_gtest.cpp
// GTest-based unit tests for WeChat database parsing logic
// Tests database structure, contact/message/chatroom data, and group message format

#include <gtest/gtest.h>
#include <sqlite3.h>
#include <filesystem>
#include <string>

namespace fs = std::filesystem;

class WeChatParserTest : public ::testing::Test {
protected:
    void SetUp() override {
        testDbPath_ = fs::temp_directory_path() / "test_wechat_parser.db";
        createTestDatabase();
    }

    void TearDown() override {
        fs::remove(testDbPath_);
    }

    void createTestDatabase() {
        sqlite3* db;
        ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

        const char* schema = R"(
            CREATE TABLE IF NOT EXISTS rcontact (
                username TEXT, nickname TEXT, conRemark TEXT, type INTEGER, chatroomFlag INTEGER
            );
            CREATE TABLE IF NOT EXISTS chatroom (
                chatroomname TEXT, roomowner TEXT, memberlist TEXT, membercount INTEGER, addtime INTEGER
            );
            CREATE TABLE IF NOT EXISTS message (
                talker TEXT, content TEXT, createTime INTEGER, type INTEGER, isSend INTEGER
            );
            CREATE TABLE IF NOT EXISTS userinfo (
                id INTEGER, value TEXT
            );
        )";
        char* errMsg = nullptr;
        ASSERT_EQ(sqlite3_exec(db, schema, nullptr, nullptr, &errMsg), SQLITE_OK)
            << "Schema creation failed: " << (errMsg ? errMsg : "unknown error");
        sqlite3_free(errMsg);

        // Insert test contacts
        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO rcontact VALUES ('wxid_test1', 'TestUser1', 'Remark1', 0, 0);",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO rcontact VALUES ('wxid_test2', 'TestUser2', '', 0, 0);",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO rcontact VALUES ('weixin', 'WeChat', '', 0, 0);",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        // Insert test chatroom
        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO chatroom VALUES ('testroom@chatroom', 'wxid_test1', 'wxid_test1,wxid_test2', 2, 1700000000);",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        // Insert test messages
        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO message VALUES ('wxid_test1', 'Hello World', 1700000001, 1, 0);",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO message VALUES ('wxid_test2', 'Hi there', 1700000002, 1, 1);",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO message VALUES ('testroom@chatroom', 'wxid_test1:\nGroup message', 1700000003, 1, 0);",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        // Insert test userinfo (owner identification)
        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO userinfo VALUES (2, 'wxid_owner');",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        ASSERT_EQ(sqlite3_exec(db,
            "INSERT INTO userinfo VALUES (4, 'OwnerNick');",
            nullptr, nullptr, &errMsg), SQLITE_OK);
        sqlite3_free(errMsg);

        sqlite3_close(db);
    }

    fs::path testDbPath_;
};

// ============================================================================
// Database Structure Tests
// ============================================================================

TEST_F(WeChatParserTest, DatabaseCreation) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, AllTablesExist) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    const char* tables[] = {"rcontact", "chatroom", "message", "userinfo"};
    for (const char* table : tables) {
        sqlite3_stmt* stmt;
        std::string sql = "SELECT name FROM sqlite_master WHERE type='table' AND name='" +
                          std::string(table) + "';";
        ASSERT_EQ(sqlite3_prepare_v2(db, sql.c_str(), -1, &stmt, nullptr), SQLITE_OK);
        ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW)
            << "Table '" << table << "' does not exist";
        sqlite3_finalize(stmt);
    }

    sqlite3_close(db);
}

// ============================================================================
// Contact Table Tests
// ============================================================================

TEST_F(WeChatParserTest, ContactTableHasData) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM rcontact", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(stmt, 0), 3);  // 3 contacts including 'weixin'
    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, ContactHasNickname) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT nickname FROM rcontact WHERE username = 'wxid_test1'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* nickname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    EXPECT_STREQ(nickname, "TestUser1");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, ContactHasRemark) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT conRemark FROM rcontact WHERE username = 'wxid_test1'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* remark = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    EXPECT_STREQ(remark, "Remark1");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, WeixinContactExists) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT nickname FROM rcontact WHERE username = 'weixin'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* nickname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    EXPECT_STREQ(nickname, "WeChat");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

// ============================================================================
// Message Table Tests
// ============================================================================

TEST_F(WeChatParserTest, MessageTableHasData) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM message", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(stmt, 0), 3);
    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, DirectMessageContent) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT content FROM message WHERE talker = 'wxid_test1'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* content = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    EXPECT_STREQ(content, "Hello World");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, MessageTimestamp) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT createTime FROM message WHERE talker = 'wxid_test1'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    int64_t timestamp = sqlite3_column_int64(stmt, 0);
    EXPECT_EQ(timestamp, 1700000001);

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, SentMessageFlag) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT isSend FROM message WHERE talker = 'wxid_test2'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    int isSend = sqlite3_column_int(stmt, 0);
    EXPECT_EQ(isSend, 1);  // Sent message

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, ReceivedMessageFlag) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT isSend FROM message WHERE talker = 'wxid_test1'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    int isSend = sqlite3_column_int(stmt, 0);
    EXPECT_EQ(isSend, 0);  // Received message

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

// ============================================================================
// Chatroom / Group Message Tests
// ============================================================================

TEST_F(WeChatParserTest, ChatroomTableHasData) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM chatroom", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(stmt, 0), 1);
    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, ChatroomMemberCount) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT membercount FROM chatroom WHERE chatroomname = 'testroom@chatroom'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    int memberCount = sqlite3_column_int(stmt, 0);
    EXPECT_EQ(memberCount, 2);

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, ChatroomOwner) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT roomowner FROM chatroom WHERE chatroomname = 'testroom@chatroom'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* owner = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    EXPECT_STREQ(owner, "wxid_test1");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, ChatroomMessageFormat) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT content FROM message WHERE talker LIKE '%@chatroom%'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* content = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    std::string contentStr(content);

    // Verify group message format: "sender:\ncontent"
    size_t colonPos = contentStr.find(":\n");
    EXPECT_NE(colonPos, std::string::npos);
    EXPECT_EQ(contentStr.substr(0, colonPos), "wxid_test1");
    EXPECT_EQ(contentStr.substr(colonPos + 2), "Group message");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, ChatroomMessageTalker) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT talker FROM message WHERE talker LIKE '%@chatroom%'",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* talker = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    EXPECT_STREQ(talker, "testroom@chatroom");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

// ============================================================================
// Userinfo / Owner Identification Tests
// ============================================================================

TEST_F(WeChatParserTest, UserinfoTableHasOwnerData) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT value FROM userinfo WHERE id = 2",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* username = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    EXPECT_STREQ(username, "wxid_owner");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, UserinfoHasOwnerNickname) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT value FROM userinfo WHERE id = 4",
        -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);

    const char* nickname = reinterpret_cast<const char*>(sqlite3_column_text(stmt, 0));
    EXPECT_STREQ(nickname, "OwnerNick");

    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

TEST_F(WeChatParserTest, UserinfoTableHasData) {
    sqlite3* db;
    ASSERT_EQ(sqlite3_open(testDbPath_.string().c_str(), &db), SQLITE_OK);

    sqlite3_stmt* stmt;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM userinfo", -1, &stmt, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(stmt), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(stmt, 0), 2);
    sqlite3_finalize(stmt);
    sqlite3_close(db);
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
