// test_file_carving.cpp
// GTest-based unit tests for FileCarving module
// Tests file signature detection, carving statistics, and file validation

#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <vector>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <string>

#include "FileCarving/FileCarver.h"

namespace fs = std::filesystem;

class TestableFileCarver : public FileCarver {
public:
    bool validate(const std::string& path, const CarvingSignature& signature,
                  std::string& message) {
        return validateCarvedFile(path, signature, message);
    }
};

using ::testing::Eq;
using ::testing::Ge;
using ::testing::Le;
using ::testing::Not;
using ::testing::IsEmpty;

// ============================================================================
// CarvingSignature Tests
// ============================================================================

class CarvingSignatureTest : public ::testing::Test {};

TEST_F(CarvingSignatureTest, ConstructedSignature) {
    CarvingSignature sig{};
    sig.name = "";
    sig.extension = "";
    sig.maxSize = 0;
    
    EXPECT_TRUE(sig.name.empty());
    EXPECT_TRUE(sig.extension.empty());
    EXPECT_TRUE(sig.header.empty());
    EXPECT_TRUE(sig.footer.empty());
    EXPECT_EQ(sig.maxSize, 0u);
    EXPECT_EQ(sig.headerOffset, 0);
    EXPECT_FALSE(sig.hasFixedSize);
}

TEST_F(CarvingSignatureTest, JPEGSignature) {
    CarvingSignature sig;
    sig.name = "JPEG";
    sig.extension = "jpg";
    sig.header = {0xFF, 0xD8, 0xFF};  // JPEG magic bytes
    sig.footer = {0xFF, 0xD9};        // JPEG end marker
    sig.maxSize = 50 * 1024 * 1024;   // 50MB max
    
    EXPECT_EQ(sig.name, "JPEG");
    EXPECT_EQ(sig.extension, "jpg");
    EXPECT_EQ(sig.header.size(), 3u);
    EXPECT_EQ(sig.header[0], 0xFF);
    EXPECT_EQ(sig.header[1], 0xD8);
    EXPECT_FALSE(sig.footer.empty());
}

TEST_F(CarvingSignatureTest, PNGSignature) {
    CarvingSignature sig;
    sig.name = "PNG";
    sig.extension = "png";
    sig.header = {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};  // PNG magic
    sig.footer = {0x49, 0x45, 0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82};  // IEND chunk
    sig.maxSize = 100 * 1024 * 1024;  // 100MB max
    
    EXPECT_EQ(sig.header.size(), 8u);
    EXPECT_EQ(sig.footer.size(), 8u);
}

TEST_F(CarvingSignatureTest, PDFSignature) {
    CarvingSignature sig;
    sig.name = "PDF";
    sig.extension = "pdf";
    sig.header = {0x25, 0x50, 0x44, 0x46};  // %PDF
    sig.footer = {0x25, 0x25, 0x45, 0x4F, 0x46};  // %%EOF
    sig.maxSize = 500 * 1024 * 1024;  // 500MB max
    
    EXPECT_EQ(sig.name, "PDF");
    EXPECT_EQ(sig.header[0], '%');
    EXPECT_EQ(sig.header[1], 'P');
}

TEST_F(CarvingSignatureTest, ZIPSignature) {
    CarvingSignature sig;
    sig.name = "ZIP";
    sig.extension = "zip";
    sig.header = {0x50, 0x4B, 0x03, 0x04};  // PK..
    sig.maxSize = 1024 * 1024 * 1024;  // 1GB max
    
    EXPECT_EQ(sig.header[0], 'P');
    EXPECT_EQ(sig.header[1], 'K');
}

// ============================================================================
// CarvedFileInfo Tests
// ============================================================================

class CarvedFileInfoTest : public ::testing::Test {};

TEST_F(CarvedFileInfoTest, EmptyStrings) {
    CarvedFileInfo info{};
    info.sourceOffset = 0;
    info.size = 0;
    info.validated = false;
    
    EXPECT_TRUE(info.path.empty());
    EXPECT_TRUE(info.signatureName.empty());
    EXPECT_TRUE(info.extension.empty());
    EXPECT_EQ(info.sourceOffset, 0u);
    EXPECT_EQ(info.size, 0u);
    EXPECT_FALSE(info.validated);
    EXPECT_TRUE(info.validationMessage.empty());
}

TEST_F(CarvedFileInfoTest, PopulatedInfo) {
    CarvedFileInfo info{};
    info.path = "/output/carved_001.jpg";
    info.signatureName = "JPEG";
    info.extension = "jpg";
    info.sourceOffset = 1024000;
    info.size = 256000;
    info.validated = true;
    info.validationMessage = "Valid JPEG file";
    
    EXPECT_EQ(info.path, "/output/carved_001.jpg");
    EXPECT_EQ(info.signatureName, "JPEG");
    EXPECT_EQ(info.sourceOffset, 1024000u);
    EXPECT_EQ(info.size, 256000u);
    EXPECT_TRUE(info.validated);
}

// ============================================================================
// CarvingStatistics Tests
// ============================================================================

class CarvingStatisticsTest : public ::testing::Test {};

TEST_F(CarvingStatisticsTest, DefaultStatistics) {
    CarvingStatistics stats;
    
    EXPECT_EQ(stats.totalFilesCarved, 0);
    EXPECT_EQ(stats.totalBytesCarved, 0u);
    EXPECT_EQ(stats.validFiles, 0);
    EXPECT_EQ(stats.invalidFiles, 0);
    EXPECT_EQ(stats.errors, 0);
    EXPECT_TRUE(stats.filesByType.empty());
    EXPECT_EQ(stats.elapsedSeconds, 0.0);
    EXPECT_EQ(stats.blocksScanned, 0u);
    EXPECT_EQ(stats.unallocatedBlocks, 0u);
}

TEST_F(CarvingStatisticsTest, PopulatedStatistics) {
    CarvingStatistics stats;
    stats.totalFilesCarved = 150;
    stats.totalBytesCarved = 1024 * 1024 * 500;  // 500MB
    stats.validFiles = 140;
    stats.invalidFiles = 10;
    stats.errors = 2;
    stats.filesByType["JPEG"] = 100;
    stats.filesByType["PNG"] = 30;
    stats.filesByType["PDF"] = 20;
    stats.elapsedSeconds = 45.5;
    stats.blocksScanned = 1000000;
    stats.unallocatedBlocks = 50000;
    
    EXPECT_EQ(stats.totalFilesCarved, 150);
    EXPECT_EQ(stats.validFiles + stats.invalidFiles, 150);
    EXPECT_EQ(stats.filesByType.size(), 3u);
    EXPECT_EQ(stats.filesByType["JPEG"], 100);
    EXPECT_THAT(stats.elapsedSeconds, Ge(0.0));
}

TEST_F(CarvingStatisticsTest, FilesByTypeAccumulation) {
    CarvingStatistics stats;
    
    stats.filesByType["JPEG"]++;
    stats.filesByType["JPEG"]++;
    stats.filesByType["PNG"]++;
    
    EXPECT_EQ(stats.filesByType["JPEG"], 2);
    EXPECT_EQ(stats.filesByType["PNG"], 1);
}

// ============================================================================
// FileCarver Tests
// ============================================================================

class FileCarverTest : public ::testing::Test {
protected:
    FileCarver carver;
};

TEST_F(FileCarverTest, ConstructorInitializesSignatures) {
    const auto& signatures = carver.getSignatures();
    
    // Carver should have some built-in signatures
    EXPECT_FALSE(signatures.empty());
}

TEST_F(FileCarverTest, SignaturesContainCommonFormats) {
    const auto& signatures = carver.getSignatures();
    
    bool hasJPEG = false;
    bool hasPNG = false;
    bool hasPDF = false;
    
    for (const auto& sig : signatures) {
        if (sig.name == "JPEG" || sig.extension == "jpg") hasJPEG = true;
        if (sig.name == "PNG" || sig.extension == "png") hasPNG = true;
        if (sig.name == "PDF" || sig.extension == "pdf") hasPDF = true;
    }
    
    EXPECT_TRUE(hasJPEG) << "FileCarver should have JPEG signature";
    EXPECT_TRUE(hasPNG) << "FileCarver should have PNG signature";
    EXPECT_TRUE(hasPDF) << "FileCarver should have PDF signature";
}

TEST_F(FileCarverTest, AddCustomSignature) {
    CarvingSignature customSig;
    customSig.name = "CustomFormat";
    customSig.extension = "cust";
    customSig.header = {0xCA, 0xFE, 0xBA, 0xBE};
    customSig.maxSize = 10 * 1024 * 1024;
    
    size_t initialCount = carver.getSignatures().size();
    carver.addSignature(customSig);
    
    EXPECT_EQ(carver.getSignatures().size(), initialCount + 1);
    
    // Find the custom signature
    bool found = false;
    for (const auto& sig : carver.getSignatures()) {
        if (sig.name == "CustomFormat") {
            found = true;
            EXPECT_EQ(sig.extension, "cust");
            break;
        }
    }
    EXPECT_TRUE(found);
}

TEST_F(FileCarverTest, InitiallyNoCarvedFiles) {
    EXPECT_TRUE(carver.getCarvedFiles().empty());
}

TEST_F(FileCarverTest, InitialStatisticsAreZero) {
    const auto& stats = carver.getStatistics();
    
    EXPECT_EQ(stats.totalFilesCarved, 0);
    EXPECT_EQ(stats.totalBytesCarved, 0u);
}

TEST_F(FileCarverTest, SetValidationEnabled) {
    // Should not throw
    carver.setValidationEnabled(true);
    carver.setValidationEnabled(false);
    SUCCEED();
}

TEST_F(FileCarverTest, SetDatabasePath) {
    // Should not throw
    carver.setDatabasePath("/tmp/test_carving.db");
    SUCCEED();
}

TEST_F(FileCarverTest, SetProgressCallback) {
    bool callbackCalled = false;
    carver.setProgressCallback([&](uint64_t current, uint64_t total, const std::string& file) {
        callbackCalled = true;
    });
    
    // Callback is set, but won't be called until carve() is invoked
    SUCCEED();
}

TEST(FileCarverValidationTest, ValidatesCompleteJpeg) {
    const fs::path path = fs::temp_directory_path() / "tracelens_valid.jpg";
    {
        std::ofstream output(path, std::ios::binary);
        output.write("\xFF\xD8\xFF", 3);
        output.write("test", 4);
        output.write("\xFF\xD9", 2);
    }

    CarvingSignature signature{"JPEG Image", "jpg", {0xFF, 0xD8, 0xFF},
                               {0xFF, 0xD9}, 1024};
    TestableFileCarver carver;
    std::string message;

    EXPECT_TRUE(carver.validate(path.string(), signature, message));
    EXPECT_EQ(message, "Valid JPEG");
    fs::remove(path);
}

TEST(FileCarverValidationTest, DoesNotValidateVideoWithoutContainerParser) {
    const fs::path path = fs::temp_directory_path() / "tracelens_candidate.mp4";
    {
        std::ofstream output(path, std::ios::binary);
        output.write("\x00\x00\x00\x18" "ftypisom", 12);
    }

    CarvingSignature signature{"MP4/MOV Video", "mp4", {0x66, 0x74, 0x79, 0x70},
                               {}, 1024, -4};
    TestableFileCarver carver;
    std::string message;

    EXPECT_FALSE(carver.validate(path.string(), signature, message));
    EXPECT_EQ(message, "No content validator for this type");
    fs::remove(path);
}

TEST(FileCarverValidationTest, DoesNotValidateUnknownFormat) {
    const fs::path path = fs::temp_directory_path() / "tracelens_candidate.bin";
    {
        std::ofstream output(path, std::ios::binary);
        output << "candidate data";
    }

    CarvingSignature signature{"Unknown", "bin", {0x00}, {}, 1024};
    TestableFileCarver carver;
    std::string message;

    EXPECT_FALSE(carver.validate(path.string(), signature, message));
    EXPECT_EQ(message, "No content validator for this type");
    fs::remove(path);
}

// ============================================================================
// Signature Magic Bytes Verification
// ============================================================================

class MagicBytesTest : public ::testing::Test {};

TEST_F(MagicBytesTest, JPEGMagicBytes) {
    std::vector<uint8_t> jpegHeader = {0xFF, 0xD8, 0xFF, 0xE0};
    
    EXPECT_EQ(jpegHeader[0], 0xFF);
    EXPECT_EQ(jpegHeader[1], 0xD8);
}

TEST_F(MagicBytesTest, PNGMagicBytes) {
    std::vector<uint8_t> pngHeader = {0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A};
    
    // ASCII: .PNG....
    EXPECT_EQ(pngHeader[0], 0x89);
    EXPECT_EQ(pngHeader[1], 'P');
    EXPECT_EQ(pngHeader[2], 'N');
    EXPECT_EQ(pngHeader[3], 'G');
}

TEST_F(MagicBytesTest, PDFMagicBytes) {
    std::vector<uint8_t> pdfHeader = {'%', 'P', 'D', 'F', '-'};
    
    EXPECT_EQ(pdfHeader[0], '%');
    EXPECT_EQ(pdfHeader[1], 'P');
    EXPECT_EQ(pdfHeader[2], 'D');
    EXPECT_EQ(pdfHeader[3], 'F');
}

TEST_F(MagicBytesTest, ZIPMagicBytes) {
    std::vector<uint8_t> zipHeader = {0x50, 0x4B, 0x03, 0x04};
    
    // ASCII: PK..
    EXPECT_EQ(zipHeader[0], 'P');
    EXPECT_EQ(zipHeader[1], 'K');
}

TEST_F(MagicBytesTest, GIFMagicBytes) {
    // GIF87a or GIF89a
    std::vector<uint8_t> gifHeader89a = {'G', 'I', 'F', '8', '9', 'a'};
    std::vector<uint8_t> gifHeader87a = {'G', 'I', 'F', '8', '7', 'a'};
    
    EXPECT_EQ(gifHeader89a[0], 'G');
    EXPECT_EQ(gifHeader89a[1], 'I');
    EXPECT_EQ(gifHeader89a[2], 'F');
    EXPECT_EQ(gifHeader87a[4], '7');
    EXPECT_EQ(gifHeader89a[4], '9');
}

TEST_F(MagicBytesTest, MP3MagicBytes) {
    // ID3 tag or sync word
    std::vector<uint8_t> id3Header = {'I', 'D', '3'};
    std::vector<uint8_t> mp3SyncWord = {0xFF, 0xFB};  // MPEG Audio Layer 3
    
    EXPECT_EQ(id3Header[0], 'I');
    EXPECT_EQ(id3Header[1], 'D');
    EXPECT_EQ(mp3SyncWord[0], 0xFF);
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
