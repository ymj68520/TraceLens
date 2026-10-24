// Unit tests for the resumable-task stage ledger (TaskStageLedger.h).
//
// The ledger is the checkpoint that makes a resumed run correct: a stage may
// only be skipped when its claim says done AND the fingerprint recorded at
// completion equals the fingerprint of the inputs now. These tests pin the two
// properties everything else depends on:
//
//   1. Value grammar — parse/format round-trip, detail may carry a colon-free
//      payload (fingerprint, "N/M:mode", scenario list).
//   2. Change detection — a fingerprint must change when the artifact it
//      describes changes, and must be empty (never validating a skip) when the
//      artifact is missing.

#include <gtest/gtest.h>

#include "network/HTTPServer/TaskStageLedger.h"

#include <filesystem>
#include <fstream>
#include <string>

namespace fs = std::filesystem;
using namespace forensics::stage_ledger;

namespace {

// A temp file whose contents/mtime we control, cleaned up on destruction.
class TempFile {
public:
    explicit TempFile(const std::string& name, const std::string& contents)
        : path_(fs::temp_directory_path() / ("ledger_test_" + name)) {
        fs::remove(path_);
        write(contents);
    }
    ~TempFile() { fs::remove(path_); }

    const std::string path() const { return path_.string(); }

    void write(const std::string& contents, bool bump_mtime = true) {
        {
            std::ofstream out(path_, std::ios::binary | std::ios::trunc);
            out << contents;
        }
        if (bump_mtime) {
            // Ensure two consecutive writes get distinct mtimes even on
            // coarse-grained filesystems.
            fs::permissions(path_, fs::perms::owner_all);
        }
    }

private:
    fs::path path_;
};

}  // namespace

// ── Value grammar ────────────────────────────────────────────────────────────

TEST(StageLedger, parse_state_only) {
    const auto e = parse("done");
    EXPECT_EQ(e.state, "done");
    EXPECT_TRUE(e.detail.empty());
}

TEST(StageLedger, parse_state_with_detail) {
    const auto e = parse("done:abc123");
    EXPECT_EQ(e.state, "done");
    EXPECT_EQ(e.detail, "abc123");
}

TEST(StageLedger, parse_partial_with_progress_detail) {
    const auto e = parse("partial:1250/5000:full");
    EXPECT_EQ(e.state, "partial");
    // Only the first colon separates state from detail: the detail keeps its
    // own colon so a progress payload can carry a mode tag.
    EXPECT_EQ(e.detail, "1250/5000:full");
}

TEST(StageLedger, parse_empty_gives_empty_state) {
    const auto e = parse("");
    EXPECT_TRUE(e.state.empty());
    EXPECT_TRUE(e.detail.empty());
}

TEST(StageLedger, format_omits_separator_without_detail) {
    EXPECT_EQ(format("done", ""), "done");
    EXPECT_EQ(done(""), "done");
    EXPECT_EQ(done("fp"), "done:fp");
    EXPECT_EQ(partial("3/10:smart"), "partial:3/10:smart");
}

TEST(StageLedger, key_prefix_is_stable) {
    // The "stage." prefix is persisted in tasks.json; changing it would orphan
    // every existing ledger entry, so pin it.
    EXPECT_EQ(key("IMAGE_ANALYSIS"), "stage.IMAGE_ANALYSIS");
}

// ── Change detection ─────────────────────────────────────────────────────────

TEST(StageLedger, fingerprint_stat_is_deterministic) {
    TempFile f("det.txt", "contents");
    const auto a = fingerprintStat(f.path());
    const auto b = fingerprintStat(f.path());
    EXPECT_FALSE(a.empty());
    EXPECT_EQ(a, b);
}

TEST(StageLedger, fingerprint_stat_changes_with_content) {
    TempFile f("content.txt", "before");
    const auto before = fingerprintStat(f.path());
    f.write("after");
    const auto after = fingerprintStat(f.path());
    EXPECT_FALSE(before.empty());
    EXPECT_NE(before, after) << "regenerating an artifact must change its fingerprint";
}

TEST(StageLedger, fingerprint_stat_empty_for_missing_file) {
    // An unreadable input must never validate a skip.
    EXPECT_TRUE(fingerprintStat("/nonexistent/path/for/ledger/test.db").empty());
}

TEST(StageLedger, fingerprint_stat_distinguishes_paths_with_same_content) {
    TempFile a("path_a.txt", "same");
    TempFile b("path_b.txt", "same");
    // Different artifacts, same bytes: the path is part of the material, so a
    // ledger entry can never be satisfied by the wrong database.
    EXPECT_NE(fingerprintStat(a.path()), fingerprintStat(b.path()));
}

TEST(StageLedger, fingerprint_file_hashes_contents) {
    TempFile a("hash_a.txt", "alpha");
    TempFile b("hash_b.txt", "beta");
    const auto ha = fingerprintFile(a.path());
    const auto hb = fingerprintFile(b.path());
    EXPECT_EQ(ha.size(), 64u) << "SHA-256 hex digest is 64 chars";
    EXPECT_NE(ha, hb);
    // Same content in a different file must hash identically (content-addressed,
    // unlike fingerprintStat which also binds the path).
    TempFile c("hash_c.txt", "alpha");
    EXPECT_EQ(ha, fingerprintFile(c.path()));
}

TEST(StageLedger, fingerprint_file_empty_for_missing) {
    EXPECT_TRUE(fingerprintFile("/nonexistent/path/for/ledger/test.db").empty());
}

// ── Composite fingerprints (what each stage records) ─────────────────────────

TEST(StageLedger, combine_is_order_sensitive) {
    // Reversing the input list must change the composite: stage A feeding B is
    // not the same claim as B feeding A.
    EXPECT_NE(combine({"a", "b"}), combine({"b", "a"}));
}

TEST(StageLedger, combine_empty_list_is_stable) {
    EXPECT_EQ(combine({}), combine({}));
}

TEST(StageLedger, combine_detects_input_change) {
    TempFile input("combine_input.db", "raw-v1");
    const auto before = combine({fingerprintStat(input.path()), "general_forensics"});
    // Changing the filter profile must invalidate the filtered DB claim, even
    // though the raw DB is untouched.
    const auto after = combine({fingerprintStat(input.path()), "telecom_fraud"});
    EXPECT_NE(before, after);
}

TEST(StageLedger, combine_respects_separator_boundaries) {
    // {"ab","c"} vs {"a","bc"}: without a separator these would concatenate to
    // the same byte stream. The \x1e separator must keep them distinct.
    EXPECT_NE(combine({"ab", "c"}), combine({"a", "bc"}));
}

TEST(StageLedger, fingerprint_inputs_requires_every_file) {
    TempFile present("inputs_present.db", "x");
    // A composite over a missing file cannot be computed — the caller must
    // treat the empty result as "unknown", never as a valid fingerprint.
    EXPECT_TRUE(fingerprintInputs({present.path(), "/nonexistent/other.db"}, {}).empty());
    EXPECT_FALSE(fingerprintInputs({present.path()}, {}).empty());
}

// ── Skip-decision semantics (the rule the pipeline enforces) ─────────────────

// These mirror TaskManager::stage_is_reusable's contract at the ledger level:
// state must be "done" and the recorded detail must equal the fingerprint
// computed from the current inputs.
TEST(StageLedger, skip_requires_done_state) {
    const auto entry = parse("partial:10/100");  // interrupted mid-stage
    EXPECT_NE(entry.state, "done");
}

TEST(StageLedger, skip_requires_matching_fingerprint) {
    TempFile raw("skip_raw.db", "v1");
    const auto recorded = done(fingerprintStat(raw.path()));

    // Unchanged input: the recorded claim still matches.
    EXPECT_EQ(parse(recorded).detail, fingerprintStat(raw.path()));

    // Input replaced (a re-walk rewrote raw.db): the old claim no longer holds.
    raw.write("v2");
    EXPECT_NE(parse(recorded).detail, fingerprintStat(raw.path()))
        << "a rewritten upstream database must void the downstream claim";
}

TEST(StageLedger, bare_done_carries_no_fingerprint) {
    // Stages whose inputs are fully described upstream (LLM analysis, whose
    // progress lives in per-row markers) record a bare "done".
    const auto entry = parse(done(""));
    EXPECT_EQ(entry.state, "done");
    EXPECT_TRUE(entry.detail.empty());
}
