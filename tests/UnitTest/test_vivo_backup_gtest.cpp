/**
 * @file test_vivo_backup_gtest.cpp
 * @brief Tests for the vivo (iQOO) backup extractor and artifact parser.
 *
 * The fixture builds the normalised index JSON the Python bridge produces, so
 * the test covers the C++ contract without needing LevelDB in the test binary.
 */

#include <gtest/gtest.h>

#include <sqlite3.h>

#include <filesystem>
#include <fstream>
#include <string>

#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include "analyzers/VivoAnalyzer/VivoArtifactParsers.h"
#include "analyzers/VivoAnalyzer/VivoBackupExtractor.h"

namespace fs = std::filesystem;

namespace {

void writeFile(const fs::path& path, const std::string& bytes) {
    fs::create_directories(path.parent_path());
    std::ofstream output(path, std::ios::binary);
    output.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

/** A backup with a .backup header, a db/ marker and an index.json. */
fs::path makeBackup(const fs::path& root, const std::string& indexJson,
                    bool encrypted = false, const std::string& model = "vivo iQOO") {
    fs::create_directories(root / "db");
    writeFile(root / ".backup",
              std::string("{\"model\":\"") + model + "\",\"createTime\":1793257658334,"
              "\"encrypted\":" + (encrypted ? "true" : "false") +
              ",\"backupPackageVer\":2,\"success\":true}");
    writeFile(root / "index.json", indexJson);
    return root;
}

std::string indexWithItems(bool obfuscated) {
    return std::string("{\"format\":\"tracelens-vivo-index-v1\",")
        + "\"model\":\"vivo iQOO\",\"backup_package_version\":2,"
        + "\"backup_time_ms\":1793257658334,"
        + "\"obfuscated\":" + (obfuscated ? "true" : "false") + ","
        + "\"items\":["
        + "{\"category\":\"album\",\"index\":0,\"hash\":\"" + std::string(40, '1') + "\","
          "\"original_path\":\"storage/emulated/0/DCIM/Camera/IMG_1.jpg\","
          "\"size\":3403363,\"mtime_ms\":1573115211000},"
        + "{\"category\":\"document\",\"index\":0,\"hash\":\"" + std::string(40, '2') + "\","
          "\"original_path\":\"storage/emulated/0/tencent/report.xlsx\","
          "\"size\":10746,\"mtime_ms\":1551662274000}"
        + "],"
        + "\"applications\":["
        + "{\"package\":\"com.example.one\",\"kind\":\"apk\",\"hash\":\"" + std::string(40, '3') + "\","
          "\"file_name\":\"app_com.example.one.apk\",\"size\":53078111,"
          "\"app_name\":\"One\",\"version_name\":\"1.0\",\"version_code\":10,"
          "\"with_data\":true}"
        + "],"
        + "\"categories\":[{\"key\":\"album\",\"label\":\"相册\",\"count\":4259,"
          "\"size\":1419018700,\"stored_as_files\":true}],"
        + "\"record_categories\":[{\"key\":\"sms\",\"label\":\"信息\",\"data_type\":2,"
          "\"count\":2331,\"size\":4662000,\"stored_as_files\":false}],"
        + "\"warnings\":[]}";
}

}  // namespace

TEST(VivoBackupExtractorTest, RecognizesBackupDirectory) {
    const fs::path temp = fs::temp_directory_path() / "vivo-recognize";
    fs::remove_all(temp);
    makeBackup(temp / "case" / "UDID", indexWithItems(false));
    EXPECT_TRUE(VivoBackupExtractor::recognizes(temp.string()));
    EXPECT_FALSE(VivoBackupExtractor::recognizes((temp / "missing").string()));
    fs::remove_all(temp);
}

TEST(VivoBackupExtractorTest, InitializesAndIndexesItems) {
    const fs::path temp = fs::temp_directory_path() / "vivo-init";
    fs::remove_all(temp);
    makeBackup(temp / "UDID", indexWithItems(false));

    VivoBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    EXPECT_EQ(extractor.model(), "vivo iQOO");
    EXPECT_EQ(extractor.backupVersion(), "2");
    EXPECT_EQ(extractor.itemCount(), 3u);   // 2 files + 1 app entry
    EXPECT_EQ(extractor.applicationCount(), 1u);
    EXPECT_FALSE(extractor.obfuscated());
    fs::remove_all(temp);
}

TEST(VivoBackupExtractorTest, EncryptedBackupIsRejected) {
    const fs::path temp = fs::temp_directory_path() / "vivo-enc";
    fs::remove_all(temp);
    makeBackup(temp / "UDID", indexWithItems(false), true);

    VivoBackupExtractor extractor((temp / "UDID").string());
    EXPECT_FALSE(extractor.initialize());
    EXPECT_EQ(extractor.error(), "VIVO_BACKUP_ENCRYPTED");
    fs::remove_all(temp);
}

TEST(VivoBackupExtractorTest, ObfuscationFlagIsSurfaced) {
    const fs::path temp = fs::temp_directory_path() / "vivo-obf";
    fs::remove_all(temp);
    makeBackup(temp / "UDID", indexWithItems(true));

    VivoBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    EXPECT_TRUE(extractor.obfuscated());
    fs::remove_all(temp);
}

TEST(VivoBackupExtractorTest, ExtractCopiesPayloadByOriginalPath) {
    const fs::path temp = fs::temp_directory_path() / "vivo-extract";
    fs::remove_all(temp);
    const fs::path root = makeBackup(temp / "UDID", indexWithItems(false));
    writeFile(root / std::string(40, '1'), "PAYLOADBYTES");

    VivoBackupExtractor extractor(root.string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();

    const fs::path out = temp / "out" / "IMG_1.jpg";
    ASSERT_TRUE(extractor.extractFileByPath(
        "storage/emulated/0/DCIM/Camera/IMG_1.jpg", out.string()));
    ASSERT_TRUE(fs::is_regular_file(out));

    const auto provenance = extractor.usedSourceProvenance();
    ASSERT_EQ(provenance.size(), 1u);
    EXPECT_EQ(provenance[0].adapterType, "vivo-backup");
    EXPECT_EQ(provenance[0].normalizedAndroidPath,
              "storage/emulated/0/DCIM/Camera/IMG_1.jpg");
    fs::remove_all(temp);
}

TEST(VivoBackupExtractorTest, MissingPayloadIsNotAnEmptyFile) {
    const fs::path temp = fs::temp_directory_path() / "vivo-missing";
    fs::remove_all(temp);
    const fs::path root = makeBackup(temp / "UDID", indexWithItems(false));
    // Deliberately do not create the payload file.

    VivoBackupExtractor extractor(root.string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    EXPECT_FALSE(extractor.extractFileByPath(
        "storage/emulated/0/DCIM/Camera/IMG_1.jpg", (temp / "out.jpg").string()));
    EXPECT_FALSE(fs::exists(temp / "out.jpg"));
    fs::remove_all(temp);
}

TEST(VivoArtifactParsersTest, WritesManifestAppsAndRecords) {
    const fs::path temp = fs::temp_directory_path() / "vivo-parse";
    fs::remove_all(temp);
    const fs::path root = makeBackup(temp / "UDID", indexWithItems(true));

    VivoBackupExtractor extractor(root.string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();

    vivo_artifacts::VivoParseResult parsed;
    {
        AndroidAnalysisDatabase database((temp / "android.db").string());
        ASSERT_TRUE(database.initialize());
        parsed = vivo_artifacts::analyzeVivoBackup(extractor, database);
    }

    EXPECT_EQ(parsed.applications, 1);
    EXPECT_EQ(parsed.fileRecords, 3);   // 2 files + 1 app entry

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((temp / "android.db").c_str(), &db), SQLITE_OK);
    auto scalar = [&db](const char* sql) -> long long {
        sqlite3_stmt* statement = nullptr;
        long long value = -1;
        if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) == SQLITE_OK) {
            if (sqlite3_step(statement) == SQLITE_ROW) value = sqlite3_column_int64(statement, 0);
            sqlite3_finalize(statement);
        }
        return value;
    };
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM mobile_backup_manifest"), 1);
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM installed_packages"), 1);
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM mobile_artifacts"), 3);
    // Obfuscated payload must be recorded as locked, never as parsed rows.
    // Three categories are present in the fixture: album, document and app.
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM android_source_coverage WHERE status='locked_or_unsupported'"), 3);
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM sms_messages"), 0);
    sqlite3_close(db);
    fs::remove_all(temp);
}

TEST(VivoArtifactParsersTest, RecordCategoryCountsNeverBecomeRows) {
    const fs::path temp = fs::temp_directory_path() / "vivo-counts";
    fs::remove_all(temp);
    const fs::path root = makeBackup(temp / "UDID", indexWithItems(false));

    VivoBackupExtractor extractor(root.string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    {
        AndroidAnalysisDatabase database((temp / "android.db").string());
        ASSERT_TRUE(database.initialize());
        vivo_artifacts::analyzeVivoBackup(extractor, database);
    }

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((temp / "android.db").c_str(), &db), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT COUNT(*) FROM sms_messages", -1, &statement, nullptr),
              SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    // The index says 2331 SMS exist on the phone; none are in this package.
    EXPECT_EQ(sqlite3_column_int(statement, 0), 0);
    sqlite3_finalize(statement);
    sqlite3_close(db);
    fs::remove_all(temp);
}

TEST(VivoArtifactParsersTest, SourceKeyIsValidJson) {
    const fs::path temp = fs::temp_directory_path() / "vivo-key";
    fs::remove_all(temp);
    const fs::path root = makeBackup(temp / "UDID", indexWithItems(false));
    VivoBackupExtractor extractor(root.string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    {
        AndroidAnalysisDatabase database((temp / "android.db").string());
        ASSERT_TRUE(database.initialize());
        vivo_artifacts::analyzeVivoBackup(extractor, database);
    }

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((temp / "android.db").c_str(), &db), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT source_key FROM mobile_artifacts LIMIT 1",
                                 -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    const std::string key = reinterpret_cast<const char*>(sqlite3_column_text(statement, 0));
    EXPECT_EQ(key.front(), '{');
    EXPECT_EQ(key.back(), '}');
    sqlite3_finalize(statement);
    sqlite3_close(db);
    fs::remove_all(temp);
}

// ----------------------------------------------------------- deobfuscation

#include "analyzers/VivoAnalyzer/VivoDeobfuscator.h"

TEST(VivoDeobfuscatorTest, KeyIsEightBytesAndSymmetric) {
    // XOR is its own inverse: applying it twice must restore the input.
    const std::vector<std::uint8_t> original = {0x00, 0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77,
                                                0x88, 0x99, 0xAA, 0xBB};
    auto encoded = vivo::deobfuscate(original);
    EXPECT_NE(encoded, original);
    auto restored = vivo::deobfuscate(encoded);
    EXPECT_EQ(restored, original);
}

TEST(VivoDeobfuscatorTest, DecodesStandardJpegHeader) {
    // A camera JPEG starts FF D8 FF E1; the encoder wrote those bytes XORed.
    const std::vector<std::uint8_t> plain = {0xFF, 0xD8, 0xFF, 0xE1, 0x00, 0x40,
                                             0x45, 0x78, 0x69, 0x66, 0x00, 0x00};
    const auto encoded = vivo::deobfuscate(plain);
    const auto decoded = vivo::deobfuscate(encoded);
    ASSERT_GE(decoded.size(), 4u);
    EXPECT_EQ(decoded[0], 0xFF);
    EXPECT_EQ(decoded[1], 0xD8);
    EXPECT_EQ(decoded[2], 0xFF);
    EXPECT_EQ(decoded[3], 0xE1);
    EXPECT_TRUE(vivo::hasKnownMagic(decoded));
}

TEST(VivoDeobfuscatorTest, OffsetChangesAlignment) {
    // Decoding a slice must use the absolute offset or the key misaligns.
    std::vector<std::uint8_t> whole = {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12};
    auto decodedWhole = vivo::deobfuscate(whole, 0);
    std::vector<std::uint8_t> tail(whole.begin() + 4, whole.end());
    auto decodedTail = vivo::deobfuscate(tail, 4);
    EXPECT_EQ(std::vector<std::uint8_t>(decodedWhole.begin() + 4, decodedWhole.end()),
              decodedTail);
}

TEST(VivoDeobfuscatorTest, RecognisesCommonContainerMagic) {
    EXPECT_TRUE(vivo::hasKnownMagic({0xFF, 0xD8, 0xFF, 0xE0}));           // JPEG
    EXPECT_TRUE(vivo::hasKnownMagic({0x89, 0x50, 0x4E, 0x47}));           // PNG
    EXPECT_TRUE(vivo::hasKnownMagic({'P', 'K', 0x03, 0x04}));             // ZIP
    EXPECT_TRUE(vivo::hasKnownMagic({'R', 'a', 'r', '!'}));               // RAR
    EXPECT_TRUE(vivo::hasKnownMagic({'f', 'L', 'a', 'C'}));               // FLAC
    EXPECT_TRUE(vivo::hasKnownMagic({'%', 'P', 'D', 'F'}));               // PDF
    EXPECT_FALSE(vivo::hasKnownMagic({0x01, 0x02, 0x03, 0x04}));
}
