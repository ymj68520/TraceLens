// test_mobile_evidence_package_gtest.cpp
// 统一取数格式（.mep.db）的端到端测试：MIUI 备份 → 取数包 → 分析库。
//
// 覆盖点：
//  1. Writer/Reader 往返：设备、采集、记录、文件、覆盖度全部保真。
//  2. 重复写入幂等。
//  3. 非本格式的 SQLite 被拒绝。
//  4. MIUI 适配器把真实 protobuf 载荷翻译成统一记录。
//  5. 分析阶段只读统一包即可还原短信/联系人/通话/笔记。
//  6. 未产出的类别在 coverage 中显式声明，不会被读成"设备没有"。

#include <gtest/gtest.h>

#include <sqlite3.h>

#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <string>
#include <vector>

#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include "analyzers/AndroidAnalyzer/MiuiBackupExtractor.h"
#include "analyzers/AndroidAnalyzer/MobileEvidenceAnalysis.h"
#include "analyzers/AndroidAnalyzer/MobileEvidenceMiuiAdapter.h"
#include "analyzers/AndroidAnalyzer/MobileEvidencePackage.h"

namespace fs = std::filesystem;

namespace {

std::atomic_uint64_t serial{0};

fs::path uniqueTempPath(const std::string& stem, const std::string& extension = {}) {
    const auto timestamp = std::chrono::steady_clock::now().time_since_epoch().count();
    return fs::temp_directory_path() /
        (stem + "_" + std::to_string(timestamp) + "_" +
         std::to_string(serial.fetch_add(1, std::memory_order_relaxed)) + extension);
}

class TempDir {
public:
    TempDir() : path_(uniqueTempPath("mep_test")) { fs::create_directories(path_); }
    ~TempDir() { std::error_code error; fs::remove_all(path_, error); }
    const fs::path& path() const { return path_; }
    fs::path operator/(const std::string& name) const { return path_ / name; }

private:
    fs::path path_;
};

// ---- 真实 MIUI protobuf 载荷（与 test_miui_proto_bak_gtest 同源） ----

const char kCallLogBak[] =
    "\x12\xa4\x01\x0a\x17\x12\x01\x36\x1a\x05\x31\x32\x33\x31\x35\x20"
    "\x84\xe1\xa4\xa7\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x17\x12\x01"
    "\x35\x1a\x05\x31\x32\x33\x30\x35\x20\x87\xb5\xa4\xa7\xfe\x33\x28"
    "\x00\x30\x02\x38\x01\x0a\x19\x12\x01\x34\x1a\x07\x31\x30\x30\x38"
    "\x36\x31\x31\x20\xc6\xeb\xa3\xa7\xfe\x33\x28\x00\x30\x02\x38\x01"
    "\x0a\x17\x12\x01\x33\x1a\x05\x31\x30\x30\x38\x36\x20\xb7\xc4\xa3"
    "\xa7\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x1d\x12\x01\x32\x1a\x0b"
    "\x31\x38\x38\x37\x39\x35\x30\x30\x37\x39\x34\x20\x8c\xfc\xa2\xa7"
    "\xfe\x33\x28\x00\x30\x02\x38\x01\x0a\x1d\x12\x01\x31\x1a\x0b\x31"
    "\x35\x38\x30\x39\x36\x34\x39\x38\x30\x34\x20\xb1\x8f\xa2\xa7\xfe"
    "\x33\x28\x00\x30\x02\x38\x01";

const char kContactsBak[] =
    "\x0a\x64\x12\x30\x12\x01\x31\x2a\x18\x0a\x09\xe5\x86\xb6\xe6\xa2"
    "\xa6\xe6\x9d\xb0\x12\x06\xe6\xa2\xa6\xe6\x9d\xb0\x22\x03\xe5\x86"
    "\xb6\x32\x11\x0a\x0d\x31\x35\x38\x20\x30\x39\x36\x34\x20\x39\x38"
    "\x30\x34\x10\x02\x12\x30\x12\x01\x32\x2a\x18\x0a\x09\xe6\x9d\x8e"
    "\xe5\xb0\x89\xe8\x81\xaa\x12\x06\xe5\xb0\x89\xe8\x81\xaa\x22\x03"
    "\xe6\x9d\x8e\x32\x11\x0a\x0d\x31\x38\x38\x20\x37\x39\x35\x30\x20"
    "\x30\x37\x39\x34\x10\x02";

const char kSmsBak[] =
    "\x22\xba\x02\x0a\x69\x12\x02\x35\x37\x18\x01\x22\x0c\x31\x30\x36"
    "\x39\x35\x33\x36\x32\x38\x39\x35\x34\x32\x34\xef\xbc\xbb\xe7\x88"
    "\xb1\xe8\x81\x8a\xef\xbc\xbd\xe6\x82\xa8\xe6\x89\x8b\xe6\x9c\xba"
    "\xe5\xb0\xbe\xe5\x8f\xb7\x31\x38\x36\x33\xe7\x9a\x84\xe9\xaa\x8c"
    "\xe8\xaf\x81\xe7\xa0\x81\xe6\x98\xaf\x35\x36\x38\x32\x35\x34\x38"
    "\xce\xf1\xad\xd1\x9b\x31\x40\x01\x48\x01\x50\xff\xff\xff\xff\xff"
    "\xff\xff\xff\xff\x01\x58\x00\x68\x00\x78\x00\x88\x01\x00\x0a\xcc"
    "\x01\x12\x01\x31\x18\x01\x22\x0a\x31\x30\x36\x35\x35\x35\x32\x36"
    "\x31\x31\x32\x9b\x01\xe4\xb8\xad\xe5\x9b\xbd\xe8\x81\x94\xe9\x80"
    "\x9a\xe6\xb8\xa9\xe9\xa6\xa8\xe6\x8f\x90\xe9\x86\x92\xef\xbc\x9a"
    "\xe6\x82\xa8\xe5\x88\x9a\xe6\x89\x8d\xe6\x8e\xa5\xe5\x90\xac\xe7"
    "\x9a\x84\xe7\x94\xb5\xe8\xaf\x9d\x30\x30\x31\x38\x33\x32\x35\x36"
    "\x34\x33\x31\x39\x39\xe4\xb8\xba\xe5\xa2\x83\xe5\xa4\x96\xe6\x9d"
    "\xa5\xe7\x94\xb5\xef\xbc\x8c\xe8\xaf\xb7\xe6\xb3\xa8\xe6\x84\x8f"
    "\xe8\xbe\xa8\xe5\x88\xab\xef\xbc\x8c\xe9\x98\xb2\xe8\x8c\x83\xe9"
    "\xa3\x8e\xe9\x99\xa9\xe3\x80\x82\xe5\x8f\x96\xe6\xb6\x88\xe8\xaf"
    "\xa5\xe7\x9f\xad\xe4\xbf\xa1\xe6\x8f\x90\xe9\x86\x92\xe8\xaf\xb7"
    "\xe5\x9b\x9e\xe5\xa4\x8d\xe2\x80\x9c\x39\xe2\x80\x9d\xe3\x80\x82"
    "\x38\x98\xf9\xfb\xc4\xb0\x31\x40\x01\x48\x01\x50\xff\xff\xff\xff"
    "\xff\xff\xff\xff\xff\x01\x58\x00\x78\x00\x88\x01\x00";

// Binary protobuf payloads contain NUL bytes, so the size must come from the
// array extent: a strlen-based std::string(const char*) truncates at the first
// zero and silently drops most records.
template <std::size_t N>
std::string fixture(const char (&data)[N]) {
    return std::string(data, N - 1);
}

// ---- ustar 构造（与既有 MIUI 测试同款） ----

std::string makeUstarTar(const std::vector<std::pair<std::string, std::string>>& files) {
    std::string tar;
    for (const auto& [name, content] : files) {
        std::string block(512, '\0');
        std::memcpy(block.data(), name.data(), std::min(name.size(), static_cast<size_t>(100)));
        char buffer[16];
        auto toOct = [&](size_t value, int width) {
            std::snprintf(buffer, sizeof(buffer), "%0*lo", width - 1, value);
            std::string text(buffer);
            text.push_back('\0');
            text.push_back(' ');
            return text;
        };
        std::memcpy(block.data() + 124, toOct(content.size(), 12).data(), 12);
        std::memcpy(block.data() + 136, toOct(0, 12).data(), 12);
        block[156] = '0';
        std::memcpy(block.data() + 257, "ustar", 5);
        std::memset(block.data() + 148, ' ', 8);
        unsigned sum = 0;
        for (unsigned char c : block) sum += c;
        std::snprintf(buffer, sizeof(buffer), "%06o", sum);
        std::memcpy(block.data() + 148, buffer, 6);
        block[154] = '\0';
        block[155] = ' ';
        tar += block;
        std::string data = content;
        data.append((512 - data.size() % 512) % 512, '\0');
        tar += data;
    }
    tar.append(1024, '\0');
    return tar;
}

// 构造一个最小 MIUI 备份目录：descript.xml + 若干 .bak。
fs::path buildMiuiBackup(const fs::path& dir) {
    fs::create_directories(dir);
    const char* xml =
        "<?xml version='1.0' encoding='UTF-8' ?><MIUI-backup>"
        "<device>cepheus</device><miuiVersion>V12.5.6.0.RFACNXM</miuiVersion>"
        "<date>1785299538978</date><size>4122640883</size><packages>"
        "<package><packageName>com.android.contacts</packageName>"
        "<bakFile>联系人(com.android.contacts).bak</bakFile><bakType>1</bakType>"
        "<pkgSize>1024</pkgSize><sdSize>0</sdSize><state>1</state><error>0</error></package>"
        "<package><packageName>com.android.contacts</packageName>"
        "<bakFile>通话记录(com.android.contacts).bak</bakFile><bakType>1</bakType>"
        "<pkgSize>1024</pkgSize><sdSize>0</sdSize><state>1</state><error>0</error></package>"
        "<package><packageName>com.android.mms</packageName>"
        "<bakFile>短信(com.android.mms).bak</bakFile><bakType>1</bakType>"
        "<pkgSize>1024</pkgSize><sdSize>0</sdSize><state>1</state><error>0</error></package>"
        "</packages></MIUI-backup>";
    std::ofstream(dir / "descript.xml", std::ios::binary) << xml;

    auto writeBak = [&](const std::string& name, const std::string& packageName,
                        const std::string& payload) {
        // Member names are namespaced by package, so each .bak must carry its
        // own apps/<pkg>/miui_bak/_tmp_bak member to exercise the right branch.
        const std::string member = "apps/" + packageName + "/miui_bak/_tmp_bak";
        const std::string tar = makeUstarTar({{member, payload}});
        std::ofstream(dir / name, std::ios::binary)
            << "ANDROID BACKUP\n5\n0\nnone\n" << tar;
    };
    writeBak("联系人(com.android.contacts).bak", "com.android.contacts",
             fixture(kContactsBak));
    writeBak("通话记录(com.android.contacts).bak", "com.android.contacts",
             fixture(kCallLogBak));
    writeBak("短信(com.android.mms).bak", "com.android.mms", fixture(kSmsBak));

    return dir;
}

}  // namespace

// ---------------------------------------------------------------------------
// Writer / Reader 往返
// ---------------------------------------------------------------------------

TEST(MobileEvidencePackageTest, RoundTripsAllSections) {
    TempDir temp;
    const std::string packagePath = (temp / "pkg.mep.db").string();

    mobile_evidence::Package package;
    package.device.platform = "android";
    package.device.model = "M2102K1C";
    package.device.imei = "357323092152102";
    package.acquisition.adapterName = "miui-backup";
    package.acquisition.adapterVersion = "1.0";
    package.acquisition.sourceType = "directory";

    mobile_evidence::Record record;
    record.kind = mobile_evidence::kind::kSms;
    record.packageName = "com.android.mms";
    record.sourcePath = "apps/com.android.mms/miui_bak/_tmp_bak";
    record.sourceTable = "sms";
    record.sourceKey = "10086|1786251915396";
    record.rawJson = R"({"address":"10086","body":"hello","date":1786251915396})";
    record.payloadJson = R"({"address":"10086","body":"hello","type":1})";
    record.timestampRaw = "1786251915396";
    record.timestampUnit = mobile_evidence::time_unit::kMilliseconds;
    record.timestampSeconds = 1786251915;
    record.parserVersion = "1.0";
    package.records.push_back(record);

    mobile_evidence::FileEntry file;
    file.relativePath = "DCIM/Camera/x.jpg";
    file.fileName = "x.jpg";
    file.extension = "jpg";
    file.category = "image";
    file.size = 1234;
    package.files.push_back(file);

    mobile_evidence::Coverage coverage;
    coverage.artifactKind = mobile_evidence::kind::kSms;
    coverage.sourcePath = "apps/com.android.mms/miui_bak/_tmp_bak";
    coverage.status = mobile_evidence::status::kParsed;
    coverage.detail = "ok";
    coverage.recordCount = 1;
    package.coverage.push_back(coverage);

    {
        mobile_evidence::Writer writer(packagePath);
        ASSERT_TRUE(writer.writePackage(package)) << writer.error();
        writer.close();
    }

    mobile_evidence::Reader reader(packagePath);
    ASSERT_TRUE(reader.open()) << reader.error();
    EXPECT_EQ(reader.schemaVersion(), mobile_evidence::kSchemaVersion);

    mobile_evidence::DeviceInfo device;
    ASSERT_TRUE(reader.readDevice(device));
    EXPECT_EQ(device.platform, "android");
    EXPECT_EQ(device.model, "M2102K1C");
    EXPECT_EQ(device.imei, "357323092152102");

    mobile_evidence::AcquisitionInfo acquisition;
    ASSERT_TRUE(reader.readAcquisition(acquisition));
    EXPECT_EQ(acquisition.adapterName, "miui-backup");

    const auto records = reader.readRecords();
    ASSERT_EQ(records.size(), 1u);
    EXPECT_EQ(records[0].kind, mobile_evidence::kind::kSms);
    EXPECT_EQ(records[0].sourceKey, "10086|1786251915396");
    EXPECT_EQ(records[0].timestampSeconds, 1786251915);
    // 原始行必须完整保留，不能只剩规范化投影。
    EXPECT_NE(records[0].rawJson.find("hello"), std::string::npos);

    EXPECT_EQ(reader.readFiles().size(), 1u);
    EXPECT_EQ(reader.readCoverage().size(), 1u);

    const auto counts = reader.recordCountsByKind();
    ASSERT_EQ(counts.count(mobile_evidence::kind::kSms), 1u);
    EXPECT_EQ(counts.at(mobile_evidence::kind::kSms), 1u);
}

TEST(MobileEvidencePackageTest, RewritingIsIdempotent) {
    TempDir temp;
    const std::string packagePath = (temp / "pkg.mep.db").string();

    mobile_evidence::Package package;
    package.acquisition.adapterName = "test";
    mobile_evidence::Record record;
    record.kind = mobile_evidence::kind::kContact;
    record.sourceKey = "zhang|13800000000";
    package.records.push_back(record);

    mobile_evidence::Writer writer(packagePath);
    ASSERT_TRUE(writer.writePackage(package));
    ASSERT_TRUE(writer.writePackage(package));  // 第二次不应累加
    writer.close();

    mobile_evidence::Reader reader(packagePath);
    ASSERT_TRUE(reader.open());
    EXPECT_EQ(reader.readRecords().size(), 1u);
}

TEST(MobileEvidencePackageTest, RejectsForeignKeylessDatabase) {
    TempDir temp;
    const std::string otherPath = (temp / "other.db").string();
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(otherPath.c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db, "CREATE TABLE t(x);", nullptr, nullptr, nullptr), SQLITE_OK);
    sqlite3_close(db);

    EXPECT_FALSE(mobile_evidence::looksLikePackage(otherPath));
    mobile_evidence::Reader reader(otherPath);
    EXPECT_FALSE(reader.open());
}

// ---------------------------------------------------------------------------
// MIUI 适配器 + 分析阶段
// ---------------------------------------------------------------------------

TEST(MobileEvidenceMiuiTest, AdapterProducesUnifiedRecords) {
    TempDir temp;
    const fs::path backupDir = buildMiuiBackup(temp / "backup");

    MiuiBackupExtractor extractor(backupDir.string());
    ASSERT_TRUE(extractor.initialize());

    mobile_evidence::MiuiAdapterOptions options;
    mobile_evidence::Package package;
    ASSERT_TRUE(mobile_evidence::buildPackageFromMiui(extractor, options, package));

    std::map<std::string, std::size_t> byKind;
    for (const auto& record : package.records) byKind[record.kind]++;
    EXPECT_EQ(byKind[mobile_evidence::kind::kContact], 2u);
    EXPECT_EQ(byKind[mobile_evidence::kind::kCallLog], 6u);
    EXPECT_EQ(byKind[mobile_evidence::kind::kSms], 2u);
    // 清单里的三个包都应有 installed_app 行。
    EXPECT_GE(byKind[mobile_evidence::kind::kInstalledApp], 3u);

    // 号码被规范化（MIUI 用分组空格渲染）。
    bool sawPlainNumber = false;
    for (const auto& record : package.records) {
        if (record.kind != mobile_evidence::kind::kContact) continue;
        if (record.payloadJson.find("15809649804") != std::string::npos) sawPlainNumber = true;
    }
    EXPECT_TRUE(sawPlainNumber);
}

TEST(MobileEvidenceMiuiTest, AnalysisStageRebuildsArtifactsFromPackageAlone) {
    TempDir temp;
    const fs::path backupDir = buildMiuiBackup(temp / "backup");
    const std::string packagePath = (temp / "case.mep.db").string();

    // ---- 取数阶段 ----
    {
        MiuiBackupExtractor extractor(backupDir.string());
        ASSERT_TRUE(extractor.initialize());
        mobile_evidence::Package package;
        ASSERT_TRUE(mobile_evidence::buildPackageFromMiui(extractor, {}, package));

        mobile_evidence::Writer writer(packagePath);
        ASSERT_TRUE(writer.writePackage(package)) << writer.error();
        writer.close();
    }

    // ---- 分析阶段：完全不接触原始备份 ----
    const std::string androidDbPath = (temp / "android.db").string();
    {
        AndroidAnalysisDatabase database(androidDbPath);
        ASSERT_TRUE(database.initialize());

        mobile_evidence::AnalysisOptions options;
        mobile_evidence::AnalysisResult result;
        ASSERT_TRUE(mobile_evidence::analyzePackage(packagePath, database, options, result));

        EXPECT_EQ(result.contacts, 2u);
        EXPECT_EQ(result.callLogs, 6u);
        EXPECT_EQ(result.sms, 2u);
        EXPECT_GE(result.installedApps, 3u);
        EXPECT_GT(result.coverageEntries, 0u);

        EXPECT_EQ(database.artifactRowCount("contacts"), 2);
        EXPECT_EQ(database.artifactRowCount("sms_messages"), 2);
        // artifactRowCount only whitelists a few tables, so count call_logs directly.
        sqlite3_stmt* statement = nullptr;
        ASSERT_EQ(sqlite3_prepare_v2(database.handle(), "SELECT COUNT(*) FROM call_logs",
                                     -1, &statement, nullptr), SQLITE_OK);
        ASSERT_EQ(sqlite3_step(statement), SQLITE_ROW);
        EXPECT_EQ(sqlite3_column_int(statement, 0), 6);
        sqlite3_finalize(statement);
    }
}

TEST(MobileEvidenceMiuiTest, CoverageDeclaresAbsentKindsInsteadOfSilence) {
    TempDir temp;
    const fs::path backupDir = buildMiuiBackup(temp / "backup");

    MiuiBackupExtractor extractor(backupDir.string());
    ASSERT_TRUE(extractor.initialize());
    mobile_evidence::Package package;
    ASSERT_TRUE(mobile_evidence::buildPackageFromMiui(extractor, {}, package));

    // 该样本没有笔记，适配器必须显式声明，而不是让下游读到空表就下结论。
    bool declared = false;
    for (const auto& entry : package.coverage) {
        if (entry.artifactKind == mobile_evidence::kind::kNote &&
            entry.status == "no_candidate_path") {
            declared = true;
        }
    }
    EXPECT_TRUE(declared);
}
