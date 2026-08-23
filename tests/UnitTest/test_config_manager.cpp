#include <gtest/gtest.h>
#include <gmock/gmock.h>
#include <filesystem>
#include <fstream>
#include "ConfigManager/ConfigManager.h"

namespace fs = std::filesystem;
using namespace forensics::llm;

class ConfigManagerTest : public ::testing::Test {
protected:
    void SetUp() override {
        // Create a unique temporary directory for this test
        testDir_ = fs::temp_directory_path() / ("config_test_" + std::to_string(std::rand()));
        fs::create_directories(testDir_);
        
        // Setup directory structure:
        // testDir/
        //   .env (Master .env)
        //   child/
        //     grandchild/
        
        childDir_ = testDir_ / "child";
        grandchildDir_ = childDir_ / "grandchild";
        
        fs::create_directories(grandchildDir_);
        
        envFile_ = testDir_ / ".env";
    }

    void TearDown() override {
        fs::remove_all(testDir_);
    }
    
    void createEnvFile(const std::string& content) {
        std::ofstream ofs(envFile_);
        ofs << content;
        ofs.close();
    }
    
    fs::path testDir_;
    fs::path childDir_;
    fs::path grandchildDir_;
    fs::path envFile_;
};


TEST_F(ConfigManagerTest, LoadFromCurrentDirectory) {
    createEnvFile("TEST_KEY_1=value1");
    
    // Change CWD to testDir where .env is
    auto currentPath = fs::current_path();
    fs::current_path(testDir_);
    
    auto& config = forensics::ConfigManager::instance();
    bool loaded = config.load(".env");
    
    EXPECT_TRUE(loaded);
    EXPECT_EQ(config.get("TEST_KEY_1"), "value1");
    
    fs::current_path(currentPath);
}

TEST_F(ConfigManagerTest, LoadFromParentDirectory) {
    createEnvFile("TEST_KEY_2=value2");
    
    // Change CWD to childDir (one level deep)
    auto currentPath = fs::current_path();
    fs::current_path(childDir_);
    
    auto& config = forensics::ConfigManager::instance();
    // Force reload/search
    bool loaded = config.load(".env");
    
    EXPECT_TRUE(loaded);
    EXPECT_EQ(config.get("TEST_KEY_2"), "value2");
    
    fs::current_path(currentPath);
}

TEST_F(ConfigManagerTest, LoadFromGrandParentDirectory) {
    createEnvFile("TEST_KEY_3=value3");
    
    // Change CWD to grandchildDir (two levels deep)
    // This simulates running from build/bin/ while .env is in project root
    auto currentPath = fs::current_path();
    fs::current_path(grandchildDir_);
    
    auto& config = forensics::ConfigManager::instance();
    bool loaded = config.load(".env");
    
    EXPECT_TRUE(loaded);
    EXPECT_EQ(config.get("TEST_KEY_3"), "value3");
    
    fs::current_path(currentPath);
}
TEST_F(ConfigManagerTest, EventClusterLimitIsConfigurable) {
    createEnvFile("LLM_MAX_EVENT_CLUSTERS=37\n");
    auto currentPath = fs::current_path();
    fs::current_path(testDir_);

    auto& config = forensics::ConfigManager::instance();
    ASSERT_TRUE(config.load(".env"));
    EXPECT_EQ(config.getLLMMaxEventClusters(), 37);

    fs::current_path(currentPath);
}


int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
