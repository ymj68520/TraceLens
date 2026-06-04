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

} // namespace
} // namespace forensics

int main(int argc, char** argv) {
    ::testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
