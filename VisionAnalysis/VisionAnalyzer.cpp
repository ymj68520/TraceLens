#include "VisionAnalyzer.h"
#include "json.hpp"

#include <filesystem>
#include <fstream>
#include <sstream>
#include <chrono>
#include <algorithm>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace forensics {
namespace llm {

// Base64 encoding table
static const char base64_chars[] =
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static std::string base64Encode(const std::vector<unsigned char>& data) {
    std::string result;
    size_t i = 0;
    unsigned char array3[3];
    unsigned char array4[4];
    size_t in_len = data.size();
    
    while (in_len--) {
        array3[i++] = data[data.size() - in_len - 1];
        if (i == 3) {
            array4[0] = (array3[0] & 0xfc) >> 2;
            array4[1] = ((array3[0] & 0x03) << 4) + ((array3[1] & 0xf0) >> 4);
            array4[2] = ((array3[1] & 0x0f) << 2) + ((array3[2] & 0xc0) >> 6);
            array4[3] = array3[2] & 0x3f;
            
            for (i = 0; i < 4; i++) {
                result += base64_chars[array4[i]];
            }
            i = 0;
        }
    }
    
    if (i) {
        for (size_t j = i; j < 3; j++) {
            array3[j] = '\0';
        }
        
        array4[0] = (array3[0] & 0xfc) >> 2;
        array4[1] = ((array3[0] & 0x03) << 4) + ((array3[1] & 0xf0) >> 4);
        array4[2] = ((array3[1] & 0x0f) << 2) + ((array3[2] & 0xc0) >> 6);
        
        for (size_t j = 0; j < i + 1; j++) {
            result += base64_chars[array4[j]];
        }
        
        while (i++ < 3) {
            result += '=';
        }
    }
    
    return result;
}

VisionAnalyzer::VisionAnalyzer(std::shared_ptr<ModelRouter> router)
    : router_(router) {
    initDefaultPrompts();
}

VisionAnalyzer::~VisionAnalyzer() = default;

void VisionAnalyzer::initDefaultPrompts() {
    analysisPrompt_ = 
        "Analyze this image thoroughly. Provide:\n"
        "1. A detailed description of what you see\n"
        "2. Key objects, people, or elements identified\n"
        "3. Any text visible in the image\n"
        "4. The context or purpose of the image\n"
        "Be comprehensive but concise.";
    
    descriptionPrompt_ = 
        "Describe this image in natural language. Focus on the main subjects, "
        "setting, and any notable details. Write 2-3 sentences.";
    
    ocrPrompt_ = 
        "Extract all text visible in this image. Return only the text content, "
        "preserving the original layout as much as possible. If no text is visible, "
        "respond with 'No text detected'.";
}

AnalysisResult VisionAnalyzer::analyzeImage(const std::string& imagePath) {
    AnalysisResult result;
    result.filePath = imagePath;
    
    auto startTime = std::chrono::high_resolution_clock::now();
    
    if (!fs::exists(imagePath)) {
        result.errorMessage = "Image file not found: " + imagePath;
        return result;
    }
    
    if (!isSupportedImage(imagePath)) {
        result.errorMessage = "Unsupported image format: " + imagePath;
        return result;
    }
    
    result.fileSize = fs::file_size(imagePath);
    result.fileType = getMimeType(imagePath);
    
    if (!router_) {
        result.errorMessage = "No LLM router configured";
        return result;
    }
    
    // Create image content
    ImageContent imgContent = createImageContent(imagePath);
    if (imgContent.base64Data.empty()) {
        result.errorMessage = "Failed to load image";
        return result;
    }
    
    // Create message with image
    ChatMessage msg("user", analysisPrompt_, imgContent);
    
    std::vector<ChatMessage> messages;
    messages.push_back(ChatMessage("system", 
        "You are an expert image analyst. Analyze images thoroughly and provide "
        "detailed, accurate descriptions. Focus on forensically relevant details."));
    messages.push_back(msg);
    
    // Route to vision model
    auto response = router_->chat(messages, ModelCapability::Vision);
    
    if (!response.success) {
        result.errorMessage = "Vision analysis failed: " + response.errorMessage;
        return result;
    }
    
    result.description = response.content;
    result.summary = response.content.substr(0, std::min(size_t(300), response.content.size()));
    result.modelUsed = router_->getLastUsedModel();
    result.tokensUsed = response.promptTokens + response.completionTokens;
    
    auto endTime = std::chrono::high_resolution_clock::now();
    result.analysisTimeMs = std::chrono::duration<double, std::milli>(endTime - startTime).count();
    result.success = true;
    
    return result;
}

AnalysisResult VisionAnalyzer::analyzeImageData(const std::string& base64Data,
                                                  const std::string& mimeType) {
    AnalysisResult result;
    
    if (base64Data.empty()) {
        result.errorMessage = "Empty image data";
        return result;
    }
    
    if (!router_) {
        result.errorMessage = "No LLM router configured";
        return result;
    }
    
    ImageContent imgContent;
    imgContent.base64Data = base64Data;
    imgContent.mimeType = mimeType;
    
    ChatMessage msg("user", analysisPrompt_, imgContent);
    
    std::vector<ChatMessage> messages;
    messages.push_back(ChatMessage("system", 
        "You are an expert image analyst. Provide detailed analysis."));
    messages.push_back(msg);
    
    auto response = router_->chat(messages, ModelCapability::Vision);
    
    if (!response.success) {
        result.errorMessage = "Analysis failed: " + response.errorMessage;
        return result;
    }
    
    result.description = response.content;
    result.summary = response.content.substr(0, std::min(size_t(300), response.content.size()));
    result.modelUsed = router_->getLastUsedModel();
    result.success = true;
    
    return result;
}

AnalysisResult VisionAnalyzer::analyzeWithPrompt(const std::string& imagePath,
                                                   const std::string& prompt) {
    AnalysisResult result;
    result.filePath = imagePath;
    
    if (!fs::exists(imagePath)) {
        result.errorMessage = "Image file not found";
        return result;
    }
    
    if (!router_) {
        result.errorMessage = "No LLM router configured";
        return result;
    }
    
    ImageContent imgContent = createImageContent(imagePath);
    if (imgContent.base64Data.empty()) {
        result.errorMessage = "Failed to load image";
        return result;
    }
    
    ChatMessage msg("user", prompt, imgContent);
    
    std::vector<ChatMessage> messages;
    messages.push_back(msg);
    
    auto response = router_->chat(messages, ModelCapability::Vision);
    
    if (!response.success) {
        result.errorMessage = response.errorMessage;
        return result;
    }
    
    result.description = response.content;
    result.success = true;
    
    return result;
}

std::string VisionAnalyzer::extractText(const std::string& imagePath) {
    if (!fs::exists(imagePath)) {
        return "Error: Image file not found";
    }
    
    if (!router_) {
        return "Error: No LLM router configured";
    }
    
    ImageContent imgContent = createImageContent(imagePath);
    if (imgContent.base64Data.empty()) {
        return "Error: Failed to load image";
    }
    
    ChatMessage msg("user", ocrPrompt_, imgContent);
    
    std::vector<ChatMessage> messages;
    messages.push_back(msg);
    
    auto response = router_->chat(messages, ModelCapability::Vision);
    
    if (!response.success) {
        return "Error: " + response.errorMessage;
    }
    
    return response.content;
}

std::string VisionAnalyzer::describeImage(const std::string& imagePath) {
    if (!fs::exists(imagePath)) {
        return "Error: Image file not found";
    }
    
    if (!router_) {
        return "Error: No LLM router configured";
    }
    
    ImageContent imgContent = createImageContent(imagePath);
    if (imgContent.base64Data.empty()) {
        return "Error: Failed to load image";
    }
    
    ChatMessage msg("user", descriptionPrompt_, imgContent);
    
    std::vector<ChatMessage> messages;
    messages.push_back(msg);
    
    auto response = router_->chat(messages, ModelCapability::Vision);
    
    if (!response.success) {
        return "Error: " + response.errorMessage;
    }
    
    return response.content;
}

std::vector<AnalysisResult> VisionAnalyzer::analyzeBatch(const std::vector<std::string>& imagePaths) {
    std::vector<AnalysisResult> results;
    results.reserve(imagePaths.size());
    
    size_t current = 0;
    for (const auto& path : imagePaths) {
        if (progressCallback_) {
            progressCallback_(current, imagePaths.size(), path);
        }
        
        results.push_back(analyzeImage(path));
        current++;
    }
    
    if (progressCallback_) {
        progressCallback_(current, imagePaths.size(), "Complete");
    }
    
    return results;
}

AnalysisResult VisionAnalyzer::analyzeVideo(const std::string& videoPath, int maxFrames) {
    AnalysisResult result;
    result.filePath = videoPath;
    
    if (!fs::exists(videoPath)) {
        result.errorMessage = "Video file not found: " + videoPath;
        return result;
    }
    
    if (!isSupportedVideo(videoPath)) {
        result.errorMessage = "Unsupported video format. Video frame extraction requires ffmpeg.";
        return result;
    }
    
    // Note: Full video analysis would require ffmpeg for frame extraction
    // For now, return a placeholder indicating the limitation
    result.errorMessage = "Video frame extraction not yet implemented. "
                          "Please extract key frames manually and use analyzeImage().";
    result.description = "Video analysis requires frame extraction. File: " + videoPath;
    
    return result;
}

std::string VisionAnalyzer::compareImages(const std::string& imagePath1,
                                           const std::string& imagePath2) {
    if (!fs::exists(imagePath1) || !fs::exists(imagePath2)) {
        return "Error: One or both image files not found";
    }
    
    if (!router_) {
        return "Error: No LLM router configured";
    }
    
    ImageContent img1 = createImageContent(imagePath1);
    ImageContent img2 = createImageContent(imagePath2);
    
    if (img1.base64Data.empty() || img2.base64Data.empty()) {
        return "Error: Failed to load images";
    }
    
    ChatMessage msg;
    msg.role = "user";
    msg.content = "Compare these two images. Describe their similarities and differences. "
                  "Note any significant changes between them.";
    msg.images.push_back(img1);
    msg.images.push_back(img2);
    msg.contentType = ContentType::Image;
    
    std::vector<ChatMessage> messages;
    messages.push_back(msg);
    
    auto response = router_->chat(messages, ModelCapability::Vision);
    
    if (!response.success) {
        return "Error: " + response.errorMessage;
    }
    
    return response.content;
}

void VisionAnalyzer::setAnalysisPrompt(const std::string& prompt) {
    analysisPrompt_ = prompt;
}

void VisionAnalyzer::setDescriptionPrompt(const std::string& prompt) {
    descriptionPrompt_ = prompt;
}

void VisionAnalyzer::setOCRPrompt(const std::string& prompt) {
    ocrPrompt_ = prompt;
}

void VisionAnalyzer::setProgressCallback(ProgressCallback callback) {
    progressCallback_ = callback;
}

bool VisionAnalyzer::isSupportedImage(const std::string& path) {
    std::string ext = fs::path(path).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    
    static const std::vector<std::string> supported = {
        ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".tiff", ".tif"
    };
    
    return std::find(supported.begin(), supported.end(), ext) != supported.end();
}

bool VisionAnalyzer::isSupportedVideo(const std::string& path) {
    std::string ext = fs::path(path).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    
    static const std::vector<std::string> supported = {
        ".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv", ".wmv"
    };
    
    return std::find(supported.begin(), supported.end(), ext) != supported.end();
}

std::string VisionAnalyzer::loadImageAsBase64(const std::string& path) {
    std::ifstream file(path, std::ios::binary);
    if (!file) {
        return "";
    }
    
    std::vector<unsigned char> buffer{
        std::istreambuf_iterator<char>(file),
        std::istreambuf_iterator<char>()
    };
    
    return base64Encode(buffer);
}

std::string VisionAnalyzer::getMimeType(const std::string& path) {
    std::string ext = fs::path(path).extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), ::tolower);
    
    static const std::map<std::string, std::string> mimeTypes = {
        {".jpg", "image/jpeg"},
        {".jpeg", "image/jpeg"},
        {".png", "image/png"},
        {".gif", "image/gif"},
        {".bmp", "image/bmp"},
        {".webp", "image/webp"},
        {".tiff", "image/tiff"},
        {".tif", "image/tiff"}
    };
    
    auto it = mimeTypes.find(ext);
    if (it != mimeTypes.end()) {
        return it->second;
    }
    
    return "application/octet-stream";
}

ImageContent VisionAnalyzer::createImageContent(const std::string& path) {
    ImageContent content;
    content.mimeType = getMimeType(path);
    content.base64Data = loadImageAsBase64(path);
    content.detail = "auto";
    return content;
}

} // namespace llm
} // namespace forensics
