#pragma once

#include "IFileExtractor.h"
#include <cstdint>
#include <filesystem>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <vector>
#include <tsk/libtsk.h>

struct FilesystemEvidenceEntry {
    std::string path;                 // relative to the partition's filesystem root
    std::uint64_t objectId = 0;
    std::uint64_t size = 0;
    std::int64_t mtime = 0, ctime = 0, atime = 0;
    bool directory = false;
    bool encrypted = false;
    bool compressed = false;
    std::string nameState = "clear";
};

struct FilesystemSourceMetadata {
    std::string imagePath;
    std::string containerType;
    std::string partitionName;
    int partitionNumber = 0;
    std::uint64_t partitionOffset = 0;
    std::string filesystemType;
    std::string reader;
    std::string readerVersion;
    std::uint64_t walkMilliseconds = 0;
    std::uint64_t indexedFiles = 0;
    std::uint64_t extractedFiles = 0;
    std::uint64_t bytesRead = 0;
    std::string error;
};

class IFilesystemEvidenceSource {
public:
    virtual ~IFilesystemEvidenceSource() = default;
    virtual bool initialize() = 0;
    virtual std::vector<FilesystemEvidenceEntry> list(const std::string& path) const = 0;
    virtual std::optional<FilesystemEvidenceEntry> stat(const std::string& path) const = 0;
    virtual bool exists(const std::string& path) const { return stat(path).has_value(); }
    virtual bool readFile(const std::string& path, std::vector<std::uint8_t>& bytes,
                          std::size_t limit = 64 * 1024 * 1024) = 0;
    virtual bool extractFileByPath(const std::string& path, const std::string& output) = 0;
    virtual std::string filesystemType() const = 0;
    virtual FilesystemSourceMetadata sourceMetadata() const = 0;
    virtual std::vector<std::string> regularPaths() const = 0;
    virtual std::vector<FilesystemEvidenceEntry> unavailableNames() const { return {}; }
};

class TskFilesystemEvidenceSource final : public IFilesystemEvidenceSource {
public:
    TskFilesystemEvidenceSource(std::string image, FilesystemSourceMetadata metadata);
    ~TskFilesystemEvidenceSource() override;
    bool initialize() override;
    std::vector<FilesystemEvidenceEntry> list(const std::string& path) const override;
    std::optional<FilesystemEvidenceEntry> stat(const std::string& path) const override;
    bool readFile(const std::string& path, std::vector<std::uint8_t>& bytes,
                  std::size_t limit) override;
    bool extractFileByPath(const std::string& path, const std::string& output) override;
    std::string filesystemType() const override { return "ext4"; }
    FilesystemSourceMetadata sourceMetadata() const override { return metadata_; }
    std::vector<std::string> regularPaths() const override;
    std::vector<FilesystemEvidenceEntry> unavailableNames() const override { return unknownNames_; }
private:
    static TSK_WALK_RET_ENUM walkCallback(TSK_FS_FILE*, const char*, void*);
    std::string image_;
    FilesystemSourceMetadata metadata_;
    TSK_IMG_INFO* imageHandle_ = nullptr;
    TSK_FS_INFO* filesystem_ = nullptr;
    std::map<std::string, FilesystemEvidenceEntry> entries_;
    std::vector<FilesystemEvidenceEntry> unknownNames_;
};

class F2fsFilesystemEvidenceSource final : public IFilesystemEvidenceSource {
public:
    F2fsFilesystemEvidenceSource(std::string image, FilesystemSourceMetadata metadata);
    bool initialize() override;
    std::vector<FilesystemEvidenceEntry> list(const std::string& path) const override;
    std::optional<FilesystemEvidenceEntry> stat(const std::string& path) const override;
    bool readFile(const std::string& path, std::vector<std::uint8_t>& bytes,
                  std::size_t limit) override;
    bool extractFileByPath(const std::string& path, const std::string& output) override;
    std::string filesystemType() const override { return "f2fs"; }
    FilesystemSourceMetadata sourceMetadata() const override { return metadata_; }
    std::vector<std::string> regularPaths() const override;
    std::vector<FilesystemEvidenceEntry> unavailableNames() const override { return unknownNames_; }
private:
    std::string image_;
    FilesystemSourceMetadata metadata_;
    std::map<std::string, FilesystemEvidenceEntry> entries_;
    std::vector<FilesystemEvidenceEntry> unknownNames_;
};

// Opens only a demonstrable Android userdata candidate, not an arbitrary ext4
// or F2FS partition. TSK is used for EXT4 and container/partition discovery;
// the pinned user-space reader handles F2FS content and EWF block views.
std::unique_ptr<IFilesystemEvidenceSource> openAndroidFilesystemImage(
    const std::string& image, std::string& error,
    std::optional<std::uint64_t> expectedOffset = std::nullopt);

class FilesystemEvidenceFileExtractor final : public IFileExtractor {
public:
    explicit FilesystemEvidenceFileExtractor(std::string image,
        std::optional<std::uint64_t> expectedOffset = std::nullopt);
    bool initialize() override;
    bool extractFileByPath(const std::string& path, const std::string& output) override;
    std::vector<std::string> findPathsByFilename(const std::string& filename,
                                                  std::size_t limit = 200) const override;
    std::vector<AndroidSourceProvenance> usedSourceProvenance() const override { return used_; }
    FilesystemSourceMetadata sourceMetadata() const;
    const std::string& errorCode() const { return error_; }
    void setSourceHash(std::string hash) { sourceHash_ = std::move(hash); }
    std::vector<FilesystemEvidenceEntry> entries() const;
private:
    std::string image_;
    std::string error_;
    std::string sourceHash_;
    std::optional<std::uint64_t> expectedOffset_;
    std::unique_ptr<IFilesystemEvidenceSource> source_;
    std::map<std::string, std::string> normalizedToSource_;
    std::vector<AndroidSourceProvenance> used_;
};
