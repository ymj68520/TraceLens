// test_mobile_evidence_adapters_gtest.cpp
// 鸿蒙适配器的取数/分析分离契约测试。
//
// 覆盖点：
//  1. 适配器产出统一包：模块清单、数据库表盘点、mobile_backup_manifest。
//  2. 分析阶段仅凭包即可重建 mobile_artifacts / installed_apps /
//     app_db_inventory / mobile_backup_manifest，且保留原生 kind 名。
//  3. harmony 的 NOT_PRESENT 覆盖声明不丢，也不被改写成"设备没有"。

#include <gtest/gtest.h>
#include <sqlite3.h>

#include <archive.h>
#include <archive_entry.h>

#include <atomic>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include "analyzers/AndroidAnalyzer/HarmonyBackupExtractor.h"
#include "analyzers/AndroidAnalyzer/MobileEvidenceAnalysis.h"
#include "analyzers/AndroidAnalyzer/MobileEvidenceHarmonyAdapter.h"
#include "analyzers/AndroidAnalyzer/MobileEvidencePackage.h"

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {

std::atomic_uint64_t serial{0};

class TempDir {
public:
    TempDir() {
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        path_ = fs::temp_directory_path() /
            ("mep_adapter_" + std::to_string(stamp) + "_" +
             std::to_string(serial.fetch_add(1, std::memory_order_relaxed)));
        fs::create_directories(path_);
    }
    ~TempDir() {
        std::error_code error;
        fs::remove_all(path_, error);
    }
    const fs::path& path() const { return path_; }
    fs::path operator/(const std::string& name) const { return path_ / name; }

private:
    fs::path path_;
};

void writeFile(const fs::path& path, const std::string& bytes) {
    std::ofstream out(path, std::ios::binary);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

// Minimal decrypted-HarmonyOS backup: .info.json + one module archive.
class HarmonyFixture {
public:
    explicit HarmonyFixture(const fs::path& root) : root_(root) {
        app_ = root_ / "files/BASIC/com.huawei.hmos.calendardata";
        fs::create_directories(app_);
        writeFile(root_ / ".info.json", json({
            {"BackupFileHeaderInfo", {{"deviceModel", "fixture"}, {"backupTime", 1700000000000LL}}},
            {"BackupFileModuleInfo", json::array({
                {{"moduleName", "com.huawei.hmos.calendardata"},
                 {"appIndex", 0}, {"appName", "Calendar"}}})}}).dump());
    }

    void archive(const std::vector<std::pair<std::string, std::string>>& entries) {
        auto* writer = archive_write_new();
        archive_write_set_format_gnutar(writer);
        archive_write_open_filename(writer, (app_ / "part.0.tarx").c_str());
        for (const auto& [name, bytes] : entries) {
            auto* entry = archive_entry_new();
            archive_entry_set_pathname(entry, name.c_str());
            archive_entry_set_filetype(entry, AE_IFREG);
            archive_entry_set_perm(entry, 0600);
            archive_entry_set_size(entry, static_cast<int64_t>(bytes.size()));
            archive_entry_set_mtime(entry, 1700000000, 0);
            archive_write_header(writer, entry);
            archive_write_data(writer, bytes.data(), bytes.size());
            archive_entry_free(entry);
        }
        archive_write_close(writer);
        archive_write_free(writer);
        writeFile(app_ / "manage.jsonx", json::array({
            {{"fileName", "part.0.tar"}, {"isBigFile", false},
             {"information", {{"path", "/data/storage/el2/base/.backup/part.0.tar"},
                              {"stat", {{"st_size", fs::file_size(app_ / "part.0.tarx")}}}}}}}).dump());
    }

    const fs::path& root() const { return root_; }

private:
    fs::path root_;
    fs::path app_;
};

std::string calendarDatabaseBytes() {
    const fs::path path = fs::temp_directory_path() /
        ("mep_cal_" + std::to_string(serial.fetch_add(1, std::memory_order_relaxed)) + ".db");
    sqlite3* db = nullptr;
    sqlite3_open(path.c_str(), &db);
    sqlite3_exec(db,
        "CREATE TABLE Events(_id INTEGER PRIMARY KEY,title TEXT,dtstart INTEGER);"
        "INSERT INTO Events VALUES(7,'test event',1700000000000);",
        nullptr, nullptr, nullptr);
    sqlite3_close(db);
    std::ifstream in(path, std::ios::binary);
    std::string bytes((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    std::error_code error;
    fs::remove(path, error);
    return bytes;
}

}  // namespace

TEST(MobileEvidenceHarmonyTest, ExtractionProducesPackageWithManifestAndInventory) {
    TempDir temp;
    HarmonyFixture fixture(temp / "evidence");
    fixture.archive({{"/data/storage/el2/database/entry/rdb/calendardata.db",
                      calendarDatabaseBytes()}});

    HarmonyBackupExtractor source(fixture.root().string());
    ASSERT_TRUE(source.initialize()) << source.error();

    mobile_evidence::Package package;
    mobile_evidence::HarmonyAdapterOptions options;
    ASSERT_TRUE(mobile_evidence::buildPackageFromHarmony(source, temp.path(), options, package));

    // 包必须自带清单与平台信息，分析层不再读源。
    EXPECT_TRUE(package.manifest.present);
    EXPECT_EQ(package.manifest.targetTable, "mobile_backup_manifest");
    EXPECT_EQ(package.manifest.platform, "HarmonyOS");
    EXPECT_EQ(package.device.platform, "harmonyos");

    std::size_t installed = 0, tables = 0, artifacts = 0;
    for (const auto& record : package.records) {
        if (record.kind == mobile_evidence::kind::kInstalledApp) ++installed;
        if (record.kind == mobile_evidence::kind::kDatabaseTable) ++tables;
        if (record.mobileArtifact) {
            ++artifacts;
            // 原生 kind 名必须保留，否则下游 artifact reader 契约会变。
            EXPECT_EQ(record.nativeKind, "calendar");
        }
    }
    EXPECT_EQ(installed, 1u);
    EXPECT_GE(tables, 1u);   // Events 表盘点
    EXPECT_EQ(artifacts, 1u);  // 一条日历事件

    // 缺失类别必须显式声明。
    bool declaredAbsent = false;
    for (const auto& entry : package.coverage) {
        if (entry.artifactKind == "sms" && entry.status == "NOT_PRESENT") declaredAbsent = true;
    }
    EXPECT_TRUE(declaredAbsent);
}

TEST(MobileEvidenceHarmonyTest, AnalysisRebuildsAndroidDbFromPackageAlone) {
    TempDir temp;
    HarmonyFixture fixture(temp / "evidence");
    fixture.archive({{"/data/storage/el2/database/entry/rdb/calendardata.db",
                      calendarDatabaseBytes()}});

    mobile_evidence::Package package;
    {
        HarmonyBackupExtractor source(fixture.root().string());
        ASSERT_TRUE(source.initialize()) << source.error();
        mobile_evidence::HarmonyAdapterOptions options;
        ASSERT_TRUE(mobile_evidence::buildPackageFromHarmony(source, temp.path(), options, package));
    }

    // 移走原始检材：分析阶段此后只能依赖包。
    std::error_code error;
    fs::rename(fixture.root(), temp / "evidence_hidden", error);
    ASSERT_FALSE(error) << "fixture must be moved away";

    AndroidAnalysisDatabase database((temp / "android.db").string());
    ASSERT_TRUE(database.initialize());

    mobile_evidence::AnalysisOptions analysisOptions;
    analysisOptions.mirrorFiles = false;
    mobile_evidence::AnalysisResult result;
    ASSERT_TRUE(mobile_evidence::analyzePackage(package, database, analysisOptions, result));

    EXPECT_EQ(result.mobileArtifacts, 1u);
    EXPECT_EQ(result.installedApps, 1u);

    sqlite3_stmt* statement = nullptr;
    ASSERT_EQ(sqlite3_prepare_v2(database.handle(),
        "SELECT kind, timestamp_seconds FROM mobile_artifacts", -1, &statement, nullptr),
        SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "calendar");
    EXPECT_EQ(sqlite3_column_int64(statement, 1), 1700000000);
    EXPECT_EQ(sqlite3_step(statement), SQLITE_DONE);
    sqlite3_finalize(statement);

    ASSERT_EQ(sqlite3_prepare_v2(database.handle(),
        "SELECT platform, device, module_count FROM mobile_backup_manifest",
        -1, &statement, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 0)), "HarmonyOS");
    EXPECT_STREQ(reinterpret_cast<const char*>(sqlite3_column_text(statement, 1)), "fixture");
    EXPECT_EQ(sqlite3_column_int64(statement, 2), 1);
    sqlite3_finalize(statement);
}

TEST(MobileEvidencePackageTest, CoverageKeepsNativeStatus) {
    TempDir temp;
    const std::string packagePath = (temp / "cov.mep.db").string();

    mobile_evidence::Package package;
    package.acquisition.adapterName = "thunder-backup";
    mobile_evidence::Coverage coverage;
    coverage.artifactKind = "note_archive";
    coverage.sourcePath = "note.zip";
    coverage.status = mobile_evidence::status::kLocked;   // 归一化
    coverage.nativeStatus = "LOCKED";                    // 厂商原生词
    coverage.detail = "content_not_decrypted";
    package.coverage.push_back(coverage);

    {
        mobile_evidence::Writer writer(packagePath);
        ASSERT_TRUE(writer.writePackage(package)) << writer.error();
        writer.close();
    }

    mobile_evidence::Reader reader(packagePath);
    ASSERT_TRUE(reader.open()) << reader.error();
    const auto loaded = reader.readCoverage();
    ASSERT_EQ(loaded.size(), 1u);
    EXPECT_EQ(loaded[0].status, mobile_evidence::status::kLocked);
    EXPECT_EQ(loaded[0].nativeStatus, "LOCKED");
}

TEST(MobileEvidencePackageTest, RoundTripsNativeKindAndMobileArtifactFlag) {
    TempDir temp;
    const std::string packagePath = (temp / "native.mep.db").string();

    mobile_evidence::Package package;
    package.acquisition.adapterName = "test";
    mobile_evidence::Record record;
    record.kind = mobile_evidence::kind::kGeneric;
    record.nativeKind = "app_data_container";
    record.mobileArtifact = true;
    record.sourceKey = "container";
    record.rawJson = R"({"a":1})";
    package.records.push_back(record);

    {
        mobile_evidence::Writer writer(packagePath);
        ASSERT_TRUE(writer.writePackage(package)) << writer.error();
        writer.close();
    }

    mobile_evidence::Reader reader(packagePath);
    ASSERT_TRUE(reader.open());
    const auto records = reader.readRecords();
    ASSERT_EQ(records.size(), 1u);
    EXPECT_EQ(records[0].nativeKind, "app_data_container");
    EXPECT_TRUE(records[0].mobileArtifact);
}
