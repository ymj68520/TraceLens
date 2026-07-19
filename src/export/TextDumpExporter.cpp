#include "TextDumpExporter.h"

#include <algorithm>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <system_error>

namespace fs = std::filesystem;

namespace forensics {
namespace textdump {
namespace {

constexpr std::string_view kTempPrefix = ".tracelens-textdump-tmp-";

bool prepareRoot(const fs::path& root, std::string& error) {
    std::error_code ec;
    if (fs::exists(root, ec) &&
        fs::is_symlink(fs::symlink_status(root, ec))) {
        error = "Text dump root is a symlink: " + root.string();
        return false;
    }
    fs::create_directories(root, ec);
    if (ec || !fs::is_directory(root, ec)) {
        error = "Cannot prepare text dump root " + root.string() + ": " +
                ec.message();
        return false;
    }
    return true;
}

std::optional<uint64_t> scanRoot(const fs::path& root, std::string& error) {
    uint64_t total = 0;
    std::error_code ec;
    fs::recursive_directory_iterator it(
        root, fs::directory_options::skip_permission_denied, ec);
    fs::recursive_directory_iterator end;
    if (ec) {
        error = "Cannot scan " + root.string() + ": " + ec.message();
        return std::nullopt;
    }
    for (; it != end; it.increment(ec)) {
        if (ec) {
            error = "Cannot continue scanning " + root.string() + ": " +
                    ec.message();
            return std::nullopt;
        }
        const auto status = it->symlink_status(ec);
        if (ec) {
            error = "Cannot inspect " + it->path().string() + ": " +
                    ec.message();
            return std::nullopt;
        }
        if (fs::is_symlink(status)) {
            if (fs::is_directory(status)) it.disable_recursion_pending();
            continue;
        }
        if (!fs::is_regular_file(status)) continue;
        if (it->path().filename().string().starts_with(kTempPrefix)) {
            fs::remove(it->path(), ec);
            if (ec) {
                error = "Cannot remove stale text-dump temp file: " +
                        ec.message();
                return std::nullopt;
            }
            continue;
        }
        const uint64_t size = fs::file_size(it->path(), ec);
        if (ec || size > std::numeric_limits<uint64_t>::max() - total) {
            error = ec ? ec.message() : "Text dump usage overflows uint64_t";
            return std::nullopt;
        }
        total += size;
    }
    return total;
}

void applyDelta(uint64_t& usage, uint64_t before, uint64_t after) {
    usage -= std::min(usage, before);
    if (after > std::numeric_limits<uint64_t>::max() - usage) {
        throw std::overflow_error("Text dump usage overflows uint64_t");
    }
    usage += after;
}

} // namespace

TextDumpExporter::TextDumpExporter(ITextDumpFileSource& source,
                                   ITextDumpConverter& converter)
    : source_(source), converter_(converter) {}

std::optional<uint64_t> TextDumpExporter::calculateUsage(
    const fs::path& originalRoot,
    const fs::path& markdownRoot,
    std::string& error) {
    if (!prepareRoot(originalRoot, error)) return std::nullopt;
    if (!prepareRoot(markdownRoot, error)) return std::nullopt;
    const auto originalUsage = scanRoot(originalRoot, error);
    if (!originalUsage) return std::nullopt;
    const auto markdownUsage = scanRoot(markdownRoot, error);
    if (!markdownUsage) return std::nullopt;
    if (*markdownUsage > std::numeric_limits<uint64_t>::max() - *originalUsage) {
        error = "Text dump usage overflows uint64_t";
        return std::nullopt;
    }
    return *originalUsage + *markdownUsage;
}

std::string TextDumpExporter::formatBytes(uint64_t bytes) {
    static constexpr const char* units[] = {"B", "KiB", "MiB", "GiB", "TiB"};
    double value = static_cast<double>(bytes);
    size_t unit = 0;
    while (value >= 1024.0 && unit < 4) {
        value /= 1024.0;
        ++unit;
    }
    std::ostringstream out;
    out << std::fixed << std::setprecision(unit == 0 ? 0 : 1)
        << value << ' ' << units[unit];
    return out.str();
}

TextDumpResult TextDumpExporter::run(const TextDumpOptions& options) {
    TextDumpResult result;
    result.max_bytes = options.max_bytes;

    try {
        if (!converter_.isAvailable()) {
            result.stop_reason = StopReason::ServiceUnavailable;
            result.message = "Markdown converter service is unavailable";
            return result;
        }

        if (!options.max_bytes.has_value()) {
            std::string error;
            if (!source_.initialize(error)) {
                result.stop_reason = StopReason::OutputError;
                result.message = error;
                return result;
            }
            const int extracted =
                source_.extractAll(options.original_root, error);
            if (extracted < 0) {
                result.stop_reason = StopReason::OutputError;
                result.message = error;
                return result;
            }
            const auto batch = converter_.convertBatch(
                options.original_root, options.markdown_root);
            result.candidate_files = static_cast<size_t>(batch.total);
            result.processed_files = static_cast<size_t>(batch.total);
            result.originals_extracted = static_cast<size_t>(extracted);
            result.markdown_converted = static_cast<size_t>(batch.converted);
            result.markdown_skipped = static_cast<size_t>(batch.skipped);
            result.markdown_failed = static_cast<size_t>(batch.failed);
            if (!batch.ok) {
                result.stop_reason = StopReason::ServiceUnavailable;
                result.message = batch.error;
            }
            std::string usageError;
            const auto usage = calculateUsage(
                options.original_root, options.markdown_root, usageError);
            if (usage) {
                result.initial_bytes = result.final_bytes = *usage;
            }
            return result;
        }

        std::string usageError;
        const auto usage = calculateUsage(
            options.original_root, options.markdown_root, usageError);
        if (!usage) {
            result.stop_reason = StopReason::OutputError;
            result.message = usageError;
            return result;
        }
        result.initial_bytes = result.final_bytes = *usage;

        if (result.initial_bytes >= *options.max_bytes) {
            result.truncated = true;
            result.stop_reason = StopReason::SizeLimitReached;
            result.message =
                "size limit reached; completed files were preserved";
            return result;
        }

        std::string initError;
        if (!source_.initialize(initError)) {
            result.stop_reason = StopReason::OutputError;
            result.message = initError;
            return result;
        }
        std::string listError;
        auto records = source_.listRegularFilesOrdered(listError);
        result.candidate_files = records.size();

        uint64_t current = result.initial_bytes;
        for (const auto& fileRecord : records) {
            if (current >= *options.max_bytes) {
                result.truncated = true;
                result.stop_reason = StopReason::SizeLimitReached;
                result.message =
                    "size limit reached; completed files were preserved";
                break;
            }
            ++result.processed_files;
            const auto original =
                source_.extractOne(fileRecord, options.original_root);
            switch (original.status) {
                case OriginalStatus::Extracted:
                    ++result.originals_extracted;
                    break;
                case OriginalStatus::Reused:
                    ++result.originals_reused;
                    break;
                case OriginalStatus::Failed:
                case OriginalStatus::UnsafePath:
                    ++result.originals_failed;
                    continue;
            }
            applyDelta(current, original.previous_bytes, original.output_bytes);

            const auto markdown = converter_.convertOne(
                options.original_root,
                original.output_path,
                options.markdown_root,
                original.status == OriginalStatus::Extracted);
            switch (markdown.status) {
                case MarkdownStatus::Converted:
                    ++result.markdown_converted;
                    break;
                case MarkdownStatus::Reused:
                    ++result.markdown_reused;
                    break;
                case MarkdownStatus::Skipped:
                    ++result.markdown_skipped;
                    break;
                case MarkdownStatus::Failed:
                    ++result.markdown_failed;
                    break;
                case MarkdownStatus::ServiceError:
                    ++result.markdown_failed;
                    applyDelta(current, markdown.previous_bytes,
                               markdown.output_bytes);
                    result.final_bytes = current;
                    result.stop_reason = StopReason::ServiceUnavailable;
                    result.message = markdown.error;
                    return result;
            }
            applyDelta(current, markdown.previous_bytes, markdown.output_bytes);
            result.final_bytes = current;
        }

        // After the loop, set SizeLimitReached only if unprocessed candidates
        // remain AND usage is at/above the limit. The active file was allowed
        // to push final usage over the limit.
        if (result.processed_files < result.candidate_files &&
            current >= *options.max_bytes) {
            result.truncated = true;
            result.stop_reason = StopReason::SizeLimitReached;
            result.message =
                "size limit reached; completed files were preserved";
        }
        return result;
    } catch (const std::exception& ex) {
        // Preserve the last computed final_bytes; surface the failure message.
        result.stop_reason = StopReason::OutputError;
        result.message = ex.what();
        return result;
    }
}

} // namespace textdump
} // namespace forensics
