#pragma once

// Analysis file budget policy (task-level llm_max_files).
//
// One number bounds the whole per-file cost curve: the LLM analysis stage
// decides how many files get a description, knowledge-graph ingestion
// ingests exactly the described files (ANALYZED_ONLY), and the pipeline
// report seeds its evidence from the same described set. A per-stage cap
// would let the graph and the report disagree about which files are
// evidence, so the resolution lives here and every consumer calls it.
//
// Header-only and dependency-free so the fast unit-test target can cover it
// without linking the HTTP server.

#include <algorithm>
#include <string>

namespace forensics {
namespace analysis_budget {

// Accepted request range for the task-level budget. 0 is the explicit
// "inherit the global LLM_MAX_FILES" value; the upper bound matches the
// ConfigManager cap so a request that passes validation is still meaningful.
inline constexpr int kMinTaskBudget = 0;
inline constexpr int kMaxTaskBudget = 100000;

// Why a resolved budget differs from the value the caller asked for. The
// pipeline writes this to the task audit log so an operator can tell "the
// task ran 300 because it asked for 300" from "…because it was clamped".
enum class BudgetSource {
    Task,           // task-level value honoured as requested
    Global,         // task did not set one; inherited LLM_MAX_FILES
    ClampedToPool,  // task asked for more than smart selection can return
};

inline const char* budget_source_name(BudgetSource source) {
    switch (source) {
        case BudgetSource::Task: return "task";
        case BudgetSource::Global: return "LLM_MAX_FILES";
        case BudgetSource::ClampedToPool: return "task_clamped_to_candidate_pool";
    }
    return "unknown";
}

struct ResolvedBudget {
    // Effective file budget. 0 means unlimited (explicit opt-in only).
    int files = 0;
    int requested = 0;
    BudgetSource source = BudgetSource::Global;
    bool clamped = false;
};

// Resolve the budget a task should actually run with.
//
// @param task_budget        task.llm_max_files (0 = inherit)
// @param global_budget      ConfigManager::getLLMMaxFiles()
// @param candidate_budget   ConfigManager::getLLMSmartCandidateFiles()
// @param smart_mode         true for smart selection, false for full scan
//
// In smart mode the selection can never return more files than the candidate
// pool it scans, so an over-large request is clamped rather than silently
// under-delivering relative to what the task promised. Full mode scans the
// whole database and needs no clamp.
inline ResolvedBudget resolve(int task_budget,
                              int global_budget,
                              int candidate_budget,
                              bool smart_mode) {
    ResolvedBudget resolved;
    if (task_budget > 0) {
        resolved.files = task_budget;
        resolved.source = BudgetSource::Task;
    } else {
        resolved.files = global_budget;
        resolved.source = BudgetSource::Global;
    }
    resolved.requested = resolved.files;

    if (smart_mode && resolved.files > 0 && candidate_budget > 0 &&
        resolved.files > candidate_budget) {
        resolved.files = candidate_budget;
        resolved.source = BudgetSource::ClampedToPool;
        resolved.clamped = true;
    }
    return resolved;
}

// Human-readable audit detail for the resolved budget.
inline std::string describe(const ResolvedBudget& resolved, bool smart_mode) {
    std::string text = "LLM file budget: " +
        (resolved.files == 0 ? std::string("unlimited")
                            : std::to_string(resolved.files)) +
        " source=" + budget_source_name(resolved.source) +
        ", mode=" + (smart_mode ? "smart" : "full");
    if (resolved.clamped) {
        text += " (requested " + std::to_string(resolved.requested) +
                ", clamped to the smart-selection candidate pool)";
    }
    return text;
}

}  // namespace analysis_budget
}  // namespace forensics
