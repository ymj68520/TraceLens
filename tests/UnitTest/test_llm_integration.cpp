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
// Main
// ============================================================================

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
