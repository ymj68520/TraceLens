// Unit tests for DLLAnalyzerLLMService
#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include "analyzers/DLLAnalyzer/Core/DLLAnalyzerLLMService.h"
#include "analyzers/DLLAnalyzer/Common/DLLDataTypes.h"
#include "LLMIntegration/LLMDataTypes.h"

using namespace forensics::dll;
using namespace forensics::llm;

// ============================================================================
// DLLAnalysisOptions Tests
// ============================================================================

TEST(DLLAnalyzerLLMServiceTest, DefaultOptions) {
    DLLAnalysisOptions options;

    EXPECT_EQ(options.maxContentLength, 10000);
    EXPECT_TRUE(options.generateSummary);
    EXPECT_TRUE(options.generateDescription);
    EXPECT_TRUE(options.extractKeywords);
    EXPECT_TRUE(options.analyzeThreats);
    EXPECT_TRUE(options.analyzeBehavior);
    EXPECT_TRUE(options.focusAreas.empty());
}

TEST(DLLAnalyzerLLMServiceTest, CustomOptions) {
    DLLAnalysisOptions options;
    options.maxContentLength = 5000;
    options.generateSummary = false;
    options.analyzeThreats = false;
    options.focusAreas = {"behavior", "threats"};

    EXPECT_EQ(options.maxContentLength, 5000);
    EXPECT_FALSE(options.generateSummary);
    EXPECT_FALSE(options.analyzeThreats);
    EXPECT_EQ(options.focusAreas.size(), 2);
}

// ============================================================================
// DLLLLMResult Tests
// ============================================================================

TEST(DLLAnalyzerLLMServiceTest, DefaultLLMResult) {
    DLLLLMResult result;

    EXPECT_TRUE(result.summary.empty());
    EXPECT_TRUE(result.description.empty());
    EXPECT_TRUE(result.keywords.empty());
    EXPECT_TRUE(result.threatAssessment.empty());
    EXPECT_TRUE(result.behaviorAnalysis.empty());
    EXPECT_TRUE(result.indicators.empty());
    EXPECT_TRUE(result.recommendations.empty());
    EXPECT_TRUE(result.modelUsed.empty());
    EXPECT_EQ(result.tokensUsed, 0);
    EXPECT_EQ(result.analysisTimeMs, 0.0);
    EXPECT_FALSE(result.success);
    EXPECT_TRUE(result.errorMessage.empty());
}

// ============================================================================
// Initialization Tests
// ============================================================================

TEST(DLLAnalyzerLLMServiceTest, InitialState) {
    DLLAnalyzerLLMService service;

    EXPECT_FALSE(service.isAvailable());
    EXPECT_TRUE(service.getLastError().empty());
}

// ============================================================================
// Integration Test
// ============================================================================

TEST(DLLAnalyzerLLMServiceTest, ServiceCreation) {
    DLLAnalyzerLLMService service;

    // Service should start uninitialized
    EXPECT_FALSE(service.isAvailable());

    // Manual initialization would require .env config
    // For now, just verify the service object can be created and queried
    EXPECT_TRUE(service.getLastError().empty());
}

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
