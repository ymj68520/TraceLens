#pragma once
#ifndef TEXT_DUMP_EXPORTER_H
#define TEXT_DUMP_EXPORTER_H

#include <cstdint>
#include <filesystem>
#include <optional>
#include <string>
#include <vector>
#include "DatabaseManager/DatabaseManagerDataTypes.h"

namespace forensics {
namespace textdump {

enum class OriginalStatus { Extracted, Reused, Failed, UnsafePath };
enum class MarkdownStatus { Converted, Reused, Skipped, Failed, ServiceError };
enum class StopReason { Completed, SizeLimitReached, ServiceUnavailable, OutputError };

struct FileDeltaResult {
    OriginalStatus status = OriginalStatus::Failed;
    std::filesystem::path output_path;
    uint64_t previous_bytes = 0;
    uint64_t output_bytes = 0;
    std::string error;
};

struct MarkdownDeltaResult {
    MarkdownStatus status = MarkdownStatus::Failed;
    std::filesystem::path output_path;
    uint64_t previous_bytes = 0;
    uint64_t output_bytes = 0;
    std::string error;
};

struct BatchConversionResult {
    bool ok = false;
    int total = 0;
    int converted = 0;
    int skipped = 0;
    int failed = 0;
    std::string error;
};

class ITextDumpFileSource {
public:
    virtual ~ITextDumpFileSource() = default;
    virtual bool initialize(std::string& error) = 0;
    virtual std::vector<FileRecord> listRegularFilesOrdered(std::string& error) = 0;
    virtual FileDeltaResult extractOne(const FileRecord& record,
                                       const std::filesystem::path& outputRoot) = 0;
    virtual int extractAll(const std::filesystem::path& outputRoot,
                           std::string& error) = 0;
};

class ITextDumpConverter {
public:
    virtual ~ITextDumpConverter() = default;
    virtual bool isAvailable() = 0;
    virtual MarkdownDeltaResult convertOne(
        const std::filesystem::path& inputRoot,
        const std::filesystem::path& inputFile,
        const std::filesystem::path& outputRoot,
        bool force) = 0;
    virtual BatchConversionResult convertBatch(
        const std::filesystem::path& inputRoot,
        const std::filesystem::path& outputRoot) = 0;
};

struct TextDumpOptions {
    std::filesystem::path original_root;
    std::filesystem::path markdown_root;
    std::optional<uint64_t> max_bytes;
    std::string task_id;  // task anchor for the Python conversion service (D2b)
};

struct TextDumpResult {
    StopReason stop_reason = StopReason::Completed;
    size_t candidate_files = 0;
    size_t processed_files = 0;
    size_t originals_extracted = 0;
    size_t originals_reused = 0;
    size_t originals_failed = 0;
    size_t markdown_converted = 0;
    size_t markdown_reused = 0;
    size_t markdown_skipped = 0;
    size_t markdown_failed = 0;
    uint64_t initial_bytes = 0;
    uint64_t final_bytes = 0;
    std::optional<uint64_t> max_bytes;
    bool truncated = false;
    std::string message;
};

class TextDumpExporter {
public:
    TextDumpExporter(ITextDumpFileSource& source, ITextDumpConverter& converter);
    TextDumpResult run(const TextDumpOptions& options);
    static std::optional<uint64_t> calculateUsage(
        const std::filesystem::path& originalRoot,
        const std::filesystem::path& markdownRoot,
        std::string& error);
    static std::string formatBytes(uint64_t bytes);

private:
    ITextDumpFileSource& source_;
    ITextDumpConverter& converter_;
};

} // namespace textdump
} // namespace forensics

#endif // TEXT_DUMP_EXPORTER_H
