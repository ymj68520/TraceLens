// test_miui_backup_gtest.cpp
#include <gtest/gtest.h>
#include <fstream>
#include <filesystem>
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <future>
#include <memory>
#include <string>
#include <utility>
#ifndef _WIN32
#include <sys/stat.h>
#include <unistd.h>
#endif
#include "analyzers/AndroidAnalyzer/AndroidBackupHeader.h"
#include "analyzers/AndroidAnalyzer/TarIndex.h"
#include "analyzers/AndroidAnalyzer/MiuiPathMap.h"
#include "analyzers/AndroidAnalyzer/MiuiBackupManifest.h"
#include "analyzers/AndroidAnalyzer/MiuiBackupExtractor.h"
#include "analyzers/AndroidAnalyzer/MiuiArtifactParsers.h"
#include "analyzers/AndroidAnalyzer/MiuiSecureTemp.h"
#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include <sqlite3.h>
#ifdef USE_ZLIB
#include <zlib.h>
#endif

namespace fs = std::filesystem;

static std::atomic_uint64_t serial{0};

static fs::path uniqueTempPath(const std::string& stem, const std::string& extension = {}) {
    const auto timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    const auto suffix = std::to_string(timestamp) + "_" +
                        std::to_string(serial.fetch_add(1, std::memory_order_relaxed));
    return fs::temp_directory_path() / (stem + "_" + suffix + extension);
}

class TemporaryFile {
public:
    explicit TemporaryFile(fs::path path) : path_(std::move(path)) {}
    ~TemporaryFile() {
        std::error_code error;
        fs::remove(path_, error);
    }

private:
    fs::path path_;
};

static fs::path writeTempBak(const std::string& name, const std::string& body) {
    fs::path p = uniqueTempPath(name);
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

class InvalidCompressionField : public ::testing::TestWithParam<const char*> {};
TEST_P(InvalidCompressionField, RejectsAnythingExceptExactZeroOrOne) {
    const std::string body = "ANDROID BACKUP\n5\n" + std::string(GetParam()) +
                             "\nnone\n" + std::string(512, '\0');
    auto p = writeTempBak("hdr_strict_comp.bak", body);
    AndroidBackupHeader h;
    EXPECT_FALSE(parseAndroidBackupHeader(p.string(), h));
}
INSTANTIATE_TEST_SUITE_P(
    StrictGrammar, InvalidCompressionField,
    ::testing::Values("0junk", "1 ", " 1", "+1", "-0", "2",
                      "184467440737095516160000000000000000"));

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
    fs::path p = uniqueTempPath("payload", ".tar");
    std::ofstream(p, std::ios::binary) << tar;
    return p;
}

static fs::path makeUstarDirectory(const std::string& name) {
    std::string header(512, '\0');
    std::memcpy(header.data(), name.data(), std::min(name.size(), static_cast<size_t>(100)));
    std::memcpy(header.data() + 124, "00000000000\0", 12);
    std::memcpy(header.data() + 136, "00000000000\0", 12);
    header[156] = '5';
    std::memcpy(header.data() + 257, "ustar", 5);
    std::memset(header.data() + 148, ' ', 8);
    unsigned checksum = 0;
    for (unsigned char byte : header) checksum += byte;
    char checksumText[8]{};
    std::snprintf(checksumText, sizeof(checksumText), "%06o", checksum);
    std::memcpy(header.data() + 148, checksumText, 6);
    header[154] = '\0';
    header[155] = ' ';

    const fs::path path = uniqueTempPath("directory_payload", ".tar");
    std::ofstream(path, std::ios::binary) << header << std::string(1024, '\0');
    return path;
}

TEST(TarIndexTest, PreservesDirectoryTypeAndTimestamp) {
    const auto tar = makeUstarDirectory("apps/com.tencent.mobileqq/db/nt_db/");
    TarIndex index;
    ASSERT_TRUE(index.build(tar.string(), 0, false));

    TarEntry entry;
    ASSERT_TRUE(index.find("apps/com.tencent.mobileqq/db/nt_db/", entry));
    EXPECT_TRUE(entry.isDirectory());
    EXPECT_FALSE(entry.isRegularFile());
    EXPECT_EQ(entry.modifiedTime, 0u);
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
    fs::path tar = uniqueTempPath("truncated", ".tar");
    std::ofstream(tar, std::ios::binary) << std::string(511, '\0');

    TarIndex idx;
    EXPECT_FALSE(idx.build(tar.string(), 0, /*inflate=*/false));
}

TEST(TarIndexTest, RejectsMalformedOrOverflowingOctalSize) {
    for (const std::string& field : {std::string("0000000008\0 ", 12),
                                     std::string("777777777777", 12)}) {
        std::string block(512, '\0');
        std::memcpy(block.data(), "apps/com.foo/db/x.db", 20);
        std::memcpy(block.data() + 124, field.data(), 12);
        block[156] = '0';
        fs::path tar = uniqueTempPath("bad_octal", ".tar");
        std::ofstream(tar, std::ios::binary) << block << std::string(1024, '\0');
        TarIndex idx;
        EXPECT_FALSE(idx.build(tar.string(), 0, false));
    }
}

TEST(TarIndexTest, RequiresTwoCompleteZeroTerminatorBlocks) {
    auto valid = makeUstarTar({{"apps/com.foo/db/x.db", "DATA"}});
    std::string bytes = readFile(valid);
    ASSERT_GE(bytes.size(), 1024u);
    bytes[bytes.size() - 512] = 'X';
    fs::path tar = uniqueTempPath("bad_terminator", ".tar");
    std::ofstream(tar, std::ios::binary) << bytes;
    TarIndex idx;
    EXPECT_FALSE(idx.build(tar.string(), 0, false));
}

TEST(TarIndexTest, CombinesUstarPrefixAndName) {
    std::string block(512, '\0');
    const std::string prefix = "apps/com.example.very.long.package/db";
    const std::string name = "database-with-a-long-name.db";
    std::memcpy(block.data(), name.data(), name.size());
    std::memcpy(block.data() + 345, prefix.data(), prefix.size());
    std::memcpy(block.data() + 257, "ustar\0", 6);
    std::memcpy(block.data() + 263, "00", 2);
    const std::string sizeField("00000000004\0", 12);
    std::memcpy(block.data() + 124, sizeField.data(), 12);
    block[156] = '0';
    std::string tarBytes = block + std::string("DATA") + std::string(508, '\0') +
                           std::string(1024, '\0');
    fs::path tar = uniqueTempPath("ustar_prefix", ".tar");
    std::ofstream(tar, std::ios::binary) << tarBytes;
    TarIndex idx;
    ASSERT_TRUE(idx.build(tar.string(), 0, false));
    TarEntry entry;
    EXPECT_TRUE(idx.find(prefix + "/" + name, entry));
    EXPECT_EQ(entry.size, 4u);
}

TEST(TarIndexTest, RejectsNonUstarHeaderWithPrefixBytes) {
    std::string block(512, '\0');
    const std::string forgedPrefix = "apps/com.miui.forged/db";
    const std::string name = "identity.db";
    std::memcpy(block.data(), name.data(), name.size());
    std::memcpy(block.data() + 345, forgedPrefix.data(), forgedPrefix.size());
    const std::string sizeField("00000000004\0", 12);
    std::memcpy(block.data() + 124, sizeField.data(), 12);
    block[156] = '0';
    const fs::path tar = uniqueTempPath("v7_forged_prefix", ".tar");
    std::ofstream(tar, std::ios::binary)
        << block << "DATA" << std::string(508, '\0') << std::string(1024, '\0');

    TarIndex index;
    EXPECT_FALSE(index.build(tar.string(), 0, false));
    TarEntry entry;
    EXPECT_FALSE(index.find(forgedPrefix + "/" + name, entry));
}

#ifdef USE_ZLIB
TEST(TarIndexTest, RejectsInflationBeyondArchiveWideCapAndCleansPartialTemp) {
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", std::string(4096, 'A')}});
    const std::string raw = readFile(tar);
    uLong bound = compressBound(static_cast<uLong>(raw.size()));
    std::vector<Bytef> compressed(bound);
    uLongf compressedSize = bound;
    ASSERT_EQ(compress(compressed.data(), &compressedSize,
                       reinterpret_cast<const Bytef*>(raw.data()), raw.size()), Z_OK);
    const fs::path root = uniqueTempPath("miui_inflate_cap_root");
    fs::create_directories(root);
    const fs::path bak = uniqueTempPath("miui_inflate_cap", ".bak");
    std::ofstream(bak, std::ios::binary).write(
        reinterpret_cast<const char*>(compressed.data()), compressedSize);
    TarIndex index;
    EXPECT_FALSE(index.build(bak.string(), 0, true, root, 1024));
    EXPECT_TRUE(fs::is_empty(root));
}

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
TEST(MiuiPathMapTest, MapsNestedFlutterFiles) {
    EXPECT_EQ(analyzerPathToTarMember("data/data/com.socialchat.social_chat_app/app_flutter/files/password.json"),
              "apps/com.socialchat.social_chat_app/f/app_flutter/files/password.json");
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
TEST(MiuiPathMapTest, InverseMapsNestedFlutterFiles) {
    EXPECT_EQ(tarMemberToAnalyzerPath("apps/com.socialchat.social_chat_app/f/app_flutter/files/password.json"),
              "data/data/com.socialchat.social_chat_app/app_flutter/files/password.json");
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
TEST(MiuiManifestTest, RejectsOversizedManifestField) {
#ifndef _WIN32
    const fs::path dir = uniqueTempPath("miui_manifest_long_field");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages><package><packageName>"
        << std::string(9, 'p')
        << "</packageName><bakFile>Foo.bak</bakFile></package></packages></MIUI-backup>";
    ASSERT_EQ(::setenv("TRACELENS_MIUI_MAX_MANIFEST_FIELD_BYTES", "8", 1), 0);
    BackupMeta manifest;
    EXPECT_FALSE(parseMiuiManifest(dir.string(), manifest));
    ::unsetenv("TRACELENS_MIUI_MAX_MANIFEST_FIELD_BYTES");
#endif
}

TEST(MiuiManifestTest, RejectsManifestBeyondAggregateMetadataCap) {
#ifndef _WIN32
    const fs::path dir = uniqueTempPath("miui_manifest_metadata_cap");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages>"
           "<package><packageName>abcd</packageName><bakFile>efgh</bakFile></package>"
           "<package><packageName>ijkl</packageName><bakFile>mnop</bakFile></package>"
           "</packages></MIUI-backup>";
    ASSERT_EQ(::setenv("TRACELENS_MIUI_MAX_MANIFEST_METADATA_BYTES", "15", 1), 0);
    BackupMeta manifest;
    EXPECT_FALSE(parseMiuiManifest(dir.string(), manifest));
    ::unsetenv("TRACELENS_MIUI_MAX_MANIFEST_METADATA_BYTES");
#endif
}

TEST(MiuiManifestTest, RejectsManifestBeyondPackageCountCap) {
#ifndef _WIN32
    const fs::path dir = uniqueTempPath("miui_manifest_package_cap");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages>"
           "<package><packageName>one</packageName><bakFile>one.bak</bakFile></package>"
           "<package><packageName>two</packageName><bakFile>two.bak</bakFile></package>"
           "</packages></MIUI-backup>";
    ASSERT_EQ(::setenv("TRACELENS_MIUI_MAX_MANIFEST_PACKAGES", "1", 1), 0);
    BackupMeta manifest;
    EXPECT_FALSE(parseMiuiManifest(dir.string(), manifest));
    ::unsetenv("TRACELENS_MIUI_MAX_MANIFEST_PACKAGES");
#endif
}

TEST(MiuiManifestTest, MissingFileReturnsFalse) {
    BackupMeta m;
    EXPECT_FALSE(parseMiuiManifest(fs::temp_directory_path().string(), m));
}

TEST(MiuiManifestTest, DecodesXmlEntitiesInPackageFields) {
    fs::path dir = uniqueTempPath("miui_manifest_entities");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages><package>"
           "<packageName>com.foo&amp;bar</packageName>"
           "<bakFile>Foo &amp; Bar.bak</bakFile>"
           "</package></packages></MIUI-backup>";
    BackupMeta m;
    ASSERT_TRUE(parseMiuiManifest(dir.string(), m));
    ASSERT_EQ(m.packages.size(), 1u);
    EXPECT_EQ(m.packages[0].packageName, "com.foo&bar");
    EXPECT_EQ(m.packages[0].bakFile, "Foo & Bar.bak");
}

TEST(MiuiManifestTest, RejectsMalformedXmlAndWrongStructure) {
    for (const std::string& xml : {
             "<MIUI-backup><packages><package><packageName>com.foo</packageName></packages>",
             "<wrapper><MIUI-backup/></wrapper>",
             "<MIUI-backup><package><packageName>com.foo</packageName></package></MIUI-backup>"}) {
        fs::path dir = uniqueTempPath("miui_manifest_malformed");
        fs::create_directories(dir);
        std::ofstream(dir / "descript.xml", std::ios::binary) << xml;
        BackupMeta m;
        EXPECT_FALSE(parseMiuiManifest(dir.string(), m)) << xml;
    }
}

#ifndef _WIN32
TEST(MiuiManifestTest, RejectsSymlinkAndFifoWithoutBlocking) {
    const fs::path root = uniqueTempPath("miui_manifest_special");
    const fs::path external = uniqueTempPath("miui_manifest_external", ".xml");
    fs::create_directories(root);
    std::ofstream(external, std::ios::binary) << "<MIUI-backup><packages/></MIUI-backup>";
    std::error_code error;
    fs::create_symlink(external, root / "descript.xml", error);
    if (error) GTEST_SKIP() << "symlink creation unavailable: " << error.message();
    BackupMeta m;
    EXPECT_FALSE(parseMiuiManifest(root.string(), m));
    fs::remove(root / "descript.xml", error);

    ASSERT_EQ(::mkfifo((root / "descript.xml").c_str(), 0600), 0);
    auto parse = std::async(std::launch::async, [&] {
        BackupMeta fifoMeta;
        return parseMiuiManifest(root.string(), fifoMeta);
    });
    EXPECT_EQ(parse.wait_for(std::chrono::milliseconds(500)), std::future_status::ready);
    EXPECT_FALSE(parse.get());
}
#endif

TEST(MiuiBackupExtractorTest, ServesFileThroughAnalyzerPath) {
    fs::path dir = uniqueTempPath("miui_ext_test");
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
    fs::path dir = uniqueTempPath("miui_ext_missing_test");
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

TEST(MiuiBackupExtractorTest, EncryptedOnlyManifestInitializesAndRetainsFailure) {
    fs::path dir = uniqueTempPath("miui_ext_encrypted_test");
    fs::create_directories(dir);

    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages><package><packageName>com.foo</packageName>"
           "<bakFile>Foo(com.foo).bak</bakFile></package></packages></MIUI-backup>";
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary)
        << "ANDROID BACKUP\n5\n0\nAES-256-encrypted\nnot-an-encrypted-payload";

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    ASSERT_EQ(extractor.packageFailures().size(), 1u);
    EXPECT_EQ(extractor.packageFailures()[0].packageName, "com.foo");
    EXPECT_EQ(extractor.packageFailures()[0].bakFile, "Foo(com.foo).bak");
    EXPECT_EQ(extractor.packageFailures()[0].openStatus, "encrypted_locked");
}

TEST(MiuiArtifactTest, PersistsUniqueLockedBackupAsInstalledAppAndFailure) {
    const fs::path dir = uniqueTempPath("miui_locked_persistence");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << minimalBackupXml("locked.bak");
    std::ofstream(dir / "locked.bak", std::ios::binary)
        << "ANDROID BACKUP\n5\n0\nAES-256-encrypted\nciphertext";

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_locked_persistence", ".db");
    TemporaryFile cleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    ASSERT_TRUE(persistMiuiBackupAnalysis(extractor, db));

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT package_name FROM installed_apps", -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "com.foo");
    EXPECT_EQ(sqlite3_step(statement), SQLITE_DONE);
    sqlite3_finalize(statement);

    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT db_path, open_status FROM app_db_inventory WHERE package_name = 'com.foo'", -1,
        &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "locked.bak");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1)), "encrypted_locked");
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(MiuiBackupExtractorTest, MissingManifestBackupFileRetainsParseFailure) {
    fs::path dir = uniqueTempPath("miui_ext_missing_bak_test");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << minimalBackupXml("missing.bak");

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    ASSERT_EQ(extractor.packageFailures().size(), 1u);
    EXPECT_EQ(extractor.packageFailures()[0].bakFile, "missing.bak");
    EXPECT_EQ(extractor.packageFailures()[0].openStatus, "parse_error");
}

TEST(MiuiBackupExtractorTest, CreatesOutputParentBeforeTarEntryWrite) {
    fs::path dir = uniqueTempPath("miui_ext_output_test");
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
    fs::path dir = uniqueTempPath("miui_ext_absolute_test");
    fs::create_directories(dir);
    fs::path externalBak = uniqueTempPath("outside_miui", ".bak");
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "OUTSIDE"}});
    std::ofstream(externalBak, std::ios::binary) << rawBackup(readFile(tar));
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml(externalBak.string());

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    ASSERT_EQ(extractor.packageFailures().size(), 1u);
    EXPECT_EQ(extractor.packageFailures()[0].bakFile, externalBak.string());
    EXPECT_EQ(extractor.packageFailures()[0].openStatus, "parse_error");
}

TEST(MiuiBackupExtractorTest, RejectsTraversalManifestBackupPath) {
    fs::path parent = uniqueTempPath("miui_ext_traversal_parent");
    fs::path dir = parent / "backup";
    fs::create_directories(dir);
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "OUTSIDE"}});
    std::ofstream(parent / "outside.bak", std::ios::binary) << rawBackup(readFile(tar));
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("../outside.bak");

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    ASSERT_EQ(extractor.packageFailures().size(), 1u);
    EXPECT_EQ(extractor.packageFailures()[0].bakFile, "../outside.bak");
    EXPECT_EQ(extractor.packageFailures()[0].openStatus, "parse_error");
}

TEST(MiuiBackupExtractorTest, RejectsSymlinkedManifestBackupFile) {
    fs::path dir = uniqueTempPath("miui_ext_symlink_test");
    fs::create_directories(dir);
    fs::path externalBak = uniqueTempPath("outside_symlink_miui", ".bak");
    auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "OUTSIDE"}});
    std::ofstream(externalBak, std::ios::binary) << rawBackup(readFile(tar));
    std::error_code ec;
    fs::create_symlink(externalBak, dir / "linked.bak", ec);
    if (ec) GTEST_SKIP() << "symlink creation unavailable: " << ec.message();
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("linked.bak");

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    ASSERT_EQ(extractor.packageFailures().size(), 1u);
    EXPECT_EQ(extractor.packageFailures()[0].bakFile, "linked.bak");
    EXPECT_EQ(extractor.packageFailures()[0].openStatus, "parse_error");
}

TEST(MiuiBackupExtractorTest, RejectsDuplicateManifestBackupFile) {
    const fs::path dir = uniqueTempPath("miui_duplicate_bak");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages>"
           "<package><packageName>com.first</packageName><bakFile>shared.bak</bakFile></package>"
           "<package><packageName>com.second</packageName><bakFile>shared.bak</bakFile></package>"
           "</packages></MIUI-backup>";
    const auto tar = makeUstarTar({{"apps/com.first/db/x.db", "DATA"}});
    std::ofstream(dir / "shared.bak", std::ios::binary) << rawBackup(readFile(tar));

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    ASSERT_EQ(extractor.packageFailures().size(), 1u);
    EXPECT_EQ(extractor.packageFailures()[0].packageName, "com.second");
    EXPECT_EQ(extractor.packageFailures()[0].openStatus, "parse_error");
}

TEST(MiuiArtifactTest, PersistsDuplicateBackupOnlyAsFailureWithoutMisattribution) {
    const fs::path dir = uniqueTempPath("miui_duplicate_persistence");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages>"
           "<package><packageName>com.first</packageName><bakFile>shared.bak</bakFile></package>"
           "<package><packageName>com.second</packageName><bakFile>shared.bak</bakFile></package>"
           "</packages></MIUI-backup>";
    const auto tar = makeUstarTar({{"apps/com.first/db/x.db", "not-a-sqlite-db"}});
    std::ofstream(dir / "shared.bak", std::ios::binary) << rawBackup(readFile(tar));

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_duplicate_persistence", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    ASSERT_TRUE(persistMiuiBackupAnalysis(extractor, db));

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT package_name FROM installed_apps ORDER BY package_name", -1, &statement, nullptr),
        SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "com.first");
    EXPECT_EQ(sqlite3_step(statement), SQLITE_DONE);
    sqlite3_finalize(statement);

    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT db_path, open_status FROM app_db_inventory WHERE package_name = 'com.second'", -1,
        &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "shared.bak");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1)), "parse_error");
    EXPECT_EQ(sqlite3_step(statement), SQLITE_DONE);
    sqlite3_finalize(statement);

    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT count(*) FROM app_db_inventory WHERE package_name = 'com.second' "
        "AND db_path LIKE 'apps/com.first/%'", -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(statement, 0), 0);
    sqlite3_finalize(statement);
    sqlite3_close(raw);
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

    fs::path bakDir = uniqueTempPath("miui_evidence");
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

TEST(MiuiBackupExtractorTest, KeepsInternalTempsOutsideEvidenceWhenTmpdirIsInside) {
#ifndef _WIN32
    const fs::path dir = uniqueTempPath("miui_tmpdir_evidence");
    const fs::path hostileTmp = dir / "hostile-tmp";
    fs::create_directories(hostileTmp);
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("Foo.bak");
    const auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "DATA"}});
    const std::string raw = readFile(tar);
    uLong bound = compressBound(static_cast<uLong>(raw.size()));
    std::vector<Bytef> compressed(bound);
    uLongf compressedSize = bound;
    ASSERT_EQ(compress(compressed.data(), &compressedSize,
                       reinterpret_cast<const Bytef*>(raw.data()), raw.size()), Z_OK);
    std::ofstream bak(dir / "Foo.bak", std::ios::binary);
    bak << "ANDROID BACKUP\n5\n1\nnone\n";
    bak.write(reinterpret_cast<const char*>(compressed.data()), compressedSize);
    bak.close();

    const char* previous = std::getenv("TMPDIR");
    const std::string saved = previous ? previous : "";
    ASSERT_EQ(::setenv("TMPDIR", hostileTmp.c_str(), 1), 0);
    {
        MiuiBackupExtractor extractor(dir.string());
        ASSERT_TRUE(extractor.initialize());
        EXPECT_FALSE(miui_secure_temp::isSameOrDescendant(extractor.temporaryRoot(),
                                                           fs::canonical(dir)));
        EXPECT_TRUE(fs::is_empty(hostileTmp));
    }
    if (previous) ::setenv("TMPDIR", saved.c_str(), 1);
    else ::unsetenv("TMPDIR");
#endif
}

TEST(MiuiArtifactTest, IgnoresDatabaseDirectoryEntries) {
    const fs::path dir = uniqueTempPath("miui_directory_inventory");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages><package><packageName>com.tencent.mobileqq</packageName>"
           "<bakFile>QQ(com.tencent.mobileqq).bak</bakFile></package></packages></MIUI-backup>";
    const auto tar = makeUstarDirectory("apps/com.tencent.mobileqq/db/nt_db/");
    std::ofstream(dir / "QQ(com.tencent.mobileqq).bak", std::ios::binary) << rawBackup(readFile(tar));

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_directory_inventory", ".db");
    TemporaryFile cleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    ASSERT_TRUE(writeAppDbInventory(extractor, db));

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw, "SELECT COUNT(*) FROM app_db_inventory", -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(statement, 0), 0);
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(QqntArtifactTest, RecoversSensitiveXmlValuesWithPerValueHashes) {
    const fs::path dir = uniqueTempPath("qqnt_xml");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages><package><packageName>com.tencent.mobileqq</packageName>"
           "<bakFile>QQ(com.tencent.mobileqq).bak</bakFile></package></packages></MIUI-backup>";
    const auto tar = makeUstarTar({
        {"apps/com.tencent.mobileqq/sp/preferences.xml",
         "<map><string name=\"deviceId\">secret-device</string><int name=\"retry_count\" value=\"2\" /></map>"}
    });
    std::ofstream(dir / "QQ(com.tencent.mobileqq).bak", std::ios::binary) << rawBackup(readFile(tar));

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("qqnt_xml", ".db");
    TemporaryFile cleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    ASSERT_TRUE(persistMiuiBackupAnalysis(extractor, db));

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT value_text, value_hash, is_sensitive FROM qqnt_kv_records WHERE key = 'deviceId'", -1,
        &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "secret-device");
    EXPECT_EQ(std::strlen(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1))), 64u);
    EXPECT_EQ(sqlite3_column_int(statement, 2), 1);
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(MiuiArtifactTest, WritesManifestAndRecordsUnreadableDatabaseFailure) {
    const fs::path dir = uniqueTempPath("miui_art_invalid");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<?xml version='1.0'?><MIUI-backup><device>cepheus</device>"
           "<miuiVersion>V12</miuiVersion><date>1</date><size>4</size><packages>"
           "<package><packageName>com.foo</packageName><bakFile>Foo(com.foo).bak</bakFile>"
           "<bakType>1</bakType><pkgSize>4</pkgSize><sdSize>0</sdSize><state>1</state>"
           "<error>0</error></package></packages></MIUI-backup>";
    const auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "DATA"}});
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary)
        << "MIUI BACKUP\n2\ncom.foo Foo\n-1\n0\nANDROID BACKUP\n5\n0\nnone\n"
        << readFile(tar);

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());

    const fs::path dbPath = uniqueTempPath("miui_art_invalid", ".db");
    TemporaryFile cleanup(dbPath);
    AndroidAnalysisDatabase db(dbPath.string());
    ASSERT_TRUE(db.initialize());

    writeMiuiManifest(extractor, db);
    writeAppDbInventory(extractor, db);

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(dbPath.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT count(*) FROM installed_apps WHERE package_name = ?", -1, &statement, nullptr),
        SQLITE_OK);
    ASSERT_EQ(sqlite3_bind_text(statement, 1, "com.foo", -1, SQLITE_STATIC), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(statement, 0), 1);
    sqlite3_finalize(statement);

    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT table_name, row_count, columns, open_status FROM app_db_inventory "
        "WHERE package_name = ? AND db_path = ?", -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_bind_text(statement, 1, "com.foo", -1, SQLITE_STATIC), SQLITE_OK);
    ASSERT_EQ(sqlite3_bind_text(statement, 2, "apps/com.foo/db/x.db", -1, SQLITE_STATIC), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "");
    EXPECT_EQ(sqlite3_column_int64(statement, 1), 0);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 2)), "");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 3)), "parse_error");
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(MiuiArtifactTest, InventoriesRealSqliteTablesAndColumns) {
    const fs::path sourceDb = uniqueTempPath("miui_source", ".db");
    TemporaryFile sourceCleanup(sourceDb);
    sqlite3* source = nullptr;
    ASSERT_EQ(sqlite3_open(sourceDb.string().c_str(), &source), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(source,
        "CREATE TABLE t(id INTEGER PRIMARY KEY, note TEXT);"
        "INSERT INTO t(note) VALUES('one'),('two');",
        nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(source);

    const fs::path dir = uniqueTempPath("miui_art_valid");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><device>cepheus</device><miuiVersion>V12</miuiVersion>"
           "<date>1</date><size>1</size><packages><package>"
           "<packageName>com.foo</packageName><bakFile>Foo(com.foo).bak</bakFile>"
           "<bakType>1</bakType><pkgSize>1</pkgSize><sdSize>0</sdSize>"
           "</package></packages></MIUI-backup>";
    const auto tar = makeUstarTar({
        {"apps/com.foo/db/real.db", readFile(sourceDb)},
        {"apps/com.foo/f/not-a-db.db", "not sqlite"}
    });
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary)
        << rawBackup(readFile(tar));

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());

    std::vector<std::pair<std::string, std::string>> entries;
    extractor.enumerateEntries([&](const std::string& member, const std::string& bakFile) {
        entries.emplace_back(member, bakFile);
    });
    ASSERT_EQ(entries.size(), 2u);
    EXPECT_EQ(entries[0].second, "Foo(com.foo).bak");
    EXPECT_EQ(entries[1].second, "Foo(com.foo).bak");

    const fs::path copiedDb = dir / "copied" / "real.db";
    ASSERT_TRUE(extractor.extractTarMember("apps/com.foo/db/real.db", copiedDb.string()));
    EXPECT_EQ(readFile(copiedDb), readFile(sourceDb));

    const fs::path analysisDb = uniqueTempPath("miui_art_valid", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    writeAppDbInventory(extractor, db);

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT row_count, columns, open_status FROM app_db_inventory "
        "WHERE package_name = ? AND db_path = ? AND table_name = ?", -1, &statement, nullptr),
        SQLITE_OK);
    ASSERT_EQ(sqlite3_bind_text(statement, 1, "com.foo", -1, SQLITE_STATIC), SQLITE_OK);
    ASSERT_EQ(sqlite3_bind_text(statement, 2, "apps/com.foo/db/real.db", -1, SQLITE_STATIC), SQLITE_OK);
    ASSERT_EQ(sqlite3_bind_text(statement, 3, "t", -1, SQLITE_STATIC), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int64(statement, 0), 2);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1)), "id,note");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 2)), "decrypted");
    sqlite3_finalize(statement);

    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT count(*) FROM app_db_inventory WHERE db_path = ?", -1, &statement, nullptr),
        SQLITE_OK);
    ASSERT_EQ(sqlite3_bind_text(statement, 1, "apps/com.foo/f/not-a-db.db", -1, SQLITE_STATIC),
              SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(statement, 0), 0);
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

static std::string createWalDatabaseBytes(std::string& mainBytes,
                                          std::string& walBytes,
                                          std::string& shmBytes) {
    const fs::path path = uniqueTempPath("miui_wal_source", ".db");
    sqlite3* connection = nullptr;
    EXPECT_EQ(sqlite3_open(path.string().c_str(), &connection), SQLITE_OK);
    if (!connection) return {};
    EXPECT_EQ(sqlite3_exec(connection,
        "PRAGMA journal_mode=WAL;"
        "PRAGMA wal_autocheckpoint=0;"
        "CREATE TABLE t(id INTEGER PRIMARY KEY, note TEXT);"
        "INSERT INTO t(note) VALUES('main');"
        "PRAGMA wal_checkpoint(TRUNCATE);"
        "INSERT INTO t(note) VALUES('wal-one'),('wal-two');",
        nullptr, nullptr, nullptr), SQLITE_OK);
    mainBytes = readFile(path);
    walBytes = readFile(path.string() + "-wal");
    shmBytes = readFile(path.string() + "-shm");
    sqlite3_close(connection);
    std::error_code error;
    fs::remove(path, error);
    fs::remove(path.string() + "-wal", error);
    fs::remove(path.string() + "-shm", error);
    return mainBytes;
}

TEST(MiuiArtifactTest, AppliesWalSidecarsBeforeInventory) {
    std::string mainBytes;
    std::string walBytes;
    std::string shmBytes;
    ASSERT_FALSE(createWalDatabaseBytes(mainBytes, walBytes, shmBytes).empty());
    ASSERT_FALSE(walBytes.empty());

    const fs::path dir = uniqueTempPath("miui_art_wal");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << minimalBackupXml("Foo(com.foo).bak");
    const auto tar = makeUstarTar({
        {"apps/com.foo/db/live.db", mainBytes},
        {"apps/com.foo/db/live.db-wal", walBytes},
        {"apps/com.foo/db/live.db-shm", shmBytes}
    });
    std::ofstream(dir / "Foo(com.foo).bak", std::ios::binary) << rawBackup(readFile(tar));

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_art_wal", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    writeAppDbInventory(extractor, db);

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT row_count, open_status FROM app_db_inventory "
        "WHERE db_path = ? AND table_name = 't'", -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_bind_text(statement, 1, "apps/com.foo/db/live.db", -1, SQLITE_STATIC),
              SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int64(statement, 0), 3);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1)), "decrypted");
    sqlite3_finalize(statement);

    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT count(*) FROM app_db_inventory WHERE db_path LIKE '%-wal' OR db_path LIKE '%-shm'",
        -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(statement, 0), 0);
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(MiuiArtifactTest, RecordsEncryptedPackageThatHasNoEnumerableEntries) {
    const fs::path dir = uniqueTempPath("miui_art_mixed");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << "<MIUI-backup><packages>"
           "<package><packageName>com.foo</packageName><bakFile>Foo.bak</bakFile></package>"
           "<package><packageName>com.locked</packageName><bakFile>Locked.bak</bakFile></package>"
           "</packages></MIUI-backup>";
    const auto tar = makeUstarTar({{"apps/com.foo/db/x.db", "DATA"}});
    std::ofstream(dir / "Foo.bak", std::ios::binary) << rawBackup(readFile(tar));
    std::ofstream(dir / "Locked.bak", std::ios::binary)
        << "ANDROID BACKUP\n5\n0\nAES-256-encrypted\nciphertext";

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_art_mixed", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    writeAppDbInventory(extractor, db);

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT db_path, open_status FROM app_db_inventory WHERE package_name = 'com.locked'",
        -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "Locked.bak");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1)),
                 "encrypted_locked");
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(MiuiArtifactTest, RejectsDatabaseBeyondExtractionLimitWithoutWritingIt) {
    const fs::path dir = uniqueTempPath("miui_art_oversize");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << minimalBackupXml("Foo.bak");
    std::string header(512, '\0');
    const std::string member = "apps/com.foo/db/huge.db";
    std::memcpy(header.data(), member.data(), member.size());
    const uint64_t declaredSize = 513ULL * 1024 * 1024;
    char sizeField[13]{};
    std::snprintf(sizeField, sizeof(sizeField), "%011lo", static_cast<unsigned long>(declaredSize));
    std::memcpy(header.data() + 124, sizeField, 12);
    header[156] = '0';
    const std::string backupHeader = "ANDROID BACKUP\n5\n0\nnone\n";
    std::ofstream oversized(dir / "Foo.bak", std::ios::binary);
    oversized << backupHeader << header;
    oversized.seekp(static_cast<std::streamoff>(backupHeader.size() + 512 + declaredSize));
    oversized << std::string(1024, '\0');
    oversized.close();

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_art_oversize", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    writeAppDbInventory(extractor, db);

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT open_status FROM app_db_inventory WHERE db_path = 'apps/com.foo/db/huge.db'",
        -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "parse_error");
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(MiuiArtifactTest, RejectsOversizedSerializedColumnMetadata) {
    const fs::path sourceDb = uniqueTempPath("miui_columns_source", ".db");
    TemporaryFile sourceCleanup(sourceDb);
    sqlite3* source = nullptr;
    ASSERT_EQ(sqlite3_open(sourceDb.string().c_str(), &source), SQLITE_OK);
    std::string create = "CREATE TABLE wide(";
    for (int index = 0; index < 80; ++index) {
        if (index) create += ',';
        create += "column_" + std::to_string(index) + "_" + std::string(80, 'x') + " TEXT";
    }
    create += ");";
    ASSERT_EQ(sqlite3_exec(source, create.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(source);

    const fs::path dir = uniqueTempPath("miui_art_columns");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("Foo.bak");
    const auto tar = makeUstarTar({{"apps/com.foo/db/wide.db", readFile(sourceDb)}});
    std::ofstream(dir / "Foo.bak", std::ios::binary) << rawBackup(readFile(tar));

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_art_columns", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    writeAppDbInventory(extractor, db);

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT table_name, columns, open_status FROM app_db_inventory "
        "WHERE db_path = 'apps/com.foo/db/wide.db' ORDER BY id DESC LIMIT 1",
        -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1)), "");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 2)), "parse_error");
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(MiuiArtifactTest, DoesNotFollowPreexistingInventorySymlink) {
#ifndef _WIN32
    const fs::path sourceDb = uniqueTempPath("miui_symlink_source", ".db");
    TemporaryFile sourceCleanup(sourceDb);
    sqlite3* source = nullptr;
    ASSERT_EQ(sqlite3_open(sourceDb.string().c_str(), &source), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(source, "CREATE TABLE t(id INTEGER);", nullptr, nullptr, nullptr),
              SQLITE_OK);
    sqlite3_close(source);

    const fs::path dir = uniqueTempPath("miui_art_symlink_output");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("Foo.bak");
    const auto tar = makeUstarTar({{"apps/com.foo/db/real.db", readFile(sourceDb)}});
    std::ofstream(dir / "Foo.bak", std::ios::binary) << rawBackup(readFile(tar));

    const fs::path victim = uniqueTempPath("miui_inventory_victim");
    TemporaryFile victimCleanup(victim);
    std::ofstream(victim, std::ios::binary) << "UNCHANGED";
    const fs::path malicious = fs::temp_directory_path() / "tracelens-miui-inventory-malicious";
    std::error_code error;
    fs::remove_all(malicious, error);
    fs::create_directory(malicious);
    fs::create_symlink(victim, malicious / "database-0.db", error);
    if (error) GTEST_SKIP() << "symlink creation unavailable: " << error.message();

    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_art_symlink_output", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    writeAppDbInventory(extractor, db);

    EXPECT_EQ(readFile(victim), "UNCHANGED");
    fs::remove_all(malicious, error);
#endif
}

TEST(MiuiArtifactTest, PersistBackupAnalysisRollsBackManifestWhenInventoryFails) {
    const fs::path dir = uniqueTempPath("miui_atomic_persist");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary)
        << minimalBackupXml("missing.bak");
    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());

    const fs::path analysisDb = uniqueTempPath("miui_atomic_persist", ".db");
    TemporaryFile cleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(raw, "DROP TABLE app_db_inventory;", nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(raw);

    EXPECT_FALSE(persistMiuiBackupAnalysis(extractor, db));

    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw, "SELECT count(*) FROM miui_backup_manifest;", -1,
                                 &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(statement, 0), 0);
    sqlite3_finalize(statement);
    ASSERT_EQ(sqlite3_prepare_v2(raw, "SELECT count(*) FROM installed_apps;", -1,
                                 &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(statement, 0), 0);
    sqlite3_finalize(statement);
    sqlite3_close(raw);
}

TEST(MiuiArtifactTest, PropagatesPersistenceFailureAndRollsBack) {
    const fs::path dir = uniqueTempPath("miui_persist_failure");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("missing.bak");
    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());

    const fs::path analysisDb = uniqueTempPath("miui_persist_failure", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());
    ASSERT_TRUE(db.beginTransaction());
    ASSERT_TRUE(db.insertAppDbInventory("lock", "lock", "", 0, "", "parse_error"));

    EXPECT_FALSE(writeAppDbInventory(extractor, db));
    EXPECT_TRUE(db.rollbackTransaction());
}

TEST(MiuiArtifactTest, RecordsDurableIncompleteStatusWhenBackupWideLimitHits) {
#ifndef _WIN32
    const fs::path sourceDb = uniqueTempPath("miui_limit_source", ".db");
    TemporaryFile sourceCleanup(sourceDb);
    sqlite3* source = nullptr;
    ASSERT_EQ(sqlite3_open(sourceDb.string().c_str(), &source), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(source, "CREATE TABLE t(id INTEGER);", nullptr, nullptr, nullptr),
              SQLITE_OK);
    sqlite3_close(source);

    const fs::path dir = uniqueTempPath("miui_art_limit");
    fs::create_directories(dir);
    std::ofstream(dir / "descript.xml", std::ios::binary) << minimalBackupXml("Foo.bak");
    const auto tar = makeUstarTar({
        {"apps/com.foo/db/first.db", readFile(sourceDb)},
        {"apps/com.foo/db/second.db", readFile(sourceDb)}
    });
    std::ofstream(dir / "Foo.bak", std::ios::binary) << rawBackup(readFile(tar));
    MiuiBackupExtractor extractor(dir.string());
    ASSERT_TRUE(extractor.initialize());
    const fs::path analysisDb = uniqueTempPath("miui_art_limit", ".db");
    TemporaryFile analysisCleanup(analysisDb);
    AndroidAnalysisDatabase db(analysisDb.string());
    ASSERT_TRUE(db.initialize());

    ASSERT_EQ(::setenv("TRACELENS_MIUI_MAX_CANDIDATES", "1", 1), 0);
    EXPECT_TRUE(writeAppDbInventory(extractor, db));
    ::unsetenv("TRACELENS_MIUI_MAX_CANDIDATES");

    sqlite3* raw = nullptr;
    ASSERT_EQ(sqlite3_open(analysisDb.string().c_str(), &raw), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(raw,
        "SELECT count(*) FROM app_db_inventory WHERE open_status = 'incomplete_limit'",
        -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_EQ(sqlite3_column_int(statement, 0), 1);
    sqlite3_finalize(statement);
    sqlite3_close(raw);
#endif
}

TEST(MiuiDbTest, PersistsMiuiBackupMetadataAcrossAllTables) {
    const fs::path dbPath = uniqueTempPath("miui_metadata", ".db");
    TemporaryFile cleanup(dbPath);

    {
        AndroidAnalysisDatabase db(dbPath.string());
        ASSERT_TRUE(db.initialize());
        ASSERT_TRUE(db.insertMiuiBackupManifest("cepheus", "V12", 1785299538978ull,
                                                100, 3, "/evidence/backup"));
        ASSERT_TRUE(db.insertInstalledApp("com.foo", "Foo", "10", "1.0", 500, 0,
                                          1, "manifest summary"));
        ASSERT_TRUE(db.insertAppDbInventory("com.foo", "apps/com.foo/db/x.db", "msgs", 42,
                                            "id,text", "decrypted"));

        using SqliteConnection = std::unique_ptr<sqlite3, decltype(&sqlite3_close)>;
        using SqliteStatement = std::unique_ptr<sqlite3_stmt, decltype(&sqlite3_finalize)>;

        sqlite3* rawConnection = nullptr;
        const int openResult = sqlite3_open(dbPath.string().c_str(), &rawConnection);
        SqliteConnection raw(rawConnection, sqlite3_close);
        ASSERT_EQ(openResult, SQLITE_OK);

        auto query = [&raw](const char* sql) {
            sqlite3_stmt* rawStatement = nullptr;
            const int prepareResult = sqlite3_prepare_v2(raw.get(), sql, -1, &rawStatement, nullptr);
            return std::make_pair(prepareResult,
                                  SqliteStatement(rawStatement, sqlite3_finalize));
        };

        auto [manifestPrepareResult, manifestStatement] = query(
            "SELECT device, miui_version, backup_date, total_size, package_count, source_folder "
            "FROM miui_backup_manifest");
        ASSERT_EQ(manifestPrepareResult, SQLITE_OK);
        ASSERT_EQ(sqlite3_step(manifestStatement.get()), SQLITE_ROW);
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(manifestStatement.get(), 0)), "cepheus");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(manifestStatement.get(), 1)), "V12");
        EXPECT_EQ(sqlite3_column_int64(manifestStatement.get(), 2), 1785299538978ll);
        EXPECT_EQ(sqlite3_column_int64(manifestStatement.get(), 3), 100);
        EXPECT_EQ(sqlite3_column_int(manifestStatement.get(), 4), 3);
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(manifestStatement.get(), 5)), "/evidence/backup");

        auto [appPrepareResult, appStatement] = query(
            "SELECT display_name, version_code, version_name, data_size, sd_size, bak_type, "
            "manifest_summary FROM installed_apps WHERE package_name = 'com.foo'");
        ASSERT_EQ(appPrepareResult, SQLITE_OK);
        ASSERT_EQ(sqlite3_step(appStatement.get()), SQLITE_ROW);
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(appStatement.get(), 0)), "Foo");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(appStatement.get(), 1)), "10");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(appStatement.get(), 2)), "1.0");
        EXPECT_EQ(sqlite3_column_int64(appStatement.get(), 3), 500);
        EXPECT_EQ(sqlite3_column_int64(appStatement.get(), 4), 0);
        EXPECT_EQ(sqlite3_column_int(appStatement.get(), 5), 1);
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(appStatement.get(), 6)), "manifest summary");

        auto [inventoryPrepareResult, inventoryStatement] = query(
            "SELECT db_path, table_name, row_count, columns, open_status FROM app_db_inventory "
            "WHERE package_name = 'com.foo'");
        ASSERT_EQ(inventoryPrepareResult, SQLITE_OK);
        ASSERT_EQ(sqlite3_step(inventoryStatement.get()), SQLITE_ROW);
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(inventoryStatement.get(), 0)), "apps/com.foo/db/x.db");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(inventoryStatement.get(), 1)), "msgs");
        EXPECT_EQ(sqlite3_column_int64(inventoryStatement.get(), 2), 42);
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(inventoryStatement.get(), 3)), "id,text");
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(inventoryStatement.get(), 4)), "decrypted");
    }
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
