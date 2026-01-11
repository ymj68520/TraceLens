#pragma once

#include "LLMDataTypes.h"
#include "ModelRouter.h"
#include <memory>
#include <string>
#include <vector>
#include <functional>

namespace forensics {
namespace llm {

/**
 * @brief Vision analyzer for images and videos using Qwen3 VL model
 * 
 * Analyzes visual content including:
 * - Images (JPEG, PNG, BMP, GIF, WebP)
 * - Video frames (extracted from videos)
 * - Screenshots and scanned documents
 */
class VisionAnalyzer {
public:
    /**
     * @brief Constructor
     * @param router Model router for LLM requests
     */
    explicit VisionAnalyzer(std::shared_ptr<ModelRouter> router);
    ~VisionAnalyzer();
    
    // Non-copyable
    VisionAnalyzer(const VisionAnalyzer&) = delete;
    VisionAnalyzer& operator=(const VisionAnalyzer&) = delete;
    
    /**
     * @brief Analyze an image file
     * @param imagePath Path to the image file
     * @return Analysis result with description and detected content
     */
    AnalysisResult analyzeImage(const std::string& imagePath);
    
    /**
     * @brief Analyze image from base64 data
     * @param base64Data Base64 encoded image data
     * @param mimeType MIME type (e.g., "image/jpeg")
     * @return Analysis result
     */
    AnalysisResult analyzeImageData(const std::string& base64Data, 
                                     const std::string& mimeType = "image/jpeg");
    
    /**
     * @brief Analyze image with a specific prompt
     * @param imagePath Path to the image
     * @param prompt Custom analysis prompt
     * @return Analysis result
     */
    AnalysisResult analyzeWithPrompt(const std::string& imagePath,
                                      const std::string& prompt);
    
    /**
     * @brief Extract text from image (OCR-like)
     * @param imagePath Path to the image
     * @return Extracted text content
     */
    std::string extractText(const std::string& imagePath);
    
    /**
     * @brief Describe image content
     * @param imagePath Path to the image
     * @return Natural language description
     */
    std::string describeImage(const std::string& imagePath);
    
    /**
     * @brief Analyze multiple images
     * @param imagePaths Vector of image paths
     * @return Vector of analysis results
     */
    std::vector<AnalysisResult> analyzeBatch(const std::vector<std::string>& imagePaths);
    
    /**
     * @brief Analyze video by extracting key frames
     * @param videoPath Path to video file
     * @param maxFrames Maximum number of frames to analyze
     * @return Analysis result with combined frame descriptions
     */
    AnalysisResult analyzeVideo(const std::string& videoPath, int maxFrames = 5);
    
    /**
     * @brief Compare two images
     * @param imagePath1 First image path
     * @param imagePath2 Second image path
     * @return Comparison description
     */
    std::string compareImages(const std::string& imagePath1, 
                              const std::string& imagePath2);
    
    /**
     * @brief Set custom prompts
     */
    void setAnalysisPrompt(const std::string& prompt);
    void setDescriptionPrompt(const std::string& prompt);
    void setOCRPrompt(const std::string& prompt);
    
    /**
     * @brief Set progress callback for batch operations
     */
    using ProgressCallback = std::function<void(size_t current, size_t total, 
                                                 const std::string& currentFile)>;
    void setProgressCallback(ProgressCallback callback);
    
    /**
     * @brief Check if a file is a supported image format
     */
    static bool isSupportedImage(const std::string& path);
    
    /**
     * @brief Check if a file is a supported video format
     */
    static bool isSupportedVideo(const std::string& path);

private:
    std::shared_ptr<ModelRouter> router_;
    std::string analysisPrompt_;
    std::string descriptionPrompt_;
    std::string ocrPrompt_;
    ProgressCallback progressCallback_;
    
    // Helper methods
    std::string loadImageAsBase64(const std::string& path);
    std::string getMimeType(const std::string& path);
    ImageContent createImageContent(const std::string& path);
    void initDefaultPrompts();
};

} // namespace llm
} // namespace forensics
