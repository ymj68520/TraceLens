// test_miui_backup_gtest.cpp
#include <gtest/gtest.h>
#include <fstream>
#include <filesystem>
#include <cstdio>
#include <cstring>
#include <unistd.h>
#include "analyzers/AndroidAnalyzer/AndroidBackupHeader.h"
#include "analyzers/AndroidAnalyzer/TarIndex.h"
#include "analyzers/AndroidAnalyzer/MiuiPathMap.h"
#include "analyzers/AndroidAnalyzer/MiuiBackupManifest.h"
#include "analyzers/AndroidAnalyzer/MiuiBackupExtractor.h"
#ifdef USE_ZLIB
#include <zlib.h>
#endif

namespace fs = std::filesystem;

static unsigned serial = 0;

static fs::path writeTempBak(const std::string& name, const std::string& body) {
    fs::path p = fs::temp_directory_path() / name;
    std::ofstream(p, std::ios::binary) << body;
    return p;
}

static std::string readFile(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(input)),
                       std::istreambuf_iterator<char>());
}

static std::string minimalBackupXml(const std::string& bakFile) {
    return "<MIUI-backup><packages><package><packageName>com.foo</packageName>"
           "<bakFile>" + bakFile + "</bakFile></package></packages></MIUI-backup>";
}

static std::string rawBackup(const std::string& tarBytes) {
    return "ANDROID BACKUP\n5\n0\nnone\n" + tarBytes;
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
    fs::path p = fs::temp_directory_path() /
                 ("payload_" + std::to_string(::getpid()) + "_" + std::to_string(serial++) + ".tar");
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

TEST(TarIndexTest, RejectsTruncatedTar) {
    fs::path tar = fs::temp_directory_path() /
                   ("truncated_" + std::to_string(::getpid()) + ".tar");
    std::ofstream(tar, std::ios::binary) << std::string(511, '\0');

    TarIndex idx;
    EXPECT_FALSE(idx.build(tar.string(), 0, /*inflate=*/false));
}

#ifdef USE_ZLIB
TEST(TarIndexTest, IndexesInflatedTar) {
    // Build a raw tar, then zlib-deflate it.
    auto tar = makeUstarTar({{"apps/com.bar/db/y.db", "WORLD"}});
    std::ifstream tin(tar, std::ios::binary);
    std::string raw((std::istreambuf_iterator<char>(tin)), std::istreambuf_iterator<char>());
    ASSERT_FALSE(raw.empty());

    uLong bound = compressBound(static_cast<uLong>(raw.size()));
    std::vector<Bytef> deflated(bound);
    uLongf deflatedLen = bound;
    int rc = compress(deflated.data(), &deflatedLen,
                      reinterpret_cast<const Bytef*>(raw.data()),
                      static_cast<uLong>(raw.size()));
    ASSERT_EQ(rc, Z_OK);

    // Write deflated payload to a temp .bak PREPENDED with header bytes so
    // payloadOffset > 0 (mirrors real ab/miui layout: header then payload).
    const std::string headerPad = "FAKE-HEADER-BYTES";
    fs::path p = fs::temp_directory_path() / "payload_inflated.bak";
    std::ofstream bout(p, std::ios::binary);
    bout.write(headerPad.data(), headerPad.size());
    bout.write(reinterpret_cast<const char*>(deflated.data()),
               static_cast<std::streamsize>(deflatedLen));
    bout.close();

    uint64_t payloadOffset = headerPad.size();
    TarIndex idx;
    ASSERT_TRUE(idx.build(p.string(), payloadOffset, /*inflate=*/true));

    TarEntry e;
    ASSERT_TRUE(idx.find("apps/com.bar/db/y.db", e));
    EXPECT_EQ(e.size, 5u);
    fs::path out = fs::temp_directory_path() / "out_y.db";
    ASSERT_TRUE(idx.readEntry(e, out.string()));
    std::ifstream f(out, std::ios::binary);
    std::string got((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
    EXPECT_EQ(got, "WORLD");
}
#endif

TEST(MiuiPathMapTest, MapsDatabasesFilesSharedPrefs) {
    EXPECT_EQ(analyzerPathToTarMember("data/data/com.foo/databases/x.db"), "apps/com.foo/db/x.db");
    EXPECT_EQ(analyzerPathToTarMember("data/data/com.foo/files/y"), "apps/com.foo/f/y");
    EXPECT_EQ(analyzerPathToTarMember("data/data/com.foo/shared_prefs/z.xml"), "apps/com.foo/sp/z.xml");
}
TEST(MiuiPathMapTest, ToleratesLeadingSlashAndBackslashes) {
    EXPECT_EQ(analyzerPathToTarMember("/data/data/com.foo/databases/x.db"), "apps/com.foo/db/x.db");
    EXPECT_EQ(analyzerPathToTarMember("data\\data\\com.foo\\databases\\x.db"), "apps/com.foo/db/x.db");
}
TEST(MiuiPathMapTest, ReturnsEmptyForUnmappable) {
    EXPECT_TRUE(analyzerPathToTarMember("system/build.prop").empty());
}
TEST(MiuiPathMapTest, InverseRoundTrip) {
    EXPECT_EQ(tarMemberToAnalyzerPath("apps/com.foo/db/x.db"), "data/data/com.foo/databases/x.db");
}

TEST(MiuiManifestTest, ParsesPackagesAndDevice) {
    fs::path dir = fs::temp_directory_path() / "miui_manifest_test";
    fs::create_directories(dir);
    std::string xml =
        "<?xml version='1.0' encoding='UTF-8' ?><MIUI-backup>"
        "<device>cepheus</device><miuiVersion>V12.5.6.0.RFACNXM</miuiVersion>"
        "<date>1785299538978</date><size>4122640883</size><packages>"
        "<package><packageName>com.android.mms</packageName>"
        "<bakFile>短信设置(com.android.mms).bak</bakFile><bakType>1</bakType>"
        "<pkgSize>7905280</pkgSize><sdSize>0</sdSize><state>1</state><error>0</error>"
        "</package></packages></MIUI-backup>";
    std::ofstream(dir / "descript.xml", std::ios::binary) << xml;
    BackupMeta m;
    ASSERT_TRUE(parseMiuiManifest(dir.string(), m));
    EXPECT_EQ(m.device, "cepheus");
    EXPECT_EQ(m.miuiVersion, "V12.5.6.0.RFACNXM");
    EXPECT_EQ(m.date, 1785299538978ull);
    ASSERT_EQ(m.packages.size(), 1u);
    EXPECT_EQ(m.packages[0].packageName, "com.android.mms");
    EXPECT_EQ(m.packages[0].bakFile, "短信设置(com.android.mms).bak");
    EXPECT_EQ(m.packages[0].bakType, 1);
    EXPECT_EQ(m.packages[0].pkgSize, 7905280ull);
    EXPECT_EQ(m.sourceFolder, dir.string());
}
TEST(MiuiManifestTest, MissingFileReturnsFalse) {
    BackupMeta m;
    EXPECT_FALSE(parseMiuiManifest(fs::temp_directory_path().string(), m));
}

TEST(MiuiBackupExtractorTest, ServesFileThroughAnalyzerPath) {
    fs::path dir = fs::temp_directory_path() /
                   ("miui_ext_test_" + std::to_string(::getpid()) + "_" + std::to_string(++serial));
    fs::create_directories(dir);

    std::string xml = "<?xml version='1.0'?><MIUI-backup><device>cepheus</device>"
        "<miuiVersion>V12</miuiVersion><date>1</date><size>1</size><packages>"
        "<package><packageName>com.foo</packageName>"
        "<bakFile>Foo(com.foo).bak</bakFile><bakType>1</bakType><pkgSize>1</pkgSize>"
        "<sdSize>0</sdSize><state>1</state><error>0</error></package></packages></MIUI-backup>";
    std::ofstream(dir / "descript.xml", std::ios::binary) << xml;

    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "DATA"}});
    std::ifstream tarIn(tar, std::ios::binary);
    std::string tarBytes((std::istreambuf_iterator<char>(tarIn)),
                         std::istreambuf_iterator<char>());
    std::string bak = "MIUI BACKUP\n2\ncom.foo Foo\n-1\n0\n"
                      "ANDROID BACKUP\n5\n0\nnone\n" + tarBytes;
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary) << bak;

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());

    fs::path out = dir / "output" / "served_x.db";
    ASSERT_TRUE(extractor.extractFileByPath("data/data/com.foo/databases/x.db", out.string()));
    EXPECT_TRUE(fs::exists(out));
    EXPECT_EQ(readFile(out), "DATA");

}

TEST(MiuiBackupExtractorTest, ExtractFailsWithoutCreatingOutputForMissingMember) {
    fs::path dir = fs::temp_directory_path() /
                   ("miui_ext_missing_test_" + std::to_string(::getpid()) + "_" + std::to_string(++serial));
    fs::create_directories(dir);

    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages><package><packageName>com.foo</packageName>"
           "<bakFile>Foo(com.foo).bak</bakFile></package></packages></MIUI-backup>";
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "DATA"}});
    std::ifstream tarIn(tar, std::ios::binary);
    std::string tarBytes((std::istreambuf_iterator<char>(tarIn)),
                         std::istreambuf_iterator<char>());
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary)
        << "ANDROID BACKUP\n5\n0\nnone\n" << tarBytes;

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());

    fs::path out = dir / "output" / "missing.db";
    EXPECT_FALSE(extractor.extractFileByPath("data/data/com.foo/databases/missing.db", out.string()));
    EXPECT_FALSE(fs::exists(out));

}

TEST(MiuiBackupExtractorTest, InitializeSkipsEncryptedBackupAndReturnsFalseWhenNoUsableApps) {
    fs::path dir = fs::temp_directory_path() /
                   ("miui_ext_encrypted_test_" + std::to_string(::getpid()) + "_" + std::to_string(++serial));
    fs::create_directories(dir);

    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages><package><packageName>com.foo</packageName>"
           "<bakFile>Foo(com.foo).bak</bakFile></package></packages></MIUI-backup>";
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary)
        << "ANDROID BACKUP\n5\n0\nAES-256-encrypted\nnot-an-encrypted-payload";

    MiuiBackupExtractor extractor(dir.string());
    EXPECT_FALSE(extractor.initialize());

}

TEST(MiuiBackupExtractorTest, CreatesOutputParentBeforeTarEntryWrite) {
    fs::path dir = fs::temp_directory_path() /
                   ("miui_ext_output_test_" + std::to_string(::getpid()) + "_" + std::to_string(++serial));
    fs::create_directories(dir);

    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages><package><packageName>com.foo</packageName>"
           "<bakFile>Foo(com.foo).bak</bakFile></package></packages></MIUI-backup>";
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "DATA"}});
    std::ifstream tarIn(tar, std::ios::binary);
    std::string tarBytes((std::istreambuf_iterator<char>(tarIn)),
                         std::istreambuf_iterator<char>());
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary)
        << "ANDROID BACKUP\n5\n0\nnone\n" << tarBytes;

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());

    fs::path out = dir / "nested" / "child" / "served_x.db";
    ASSERT_TRUE(extractor.extractFileByPath("data/data/com.foo/databases/x.db", out.string()));
    EXPECT_EQ(readFile(out), "DATA");

}

TEST(MiuiBackupExtractorTest, RejectsAbsoluteManifestBackupPath) {
    fs::path dir = fs::temp_directory_path() /
                   ("miui_ext_absolute_test_" + std::to_string(::getpid()) + "_" + std::to_string(++serial));
    fs::create_directories(dir);
    fs::path externalBak = fs::temp_directory_path() /
                           ("outside_miui_" + std::to_string(::getpid()) + "_" + std::to_string(++serial) + ".bak");
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "OUTSIDE"}});
    std::ofstream(externalBak, std::ios::binary) << rawBackup(readFile(tar));
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml(externalBak.string());

    MiuiBackupExtractor extractor(dir.string());
    EXPECT_FALSE(extractor.initialize());
}

TEST(MiuiBackupExtractorTest, RejectsTraversalManifestBackupPath) {
    fs::path parent = fs::temp_directory_path() /
                      ("miui_ext_traversal_parent_" + std::to_string(::getpid()) + "_" + std::to_string(++serial));
    fs::path dir = parent / "backup";
    fs::create_directories(dir);
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "OUTSIDE"}});
    std::ofstream(parent / "outside.bak", std::ios::binary) << rawBackup(readFile(tar));
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("../outside.bak");

    MiuiBackupExtractor extractor(dir.string());
    EXPECT_FALSE(extractor.initialize());
}

TEST(MiuiBackupExtractorTest, RejectsSymlinkedManifestBackupFile) {
    fs::path dir = fs::temp_directory_path() /
                   ("miui_ext_symlink_test_" + std::to_string(::getpid()) + "_" + std::to_string(++serial));
    fs::create_directories(dir);
    fs::path externalBak = fs::temp_directory_path() /
                           ("outside_symlink_miui_" + std::to_string(::getpid()) + "_" + std::to_string(++serial) + ".bak");
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "OUTSIDE"}});
    std::ofstream(externalBak, std::ios::binary) << rawBackup(readFile(tar));
    std::error_code ec;
    fs::create_symlink(externalBak, dir / "linked.bak", ec);
    if (ec) GTEST_SKIP() << "symlink creation unavailable: " << ec.message();
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("linked.bak");

    MiuiBackupExtractor extractor(dir.string());
    EXPECT_FALSE(extractor.initialize());
}

#ifdef USE_ZLIB
TEST(TarIndexTest, DeletesInflatedTemporaryFileOnDestruction) {
    auto tar = makeUstarTar({{"apps/com.bar/db/y.db", "WORLD"}});
    const std::string raw = readFile(tar);
    uLong bound = compressBound(static_cast<uLong>(raw.size()));
    std::vector<Bytef> deflated(bound);
    uLongf deflatedLen = bound;
    ASSERT_EQ(compress(deflated.data(), &deflatedLen,
                       reinterpret_cast<const Bytef*>(raw.data()),
                       static_cast<uLong>(raw.size())), Z_OK);

    fs::path bakDir = fs::temp_directory_path() /
                      ("miui_evidence_" + std::to_string(::getpid()) + "_" + std::to_string(++serial));
    fs::create_directories(bakDir);
    fs::path bak = bakDir / "inflated_lifecycle.bak";
    std::ofstream(bak, std::ios::binary).write(reinterpret_cast<const char*>(deflated.data()),
                                                static_cast<std::streamsize>(deflatedLen));
    std::string tempPath;
    {
        TarIndex idx;
        ASSERT_TRUE(idx.build(bak.string(), 0, /*inflate=*/true));
        tempPath = idx.dataFile();
        EXPECT_NE(fs::path(tempPath).parent_path(), bak.parent_path());
        EXPECT_TRUE(fs::exists(tempPath));
    }
    EXPECT_FALSE(fs::exists(tempPath));
}
#endif

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
