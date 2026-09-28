#pragma once

#include "AndroidPathMapper.h"
#include "IFileExtractor.h"

#include <cstdint>
#include <map>
#include <optional>
#include <string>
#include <vector>
#include <utility>

enum class AndroidArchiveKind { Tar, SevenZip, AndroidBackup };

struct ArchiveCoverageEvent {
    std::string sourcePath;
    std::string normalizedPath;
    std::string status;
    std::string reason;
};

class ArchiveFileExtractor : public IFileExtractor {
public:
    ArchiveFileExtractor(std::string source, AndroidArchiveKind kind, std::string password = {});
    ~ArchiveFileExtractor() override;
    ArchiveFileExtractor(const ArchiveFileExtractor&) = delete;
    ArchiveFileExtractor& operator=(const ArchiveFileExtractor&) = delete;

    bool initialize() override;
    bool extractFileByPath(const std::string& androidRelativePath,
                           const std::string& outPath) override;
    std::vector<std::string> findPathsByFilename(
        const std::string& filename, std::size_t limit = 200) const override;
    std::vector<AndroidSourceProvenance> usedSourceProvenance() const override;
    std::vector<ArchiveCoverageEvent> coverageEvents() const;

    const std::string& errorCode() const { return errorCode_; }
    const AndroidPathMappingResult& rootMapping() const { return mapping_; }
    std::size_t memberCount() const { return memberCount_; }
    std::optional<std::uint64_t> statMember(const std::string& normalizedPath) const;
    std::size_t skippedLinkCount() const { return skippedLinks_; }
    bool passwordSupplied() const { return passwordSupplied_; }

private:
    struct Member { std::string sourcePath; std::uint64_t size = 0; };
    std::string source_;
    AndroidArchiveKind kind_;
    std::string password_;
    bool passwordSupplied_ = false;
    bool initialized_ = false;
    std::string errorCode_;
    std::string containerSha256_;
    AndroidPathMappingResult mapping_;
    std::map<std::string, Member> members_;
    std::vector<AndroidSourceProvenance> used_;
    std::map<std::string, ArchiveCoverageEvent> coverage_;
    std::size_t memberCount_ = 0;
    std::size_t skippedLinks_ = 0;
};

class TarArchiveExtractor final : public ArchiveFileExtractor {
public:
    explicit TarArchiveExtractor(const std::string& source)
        : ArchiveFileExtractor(source, AndroidArchiveKind::Tar) {}
};

class SevenZipArchiveExtractor final : public ArchiveFileExtractor {
public:
    SevenZipArchiveExtractor(const std::string& source, std::string password = {})
        : ArchiveFileExtractor(source, AndroidArchiveKind::SevenZip, std::move(password)) {}
};

class AndroidBackupExtractor final : public ArchiveFileExtractor {
public:
    AndroidBackupExtractor(const std::string& source, std::string password = {})
        : ArchiveFileExtractor(source, AndroidArchiveKind::AndroidBackup, std::move(password)) {}
};
