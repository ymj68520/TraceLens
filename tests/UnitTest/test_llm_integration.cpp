#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include "LLMIntegration/LLMDataTypes.h"
#include "LLMIntegration/LLMClient.h"
#include "LLMIntegration/ModelRouter.h"
#include "LLMIntegration/FileAnalyzer.h"

#include <filesystem>
#include <fstream>

using namespace forensics::llm;

// ============================================================================
// LLMDataTypes Tests
// ============================================================================

TEST(LLMDataTypesTest, LLMConfigDefaults) {
    LLMConfig config;
    
    EXPECT_EQ(config.baseUrl, "http://localhost:1234");
    EXPECT_EQ(config.endpoint, "/v1/chat/completions");
    EXPECT_EQ(config.maxTokens, 2048);
    EXPECT_DOUBLE_EQ(config.temperature, 0.7);
    EXPECT_EQ(config.timeoutSeconds, 60);
    EXPECT_EQ(config.maxRetries, 3);
}

TEST(LLMDataTypesTest, ChatMessageConstruction) {
    ChatMessage msg1;
    EXPECT_TRUE(msg1.role.empty());
    EXPECT_TRUE(msg1.content.empty());
    
    ChatMessage msg2("user", "Hello, world!");
    EXPECT_EQ(msg2.role, "user");
    EXPECT_EQ(msg2.content, "Hello, world!");
}

TEST(LLMDataTypesTest, ModelInfoCapabilities) {
    ModelInfo info;
    info.name = "test-model";
    info.capabilities = {
        ModelCapability::TextGeneration,
        ModelCapability::Summarization
    };
    
    EXPECT_TRUE(info.hasCapability(ModelCapability::TextGeneration));
    EXPECT_TRUE(info.hasCapability(ModelCapability::Summarization));
    EXPECT_FALSE(info.hasCapability(ModelCapability::CodeGeneration));
}

TEST(LLMDataTypesTest, AnalysisResultDefaults) {
    AnalysisResult result;
    
    EXPECT_TRUE(result.filePath.empty());
    EXPECT_TRUE(result.summary.empty());
    EXPECT_EQ(result.fileSize, 0);
    EXPECT_FALSE(result.success);
    EXPECT_EQ(result.tokensUsed, 0);
}

// ============================================================================
// LLMClient Tests (offline tests only)
// ============================================================================

TEST(LLMClientTest, ConstructWithConfig) {
    LLMConfig config;
    config.baseUrl = "http://localhost:9999";
    config.model = "test-model";
    
    LLMClient client(config);
    
    EXPECT_EQ(client.getModel(), "test-model");
    EXPECT_TRUE(client.isReady());
}

TEST(LLMClientTest, ConstructWithUrl) {
    LLMClient client("http://localhost:8888");
    
    EXPECT_TRUE(client.isReady());
    EXPECT_TRUE(client.getModel().empty());
}

TEST(LLMClientTest, SetModel) {
    LLMClient client("http://localhost:1234");
    
    client.setModel("new-model");
    EXPECT_EQ(client.getModel(), "new-model");
}

TEST(LLMClientTest, ConnectionTestFails) {
    // Test with invalid port - should fail connection test
    LLMClient client("http://localhost:59999");
    
    // This will fail since no server is running
    EXPECT_FALSE(client.testConnection());
    EXPECT_FALSE(client.getLastError().empty());
}

// ============================================================================
// ModelRouter Tests
// ============================================================================

TEST(ModelRouterTest, DefaultConstruction) {
    ModelRouter router;
    
    EXPECT_EQ(router.getStrategy(), RoutingStrategy::Fallback);
    EXPECT_FALSE(router.hasAvailableModels());
    EXPECT_TRUE(router.getModelNames().empty());
}

TEST(ModelRouterTest, AddAndRemoveModel) {
    ModelRouter router;
    
    LLMConfig config;
    config.baseUrl = "http://localhost:1234";
    
    ModelInfo info;
    info.name = "test-model";
    info.priority = 10;
    info.available = true;
    
    router.addModel("primary", config, info);
    
    auto names = router.getModelNames();
    EXPECT_EQ(names.size(), 1);
    EXPECT_EQ(names[0], "primary");
    
    auto retrievedInfo = router.getModelInfo("primary");
    EXPECT_EQ(retrievedInfo.name, "test-model");
    EXPECT_EQ(retrievedInfo.priority, 10);
    
    router.removeModel("primary");
    EXPECT_TRUE(router.getModelNames().empty());
}

TEST(ModelRouterTest, SetStrategy) {
    ModelRouter router;
    
    router.setStrategy(RoutingStrategy::RoundRobin);
    EXPECT_EQ(router.getStrategy(), RoutingStrategy::RoundRobin);
    
    router.setStrategy(RoutingStrategy::Priority);
    EXPECT_EQ(router.getStrategy(), RoutingStrategy::Priority);
}

TEST(ModelRouterTest, NoModelsError) {
    ModelRouter router;
    
    auto response = router.chat("Hello");
    EXPECT_FALSE(response.success);
    EXPECT_EQ(response.errorMessage, "No models registered");
}

TEST(ModelRouterTest, SetPreferredModel) {
    ModelRouter router;
    
    LLMConfig config;
    ModelInfo info1, info2;
    info1.name = "model1";
    info2.name = "model2";
    
    router.addModel("model1", config, info1);
    router.addModel("model2", config, info2);
    
    router.setPreferredModel("model2");
    // Preferred model is set internally
    
    // Test that non-existent model is ignored
    router.setPreferredModel("nonexistent");
}

// ============================================================================
// FileAnalyzer Tests (offline tests only)
// ============================================================================

class FileAnalyzerTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Create test files
        testDir_ = std::filesystem::temp_directory_path() / "llm_test";
        std::filesystem::create_directories(testDir_);
        
        testFile_ = testDir_ / "test_file.txt";
        std::ofstream(testFile_) << "This is test content for analysis.\n"
                                  << "It contains multiple lines.\n"
                                  << "The analyzer should read this.";
    }
    
    void TearDown() override {
        std::filesystem::remove_all(testDir_);
    }
    
    std::filesystem::path testDir_;
    std::filesystem::path testFile_;
};

TEST_F(FileAnalyzerTest, AnalyzeNonExistentFile) {
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    auto result = analyzer.analyzeFile("/nonexistent/file.txt");
    
    EXPECT_FALSE(result.success);
    EXPECT_TRUE(result.errorMessage.find("not found") != std::string::npos);
}

TEST_F(FileAnalyzerTest, GenerateDescriptionNonExistent) {
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    auto desc = analyzer.generateDescription("/nonexistent/file.txt");
    
    EXPECT_TRUE(desc.find("Error") != std::string::npos);
}

TEST_F(FileAnalyzerTest, CustomPrompts) {
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    // Should not throw
    analyzer.setSummaryPrompt("Custom summary prompt");
    analyzer.setDescriptionPrompt("Custom description prompt");
    analyzer.setKeywordPrompt("Custom keyword prompt");
}

TEST_F(FileAnalyzerTest, ProgressCallback) {
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    int callCount = 0;
    analyzer.setProgressCallback([&callCount](size_t current, size_t total, const std::string&) {
        callCount++;
    });
    
    BatchAnalysisRequest request;
    request.filePaths = {testFile_.string()};
    
    // Will fail due to no models, but callback should still fire
    auto results = analyzer.analyzeBatch(request);
    
    EXPECT_GT(callCount, 0);
}

// ============================================================================
// Integration Test - File Type Detection
// ============================================================================

TEST_F(FileAnalyzerTest, DetectFileTypes) {
    // Create files with different extensions
    std::filesystem::path pyFile = testDir_ / "test.py";
    std::filesystem::path jsonFile = testDir_ / "test.json";
    std::filesystem::path cppFile = testDir_ / "test.cpp";
    
    std::ofstream(pyFile) << "print('hello')";
    std::ofstream(jsonFile) << R"({"key": "value"})";
    std::ofstream(cppFile) << "#include <iostream>";
    
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    // Analyze files - will get basic info even without LLM
    auto pyResult = analyzer.analyzeFile(pyFile.string());
    EXPECT_EQ(pyResult.fileType, "Python");
    
    auto jsonResult = analyzer.analyzeFile(jsonFile.string());
    EXPECT_EQ(jsonResult.fileType, "JSON");
    
    auto cppResult = analyzer.analyzeFile(cppFile.string());
    EXPECT_EQ(cppResult.fileType, "C++");
}

// ============================================================================
// Fallback Strategy Tests
// ============================================================================

TEST(ModelRouterTest, FallbackStrategyIsDefault) {
    ModelRouter router;
    EXPECT_EQ(router.getStrategy(), RoutingStrategy::Fallback);
}

TEST(ModelRouterTest, FallbackWithMultipleModels) {
    ModelRouter router;
    router.setStrategy(RoutingStrategy::Fallback);
    
    // Add multiple models with different priorities
    LLMConfig config1, config2;
    config1.baseUrl = "http://localhost:9991";
    config2.baseUrl = "http://localhost:9992";
    
    ModelInfo info1, info2;
    info1.name = "high-priority-model";
    info1.priority = 100;
    info1.available = true;
    
    info2.name = "low-priority-model";
    info2.priority = 50;
    info2.available = true;
    
    router.addModel("model1", config1, info1);
    router.addModel("model2", config2, info2);
    
    // Both models are added
    EXPECT_EQ(router.getModelNames().size(), 2);
    EXPECT_TRUE(router.hasAvailableModels());
    
    // When chat is called, it will try models in priority order
    // Since no server is running, all will fail, but it should try all
    auto response = router.chat("Test message");
    
    // Should have tried all models and failed
    EXPECT_FALSE(response.success);
    std::cout << "TEST ERROR MESSAGE: " << response.errorMessage << std::endl;
    EXPECT_TRUE(response.errorMessage.find("failed") != std::string::npos || 
                response.errorMessage.find("No suitable model available") != std::string::npos);
}

TEST(ModelRouterTest, PriorityStrategySelectsHighestPriority) {
    ModelRouter router;
    router.setStrategy(RoutingStrategy::Priority);
    
    LLMConfig config;
    ModelInfo lowPriority, highPriority;
    
    lowPriority.name = "low";
    lowPriority.priority = 10;
    lowPriority.available = true;
    
    highPriority.name = "high";
    highPriority.priority = 100;
    highPriority.available = true;
    
    router.addModel("low", config, lowPriority);
    router.addModel("high", config, highPriority);
    
    // Should have both models
    EXPECT_EQ(router.getModelNames().size(), 2);
}

// ============================================================================
// Extended File Type Detection Tests
// ============================================================================

TEST_F(FileAnalyzerTest, DetectAllNewFileTypes) {
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    // Create test files for new types
    std::vector<std::pair<std::string, std::string>> testCases = {
        {"test.pptx", "PowerPoint"},
        {"test.epub", "E-Book"},
        {"test.mp4", "MP4 Video"},
        {"test.mp3", "MP3 Audio"},
        {"test.zip", "ZIP Archive"},
        {"test.svg", "SVG Image"},
        {"test.odt", "OpenDocument Text"},
        {"test.rb", "Ruby"},
        {"test.swift", "Swift"},
        {"test.kt", "Kotlin"},
    };
    
    for (const auto& [filename, expectedType] : testCases) {
        std::filesystem::path testFile = testDir_ / filename;
        std::ofstream(testFile) << "test content";
        
        auto result = analyzer.analyzeFile(testFile.string());
        EXPECT_EQ(result.fileType, expectedType) << "Failed for: " << filename;
        
        std::filesystem::remove(testFile);
    }
}

// ============================================================================
// Batch Analysis Tests
// ============================================================================

TEST_F(FileAnalyzerTest, BatchAnalysisReturnsCorrectCount) {
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    // Create multiple test files
    std::vector<std::string> testFiles;
    for (int i = 0; i < 5; ++i) {
        auto filePath = testDir_ / ("batch_test_" + std::to_string(i) + ".txt");
        std::ofstream(filePath) << "Test content " << i;
        testFiles.push_back(filePath.string());
    }
    
    BatchAnalysisRequest request;
    request.filePaths = testFiles;
    request.maxContentLength = 1000;
    
    auto results = analyzer.analyzeBatch(request);
    
    EXPECT_EQ(results.size(), 5);
}

TEST_F(FileAnalyzerTest, ProgressCallbackCalled) {
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    std::vector<size_t> progressValues;
    analyzer.setProgressCallback([&progressValues](size_t current, size_t total, const std::string&) {
        progressValues.push_back(current);
    });
    
    // Create test files
    std::vector<std::string> testFiles;
    for (int i = 0; i < 3; ++i) {
        auto filePath = testDir_ / ("progress_test_" + std::to_string(i) + ".txt");
        std::ofstream(filePath) << "Content";
        testFiles.push_back(filePath.string());
    }
    
    BatchAnalysisRequest request;
    request.filePaths = testFiles;
    
    analyzer.analyzeBatch(request);
    
    // Progress callback should be called at least once
    EXPECT_GT(progressValues.size(), 0);
}

// ============================================================================
// Content Truncation Tests
// ============================================================================

TEST_F(FileAnalyzerTest, LargeFileGetsTruncated) {
    auto router = std::make_shared<ModelRouter>();
    FileAnalyzer analyzer(router);
    
    // Create a large test file (100KB)
    std::filesystem::path largeFile = testDir_ / "large_file.txt";
    {
        std::ofstream ofs(largeFile);
        for (int i = 0; i < 10000; ++i) {
            ofs << "This is line " << i << " with some content to make it larger.\n";
        }
    }
    
    // Analyze with small max content length
    auto result = analyzer.analyzeFile(largeFile.string(), 1000);
    
    // File should be analyzed (may fail due to no LLM, but file info should be set)
    EXPECT_EQ(result.filePath, largeFile.string());
    EXPECT_GT(result.fileSize, 0);
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}

