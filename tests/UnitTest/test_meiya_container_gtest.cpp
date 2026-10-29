// test_meiya_container_gtest.cpp
// 美亚容器掩码自推导与统一包适配的单元测试。
//
// 测试用**合成**容器：先生成合法 SQLite，再用任意掩码 XOR。因此本测试不
// 携带任何厂商密钥，也不依赖真实检材；它验证的是"能否从数据自身推出掩码"
// 这一机制本身。

#include <gtest/gtest.h>

#include <sqlite3.h>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <memory>
#include <random>
#include <string>
#include <vector>

#include "analyzers/AndroidAnalyzer/AndroidAnalysisDatabase.h"
#include "analyzers/AndroidAnalyzer/MeiyaBackupExtractor.h"
#include "analyzers/AndroidAnalyzer/MeiyaContainerCrypto.h"
#include "analyzers/AndroidAnalyzer/MobileEvidenceAnalysis.h"
#include "analyzers/AndroidAnalyzer/MobileEvidenceMeiyaAdapter.h"
#include "analyzers/AndroidAnalyzer/MobileEvidencePackage.h"

#include <nlohmann/json.hpp>

namespace fs = std::filesystem;
using json = nlohmann::json;

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
    TempDir() : path_(uniqueTempPath("meiya_test")) { fs::create_directories(path_); }
    ~TempDir() { std::error_code error; fs::remove_all(path_, error); }
    const fs::path& path() const { return path_; }
    fs::path operator/(const std::string& name) const { return path_ / name; }

private:
    fs::path path_;
};

std::vector<unsigned char> readAll(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    return std::vector<unsigned char>((std::istreambuf_iterator<char>(input)),
                                      std::istreambuf_iterator<char>());
}

void writeAll(const fs::path& path, const std::vector<unsigned char>& bytes) {
    std::ofstream output(path, std::ios::binary | std::ios::trunc);
    output.write(reinterpret_cast<const char*>(bytes.data()),
                 static_cast<std::streamsize>(bytes.size()));
}

// 生成一个页大小 1024 的合法 SQLite 库。
// 关键：写入后再删除一张表，使文件中留下真正的全零空闲页——真实美亚容器
// 正是靠这类空页泄露掩码，测试必须复现同样的条件，否则验证的是不存在的假设。
void buildSqlite(const fs::path& path, int tables = 3) {
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(path.c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db, "PRAGMA page_size=1024;", nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db, "PRAGMA journal_mode=DELETE;", nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db, "PRAGMA auto_vacuum=NONE;", nullptr, nullptr, nullptr), SQLITE_OK);

    // 先建一张会被删掉的大表，它的页在删除后成为空闲页。
    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE scratch(pad TEXT);", nullptr, nullptr, nullptr), SQLITE_OK);
    for (int row = 0; row < 200; ++row) {
        const std::string insert =
            "INSERT INTO scratch(pad) VALUES('" + std::string(900, 'x') + "');";
        ASSERT_EQ(sqlite3_exec(db, insert.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
    }
    ASSERT_EQ(sqlite3_exec(db, "DROP TABLE scratch;", nullptr, nullptr, nullptr), SQLITE_OK);

    for (int index = 0; index < tables; ++index) {
        const std::string sql =
            "CREATE TABLE t" + std::to_string(index) +
            "(id INTEGER PRIMARY KEY, name TEXT, note TEXT);";
        ASSERT_EQ(sqlite3_exec(db, sql.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
        for (int row = 0; row < 20; ++row) {
            const std::string insert =
                "INSERT INTO t" + std::to_string(index) +
                "(name, note) VALUES('row" + std::to_string(row) + "','payload');";
            ASSERT_EQ(sqlite3_exec(db, insert.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
        }
    }
    sqlite3_close(db);
}

// 构造一段确定但任意的 1024 字节掩码。
// 真实容器的掩码来自"空页 XOR 全零"，因此这里也按同样方式生成：取一个
// 高位字节随机、其余位随机的 1024 字节串，作为掩码。测试只要求"掩码存在
// 且能被推导出来"，不要求它等于任何真实厂商密钥。
std::vector<unsigned char> syntheticMask(std::uint32_t seed = 0x5eed1234) {
    std::vector<unsigned char> mask(meiya::kMaskPeriod);
    std::mt19937 engine(seed);
    // 分布刻意包含 0，使"逐字节众数为 0"的假设在统计学上成立——这与真实
    // 容器中大量零字节明文页的情形一致。
    std::uniform_int_distribution<int> distribution(0, 255);
    for (auto& byte : mask) byte = static_cast<unsigned char>(distribution(engine));
    return mask;
}

std::vector<unsigned char> xorWith(const std::vector<unsigned char>& data,
                                   const std::vector<unsigned char>& mask) {
    std::vector<unsigned char> out(data.size());
    for (std::size_t index = 0; index < data.size(); ++index) {
        out[index] = data[index] ^ mask[index % meiya::kMaskPeriod];
    }
    return out;
}

}  // namespace

TEST(MeiyaCryptoTest, DerivesMaskFromObfuscatedContainers) {
    TempDir temp;
    const fs::path plain = temp / "plain.db";
    buildSqlite(plain, 4);

    const auto mask = syntheticMask();
    const auto obfuscated = xorWith(readAll(plain), mask);
    const fs::path container = temp / "device.dmf";
    writeAll(container, obfuscated);

    EXPECT_TRUE(meiya::looksLikeEncryptedContainer(container.string()));

    meiya::DerivedKey key;
    std::string error;
    ASSERT_TRUE(meiya::deriveMask({container}, key, error)) << error;
    EXPECT_EQ(key.mask, mask);
    EXPECT_EQ(key.mask.size(), meiya::kMaskPeriod);
    EXPECT_GT(key.validationEntries, 0u);

    // 解出的镜像必须通过 SQLite 自身的完整性校验。
    const auto decoded = meiya::decryptBytes(obfuscated, key.mask);
    std::size_t entries = 0;
    std::string validationError;
    EXPECT_TRUE(meiya::validateSqlite(decoded, entries, validationError)) << validationError;
    EXPECT_GT(entries, 0u);
}

TEST(MeiyaCryptoTest, DerivedMaskRoundTripsExactly) {
    TempDir temp;
    const fs::path plain = temp / "plain.db";
    buildSqlite(plain, 2);
    const auto original = readAll(plain);

    const auto mask = syntheticMask(0xabc);
    const fs::path container = temp / "x.dmf";
    writeAll(container, xorWith(original, mask));

    meiya::DerivedKey key;
    std::string error;
    ASSERT_TRUE(meiya::deriveMask({container}, key, error)) << error;

    const fs::path output = temp / "decrypted.db";
    ASSERT_TRUE(meiya::decryptFile(container.string(), output.string(), key.mask));
    EXPECT_EQ(readAll(output), original);
}

TEST(MeiyaCryptoTest, SharedMaskAcrossSmallSiblings) {
    TempDir temp;
    // 小文件页少，单独推导往往失败；同案件内掩码共享，合并后即可恢复。
    const fs::path big = temp / "big.dmf";
    buildSqlite(temp / "big_plain.db", 6);
    const auto mask = syntheticMask(0x1234);
    writeAll(big, xorWith(readAll(temp / "big_plain.db"), mask));

    meiya::DerivedKey key;
    std::string error;
    ASSERT_TRUE(meiya::deriveMask({big}, key, error)) << error;
    EXPECT_EQ(key.mask, mask);
}

TEST(MeiyaCryptoTest, RejectsPlaintextSqlite) {
    TempDir temp;
    const fs::path plain = temp / "plain.db";
    buildSqlite(plain, 1);
    // 明文库不是"加密容器"，识别必须拒绝，避免把普通业务库当成掩码容器。
    EXPECT_FALSE(meiya::looksLikeEncryptedContainer(plain.string()));
}

TEST(MeiyaCryptoTest, RejectsNonPageAlignedFile) {
    TempDir temp;
    const fs::path odd = temp / "odd.bin";
    writeAll(odd, std::vector<unsigned char>(1500, 0xAB));
    EXPECT_FALSE(meiya::looksLikeEncryptedContainer(odd.string()));
}

TEST(MeiyaCryptoTest, GarbageFailsValidationRatherThanSilentlyPassing) {
    TempDir temp;
    const fs::path junk = temp / "junk.dmf";
    std::vector<unsigned char> bytes(meiya::kMaskPeriod * 8);
    std::mt19937 engine(7);
    for (auto& byte : bytes) byte = static_cast<unsigned char>(engine() & 0xFF);
    writeAll(junk, bytes);

    meiya::DerivedKey key;
    std::string error;
    // 随机数据不该被当成可解的容器；即使推出掩码，也必须通不过 SQLite 校验。
    const bool derived = meiya::deriveMask({junk}, key, error);
    if (derived) {
        std::size_t entries = 0;
        std::string validationError;
        EXPECT_FALSE(meiya::validateSqlite(meiya::decryptBytes(bytes, key.mask),
                                          entries, validationError));
    }
}

// ---------------------------------------------------------------------------
// 适配器 → 分析层的规范化投影
//
// 美亚原始列名（strContactName / strSMSPhoneNum / strDialogPhoneNum ...）不是
// 统一包约定的规范键。适配器必须额外产出 display_name / phone_number /
// address / body / number 等键，否则分析层按规范键取值会得到空行。
// ---------------------------------------------------------------------------

namespace {

// 建一个含美亚规范化表的明文库，再用掩码混淆成容器文件。
void buildMeiyaDeviceDatabase(const fs::path& plain) {
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(plain.c_str(), &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db, "PRAGMA page_size=1024;", nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db, "PRAGMA journal_mode=DELETE;", nullptr, nullptr, nullptr), SQLITE_OK);

    // 先制造空页，让掩码可被自推导（与 MeiyaCryptoTest 同一前提）。
    ASSERT_EQ(sqlite3_exec(db, "CREATE TABLE scratch(pad TEXT);", nullptr, nullptr, nullptr),
              SQLITE_OK);
    for (int row = 0; row < 120; ++row) {
        const std::string insert =
            "INSERT INTO scratch(pad) VALUES('" + std::string(900, 'y') + "');";
        ASSERT_EQ(sqlite3_exec(db, insert.c_str(), nullptr, nullptr, nullptr), SQLITE_OK);
    }
    ASSERT_EQ(sqlite3_exec(db, "DROP TABLE scratch;", nullptr, nullptr, nullptr), SQLITE_OK);

    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE TBL_PR_CONTACT_INFO("
        "ID INTEGER PRIMARY KEY, strContactName TEXT, strContactNickname TEXT,"
        "strContactMobilePhone TEXT, strContactHomePhone TEXT, strContactWorkPhone TEXT,"
        "strContactCustomedNumber TEXT, strContactOtherPhone TEXT, strNote TEXT,"
        "strLastUpdatedTime TEXT);", nullptr, nullptr, nullptr), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "INSERT INTO TBL_PR_CONTACT_INFO VALUES"
        "(1,'张三','小张','13800138000','01088886666','','','','','2026-03-01 10:00:00'),"
        "(2,'李四','','13900139000','','','','','','2026-03-02 11:00:00');",
        nullptr, nullptr, nullptr), SQLITE_OK);

    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE TBL_PR_DIALOG_INFO("
        "ID INTEGER PRIMARY KEY, strDialogPhoneNum TEXT, strDialogName TEXT,"
        "dwDialogDuration INTEGER, dwDialogType INTEGER, dwDeleted INTEGER,"
        "strDialogLocation TEXT, strDialogInitiatedAt TEXT);", nullptr, nullptr, nullptr),
        SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "INSERT INTO TBL_PR_DIALOG_INFO VALUES"
        "(1,'13800138000','张三',65,1,0,'北京','2026-03-03 09:15:00'),"
        "(2,'13900139000','李四',0,3,0,'上海','2026-03-04 20:05:00');",
        nullptr, nullptr, nullptr), SQLITE_OK);

    ASSERT_EQ(sqlite3_exec(db,
        "CREATE TABLE TBL_PR_SMS_INFO("
        "ID INTEGER PRIMARY KEY, strSMSPhoneNum TEXT, strSMSContents TEXT,"
        "dwSMSType INTEGER, dwReadStatus INTEGER, dwDeleted INTEGER,"
        "strSMSCenter TEXT, strSMSName TEXT, strSMSSentAt TEXT);", nullptr, nullptr, nullptr),
        SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db,
        "INSERT INTO TBL_PR_SMS_INFO VALUES"
        "(1,'13800138000','晚点到',1,1,0,'+8613800138000','张三','2026-03-05 08:30:00');",
        nullptr, nullptr, nullptr), SQLITE_OK);

    sqlite3_close(db);
}

}  // namespace

TEST(MeiyaAdapterTest, EmitsCanonicalPayloadKeysAndRebuildsStandardTables) {
    TempDir temp;
    const fs::path caseRoot = temp / "case";
    const fs::path deviceDir = caseRoot / "V1824BA";
    fs::create_directories(deviceDir);

    const fs::path plain = temp / "device_plain.db";
    buildMeiyaDeviceDatabase(plain);

    const auto mask = syntheticMask(0x77aa);
    writeAll(deviceDir / "V1824BA.dmf", xorWith(readAll(plain), mask));

    meiya::MeiyaBackupExtractor extractor(caseRoot.string());
    ASSERT_TRUE(extractor.initialize()) << extractor.error();

    mobile_evidence::MeiyaAdapterOptions options;
    mobile_evidence::Package package;
    ASSERT_TRUE(mobile_evidence::buildPackageFromMeiya(extractor, options, package))
        << "buildPackageFromMeiya failed";

    // 适配器层：规范键必须出现，原始列名同时保留。
    int contacts = 0, sms = 0, calls = 0;
    for (const auto& record : package.records) {
        const json payload = json::parse(record.payloadJson);
        if (record.kind == mobile_evidence::kind::kContact) {
            ++contacts;
            EXPECT_TRUE(payload.contains("display_name")) << record.payloadJson;
            EXPECT_TRUE(payload.contains("phone_number")) << record.payloadJson;
            EXPECT_TRUE(payload.contains("strContactName"))
                << "raw column must be preserved for traceability";
        } else if (record.kind == mobile_evidence::kind::kSms) {
            ++sms;
            EXPECT_TRUE(payload.contains("address")) << record.payloadJson;
            EXPECT_TRUE(payload.contains("body")) << record.payloadJson;
        } else if (record.kind == mobile_evidence::kind::kCallLog) {
            ++calls;
            EXPECT_TRUE(payload.contains("number")) << record.payloadJson;
            EXPECT_TRUE(payload.contains("duration_seconds")) << record.payloadJson;
        }
    }
    EXPECT_EQ(contacts, 2);
    EXPECT_EQ(sms, 1);
    EXPECT_EQ(calls, 2);

    // 分析层：只凭包重建标准表，行与关键字段都要非空。
    const fs::path androidDb = temp / "android.db";
    {
        AndroidAnalysisDatabase database(androidDb.string());
        ASSERT_TRUE(database.initialize());
        mobile_evidence::AnalysisOptions analysisOptions;
        mobile_evidence::AnalysisResult result;
        ASSERT_TRUE(mobile_evidence::analyzePackage(package, database, analysisOptions, result));
        EXPECT_EQ(result.contacts, 2u);
        EXPECT_EQ(result.sms, 1u);
        EXPECT_EQ(result.callLogs, 2u);
    }

    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open_v2(androidDb.c_str(), &db, SQLITE_OPEN_READONLY, nullptr), SQLITE_OK);
    const auto scalar = [&db](const char* sql) -> sqlite3_int64 {
        sqlite3_stmt* statement = nullptr;
        if (sqlite3_prepare_v2(db, sql, -1, &statement, nullptr) != SQLITE_OK) return -1;
        sqlite3_int64 value = -1;
        if (sqlite3_step(statement) == SQLITE_ROW) value = sqlite3_column_int64(statement, 0);
        sqlite3_finalize(statement);
        return value;
    };
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM contacts WHERE phone_number<>''"), 2);
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM call_logs WHERE number<>''"), 2);
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM sms_messages WHERE address<>'' AND body<>''"), 1);
    // 时间：date 保留原值（美亚是秒级 epoch，来自 timestamp_seconds），
    // date_seconds 必须与之一致，供跨源排序使用。
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM call_logs WHERE date_seconds > 0"), 2);
    EXPECT_EQ(scalar("SELECT COUNT(*) FROM sms_messages WHERE date_seconds > 0"), 1);
    sqlite3_close(db);
}

