/**
 * @file test_android_logical_source_gtest.cpp
 * @brief Unit tests for the Android logical-extraction file backends:
 *        LogicalDirExtractor (extracted data/ directory) and
 *        ZipArchiveExtractor (Image.zip via libzip).
 *
 * These verify the IFileExtractor contract used by AndroidAnalyzer when
 * --android-source is `dir` or `zip`: image-relative paths like
 * "data/data/com.foo/databases/foo.db" resolve against the data source and the
 * file content is copied out faithfully, with missing files reported (not
 * crashing) and path-traversal attempts rejected.
 */

#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <string>
#include <cstdlib>

#include "LogicalDirExtractor.h"
#include "ZipArchiveExtractor.h"

namespace fs = std::filesystem;

namespace {

// Create a unique temp working directory for a test.
fs::path makeTempDir(const std::string& tag) {
    fs::path base = fs::temp_directory_path() /
                    ("android_logical_test_" + tag + "_" + std::to_string(::getpid()) +
                     "_" + std::to_string(reinterpret_cast<uintptr_t>(&tag)));
    fs::create_directories(base);
    return base;
}

void writeFile(const fs::path& p, const std::string& content) {
    fs::create_directories(p.parent_path());
    std::ofstream ofs(p, std::ios::binary);
    ofs << content;
}

std::string readFile(const fs::path& p) {
    std::ifstream ifs(p, std::ios::binary);
    return std::string((std::istreambuf_iterator<char>(ifs)),
                       std::istreambuf_iterator<char>());
}

}  // namespace

// ---------------------------------------------------------------------------
// LogicalDirExtractor
// ---------------------------------------------------------------------------

class LogicalDirExtractorTest : public ::testing::Test {
protected:
    fs::path root_;
    fs::path outDir_;

    void SetUp() override {
        root_ = makeTempDir("dir_root");
        outDir_ = makeTempDir("dir_out");
        // Mimic an Android logical extraction layout.
        writeFile(root_ / "data/data/com.foo.app/databases/foo.db", "FOO-DB-CONTENT");
        writeFile(root_ / "data/system/packages.xml", "<packages/>");
    }

    void TearDown() override {
        std::error_code ec;
        fs::remove_all(root_, ec);
        fs::remove_all(outDir_, ec);
    }
};

TEST_F(LogicalDirExtractorTest, InitializeSucceedsForExistingDir) {
    LogicalDirExtractor ex(root_.string());
    EXPECT_TRUE(ex.initialize());
}

TEST_F(LogicalDirExtractorTest, InitializeFailsForMissingDir) {
    LogicalDirExtractor ex((root_ / "does_not_exist").string());
    EXPECT_FALSE(ex.initialize());
}

TEST_F(LogicalDirExtractorTest, ExtractsExistingFileByRelativePath) {
    LogicalDirExtractor ex(root_.string());
    ASSERT_TRUE(ex.initialize());

    fs::path out = outDir_ / "foo.db";
    EXPECT_TRUE(ex.extractFileByPath("data/data/com.foo.app/databases/foo.db", out.string()));
    ASSERT_TRUE(fs::exists(out));
    EXPECT_EQ(readFile(out), "FOO-DB-CONTENT");
}

TEST_F(LogicalDirExtractorTest, ToleratesLeadingSlash) {
    LogicalDirExtractor ex(root_.string());
    ASSERT_TRUE(ex.initialize());

    fs::path out = outDir_ / "pkgs.xml";
    EXPECT_TRUE(ex.extractFileByPath("/data/system/packages.xml", out.string()));
    EXPECT_EQ(readFile(out), "<packages/>");
}

TEST_F(LogicalDirExtractorTest, MissingFileReturnsFalseNotCrash) {
    LogicalDirExtractor ex(root_.string());
    ASSERT_TRUE(ex.initialize());

    fs::path out = outDir_ / "nope.db";
    EXPECT_FALSE(ex.extractFileByPath("data/data/com.absent/databases/x.db", out.string()));
    EXPECT_FALSE(fs::exists(out));
}

TEST_F(LogicalDirExtractorTest, RejectsPathTraversal) {
    // Place a secret outside the root.
    fs::path secret = root_.parent_path() / "secret.txt";
    writeFile(secret, "TOP-SECRET");

    LogicalDirExtractor ex(root_.string());
    ASSERT_TRUE(ex.initialize());

    fs::path out = outDir_ / "leak.txt";
    EXPECT_FALSE(ex.extractFileByPath("data/../../secret.txt", out.string()));
    EXPECT_FALSE(fs::exists(out));

    std::error_code ec;
    fs::remove(secret, ec);
}

// ---------------------------------------------------------------------------
// ZipArchiveExtractor (only meaningful when built with libzip)
// ---------------------------------------------------------------------------

#ifdef HAVE_LIBZIP

class ZipArchiveExtractorTest : public ::testing::Test {
protected:
    fs::path workDir_;
    fs::path zipPath_;
    fs::path outDir_;
    bool zipBuilt_ = false;

    void SetUp() override {
        workDir_ = makeTempDir("zip_work");
        outDir_ = makeTempDir("zip_out");
        zipPath_ = workDir_ / "Image.zip";

        // Stage a small data/ tree then zip it with the system `zip` tool so
        // the test exercises a real archive. If `zip` is unavailable, tests
        // self-skip.
        fs::path stage = workDir_ / "stage";
        writeFile(stage / "data/data/com.bar.app/databases/bar.db", "BAR-DB-XYZ");
        writeFile(stage / "data/system/packages.xml", "<pkgs/>");

        std::string cmd = "cd '" + stage.string() + "' && zip -q -r -X '" +
                          zipPath_.string() + "' data >/dev/null 2>&1";
        int rc = std::system(cmd.c_str());
        zipBuilt_ = (rc == 0 && fs::exists(zipPath_));
    }

    void TearDown() override {
        std::error_code ec;
        fs::remove_all(workDir_, ec);
        fs::remove_all(outDir_, ec);
    }
};

TEST_F(ZipArchiveExtractorTest, InitializeAndExtract) {
    if (!zipBuilt_) GTEST_SKIP() << "system `zip` tool unavailable";

    ZipArchiveExtractor ex(zipPath_.string());
    ASSERT_TRUE(ex.initialize());

    fs::path out = outDir_ / "bar.db";
    EXPECT_TRUE(ex.extractFileByPath("data/data/com.bar.app/databases/bar.db", out.string()));
    ASSERT_TRUE(fs::exists(out));
    EXPECT_EQ(readFile(out), "BAR-DB-XYZ");
}

TEST_F(ZipArchiveExtractorTest, MissingEntryReturnsFalse) {
    if (!zipBuilt_) GTEST_SKIP() << "system `zip` tool unavailable";

    ZipArchiveExtractor ex(zipPath_.string());
    ASSERT_TRUE(ex.initialize());

    fs::path out = outDir_ / "absent.db";
    EXPECT_FALSE(ex.extractFileByPath("data/data/com.absent/databases/x.db", out.string()));
    EXPECT_FALSE(fs::exists(out));
}

TEST_F(ZipArchiveExtractorTest, InitializeFailsForMissingArchive) {
    ZipArchiveExtractor ex((workDir_ / "nonexistent.zip").string());
    EXPECT_FALSE(ex.initialize());
}

#endif  // HAVE_LIBZIP

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
