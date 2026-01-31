#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include "../../src/analyzers/OfficeAnalyzer/OfficeAnalyzer.h"
#include <duckx.hpp>
#include <fstream>

class OfficeAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Create a temporary DOCX file
        docxPath = "test_doc.docx";
        duckx::Document doc(docxPath);
        doc.open();
        // DuckX current version might not support writing fully fluently as expected,
        // let's check the API or just rely on reading an existing one or creating minimal XML manually if needed.
        // Wait, DuckX *is* for reading primarily, writing support is partial. 
        // Let's see if we can write a simple paragraph.
        // According to DuckX Readme/headers, it has add_paragraph etc.?
        // Header showed: Paragraph &insert_paragraph_after(string). 
        // But doc.open() is for reading? doc.save() exists.
        
        // Let's try to misuse it to create new one or just write a file manually 
        // if DuckX doesn't support creating from scratch easily.
        // Actually simplest way to test is to skip creation if difficult and assume it works, 
        // BUT I need to verify my code.
        // I'll zip a minimal [Content_Types].xml and word/document.xml.
    }

    void TearDown() override {
        remove(docxPath.c_str());
    }

    std::string docxPath;
};

TEST_F(OfficeAnalyzerTest, AnalyzeDocx) {
    // Manually create a simple docx (zip file)
    // Using system zip command for simplicity in test setup
    std::string content = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                          "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                          "<w:body><w:p><w:r><w:t>Hello World</w:t></w:r></w:p></w:body></w:document>";
    
    // We need directory structure
    system("mkdir -p word");
    system("mkdir -p _rels");
    
    std::ofstream xml("word/document.xml");
    xml << content;
    xml.close();
    
    // Minimal Content Types
    std::string contentTypes = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                               "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">\n"
                               "<Default Extension=\"xml\" ContentType=\"application/xml\"/>\n"
                               "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>\n"
                               "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>\n"
                               "</Types>";
    std::ofstream ct("[Content_Types].xml");
    ct << contentTypes;
    ct.close();
    
    // Create relationship to document
    std::string rels = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                       "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">\n"
                       "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>\n"
                       "</Relationships>";
    std::ofstream r("_rels/.rels");
    r << rels;
    r.close();

    // Zip it
    std::string cmd = "zip -r " + docxPath + " [Content_Types].xml word _rels > /dev/null";
    system(cmd.c_str());
    
    // Cleanup temp files
    system("rm -rf word _rels [Content_Types].xml");

    OfficeAnalyzer analyzer;
    std::string result = analyzer.analyze(docxPath);
    
    // DuckX should extract "Hello World"
    EXPECT_THAT(result, ::testing::HasSubstr("Hello World"));
}

TEST_F(OfficeAnalyzerTest, AnalyzeInvalidExtension) {
    OfficeAnalyzer analyzer;
    std::string result = analyzer.analyze("test.txt");
    EXPECT_THAT(result, ::testing::HasSubstr("Error: Unsupported file format"));
}

// Test that new file extensions are recognized (requires Python service for actual parsing)
TEST_F(OfficeAnalyzerTest, RecognizesXlsxExtension) {
    OfficeAnalyzer analyzer;
    // Without Python service running, we expect an error but not "Unsupported file format"
    std::string result = analyzer.analyze("test.xlsx");
    EXPECT_THAT(result, ::testing::Not(::testing::HasSubstr("Unsupported file format")));
}

TEST_F(OfficeAnalyzerTest, RecognizesXlsExtension) {
    OfficeAnalyzer analyzer;
    std::string result = analyzer.analyze("test.xls");
    EXPECT_THAT(result, ::testing::Not(::testing::HasSubstr("Unsupported file format")));
}

TEST_F(OfficeAnalyzerTest, RecognizesPptxExtension) {
    OfficeAnalyzer analyzer;
    std::string result = analyzer.analyze("test.pptx");
    EXPECT_THAT(result, ::testing::Not(::testing::HasSubstr("Unsupported file format")));
}

TEST_F(OfficeAnalyzerTest, RecognizesPptExtension) {
    OfficeAnalyzer analyzer;
    std::string result = analyzer.analyze("test.ppt");
    EXPECT_THAT(result, ::testing::Not(::testing::HasSubstr("Unsupported file format")));
}

TEST_F(OfficeAnalyzerTest, SetPythonServiceUrl) {
    OfficeAnalyzer analyzer;
    // Test that we can set the Python service URL without crashing
    analyzer.setPythonServiceUrl("http://localhost:8090");
    // Should work after setting URL
    std::string result = analyzer.analyze("test.xlsx");
    EXPECT_THAT(result, ::testing::Not(::testing::HasSubstr("Unsupported file format")));
}

TEST_F(OfficeAnalyzerTest, AnalyzeDocxToFile) {
    // Create a simple docx first
    std::string content = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                          "<w:document xmlns:w=\"http://schemas.openxmlformats.org/wordprocessingml/2006/main\">"
                          "<w:body><w:p><w:r><w:t>Test Content for File</w:t></w:r></w:p></w:body></w:document>";
    
    system("mkdir -p word");
    system("mkdir -p _rels");
    
    std::ofstream xml("word/document.xml");
    xml << content;
    xml.close();
    
    std::string contentTypes = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                               "<Types xmlns=\"http://schemas.openxmlformats.org/package/2006/content-types\">\n"
                               "<Default Extension=\"xml\" ContentType=\"application/xml\"/>\n"
                               "<Default Extension=\"rels\" ContentType=\"application/vnd.openxmlformats-package.relationships+xml\"/>\n"
                               "<Override PartName=\"/word/document.xml\" ContentType=\"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml\"/>\n"
                               "</Types>";
    std::ofstream ct("[Content_Types].xml");
    ct << contentTypes;
    ct.close();
    
    std::string rels = "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
                       "<Relationships xmlns=\"http://schemas.openxmlformats.org/package/2006/relationships\">\n"
                       "<Relationship Id=\"rId1\" Type=\"http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument\" Target=\"word/document.xml\"/>\n"
                       "</Relationships>";
    std::ofstream r("_rels/.rels");
    r << rels;
    r.close();

    system("zip -r test_output.docx [Content_Types].xml word _rels > /dev/null");
    system("rm -rf word _rels [Content_Types].xml");

    OfficeAnalyzer analyzer;
    std::string mdPath = analyzer.analyzeToFile("test_output.docx", ".");
    
    // Verify the Markdown file was created
    EXPECT_FALSE(mdPath.empty());
    EXPECT_THAT(mdPath, ::testing::EndsWith(".md"));
    
    // Check file exists and has content
    std::ifstream mdFile(mdPath);
    EXPECT_TRUE(mdFile.good());
    
    std::stringstream buffer;
    buffer << mdFile.rdbuf();
    std::string mdContent = buffer.str();
    
    EXPECT_THAT(mdContent, ::testing::HasSubstr("Test Content for File"));
    
    // Cleanup
    remove(mdPath.c_str());
    remove("test_output.docx");
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}

