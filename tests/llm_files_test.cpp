#include "integration/LLMIntegration/ConfigManager.h"
#include "integration/LLMIntegration/ModelRouter.h"
#include "integration/LLMIntegration/FileAnalyzer.h"
#include "analyzers/VisionAnalysis/VisionAnalyzer.h"
#include <iostream>
#include <vector>
#include <filesystem>
#include <thread>
#include <chrono>

namespace fs = std::filesystem;
using namespace forensics::llm;

int main() {
    std::cout << "=== Testing 13 Files with Multi-Model LLM ===" << std::endl;

    // 1. Load Config
    if (!forensics::ConfigManager::instance().load(".env")) {
        std::cerr << "Failed to load .env" << std::endl;
        return 1;
    }

    std::cout << "Configuration Loaded:" << std::endl;
    std::cout << "Text Base URL: " << forensics::ConfigManager::instance().getTextBaseUrl() << std::endl;
    std::cout << "Vision Base URL: " << forensics::ConfigManager::instance().getVisionBaseUrl() << std::endl;

    // 2. Setup Router
    auto router = std::make_shared<ModelRouter>();
    
    // Add Text Model
    ModelInfo textInfo;
    textInfo.name = forensics::ConfigManager::instance().getTextModel();
    std::cout << "Text Model Name: '" << textInfo.name << "'" << std::endl;
    textInfo.capabilities = {ModelCapability::TextGeneration, ModelCapability::Analysis};
    textInfo.priority = 10;
    router->addModel("text-model", forensics::ConfigManager::instance().getTextModelConfig(), textInfo);

    // Add Vision Model
    ModelInfo visionInfo;
    visionInfo.name = forensics::ConfigManager::instance().getVisionModel();
    std::cout << "Vision Model Name: '" << visionInfo.name << "'" << std::endl;
    visionInfo.capabilities = {ModelCapability::Vision, ModelCapability::ImageAnalysis};
    visionInfo.supportsVision = true;
    visionInfo.priority = 10;
    router->addModel("vision-model", forensics::ConfigManager::instance().getVisionModelConfig(), visionInfo);

    // 3. Setup Analyzers
    FileAnalyzer fileAnalyzer(router);
    VisionAnalyzer visionAnalyzer(router);

    // DEBUG: Direct LLMClient Test
    std::cout << "\n[DEBUG] Running Direct LLMClient Test..." << std::endl;
    LLMClient debugClient(forensics::ConfigManager::instance().getTextModelConfig());
    if (debugClient.testConnection()) {
         std::cout << "[DEBUG] Connection Test Passed" << std::endl;
         auto resp = debugClient.chat("Hello", "You are a test.");
         std::cout << "[DEBUG] Direct Chat Result: Success=" << resp.success << " Error='" << resp.errorMessage << "'" << std::endl;
    } else {
         std::cout << "[DEBUG] Connection Test Failed: " << debugClient.getLastError() << std::endl;
    }

    // 4. Define Files
    // 4. Discover Files
    std::string testDir = "tests/test_data_13";
    std::vector<std::string> files;
    
    if (fs::exists(testDir) && fs::is_directory(testDir)) {
        for (const auto& entry : fs::directory_iterator(testDir)) {
            if (entry.is_regular_file()) {
                files.push_back(entry.path().string());
            }
        }
        // Sort for consistent order
        std::sort(files.begin(), files.end());
    } else {
        std::cerr << "Test directory not found: " << testDir << std::endl;
        return 1;
    }
    
    std::cout << "Found " << files.size() << " files in " << testDir << std::endl;

    int successCount = 0;

    // 5. Process
    for (const auto& path : files) {
        if (!fs::exists(path)) {
            std::cerr << "File not found: " << path << std::endl;
            continue;
        }

        std::cout << "\n--------------------------------------------------" << std::endl;
        std::cout << "Analyzing: " << path << std::endl;
        
        AnalysisResult result;
        bool isVision = false;

        if (VisionAnalyzer::isSupportedImage(path)) {
            std::cout << "[Type: Image] -> Routing to VisionAnalyzer (Qwen3 VL)" << std::endl;
            result = visionAnalyzer.analyzeImage(path);
            isVision = true;
        } else {
            std::cout << "[Type: Text/Other] -> Routing to FileAnalyzer (GPT OSS)" << std::endl;
            result = fileAnalyzer.analyzeFile(path);
        }

        if (result.success) {
            successCount++;
            std::cout << "SUCCESS" << std::endl;
            // Always print which model was likely used (based on our logic or metadata)
            // Note: AnalysisResult has modelUsed field
            std::cout << "Model Used: " << result.modelUsed << std::endl;
            std::cout << "Summary: " << result.summary << std::endl;
        } else {
            std::cerr << "FAILED: '" << result.errorMessage << "'" << std::endl;
        }
        
        // Small delay to avoid rate limits if any
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    std::cout << "\n--------------------------------------------------" << std::endl;
    std::cout << "Finished. Successful: " << successCount << "/" << files.size() << std::endl;

    return 0;
}
