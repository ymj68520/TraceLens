#ifndef PDF_ANALYZER_H
#define PDF_ANALYZER_H

#include <string>
#include <vector>

namespace forensics {
namespace analyzers {

struct PDFMetadata {
    std::string title;
    std::string author;
    std::string subject;
    std::string keywords;
    std::string creator;
    std::string producer;
    int pageCount = 0;
    std::vector<std::string> permissions;
    int64_t creationTime = 0;
    int64_t modificationTime = 0;
    bool isEncrypted = false;
};

/**
 * @brief Analyzes PDF documents
 * Extracts text, metadata, and generates LLM reports.
 */
class PDFAnalyzer {
public:
    /**
     * @brief Extract raw text from PDF
     * @param pdfPath Path to PDF file
     * @return Extracted text content
     */
    static std::string extractText(const std::string& pdfPath);

    /**
     * @brief Extract PDF metadata
     * @param pdfPath Path to PDF file
     * @return PDFMetadata structure
     */
    static PDFMetadata extractMetadata(const std::string& pdfPath);
    
    /**
     * @brief Generate comprehensive markdown report for LLM Analysis
     * @param pdfPath Path to PDF file
     * @param outputPath Path to write the report
     * @return true if successful
     */
    static bool createLLMReport(const std::string& pdfPath, const std::string& outputPath);

private:
    static std::string cleanText(const std::string& text);
};

} // namespace analyzers
} // namespace forensics

#endif // PDF_ANALYZER_H
