#include "FileAnalyzer.h"
#include "FileContentExtractor.h"
#include "FileTextProcessor.h"
#include "MarkitdownProxy.h"
#include "json.hpp"
#include "ConfigManager/ConfigManager.h"
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
    "SUMMARY:\\s*(.+?)(?=DESCRIPTION:|$)", std::regex::icase);
const std::regex FileAnalyzer::DESCRIPTION_REGEX(
    "DESCRIPTION:\\s*(.+?)(?=KEYWORDS:|$)", std::regex::icase);
const std::regex FileAnalyzer::KEYWORD_REGEX(
    "KEYWORDS:\\s*(.+)$", std::regex::icase);

// ---------------------------------------------------------------------------
// Extension routing for content extraction.
//
// Microsoft's markitdown library only converts document/image/audio/HTML text
// formats. Feeding it binary forensic artifacts (disk images, PE/ELF binaries,
// registry hives, event logs, archives, databases...) raises
// UnsupportedFormatException, which the Python /api/markitdown/convert endpoint
// surfaces as HTTP 500 — flooding the backend log with errors whenever such a
// file is analyzed (e.g. Linux GRUB *.img files, evidence .img/.dd/.e01 images).
//
// isMarkitdownSupportedExt() is the allow-list of extensions markitdown can
// actually handle. Everything else bypasses markitdown and relies on the
// platform-aware extractor pipeline:
//   - Windows artifacts (.exe/.dll/.pf/.evtx/.hiv/.lnk...) -> PeExtractor,
//     EvtxExtractor, RegistryExtractor, LnkExtractor, PrefetchExtractor...
//   - Linux artifacts  (.so/.ko/.mod/.journal...)          -> ElfExtractor,
//     GrubModuleExtractor, JournalExtractor...
//   - Common files     (.pdf/.docx/.csv/.json/...)         -> shared extractors
// ---------------------------------------------------------------------------
namespace {
const std::set<std::string>& markitdownSupportedExtensions() {
    // Mirrors MarkitdownExtractor's extension list in
    // python_service/config/extractor_mapping.json plus the plain-text formats
    // markitdown handles natively.
    static const std::set<std::string> supported = {
        // Office documents
        ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
        // Web / structured text
        ".html", ".htm", ".ipynb", ".rss",
        // Images (EXIF + OCR)
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif",
        // Audio (transcription)
        ".mp3", ".wav",
        // Plain text / data formats markitdown reads directly
        ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".xml",
        ".yaml", ".yml", ".rst", ".log"
    };
    return supported;
}

bool isMarkitdownSupportedExt(const std::string& ext) {
    if (ext.empty()) return false;
    return markitdownSupportedExtensions().count(ext) > 0;
}
} // namespace

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
                                          size_t maxContentLength,
                                          const std::string& taskId) {
    AnalysisResult result;
    result.filePath = filePath;

    auto startTime = std::chrono::high_resolution_clock::now();

    // Check if file exists
    if (!fs::exists(filePath)) {
        result.errorMessage = "File not found: " + filePath;
        return result;
    }

    // Get file info using FileContentExtractor
    result.fileSize = fs::file_size(filePath);
    result.fileType = FileContentExtractor::detectFileType(filePath);

    // Read content — try markitdown first, fall back to local parsers
    std::string content;
    std::string ext = fs::path(filePath).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);

    LOG_DEBUG("File: " + filePath + ", Ext: " + ext);

    // Try markitdown proxy first (converts via Python service).
    //
    // IMPORTANT: markitdown only knows how to convert document/image/audio/text
    // formats. Passing binary forensic artifacts — disk images (.img/.iso/.dd),
    // executables/libraries (.exe/.dll/.so/.ko/.elf/.mod), registry hives,
    // event logs (.evtx), databases, archives, etc. — makes markitdown throw
    // UnsupportedFormatException, which the Python endpoint turns into an
    // HTTP 500 and floods the backend log with errors.
    //
    // Gate the markitdown call on an allow-list of extensions it actually
    // supports. Everything else goes straight to the local / Python extractor
    // pipeline (which has platform-aware extractors: PeExtractor for Windows
    // PE files, ElfExtractor + GrubModuleExtractor for Linux, E01Metadata
    // for evidence images, etc.).
    bool useMarkitdown = isMarkitdownSupportedExt(ext);

    if (useMarkitdown) {
        auto& markitdown = MarkitdownProxy::instance();
        if (markitdown.isServiceAvailable()) {
            content = markitdown.convertToMarkdown(filePath, taskId, fs::path(filePath).parent_path().string());
            if (!content.empty() && content.find("Error:") != 0) {
                LOG_DEBUG("Successfully converted via markitdown: " + filePath);
            } else {
                LOG_WARNING("markitdown failed for " + filePath + ", falling back to local parsers");
                content.clear();
            }
        }
    } else {
        LOG_DEBUG("Skipping markitdown for unsupported extension " + ext + " (" + filePath + ")");
    }

    // Fallback to local parsers if markitdown unavailable or failed
    if (content.empty()) {
        if (ext == ".pdf") {
            LOG_DEBUG("Using PDFAnalyzer (fallback)");
            content = forensics::analyzers::PDFAnalyzer::extractText(filePath);
        } else if (ext == ".docx" || ext == ".doc") {
            LOG_DEBUG("Using OfficeAnalyzer (fallback)");
            OfficeAnalyzer officeAnalyzer;
            officeAnalyzer.setPythonServiceUrl(ConfigManager::instance().getPythonServiceUrl());
            content = officeAnalyzer.analyze(filePath, taskId);
        } else if (result.fileType == "Archive" || result.fileType == "Binary" || result.fileType == "Database") {
            LOG_DEBUG("Binary/Archive detected. Skipping content read.");
            content = "[Binary/Archive File Content Omitted. Analysis based on metadata only.]";
        } else {
            LOG_DEBUG("Using Raw Read (fallback)");
            content = FileContentExtractor::readFileContent(filePath, maxContentLength);
        }
    }

    if (content.empty()) {
        result.errorMessage = "Failed to read file content or content is empty";
        return result;
    }

    // Sanitize UTF-8 using FileTextProcessor
    FileTextProcessor::sanitizeUTF8(content);

    if (!router_) {
        result.errorMessage = "No LLM router configured";
        return result;
    }

    // Apply smart content truncation based on context window (Issue 7)
    size_t calculatedMaxLength = calculateMaxContentLength();
    size_t configLimit = static_cast<size_t>(ConfigManager::instance().getLLMMaxContentLength());
    size_t effectiveMaxLength = std::min({maxContentLength, calculatedMaxLength, configLimit});

    if (content.size() > effectiveMaxLength) {
        LOG_DEBUG("Content exceeds limit (" + std::to_string(content.size()) +
                  " > " + std::to_string(effectiveMaxLength) + "), applying smart truncation");
        content = FileTextProcessor::truncateContent(content, effectiveMaxLength);
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
        result.keywords = FileTextProcessor::parseKeywords(keywordMatch[1].str());
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
                progressCallback_(i + 1, request.filePaths.size(), request.filePaths[i]);
            }
        }
    } else {
        // Sequential analysis
        for (size_t i = 0; i < request.filePaths.size(); ++i) {
            results[i] = analyzeFile(request.filePaths[i], request.maxContentLength);
            if (progressCallback_) {
                progressCallback_(i + 1, request.filePaths.size(), request.filePaths[i]);
            }
        }
    }

    return results;
}

std::string FileAnalyzer::summarize(const std::string& content,
                                      const std::string& context) {
    if (!router_) {
        return "Error: No LLM router configured";
    }

    std::string prompt = summaryPrompt_ + "\n\nContent:\n" + content;
    if (!context.empty()) {
        prompt += "\n\nContext: " + context;
    }

    auto response = router_->chat(prompt, "You are a file analysis assistant.");
    return response.success ? response.content : "Error: " + response.errorMessage;
}

std::string FileAnalyzer::generateDescription(const std::string& filePath) {
    if (!fs::exists(filePath)) {
        return "Error: File not found";
    }

    std::string content = FileContentExtractor::readFileContent(filePath);
    if (content.empty()) {
        return "Error: Unable to read file";
    }

    // Sanitize UTF-8
    FileTextProcessor::sanitizeUTF8(content);

    std::string fileType = FileContentExtractor::detectFileType(filePath);
    size_t fileSize = fs::file_size(filePath);

    std::string prompt = descriptionPrompt_ +
        "\n\nFile: " + filePath +
        "\nType: " + fileType +
        "\nSize: " + std::to_string(fileSize) + " bytes" +
        "\n\nContent:\n" + content;

    auto response = router_->chat(prompt, "You are a file analysis assistant.");
    return response.success ? response.content : "Error: " + response.errorMessage;
}

std::string FileAnalyzer::generateDescription(const std::vector<std::string>& filePaths) {
    if (filePaths.empty()) {
        return "Error: No files provided";
    }

    // Analyze first few files to understand the set
    std::string context = "File set analysis:\n";
    int count = 0;
    for (const auto& path : filePaths) {
        if (count >= 5) break; // Limit to 5 files for context
        std::string fileType = FileContentExtractor::detectFileType(path);
        size_t fileSize = fs::exists(path) ? fs::file_size(path) : 0;
        context += "- " + path + " (" + fileType + ", " + std::to_string(fileSize) + " bytes)\n";
        count++;
    }

    if (filePaths.size() > 5) {
        context += "... and " + std::to_string(filePaths.size() - 5) + " more files\n";
    }

    std::string prompt = descriptionPrompt_ + "\n\n" + context;
    auto response = router_->chat(prompt, "You are a file analysis assistant.");
    return response.success ? response.content : "Error: " + response.errorMessage;
}

std::vector<std::string> FileAnalyzer::extractKeywords(const std::string& content,
                                                         size_t maxKeywords) {
    if (!router_) {
        return {};
    }

    std::string prompt = keywordPrompt_ + "\n\nContent:\n" + content;
    auto response = router_->chat(prompt, "You are a keyword extraction assistant.");

    if (!response.success) {
        return {};
    }

    auto keywords = FileTextProcessor::parseKeywords(response.content);

    // Limit to maxKeywords
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

void FileAnalyzer::setChunkConfig(const ChunkConfig& config) {
    chunkConfig_ = config;
}

const ChunkConfig& FileAnalyzer::getChunkConfig() const {
    return chunkConfig_;
}

// ===== Context Window Management Methods =====

size_t FileAnalyzer::estimateTokens(const std::string& content, double charsPerToken) {
    return FileTextProcessor::estimateTokens(content, charsPerToken);
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

    return maxChars;
}

std::string FileAnalyzer::truncateContent(const std::string& content, size_t maxLength) const {
    return FileTextProcessor::truncateContent(content, maxLength);
}

std::vector<std::string> FileAnalyzer::splitIntoChunks(const std::string& content) const {
    return FileTextProcessor::splitIntoChunks(content, chunkConfig_);
}

size_t FileAnalyzer::findSmartBoundary(const std::string& content, size_t targetPos) const {
    return FileTextProcessor::findSmartBoundary(content, targetPos);
}

AnalysisResult FileAnalyzer::analyzeFileChunked(const std::string& filePath) {
    AnalysisResult result;
    result.filePath = filePath;

    auto startTime = std::chrono::high_resolution_clock::now();

    if (!fs::exists(filePath)) {
        result.errorMessage = "File not found: " + filePath;
        return result;
    }

    // Read file content
    std::string content = FileContentExtractor::readFileContent(filePath);
    if (content.empty()) {
        result.errorMessage = "Failed to read file content";
        return result;
    }

    // Sanitize UTF-8
    FileTextProcessor::sanitizeUTF8(content);

    // Split into chunks
    std::vector<std::string> chunks = splitIntoChunks(content);
    if (chunks.empty()) {
        result.errorMessage = "Failed to split content into chunks";
        return result;
    }

    std::cout << "[INFO] Analyzing file in " << chunks.size() << " chunks" << std::endl;

    // Analyze each chunk
    std::vector<AnalysisResult> chunkResults;
    chunkResults.reserve(chunks.size());

    for (size_t i = 0; i < chunks.size(); ++i) {
        AnalysisResult chunkResult;
        chunkResult.filePath = filePath;
        chunkResult.fileType = FileContentExtractor::detectFileType(filePath);
        chunkResult.fileSize = fs::file_size(filePath);

        // Analyze chunk
        std::string combinedPrompt =
            "Analyze this file chunk (" + std::to_string(i + 1) + "/" + std::to_string(chunks.size()) + ").\n\n"
            "Provide:\n"
            "1. SUMMARY: Brief summary of this chunk\n"
            "2. DESCRIPTION: What this chunk contains\n"
            "3. KEYWORDS: Key terms in this chunk\n\n"
            "Chunk content:\n" + chunks[i];

        auto response = router_->chat(combinedPrompt,
            "You are a forensic file analyst. Format: SUMMARY: [...] DESCRIPTION: [...] KEYWORDS: [...]");

        if (response.success) {
            // Parse response
            std::smatch summaryMatch, descMatch, keywordMatch;
            std::string responseText = response.content;

            if (std::regex_search(responseText, summaryMatch, SUMMARY_REGEX)) {
                chunkResult.summary = summaryMatch[1].str();
            }
            if (std::regex_search(responseText, descMatch, DESCRIPTION_REGEX)) {
                chunkResult.description = descMatch[1].str();
            }
            if (std::regex_search(responseText, keywordMatch, KEYWORD_REGEX)) {
                chunkResult.keywords = FileTextProcessor::parseKeywords(keywordMatch[1].str());
            }

            chunkResult.tokensUsed = response.promptTokens + response.completionTokens;
            chunkResult.modelUsed = router_->getLastUsedModel();
            chunkResult.success = true;
        } else {
            chunkResult.errorMessage = response.errorMessage;
        }

        chunkResults.push_back(std::move(chunkResult));

        // Progress callback
        if (progressCallback_) {
            progressCallback_(i + 1, chunks.size(), filePath);
        }
    }

    // Merge results
    result = mergeChunkResults(chunkResults, filePath);

    auto endTime = std::chrono::high_resolution_clock::now();
    result.analysisTimeMs = std::chrono::duration<double, std::milli>(endTime - startTime).count();

    return result;
}

AnalysisResult FileAnalyzer::mergeChunkResults(const std::vector<AnalysisResult>& results,
                                                 const std::string& filePath) const {
    AnalysisResult merged;
    merged.filePath = filePath;
    merged.fileType = results.empty() ? "Unknown" : results[0].fileType;
    merged.fileSize = results.empty() ? 0 : results[0].fileSize;
    merged.modelUsed = results.empty() ? "" : results[0].modelUsed;

    // Collect all summaries
    std::string combinedSummary;
    for (const auto& result : results) {
        if (!result.summary.empty()) {
            combinedSummary += result.summary + " ";
        }
    }

    // Generate merged summary via LLM
    if (!combinedSummary.empty() && router_) {
        std::string prompt =
            "Merge these chunk summaries into a cohesive file summary:\n\n" + combinedSummary +
            "\n\nProvide a single comprehensive summary.";

        auto response = router_->chat(prompt, "You are a summary merger.");
        if (response.success) {
            merged.summary = response.content;
        } else {
            merged.summary = combinedSummary;
        }
    }

    // Collect unique keywords
    std::set<std::string> uniqueKeywords;
    for (const auto& result : results) {
        for (const auto& keyword : result.keywords) {
            uniqueKeywords.insert(keyword);
        }
    }
    merged.keywords.assign(uniqueKeywords.begin(), uniqueKeywords.end());

    // Combine descriptions
    std::string combinedDesc;
    for (const auto& result : results) {
        if (!result.description.empty()) {
            combinedDesc += result.description + " ";
        }
    }
    merged.description = combinedDesc;

    // Sum tokens and time
    size_t totalTokens = 0;
    double totalTime = 0.0;
    for (const auto& result : results) {
        totalTokens += result.tokensUsed;
        totalTime += result.analysisTimeMs;
    }
    merged.tokensUsed = totalTokens;
    merged.analysisTimeMs = totalTime;
    merged.success = true;

    return merged;
}

} // namespace llm
} // namespace forensics
