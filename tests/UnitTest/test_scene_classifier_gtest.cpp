// test_scene_classifier_gtest.cpp
// GTest-based unit tests for FileClassifier scene-aware classification
// Tests scene type management and platform-specific priority calculation

#include <gtest/gtest.h>
#include "DatabaseManager/FileClassifier/FileClassifier.h"

class SceneClassifierTest : public ::testing::Test {
protected:
    void SetUp() override {
        dbPath_ = ":memory:";
    }

    std::string dbPath_;
};

TEST_F(SceneClassifierTest, SceneTypeNoneByDefault) {
    FileClassifier classifier(":memory:", ":memory:");
    EXPECT_EQ(classifier.getSceneType(), SceneType::NONE);
}

TEST_F(SceneClassifierTest, SetSceneTypeAndroid) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);
    EXPECT_EQ(classifier.getSceneType(), SceneType::ANDROID);
}

TEST_F(SceneClassifierTest, SetSceneTypeWindows) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::WINDOWS);
    EXPECT_EQ(classifier.getSceneType(), SceneType::WINDOWS);
}

TEST_F(SceneClassifierTest, SetSceneTypeLinux) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::LINUX);
    EXPECT_EQ(classifier.getSceneType(), SceneType::LINUX);
}

TEST_F(SceneClassifierTest, AndroidScenePriorityCritical) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);

    EXPECT_EQ(classifier.calculateScenePriority("/data/data/com.android.providers.contacts/", "contacts.db", FileCategory::DATABASE), ScenePriority::CRITICAL);
    EXPECT_EQ(classifier.calculateScenePriority("/data/system/", "system.db", FileCategory::DATABASE), ScenePriority::CRITICAL);
}

TEST_F(SceneClassifierTest, AndroidScenePriorityHigh) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);

    EXPECT_EQ(classifier.calculateScenePriority("/data/data/com.tencent.mm/", "mm.db", FileCategory::DATABASE), ScenePriority::HIGH);
    EXPECT_EQ(classifier.calculateScenePriority("/data/app/", "app.apk", FileCategory::ARCHIVE), ScenePriority::HIGH);
}

TEST_F(SceneClassifierTest, AndroidScenePriorityIrrelevant) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::ANDROID);

    EXPECT_EQ(classifier.calculateScenePriority("/Windows/System32/config/", "SAM", FileCategory::SYSTEM), ScenePriority::IRRELEVANT);
    EXPECT_EQ(classifier.calculateScenePriority("/usr/lib/", "lib.so", FileCategory::SYSTEM), ScenePriority::IRRELEVANT);
}

TEST_F(SceneClassifierTest, WindowsScenePriorityCritical) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::WINDOWS);

    EXPECT_EQ(classifier.calculateScenePriority("/Windows/System32/config/", "SAM", FileCategory::SYSTEM), ScenePriority::CRITICAL);
    EXPECT_EQ(classifier.calculateScenePriority("/Windows/System32/winevt/", "System.evtx", FileCategory::SYSTEM), ScenePriority::CRITICAL);
}

TEST_F(SceneClassifierTest, LinuxScenePriorityCritical) {
    FileClassifier classifier(":memory:", ":memory:");
    classifier.setSceneType(SceneType::LINUX);

    EXPECT_EQ(classifier.calculateScenePriority("/var/log/auth.log", "auth.log", FileCategory::LOG_FILE), ScenePriority::CRITICAL);
    EXPECT_EQ(classifier.calculateScenePriority("/etc/passwd", "passwd", FileCategory::SYSTEM), ScenePriority::CRITICAL);
}

int main(int argc, char **argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
