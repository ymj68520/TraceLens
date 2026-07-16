#include <gtest/gtest.h>
#include <sqlite3.h>
#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <system_error>
#include <utility>
#include "DatabaseManager/FileExtractor/FileExtractor.h"

namespace fs = std::filesystem;

namespace {

std::string temporarySuffix() {
    return std::to_string(std::chrono::steady_clock::now().time_since_epoch().count());
}

fs::path temporaryRoot(const std::string& label) {
    return fs::temp_directory_path() /
           ("tracelens-" + label + "-" + temporarySuffix());
}

class ScopedDirectory {
public:
    explicit ScopedDirectory(fs::path path) : path_(std::move(path)) {}

    ~ScopedDirectory() {
        std::error_code ec;
        fs::remove_all(path_, ec);
    }

    const fs::path& path() const { return path_; }

private:
    fs::path path_;
};

std::error_code createDirectorySymlink(const fs::path& target,
                                       const fs::path& link) {
    std::error_code ec;
    fs::create_directory_symlink(target, link, ec);
    return ec;
}

std::error_code createFileSymlink(const fs::path& target, const fs::path& link) {
    std::error_code ec;
    fs::create_symlink(target, link, ec);
    return ec;
}

#ifdef _WIN32
#define REQUIRE_SYMLINK_CREATED(expression)                                      \
    do {                                                                         \
        const std::error_code symlinkError = (expression);                       \
        if (symlinkError) {                                                      \
            GTEST_SKIP() << "Symlink creation is unavailable: "                 \
                         << symlinkError.message();                              \
        }                                                                        \
    } while (false)
#else
#define REQUIRE_SYMLINK_CREATED(expression)                                      \
    do {                                                                         \
        const std::error_code symlinkError = (expression);                       \
        ASSERT_FALSE(symlinkError)                                               \
            << "Symlink creation failed: " << symlinkError.message();           \
    } while (false)
#endif

std::string readFile(const fs::path& path) {
    std::ifstream input(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

bool hasTemporaryExtractionFile(const fs::path& root) {
    std::error_code ec;
    fs::recursive_directory_iterator iterator(root, ec);
    const fs::recursive_directory_iterator end;
    while (!ec && iterator != end) {
        if (iterator->path().filename().string().starts_with(
                ".tracelens-textdump-tmp-")) {
            return true;
        }
        iterator.increment(ec);
    }
    return false;
}

FileRecord recordFor(const std::string& imagePath, int64_t size) {
    FileRecord record{};
    record.inode = 42;
    record.partitionNum = 7;
    record.path = imagePath;
    record.size = size;
    record.type = "REG";
    return record;
}

class ControlledFileExtractor final : public FileExtractor {
public:
    ControlledFileExtractor(std::string bytes, bool returnSuccess)
        : FileExtractor("", ""), bytes_(std::move(bytes)), returnSuccess_(returnSuccess) {}

    int extractionCalls() const { return extractionCalls_; }

protected:
    bool extractFile(const FileRecord&, const std::string& outputPath, bool,
                     int*) override {
        ++extractionCalls_;
        std::error_code ec;
        fs::create_directories(fs::path(outputPath).parent_path(), ec);
        if (ec) {
            return false;
        }

        std::ofstream output(outputPath, std::ios::binary);
        output.write(bytes_.data(), static_cast<std::streamsize>(bytes_.size()));
        output.flush();
        return output.good() && returnSuccess_;
    }

private:
    std::string bytes_;
    bool returnSuccess_;
    int extractionCalls_ = 0;
};

class SQLiteFixture : public ::testing::Test {
protected:
    void SetUp() override {
        ASSERT_EQ(sqlite3_open(":memory:", &db_), SQLITE_OK);
        ASSERT_EQ(sqlite3_exec(db_, R"SQL(
            CREATE TABLE files (
                inode INTEGER, name TEXT, path TEXT, size INTEGER,
                mtime INTEGER, ctime INTEGER, type TEXT,
                is_deleted INTEGER, is_allocated INTEGER, md5 TEXT,
                partition_num INTEGER
            );
            INSERT INTO files VALUES
                (8, 'z', '/z.txt', 1, 0, 0, 'REG', 0, 1, '', 0),
                (9, 'a2', '/a.txt', 1, 0, 0, 'REG', 0, 1, '', 2),
                (3, 'a1', '/a.txt', 1, 0, 0, 'REG', 0, 1, '', 1),
                (6, 'upper', '/A.txt', 1, 0, 0, 'REG', 0, 1, '', 0),
                (7, 'nullable', '/nullable.txt', 1, 0, 0, 'REG', 0, NULL, '', 0),
                (5, 'unallocated', '/unallocated.txt', 1, 0, 0, 'REG', 0, 0, '', 0),
                (2, 'deleted', '/b.txt', 1, 0, 0, 'REG', 1, 1, '', 0),
                (1, 'dir', '/c', 0, 0, 0, 'DIR', 0, 1, '', 0);
        )SQL", nullptr, nullptr, nullptr), SQLITE_OK);
    }
    void TearDown() override { sqlite3_close(db_); }
    sqlite3* db_ = nullptr;
};

TEST_F(SQLiteFixture, OrdersAllocatedRegularFilesDeterministically) {
    std::string error;
    const auto rows = FileExtractor::queryRegularFilesOrdered(db_, &error);
    ASSERT_TRUE(error.empty());
    ASSERT_EQ(rows.size(), 5U);
    EXPECT_EQ(rows[0].path, "/A.txt");
    EXPECT_EQ(rows[0].partitionNum, 0);
    EXPECT_EQ(rows[0].inode, 6);
    EXPECT_EQ(rows[1].path, "/a.txt");
    EXPECT_EQ(rows[1].partitionNum, 1);
    EXPECT_EQ(rows[1].inode, 3);
    EXPECT_EQ(rows[2].path, "/a.txt");
    EXPECT_EQ(rows[2].partitionNum, 2);
    EXPECT_EQ(rows[2].inode, 9);
    EXPECT_EQ(rows[3].path, "/nullable.txt");
    EXPECT_EQ(rows[3].partitionNum, 0);
    EXPECT_EQ(rows[3].inode, 7);
    EXPECT_EQ(rows[4].path, "/z.txt");
    EXPECT_EQ(rows[4].partitionNum, 0);
    EXPECT_EQ(rows[4].inode, 8);
    EXPECT_TRUE(std::none_of(rows.begin(), rows.end(), [](const FileRecord& record) {
        return record.path == "/unallocated.txt";
    }));
}

TEST(FileExtractorTextDumpQuery, NullDatabaseReportsError) {
    std::string error;
    const auto rows = FileExtractor::queryRegularFilesOrdered(nullptr, &error);
    EXPECT_TRUE(rows.empty());
    EXPECT_FALSE(error.empty());
}

TEST(FileExtractorTextDumpQuery, MissingTableReportsPrepareError) {
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(":memory:", &db), SQLITE_OK);

    std::string error;
    const auto rows = FileExtractor::queryRegularFilesOrdered(db, &error);
    EXPECT_TRUE(rows.empty());
    EXPECT_FALSE(error.empty());

    sqlite3_close(db);
}

TEST(FileExtractorTextDumpQuery, MalformedSchemaReportsPrepareError) {
    sqlite3* db = nullptr;
    ASSERT_EQ(sqlite3_open(":memory:", &db), SQLITE_OK);
    ASSERT_EQ(sqlite3_exec(db, "CREATE TABLE files (inode INTEGER);", nullptr, nullptr,
                           nullptr),
              SQLITE_OK);

    std::string error;
    const auto rows = FileExtractor::queryRegularFilesOrdered(db, &error);
    EXPECT_TRUE(rows.empty());
    EXPECT_FALSE(error.empty());

    sqlite3_close(db);
}

TEST(FileExtractorTextDumpPath, ResolvesImagePathBeneathRoot) {
    ScopedDirectory root(temporaryRoot("safe-path"));
    ASSERT_FALSE(fs::exists(root.path()));
    fs::create_directories(root.path());
    std::string error;
    const auto result = FileExtractor::resolveSafeOutputPath(
        root.path(), "/etc/auth.log", &error);
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(*result, root.path() / "etc" / "auth.log");
}

TEST(FileExtractorTextDumpPath, RejectsTraversalAndPrefixConfusion) {
    ScopedDirectory root(temporaryRoot("unsafe-path"));
    fs::create_directories(root.path());

    std::string error;
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root.path(), "../../escape", &error).has_value());
    error.clear();
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root.path(), "/../../escape", &error).has_value());
}

TEST(FileExtractorTextDumpPath, RejectsOutputRootOrdinaryFile) {
    ScopedDirectory sandbox(temporaryRoot("ordinary-root-file"));
    fs::create_directories(sandbox.path());
    const fs::path outputRoot = sandbox.path() / "dump";
    {
        std::ofstream file(outputRoot);
        file << "not a directory";
    }

    std::string error;
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        outputRoot, "/entry.txt", &error).has_value());
    EXPECT_FALSE(error.empty());
}

TEST(FileExtractorTextDumpPath, RejectsOutputRootAncestorSymlink) {
    ScopedDirectory sandbox(temporaryRoot("ancestor-sandbox"));
    ScopedDirectory outside(temporaryRoot("ancestor-outside"));
    const fs::path outputRoot = sandbox.path() / "link" / "dump";
    fs::create_directories(sandbox.path());
    fs::create_directories(outside.path());
    REQUIRE_SYMLINK_CREATED(
        createDirectorySymlink(outside.path(), sandbox.path() / "link"));

    std::string error;
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        outputRoot, "/entry.txt", &error).has_value());
    EXPECT_FALSE(error.empty());
}

TEST(FileExtractorTextDumpPath, RejectsFinalAndDanglingFinalSymlinks) {
    ScopedDirectory root(temporaryRoot("final-symlink-root"));
    ScopedDirectory outside(temporaryRoot("final-symlink-outside"));
    fs::create_directories(root.path());
    fs::create_directories(outside.path());
    const fs::path finalPath = root.path() / "entry.txt";
    {
        std::ofstream outsideFile(outside.path() / "live.txt");
        outsideFile << "outside";
    }
    REQUIRE_SYMLINK_CREATED(
        createFileSymlink(outside.path() / "live.txt", finalPath));

    std::string error;
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root.path(), "/entry.txt", &error).has_value());
    EXPECT_FALSE(error.empty());

    std::error_code ec;
    fs::remove(finalPath, ec);
    ASSERT_FALSE(ec) << ec.message();
    REQUIRE_SYMLINK_CREATED(
        createFileSymlink(outside.path() / "missing.txt", finalPath));
    error.clear();
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root.path(), "/entry.txt", &error).has_value());
    EXPECT_FALSE(error.empty());
}

TEST(FileExtractorTextDumpPath, RejectsDanglingChildDirectorySymlink) {
    ScopedDirectory root(temporaryRoot("dangling-child-root"));
    fs::create_directories(root.path());
    REQUIRE_SYMLINK_CREATED(createDirectorySymlink(
        temporaryRoot("missing-target"), root.path() / "linked"));

    std::string error;
    EXPECT_FALSE(FileExtractor::resolveSafeOutputPath(
        root.path(), "/linked/entry.txt", &error).has_value());
    EXPECT_FALSE(error.empty());
}

TEST(FileExtractorTextDumpPath, AllowsExistingOrdinaryParentDirectory) {
    ScopedDirectory root(temporaryRoot("ordinary-parent"));
    fs::create_directories(root.path() / "ordinary");

    std::string error;
    const auto result = FileExtractor::resolveSafeOutputPath(
        root.path(), "/ordinary/entry.txt", &error);
    ASSERT_TRUE(result.has_value());
    EXPECT_EQ(*result, root.path() / "ordinary" / "entry.txt");
    EXPECT_TRUE(error.empty());
}

TEST(FileExtractorTextDumpAtomic, PublishesOnlyCompleteTemporaryOutput) {
    ScopedDirectory root(temporaryRoot("atomic-complete"));
    ControlledFileExtractor extractor("full", true);
    const auto result = extractor.extractRecordAtomically(
        recordFor("/entry.txt", 4), root.path());

    EXPECT_EQ(result.status, FileExtractor::AtomicExtractionStatus::Extracted);
    EXPECT_EQ(result.output_path, root.path() / "entry.txt");
    EXPECT_EQ(result.output_bytes, 4U);
    EXPECT_EQ(readFile(root.path() / "entry.txt"), "full");
    EXPECT_EQ(extractor.extractionCalls(), 1);
    EXPECT_FALSE(hasTemporaryExtractionFile(root.path()));
}

TEST(FileExtractorTextDumpAtomic, ReusesMatchingRegularFinalWithoutWriting) {
    ScopedDirectory root(temporaryRoot("atomic-reuse"));
    fs::create_directories(root.path());
    {
        std::ofstream finalFile(root.path() / "entry.txt", std::ios::binary);
        finalFile << "keep";
    }
    ControlledFileExtractor extractor("new!", true);

    const auto result = extractor.extractRecordAtomically(
        recordFor("/entry.txt", 4), root.path());

    EXPECT_EQ(result.status, FileExtractor::AtomicExtractionStatus::Reused);
    EXPECT_EQ(result.previous_bytes, 4U);
    EXPECT_EQ(result.output_bytes, 4U);
    EXPECT_EQ(readFile(root.path() / "entry.txt"), "keep");
    EXPECT_EQ(extractor.extractionCalls(), 0);
    EXPECT_FALSE(hasTemporaryExtractionFile(root.path()));
}

TEST(FileExtractorTextDumpAtomic, PreservesFinalWhenTemporaryOutputIsPartial) {
    ScopedDirectory root(temporaryRoot("atomic-partial"));
    fs::create_directories(root.path());
    {
        std::ofstream finalFile(root.path() / "entry.txt", std::ios::binary);
        finalFile << "previous-final";
    }
    ControlledFileExtractor extractor("short", true);

    const auto result = extractor.extractRecordAtomically(
        recordFor("/entry.txt", 8), root.path());

    EXPECT_EQ(result.status, FileExtractor::AtomicExtractionStatus::Failed);
    EXPECT_EQ(readFile(root.path() / "entry.txt"), "previous-final");
    EXPECT_NE(result.error.find("expected"), std::string::npos);
    EXPECT_FALSE(hasTemporaryExtractionFile(root.path()));
}

TEST(FileExtractorTextDumpAtomic, RejectsNegativeExpectedSizeWithoutPublishing) {
    ScopedDirectory root(temporaryRoot("atomic-negative-size"));
    fs::create_directories(root.path());
    {
        std::ofstream finalFile(root.path() / "entry.txt", std::ios::binary);
        finalFile << "previous";
    }
    ControlledFileExtractor extractor("temporary", true);

    const auto result = extractor.extractRecordAtomically(
        recordFor("/entry.txt", -1), root.path());

    EXPECT_EQ(result.status, FileExtractor::AtomicExtractionStatus::Failed);
    EXPECT_EQ(readFile(root.path() / "entry.txt"), "previous");
    EXPECT_NE(result.error.find("expected size -1"), std::string::npos);
    EXPECT_EQ(extractor.extractionCalls(), 1);
    EXPECT_FALSE(hasTemporaryExtractionFile(root.path()));
}

TEST(FileExtractorTextDumpAtomic, PreservesFinalWhenWriterFails) {
    ScopedDirectory root(temporaryRoot("atomic-writer-failure"));
    fs::create_directories(root.path());
    {
        std::ofstream finalFile(root.path() / "entry.txt", std::ios::binary);
        finalFile << "previous";
    }
    ControlledFileExtractor extractor("temporary", false);

    const auto result = extractor.extractRecordAtomically(
        recordFor("/entry.txt", 9), root.path());

    EXPECT_EQ(result.status, FileExtractor::AtomicExtractionStatus::Failed);
    EXPECT_EQ(readFile(root.path() / "entry.txt"), "previous");
    EXPECT_EQ(extractor.extractionCalls(), 1);
    EXPECT_FALSE(hasTemporaryExtractionFile(root.path()));
}

TEST(FileExtractorTextDumpAtomic, ReplacesMismatchedFinalAfterCompleteWrite) {
    ScopedDirectory root(temporaryRoot("atomic-replace"));
    fs::create_directories(root.path());
    {
        std::ofstream finalFile(root.path() / "entry.txt", std::ios::binary);
        finalFile << "old";
    }
    ControlledFileExtractor extractor("fresh", true);

    const auto result = extractor.extractRecordAtomically(
        recordFor("/entry.txt", 5), root.path());

    EXPECT_EQ(result.status, FileExtractor::AtomicExtractionStatus::Extracted);
    EXPECT_EQ(result.previous_bytes, 3U);
    EXPECT_EQ(result.output_bytes, 5U);
    EXPECT_EQ(readFile(root.path() / "entry.txt"), "fresh");
    EXPECT_EQ(extractor.extractionCalls(), 1);
    EXPECT_FALSE(hasTemporaryExtractionFile(root.path()));
}

TEST(FileExtractorTextDumpAtomic, RejectsUnsafeStaticSymlinkBeforeWriting) {
    ScopedDirectory root(temporaryRoot("atomic-unsafe-root"));
    ScopedDirectory outside(temporaryRoot("atomic-unsafe-outside"));
    fs::create_directories(root.path());
    fs::create_directories(outside.path());
    REQUIRE_SYMLINK_CREATED(
        createDirectorySymlink(outside.path(), root.path() / "linked"));
    ControlledFileExtractor extractor("unsafe", true);

    const auto result = extractor.extractRecordAtomically(
        recordFor("/linked/entry.txt", 6), root.path());

    EXPECT_EQ(result.status, FileExtractor::AtomicExtractionStatus::Failed);
    EXPECT_EQ(extractor.extractionCalls(), 0);
    EXPECT_FALSE(hasTemporaryExtractionFile(root.path()));
}

} // namespace
