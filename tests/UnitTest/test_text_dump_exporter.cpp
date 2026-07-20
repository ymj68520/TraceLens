#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <map>
#include "export/TextDumpExporter.h"

namespace fs = std::filesystem;
using namespace forensics::textdump;

namespace {

void writeBytes(const fs::path& path, size_t size, char fill = 'x') {
    fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary);
    std::string bytes(size, fill);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

class FakeSource final : public ITextDumpFileSource {
public:
    bool available = true;
    std::vector<FileRecord> records;
    std::map<std::string, size_t> sizes;
    std::vector<std::string> started;
    int extract_all_calls = 0;

    bool initialize(std::string& error) override {
        if (!available) error = "source unavailable";
        return available;
    }
    bool list_fail = false;
    std::string list_error;
    std::vector<FileRecord> listRegularFilesOrdered(std::string& error) override {
        if (list_fail) {
            error = list_error;
            return {};
        }
        return records;
    }
    FileDeltaResult extractOne(const FileRecord& record,
                               const fs::path& root) override {
        started.push_back(record.path);
        const fs::path output = root / fs::path(record.path).relative_path();
        const uint64_t before = fs::exists(output) ? fs::file_size(output) : 0;
        writeBytes(output, sizes.at(record.path), 'o');
        return {OriginalStatus::Extracted, output, before,
                static_cast<uint64_t>(sizes.at(record.path)), ""};
    }
    int extractAll(const fs::path& root, std::string&) override {
        ++extract_all_calls;
        // Bulk extraction writes files directly without per-file delta tracking
        // (started stays empty), mirroring the production extractor's unlimited
        // path which the exporter must select when no size limit is set.
        for (const auto& rec : records) {
            const fs::path output = root / fs::path(rec.path).relative_path();
            writeBytes(output, sizes.at(rec.path), 'o');
        }
        return static_cast<int>(records.size());
    }
};

class FakeConverter final : public ITextDumpConverter {
public:
    bool available = true;
    std::map<std::string, size_t> sizes;
    std::map<std::string, MarkdownStatus> statuses;
    std::vector<std::string> started;
    std::vector<int> force_flags;
    int batch_calls = 0;

    bool isAvailable() override { return available; }
    MarkdownDeltaResult convertOne(const fs::path& inputRoot,
                                   const fs::path& inputFile,
                                   const fs::path& outputRoot,
                                   bool force) override {
        force_flags.push_back(force ? 1 : 0);
        const auto rel = fs::relative(inputFile, inputRoot);
        started.push_back("/" + rel.generic_string());
        const fs::path output = outputRoot / (rel.string() + ".md");
        const uint64_t before = fs::exists(output) ? fs::file_size(output) : 0;
        const auto status = statuses.count(started.back())
            ? statuses.at(started.back()) : MarkdownStatus::Converted;
        if (status == MarkdownStatus::Converted) {
            writeBytes(output, sizes.at(started.back()), 'm');
            return {status, output, before,
                    static_cast<uint64_t>(sizes.at(started.back())), ""};
        }
        return {status, output, before, before,
                status == MarkdownStatus::ServiceError ? "service lost" : "conversion failed"};
    }
    BatchConversionResult convertBatch(const fs::path&, const fs::path&) override {
        ++batch_calls;
        return {true, 0, 0, 0, 0, ""};
    }
};

class TextDumpExporterTest : public ::testing::Test {
protected:
    void SetUp() override {
        root = fs::temp_directory_path() / "tracelens-text-dump-exporter";
        fs::remove_all(root);
        fs::create_directories(root);
    }
    void TearDown() override { fs::remove_all(root); }
    FileRecord record(const std::string& path, int64_t inode) {
        FileRecord value{};
        value.path = path;
        value.name = fs::path(path).filename().string();
        value.inode = inode;
        value.partitionNum = 0;
        value.type = "REG";
        value.isDeleted = 0;
        value.isAllocated = 1;
        return value;
    }
    fs::path root;
};

TEST_F(TextDumpExporterTest, CompletesActiveFileThenStopsBeforeNextFile) {
    FakeSource source;
    source.records = {record("/a.txt", 1), record("/b.txt", 2)};
    source.sizes = {{"/a.txt", 12}, {"/b.txt", 3}};
    FakeConverter converter;
    converter.sizes = {{"/a.txt", 5}, {"/b.txt", 2}};
    TextDumpExporter exporter(source, converter);

    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{10}});

    EXPECT_EQ(source.started, std::vector<std::string>({"/a.txt"}));
    EXPECT_EQ(converter.started, std::vector<std::string>({"/a.txt"}));
    EXPECT_EQ(result.final_bytes, 17U);
    EXPECT_TRUE(result.truncated);
    EXPECT_EQ(result.stop_reason, StopReason::SizeLimitReached);
}

TEST_F(TextDumpExporterTest, CountsBothTreesAndDoesNotFollowSymlinks) {
    writeBytes(root / "originals/a", 3);
    writeBytes(root / "markdown/a.md", 5);
    writeBytes(root / "outside/large", 100);
    fs::create_directory_symlink(root / "outside", root / "originals/link");
    writeBytes(root / "originals/.tracelens-textdump-tmp-stale", 50);
    std::string error;
    const auto usage = TextDumpExporter::calculateUsage(
        root / "originals", root / "markdown", error);
    ASSERT_TRUE(usage.has_value()) << error;
    EXPECT_EQ(*usage, 8U);
    EXPECT_FALSE(fs::exists(root / "originals/.tracelens-textdump-tmp-stale"));
}

TEST_F(TextDumpExporterTest, DoesNoWorkWhenExistingUsageMeetsLimit) {
    writeBytes(root / "originals/existing", 10);
    FakeSource source;
    source.records = {record("/a.txt", 1)};
    FakeConverter converter;
    TextDumpExporter exporter(source, converter);
    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{10}});
    EXPECT_TRUE(source.started.empty());
    EXPECT_EQ(result.stop_reason, StopReason::SizeLimitReached);
}

TEST_F(TextDumpExporterTest, ContinuesAfterPerFileConversionFailure) {
    FakeSource source;
    source.records = {record("/a.txt", 1), record("/b.txt", 2)};
    source.sizes = {{"/a.txt", 1}, {"/b.txt", 1}};
    FakeConverter converter;
    converter.sizes = {{"/b.txt", 1}};
    converter.statuses["/a.txt"] = MarkdownStatus::Failed;
    TextDumpExporter exporter(source, converter);
    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{100}});
    EXPECT_EQ(source.started.size(), 2U);
    EXPECT_EQ(result.markdown_failed, 1U);
    EXPECT_EQ(result.markdown_converted, 1U);
}

TEST_F(TextDumpExporterTest, StopsAfterServiceFailure) {
    FakeSource source;
    source.records = {record("/a.txt", 1), record("/b.txt", 2)};
    source.sizes = {{"/a.txt", 1}, {"/b.txt", 1}};
    FakeConverter converter;
    converter.statuses["/a.txt"] = MarkdownStatus::ServiceError;
    TextDumpExporter exporter(source, converter);
    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{100}});
    EXPECT_EQ(source.started, std::vector<std::string>({"/a.txt"}));
    EXPECT_EQ(result.stop_reason, StopReason::ServiceUnavailable);
}

// Resume scenario: source reports Reused and converter reports Reused with
// equal before/after sizes, so usage must not change. The first record is
// already accounted for in initial_bytes; a larger limit permits the next
// candidate to be processed.
class ResumeFakeSource final : public ITextDumpFileSource {
public:
    std::vector<FileRecord> records;
    std::vector<std::string> started;

    bool initialize(std::string&) override { return true; }
    std::vector<FileRecord> listRegularFilesOrdered(std::string&) override {
        return records;
    }
    FileDeltaResult extractOne(const FileRecord& record,
                               const fs::path& root) override {
        started.push_back(record.path);
        const fs::path output = root / fs::path(record.path).relative_path();
        const uint64_t before = fs::exists(output) ? fs::file_size(output) : 0;
        return {OriginalStatus::Reused, output, before, before, ""};
    }
    int extractAll(const fs::path&, std::string&) override {
        return static_cast<int>(records.size());
    }
};

class ResumeFakeConverter final : public ITextDumpConverter {
public:
    bool available = true;
    std::vector<std::string> started;
    std::vector<int> force_flags;

    bool isAvailable() override { return available; }
    MarkdownDeltaResult convertOne(const fs::path& inputRoot,
                                   const fs::path& inputFile,
                                   const fs::path& outputRoot,
                                   bool force) override {
        force_flags.push_back(force ? 1 : 0);
        const auto rel = fs::relative(inputFile, inputRoot);
        started.push_back("/" + rel.generic_string());
        const fs::path output = outputRoot / (rel.string() + ".md");
        const uint64_t before = fs::exists(output) ? fs::file_size(output) : 0;
        return {MarkdownStatus::Reused, output, before, before, ""};
    }
    BatchConversionResult convertBatch(const fs::path&, const fs::path&) override {
        return {true, 0, 0, 0, 0, ""};
    }
};

TEST_F(TextDumpExporterTest, ResumeReusedFilesDoNotDoubleCountAndPermitNext) {
    // Pre-existing original + markdown that should both be reused as-is.
    writeBytes(root / "originals/a.txt", 4);
    writeBytes(root / "markdown/a.txt.md", 6);
    writeBytes(root / "originals/b.txt", 8);
    writeBytes(root / "markdown/b.txt.md", 2);

    ResumeFakeSource source;
    source.records = {record("/a.txt", 1), record("/b.txt", 2)};
    ResumeFakeConverter converter;
    TextDumpExporter exporter(source, converter);

    // Limit exactly equals current usage (10): next candidate would push over.
    // Both candidates are Reused with identical before/after, so usage stays
    // at 10 and neither is truncated.  Use a larger limit so processing is
    // allowed; this proves no double-counting.
    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{100}});

    EXPECT_EQ(source.started.size(), 2U);
    EXPECT_EQ(converter.started.size(), 2U);
    EXPECT_EQ(result.originals_reused, 2U);
    EXPECT_EQ(result.markdown_reused, 2U);
    EXPECT_EQ(result.initial_bytes, 20U);
    EXPECT_EQ(result.final_bytes, 20U);
    EXPECT_FALSE(result.truncated);
    EXPECT_EQ(result.stop_reason, StopReason::Completed);
}

// Resume with a tight limit: existing usage already at the limit must skip
// processing even though every record would otherwise be a no-op Reused.
TEST_F(TextDumpExporterTest, ResumeAtLimitStopsBeforeAnyCandidate) {
    writeBytes(root / "originals/a.txt", 4);
    writeBytes(root / "markdown/a.txt.md", 6);

    ResumeFakeSource source;
    source.records = {record("/a.txt", 1)};
    ResumeFakeConverter converter;
    TextDumpExporter exporter(source, converter);

    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{10}});

    EXPECT_TRUE(source.started.empty());
    EXPECT_EQ(result.initial_bytes, 10U);
    EXPECT_EQ(result.final_bytes, 10U);
    EXPECT_EQ(result.stop_reason, StopReason::SizeLimitReached);
    EXPECT_TRUE(result.truncated);
}

// A listing failure in the size-limited path must be surfaced as OutputError,
// not silently completed with zero candidates. Accounting figures already
// placed on result must be preserved, and no per-file extraction should run.
TEST_F(TextDumpExporterTest, ListingFailureIsSurfacedNotSilentlyCompleted) {
    // Pre-existing content so accounting produces a non-zero initial_bytes
    // before the listing call.
    writeBytes(root / "originals/preexisting", 2);
    writeBytes(root / "markdown/preexisting.md", 3);

    FakeSource source;
    source.records = {record("/a.txt", 1)};
    source.sizes = {{"/a.txt", 4}};
    source.list_fail = true;
    source.list_error = "listing failed: DB error";
    FakeConverter converter;
    converter.sizes = {{"/a.txt", 5}};
    TextDumpExporter exporter(source, converter);

    const auto result = exporter.run({
        root / "originals", root / "markdown", uint64_t{100}});

    EXPECT_EQ(result.stop_reason, StopReason::OutputError);
    EXPECT_EQ(result.message, "listing failed: DB error");
    EXPECT_EQ(result.initial_bytes, 5U);
    EXPECT_EQ(result.final_bytes, 5U);
    EXPECT_TRUE(source.started.empty());
}

TEST_F(TextDumpExporterTest, FormatBytesUsesLargestBinaryUnit) {
    EXPECT_EQ(TextDumpExporter::formatBytes(0), "0 B");
    EXPECT_EQ(TextDumpExporter::formatBytes(1023), "1023 B");
    EXPECT_EQ(TextDumpExporter::formatBytes(1024), "1.0 KiB");
    EXPECT_EQ(TextDumpExporter::formatBytes(1536), "1.5 KiB");
    EXPECT_EQ(TextDumpExporter::formatBytes(1024ULL * 1024ULL), "1.0 MiB");
    EXPECT_EQ(TextDumpExporter::formatBytes(1024ULL * 1024ULL * 1024ULL), "1.0 GiB");
    EXPECT_EQ(TextDumpExporter::formatBytes(1024ULL * 1024ULL * 1024ULL * 1024ULL), "1.0 TiB");
}

// Unlimited mode (max_bytes == nullopt) must take the bulk path: initialize ->
// extractAll -> convertBatch. It must NOT enumerate records or do per-file
// extraction/conversion, so no per-file work is recorded.
TEST_F(TextDumpExporterTest, UnlimitedModeUsesBatchAndDoesNotEnumerate) {
    FakeSource source;
    source.records = {record("/a.txt", 1), record("/b.txt", 2)};
    source.sizes = {{"/a.txt", 4}, {"/b.txt", 8}};
    FakeConverter converter;
    TextDumpExporter exporter(source, converter);

    const auto result = exporter.run({
        root / "originals", root / "markdown", std::nullopt});

    EXPECT_EQ(source.extract_all_calls, 1);
    EXPECT_EQ(converter.batch_calls, 1);
    EXPECT_TRUE(source.started.empty());    // no per-file extraction
    EXPECT_TRUE(converter.started.empty()); // no per-file conversion
    EXPECT_EQ(result.stop_reason, StopReason::Completed);
}

// The exporter passes force=true only when the original was freshly Extracted,
// and force=false when it was Reused. This governs whether the converter may
// short-circuit on existing Markdown.
TEST_F(TextDumpExporterTest, ForceFlagReflectsOriginalStatus) {
    // Extracted original -> converter invoked with force=true.
    {
        FakeSource source;
        source.records = {record("/a.txt", 1)};
        source.sizes = {{"/a.txt", 4}};
        FakeConverter converter;
        converter.sizes = {{"/a.txt", 5}};
        TextDumpExporter exporter(source, converter);
        exporter.run({root / "originals", root / "markdown", uint64_t{100}});
        ASSERT_EQ(converter.force_flags.size(), 1U);
        EXPECT_EQ(converter.force_flags[0], 1);
    }
    // Reused original -> converter invoked with force=false.
    {
        ResumeFakeSource source;
        source.records = {record("/a.txt", 1)};
        ResumeFakeConverter converter;
        TextDumpExporter exporter(source, converter);
        exporter.run({root / "originals", root / "markdown", uint64_t{100}});
        ASSERT_EQ(converter.force_flags.size(), 1U);
        EXPECT_EQ(converter.force_flags[0], 0);
    }
}

} // namespace
