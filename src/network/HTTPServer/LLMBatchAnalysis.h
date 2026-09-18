#pragma once
#ifndef LLM_BATCH_ANALYSIS_H
#define LLM_BATCH_ANALYSIS_H

// llm-throughput-hardening SPEC C: pack N artifact records into one LLM
// request. The E01 long tail is per-row calls (14-15 artifact types x up to
// LLM_MAX_ARTIFACTS rows each, one synchronous chat per row); batching divides
// the call count by the batch size.
//
// Failure ladder (SPEC C3) — never silently skip evidence:
//   1. whole-response parse failure -> one retry with a correction instruction
//   2. still unusable               -> split the chunk in half, recurse
//   3. chunk of one                 -> reported unresolved; the CALLER falls
//      back to its legacy per-item analysis so the floor equals today's
//      behaviour by construction.
//
// Header-only and free of the per-service nested types: operates on plain
// id/record strings so Linux/Windows/Android services share one implementation.

#include <map>
#include <string>
#include <vector>

#include <nlohmann/json.hpp>

#include "LLMIntegration/ModelRouter.h"

namespace forensics {
namespace llmbatch {

struct Item {
    std::string id;     // artifact id, as it must appear in the response
    std::string record; // JSON-formatted artifact payload
};

struct Outcome {
    // id -> object with "summary"/"description"/"keywords" fields
    std::map<std::string, nlohmann::json> results;
    std::vector<std::string> unresolved_ids;
};

inline std::vector<std::string> idsOf(const std::vector<Item>& items) {
    std::vector<std::string> ids;
    ids.reserve(items.size());
    for (const auto& item : items) ids.push_back(item.id);
    return ids;
}

inline std::string buildUserPrompt(const std::string& artifactLabel,
                                   const std::vector<Item>& items,
                                   const std::string& extraInstruction = "") {
    nlohmann::json arr = nlohmann::json::array();
    for (const auto& item : items) {
        nlohmann::json entry = nlohmann::json::object();
        entry["id"] = item.id;
        try {
            entry["record"] = nlohmann::json::parse(item.record);
        } catch (...) {
            entry["record"] = item.record; // raw string when data isn't JSON
        }
        arr.push_back(entry);
    }

    std::string prompt =
        "You are a digital forensics expert analyzing " +
        std::to_string(items.size()) + " " + artifactLabel +
        " records from a forensic disk image.\n\n"
        "For EACH record provide:\n"
        "1. summary: brief one-line description\n"
        "2. description: forensic significance and security implications\n"
        "3. keywords: 3-5 relevant keywords\n\n"
        "Respond with ONLY a JSON array, one object per record, in the form:\n"
        "[{\"id\": <same id as input>, \"summary\": \"...\", "
        "\"description\": \"...\", \"keywords\": [\"k1\", \"k2\"]}]\n"
        "Every input id must appear exactly once. No extra text.\n\n"
        "Records:\n" +
        arr.dump();
    if (!extraInstruction.empty()) {
        prompt += "\n\n" + extraInstruction;
    }
    return prompt;
}

// Parse a batch response; returns the resolved subset and lists every
// expected id that is missing, duplicated or malformed as unresolved.
inline Outcome parseResponse(const std::string& raw,
                             const std::vector<std::string>& expectedIds) {
    Outcome outcome;
    nlohmann::json parsed;
    try {
        parsed = nlohmann::json::parse(raw);
    } catch (...) {
        for (const auto& id : expectedIds) outcome.unresolved_ids.push_back(id);
        return outcome;
    }
    // Tolerate an object wrapping the array under "results"/"items".
    if (parsed.is_object()) {
        for (const char* key : {"results", "items", "records"}) {
            if (parsed.contains(key) && parsed[key].is_array()) {
                parsed = parsed[key];
                break;
            }
        }
    }
    if (!parsed.is_array()) {
        for (const auto& id : expectedIds) outcome.unresolved_ids.push_back(id);
        return outcome;
    }

    std::map<std::string, int> seen;
    for (const auto& entry : parsed) {
        if (!entry.is_object() || !entry.contains("id")) continue;
        std::string id = entry["id"].is_string() ? entry["id"].get<std::string>()
                                                 : entry["id"].dump();
        if (!entry.contains("summary") && !entry.contains("description")) continue;
        seen[id] += 1;
        if (seen[id] == 1) outcome.results[id] = entry;
    }
    for (const auto& id : expectedIds) {
        if (seen[id] != 1) outcome.unresolved_ids.push_back(id);
    }
    return outcome;
}

inline Outcome analyzeChunk(llm::ModelRouter& router,
                            const std::string& artifactLabel,
                            const std::vector<Item>& items,
                            int retries) {
    const std::string systemPrompt =
        "You are a digital forensics expert. Respond with valid JSON only — "
        "no markdown fences, no commentary.";

    Outcome outcome;
    std::string extra;
    for (int attempt = 0; attempt <= retries; ++attempt) {
        std::string prompt = buildUserPrompt(artifactLabel, items, extra);
        auto response = router.chat(prompt, systemPrompt);
        if (!response.success || response.content.empty()) {
            extra = "The previous attempt produced no usable output. "
                    "Respond ONLY with the JSON array.";
            continue;
        }
        outcome = parseResponse(response.content, idsOf(items));
        if (outcome.unresolved_ids.empty()) return outcome;
        extra = "Your previous response was not a valid JSON array covering "
                "every input id exactly once. Respond ONLY with the JSON array.";
    }
    return outcome;
}

// Chunk-local ladder entry: halves the chunk while it keeps failing totally
// and the chunk is larger than one item.
inline void analyzeWithLadder(llm::ModelRouter& router,
                              const std::string& artifactLabel,
                              const std::vector<Item>& items,
                              int retries,
                              Outcome& aggregated) {
    if (items.empty()) return;
    if (items.size() == 1) {
        aggregated.unresolved_ids.push_back(items[0].id);
        return;
    }
    auto outcome = analyzeChunk(router, artifactLabel, items, retries);
    for (const auto& [id, value] : outcome.results) {
        aggregated.results[id] = value;
    }
    if (outcome.unresolved_ids.empty()) return;

    // Split and retry the halves; unresolved singles land in unresolved_ids.
    std::size_t mid = items.size() / 2;
    std::vector<Item> left(items.begin(), items.begin() + mid);
    std::vector<Item> right(items.begin() + mid, items.end());
    analyzeWithLadder(router, artifactLabel, left, retries, aggregated);
    analyzeWithLadder(router, artifactLabel, right, retries, aggregated);
}

} // namespace llmbatch
} // namespace forensics

#endif // LLM_BATCH_ANALYSIS_H
