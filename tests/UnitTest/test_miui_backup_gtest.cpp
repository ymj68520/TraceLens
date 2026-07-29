// test_miui_backup_gtest.cpp
#include <gtest/gtest.h>
#include <fstream>
#include <filesystem>
#include "analyzers/AndroidAnalyzer/AndroidBackupHeader.h"

namespace fs = std::filesystem;

static fs::path writeTempBak(const std::string& name, const std::string& body) {
    fs::path p = fs::temp_directory_path() / name;
    std::ofstream(p, std::ios::binary) << body;
    return p;
}

TEST(AndroidBackupHeaderTest, ParsesMiuiPrefixedStream) {
    std::string body =
        "MIUI BACKUP\n2\ncom.android.deskclock 时钟\n-1\n0\n"
        "ANDROID BACKUP\n5\n0\nnone\n" + std::string(512, '\0'); // padding stands in for tar
    auto p = writeTempBak("hdr_ok.bak", body);
    AndroidBackupHeader h;
    ASSERT_TRUE(parseAndroidBackupHeader(p.string(), h));
    EXPECT_EQ(h.version, 5);
    EXPECT_EQ(h.compression, 0);
    EXPECT_EQ(h.encryption, BackupEncryption::None);
    EXPECT_EQ(h.encMarker, "none");
    // payload starts right after "none\n"
    EXPECT_GT(h.payloadOffset, 0u);
    EXPECT_EQ(body[h.payloadOffset], '\0'); // first payload byte
}

TEST(AndroidBackupHeaderTest, RejectsNonBackupFile) {
    auto p = writeTempBak("hdr_bad.bak", std::string("just some bytes that are not a backup"));
    AndroidBackupHeader h;
    EXPECT_FALSE(parseAndroidBackupHeader(p.string(), h));
}

TEST(AndroidBackupHeaderTest, DetectsAesMarker) {
    std::string body =
        "MIUI BACKUP\n2\ncom.example Ex\n-1\n0\n"
        "ANDROID BACKUP\n5\n1\nAES-256-encrypted\n" + std::string(512, '\0');
    auto p = writeTempBak("hdr_aes.bak", body);
    AndroidBackupHeader h;
    ASSERT_TRUE(parseAndroidBackupHeader(p.string(), h));
    EXPECT_EQ(h.compression, 1);
    EXPECT_EQ(h.encryption, BackupEncryption::Aes256);
    EXPECT_EQ(h.encMarker, "AES-256-encrypted");
}

TEST(AndroidBackupHeaderTest, RejectsNonNumericCompression) {
    // A non-numeric compression field is malformed input -> strict false
    // (do not silently treat as "no compression").
    std::string body =
        "MIUI BACKUP\n2\ncom.example Ex\n-1\n0\n"
        "ANDROID BACKUP\n5\nx\nnone\n" + std::string(512, '\0');
    auto p = writeTempBak("hdr_badcomp.bak", body);
    AndroidBackupHeader h;
    EXPECT_FALSE(parseAndroidBackupHeader(p.string(), h));
}

TEST(AndroidBackupHeaderTest, DetectsUnknownEncryptionMarker) {
    // An unrecognized encryption marker is detected (not decoded) as Unknown.
    std::string body =
        "MIUI BACKUP\n2\ncom.example Ex\n-1\n0\n"
        "ANDROID BACKUP\n5\n0\nweird-scheme\n" + std::string(512, '\0');
    auto p = writeTempBak("hdr_unknown_enc.bak", body);
    AndroidBackupHeader h;
    ASSERT_TRUE(parseAndroidBackupHeader(p.string(), h));
    EXPECT_EQ(h.encryption, BackupEncryption::Unknown);
    EXPECT_EQ(h.encMarker, "weird-scheme");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
