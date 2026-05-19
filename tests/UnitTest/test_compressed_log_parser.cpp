// test_compressed_log_parser.cpp
// Unit tests for CompressedLogParser

#ifdef linux
#undef linux
#endif

#include <gtest/gtest.h>
#include <fstream>
#include <filesystem>
#include "Parsers/CompressedLogParser.h"

namespace fs = std::filesystem;
using namespace forensics::linux;

class CompressedLogParserTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Create temporary test directory
        testDir_ = fs::temp_directory_path() / "compressed_log_test";
        fs::create_directories(testDir_);
    }

    void TearDown() override {
        // Clean up test directory
        fs::remove_all(testDir_);
    }

    // Helper to create a test file
    void createTestFile(const std::string& filename, const std::string& content) {
        std::ofstream file(testDir_ / filename);
        file << content;
        file.close();
    }

    fs::path testDir_;
};

// ============================================================================
// Compression type identification tests
// ============================================================================

TEST_F(CompressedLogParserTest, IdentifyGzipByExtension) {
    EXPECT_EQ(CompressedLogParser::identifyCompression("auth.log.gz"), CompressionType::GZIP);
    EXPECT_EQ(CompressedLogParser::identifyCompression("syslog.1.gz"), CompressionType::GZIP);
}

TEST_F(CompressedLogParserTest, IdentifyXzByExtension) {
    EXPECT_EQ(CompressedLogParser::identifyCompression("auth.log.xz"), CompressionType::XZ);
    EXPECT_EQ(CompressedLogParser::identifyCompression("audit.log.2.xz"), CompressionType::XZ);
}

TEST_F(CompressedLogParserTest, IdentifyBzip2ByExtension) {
    EXPECT_EQ(CompressedLogParser::identifyCompression("auth.log.bz2"), CompressionType::BZIP2);
}

TEST_F(CompressedLogParserTest, IdentifyZstdByExtension) {
    EXPECT_EQ(CompressedLogParser::identifyCompression("auth.log.zst"), CompressionType::ZSTD);
}

TEST_F(CompressedLogParserTest, IdentifyNoneForPlainFile) {
    EXPECT_EQ(CompressedLogParser::identifyCompression("auth.log"), CompressionType::NONE);
    EXPECT_EQ(CompressedLogParser::identifyCompression("syslog"), CompressionType::NONE);
}

TEST_F(CompressedLogParserTest, IdentifyUnknownForOtherExtension) {
    EXPECT_EQ(CompressedLogParser::identifyCompression("auth.log.zip"), CompressionType::UNKNOWN);
}

// ============================================================================
// Rotation pattern detection tests
// ============================================================================

TEST_F(CompressedLogParserTest, IsRotatedLogSimple) {
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("auth.log.1"));
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("syslog.2"));
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("kern.log.3"));
}

TEST_F(CompressedLogParserTest, IsRotatedLogCompressed) {
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("auth.log.1.gz"));
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("syslog.2.xz"));
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("audit.log.3.bz2"));
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("messages.1.zst"));
}

TEST_F(CompressedLogParserTest, IsRotatedLogDateBased) {
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("messages-20240101"));
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("messages-20240101.gz"));
    EXPECT_TRUE(CompressedLogParser::isRotatedLog("syslog.20240101"));
}

TEST_F(CompressedLogParserTest, IsNotRotatedLog) {
    EXPECT_FALSE(CompressedLogParser::isRotatedLog("auth.log"));
    EXPECT_FALSE(CompressedLogParser::isRotatedLog("syslog"));
    EXPECT_FALSE(CompressedLogParser::isRotatedLog("."));
    EXPECT_FALSE(CompressedLogParser::isRotatedLog(".."));
}

// ============================================================================
// Base name extraction tests
// ============================================================================

TEST_F(CompressedLogParserTest, GetBaseNameSimple) {
    EXPECT_EQ(CompressedLogParser::getBaseName("auth.log.1"), "auth.log");
    EXPECT_EQ(CompressedLogParser::getBaseName("syslog.2"), "syslog");
}

TEST_F(CompressedLogParserTest, GetBaseNameCompressed) {
    EXPECT_EQ(CompressedLogParser::getBaseName("auth.log.1.gz"), "auth.log");
    EXPECT_EQ(CompressedLogParser::getBaseName("syslog.2.xz"), "syslog");
}

TEST_F(CompressedLogParserTest, GetBaseNameDateBased) {
    EXPECT_EQ(CompressedLogParser::getBaseName("messages-20240101"), "messages");
    EXPECT_EQ(CompressedLogParser::getBaseName("messages-20240101.gz"), "messages");
}

// ============================================================================
// Rotation index extraction tests
// ============================================================================

TEST_F(CompressedLogParserTest, ParseRotationIndexSimple) {
    EXPECT_EQ(CompressedLogParser::parseRotationIndex("auth.log.1"), 1);
    EXPECT_EQ(CompressedLogParser::parseRotationIndex("syslog.2"), 2);
    EXPECT_EQ(CompressedLogParser::parseRotationIndex("kern.log.10"), 10);
}

TEST_F(CompressedLogParserTest, ParseRotationIndexCompressed) {
    EXPECT_EQ(CompressedLogParser::parseRotationIndex("auth.log.1.gz"), 1);
    EXPECT_EQ(CompressedLogParser::parseRotationIndex("syslog.2.xz"), 2);
}

TEST_F(CompressedLogParserTest, ParseRotationIndexInvalid) {
    EXPECT_EQ(CompressedLogParser::parseRotationIndex("auth.log"), -1);
    EXPECT_EQ(CompressedLogParser::parseRotationIndex("messages-20240101"), -1);
}

// ============================================================================
// Date suffix extraction tests
// ============================================================================

TEST_F(CompressedLogParserTest, ParseDateSuffixDash) {
    EXPECT_EQ(CompressedLogParser::parseDateSuffix("messages-20240101"), "20240101");
    EXPECT_EQ(CompressedLogParser::parseDateSuffix("messages-20240101.gz"), "20240101");
}

TEST_F(CompressedLogParserTest, ParseDateSuffixDot) {
    EXPECT_EQ(CompressedLogParser::parseDateSuffix("syslog.20240101"), "20240101");
}

TEST_F(CompressedLogParserTest, ParseDateSuffixNone) {
    EXPECT_EQ(CompressedLogParser::parseDateSuffix("auth.log.1"), "");
    EXPECT_EQ(CompressedLogParser::parseDateSuffix("syslog"), "");
}

// ============================================================================
// Compression type string conversion tests
// ============================================================================

TEST_F(CompressedLogParserTest, CompressionTypeToString) {
    EXPECT_EQ(CompressedLogParser::compressionTypeToString(CompressionType::NONE), "none");
    EXPECT_EQ(CompressedLogParser::compressionTypeToString(CompressionType::GZIP), "gzip");
    EXPECT_EQ(CompressedLogParser::compressionTypeToString(CompressionType::XZ), "xz");
    EXPECT_EQ(CompressedLogParser::compressionTypeToString(CompressionType::BZIP2), "bzip2");
    EXPECT_EQ(CompressedLogParser::compressionTypeToString(CompressionType::ZSTD), "zstd");
    EXPECT_EQ(CompressedLogParser::compressionTypeToString(CompressionType::UNKNOWN), "unknown");
}

// ============================================================================
// File enumeration tests
// ============================================================================

TEST_F(CompressedLogParserTest, EnumerateRotatedLogs) {
    // Create test files
    createTestFile("auth.log", "Current auth log");
    createTestFile("auth.log.1", "Previous auth log");
    createTestFile("auth.log.2.gz", "Old compressed auth log");
    createTestFile("syslog", "Current syslog");
    createTestFile("syslog.1", "Previous syslog");
    createTestFile("messages", "Current messages");
    createTestFile("messages-20240101", "Old messages");
    createTestFile("not-a-log.txt", "Not a log file");

    auto logs = CompressedLogParser::enumerateRotatedLogs(testDir_.string());

    // Should find 4 rotated logs (auth.log.1, auth.log.2.gz, syslog.1, messages-20240101)
    EXPECT_GE(logs.size(), 4);

    // Check that we found the expected files
    bool foundAuthLog1 = false;
    bool foundAuthLog2Gz = false;
    bool foundSyslog1 = false;
    bool foundMessagesDate = false;

    for (const auto& log : logs) {
        if (log.originalPath.find("auth.log.1") != std::string::npos) {
            foundAuthLog1 = true;
            EXPECT_EQ(log.baseName, "auth.log");
            EXPECT_EQ(log.rotationIndex, 1);
            EXPECT_FALSE(log.isCompressed);
        }
        if (log.originalPath.find("auth.log.2.gz") != std::string::npos) {
            foundAuthLog2Gz = true;
            EXPECT_EQ(log.baseName, "auth.log");
            EXPECT_EQ(log.rotationIndex, 2);
            EXPECT_TRUE(log.isCompressed);
            EXPECT_EQ(log.compression, CompressionType::GZIP);
        }
        if (log.originalPath.find("syslog.1") != std::string::npos) {
            foundSyslog1 = true;
            EXPECT_EQ(log.baseName, "syslog");
        }
        if (log.originalPath.find("messages-20240101") != std::string::npos) {
            foundMessagesDate = true;
            EXPECT_EQ(log.baseName, "messages");
            EXPECT_TRUE(log.isDateRotated);
            EXPECT_EQ(log.dateSuffix, "20240101");
        }
    }

    EXPECT_TRUE(foundAuthLog1);
    EXPECT_TRUE(foundAuthLog2Gz);
    EXPECT_TRUE(foundSyslog1);
    EXPECT_TRUE(foundMessagesDate);
}

TEST_F(CompressedLogParserTest, EnumerateRotatedLogsForBase) {
    // Create test files
    createTestFile("auth.log", "Current auth log");
    createTestFile("auth.log.1", "Previous auth log");
    createTestFile("auth.log.2.gz", "Old compressed auth log");
    createTestFile("auth.log.3.xz", "Very old compressed auth log");
    createTestFile("syslog", "Current syslog");
    createTestFile("syslog.1", "Previous syslog");

    auto authLogs = CompressedLogParser::enumerateRotatedLogsForBase(testDir_.string(), "auth.log");

    // Should find 3 rotated auth logs
    EXPECT_EQ(authLogs.size(), 3);

    for (const auto& log : authLogs) {
        EXPECT_EQ(log.baseName, "auth.log");
    }
}

// ============================================================================
// Plain text decompression tests
// ============================================================================

TEST_F(CompressedLogParserTest, DecompressPlainText) {
    std::string content = "This is a test log line\nAnother line\n";
    createTestFile("test.log", content);

    std::string result = CompressedLogParser::decompressFile(
        (testDir_ / "test.log").string(), CompressionType::NONE);

    EXPECT_EQ(result, content);
}

// ============================================================================
// Magic byte detection tests
// ============================================================================

TEST_F(CompressedLogParserTest, DetectGzipMagic) {
    // Create a file with gzip magic bytes
    std::ofstream file(testDir_ / "test_magic", std::ios::binary);
    unsigned char gzipMagic[] = {0x1f, 0x8b, 0x08, 0x00};
    file.write(reinterpret_cast<char*>(gzipMagic), sizeof(gzipMagic));
    file.close();

    auto type = CompressedLogParser::identifyCompressionFromMagic(
        (testDir_ / "test_magic").string());
    EXPECT_EQ(type, CompressionType::GZIP);
}

TEST_F(CompressedLogParserTest, DetectNoMagic) {
    createTestFile("test_plain", "Just plain text");

    auto type = CompressedLogParser::identifyCompressionFromMagic(
        (testDir_ / "test_plain").string());
    EXPECT_EQ(type, CompressionType::NONE);
}

// ============================================================================
// File metadata tests
// ============================================================================

TEST_F(CompressedLogParserTest, GetFileMetadata) {
    createTestFile("auth.log.1.gz", "compressed content");

    auto metadata = CompressedLogParser::getFileMetadata(
        (testDir_ / "auth.log.1.gz").string());

    EXPECT_EQ(metadata.baseName, "auth.log");
    EXPECT_EQ(metadata.rotationIndex, 1);
    EXPECT_TRUE(metadata.isCompressed);
    EXPECT_EQ(metadata.compression, CompressionType::GZIP);
    EXPECT_GT(metadata.fileSize, 0);
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
