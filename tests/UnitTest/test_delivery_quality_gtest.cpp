#include <gtest/gtest.h>
#include "network/HTTPServer/TaskDeliveryState.h"
#include "core/Selection/SelectionQuality.h"

TEST(DeliveryQuality, ActiveAndRestartedTasksHaveNoCompletionTimestamp) {
    AnalysisTask task;
    task.created_time=std::chrono::system_clock::time_point(std::chrono::seconds(100));
    task.completed_time=std::chrono::system_clock::time_point(std::chrono::seconds(200));
    for(auto status:{TaskStatus::PENDING,TaskStatus::RUNNING,TaskStatus::PAUSED,TaskStatus::INTERRUPTED}) {
        task.status=status;EXPECT_FALSE(forensics::completed_timestamp(task));
    }
    task.status=TaskStatus::COMPLETED;
    EXPECT_EQ(forensics::completed_timestamp(task),200);
    EXPECT_EQ(forensics::completed_timestamp(task,true),200000);
    task.interrupted_by_restart=true;EXPECT_FALSE(forensics::completed_timestamp(task));
    task.interrupted_by_restart=false;task.completed_time=task.created_time;
    EXPECT_FALSE(forensics::completed_timestamp(task));
}
TEST(DeliveryQuality, ValidZeroRecordsAreDistinctFromMetadataAndFailures) {
    using nlohmann::json;
    json candidates=json::array();
    for(const auto& state:{"ok","metadata_only","error","unsupported","unprobed"})
        candidates.push_back({{"probe_state",state},{"probe",{{"coverage",{{"parsed_record_count",0}}}}}});
    auto result=forensics::selection::deliveryQuality({{"candidates",candidates},{"counts",{{"selected",5}}},{"execution",{{"completed",2},{"failed",1}}}});
    EXPECT_EQ(result["counts"]["zero_records"],1);
    EXPECT_EQ(result["counts"]["metadata_only"],1);
    EXPECT_EQ(result["counts"]["parse_failed"],1);
    EXPECT_EQ(result["counts"]["model_failed"],1);
    EXPECT_EQ(result["counts"]["unprocessed"],2);
}
