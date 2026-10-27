// Analysis file budget policy (task-level llm_max_files).
//
// One task-level number bounds LLM analysis, knowledge-graph ingestion and the
// report evidence seed, so its resolution rules are worth pinning down:
//   0                -> inherit the global LLM_MAX_FILES
//   task value       -> honoured as requested
//   smart mode clamp -> never promise more than the candidate pool can return
#include <gtest/gtest.h>

#include "network/HTTPServer/AnalysisBudget.h"

namespace {

using forensics::analysis_budget::BudgetSource;
using forensics::analysis_budget::ResolvedBudget;

TEST(AnalysisBudgetTest, ZeroInheritsGlobalBudget) {
    const ResolvedBudget resolved =
        forensics::analysis_budget::resolve(0, 500, 5000, /*smart_mode=*/true);

    EXPECT_EQ(resolved.files, 500);
    EXPECT_EQ(resolved.requested, 500);
    EXPECT_EQ(resolved.source, BudgetSource::Global);
    EXPECT_FALSE(resolved.clamped);
}

TEST(AnalysisBudgetTest, TaskBudgetOverridesGlobal) {
    const ResolvedBudget resolved =
        forensics::analysis_budget::resolve(120, 500, 5000, /*smart_mode=*/true);

    EXPECT_EQ(resolved.files, 120);
    EXPECT_EQ(resolved.source, BudgetSource::Task);
    EXPECT_FALSE(resolved.clamped);
}

TEST(AnalysisBudgetTest, TaskBudgetLargerThanGlobalIsStillHonoured) {
    // The global value is a default, not a ceiling: an explicit task-level
    // request may raise it (within the candidate pool).
    const ResolvedBudget resolved =
        forensics::analysis_budget::resolve(800, 500, 5000, /*smart_mode=*/true);

    EXPECT_EQ(resolved.files, 800);
    EXPECT_EQ(resolved.source, BudgetSource::Task);
}

TEST(AnalysisBudgetTest, SmartModeClampsToCandidatePool) {
    // Smart selection can only return files it scanned; promising more would
    // silently under-deliver.
    const ResolvedBudget resolved =
        forensics::analysis_budget::resolve(9000, 500, 5000, /*smart_mode=*/true);

    EXPECT_EQ(resolved.files, 5000);
    EXPECT_EQ(resolved.requested, 9000);
    EXPECT_EQ(resolved.source, BudgetSource::ClampedToPool);
    EXPECT_TRUE(resolved.clamped);
}

TEST(AnalysisBudgetTest, FullModeIsNotClampedByTheCandidatePool) {
    // Full mode scans the whole database, so the candidate pool does not apply.
    const ResolvedBudget resolved =
        forensics::analysis_budget::resolve(9000, 500, 5000, /*smart_mode=*/false);

    EXPECT_EQ(resolved.files, 9000);
    EXPECT_FALSE(resolved.clamped);
}

TEST(AnalysisBudgetTest, ExplicitUnlimitedIsNeverClamped) {
    // 0 from BOTH sources is the explicit unlimited opt-in; it must stay 0
    // rather than being turned into the candidate pool or a single file.
    const ResolvedBudget resolved =
        forensics::analysis_budget::resolve(0, 0, 5000, /*smart_mode=*/true);

    EXPECT_EQ(resolved.files, 0);
    EXPECT_FALSE(resolved.clamped);
    EXPECT_EQ(resolved.source, BudgetSource::Global);
}

TEST(AnalysisBudgetTest, EmptyCandidatePoolDoesNotClamp) {
    // CONFIG 0 disables the pool cap; clamping against it would look like
    // "budget 0" downstream.
    const ResolvedBudget resolved =
        forensics::analysis_budget::resolve(800, 500, 0, /*smart_mode=*/true);

    EXPECT_EQ(resolved.files, 800);
    EXPECT_FALSE(resolved.clamped);
}

TEST(AnalysisBudgetTest, DescribeNamesTheSourceAndTheClamp) {
    const auto honoured = forensics::analysis_budget::resolve(120, 500, 5000, true);
    const std::string honouredText =
        forensics::analysis_budget::describe(honoured, /*smart_mode=*/true);
    EXPECT_NE(honouredText.find("120"), std::string::npos);
    EXPECT_NE(honouredText.find("source=task"), std::string::npos);
    EXPECT_NE(honouredText.find("mode=smart"), std::string::npos);
    EXPECT_EQ(honouredText.find("clamped"), std::string::npos);

    const auto clamped = forensics::analysis_budget::resolve(9000, 500, 5000, true);
    const std::string clampedText =
        forensics::analysis_budget::describe(clamped, /*smart_mode=*/true);
    EXPECT_NE(clampedText.find("5000"), std::string::npos);
    EXPECT_NE(clampedText.find("requested 9000"), std::string::npos);
    EXPECT_NE(clampedText.find("clamped"), std::string::npos);
}

}  // namespace
