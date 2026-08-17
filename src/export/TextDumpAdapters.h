#pragma once
#ifndef TEXT_DUMP_ADAPTERS_H
#define TEXT_DUMP_ADAPTERS_H

#include <filesystem>
#include <string>
#include <vector>
#include "TextDumpExporter.h"
#include "DatabaseManager/FileExtractor/FileExtractor.h"
#include "LLMIntegration/MarkitdownProxy.h"

namespace forensics {
namespace textdump {

// Production source adapter: bridges Task 4's FileExtractor atomic extraction
// API to the exporter's ITextDumpFileSource interface.
class FileExtractorTextDumpSource final : public ITextDumpFileSource {
public:
    FileExtractorTextDumpSource(std::string imagePath, std::string databasePath);
    bool initialize(std::string& error) override;
    std::vector<FileRecord> listRegularFilesOrdered(std::string& error) override;
    FileDeltaResult extractOne(const FileRecord& record,
                               const std::filesystem::path& outputRoot) override;
    int extractAll(const std::filesystem::path& outputRoot,
                   std::string& error) override;

private:
    FileExtractor extractor_;
};

// Production converter adapter: bridges Task 3's MarkitdownProxy to the
// exporter's ITextDumpConverter interface.
class MarkitdownTextDumpConverter final : public ITextDumpConverter {
public:
    explicit MarkitdownTextDumpConverter(forensics::llm::MarkitdownProxy& proxy,
                                        std::string taskId = "",
                                        std::string workspaceRoot = "");
    bool isAvailable() override;
    MarkdownDeltaResult convertOne(
        const std::filesystem::path& inputRoot,
        const std::filesystem::path& inputFile,
        const std::filesystem::path& outputRoot,
        bool force) override;
    BatchConversionResult convertBatch(
        const std::filesystem::path& inputRoot,
        const std::filesystem::path& outputRoot) override;

private:
    forensics::llm::MarkitdownProxy& proxy_;
    std::string task_id_;
    std::string workspace_root_;
};

} // namespace textdump
} // namespace forensics

#endif // TEXT_DUMP_ADAPTERS_H
