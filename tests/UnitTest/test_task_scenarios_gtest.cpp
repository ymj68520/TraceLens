#include <gtest/gtest.h>
#include <nlohmann/json.hpp>
#include "network/HTTPServer/HTTPServerDataTypes.h"
#include "network/HTTPServer/TaskSerialization.h"

namespace forensics {
namespace {

TEST(ForensicScenarioTest, ScenarioToString) {
    EXPECT_EQ(scenario_to_string(ForensicScenario::ANDROID), "android");
    EXPECT_EQ(scenario_to_string(ForensicScenario::WINDOWS), "windows");
    EXPECT_EQ(scenario_to_string(ForensicScenario::LINUX), "linux");
    EXPECT_EQ(scenario_to_string(ForensicScenario::SERVER_CLOUD), "server_cloud");
}

TEST(ForensicScenarioTest, StringToScenario) {
    EXPECT_EQ(string_to_scenario("android"), ForensicScenario::ANDROID);
    EXPECT_EQ(string_to_scenario("windows"), ForensicScenario::WINDOWS);
    EXPECT_EQ(string_to_scenario("linux"), ForensicScenario::LINUX);
    EXPECT_EQ(string_to_scenario("server_cloud"), ForensicScenario::SERVER_CLOUD);
    EXPECT_EQ(string_to_scenario("invalid"), std::nullopt);
    EXPECT_EQ(string_to_scenario(""), std::nullopt);
}

TEST(ForensicScenarioTest, ScenarioRoundTrip) {
    // Verify round-trip through nlohmann::json serialization
    std::vector<ForensicScenario> original = {
        ForensicScenario::ANDROID, ForensicScenario::WINDOWS
    };

    nlohmann::json j = original;
    auto deserialized = j.get<std::vector<ForensicScenario>>();

    EXPECT_EQ(deserialized.size(), 2);
    EXPECT_EQ(deserialized[0], ForensicScenario::ANDROID);
    EXPECT_EQ(deserialized[1], ForensicScenario::WINDOWS);
}

TEST(AnalysisTaskTest, ScenariosFieldSerialization) {
    AnalysisTask task;
    task.id = "test-123";
    task.scenarios = {ForensicScenario::ANDROID, ForensicScenario::WINDOWS};

    nlohmann::json j;
    to_json(j, task);

    EXPECT_TRUE(j.contains("scenarios"));
    EXPECT_EQ(j["scenarios"].size(), 2);
    EXPECT_EQ(j["scenarios"][0].get<std::string>(), "android");
    EXPECT_EQ(j["scenarios"][1].get<std::string>(), "windows");

    // Backward compat field
    EXPECT_TRUE(j.contains("android_analyze"));
    EXPECT_TRUE(j["android_analyze"].get<bool>());
}

TEST(AnalysisTaskTest, BackwardCompatFromJson) {
    // Old format with android_analyze: true
    nlohmann::json j = {
        {"id", "test-456"},
        {"image_path", "/test/image.dd"},
        {"status", "PENDING"},
        {"message", ""},
        {"output_files_db", ""},
        {"output_raw_db", ""},
        {"output_events_db", ""},
        {"priority", "NORMAL"},
        {"progress", {
            {"current_phase", "INITIALIZING"},
            {"phase_percentage", 0},
            {"overall_percentage", 0},
            {"phase_description", ""}
        }},
        {"android_analyze", true}
    };

    AnalysisTask task;
    from_json(j, task);

    EXPECT_EQ(task.scenarios.size(), 1);
    EXPECT_EQ(task.scenarios[0], ForensicScenario::ANDROID);
    EXPECT_TRUE(task.get_android_analyze());
}

TEST(AnalysisTaskTest, NewFormatFromJson) {
    nlohmann::json j = {
        {"id", "test-789"},
        {"image_path", "/test/image.dd"},
        {"status", "PENDING"},
        {"message", ""},
        {"output_files_db", ""},
        {"output_raw_db", ""},
        {"output_events_db", ""},
        {"priority", "NORMAL"},
        {"progress", {
            {"current_phase", "INITIALIZING"},
            {"phase_percentage", 0},
            {"overall_percentage", 0},
            {"phase_description", ""}
        }},
        {"scenarios", {"android", "linux"}}
    };

    AnalysisTask task;
    from_json(j, task);

    EXPECT_EQ(task.scenarios.size(), 2);
    EXPECT_EQ(task.scenarios[0], ForensicScenario::ANDROID);
    EXPECT_EQ(task.scenarios[1], ForensicScenario::LINUX);
    EXPECT_TRUE(task.get_android_analyze());
}

TEST(AnalysisTaskTest, EmptyScenariosFromJson) {
    nlohmann::json j = {
        {"id", "test-empty"},
        {"image_path", "/test/image.dd"},
        {"status", "PENDING"},
        {"message", ""},
        {"output_files_db", ""},
        {"output_raw_db", ""},
        {"output_events_db", ""},
        {"priority", "NORMAL"},
        {"progress", {
            {"current_phase", "INITIALIZING"},
            {"phase_percentage", 0},
            {"overall_percentage", 0},
            {"phase_description", ""}
        }},
        {"android_analyze", false}
    };

    AnalysisTask task;
    from_json(j, task);

    EXPECT_TRUE(task.scenarios.empty());
    EXPECT_FALSE(task.get_android_analyze());
}

TEST(AnalysisTaskTest, CopyPreservesScenarios) {
    AnalysisTask original;
    original.id = "copy-test";
    original.scenarios = {ForensicScenario::WINDOWS, ForensicScenario::SERVER_CLOUD};

    AnalysisTask copy = original;
    EXPECT_EQ(copy.scenarios.size(), 2);
    EXPECT_EQ(copy.scenarios[0], ForensicScenario::WINDOWS);
    EXPECT_EQ(copy.scenarios[1], ForensicScenario::SERVER_CLOUD);
}

TEST(SceneConfigTest, DefaultValues) {
    AnalysisTask::SceneConfig config;
    EXPECT_FALSE(config.enabled);
    EXPECT_EQ(config.priorityThreshold, 50);
    EXPECT_FALSE(config.autoDetect);
    EXPECT_TRUE(config.customRules.empty());
}

TEST(SceneConfigTest, MapStorage) {
    AnalysisTask task;
    task.id = "scene-config-test";

    AnalysisTask::SceneConfig androidConfig;
    androidConfig.enabled = true;
    androidConfig.priorityThreshold = 75;
    androidConfig.autoDetect = true;
    androidConfig.customRules.push_back("rule1");

    task.sceneConfigs[ForensicScenario::ANDROID] = androidConfig;

    EXPECT_EQ(task.sceneConfigs.size(), 1);
    EXPECT_TRUE(task.sceneConfigs[ForensicScenario::ANDROID].enabled);
    EXPECT_EQ(task.sceneConfigs[ForensicScenario::ANDROID].priorityThreshold, 75);
    EXPECT_TRUE(task.sceneConfigs[ForensicScenario::ANDROID].autoDetect);
    EXPECT_EQ(task.sceneConfigs[ForensicScenario::ANDROID].customRules.size(), 1);
    EXPECT_EQ(task.sceneConfigs[ForensicScenario::ANDROID].customRules[0], "rule1");
}

TEST(SceneConfigTest, CopyPreservesSceneConfigs) {
    AnalysisTask original;
    original.id = "copy-scene-test";
    original.scenarios = {ForensicScenario::ANDROID, ForensicScenario::WINDOWS};

    AnalysisTask::SceneConfig androidConfig;
    androidConfig.enabled = true;
    androidConfig.priorityThreshold = 80;
    original.sceneConfigs[ForensicScenario::ANDROID] = androidConfig;

    AnalysisTask::SceneConfig windowsConfig;
    windowsConfig.enabled = true;
    windowsConfig.autoDetect = true;
    original.sceneConfigs[ForensicScenario::WINDOWS] = windowsConfig;

    AnalysisTask copy = original;
    EXPECT_EQ(copy.sceneConfigs.size(), 2);
    EXPECT_TRUE(copy.sceneConfigs[ForensicScenario::ANDROID].enabled);
    EXPECT_EQ(copy.sceneConfigs[ForensicScenario::ANDROID].priorityThreshold, 80);
    EXPECT_TRUE(copy.sceneConfigs[ForensicScenario::WINDOWS].autoDetect);
}

TEST(SceneConfigTest, MovePreservesSceneConfigs) {
    AnalysisTask original;
    original.id = "move-scene-test";
    original.scenarios = {ForensicScenario::LINUX};

    AnalysisTask::SceneConfig linuxConfig;
    linuxConfig.enabled = true;
    linuxConfig.priorityThreshold = 60;
    linuxConfig.customRules.push_back("ssh_rule");
    original.sceneConfigs[ForensicScenario::LINUX] = linuxConfig;

    AnalysisTask moved = std::move(original);
    EXPECT_EQ(moved.sceneConfigs.size(), 1);
    EXPECT_TRUE(moved.sceneConfigs[ForensicScenario::LINUX].enabled);
    EXPECT_EQ(moved.sceneConfigs[ForensicScenario::LINUX].priorityThreshold, 60);
    EXPECT_EQ(moved.sceneConfigs[ForensicScenario::LINUX].customRules[0], "ssh_rule");
}

TEST(AnalysisTaskTest, NoScenariosNoAndroidAnalyze) {
    AnalysisTask task;
    task.id = "no-scenarios";
    task.scenarios = {};

    EXPECT_FALSE(task.get_android_analyze());
}

TEST(AnalysisTaskTest, MultipleScenariosIncludesAndroid) {
    AnalysisTask task;
    task.id = "multi";
    task.scenarios = {ForensicScenario::LINUX, ForensicScenario::ANDROID, ForensicScenario::WINDOWS};

    EXPECT_TRUE(task.get_android_analyze());
}

TEST(AnalysisTaskTest, SerializationPersistsSafeDecryptionConfigurationOnly) {
    AnalysisTask task;
    task.id = "decrypt-serialize";
    task.enable_decryption = true;
    task.key_file_dir = "/evidence/keys";
    task.decrypt_password = "never-persist-this";

    nlohmann::json j;
    to_json(j, task);

    EXPECT_TRUE(j.at("enable_decryption").get<bool>());
    EXPECT_EQ(j.at("key_file_dir").get<std::string>(), "/evidence/keys");
    EXPECT_FALSE(j.contains("decrypt_password"));
}

TEST(AnalysisTaskTest, DeserializationRestoresSafeDecryptionConfigurationAndClearsPassword) {
    AnalysisTask source;
    source.id = "decrypt-round-trip";
    source.image_path = "/test/image.dd";
    source.status = TaskStatus::PENDING;
    source.priority = TaskPriority::NORMAL;
    source.progress = {TaskPhase::INITIALIZING, 0, 0, "", {}, {}};
    source.enable_decryption = true;
    source.key_file_dir = "/evidence/keys";
    source.decrypt_password = "runtime-secret";

    nlohmann::json j;
    to_json(j, source);
    j["decrypt_password"] = "legacy-persisted-secret";

    AnalysisTask restored;
    restored.decrypt_password = "stale-secret";
    from_json(j, restored);

    EXPECT_TRUE(restored.enable_decryption);
    EXPECT_EQ(restored.key_file_dir, "/evidence/keys");
    EXPECT_TRUE(restored.decrypt_password.empty());
}

TEST(AnalysisTaskTest, CopyPreservesDecryptionConfiguration) {
    AnalysisTask original;
    original.enable_decryption = true;
    original.key_file_dir = "/copy/keys";
    original.decrypt_password = "copy-secret";

    AnalysisTask constructed(original);
    EXPECT_TRUE(constructed.enable_decryption);
    EXPECT_EQ(constructed.key_file_dir, "/copy/keys");
    EXPECT_EQ(constructed.decrypt_password, "copy-secret");

    AnalysisTask assigned;
    assigned = original;
    EXPECT_TRUE(assigned.enable_decryption);
    EXPECT_EQ(assigned.key_file_dir, "/copy/keys");
    EXPECT_EQ(assigned.decrypt_password, "copy-secret");
}

TEST(AnalysisTaskTest, MovePreservesDecryptionConfiguration) {
    AnalysisTask original;
    original.enable_decryption = true;
    original.key_file_dir = "/move/keys";
    original.decrypt_password = "move-secret";

    AnalysisTask constructed(std::move(original));
    EXPECT_TRUE(constructed.enable_decryption);
    EXPECT_EQ(constructed.key_file_dir, "/move/keys");
    EXPECT_EQ(constructed.decrypt_password, "move-secret");

    AnalysisTask assignedSource;
    assignedSource.enable_decryption = true;
    assignedSource.key_file_dir = "/assigned/keys";
    assignedSource.decrypt_password = "assigned-secret";
    AnalysisTask assigned;
    assigned = std::move(assignedSource);

    EXPECT_TRUE(assigned.enable_decryption);
    EXPECT_EQ(assigned.key_file_dir, "/assigned/keys");
    EXPECT_EQ(assigned.decrypt_password, "assigned-secret");
}

} // namespace
} // namespace forensics

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
