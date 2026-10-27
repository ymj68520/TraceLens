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
#include <cstddef>
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

// ---------------------------------------------------------------------------
// Prompt listing budget
//
// The smart selector shows the model an indexed list of candidate paths and
// asks it to pick the important ones. That list needs a size bound: an
// unbounded list overflows the context and the selection call fails outright.
// It needs TWO bounds, because the list is ordered by forensic priority and a
// single character budget therefore cuts by path length:
//
//   * top band — registry hives, event logs, prefetch, case-named directories
//     and user-tree executables. Few per image (918 of 122,592 selectable
//     files on PC.E01) and decisive. They get their own, larger ceiling.
//   * bulk band — everything else, under the original ceiling.
//
// With one shared 48k ceiling the cut landed at rank ~590, while the case's
// own Quasar controller ranked 729-848: the RAT configuration and payload
// never appeared in the prompt. The list was then silently expanded to
// `maxFiles` rows regardless (77,367 characters at LLM_MAX_FILES=1000), which
// is 1.6x the ceiling it was meant to respect — and 7.6x at a 5000 candidate
// budget, where the selector returned "0 usable paths" and the pipeline fell
// back to its heuristic without saying so.
// ---------------------------------------------------------------------------

// Lowest path priority that belongs to the top band. Matches the scoring bands
// in LLMAnalysisService::forensicPathPriority: 95 = user-tree executable,
// 92 = case-named directory, 100 = core forensic artefact.
inline constexpr int kCriticalSummaryPriority = 92;

inline constexpr std::size_t kTopBandSummaryChars = 160000;
inline constexpr std::size_t kBulkBandSummaryChars = 48000;

// One candidate as the listing sees it.
struct SummaryCandidate {
    int priority = 0;
    std::size_t rendered_chars = 0;  // path length + index prefix + newline
};

// How many leading candidates fit in the prompt listing.
//
// Input order must already be the forensic ranking (best first). The returned
// count is a prefix length: rows [0, count) go into the prompt.
//
// `max_files` is deliberately NOT a parameter. It caps how many files may be
// SELECTED, not how many may be OFFERED; conflating the two is what let a
// larger candidate budget inflate the prompt instead of widening the choice.
inline std::size_t summary_row_count(const SummaryCandidate* rows,
                                     std::size_t count) {
    std::size_t used_chars = 0;
    std::size_t used_rows = 0;
    bool top_band_done = false;
    for (std::size_t i = 0; i < count; ++i) {
        const bool top_band = rows[i].priority >= kCriticalSummaryPriority;
        // Once the top band stops fitting, every remaining row is bulk, and the
        // bulk ceiling is lower than the top one — nothing more can fit.
        if (!top_band && top_band_done) break;
        const std::size_t limit = top_band ? kTopBandSummaryChars
                                           : kBulkBandSummaryChars;
        const std::size_t next = used_chars + rows[i].rendered_chars;
        if (next > limit) {
            if (top_band) {
                top_band_done = true;
                continue;
            }
            break;
        }
        used_chars = next;
        ++used_rows;
    }
    return used_rows;
}

}  // namespace analysis_budget
}  // namespace forensics
