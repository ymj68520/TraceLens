#ifndef OFFICE_ANALYZER_H
#define OFFICE_ANALYZER_H

#include <string>
#include <vector>

class OfficeAnalyzer {
public:
    OfficeAnalyzer();
    ~OfficeAnalyzer();

    /**
     * @brief Analyze an Office document (DOCX or DOC) and return the content as Markdown.
     * @param filePath The absolute path to the file.
     * @return The extracted content in Markdown format.
     */
    std::string analyze(const std::string& filePath);

private:
    std::string analyzeDocx(const std::string& filePath);
    std::string analyzeDoc(const std::string& filePath);
    
    // Helper to check extensions
    bool hasExtension(const std::string& filePath, const std::string& ext);
    
    // Helper to execute external command (for antiword)
    std::string execCommand(const std::string& cmd);
};

#endif // OFFICE_ANALYZER_H
