#ifndef OFFICE_ANALYZER_H
#define OFFICE_ANALYZER_H

#include <string>
#include <vector>

class OfficeAnalyzer {
public:
    OfficeAnalyzer();
    ~OfficeAnalyzer();

    /**
     * @brief Analyze an Office document and return the content as Markdown.
     * Supports: DOCX, DOC, XLSX, XLS, PPTX, PPT
     * @param filePath The absolute path to the file.
     * @return The extracted content in Markdown format.
     */
    std::string analyze(const std::string& filePath);

    /**
     * @brief Analyze an Office document and save the content to a Markdown file.
     * @param filePath The absolute path to the Office file.
     * @param outputDir The directory to save the Markdown file.
     * @return The path to the generated Markdown file, or empty string on error.
     */
    std::string analyzeToFile(const std::string& filePath, const std::string& outputDir = "");

    /**
     * @brief Set the Python service URL for Office parsing.
     * @param url The base URL of the Python service (e.g., "http://localhost:8090")
     */
    void setPythonServiceUrl(const std::string& url);

private:
    std::string pythonServiceUrl_;

    // Word document analysis (local)
    std::string analyzeDocx(const std::string& filePath);
    std::string analyzeDoc(const std::string& filePath);
    
    // Excel analysis (via Python service)
    std::string analyzeXlsx(const std::string& filePath);
    std::string analyzeXls(const std::string& filePath);
    
    // PowerPoint analysis (via Python service)
    std::string analyzePptx(const std::string& filePath);
    std::string analyzePpt(const std::string& filePath);
    
    // Helper to check extensions
    bool hasExtension(const std::string& filePath, const std::string& ext);
    
    // Helper to execute external command (for antiword, catppt)
    std::string execCommand(const std::string& cmd);
    
    // Helper to call Python service
    std::string callPythonService(const std::string& filePath);
    
    // Helper to get base filename without extension
    std::string getBaseName(const std::string& filePath);
    
    // Helper to save content to file
    bool saveToFile(const std::string& content, const std::string& outputPath);
};

#endif // OFFICE_ANALYZER_H
