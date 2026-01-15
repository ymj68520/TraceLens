#include <gtest/gtest.h>
#include <gmock/gmock.h>

#include "../../src/core/Logger/Logger.h"

#include <fstream>
#include <filesystem>
#include <sstream>

using namespace forensics;
namespace fs = std::filesystem;

// ============================================================================
// Logger Basic Tests
// ============================================================================

class LoggerTest : public ::testing::Test {
protected:
    void SetUp() override {
        testLogFile_ = fs::temp_directory_path() / "test_logger.log";
        // Reset logger to default state
        Logger::instance().setLevel(LogLevel::DEBUG);
        Logger::instance().setOutput(LogOutput::NONE);
    }
    
    void TearDown() override {
        Logger::instance().setOutput(LogOutput::NONE);
        if (fs::exists(testLogFile_)) {
            fs::remove(testLogFile_);
        }
    }
    
    std::string readLogFile() {
        std::ifstream f(testLogFile_);
        std::ostringstream oss;
        oss << f.rdbuf();
        return oss.str();
    }
    
    fs::path testLogFile_;
};

TEST_F(LoggerTest, SetAndGetLevel) {
    Logger::instance().setLevel(LogLevel::WARNING);
    EXPECT_EQ(Logger::instance().getLevel(), LogLevel::WARNING);
    
    Logger::instance().setLevel(LogLevel::DEBUG);
    EXPECT_EQ(Logger::instance().getLevel(), LogLevel::DEBUG);
}

TEST_F(LoggerTest, SetAndGetOutput) {
    Logger::instance().setOutput(LogOutput::STDOUT);
    EXPECT_EQ(Logger::instance().getOutput(), LogOutput::STDOUT);
    
    Logger::instance().setOutput(LogOutput::NONE);
    EXPECT_EQ(Logger::instance().getOutput(), LogOutput::NONE);
}

TEST_F(LoggerTest, OutputToFile) {
    Logger::instance().setOutput(LogOutput::FILE, testLogFile_.string());
    Logger::instance().setLevel(LogLevel::DEBUG);
    
    LOG_DEBUG("Test debug message");
    LOG_INFO("Test info message");
    LOG_WARNING("Test warning message");
    LOG_ERROR("Test error message");
    
    Logger::instance().flush();
    Logger::instance().setOutput(LogOutput::NONE);  // Close file
    
    std::string content = readLogFile();
    
    EXPECT_NE(content.find("Test debug message"), std::string::npos);
    EXPECT_NE(content.find("Test info message"), std::string::npos);
    EXPECT_NE(content.find("[DEBUG]"), std::string::npos);
    EXPECT_NE(content.find("[INFO]"), std::string::npos);
    EXPECT_NE(content.find("[WARN]"), std::string::npos);
    EXPECT_NE(content.find("[ERROR]"), std::string::npos);
}

TEST_F(LoggerTest, LogLevelFiltering) {
    Logger::instance().setOutput(LogOutput::FILE, testLogFile_.string());
    Logger::instance().setLevel(LogLevel::WARNING);
    
    LOG_DEBUG("This should not appear");
    LOG_INFO("This should not appear");
    LOG_WARNING("This should appear");
    LOG_ERROR("This should also appear");
    
    Logger::instance().flush();
    Logger::instance().setOutput(LogOutput::NONE);
    
    std::string content = readLogFile();
    
    EXPECT_EQ(content.find("This should not appear"), std::string::npos);
    EXPECT_NE(content.find("This should appear"), std::string::npos);
    EXPECT_NE(content.find("This should also appear"), std::string::npos);
}

TEST_F(LoggerTest, SilentModeNoOutput) {
    Logger::instance().setOutput(LogOutput::NONE);
    Logger::instance().setLevel(LogLevel::DEBUG);
    
    // These should not throw and should not write anywhere
    EXPECT_NO_THROW(LOG_DEBUG("Silent debug"));
    EXPECT_NO_THROW(LOG_INFO("Silent info"));
    EXPECT_NO_THROW(LOG_WARNING("Silent warning"));
    EXPECT_NO_THROW(LOG_ERROR("Silent error"));
}

TEST_F(LoggerTest, TimestampFormat) {
    Logger::instance().setOutput(LogOutput::FILE, testLogFile_.string());
    Logger::instance().setLevel(LogLevel::INFO);
    
    LOG_INFO("Timestamp test");
    
    Logger::instance().flush();
    Logger::instance().setOutput(LogOutput::NONE);
    
    std::string content = readLogFile();
    
    // Check for timestamp pattern: YYYY-MM-DD HH:MM:SS.mmm
    // Look for date separator '-' and time separator ':'
    EXPECT_NE(content.find("-"), std::string::npos);
    EXPECT_NE(content.find(":"), std::string::npos);
}

TEST_F(LoggerTest, SingletonBehavior) {
    Logger& logger1 = Logger::instance();
    Logger& logger2 = Logger::instance();
    
    EXPECT_EQ(&logger1, &logger2);  // Same instance
}

// ============================================================================
// Main
// ============================================================================

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
