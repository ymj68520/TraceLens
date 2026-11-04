/**
 * @file test_ios_backup_gtest.cpp
 * @brief Tests for the iOS logical-backup extractor and artifact parsers.
 *
 * Fixtures are synthesised on the fly (a real Manifest.plist/Manifest.db pair
 * plus hash-sharded files) so the tests never depend on case evidence.
 */

#include <gtest/gtest.h>

#include <sqlite3.h>

#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include "analyzers/IosAnalyzer/IosArtifactParsers.h"
#include "analyzers/IosAnalyzer/IosBackupExtractor.h"

namespace fs = std::filesystem;

namespace {

void writeFile(const fs::path& path, const std::string& bytes) {
    fs::create_directories(path.parent_path());
    std::ofstream output(path, std::ios::binary);
    output.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

std::string manifestPlist(bool encrypted, const std::string& productType = "iPhone10,3") {
    std::string xml =
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
        "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
        "<plist version=\"1.0\"><dict>\n";
    xml += "  <key>IsEncrypted</key>\n  <" + std::string(encrypted ? "true" : "false") + "/>\n";
    xml += "  <key>Version</key>\n  <string>10.0</string>\n";
    xml += "  <key>Lockdown</key>\n  <dict>\n";
    xml += "    <key>ProductType</key>\n    <string>" + productType + "</string>\n";
    xml += "    <key>ProductVersion</key>\n    <string>16.5</string>\n";
    xml += "    <key>BuildVersion</key>\n    <string>20F66</string>\n";
    xml += "    <key>UniqueDeviceID</key>\n    <string>d5747fae8f4ddba485f17710026bd6bff268acb0</string>\n";
    xml += "    <key>SerialNumber</key>\n    <string>G6VWVGSXJCLF</string>\n";
    xml += "  </dict>\n</dict></plist>\n";
    return xml;
}

/** Build a Manifest.db plus shard files under `root`. */
void buildBackup(const fs::path& root, bool encrypted,
                 const std::vector<std::tuple<std::string, std::string, std::string>>& members) {
    fs::create_directories(root);
    writeFile(root / "Manifest.plist", manifestPlist(encrypted));

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((root / "Manifest.db").c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
                           "CREATE TABLE Files (fileID TEXT PRIMARY KEY, domain TEXT, "
                           "relativePath TEXT, flags INTEGER, file BLOB);",
                           nullptr, nullptr, nullptr), SQLITE_OK);
    for (const auto& [fileId, domain, relativePath] : members) {
        sqlite3_stmt* statement = nullptr;
        ASSERT_EQ(sqlite3_prepare_v2(db,
                                     "INSERT INTO Files(fileID, domain, relativePath, flags) "
                                     "VALUES(?,?,?,1)", -1, &statement, nullptr), SQLITE_OK);
        sqlite3_bind_text(statement, 1, fileId.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(statement, 2, domain.c_str(), -1, SQLITE_TRANSIENT);
        sqlite3_bind_text(statement, 3, relativePath.c_str(), -1, SQLITE_TRANSIENT);
        ASSERT_EQ(sqlite3_step(statement), SQLITE_DONE);
        sqlite3_finalize(statement);
    }
    sqlite3_close(db);
}

/** Create the shard file for a manifest entry and return its fileID. */
std::string addShard(const fs::path& root, const std::string& fileId,
                     const std::string& sourceDbPath) {
    std::ifstream input(sourceDbPath, std::ios::binary);
    std::string bytes((std::istreambuf_iterator<char>(input)),
                      std::istreambuf_iterator<char>());
    writeFile(root / fileId.substr(0, 2) / fileId, bytes);
    return fileId;
}

/** Build a source SQLite database from DDL + inserts. */
std::string makeSourceDb(const fs::path& path, const std::string& sql) {
    fs::create_directories(path.parent_path());
    sqlite3* db = nullptr;
    EXPECT_EQ(sqlite3_open(path.c_str(), &db), SQLITE_OK);
    char* error = nullptr;
    const int status = sqlite3_exec(db, sql.c_str(), nullptr, nullptr, &error);
    if (error) sqlite3_free(error);
    EXPECT_EQ(status, SQLITE_OK);
    sqlite3_close(db);
    return path.string();
}

/** Count rows in an arbitrary table of a finished android.db. */
long long countRows(const fs::path& dbPath, const std::string& table) {
    sqlite3* db = nullptr;
    if (sqlite3_open_v2(dbPath.c_str(), &db, SQLITE_OPEN_READONLY, nullptr) != SQLITE_OK) {
        if (db) sqlite3_close(db);
        return -1;
    }
    const std::string sql = "SELECT COUNT(*) FROM " + table;
    sqlite3_stmt* statement = nullptr;
    long long count = -1;
    if (sqlite3_prepare_v2(db, sql.c_str(), -1, &statement, nullptr) == SQLITE_OK) {
        if (sqlite3_step(statement) == SQLITE_ROW) count = sqlite3_column_int64(statement, 0);
        sqlite3_finalize(statement);
    }
    sqlite3_close(db);
    return count;
}

}  // namespace

// ---------------------------------------------------------------- extractor

TEST(IosBackupExtractorTest, RecognizesBackupDirectory) {
    const fs::path temp = fs::temp_directory_path() / "ios-recognize-test";
    fs::remove_all(temp);
    buildBackup(temp / "UDID", false, {});
    EXPECT_TRUE(IosBackupExtractor::recognizes(temp.string()));
    EXPECT_FALSE(IosBackupExtractor::recognizes((temp / "missing").string()));
    fs::remove_all(temp);
}

TEST(IosBackupExtractorTest, InitializesAndIndexesManifest) {
    const fs::path temp = fs::temp_directory_path() / "ios-init-test";
    fs::remove_all(temp);
    buildBackup(temp / "UDID", false,
                {{std::string(40, 'a'), "HomeDomain", "Library/SMS/sms.db"}});
    addShard(temp / "UDID", std::string(40, 'a'),
             makeSourceDb(temp / "sms.db", "CREATE TABLE message(ROWID INTEGER);"));

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    EXPECT_EQ(extractor.entryCount(), 1u);
    EXPECT_FALSE(extractor.encrypted());
    EXPECT_EQ(extractor.device().at("product_type"), "iPhone10,3");
    EXPECT_EQ(extractor.device().at("unique_device_id"),
              "d5747fae8f4ddba485f17710026bd6bff268acb0");
    EXPECT_EQ(extractor.backupVersion(), "10.0");
    EXPECT_FALSE(extractor.manifestSha256().empty());
    EXPECT_FALSE(extractor.shardPathFor("HomeDomain/Library/SMS/sms.db").empty());
    EXPECT_TRUE(extractor.shardPathFor("HomeDomain/Library/SMS/absent.db").empty());
    fs::remove_all(temp);
}

TEST(IosBackupExtractorTest, RejectsEncryptedBackup) {
    const fs::path temp = fs::temp_directory_path() / "ios-encrypted-test";
    fs::remove_all(temp);
    buildBackup(temp / "UDID", true, {});

    IosBackupExtractor extractor((temp / "UDID").string());
    EXPECT_FALSE(extractor.initialize());
    EXPECT_EQ(extractor.error(), "IOS_BACKUP_ENCRYPTED");
    EXPECT_TRUE(extractor.encrypted());
    fs::remove_all(temp);
}

TEST(IosBackupExtractorTest, ExtractFileCopiesShardBytesAndRecordsProvenance) {
    const fs::path temp = fs::temp_directory_path() / "ios-extract-test";
    fs::remove_all(temp);
    const std::string fileId(40, 'b');
    buildBackup(temp / "UDID", false,
                {{fileId, "HomeDomain", "Library/SMS/sms.db"}});
    addShard(temp / "UDID", fileId,
             makeSourceDb(temp / "sms.db",
                          "CREATE TABLE message(ROWID INTEGER);"
                          "INSERT INTO message VALUES(1);"));

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();

    const fs::path staged = temp / "out" / "sms.db";
    ASSERT_TRUE(extractor.extractFileByPath("HomeDomain/Library/SMS/sms.db", staged.string()));
    ASSERT_TRUE(fs::is_regular_file(staged));

    const auto provenance = extractor.usedSourceProvenance();
    ASSERT_EQ(provenance.size(), 1u);
    EXPECT_EQ(provenance[0].adapterType, "ios-backup");
    EXPECT_EQ(provenance[0].normalizedAndroidPath, "HomeDomain/Library/SMS/sms.db");
    EXPECT_EQ(provenance[0].sourceMemberPath, fileId);
    EXPECT_FALSE(provenance[0].memberSha256.empty());
    fs::remove_all(temp);
}

TEST(IosBackupExtractorTest, FindPathsByFilenameUsesIndex) {
    const fs::path temp = fs::temp_directory_path() / "ios-find-test";
    fs::remove_all(temp);
    buildBackup(temp / "UDID", false,
                {{std::string(40, 'c'), "AppDomain-com.example", "Documents/foo.db"},
                 {std::string(40, 'd'), "AppDomain-com.other", "Documents/foo.db"}});

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    const auto found = extractor.findPathsByFilename("foo.db", 10);
    EXPECT_EQ(found.size(), 2u);
    fs::remove_all(temp);
}

// ------------------------------------------------------------ time mapping

TEST(IosTimestampTest, ConvertsAppleNanoseconds) {
    // 715157772646219008 ns since 2001-01-01 == 2023-08-31T06:56:12Z
    EXPECT_EQ(ios_artifacts::toUnixSeconds(715157772646219008LL), 1693464972LL);
    EXPECT_EQ(ios_artifacts::classifyTimestamp(715157772646219008LL), "apple_epoch_ns");
}

TEST(IosTimestampTest, ConvertsAppleSeconds) {
    EXPECT_EQ(ios_artifacts::toUnixSeconds(715157772LL), 1693464972LL);
    EXPECT_EQ(ios_artifacts::classifyTimestamp(715157772LL), "apple_epoch_s");
}

TEST(IosTimestampTest, PassesThroughUnixSeconds) {
    EXPECT_EQ(ios_artifacts::toUnixSeconds(1693464972LL), 1693464972LL);
    EXPECT_EQ(ios_artifacts::classifyTimestamp(1693464972LL), "unix_s");
}

TEST(IosTimestampTest, ZeroStaysZero) {
    EXPECT_EQ(ios_artifacts::toUnixSeconds(0), 0LL);
    EXPECT_EQ(ios_artifacts::toUnixSeconds(-1), 0LL);
}

// -------------------------------------------------------------- end to end

TEST(IosArtifactParsersTest, ParsesSmsContactsNotesIntoAndroidDb) {
    const fs::path temp = fs::temp_directory_path() / "ios-parse-test";
    fs::remove_all(temp);

    const std::string smsId(40, 'e');
    const std::string contactsId(40, 'f');
    const std::string notesId(40, '1');

    const std::string smsDb = makeSourceDb(temp / "src" / "sms.db",
        "CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id TEXT);"
        "CREATE TABLE message(ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, "
        "  subject TEXT, handle_id INTEGER, date INTEGER, is_from_me INTEGER, "
        "  service TEXT, attributedBody BLOB);"
        "INSERT INTO handle VALUES(1,'+8613800138000');"
        "INSERT INTO message VALUES(1,'g1','hello from ios',NULL,1,715157772646219008,0,'SMS',NULL);"
        "INSERT INTO message VALUES(2,'g2','reply',NULL,1,715157780000000000,1,'iMessage',NULL);");

    const std::string contactsDb = makeSourceDb(temp / "src" / "ab.db",
        "CREATE TABLE ABPerson(ROWID INTEGER PRIMARY KEY, First TEXT, Last TEXT, "
        "  Middle TEXT, Organization TEXT, Nickname TEXT, JobTitle TEXT, Department TEXT);"
        "CREATE TABLE ABMultiValue(UID INTEGER PRIMARY KEY, record_id INTEGER, "
        "  property INTEGER, identifier TEXT, label TEXT, value TEXT, guid TEXT);"
        "INSERT INTO ABPerson VALUES(1,'Chit To Chris','LEE',NULL,NULL,NULL,NULL,NULL);"
        "INSERT INTO ABMultiValue VALUES(1,1,3,NULL,NULL,'+85212345678',NULL);");

    const std::string notesDb = makeSourceDb(temp / "src" / "notes.sqlite",
        "CREATE TABLE ZICCLOUDSYNCINGOBJECT(Z_PK INTEGER PRIMARY KEY, ZTITLE1 TEXT, "
        "  ZSNIPPET TEXT, ZIDENTIFIER TEXT);"
        "INSERT INTO ZICCLOUDSYNCINGOBJECT VALUES(1,'meeting','discuss case','id-1');");

    buildBackup(temp / "UDID", false, {
        {smsId, "HomeDomain", "Library/SMS/sms.db"},
        {contactsId, "HomeDomain", "Library/AddressBook/AddressBook.sqlitedb"},
        {notesId, "HomeDomain", "Library/Notes/notes.sqlite"},
    });
    addShard(temp / "UDID", smsId, smsDb);
    addShard(temp / "UDID", contactsId, contactsDb);
    addShard(temp / "UDID", notesId, notesDb);

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();

    AndroidAnalysisDatabase database((temp / "android.db").string());
    ASSERT_TRUE(database.initialize());

    const fs::path secureTemp = temp / "secure";
    fs::create_directories(secureTemp);
    ios_artifacts::IosParseResult parsed;
    {
        AndroidAnalysisDatabase database((temp / "android.db").string());
        ASSERT_TRUE(database.initialize());
        parsed = ios_artifacts::analyzeIosBackup(extractor, database, secureTemp.string());
        EXPECT_EQ(database.artifactRowCount("sms_messages"), 2);
        EXPECT_EQ(database.artifactRowCount("contacts"), 1);
    }

    EXPECT_EQ(parsed.sms, 2);
    EXPECT_EQ(parsed.contacts, 1);
    EXPECT_EQ(parsed.notes, 1);
    // artifactRowCount only whitelists the Android provider tables, so app_notes
    // is counted directly after the writer releases the file.
    EXPECT_EQ(countRows(temp / "android.db", "app_notes"), 1);

    fs::remove_all(temp);
}

TEST(IosArtifactParsersTest, SmsDateSecondsIsUnixNotAppleEpoch) {
    const fs::path temp = fs::temp_directory_path() / "ios-date-test";
    fs::remove_all(temp);
    const std::string smsId(40, '2');
    const std::string smsDb = makeSourceDb(temp / "src" / "sms.db",
        "CREATE TABLE handle(ROWID INTEGER PRIMARY KEY, id TEXT);"
        "CREATE TABLE message(ROWID INTEGER PRIMARY KEY, guid TEXT, text TEXT, "
        "  subject TEXT, handle_id INTEGER, date INTEGER, is_from_me INTEGER, "
        "  service TEXT, attributedBody BLOB);"
        "INSERT INTO handle VALUES(1,'+8613800138000');"
        "INSERT INTO message VALUES(1,'g1','x',NULL,1,715157772646219008,0,'SMS',NULL);");
    buildBackup(temp / "UDID", false, {{smsId, "HomeDomain", "Library/SMS/sms.db"}});
    addShard(temp / "UDID", smsId, smsDb);

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    AndroidAnalysisDatabase database((temp / "android.db").string());
    ASSERT_TRUE(database.initialize());
    const fs::path secureTemp = temp / "secure";
    fs::create_directories(secureTemp);
    ios_artifacts::analyzeIosBackup(extractor, database, secureTemp.string());

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((temp / "android.db").c_str(), &db), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db, "SELECT date_seconds, address, type FROM sms_messages",
                                 -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    // 2023-08-31T06:56:12Z, not the raw Apple nanosecond stamp.
    EXPECT_EQ(sqlite3_column_int64(statement, 0), 1693464972LL);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1)),
                 "+8613800138000");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 2)), "1");
    sqlite3_finalize(statement);
    sqlite3_close(db);
    fs::remove_all(temp);
}

TEST(IosArtifactParsersTest, MissingSourcesRecordCoverageNotSilence) {
    const fs::path temp = fs::temp_directory_path() / "ios-coverage-test";
    fs::remove_all(temp);
    buildBackup(temp / "UDID", false, {});

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    AndroidAnalysisDatabase database((temp / "android.db").string());
    ASSERT_TRUE(database.initialize());
    const fs::path secureTemp = temp / "secure";
    fs::create_directories(secureTemp);
    ios_artifacts::analyzeIosBackup(extractor, database, secureTemp.string());

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((temp / "android.db").c_str(), &db), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT COUNT(*) FROM android_source_coverage WHERE status='no_candidate_path'",
        -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_GT(sqlite3_column_int(statement, 0), 0);
    sqlite3_finalize(statement);
    sqlite3_close(db);
    fs::remove_all(temp);
}

TEST(IosArtifactParsersTest, InstalledAppsComeFromAppDomains) {
    const fs::path temp = fs::temp_directory_path() / "ios-apps-test";
    fs::remove_all(temp);
    buildBackup(temp / "UDID", false,
                {{std::string(40, '3'), "AppDomain-com.example.one", "Documents/a.txt"},
                 {std::string(40, '4'), "AppDomain-com.example.two", "Documents/b.txt"},
                 {std::string(40, '5'), "HomeDomain", "Library/SMS/sms.db"}});

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    ios_artifacts::IosParseResult parsed;
    {
        AndroidAnalysisDatabase database((temp / "android.db").string());
        ASSERT_TRUE(database.initialize());
        const fs::path secureTemp = temp / "secure";
        fs::create_directories(secureTemp);
        parsed = ios_artifacts::analyzeIosBackup(extractor, database, secureTemp.string());
        EXPECT_EQ(database.artifactRowCount("installed_packages"), 2);
    }

    EXPECT_EQ(parsed.installedApps, 2);
    fs::remove_all(temp);
}

// ------------------------------------------------- call history / safari

TEST(IosArtifactParsersTest, ParsesCallHistoryIntoCallLogs) {
    const fs::path temp = fs::temp_directory_path() / "ios-calls-test";
    fs::remove_all(temp);
    const std::string callsId(40, '6');
    const std::string callsDb = makeSourceDb(temp / "src" / "calls.storedata",
        "CREATE TABLE ZCALLRECORD(Z_PK INTEGER PRIMARY KEY, ZADDRESS TEXT, "
        "  ZDATE INTEGER, ZDURATION REAL, ZCALLTYPE INTEGER);"
        "INSERT INTO ZCALLRECORD VALUES(1,'+8613800138000',715157772,42.5,1);"
        "INSERT INTO ZCALLRECORD VALUES(2,'+85297248239',715160000,0.0,2);");

    buildBackup(temp / "UDID", false,
                {{callsId, "HomeDomain", "Library/CallHistoryDB/CallHistory.storedata"}});
    addShard(temp / "UDID", callsId, callsDb);

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    ios_artifacts::IosParseResult parsed;
    {
        AndroidAnalysisDatabase database((temp / "android.db").string());
        ASSERT_TRUE(database.initialize());
        const fs::path secureTemp = temp / "secure";
        fs::create_directories(secureTemp);
        parsed = ios_artifacts::analyzeIosBackup(extractor, database, secureTemp.string());
        EXPECT_EQ(database.artifactRowCount("call_logs"), 2);
    }
    EXPECT_EQ(parsed.callLogs, 2);

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((temp / "android.db").c_str(), &db), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT number, date_seconds, duration, type FROM call_logs ORDER BY date_seconds",
        -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)),
                 "+8613800138000");
    // Apple-epoch seconds in, Unix seconds out.
    EXPECT_EQ(sqlite3_column_int64(statement, 1), 715157772LL + 978307200LL);
    EXPECT_EQ(sqlite3_column_int(statement, 2), 42);
    EXPECT_EQ(sqlite3_column_int(statement, 3), 1);
    sqlite3_finalize(statement);
    sqlite3_close(db);
    fs::remove_all(temp);
}

TEST(IosArtifactParsersTest, ParsesSafariHistoryIntoChromeHistory) {
    const fs::path temp = fs::temp_directory_path() / "ios-safari-test";
    fs::remove_all(temp);
    const std::string historyId(40, '7');
    const std::string historyDb = makeSourceDb(temp / "src" / "History.db",
        "CREATE TABLE history_items(id INTEGER PRIMARY KEY, url TEXT, title TEXT);"
        "CREATE TABLE history_visits(id INTEGER PRIMARY KEY, history_item INTEGER, "
        "  visit_time REAL);"
        "INSERT INTO history_items VALUES(1,'https://example.test/a','Example A');"
        "INSERT INTO history_items VALUES(2,'https://example.test/b','Example B');"
        "INSERT INTO history_visits VALUES(1,1,715157772);"
        "INSERT INTO history_visits VALUES(2,1,715160000);"
        "INSERT INTO history_visits VALUES(3,2,715170000);");

    buildBackup(temp / "UDID", false,
                {{historyId, "HomeDomain", "Library/Safari/History.db"}});
    addShard(temp / "UDID", historyId, historyDb);

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    ios_artifacts::IosParseResult parsed;
    {
        AndroidAnalysisDatabase database((temp / "android.db").string());
        ASSERT_TRUE(database.initialize());
        const fs::path secureTemp = temp / "secure";
        fs::create_directories(secureTemp);
        parsed = ios_artifacts::analyzeIosBackup(extractor, database, secureTemp.string());
    }
    EXPECT_EQ(parsed.safariHistory, 2);
    // artifactRowCount only whitelists the Android provider tables.
    EXPECT_EQ(countRows(temp / "android.db", "chrome_history"), 2);

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((temp / "android.db").c_str(), &db), SQLITE_OK);
    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(db,
        "SELECT url, title, visit_count, last_visit_time FROM chrome_history "
        "WHERE url = 'https://example.test/a'", -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)),
                 "https://example.test/a");
    EXPECT_EQ(sqlite3_column_int(statement, 2), 2);  // two visits
    EXPECT_EQ(sqlite3_column_int64(statement, 3), 715160000LL + 978307200LL);
    sqlite3_finalize(statement);
    sqlite3_close(db);
    fs::remove_all(temp);
}

TEST(IosArtifactParsersTest, MissingCallHistoryAndSafariRecordCoverage) {
    const fs::path temp = fs::temp_directory_path() / "ios-no-calls-test";
    fs::remove_all(temp);
    buildBackup(temp / "UDID", false, {});

    IosBackupExtractor extractor((temp / "UDID").string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();
    {
        AndroidAnalysisDatabase database((temp / "android.db").string());
        ASSERT_TRUE(database.initialize());
        const fs::path secureTemp = temp / "secure";
        fs::create_directories(secureTemp);
        ios_artifacts::analyzeIosBackup(extractor, database, secureTemp.string());
    }

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open((temp / "android.db").c_str(), &db), SQLITE_OK);
    for (const char* kind : {"call_logs", "safari"}) {
        sqlite3_stmt* statement = nullptr;
        ASSERT_EQ(sqlite3_prepare_v2(db,
            "SELECT status FROM android_source_coverage WHERE artifact_kind = ?",
            -1, &statement, nullptr), SQLITE_OK);
        sqlite3_bind_text(statement, 1, kind, -1, SQLITE_TRANSIENT);
        ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
        EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)),
                     "no_candidate_path");
        sqlite3_finalize(statement);
    }
    sqlite3_close(db);
    fs::remove_all(temp);
}
