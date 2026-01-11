#include "FileAnalyzer.h"
#include "json.hpp"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <chrono>
#include <algorithm>
#include <regex>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace forensics {
namespace llm {

FileAnalyzer::FileAnalyzer(std::shared_ptr<ModelRouter> router)
    : router_(router) {
    initDefaultPrompts();
}

FileAnalyzer::~FileAnalyzer() = default;

void FileAnalyzer::initDefaultPrompts() {
    summaryPrompt_ = 
        "You are a file analysis assistant. Analyze the following content and provide "
        "a concise summary (2-3 sentences) that captures the main purpose and key information. "
        "Be factual and precise.";
    
    descriptionPrompt_ = 
        "Generate a natural language description of this file. Include:\n"
        "- What type of file it is\n"
        "- Its main purpose or content\n"
        "- Any notable characteristics\n"
        "Keep the description informative but concise (3-5 sentences).";
    
    keywordPrompt_ = 
        "Extract the most important keywords and key phrases from this content. "
        "Return them as a comma-separated list. Focus on:\n"
        "- Technical terms\n"
        "- Key concepts\n"
        "- Important names or identifiers\n"
        "Return only the keywords, nothing else.";
}

AnalysisResult FileAnalyzer::analyzeFile(const std::string& filePath, 
                                          size_t maxContentLength) {
    AnalysisResult result;
    result.filePath = filePath;
    
    auto startTime = std::chrono::high_resolution_clock::now();
    
    // Check if file exists
    if (!fs::exists(filePath)) {
        result.errorMessage = "File not found: " + filePath;
        return result;
    }
    
    // Get file info
    result.fileSize = fs::file_size(filePath);
    result.fileType = detectFileType(filePath);
    
    // Read content
    std::string content = readFileContent(filePath, maxContentLength);
    if (content.empty()) {
        result.errorMessage = "Failed to read file content";
        return result;
    }
    
    if (!router_) {
        result.errorMessage = "No LLM router configured";
        return result;
    }
    
    // Build combined analysis prompt
    std::string combinedPrompt = 
        "Analyze the following file and provide:\n"
        "1. SUMMARY: A concise 2-3 sentence summary\n"
        "2. DESCRIPTION: A brief description of the file's purpose\n"
        "3. KEYWORDS: Important keywords (comma-separated)\n\n"
        "File: " + filePath + "\n"
        "Type: " + result.fileType + "\n"
        "Size: " + std::to_string(result.fileSize) + " bytes\n\n"
        "Content:\n" + content;
    
    std::string systemPrompt = 
        "You are a forensic file analyst. Provide structured analysis in this exact format:\n"
        "SUMMARY: [summary here]\n"
        "DESCRIPTION: [description here]\n"
        "KEYWORDS: [comma-separated keywords]";
    
    auto response = router_->chat(combinedPrompt, systemPrompt);
    
    if (!response.success) {
        result.errorMessage = "LLM analysis failed: " + response.errorMessage;
        return result;
    }
    
    result.modelUsed = router_->getLastUsedModel();
    result.tokensUsed = response.promptTokens + response.completionTokens;
    
    // Parse response
    std::string responseText = response.content;
    
    // Extract summary
    std::regex summaryRegex("SUMMARY:\\s*(.+?)(?=DESCRIPTION:|$)", std::regex::icase);
    std::smatch summaryMatch;
    if (std::regex_search(responseText, summaryMatch, summaryRegex)) {
        result.summary = summaryMatch[1].str();
        // Trim whitespace
        result.summary.erase(0, result.summary.find_first_not_of(" \t\n\r"));
        result.summary.erase(result.summary.find_last_not_of(" \t\n\r") + 1);
    }
    
    // Extract description
    std::regex descRegex("DESCRIPTION:\\s*(.+?)(?=KEYWORDS:|$)", std::regex::icase);
    std::smatch descMatch;
    if (std::regex_search(responseText, descMatch, descRegex)) {
        result.description = descMatch[1].str();
        result.description.erase(0, result.description.find_first_not_of(" \t\n\r"));
        result.description.erase(result.description.find_last_not_of(" \t\n\r") + 1);
    }
    
    // Extract keywords
    std::regex keywordRegex("KEYWORDS:\\s*(.+)$", std::regex::icase);
    std::smatch keywordMatch;
    if (std::regex_search(responseText, keywordMatch, keywordRegex)) {
        result.keywords = parseKeywords(keywordMatch[1].str());
    }
    
    // If structured parsing failed, use the whole response as summary
    if (result.summary.empty() && result.description.empty()) {
        result.summary = responseText;
        result.description = responseText;
    }
    
    auto endTime = std::chrono::high_resolution_clock::now();
    result.analysisTimeMs = std::chrono::duration<double, std::milli>(endTime - startTime).count();
    result.success = true;
    
    return result;
}

std::vector<AnalysisResult> FileAnalyzer::analyzeBatch(const BatchAnalysisRequest& request) {
    std::vector<AnalysisResult> results;
    results.reserve(request.filePaths.size());
    
    size_t current = 0;
    for (const auto& path : request.filePaths) {
        if (progressCallback_) {
            progressCallback_(current, request.filePaths.size(), path);
        }
        
        auto result = analyzeFile(path, request.maxContentLength);
        results.push_back(result);
        current++;
    }
    
    if (progressCallback_) {
        progressCallback_(current, request.filePaths.size(), "Complete");
    }
    
    return results;
}

std::string FileAnalyzer::summarize(const std::string& content, 
                                     const std::string& context) {
    if (!router_) {
        return "Error: No LLM router configured";
    }
    
    std::string prompt = content;
    if (!context.empty()) {
        prompt = "Context: " + context + "\n\n" + content;
    }
    
    auto response = router_->chat(prompt, summaryPrompt_);
    
    if (!response.success) {
        return "Error: " + response.errorMessage;
    }
    
    return response.content;
}

std::string FileAnalyzer::generateDescription(const std::string& filePath) {
    if (!fs::exists(filePath)) {
        return "Error: File not found";
    }
    
    if (!router_) {
        return "Error: No LLM router configured";
    }
    
    std::string content = readFileContent(filePath, 5000);
    
    std::string prompt = 
        "File: " + filePath + "\n"
        "Type: " + detectFileType(filePath) + "\n"
        "Size: " + std::to_string(fs::file_size(filePath)) + " bytes\n\n"
        "Content preview:\n" + content;
    
    auto response = router_->chat(prompt, descriptionPrompt_);
    
    if (!response.success) {
        return "Error: " + response.errorMessage;
    }
    
    return response.content;
}

std::string FileAnalyzer::generateDescription(const std::vector<std::string>& filePaths) {
    if (filePaths.empty()) {
        return "Error: No files provided";
    }
    
    if (!router_) {
        return "Error: No LLM router configured";
    }
    
    std::ostringstream prompt;
    prompt << "Describe the following set of files:\n\n";
    
    for (const auto& path : filePaths) {
        if (!fs::exists(path)) {
            continue;
        }
        
        prompt << "File: " << path << "\n";
        prompt << "  Type: " << detectFileType(path) << "\n";
        prompt << "  Size: " << fs::file_size(path) << " bytes\n";
        
        std::string preview = readFileContent(path, 1000);
        if (!preview.empty()) {
            prompt << "  Preview: " << preview.substr(0, 200) << "...\n";
        }
        prompt << "\n";
    }
    
    std::string systemPrompt = 
        "Describe this collection of files. Explain what they contain, "
        "their relationships, and their overall purpose. Be concise.";
    
    auto response = router_->chat(prompt.str(), systemPrompt);
    
    if (!response.success) {
        return "Error: " + response.errorMessage;
    }
    
    return response.content;
}

std::vector<std::string> FileAnalyzer::extractKeywords(const std::string& content, 
                                                        size_t maxKeywords) {
    if (!router_) {
        return {};
    }
    
    std::string prompt = content.substr(0, 5000);  // Limit content
    auto response = router_->chat(prompt, keywordPrompt_);
    
    if (!response.success) {
        return {};
    }
    
    auto keywords = parseKeywords(response.content);
    
    // Limit to max keywords
    if (keywords.size() > maxKeywords) {
        keywords.resize(maxKeywords);
    }
    
    return keywords;
}

void FileAnalyzer::setSummaryPrompt(const std::string& prompt) {
    summaryPrompt_ = prompt;
}

void FileAnalyzer::setDescriptionPrompt(const std::string& prompt) {
    descriptionPrompt_ = prompt;
}

void FileAnalyzer::setKeywordPrompt(const std::string& prompt) {
    keywordPrompt_ = prompt;
}

void FileAnalyzer::setProgressCallback(ProgressCallback callback) {
    progressCallback_ = callback;
}

std::string FileAnalyzer::readFileContent(const std::string& path, size_t maxBytes) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        return "";
    }
    
    std::ostringstream content;
    if (maxBytes > 0) {
        std::vector<char> buffer(maxBytes);
        file.read(buffer.data(), maxBytes);
        content.write(buffer.data(), file.gcount());
    } else {
        content << file.rdbuf();
    }
    
    return content.str();
}

std::string FileAnalyzer::detectFileType(const std::string& path) {
    std::string ext = fs::path(path).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    
    // Common file types
    static const std::map<std::string, std::string> typeMap = {
        {".txt", "Text"},
        {".md", "Markdown"},
        {".json", "JSON"},
        {".xml", "XML"},
        {".html", "HTML"},
        {".htm", "HTML"},
        {".css", "CSS"},
        {".js", "JavaScript"},
        {".ts", "TypeScript"},
        {".py", "Python"},
        {".cpp", "C++"},
        {".c", "C"},
        {".h", "C/C++ Header"},
        {".hpp", "C++ Header"},
        {".java", "Java"},
        {".rs", "Rust"},
        {".go", "Go"},
        {".sh", "Shell Script"},
        {".bat", "Batch Script"},
        {".ps1", "PowerShell"},
        {".sql", "SQL"},
        {".log", "Log File"},
        {".csv", "CSV"},
        {".yaml", "YAML"},
        {".yml", "YAML"},
        {".ini", "INI Config"},
        {".conf", "Config"},
        {".cfg", "Config"},
        {".pdf", "PDF"},
        {".doc", "Word Document"},
        {".docx", "Word Document"},
        {".xls", "Excel"},
        {".xlsx", "Excel"},
    };
    
    auto it = typeMap.find(ext);
    if (it != typeMap.end()) {
        return it->second;
    }
    
    // Check if binary
    std::ifstream file(path, std::ios::binary);
    if (file) {
        char buffer[512];
        file.read(buffer, sizeof(buffer));
        size_t count = file.gcount();
        
        // Check for null bytes (binary indicator)
        for (size_t i = 0; i < count; ++i) {
            if (buffer[i] == '\0') {
                return "Binary";
            }
        }
    }
    
    return ext.empty() ? "Unknown" : ext.substr(1) + " File";
}

std::vector<std::string> FileAnalyzer::parseKeywords(const std::string& llmResponse) {
    std::vector<std::string> keywords;
    
    std::istringstream iss(llmResponse);
    std::string keyword;
    
    while (std::getline(iss, keyword, ',')) {
        // Trim whitespace
        keyword.erase(0, keyword.find_first_not_of(" \t\n\r"));
        keyword.erase(keyword.find_last_not_of(" \t\n\r") + 1);
        
        // Remove common prefixes like "- " or numbers
        if (!keyword.empty() && (keyword[0] == '-' || keyword[0] == '*')) {
            keyword = keyword.substr(1);
            keyword.erase(0, keyword.find_first_not_of(" "));
        }
        
        if (!keyword.empty() && keyword.length() > 1) {
            keywords.push_back(keyword);
        }
    }
    
    return keywords;
}

} // namespace llm
} // namespace forensics
