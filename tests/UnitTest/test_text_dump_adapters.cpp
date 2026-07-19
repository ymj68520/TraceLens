#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>
#include <system_error>
#include <type_traits>
#include "export/TextDumpAdapters.h"

namespace fs = std::filesystem;
using namespace forensics::textdump;

// Compile-time contract: the production adapters realize the exporter
// interfaces so the orchestrator can substitute them directly.
static_assert(std::is_base_of_v<ITextDumpFileSource, FileExtractorTextDumpSource>);
static_assert(std::is_base_of_v<ITextDumpConverter, MarkitdownTextDumpConverter>);

namespace {

void writeBytes(const fs::path& path, size_t size, char fill = 'm') {
    fs::create_directories(path.parent_path());
    std::ofstream out(path, std::ios::binary);
    std::string bytes(size, fill);
    out.write(bytes.data(), static_cast<std::streamsize>(bytes.size()));
}

class TextDumpAdapterTest : public ::testing::Test {
protected:
    void SetUp() override {
        root = fs::temp_directory_path() / "tracelens-text-dump-adapters";
        fs::remove_all(root);
        fs::create_directories(root);
    }
    void TearDown() override { fs::remove_all(root); }
    fs::path root;
};

// A proxy pointed at destination port 0: TCP destination port 0 is reserved
// and cannot identify a listening service, so the kernel rejects it up front
// and isAvailable() is false and convertOneToMarkdown reports ServiceError
// without a live python_service.
forensics::llm::MarkitdownProxy makeOfflineProxy() {
    return forensics::llm::MarkitdownProxy("http://127.0.0.1:0");
}

// isAvailable() maps to the proxy's service check, so it is false when no
// python_service is reachable.
TEST_F(TextDumpAdapterTest, IsAvailableMapsToProxyServiceCheck) {
    auto proxy = makeOfflineProxy();
    MarkitdownTextDumpConverter converter(proxy);
    EXPECT_FALSE(converter.isAvailable());
}

// force=false with a pre-existing valid Markdown at the expected path: the
// adapter must short-circuit to Reused (equal before/after) WITHOUT invoking
// the proxy, so the file survives untouched even though the service is down.
TEST_F(TextDumpAdapterTest, ReusesExistingMarkdownWhenNotForced) {
    const fs::path inputRoot = root / "originals";
    const fs::path outputRoot = root / "markdown";
    const fs::path inputFile = inputRoot / "a.txt";
    writeBytes(inputFile, 4, 'o');
    const fs::path expected = outputRoot / "a.txt.md";
    writeBytes(expected, 7, 'm');
    ASSERT_TRUE(fs::exists(expected));

    auto proxy = makeOfflineProxy();
    MarkitdownTextDumpConverter converter(proxy);

    const auto result = converter.convertOne(inputRoot, inputFile, outputRoot, false);

    EXPECT_EQ(result.status, MarkdownStatus::Reused);
    EXPECT_EQ(result.output_path, expected);
    EXPECT_EQ(result.previous_bytes, 7U);
    EXPECT_EQ(result.output_bytes, 7U);
    EXPECT_TRUE(result.error.empty());
    EXPECT_TRUE(fs::exists(expected));
    EXPECT_EQ(fs::file_size(expected), 7U);
}

// force=true means the original was freshly extracted, so any pre-existing
// Markdown is stale. When the proxy cannot produce a replacement (no service ->
// ServiceError), the adapter must delete the stale Markdown and report
// output_bytes=0 so a later run cannot reuse Markdown from the prior content.
TEST_F(TextDumpAdapterTest, ForceRemovesStaleMarkdownWhenServiceFails) {
    const fs::path inputRoot = root / "originals";
    const fs::path outputRoot = root / "markdown";
    const fs::path inputFile = inputRoot / "a.txt";
    writeBytes(inputFile, 4, 'o');
    const fs::path expected = outputRoot / "a.txt.md";
    writeBytes(expected, 9, 'm');
    ASSERT_TRUE(fs::exists(expected));

    auto proxy = makeOfflineProxy();
    MarkitdownTextDumpConverter converter(proxy);

    const auto result = converter.convertOne(inputRoot, inputFile, outputRoot, true);

    EXPECT_EQ(result.status, MarkdownStatus::ServiceError);
    EXPECT_EQ(result.previous_bytes, 9U);
    EXPECT_EQ(result.output_bytes, 0U);
    EXPECT_FALSE(result.error.empty());
    EXPECT_FALSE(fs::exists(expected))
        << "stale Markdown must be removed when force=true and the proxy fails";
}

// force=true with no pre-existing Markdown: nothing to remove, output_bytes=0,
// previous_bytes=0. Confirms the removal guard does not misfire on absence.
TEST_F(TextDumpAdapterTest, ForceWithNoExistingMarkdownReportsZero) {
    const fs::path inputRoot = root / "originals";
    const fs::path outputRoot = root / "markdown";
    const fs::path inputFile = inputRoot / "a.txt";
    writeBytes(inputFile, 4, 'o');
    const fs::path expected = outputRoot / "a.txt.md";
    ASSERT_FALSE(fs::exists(expected));

    auto proxy = makeOfflineProxy();
    MarkitdownTextDumpConverter converter(proxy);

    const auto result = converter.convertOne(inputRoot, inputFile, outputRoot, true);

    EXPECT_EQ(result.status, MarkdownStatus::ServiceError);
    EXPECT_EQ(result.previous_bytes, 0U);
    EXPECT_EQ(result.output_bytes, 0U);
    EXPECT_FALSE(fs::exists(expected));
}

// convertBatch maps every field of the proxy's BatchResult into the exporter's
// BatchConversionResult. With no service, ok stays false and the error is
// forwarded.
TEST_F(TextDumpAdapterTest, ConvertBatchMapsProxyBatchResult) {
    const fs::path inputRoot = root / "originals";
    const fs::path outputRoot = root / "markdown";
    fs::create_directories(inputRoot);
    fs::create_directories(outputRoot);

    auto proxy = makeOfflineProxy();
    MarkitdownTextDumpConverter converter(proxy);

    const auto result = converter.convertBatch(inputRoot, outputRoot);

    EXPECT_FALSE(result.ok);
    EXPECT_FALSE(result.error.empty());
}

} // namespace
