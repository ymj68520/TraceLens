#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <filesystem>
#include <fstream>
#include "analyzers/PDFAnalyzer/PDFAnalyzer.h"

namespace fs = std::filesystem;

class PDFAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Setup test paths
        testResourceDir = fs::current_path() / "TestResources";
        pdfPath = testResourceDir / "Codex_io_ML.pdf";
        outputPath = fs::current_path() / "test_report.md";
        
        // Ensure test resource exists
        if (!fs::exists(pdfPath)) {
            // If running from build dir, path might be different
             // Try common locations
             if (fs::exists("../tests/TestResources/Codex_io_ML.pdf")) {
                 pdfPath = "../tests/TestResources/Codex_io_ML.pdf";
             } else if (fs::exists("../../tests/TestResources/Codex_io_ML.pdf")) {
                 pdfPath = "../../tests/TestResources/Codex_io_ML.pdf";
             }
        }
    }

    void TearDown() override {
        // Cleanup generated report
        if (fs::exists(outputPath)) {
            fs::remove(outputPath);
        }
    }

    fs::path testResourceDir;
    fs::path pdfPath;
    fs::path outputPath;
};

// Test Metadata Extraction
TEST_F(PDFAnalyzerTest, ExtractMetadata) {
    if (!fs::exists(pdfPath)) {
        GTEST_SKIP() << "Test PDF not found at " << pdfPath;
    }

    auto meta = forensics::analyzers::PDFAnalyzer::extractMetadata(pdfPath.string());
    
    // Check known values for "Codex_io_ML.pdf"
    EXPECT_EQ(meta.title, "Codex_io_ML");
    EXPECT_FALSE(meta.isEncrypted);
    EXPECT_GT(meta.pageCount, 0); // Should be 3 based on manual test
    EXPECT_EQ(meta.pageCount, 3);
}

// Test Text Extraction
TEST_F(PDFAnalyzerTest, ExtractText) {
    if (!fs::exists(pdfPath)) {
        GTEST_SKIP() << "Test PDF not found at " << pdfPath;
    }

    std::string text = forensics::analyzers::PDFAnalyzer::extractText(pdfPath.string());
    
    EXPECT_FALSE(text.empty());
    // Check for presence of known text content
    EXPECT_THAT(text, ::testing::HasSubstr("Machine Learning"));
    EXPECT_THAT(text, ::testing::HasSubstr("Alan Turing"));
    
    // Check for page delimiters
    EXPECT_THAT(text, ::testing::HasSubstr("--- Page 1 ---"));
    EXPECT_THAT(text, ::testing::HasSubstr("--- Page 2 ---"));
}

// Test Report Generation
TEST_F(PDFAnalyzerTest, CreateLLMReport) {
    if (!fs::exists(pdfPath)) {
        GTEST_SKIP() << "Test PDF not found at " << pdfPath;
    }

    bool success = forensics::analyzers::PDFAnalyzer::createLLMReport(pdfPath.string(), outputPath.string());
    EXPECT_TRUE(success);
    EXPECT_TRUE(fs::exists(outputPath));
    
    // Verify content of generated report
    std::ifstream f(outputPath);
    std::stringstream buffer;
    buffer << f.rdbuf();
    std::string content = buffer.str();
    
    EXPECT_THAT(content, ::testing::HasSubstr("# PDF Analysis Report"));
    EXPECT_THAT(content, ::testing::HasSubstr("**File**: Codex_io_ML.pdf"));
    EXPECT_THAT(content, ::testing::HasSubstr("## Metadata"));
    EXPECT_THAT(content, ::testing::HasSubstr("## Content"));
    EXPECT_THAT(content, ::testing::HasSubstr("### Page 1"));
}

// Test Error Handling (Non-existent file)
TEST_F(PDFAnalyzerTest, HandleNonExistentFile) {
    std::string badPath = "non_existent_file.pdf";
    
    auto meta = forensics::analyzers::PDFAnalyzer::extractMetadata(badPath);
    EXPECT_EQ(meta.pageCount, 0);
    
    std::string text = forensics::analyzers::PDFAnalyzer::extractText(badPath);
    EXPECT_TRUE(text.empty());
    
    bool result = forensics::analyzers::PDFAnalyzer::createLLMReport(badPath, outputPath.string());
    EXPECT_FALSE(result);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
