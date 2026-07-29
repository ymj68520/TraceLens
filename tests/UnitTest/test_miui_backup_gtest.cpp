// test_miui_backup_gtest.cpp
#include <gtest/gtest.h>
#include <fstream>
#include <filesystem>
#include <cstdio>
#include <cstring>
#include "analyzers/AndroidAnalyzer/AndroidBackupHeader.h"
#include "analyzers/AndroidAnalyzer/TarIndex.h"

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

// Build a minimal POSIX (ustar) tar holding one regular file "apps/com.foo/db/x.db"
// with known contents, optionally zlib-deflated.
static fs::path makeUstarTar(const std::vector<std::pair<std::string,std::string>>& files) {
    std::string tar;
    for (auto& [name, content] : files) {
        std::string blk(512, '\0');
        std::memcpy(blk.data(), name.data(), std::min(name.size(), (size_t)100));
        std::string oct; char buf[16];
        auto toOct = [&](size_t v, int width){ std::snprintf(buf,sizeof(buf),"%0*lo",width-1,v);
            std::string s(buf); s.push_back('\0'); s.push_back(' '); return s; };
        std::memcpy(blk.data()+124, toOct(content.size(), 12).data(), 12); // size
        std::memcpy(blk.data()+136, toOct(0, 12).data(), 12);              // mtime
        blk[156] = '0';                                                     // typeflag regular
        std::memcpy(blk.data()+257, "ustar", 5);                            // ustar magic
        // checksum: blanks then sum
        std::memset(blk.data()+148, ' ', 8);
        unsigned sum = 0; for (unsigned char c : blk) sum += c;
        std::snprintf(buf, sizeof(buf), "%06o", sum);
        std::memcpy(blk.data()+148, buf, 6); blk[154] = '\0'; blk[155] = ' ';
        tar += blk;
        std::string data = content;
        data.append(((512 - data.size() % 512) % 512), '\0');
        tar += data;
    }
    tar.append(1024, '\0'); // two zero blocks
    fs::path p = fs::temp_directory_path() / "payload.tar";
    std::ofstream(p, std::ios::binary) << tar;
    return p;
}

TEST(TarIndexTest, IndexesRawTarOffsets) {
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "HELLO"}});
    TarIndex idx;
    ASSERT_TRUE(idx.build(tar.string(), 0, /*inflate=*/false));
    TarEntry e;
    ASSERT_TRUE(idx.find("apps/com.foo/db/x.db", e));
    EXPECT_EQ(e.size, 5u);
    fs::path out = fs::temp_directory_path() / "out_x.db";
    ASSERT_TRUE(idx.readEntry(e, out.string()));
    std::ifstream f(out, std::ios::binary);
    std::string got((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    EXPECT_EQ(got, "HELLO");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
