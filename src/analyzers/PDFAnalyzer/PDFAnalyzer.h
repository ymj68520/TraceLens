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

class PDFAnalyzer {
public:
    static std::string extractText(const std::string& pdfPath);
    static PDFMetadata extractMetadata(const std::string& pdfPath);
    
    // Generates a comprehensive markdown report for LLM Analysis
    // Returns true if successful, false otherwise.
    static bool createLLMReport(const std::string& pdfPath, const std::string& outputPath);

private:
    static std::string cleanText(const std::string& text);
};

} // namespace analyzers
} // namespace forensics

#endif // PDF_ANALYZER_H
