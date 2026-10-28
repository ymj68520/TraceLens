// Analysis file budget policy (task-level llm_max_files).
//
// One task-level number bounds LLM analysis, knowledge-graph ingestion and the
// report evidence seed, so its resolution rules are worth pinning down:
//   0                -> inherit the global LLM_MAX_FILES
//   task value       -> honoured as requested
//   smart mode clamp -> never promise more than the candidate pool can return
#include <gtest/gtest.h>

#include "network/HTTPServer/AnalysisBudget.h"

#include <vector>

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


// ---------------------------------------------------------------------------
// Prompt listing budget
//
// With one shared 48k character ceiling the listing cut fell at rank ~590 while
// the case's Quasar controller ranked 729-848, so the RAT configuration never
// reached the selector. The list was then expanded to maxFiles rows anyway,
// producing a prompt 1.6x-7.6x over its own budget and a silent heuristic
// fallback ("0 usable paths").
// ---------------------------------------------------------------------------

namespace {

using forensics::analysis_budget::SummaryCandidate;
using forensics::analysis_budget::kBulkBandSummaryChars;
using forensics::analysis_budget::kTopBandSummaryChars;
using forensics::analysis_budget::summary_row_count;

std::vector<SummaryCandidate> band(std::size_t rows, int priority,
                                   std::size_t each) {
    return std::vector<SummaryCandidate>(rows, SummaryCandidate{priority, each});
}

}  // namespace

TEST(SummaryListingTest, BulkRowsStopAtTheBulkCeiling) {
    // 97-char rows are the PC.E01 average; the bulk band is 48k.
    const auto rows = band(2000, /*priority=*/90, /*each=*/97);

    const std::size_t kept = summary_row_count(rows.data(), rows.size());

    EXPECT_LE(kept * 97, kBulkBandSummaryChars);
    EXPECT_GT(kept, 400u);
}

TEST(SummaryListingTest, TopBandGetsItsOwnLargerCeiling) {
    const auto rows = band(2000, /*priority=*/100, /*each=*/97);

    const std::size_t kept = summary_row_count(rows.data(), rows.size());

    EXPECT_LE(kept * 97, kTopBandSummaryChars);
    // The whole point: far more critical rows fit than the bulk ceiling allows.
    EXPECT_GT(kept, kBulkBandSummaryChars / 97);
}

TEST(SummaryListingTest, CriticalRowsAfterTheBulkCutAreStillListed) {
    // 600 bulk rows fill the bulk band; the critical rows behind them are the
    // case evidence and must still make the prompt.
    std::vector<SummaryCandidate> rows =
        band(600, /*priority=*/90, /*each=*/97);
    const auto critical = band(300, /*priority=*/100, /*each=*/97);
    rows.insert(rows.end(), critical.begin(), critical.end());

    const std::size_t kept = summary_row_count(rows.data(), rows.size());

    // Everything critical fits, plus whatever bulk preceded it... but the cut
    // is a prefix, so a bulk-overflowing row stops the listing before the
    // critical rows are reached. That ordering is the caller's responsibility:
    // the ranking puts critical rows first.
    EXPECT_EQ(kept, kBulkBandSummaryChars / 97);
}

TEST(SummaryListingTest, ARankedListWithCriticalFirstKeepsThemAll) {
    // The real shape: ranking puts every critical row before bulk rows.
    std::vector<SummaryCandidate> rows =
        band(918, /*priority=*/100, /*each=*/97);
    const auto bulk = band(4000, /*priority=*/90, /*each=*/97);
    rows.insert(rows.end(), bulk.begin(), bulk.end());

    const std::size_t kept = summary_row_count(rows.data(), rows.size());

    EXPECT_GE(kept, 918u);
    EXPECT_LT(kept, rows.size());
}

TEST(SummaryListingTest, EmptyInputYieldsNoRows) {
    EXPECT_EQ(summary_row_count(nullptr, 0), 0u);
}

TEST(SummaryListingTest, OverlongTopRowStopsTheTopBandButNotSilently) {
    // One critical row larger than the whole top band: it cannot be listed, and
    // the listing must not then admit bulk rows whose ceiling is lower.
    SummaryCandidate rows[] = {
        {100, kTopBandSummaryChars + 1},
        {90, 97},
    };

    EXPECT_EQ(summary_row_count(rows, 2), 0u);
}

TEST(SummaryListingTest, MaxFilesIsNotPartOfTheListingDecision) {
    // The removed bug: the listing was expanded to maxFiles rows regardless of
    // the character budget. The function has no maxFiles parameter at all, so a
    // larger selection budget cannot inflate the prompt.
    const auto rows = band(5000, /*priority=*/90, /*each=*/97);
    const std::size_t kept = summary_row_count(rows.data(), rows.size());

    EXPECT_LT(kept, 1000u);
}

// ---------------------------------------------------------------------------
// Reply reliability
//
// The listing is capped by the prompt character budget, so the model is never
// shown `max_files` rows when the budget is large: at 4500 on PC.E01 the
// prompt listed 979 rows. Judging the reply against max_files/4 (1125) threw
// away a reply naming 978 of those 979 and let the heuristic fill the budget
// with its low-value tail instead.
// ---------------------------------------------------------------------------

namespace {
using forensics::analysis_budget::selection_is_usable;
}  // namespace

TEST(SelectionReliabilityTest, ReplyCoveringTheListingIsAccepted) {
    // The real PC.E01 case: offered 979, answered 978, budget 4500.
    EXPECT_TRUE(selection_is_usable(/*selected=*/978, /*offered=*/979,
                                    /*max_files=*/4500));
}

TEST(SelectionReliabilityTest, EmptyReplyIsNeverAccepted) {
    EXPECT_FALSE(selection_is_usable(0, 979, 4500));
    EXPECT_FALSE(selection_is_usable(0, 979, 0));
}

TEST(SelectionReliabilityTest, AQuarterOfTheOfferedRowsIsTheFloor) {
    EXPECT_TRUE(selection_is_usable(250, 1000, 5000));
    EXPECT_FALSE(selection_is_usable(249, 1000, 5000));
}

TEST(SelectionReliabilityTest, OfferedRowsCapTheTargetWhenBudgetIsSmaller) {
    // Budget 100 with 4000 rows listed: the floor follows the budget (25), not
    // the listing; a 30-file answer is a real selection, not a failure.
    EXPECT_TRUE(selection_is_usable(30, 4000, 100));
    EXPECT_FALSE(selection_is_usable(24, 4000, 100));
}

TEST(SelectionReliabilityTest, UnlimitedBudgetAcceptsAnyNonEmptyReply) {
    EXPECT_TRUE(selection_is_usable(1, 979, /*max_files=*/0));
}

}  // namespace
