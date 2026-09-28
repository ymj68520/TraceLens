#include <gtest/gtest.h>

#include "analyzers/AndroidAnalyzer/AndroidPathMapper.h"
#include "analyzers/AndroidAnalyzer/ArchiveFileExtractor.h"

#include <archive.h>
#include <archive_entry.h>
#include <zlib.h>
#include <openssl/evp.h>

#include <filesystem>
#include <fstream>
#include <string>
#include <vector>
#include <array>
#include <iomanip>
#include <sstream>

#include <unistd.h>

namespace fs = std::filesystem;
namespace {
const std::string kSms = "data/data/com.android.providers.telephony/databases/mmssms.db";
const std::string kWal = kSms + "-wal";

TEST(AndroidUserdataPathMapping, MountsFilesystemRootAtDataWithoutGuessing) {
    const auto mapped = AndroidPathMapper::buildUserdata({
        "data/com.android.providers.telephony/databases/mmssms.db",
        "data/com.android.providers.telephony/databases/mmssms.db-wal",
        "system/packages.xml", "misc/wifi/WifiConfigStore.xml"});
    ASSERT_TRUE(mapped.valid);
    EXPECT_EQ(mapped.normalizedToMember.at(kSms),
              "data/com.android.providers.telephony/databases/mmssms.db");
    EXPECT_EQ(mapped.normalizedToMember.at(kWal),
              "data/com.android.providers.telephony/databases/mmssms.db-wal");
    EXPECT_EQ(mapped.normalizedToMember.at("data/system/packages.xml"), "system/packages.xml");
    EXPECT_EQ(mapped.normalizedToMember.at("data/misc/wifi/WifiConfigStore.xml"),
              "misc/wifi/WifiConfigStore.xml");
    EXPECT_FALSE(AndroidPathMapper::buildUserdata({"etc/passwd"}).valid);
    EXPECT_FALSE(AndroidPathMapper::buildUserdata({"data/com.foo/x", "data/../escape"}).valid);
}

bool makeArchive(const fs::path& path, const std::string& format,
                 const std::vector<std::pair<std::string, std::string>>& members) {
    struct archive* writer = archive_write_new();
    if (!writer) return false;
    int rc = format == "7z" ? archive_write_set_format_7zip(writer) :
             format == "gnu" ? archive_write_set_format_gnutar(writer) :
                               archive_write_set_format_pax_restricted(writer);
    if (format == "tgz") rc = rc == ARCHIVE_OK ? archive_write_add_filter_gzip(writer) : rc;
    if (format == "txz") rc = rc == ARCHIVE_OK ? archive_write_add_filter_xz(writer) : rc;
    if (rc != ARCHIVE_OK || archive_write_open_filename(writer, path.c_str()) != ARCHIVE_OK) {
        archive_write_free(writer);
        return false;
    }
    bool okay = true;
    for (const auto& [name, bytes] : members) {
        struct archive_entry* item = archive_entry_new();
        archive_entry_set_pathname(item, name.c_str());
        archive_entry_set_filetype(item, AE_IFREG);
        archive_entry_set_perm(item, 0600);
        archive_entry_set_size(item, static_cast<la_int64_t>(bytes.size()));
        okay = archive_write_header(writer, item) == ARCHIVE_OK &&
               archive_write_data(writer, bytes.data(), bytes.size()) == static_cast<la_ssize_t>(bytes.size());
        archive_entry_free(item);
        if (!okay) break;
    }
    okay = archive_write_close(writer) == ARCHIVE_OK && okay;
    archive_write_free(writer);
    return okay;
}

std::string bytesOf(const fs::path& path) {
    std::ifstream source(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(source), std::istreambuf_iterator<char>()};
}

std::string hexOf(const unsigned char* bytes, std::size_t size) {
    std::ostringstream out;
    out << std::hex << std::setfill('0');
    for (std::size_t i = 0; i < size; ++i) out << std::setw(2) << static_cast<int>(bytes[i]);
    return out.str();
}

std::string encryptAes(const std::string& value, const unsigned char* key,
                       const unsigned char* iv) {
    EVP_CIPHER_CTX* ctx = EVP_CIPHER_CTX_new();
    std::string output(value.size() + 16, '\0');
    int first = 0, tail = 0;
    const bool okay = ctx && EVP_EncryptInit_ex(ctx, EVP_aes_256_cbc(), nullptr, key, iv) == 1 &&
        EVP_EncryptUpdate(ctx, reinterpret_cast<unsigned char*>(output.data()), &first,
            reinterpret_cast<const unsigned char*>(value.data()), static_cast<int>(value.size())) == 1 &&
        EVP_EncryptFinal_ex(ctx, reinterpret_cast<unsigned char*>(output.data()) + first, &tail) == 1;
    if (ctx) EVP_CIPHER_CTX_free(ctx);
    return okay ? output.substr(0, first + tail) : std::string();
}

std::string javaChecksumKey(const std::array<unsigned char, 32>& key) {
    std::string result;
    for (unsigned char value : key) {
        const unsigned int code = value < 128 ? value : 0xff00U + value;
        if (code < 0x80) result.push_back(static_cast<char>(code));
        else {
            result.push_back(static_cast<char>(0xe0 | (code >> 12)));
            result.push_back(static_cast<char>(0x80 | ((code >> 6) & 0x3f)));
            result.push_back(static_cast<char>(0x80 | (code & 0x3f)));
        }
    }
    return result;
}

bool makeEncryptedAb(const fs::path& path, const std::string& tarBytes,
                     const std::string& password) {
    std::array<unsigned char, 64> userSalt{}, checksumSalt{};
    std::array<unsigned char, 16> userIv{}, dataIv{};
    std::array<unsigned char, 32> userKey{}, dataKey{}, checksum{};
    for (std::size_t i = 0; i < 64; ++i) {
        userSalt[i] = static_cast<unsigned char>(i + 1);
        checksumSalt[i] = static_cast<unsigned char>(100 + i);
    }
    for (std::size_t i = 0; i < 16; ++i) { userIv[i] = i; dataIv[i] = 20 + i; }
    for (std::size_t i = 0; i < 32; ++i) dataKey[i] = static_cast<unsigned char>(150 + i);
    constexpr int rounds = 10000;
    if (PKCS5_PBKDF2_HMAC(password.data(), static_cast<int>(password.size()),
                          userSalt.data(), userSalt.size(), rounds, EVP_sha1(),
                          userKey.size(), userKey.data()) != 1) return false;
    const std::string checksumPassword = javaChecksumKey(dataKey);
    if (PKCS5_PBKDF2_HMAC(checksumPassword.data(), static_cast<int>(checksumPassword.size()),
                          checksumSalt.data(), checksumSalt.size(), rounds, EVP_sha1(),
                          checksum.size(), checksum.data()) != 1) return false;
    std::string blob;
    blob.push_back(16);
    blob.append(reinterpret_cast<const char*>(dataIv.data()), dataIv.size());
    blob.push_back(32);
    blob.append(reinterpret_cast<const char*>(dataKey.data()), dataKey.size());
    blob.push_back(32);
    blob.append(reinterpret_cast<const char*>(checksum.data()), checksum.size());
    const std::string encryptedBlob = encryptAes(blob, userKey.data(), userIv.data());
    std::vector<unsigned char> compressed(compressBound(tarBytes.size()));
    uLongf size = compressed.size();
    if (encryptedBlob.empty() || compress2(compressed.data(), &size,
        reinterpret_cast<const unsigned char*>(tarBytes.data()), tarBytes.size(), 6) != Z_OK) return false;
    const std::string encryptedPayload = encryptAes(
        std::string(reinterpret_cast<const char*>(compressed.data()), size),
        dataKey.data(), dataIv.data());
    if (encryptedPayload.empty()) return false;
    std::ofstream out(path, std::ios::binary);
    out << "ANDROID BACKUP\n5\n1\nAES-256\n"
        << hexOf(userSalt.data(), userSalt.size()) << '\n'
        << hexOf(checksumSalt.data(), checksumSalt.size()) << '\n'
        << rounds << '\n' << hexOf(userIv.data(), userIv.size()) << '\n'
        << hexOf(reinterpret_cast<const unsigned char*>(encryptedBlob.data()), encryptedBlob.size()) << '\n';
    out.write(encryptedPayload.data(), encryptedPayload.size());
    return out.good();
}

class ArchiveTest : public ::testing::Test {
protected:
    void SetUp() override {
        root_ = fs::temp_directory_path() /
            ("tracelens_android_archive_test_" + std::to_string(getpid()));
        fs::create_directories(root_);
    }
    void TearDown() override { std::error_code ec; fs::remove_all(root_, ec); }
    fs::path root_;
};
} // namespace

TEST_F(ArchiveTest, TarGzipAndXzMapAndExtractCompanions) {
    for (const auto& format : {"tar", "tgz", "txz"}) {
        const fs::path path = root_ / (std::string("phone.") + format);
        ASSERT_TRUE(makeArchive(path, format, {{"phone_export/" + kSms, "sms-bytes"},
                                               {"phone_export/" + kWal, "wal-bytes"}}));
        TarArchiveExtractor extractor(path.string());
        ASSERT_TRUE(extractor.initialize()) << extractor.errorCode();
        EXPECT_EQ(extractor.rootMapping().rootMapping, "phone_export/");
        EXPECT_EQ(extractor.memberCount(), 2);
        EXPECT_EQ(extractor.statMember(kWal), std::optional<std::uint64_t>(9));
        const fs::path sms = root_ / (std::string(format) + "_sms");
        const fs::path wal = root_ / (std::string(format) + "_wal");
        ASSERT_TRUE(extractor.extractFileByPath(kSms, sms.string()));
        ASSERT_TRUE(extractor.extractFileByPath(kWal, wal.string()));
        EXPECT_EQ(bytesOf(sms), "sms-bytes");
        EXPECT_EQ(bytesOf(wal), "wal-bytes");
        const auto provenance = extractor.usedSourceProvenance();
        ASSERT_EQ(provenance.size(), 2);
        EXPECT_EQ(provenance[0].sourceMemberPath, "phone_export/" + kSms);
        EXPECT_EQ(provenance[0].normalizedAndroidPath, kSms);
        EXPECT_EQ(provenance[0].memberSha256.size(), 64);
        EXPECT_EQ(provenance[0].containerSha256.size(), 64);
    }
}

TEST_F(ArchiveTest, SevenZipUsesSameAndroidPathView) {
    const fs::path path = root_ / "phone.7z";
    ASSERT_TRUE(makeArchive(path, "7z", {{kSms, "sms-bytes"}, {kWal, "wal-bytes"}}));
    SevenZipArchiveExtractor extractor(path.string());
    ASSERT_TRUE(extractor.initialize()) << extractor.errorCode();
    const fs::path output = root_ / "sms-7z";
    ASSERT_TRUE(extractor.extractFileByPath(kSms, output.string()));
    EXPECT_EQ(bytesOf(output), "sms-bytes");
    EXPECT_EQ(extractor.findPathsByFilename("mmssms.db-wal").size(), 1);
}

TEST_F(ArchiveTest, PaxAndGnuLongNamesAreMappedWithoutRewritingTar) {
    const std::string wrapper(180, 'p');
    for (const auto& format : {"tar", "gnu"}) {
        const fs::path path = root_ / (std::string("long-") + format + ".tar");
        ASSERT_TRUE(makeArchive(path, format, {{wrapper + "/" + kSms, "long-name-sms"}}));
        TarArchiveExtractor extractor(path.string());
        ASSERT_TRUE(extractor.initialize()) << extractor.errorCode();
        const fs::path output = root_ / (std::string("out-") + format);
        ASSERT_TRUE(extractor.extractFileByPath(kSms, output.string()));
        EXPECT_EQ(bytesOf(output), "long-name-sms");
    }
}

TEST_F(ArchiveTest, AndroidBackupUncompressedAndCompressed) {
    const fs::path tar = root_ / "source.tar";
    ASSERT_TRUE(makeArchive(tar, "tar", {{"apps/com.android.providers.telephony/db/mmssms.db", "sms-bytes"}}));
    const auto tarBytes = bytesOf(tar);
    for (bool compressed : {false, true}) {
        const fs::path path = root_ / (compressed ? "compressed.ab" : "plain.ab");
        std::ofstream out(path, std::ios::binary);
        out << "ANDROID BACKUP\n5\n" << (compressed ? "1" : "0") << "\nnone\n";
        if (compressed) {
            std::vector<unsigned char> buffer(compressBound(tarBytes.size()));
            uLongf size = buffer.size();
            ASSERT_EQ(compress2(buffer.data(), &size,
                reinterpret_cast<const unsigned char*>(tarBytes.data()), tarBytes.size(), 6), Z_OK);
            out.write(reinterpret_cast<const char*>(buffer.data()), size);
        } else out.write(tarBytes.data(), tarBytes.size());
        out.close();
        AndroidBackupExtractor extractor(path.string());
        ASSERT_TRUE(extractor.initialize()) << extractor.errorCode();
        const fs::path output = root_ / (compressed ? "sms-compressed" : "sms-plain");
        ASSERT_TRUE(extractor.extractFileByPath(kSms, output.string()));
        EXPECT_EQ(bytesOf(output), "sms-bytes");
        EXPECT_EQ(extractor.rootMapping().rootMapping, "adb_apps");
    }
}

TEST_F(ArchiveTest, LockedBackupAndUnsafePathFailClosed) {
    const fs::path locked = root_ / "locked.ab";
    { std::ofstream out(locked, std::ios::binary); out << "ANDROID BACKUP\n5\n1\nAES-256\n"; }
    AndroidBackupExtractor backup(locked.string());
    EXPECT_FALSE(backup.initialize());
    EXPECT_EQ(backup.errorCode(), "LOCKED_BACKUP");

    const fs::path unsafe = root_ / "unsafe.tar";
    ASSERT_TRUE(makeArchive(unsafe, "tar", {{"../../etc/passwd", "unsafe"}, {kSms, "sms"}}));
    TarArchiveExtractor extractor(unsafe.string());
    EXPECT_FALSE(extractor.initialize());
    EXPECT_NE(extractor.errorCode().find("RISK_REJECTED"), std::string::npos);
}

TEST_F(ArchiveTest, SymlinkMemberIsNeverUsedAsAndroidFileContent) {
    const fs::path path = root_ / "links.tar";
    struct archive* writer = archive_write_new();
    ASSERT_EQ(archive_write_set_format_pax_restricted(writer), ARCHIVE_OK);
    ASSERT_EQ(archive_write_open_filename(writer, path.c_str()), ARCHIVE_OK);
    struct archive_entry* link = archive_entry_new();
    archive_entry_set_pathname(link,
        "data/data/com.android.providers.telephony/databases/link.db");
    archive_entry_set_filetype(link, AE_IFLNK);
    archive_entry_set_symlink(link, "../../../../etc/passwd");
    archive_entry_set_perm(link, 0777);
    archive_entry_set_size(link, 0);
    ASSERT_EQ(archive_write_header(writer, link), ARCHIVE_OK);
    archive_entry_free(link);
    struct archive_entry* regular = archive_entry_new();
    archive_entry_set_pathname(regular, kSms.c_str());
    archive_entry_set_filetype(regular, AE_IFREG);
    archive_entry_set_perm(regular, 0600);
    archive_entry_set_size(regular, 3);
    ASSERT_EQ(archive_write_header(writer, regular), ARCHIVE_OK);
    ASSERT_EQ(archive_write_data(writer, "sms", 3), 3);
    archive_entry_free(regular);
    ASSERT_EQ(archive_write_close(writer), ARCHIVE_OK);
    archive_write_free(writer);

    TarArchiveExtractor extractor(path.string());
    ASSERT_TRUE(extractor.initialize()) << extractor.errorCode();
    EXPECT_EQ(extractor.skippedLinkCount(), 1);
    EXPECT_FALSE(extractor.extractFileByPath(
        "data/data/com.android.providers.telephony/databases/link.db",
        (root_ / "not-extracted").string()));
    EXPECT_TRUE(extractor.extractFileByPath(kSms, (root_ / "sms").string()));
    EXPECT_EQ(bytesOf(root_ / "sms"), "sms");
}

TEST_F(ArchiveTest, ExtremeCompressionRatioIsRiskRejected) {
    const fs::path path = root_ / "bomb.tgz";
    ASSERT_TRUE(makeArchive(path, "tgz", {{kSms, std::string(17 * 1024 * 1024, '0')}}));
    TarArchiveExtractor extractor(path.string());
    EXPECT_FALSE(extractor.initialize());
    EXPECT_NE(extractor.errorCode().find("RISK_REJECTED"), std::string::npos);
}

TEST_F(ArchiveTest, EncryptedBackupRequiresCorrectPassword) {
    const fs::path tar = root_ / "encrypted-source.tar";
    ASSERT_TRUE(makeArchive(tar, "tar", {{"apps/com.android.providers.telephony/db/mmssms.db", "sms-secret"}}));
    const fs::path path = root_ / "encrypted.ab";
    ASSERT_TRUE(makeEncryptedAb(path, bytesOf(tar), "test-password"));
    AndroidBackupExtractor locked(path.string());
    EXPECT_FALSE(locked.initialize());
    EXPECT_EQ(locked.errorCode(), "LOCKED_BACKUP");
    AndroidBackupExtractor incorrect(path.string(), "wrong-password");
    EXPECT_FALSE(incorrect.initialize());
    EXPECT_EQ(incorrect.errorCode(), "LOCKED_BACKUP");
    AndroidBackupExtractor correct(path.string(), "test-password");
    ASSERT_TRUE(correct.initialize()) << correct.errorCode();
    const fs::path output = root_ / "decrypted-sms";
    ASSERT_TRUE(correct.extractFileByPath(kSms, output.string())) << correct.errorCode();
    EXPECT_EQ(bytesOf(output), "sms-secret");
    EXPECT_TRUE(correct.passwordSupplied());

    std::string truncated = bytesOf(path);
    truncated.resize(truncated.size() - 8);
    const fs::path damaged = root_ / "truncated-encrypted.ab";
    { std::ofstream out(damaged, std::ios::binary); out.write(truncated.data(), truncated.size()); }
    AndroidBackupExtractor broken(damaged.string(), "test-password");
    EXPECT_FALSE(broken.initialize());
    EXPECT_EQ(broken.errorCode(), "MALFORMED_BACKUP");
}

TEST_F(ArchiveTest, UnsupportedAndTruncatedBackupNeverInitialize) {
    const fs::path unsupported = root_ / "unsupported.ab";
    { std::ofstream out(unsupported, std::ios::binary); out << "ANDROID BACKUP\n99\n1\nnone\n"; }
    AndroidBackupExtractor future(unsupported.string());
    EXPECT_FALSE(future.initialize());
    EXPECT_EQ(future.errorCode(), "UNSUPPORTED_BACKUP_VARIANT");
    const fs::path legacy = root_ / "legacy-v1-encrypted.ab";
    { std::ofstream out(legacy, std::ios::binary); out << "ANDROID BACKUP\n1\n1\nAES-256\n"; }
    AndroidBackupExtractor oldKdf(legacy.string(), "fixture-password");
    EXPECT_FALSE(oldKdf.initialize());
    EXPECT_EQ(oldKdf.errorCode(), "UNSUPPORTED_BACKUP_VARIANT");

    const fs::path tar = root_ / "source.tar";
    ASSERT_TRUE(makeArchive(tar, "tar", {{kSms, "sms"}}));
    const std::string tarBytes = bytesOf(tar);
    std::vector<unsigned char> compressed(compressBound(tarBytes.size()));
    uLongf size = compressed.size();
    ASSERT_EQ(compress2(compressed.data(), &size,
        reinterpret_cast<const unsigned char*>(tarBytes.data()), tarBytes.size(), 6), Z_OK);
    const fs::path truncated = root_ / "truncated.ab";
    { std::ofstream out(truncated, std::ios::binary);
      out << "ANDROID BACKUP\n5\n1\nnone\n";
      out.write(reinterpret_cast<const char*>(compressed.data()), size - 4); }
    AndroidBackupExtractor broken(truncated.string());
    EXPECT_FALSE(broken.initialize());
    EXPECT_EQ(broken.errorCode(), "MALFORMED_BACKUP");
}

TEST(AndroidPathMapperTest, RefusesAmbiguousOrNonAndroidRoots) {
    EXPECT_FALSE(AndroidPathMapper::build({"notes/data.txt"}).valid);
    EXPECT_FALSE(AndroidPathMapper::build({kSms, "./" + kSms}).valid);
    const auto wrapped = AndroidPathMapper::build({"userdata/" + kSms});
    ASSERT_TRUE(wrapped.valid);
    EXPECT_EQ(wrapped.normalizedToMember.at(kSms), "userdata/" + kSms);
    std::string cleaned, reason;
    EXPECT_FALSE(AndroidPathMapper::safeMemberPath("C:\\Windows\\foo", cleaned, reason));
    EXPECT_FALSE(AndroidPathMapper::safeMemberPath("../../etc/passwd", cleaned, reason));
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
