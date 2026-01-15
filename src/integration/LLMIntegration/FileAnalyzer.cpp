#include "FileAnalyzer.h"
#include "json.hpp"
#include "ConfigManager.h"
#include "../../core/Logger/Logger.h"
#include "../../core/ThreadPool/ThreadPool.h"
#include "../../analyzers/PDFAnalyzer/PDFAnalyzer.h"
#include "../../analyzers/OfficeAnalyzer/OfficeAnalyzer.h"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <chrono>
#include <algorithm>
#include <regex>
#include <set>
#include <future>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace forensics {
namespace llm {

// Static regex initialization (Issue 9 - pre-compiled for performance)
const std::regex FileAnalyzer::SUMMARY_REGEX(
    "SUMMARY:\\\\s*(.+?)(?=DESCRIPTION:|$)", std::regex::icase);
const std::regex FileAnalyzer::DESCRIPTION_REGEX(
    "DESCRIPTION:\\\\s*(.+?)(?=KEYWORDS:|$)", std::regex::icase);
const std::regex FileAnalyzer::KEYWORD_REGEX(
    "KEYWORDS:\\\\s*(.+)$", std::regex::icase);

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
    std::string content;
    std::string ext = fs::path(filePath).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    
    LOG_DEBUG("File: " + filePath + ", Ext: " + ext);

    if (ext == ".pdf") {
        LOG_DEBUG("Using PDFAnalyzer");
        content = forensics::analyzers::PDFAnalyzer::extractText(filePath);
    } else if (ext == ".docx" || ext == ".doc") {
        LOG_DEBUG("Using OfficeAnalyzer");
        OfficeAnalyzer officeAnalyzer;
        content = officeAnalyzer.analyze(filePath);
    } else if (result.fileType == "Archive" || result.fileType == "Binary" || result.fileType == "Database") {
        LOG_DEBUG("Binary/Archive detected. Skipping content read.");
        content = "[Binary/Archive File Content Omitted. Analysis based on metadata only.]";
    } else {
        LOG_DEBUG("Using Raw Read");
        content = readFileContent(filePath, maxContentLength);
    }

    if (content.empty()) {
        result.errorMessage = "Failed to read file content or content is empty";
        return result;
    }
    
    // Sanitize UTF-8
    auto sanitize = [](std::string& str) {
        std::string res;
        res.reserve(str.size());
        for (size_t i = 0; i < str.size(); ++i) {
            unsigned char c = static_cast<unsigned char>(str[i]);
            if (c < 0x80) {
                res += c;
            } else {
                // Determine sequence length
                int len = 0;
                if ((c & 0xE0) == 0xC0) len = 2;
                else if ((c & 0xF0) == 0xE0) len = 3;
                else if ((c & 0xF8) == 0xF0) len = 4;
                
                bool valid = len > 0 && (i + len <= str.size());
                if (valid) {
                    for (int j = 1; j < len; ++j) {
                        if ((static_cast<unsigned char>(str[i+j]) & 0xC0) != 0x80) {
                            valid = false;
                            break;
                        }
                    }
                }
                
                if (valid) {
                    res += str.substr(i, len);
                    i += len - 1;
                } else {
                    // Replace invalid byte with space or ?
                    res += '?';
                }
            }
        }
        str = std::move(res);
    };
    
    sanitize(content);
    
    if (!router_) {
        result.errorMessage = "No LLM router configured";
        return result;
    }
    
    // Apply smart content truncation based on context window (Issue 7)
    size_t calculatedMaxLength = calculateMaxContentLength();
    size_t configLimit = static_cast<size_t>(ConfigManager::instance().getMaxContentLimit());
    size_t effectiveMaxLength = std::min({maxContentLength, calculatedMaxLength, configLimit});
    
    if (content.size() > effectiveMaxLength) {
        LOG_DEBUG("Content exceeds limit (" + std::to_string(content.size()) + 
                  " > " + std::to_string(effectiveMaxLength) + "), applying smart truncation");
        content = truncateContent(content, effectiveMaxLength);
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
    
    // Parse response using pre-compiled static regex (Issue 9)
    std::string responseText = response.content;
    
    // Extract summary
    std::smatch summaryMatch;
    if (std::regex_search(responseText, summaryMatch, SUMMARY_REGEX)) {
        result.summary = summaryMatch[1].str();
        // Trim whitespace
        result.summary.erase(0, result.summary.find_first_not_of(" \t\n\r"));
        result.summary.erase(result.summary.find_last_not_of(" \t\n\r") + 1);
    }
    
    // Extract description
    std::smatch descMatch;
    if (std::regex_search(responseText, descMatch, DESCRIPTION_REGEX)) {
        result.description = descMatch[1].str();
        result.description.erase(0, result.description.find_first_not_of(" \t\n\r"));
        result.description.erase(result.description.find_last_not_of(" \t\n\r") + 1);
    }
    
    // Extract keywords
    std::smatch keywordMatch;
    if (std::regex_search(responseText, keywordMatch, KEYWORD_REGEX)) {
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
    results.resize(request.filePaths.size());
    
    // Get thread pool size from config (Issue 2 - concurrent batch analysis)
    int poolSize = ConfigManager::instance().getThreadPoolSize();
    
    if (poolSize > 1 && request.filePaths.size() > 1) {
        // Use thread pool for concurrent analysis
        ThreadPool pool(static_cast<size_t>(poolSize));
        std::vector<std::future<AnalysisResult>> futures;
        futures.reserve(request.filePaths.size());
        
        for (const auto& path : request.filePaths) {
            futures.push_back(pool.enqueue([this, path, &request]() {
                return analyzeFile(path, request.maxContentLength);
            }));
        }
        
        // Collect results and call progress callback
        for (size_t i = 0; i < futures.size(); ++i) {
            results[i] = futures[i].get();
            if (progressCallback_) {
                progressCallback_(i + 1, futures.size(), results[i].filePath);
            }
        }
    } else {
        // Serial processing for single thread or single file
        size_t current = 0;
        for (const auto& path : request.filePaths) {
            if (progressCallback_) {
                progressCallback_(current, request.filePaths.size(), path);
            }
            
            results[current] = analyzeFile(path, request.maxContentLength);
            current++;
        }
        
        if (progressCallback_) {
            progressCallback_(results.size(), request.filePaths.size(), "Complete");
        }
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
    
    // Extended file type mapping (Issue 10)
    static const std::map<std::string, std::string> typeMap = {
        // Text files
        {".txt", "Text"},
        {".md", "Markdown"},
        {".json", "JSON"},
        {".xml", "XML"},
        {".html", "HTML"},
        {".htm", "HTML"},
        {".css", "CSS"},
        {".rtf", "Rich Text"},
        
        // Programming languages
        {".js", "JavaScript"},
        {".jsx", "JavaScript React"},
        {".ts", "TypeScript"},
        {".tsx", "TypeScript React"},
        {".py", "Python"},
        {".cpp", "C++"},
        {".c", "C"},
        {".h", "C/C++ Header"},
        {".hpp", "C++ Header"},
        {".java", "Java"},
        {".rs", "Rust"},
        {".go", "Go"},
        {".rb", "Ruby"},
        {".php", "PHP"},
        {".cs", "C#"},
        {".swift", "Swift"},
        {".kt", "Kotlin"},
        {".scala", "Scala"},
        {".r", "R"},
        {".lua", "Lua"},
        {".pl", "Perl"},
        
        // Shell and scripts
        {".sh", "Shell Script"},
        {".bash", "Bash Script"},
        {".zsh", "Zsh Script"},
        {".bat", "Batch Script"},
        {".cmd", "Command Script"},
        {".ps1", "PowerShell"},
        
        // Data formats
        {".sql", "SQL"},
        {".log", "Log File"},
        {".csv", "CSV"},
        {".tsv", "TSV"},
        {".yaml", "YAML"},
        {".yml", "YAML"},
        {".toml", "TOML"},
        {".ini", "INI Config"},
        {".conf", "Config"},
        {".cfg", "Config"},
        {".properties", "Properties"},
        
        // Documents
        {".pdf", "PDF"},
        {".doc", "Word Document"},
        {".docx", "Word Document"},
        {".xls", "Excel"},
        {".xlsx", "Excel"},
        {".ppt", "PowerPoint"},
        {".pptx", "PowerPoint"},
        {".odt", "OpenDocument Text"},
        {".ods", "OpenDocument Spreadsheet"},
        {".odp", "OpenDocument Presentation"},
        {".odg", "OpenDocument Graphics"},
        
        // E-Books
        {".epub", "E-Book"},
        {".mobi", "Kindle E-Book"},
        {".azw", "Kindle E-Book"},
        {".azw3", "Kindle E-Book"},
        
        // Images
        {".jpg", "JPEG Image"},
        {".jpeg", "JPEG Image"},
        {".png", "PNG Image"},
        {".gif", "GIF Image"},
        {".bmp", "Bitmap Image"},
        {".svg", "SVG Image"},
        {".webp", "WebP Image"},
        {".ico", "Icon"},
        {".tiff", "TIFF Image"},
        {".tif", "TIFF Image"},
        {".psd", "Photoshop"},
        {".ai", "Illustrator"},
        {".raw", "RAW Image"},
        
        // Video
        {".mp4", "MP4 Video"},
        {".mkv", "MKV Video"},
        {".avi", "AVI Video"},
        {".mov", "QuickTime Video"},
        {".wmv", "WMV Video"},
        {".flv", "Flash Video"},
        {".webm", "WebM Video"},
        {".m4v", "M4V Video"},
        {".mpeg", "MPEG Video"},
        {".mpg", "MPEG Video"},
        
        // Audio
        {".mp3", "MP3 Audio"},
        {".wav", "WAV Audio"},
        {".flac", "FLAC Audio"},
        {".ogg", "OGG Audio"},
        {".aac", "AAC Audio"},
        {".wma", "WMA Audio"},
        {".m4a", "M4A Audio"},
        {".aiff", "AIFF Audio"},
        {".opus", "Opus Audio"},
        
        // Archives
        {".zip", "ZIP Archive"},
        {".rar", "RAR Archive"},
        {".7z", "7-Zip Archive"},
        {".tar", "TAR Archive"},
        {".gz", "GZip Archive"},
        {".bz2", "BZip2 Archive"},
        {".xz", "XZ Archive"},
        {".lz", "LZ Archive"},
        {".lzma", "LZMA Archive"},
        
        // Executables and libraries
        {".exe", "Windows Executable"},
        {".dll", "Windows Library"},
        {".so", "Linux Library"},
        {".dylib", "macOS Library"},
        {".app", "macOS Application"},
        {".apk", "Android Package"},
        {".deb", "Debian Package"},
        {".rpm", "RPM Package"},
        
        // Database
        {".db", "Database"},
        {".sqlite", "SQLite Database"},
        {".sqlite3", "SQLite Database"},
        {".mdb", "Access Database"},
        {".accdb", "Access Database"},
        
        // Certificates and keys
        {".pem", "PEM Certificate"},
        {".crt", "Certificate"},
        {".cer", "Certificate"},
        {".key", "Private Key"},
        {".p12", "PKCS12 Certificate"},
        {".pfx", "PFX Certificate"},
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

// ===== Context Window Management Methods =====

void FileAnalyzer::setChunkConfig(const ChunkConfig& config) {
    chunkConfig_ = config;
}

const ChunkConfig& FileAnalyzer::getChunkConfig() const {
    return chunkConfig_;
}

size_t FileAnalyzer::estimateTokens(const std::string& content, double charsPerToken) {
    if (content.empty() || charsPerToken <= 0) {
        return 0;
    }
    return static_cast<size_t>(content.size() / charsPerToken);
}

size_t FileAnalyzer::calculateMaxContentLength() const {
    if (!router_) {
        return 10000; // Default fallback
    }
    
    // Get config from router's primary client
    const auto& config = router_->getConfig();
    
    // Available tokens = context length - reserved tokens - max output tokens
    int availableTokens = config.contextLength - config.reservedTokens - config.maxTokens;
    if (availableTokens < 100) {
        availableTokens = 100; // Minimum
    }
    
    // Convert to characters
    size_t maxChars = static_cast<size_t>(availableTokens * config.charsPerToken);
    
    std::cout << "[DEBUG] Context optimization: contextLength=" << config.contextLength 
              << ", reserved=" << config.reservedTokens 
              << ", maxTokens=" << config.maxTokens
              << ", availableTokens=" << availableTokens
              << ", maxChars=" << maxChars << std::endl;
    
    return maxChars;
}

std::string FileAnalyzer::truncateContent(const std::string& content, size_t maxLength) const {
    if (content.size() <= maxLength) {
        return content;
    }
    
    if (maxLength < 100) {
        return content.substr(0, maxLength);
    }
    
    // Reserve space for indicator
    const std::string indicator = "\n\n[... Content truncated due to context window limit ...]\n\n";
    size_t effectiveMax = maxLength - indicator.size();
    
    // Split: 70% from beginning, 30% from end
    size_t headSize = static_cast<size_t>(effectiveMax * 0.7);
    size_t tailSize = effectiveMax - headSize;
    
    // Find smart boundaries
    size_t headEnd = findSmartBoundary(content, headSize);
    size_t tailStart = content.size() - tailSize;
    
    // Adjust tail start to a smart boundary (look forward)
    for (size_t i = tailStart; i < content.size() && i < tailStart + 200; ++i) {
        char c = content[i];
        if (c == '\n' || c == '.' || c == '!' || c == '?') {
            tailStart = i + 1;
            break;
        }
    }
    
    std::string result;
    result.reserve(maxLength);
    result += content.substr(0, headEnd);
    result += indicator;
    if (tailStart < content.size()) {
        result += content.substr(tailStart);
    }
    
    std::cout << "[DEBUG] Content truncated: original=" << content.size() 
              << " chars, truncated=" << result.size() << " chars" << std::endl;
    
    return result;
}

size_t FileAnalyzer::findSmartBoundary(const std::string& content, size_t targetPos) const {
    if (targetPos >= content.size()) {
        return content.size();
    }
    
    // Search window: look back up to 200 chars for a good break point
    size_t searchStart = (targetPos > 200) ? targetPos - 200 : 0;
    
    // Priority 1: Paragraph break (double newline)
    size_t lastParagraph = std::string::npos;
    for (size_t i = searchStart; i < targetPos - 1 && i < content.size() - 1; ++i) {
        if (content[i] == '\n' && content[i + 1] == '\n') {
            lastParagraph = i + 2;
        }
    }
    if (lastParagraph != std::string::npos && lastParagraph > searchStart) {
        return lastParagraph;
    }
    
    // Priority 2: Sentence end (. ! ?)
    size_t lastSentence = std::string::npos;
    for (size_t i = searchStart; i < targetPos && i < content.size(); ++i) {
        char c = content[i];
        if ((c == '.' || c == '!' || c == '?') && 
            (i + 1 >= content.size() || content[i + 1] == ' ' || content[i + 1] == '\n')) {
            lastSentence = i + 1;
        }
    }
    if (lastSentence != std::string::npos && lastSentence > searchStart) {
        return lastSentence;
    }
    
    // Priority 3: Line break
    size_t lastLine = std::string::npos;
    for (size_t i = searchStart; i < targetPos && i < content.size(); ++i) {
        if (content[i] == '\n') {
            lastLine = i + 1;
        }
    }
    if (lastLine != std::string::npos && lastLine > searchStart) {
        return lastLine;
    }
    
    // Priority 4: Word break (space)
    size_t lastSpace = std::string::npos;
    for (size_t i = searchStart; i < targetPos && i < content.size(); ++i) {
        if (content[i] == ' ') {
            lastSpace = i + 1;
        }
    }
    if (lastSpace != std::string::npos && lastSpace > searchStart) {
        return lastSpace;
    }
    
    // Fallback: hard cut at target position
    return targetPos;
}

std::vector<std::string> FileAnalyzer::splitIntoChunks(const std::string& content) const {
    std::vector<std::string> chunks;
    
    if (content.empty()) {
        return chunks;
    }
    
    size_t chunkSize = chunkConfig_.chunkSize;
    size_t overlap = chunkConfig_.overlapSize;
    int maxChunks = chunkConfig_.maxChunks;
    
    if (content.size() <= chunkSize) {
        chunks.push_back(content);
        return chunks;
    }
    
    size_t pos = 0;
    while (pos < content.size() && static_cast<int>(chunks.size()) < maxChunks) {
        size_t endPos = std::min(pos + chunkSize, content.size());
        
        // Find smart boundary for chunk end
        if (endPos < content.size() && chunkConfig_.smartBoundary) {
            endPos = findSmartBoundary(content, endPos);
        }
        
        chunks.push_back(content.substr(pos, endPos - pos));
        
        // Move position with overlap
        if (endPos >= content.size()) {
            break;
        }
        pos = (endPos > overlap) ? endPos - overlap : endPos;
    }
    
    std::cout << "[DEBUG] Split content into " << chunks.size() << " chunks" << std::endl;
    
    return chunks;
}

AnalysisResult FileAnalyzer::analyzeFileChunked(const std::string& filePath) {
    AnalysisResult result;
    result.filePath = filePath;
    
    auto startTime = std::chrono::high_resolution_clock::now();
    
    if (!fs::exists(filePath)) {
        result.errorMessage = "File not found: " + filePath;
        return result;
    }
    
    result.fileSize = fs::file_size(filePath);
    result.fileType = detectFileType(filePath);
    
    // Read full content
    std::string content = readFileContent(filePath, 0); // Read all
    
    if (content.empty()) {
        result.errorMessage = "Failed to read file content or content is empty";
        return result;
    }
    
    // Calculate max content length
    size_t maxLength = calculateMaxContentLength();
    
    // If content fits, use regular analysis
    if (content.size() <= maxLength) {
        return analyzeFile(filePath, maxLength);
    }
    
    std::cout << "[DEBUG] File too large (" << content.size() << " chars), using chunked analysis" << std::endl;
    
    // Split into chunks
    auto chunks = splitIntoChunks(content);
    
    if (chunks.empty()) {
        result.errorMessage = "Failed to split content into chunks";
        return result;
    }
    
    // Analyze each chunk
    std::vector<AnalysisResult> chunkResults;
    for (size_t i = 0; i < chunks.size(); ++i) {
        std::cout << "[DEBUG] Analyzing chunk " << (i + 1) << "/" << chunks.size() << std::endl;
        
        // Create temp analysis for this chunk
        std::string chunkPrompt = 
            "Analyze the following content (chunk " + std::to_string(i + 1) + 
            " of " + std::to_string(chunks.size()) + "):\n\n" +
            "File: " + filePath + "\n" +
            "Type: " + result.fileType + "\n\n" +
            "Content:\n" + chunks[i];
        
        std::string systemPrompt = 
            "You are a forensic file analyst. Provide structured analysis in this exact format:\n"
            "SUMMARY: [summary here]\n"
            "DESCRIPTION: [description here]\n"
            "KEYWORDS: [comma-separated keywords]";
        
        auto response = router_->chat(chunkPrompt, systemPrompt);
        
        AnalysisResult chunkResult;
        chunkResult.filePath = filePath;
        chunkResult.success = response.success;
        
        if (response.success) {
            // Parse chunk response
            std::string responseText = response.content;
            
            std::regex summaryRegex("SUMMARY:\\s*(.+?)(?=DESCRIPTION:|$)", std::regex::icase);
            std::smatch summaryMatch;
            if (std::regex_search(responseText, summaryMatch, summaryRegex)) {
                chunkResult.summary = summaryMatch[1].str();
            }
            
            std::regex descRegex("DESCRIPTION:\\s*(.+?)(?=KEYWORDS:|$)", std::regex::icase);
            std::smatch descMatch;
            if (std::regex_search(responseText, descMatch, descRegex)) {
                chunkResult.description = descMatch[1].str();
            }
            
            std::regex keywordRegex("KEYWORDS:\\s*(.+)$", std::regex::icase);
            std::smatch keywordMatch;
            if (std::regex_search(responseText, keywordMatch, keywordRegex)) {
                chunkResult.keywords = parseKeywords(keywordMatch[1].str());
            }
            
            chunkResult.tokensUsed = response.promptTokens + response.completionTokens;
        }
        
        chunkResults.push_back(chunkResult);
    }
    
    // Merge results
    result = mergeChunkResults(chunkResults, filePath);
    result.fileSize = fs::file_size(filePath);
    result.fileType = detectFileType(filePath);
    
    auto endTime = std::chrono::high_resolution_clock::now();
    result.analysisTimeMs = std::chrono::duration<double, std::milli>(endTime - startTime).count();
    
    return result;
}

AnalysisResult FileAnalyzer::mergeChunkResults(const std::vector<AnalysisResult>& results, 
                                                const std::string& filePath) const {
    AnalysisResult merged;
    merged.filePath = filePath;
    merged.success = false;
    
    if (results.empty()) {
        merged.errorMessage = "No chunk results to merge";
        return merged;
    }
    
    // Merge summaries
    std::ostringstream summaryStream;
    std::ostringstream descStream;
    std::set<std::string> allKeywords;
    int totalTokens = 0;
    int successCount = 0;
    
    for (size_t i = 0; i < results.size(); ++i) {
        const auto& r = results[i];
        if (!r.success) continue;
        
        successCount++;
        totalTokens += r.tokensUsed;
        
        if (!r.summary.empty()) {
            if (summaryStream.tellp() > 0) summaryStream << " ";
            summaryStream << r.summary;
        }
        
        if (!r.description.empty()) {
            if (descStream.tellp() > 0) descStream << " ";
            descStream << r.description;
        }
        
        for (const auto& kw : r.keywords) {
            allKeywords.insert(kw);
        }
    }
    
    if (successCount == 0) {
        merged.errorMessage = "All chunk analyses failed";
        return merged;
    }
    
    merged.summary = summaryStream.str();
    merged.description = descStream.str();
    merged.keywords = std::vector<std::string>(allKeywords.begin(), allKeywords.end());
    merged.tokensUsed = totalTokens;
    merged.success = true;
    
    if (router_) {
        merged.modelUsed = router_->getLastUsedModel();
    }
    
    std::cout << "[DEBUG] Merged " << successCount << "/" << results.size() 
              << " chunk results, " << merged.keywords.size() << " unique keywords" << std::endl;
    
    return merged;
}

} // namespace llm
} // namespace forensics
