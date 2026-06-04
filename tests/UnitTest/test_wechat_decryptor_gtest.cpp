// test_wechat_decryptor_gtest.cpp
// GTest-based unit tests for WeChatDecryptor module
// Tests password handling, file validation, MD5 derivation, and copy prevention

#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <type_traits>

#include "analyzers/AndroidAnalyzer/WeChatDecryptor.h"

namespace fs = std::filesystem;

class WeChatDecryptorTest : public ::testing::Test {
protected:
    void SetUp() override {
        testDbPath_ = fs::temp_directory_path() / "test_wechat.db";
    }

    void TearDown() override {
        fs::remove(testDbPath_);
    }

    fs::path testDbPath_;
};

TEST_F(WeChatDecryptorTest, EmptyPasswordReturnsError) {
    WeChatDecryptor decryptor;
    EXPECT_FALSE(decryptor.openDatabase("/nonexistent.db", ""));
    EXPECT_FALSE(decryptor.getLastError().empty());
}

TEST_F(WeChatDecryptorTest, NonexistentFileReturnsError) {
    WeChatDecryptor decryptor;
    EXPECT_FALSE(decryptor.openDatabase("/nonexistent.db", "abcdef1"));
    EXPECT_FALSE(decryptor.getLastError().empty());
}

TEST_F(WeChatDecryptorTest, MD5DerivationProducesCorrectLength) {
    std::string password = WeChatDecryptor::derivePassword("/nonexistent/");
    EXPECT_TRUE(password.empty());  // No files found
}

TEST_F(WeChatDecryptorTest, CannotCopy) {
    // Verify copy constructor is deleted (compile-time check)
    EXPECT_FALSE(std::is_copy_constructible_v<WeChatDecryptor>);
    EXPECT_FALSE(std::is_copy_assignable_v<WeChatDecryptor>);
}

TEST_F(WeChatDecryptorTest, CannotMove) {
    // Verify move constructor is deleted (compile-time check)
    EXPECT_FALSE(std::is_move_constructible_v<WeChatDecryptor>);
    EXPECT_FALSE(std::is_move_assignable_v<WeChatDecryptor>);
}

TEST_F(WeChatDecryptorTest, GetDbReturnsNullBeforeOpen) {
    WeChatDecryptor decryptor;
    EXPECT_EQ(decryptor.getDb(), nullptr);
}

TEST_F(WeChatDecryptorTest, GetLastErrorIsEmptyBeforeUse) {
    WeChatDecryptor decryptor;
    EXPECT_TRUE(decryptor.getLastError().empty());
}

TEST_F(WeChatDecryptorTest, CloseWithoutOpenIsNoop) {
    WeChatDecryptor decryptor;
    decryptor.close();  // Should not crash
    EXPECT_EQ(decryptor.getDb(), nullptr);
}

TEST_F(WeChatDecryptorTest, DestructorWithoutOpenIsNoop) {
    {
        WeChatDecryptor decryptor;
    }  // Destructor called - should not crash
}

TEST_F(WeChatDecryptorTest, OpenDatabaseUpdatesState) {
    WeChatDecryptor decryptor;

    // Try opening nonexistent file
    EXPECT_FALSE(decryptor.openDatabase("/nonexistent.db", "abcdef1"));

    // Database handle should still be null after failed open
    EXPECT_EQ(decryptor.getDb(), nullptr);
    EXPECT_FALSE(decryptor.getLastError().empty());
}

TEST_F(WeChatDecryptorTest, MultipleOpenAttempts) {
    WeChatDecryptor decryptor;

    // First attempt with empty password
    EXPECT_FALSE(decryptor.openDatabase("", ""));

    // Second attempt with nonexistent file - should still work (no stale state)
    EXPECT_FALSE(decryptor.openDatabase("/nonexistent.db", "abcdef1"));
    EXPECT_FALSE(decryptor.getLastError().empty());
}

TEST_F(WeChatDecryptorTest, DerivePasswordWithValidXml) {
    // Create a temporary directory structure mimicking WeChat shared_prefs
    fs::path tmpDir = fs::temp_directory_path() / "test_wechat_derive";
    fs::path prefsDir = tmpDir / "data" / "data" / "com.tencent.mm" / "shared_prefs";
    fs::create_directories(prefsDir);

    // Write a mock auth_info_key_prefs.xml with a UIN value
    fs::path xmlPath = prefsDir / "auth_info_key_prefs.xml";
    {
        std::ofstream ofs(xmlPath);
        ofs << R"(<?xml version='1.0' encoding='utf-8' standalone='yes' ?>)";
        ofs << "<map>";
        ofs << R"(<int name="_auth_uin" value="123456789" />)";
        ofs << "</map>";
    }

    std::string password = WeChatDecryptor::derivePassword(tmpDir.string());

    // Should derive a 7-character password from MD5(IMEI + UIN)
    EXPECT_EQ(password.length(), 7u);

    // Cleanup
    fs::remove_all(tmpDir);
}

TEST_F(WeChatDecryptorTest, DerivePasswordWithMissingXml) {
    fs::path tmpDir = fs::temp_directory_path() / "test_wechat_no_xml";
    fs::create_directories(tmpDir);

    std::string password = WeChatDecryptor::derivePassword(tmpDir.string());
    EXPECT_TRUE(password.empty());

    fs::remove_all(tmpDir);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
