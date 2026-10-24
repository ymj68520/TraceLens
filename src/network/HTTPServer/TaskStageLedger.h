#pragma once
#ifndef TASK_STAGE_LEDGER_H
#define TASK_STAGE_LEDGER_H

// Stage-level checkpoint ledger for resumable forensic tasks.
//
// The ledger lives in AnalysisTask::metadata under the "stage." prefix so it
// rides the existing tasks.json persistence (no schema change) and stays
// visible in the task JSON for traceability. Entries are written at stage
// *exit* and read at stage *entry*:
//
//   metadata["stage.IMAGE_ANALYSIS"]      = "done:<input-fingerprint>"
//   metadata["stage.LLM_ANALYSIS"]        = "partial:1234/5000:<fingerprint>"
//   metadata["stage.PLATFORM_ANALYSIS"]   = "done:windows,linux:<fingerprint>"
//
// The fingerprint is part of the value, not a separate key: a stage may only
// be skipped when both its ledger entry says done AND the inputs it derives
// from still hash to the same value. Upstream stages invalidate downstream
// claims by changing a fingerprint (e.g. re-running IMAGE_ANALYSIS rewrites
// raw.db, changing the raw fingerprint the later stages recorded).
//
// This module is deliberately header-only and dependency-free apart from
// <filesystem>/<string> so CLI and HTTP paths can both use it.

#include <filesystem>
#include <fstream>
#include <string>
#include <vector>

#include <openssl/sha.h>

namespace forensics {
namespace stage_ledger {

// Metadata key prefix. Kept short — every task persists it forever.
inline constexpr const char* kKeyPrefix = "stage.";

inline std::string key(const std::string& stage) {
    return std::string(kKeyPrefix) + stage;
}

/** Stable stage identifiers (the ledger's vocabulary). */
inline constexpr const char* kInitializing = "INITIALIZING";
inline constexpr const char* kImageAnalysis = "IMAGE_ANALYSIS";
inline constexpr const char* kFilter = "FILE_FILTER";
inline constexpr const char* kEventExtraction = "EVENT_EXTRACTION";
inline constexpr const char* kFileClassification = "FILE_CLASSIFICATION";
inline constexpr const char* kLlmAnalysis = "LLM_ANALYSIS";
inline constexpr const char* kPlatformAnalysis = "PLATFORM_ANALYSIS";
inline constexpr const char* kFileCarving = "FILE_CARVING";
inline constexpr const char* kFinalizing = "FINALIZING";

/**
 * @brief SHA-256 of a file's bytes, hex-encoded. Empty string when the file
 *        cannot be read (callers must treat empty as "fingerprint unknown",
 *        which never validates a skip).
 */
inline std::string fingerprintFile(const std::string& path) {
    std::error_code ec;
    if (!std::filesystem::exists(path, ec) || ec) return {};
    if (!std::filesystem::is_regular_file(path, ec) || ec) return {};

    std::ifstream in(path, std::ios::binary);
    if (!in.is_open()) return {};

    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    char buffer[64 * 1024];
    while (in.good()) {
        in.read(buffer, sizeof(buffer));
        const std::streamsize got = in.gcount();
        if (got > 0) {
            SHA256_Update(&ctx, buffer, static_cast<size_t>(got));
        }
    }
    if (in.bad()) return {};

    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256_Final(digest, &ctx);

    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(SHA256_DIGEST_LENGTH * 2);
    for (unsigned char byte : digest) {
        out.push_back(hex[byte >> 4]);
        out.push_back(hex[byte & 0x0F]);
    }
    return out;
}

/**
 * @brief Composite fingerprint of several inputs (paths and/or config
 *        strings). Files contribute their content hash; strings contribute
 *        their bytes. Empty when any file is missing — a partially readable
 *        input set must never validate a skip.
 */
inline std::string fingerprintInputs(const std::vector<std::string>& paths,
                                     const std::vector<std::string>& values) {
    SHA256_CTX ctx;
    SHA256_Init(&ctx);

    for (const auto& p : paths) {
        const std::string h = fingerprintFile(p);
        if (h.empty()) return {};
        SHA256_Update(&ctx, h.data(), h.size());
        SHA256_Update(&ctx, "\x1f", 1);
    }
    for (const auto& v : values) {
        SHA256_Update(&ctx, v.data(), v.size());
        SHA256_Update(&ctx, "\x1e", 1);
    }

    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256_Final(digest, &ctx);
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(SHA256_DIGEST_LENGTH * 2);
    for (unsigned char byte : digest) {
        out.push_back(hex[byte >> 4]);
        out.push_back(hex[byte & 0x0F]);
    }
    return out;
}

/**
 * @brief Cheap change-detection fingerprint for a file: SHA-256 over
 *        "path|size|mtime". Empty when the file does not exist.
 *
 * This deliberately does NOT read the file. The ledger's job is deciding what
 * work to redo, so it needs a signal that changes when an artifact is
 * rebuilt, replaced, truncated or corrupted — not a cryptographic evidence
 * proof. Evidence integrity is established upstream by the preflight full
 * hash / source_verification pipeline, which hashes the source image once at
 * admission and rejects changed evidence (see admitAliyunImage and the
 * tar/seven-zip preflight). Hashing multi-GB databases at every stage boundary
 * would add minutes of pure I/O per stage for no additional decision value.
 */
inline std::string fingerprintStat(const std::string& path) {
    std::error_code ec;
    if (!std::filesystem::exists(path, ec) || ec) return {};

    const auto size = std::filesystem::file_size(path, ec);
    if (ec) return {};

    const auto mtime = std::filesystem::last_write_time(path, ec);
    if (ec) return {};
    const auto mtime_ticks = static_cast<long long>(mtime.time_since_epoch().count());

    const std::string material = path + "|" + std::to_string(size) + "|" +
                                 std::to_string(mtime_ticks);

    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const unsigned char*>(material.data()), material.size(), digest);
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(SHA256_DIGEST_LENGTH * 2);
    for (unsigned char byte : digest) {
        out.push_back(hex[byte >> 4]);
        out.push_back(hex[byte & 0x0F]);
    }
    return out;
}

/**
 * @brief Cheap change-detection fingerprint for a SQLite database.
 *
 * Covers the main file (size + mtime) and the `-wal` sidecar (size + mtime),
 * and nothing else.
 *
 * Why the WAL matters: the analyzers run with `PRAGMA journal_mode=WAL`, so a
 * write that has not been checkpointed yet leaves the main database's size and
 * mtime completely unchanged. Fingerprinting only the main file would report
 * "no change" for a database whose contents were just rewritten — the
 * false-negative that makes a resume reuse stale artifacts.
 *
 * Why `-shm` and `-journal` are excluded: `-shm` is transient shared memory
 * that SQLite creates on *open*, including read-only opens. Including it would
 * change the fingerprint merely because something read the database, turning
 * every resume into a false invalidation. `-journal` belongs to rollback mode
 * and is likewise created/removed around a transaction. Neither holds
 * committed data absent from main + wal.
 *
 * An empty `-wal` (created by a read-only open, zero bytes) is normalised to
 * "absent": it holds no data, and treating it as a change would make the
 * fingerprint depend on whether anyone happened to open the file.
 *
 * Like fingerprintStat this reads no file contents: the decision is "was this
 * artifact rebuilt", and evidence integrity is established upstream by the
 * preflight hash. Hashing multi-GB databases at every stage boundary would add
 * minutes of pure I/O per stage for no additional decision value.
 *
 * Empty when the main file does not exist (never validates a skip).
 */
inline std::string fingerprintSqlite(const std::string& path) {
    std::error_code ec;
    if (!std::filesystem::exists(path, ec) || ec) return {};

    std::string material;
    for (const char* suffix : {"", "-wal"}) {
        const std::string part = path + suffix;
        std::error_code partEc;
        if (!std::filesystem::exists(part, partEc) || partEc) {
            material += suffix;
            material += "|absent|";
            continue;
        }
        const auto size = std::filesystem::file_size(part, partEc);
        if (partEc) return {};
        // A zero-byte WAL is the artifact of a read-only open; it carries no
        // committed data, so it must not change the fingerprint.
        if (std::string(suffix) == "-wal" && size == 0) {
            material += suffix;
            material += "|absent|";
            continue;
        }
        const auto mtime = std::filesystem::last_write_time(part, partEc);
        if (partEc) return {};
        material += suffix;
        material += "|" + std::to_string(size) + "|" +
                    std::to_string(static_cast<long long>(mtime.time_since_epoch().count())) + "|";
    }

    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256(reinterpret_cast<const unsigned char*>(material.data()), material.size(), digest);
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(SHA256_DIGEST_LENGTH * 2);
    for (unsigned char byte : digest) {
        out.push_back(hex[byte >> 4]);
        out.push_back(hex[byte & 0x0F]);
    }
    return out;
}

/**
 * @brief SHA-256 over a list of strings (config values, stat fingerprints).
 *        Used to bind a stage's completion to the configuration it ran with.
 */
inline std::string combine(const std::vector<std::string>& parts) {
    SHA256_CTX ctx;
    SHA256_Init(&ctx);
    for (const auto& part : parts) {
        SHA256_Update(&ctx, part.data(), part.size());
        SHA256_Update(&ctx, "\x1e", 1);
    }
    unsigned char digest[SHA256_DIGEST_LENGTH];
    SHA256_Final(digest, &ctx);
    static const char* hex = "0123456789abcdef";
    std::string out;
    out.reserve(SHA256_DIGEST_LENGTH * 2);
    for (unsigned char byte : digest) {
        out.push_back(hex[byte >> 4]);
        out.push_back(hex[byte & 0x0F]);
    }
    return out;
}

/**
 * @brief Parse a ledger value into (state, detail).
 *
 * Ledger values are "<state>" or "<state>:<detail>". Detail may itself
 * contain colons (fingerprints never do, but progress counters and scenario
 * lists are joined with commas and are colon-free; we only split on the
 * first colon so a future detail format stays compatible).
 */
struct Entry {
    std::string state;   // "done" | "partial" | "failed" | ""
    std::string detail;  // fingerprint / "N/M" / scenario list; may be empty
};

inline Entry parse(const std::string& value) {
    Entry entry;
    const auto colon = value.find(':');
    if (colon == std::string::npos) {
        entry.state = value;
        return entry;
    }
    entry.state = value.substr(0, colon);
    entry.detail = value.substr(colon + 1);
    return entry;
}

inline std::string format(const std::string& state, const std::string& detail) {
    if (detail.empty()) return state;
    return state + ":" + detail;
}

inline std::string done(const std::string& detail) {
    return format("done", detail);
}

inline std::string partial(const std::string& detail) {
    return format("partial", detail);
}

} // namespace stage_ledger
} // namespace forensics

#endif // TASK_STAGE_LEDGER_H
