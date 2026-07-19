#include "TextDumpAdapters.h"

#include <system_error>
#include <utility>

namespace fs = std::filesystem;

namespace forensics {
namespace textdump {

// ---------------------------------------------------------------------------
// FileExtractorTextDumpSource
// ---------------------------------------------------------------------------

FileExtractorTextDumpSource::FileExtractorTextDumpSource(
        std::string imagePath, std::string databasePath)
    : extractor_(imagePath, databasePath) {}

bool FileExtractorTextDumpSource::initialize(std::string& error) {
    if (extractor_.initialize()) return true;
    error = "FileExtractor failed to initialize for text dump";
    return false;
}

std::vector<FileRecord>
FileExtractorTextDumpSource::listRegularFilesOrdered(std::string& error) {
    return extractor_.listRegularFilesOrdered(&error);
}

FileDeltaResult FileExtractorTextDumpSource::extractOne(
        const FileRecord& record, const fs::path& outputRoot) {
    const auto source = extractor_.extractRecordAtomically(record, outputRoot);
    // Task 4's AtomicExtractionStatus has exactly {Extracted, Reused, Failed}.
    // Unsafe paths surface as Failed from the real extractor, so the exporter's
    // OriginalStatus::UnsafePath value is never emitted here by design.
    OriginalStatus status = OriginalStatus::Failed;
    switch (source.status) {
        case FileExtractor::AtomicExtractionStatus::Extracted:
            status = OriginalStatus::Extracted;
            break;
        case FileExtractor::AtomicExtractionStatus::Reused:
            status = OriginalStatus::Reused;
            break;
        case FileExtractor::AtomicExtractionStatus::Failed:
            status = OriginalStatus::Failed;
            break;
    }
    return {status, source.output_path,
            static_cast<uint64_t>(source.previous_bytes),
            static_cast<uint64_t>(source.output_bytes),
            source.error};
}

int FileExtractorTextDumpSource::extractAll(const fs::path& outputRoot,
                                            std::string& error) {
    const int count = extractor_.extractAll(outputRoot.string(), false, false, nullptr);
    if (count < 0 && error.empty()) {
        error = "FileExtractor::extractAll failed for text dump";
    }
    return count;
}

// ---------------------------------------------------------------------------
// MarkitdownTextDumpConverter
// ---------------------------------------------------------------------------

MarkitdownTextDumpConverter::MarkitdownTextDumpConverter(
        forensics::llm::MarkitdownProxy& proxy)
    : proxy_(proxy) {}

bool MarkitdownTextDumpConverter::isAvailable() {
    return proxy_.isServiceAvailable();
}

MarkdownDeltaResult MarkitdownTextDumpConverter::convertOne(
        const fs::path& inputRoot,
        const fs::path& inputFile,
        const fs::path& outputRoot,
        bool force) {
    const fs::path relative = fs::relative(inputFile, inputRoot);
    const fs::path expected = outputRoot / (relative.string() + ".md");

    std::error_code statusEc;
    const auto linkStatus = fs::symlink_status(expected, statusEc);
    const bool existingRegular = !statusEc
        && fs::is_regular_file(linkStatus)
        && !fs::is_symlink(linkStatus);
    uint64_t previous = 0U;
    if (existingRegular) {
        std::error_code sizeEc;
        previous = static_cast<uint64_t>(fs::file_size(expected, sizeEc));
    }

    // Resume fast path: an existing valid Markdown is reused as-is when the
    // original was not freshly extracted, skipping the service entirely.
    if (!force && existingRegular) {
        return {MarkdownStatus::Reused, expected, previous, previous, ""};
    }

    const auto converted = proxy_.convertOneToMarkdown(
        inputRoot.string(), inputFile.string(), outputRoot.string());

    MarkdownStatus status = MarkdownStatus::Failed;
    switch (converted.status) {
        case forensics::llm::SingleConversionStatus::Converted:
            status = MarkdownStatus::Converted;
            break;
        case forensics::llm::SingleConversionStatus::Skipped:
            status = MarkdownStatus::Skipped;
            break;
        case forensics::llm::SingleConversionStatus::Failed:
            status = MarkdownStatus::Failed;
            break;
        case forensics::llm::SingleConversionStatus::ServiceError:
            status = MarkdownStatus::ServiceError;
            break;
    }

    if (status == MarkdownStatus::Converted) {
        return {status, expected, previous, converted.output_bytes,
                converted.error};
    }

    // The proxy did not replace the file. When force=true the original was
    // freshly extracted, so any prior Markdown is stale: remove it and report
    // output_bytes=0 so a later run cannot reuse mismatched Markdown.
    if (force && existingRegular) {
        std::error_code removeEc;
        fs::remove(expected, removeEc);
        return {status, expected, previous, 0U, converted.error};
    }

    return {status, expected, previous, previous, converted.error};
}

BatchConversionResult MarkitdownTextDumpConverter::convertBatch(
        const fs::path& inputRoot, const fs::path& outputRoot) {
    const auto batch = proxy_.batchConvertToMarkdown(
        inputRoot.string(), outputRoot.string());
    return {batch.ok, batch.total, batch.converted, batch.skipped,
            batch.failed, batch.error};
}

} // namespace textdump
} // namespace forensics
