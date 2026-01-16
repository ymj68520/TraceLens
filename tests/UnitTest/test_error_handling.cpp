#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include "../../src/core/ErrorHandling/ErrorHandling.h"

#include <string>
#include <stdexcept>

using namespace forensics;

// ============================================================================
// ErrorCode Tests
// ============================================================================

TEST(ErrorCodeTest, ErrorCodeValues) {
    EXPECT_EQ(static_cast<int>(ErrorCode::Success), 0);
    EXPECT_EQ(static_cast<int>(ErrorCode::FileNotFound), 100);
    EXPECT_EQ(static_cast<int>(ErrorCode::LLMConnectionFailed), 200);
    EXPECT_EQ(static_cast<int>(ErrorCode::NoModelsAvailable), 300);
    EXPECT_EQ(static_cast<int>(ErrorCode::InvalidConfiguration), 400);
    EXPECT_EQ(static_cast<int>(ErrorCode::DatabaseOpenError), 500);
    EXPECT_EQ(static_cast<int>(ErrorCode::AnalysisFailed), 600);
}

TEST(ErrorCodeTest, ErrorCodeToString) {
    EXPECT_STREQ(errorCodeToString(ErrorCode::Success), "Success");
    EXPECT_STREQ(errorCodeToString(ErrorCode::FileNotFound), "File not found");
    EXPECT_STREQ(errorCodeToString(ErrorCode::LLMConnectionFailed), "LLM connection failed");
    EXPECT_STREQ(errorCodeToString(ErrorCode::NoModelsAvailable), "No LLM models available");
    EXPECT_STREQ(errorCodeToString(ErrorCode::AllModelsFailed), "All models failed");
    EXPECT_STREQ(errorCodeToString(ErrorCode::Cancelled), "Operation cancelled"); // Check if correct
}

// ============================================================================
// Result<T> Tests
// ============================================================================

TEST(ResultTest, SuccessWithValue) {
    auto result = Result<int>::success(42);
    
    EXPECT_TRUE(result.isSuccess());
    EXPECT_FALSE(result.isError());
    EXPECT_EQ(result.value(), 42);
    EXPECT_EQ(result.errorCode(), ErrorCode::Success);
    EXPECT_TRUE(static_cast<bool>(result));
}

TEST(ResultTest, ErrorWithCode) {
    auto result = Result<int>::error(ErrorCode::FileNotFound);
    
    EXPECT_FALSE(result.isSuccess());
    EXPECT_TRUE(result.isError());
    EXPECT_EQ(result.errorCode(), ErrorCode::FileNotFound);
    EXPECT_EQ(result.errorMessage(), "File not found");
    EXPECT_FALSE(static_cast<bool>(result));
}

TEST(ResultTest, ErrorWithCustomMessage) {
    auto result = Result<int>::error(ErrorCode::FileNotFound, "Custom error message");
    
    EXPECT_FALSE(result.isSuccess());
    EXPECT_EQ(result.errorCode(), ErrorCode::FileNotFound);
    EXPECT_EQ(result.errorMessage(), "Custom error message");
}

TEST(ResultTest, ValueOrWithSuccess) {
    auto result = Result<int>::success(100);
    
    EXPECT_EQ(result.valueOr(999), 100);
}

TEST(ResultTest, ValueOrWithError) {
    auto result = Result<int>::error(ErrorCode::InternalError);
    
    EXPECT_EQ(result.valueOr(999), 999);
}

TEST(ResultTest, ValueThrowsOnError) {
    auto result = Result<int>::error(ErrorCode::FileNotFound);
    
    EXPECT_THROW(result.value(), std::runtime_error);
}

TEST(ResultTest, StringResult) {
    auto success = Result<std::string>::success("Hello World");
    EXPECT_EQ(success.value(), "Hello World");
    
    auto error = Result<std::string>::error(ErrorCode::LLMResponseParseError);
    EXPECT_FALSE(error.isSuccess());
    EXPECT_EQ(error.valueOr("default"), "default");
}

TEST(ResultTest, VectorResult) {
    std::vector<int> data = {1, 2, 3, 4, 5};
    auto result = Result<std::vector<int>>::success(data);
    
    EXPECT_TRUE(result.isSuccess());
    EXPECT_EQ(result.value().size(), 5);
    EXPECT_EQ(result.value()[0], 1);
    EXPECT_EQ(result.value()[4], 5);
}

// ============================================================================
// Result<void> Tests
// ============================================================================

TEST(ResultVoidTest, SuccessVoid) {
    auto result = Result<void>::success();
    
    EXPECT_TRUE(result.isSuccess());
    EXPECT_FALSE(result.isError());
    EXPECT_EQ(result.errorCode(), ErrorCode::Success);
    EXPECT_TRUE(static_cast<bool>(result));
}

TEST(ResultVoidTest, ErrorVoid) {
    auto result = Result<void>::error(ErrorCode::DatabaseWriteError, "Write failed");
    
    EXPECT_FALSE(result.isSuccess());
    EXPECT_TRUE(result.isError());
    EXPECT_EQ(result.errorCode(), ErrorCode::DatabaseWriteError);
    EXPECT_EQ(result.errorMessage(), "Write failed");
}

// ============================================================================
// Usage Example Tests
// ============================================================================

Result<int> divide(int a, int b) {
    if (b == 0) {
        return Result<int>::error(ErrorCode::InternalError, "Division by zero");
    }
    return Result<int>::success(a / b);
}

TEST(ResultUsageTest, DivisionSuccess) {
    auto result = divide(10, 2);
    
    EXPECT_TRUE(result.isSuccess());
    EXPECT_EQ(result.value(), 5);
}

TEST(ResultUsageTest, DivisionError) {
    auto result = divide(10, 0);
    
    EXPECT_FALSE(result.isSuccess());
    EXPECT_EQ(result.errorCode(), ErrorCode::InternalError);
    EXPECT_EQ(result.errorMessage(), "Division by zero");
}

Result<std::string> readFile(const std::string& path) {
    if (path.empty()) {
        return Result<std::string>::error(ErrorCode::InvalidFilePath);
    }
    if (path == "/nonexistent") {
        return Result<std::string>::error(ErrorCode::FileNotFound);
    }
    return Result<std::string>::success("File content");
}

TEST(ResultUsageTest, FileReadSuccess) {
    auto result = readFile("/valid/path");
    EXPECT_TRUE(result.isSuccess());
    EXPECT_EQ(result.value(), "File content");
}

TEST(ResultUsageTest, FileReadError) {
    auto result = readFile("");
    EXPECT_EQ(result.errorCode(), ErrorCode::InvalidFilePath);
    
    auto result2 = readFile("/nonexistent");
    EXPECT_EQ(result2.errorCode(), ErrorCode::FileNotFound);
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
